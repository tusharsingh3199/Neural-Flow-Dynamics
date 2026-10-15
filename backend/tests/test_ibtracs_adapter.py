from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from app.ingestion.ibtracs import IBTracsNorthIndianAdapter
from app.ingestion.database import Base
from app.ingestion.track_repository import TrackRepository
from sqlalchemy import create_engine

HEADER = [
    "SID",
    "SEASON",
    "NUMBER",
    "BASIN",
    "SUBBASIN",
    "NAME",
    "ISO_TIME",
    "TRACK_TYPE",
    "LAT",
    "LON",
    "WMO_WIND",
    "WMO_PRES",
    "WMO_AGENCY",
    "NEWDELHI_WIND",
]
UNITS = [
    "",
    "Year",
    "",
    "",
    "",
    "",
    "",
    "",
    "degrees_north",
    "degrees_east",
    "kts",
    "mb",
    "",
    "kts",
]


def write_fixture(path: Path) -> None:
    rows = [
        HEADER,
        UNITS,
        [
            "2023TEST",
            "2023",
            "1",
            "NI",
            "BB",
            "TESTSTORM",
            "2023-06-15 00:00:00",
            "main",
            "12.5",
            "200.0",
            " ",
            " ",
            " ",
            "45",
        ],
        [
            "2023TEST",
            "2023",
            "1",
            "NI",
            "BB",
            "TESTSTORM",
            "2023-06-15 06:00:00",
            "main",
            "13.0",
            "80.0",
            "60",
            "980",
            "IMD",
            "55",
        ],
    ]
    path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")


def test_ibtracs_parser_preserves_blanks_agencies_and_units(tmp_path: Path) -> None:
    source_path = tmp_path / "ibtracs.NI.fixture.csv"
    write_fixture(source_path)
    units = IBTracsNorthIndianAdapter.read_units(source_path)

    points = list(IBTracsNorthIndianAdapter.iter_points(source_path, units))

    assert units["LAT"] == "degrees_north"
    assert units["WMO_WIND"] == "kts"
    assert points[0].valid_time == datetime(2023, 6, 15, tzinfo=UTC)
    assert points[0].latitude == 12.5
    assert points[0].longitude == -160
    assert points[0].raw_fields["LON"] == "200.0"
    assert points[0].wmo_wind is None
    assert points[0].newdelhi_wind == 45
    assert points[0].newdelhi_wind_unit == "kts"
    assert points[1].wmo_agency == "IMD"
    assert points[1].wmo_wind == 60


def test_ibtracs_parser_preserves_basin_changes_within_north_indian_subset(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "ibtracs.NI.fixture.csv"
    write_fixture(source_path)
    contents = source_path.read_text(encoding="utf-8").replace("2023,1,NI,", "2023,1,WP,")
    source_path.write_text(contents, encoding="utf-8")
    units = IBTracsNorthIndianAdapter.read_units(source_path)

    points = list(IBTracsNorthIndianAdapter.iter_points(source_path, units))

    assert points[0].basin == "WP"
    assert points[0].raw_fields["BASIN"] == "WP"


def test_ibtracs_description_records_citation_and_file_provenance(tmp_path: Path) -> None:
    source_path = tmp_path / "ibtracs.NI.fixture.csv"
    write_fixture(source_path)
    adapter = IBTracsNorthIndianAdapter(tmp_path)

    description = adapter.describe(
        source_path,
        "sha256:" + "a" * 64,
        datetime(2026, 10, 15, tzinfo=UTC),
    )

    assert description.record_count == 2
    assert "doi:10.25921/82ty-9e16" in description.citation
    assert "terms are confirmed" in description.licence_note


def test_ibtracs_repository_streams_points_and_deduplicates(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "ibtracs.NI.fixture.csv"
    write_fixture(source_path)
    checksum = f"sha256:{sha256(source_path.read_bytes()).hexdigest()}"
    retrieved_at = datetime(2026, 10, 15, tzinfo=UTC)
    adapter = IBTracsNorthIndianAdapter(tmp_path)
    monkeypatch.setattr(adapter, "fetch", lambda: (source_path, checksum, retrieved_at))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = TrackRepository(engine, batch_size=1)

    dataset, inserted = adapter.ingest(repository)
    duplicate_dataset, duplicate_inserted = adapter.ingest(repository)

    assert dataset.record_count == 2
    assert inserted is True
    assert duplicate_dataset.checksum == dataset.checksum
    assert duplicate_inserted is False
    storms = repository.list_storms()
    assert storms[0]["sid"] == "2023TEST"
    assert storms[0]["point_count"] == 2
    track_result = repository.get_track("2023TEST")
    assert track_result is not None
    track_metadata, points = track_result
    assert track_metadata.basin == "NI"
    assert points[0].wmo_wind is None
    assert points[0].newdelhi_wind == 45
    assert points[0].longitude == -160
    engine.dispose()