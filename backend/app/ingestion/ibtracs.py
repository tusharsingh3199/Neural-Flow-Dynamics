import csv
from datetime import UTC, datetime
from hashlib import sha256
import os
from pathlib import Path
import tempfile
from collections.abc import Iterator
from urllib.request import Request, urlopen

from app.ingestion.tracks import (
    TrackDataset,
    TrackPoint,
    normalize_longitude,
    parse_optional_float,
    parse_track_time,
)
from app.ingestion.track_repository import TrackRepository

IBTRACS_NI_CSV_URL = (
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
    "stewardship-ibtracs/v04r01/access/csv/ibtracs.NI.list.v04r01.csv"
)
IBTRACS_REQUIRED_COLUMNS = ("SID", "SEASON", "BASIN", "ISO_TIME", "LAT", "LON")
IBTRACS_CITATION = (
    "Gahtan et al. (2024), International Best Track Archive for Climate Stewardship "
    "(IBTrACS) Project, Version 4r01, North Indian subset, NOAA NCEI, "
    "doi:10.25921/82ty-9e16; access date is recorded per ingest. Also cite Knapp et al. "
    "(2010), BAMS 91, 363-376, doi:10.1175/2009BAMS2755.1."
)
IBTRACS_LICENCE_NOTE = (
    "The NCEI product page gives citation requirements but no standard licence "
    "identifier was verified. Keep the source file local and do not redistribute it "
    "until applicable reuse terms are confirmed."
)


class IBTracsNorthIndianAdapter:
    source_id = "ibtracs_north_indian_v04r01"
    source_url = IBTRACS_NI_CSV_URL

    def __init__(self, output_root: Path, *, timeout_seconds: int = 60) -> None:
        self.output_root = output_root
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> tuple[Path, str, datetime]:
        self.output_root.mkdir(parents=True, exist_ok=True)
        request = Request(
            self.source_url,
            headers={"User-Agent": "Neural-Flow-Dynamics research data client"},
        )
        retrieved_at = datetime.now(UTC)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="ibtracs-",
            suffix=".csv.part",
            dir=self.output_root,
        )
        temporary_path = Path(temporary_name)
        try:
            digest = sha256()
            with os.fdopen(descriptor, "wb") as temporary:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    while block := response.read(1024 * 1024):
                        temporary.write(block)
                        digest.update(block)
            checksum = f"sha256:{digest.hexdigest()}"
            destination = self.output_root / f"ibtracs.NI.v04r01.{digest.hexdigest()}.csv"
            if destination.exists():
                temporary_path.unlink()
            else:
                os.replace(temporary_path, destination)
            return destination, checksum, retrieved_at
        except (OSError, TimeoutError):
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def read_units(path: Path) -> dict[str, str | None]:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file)
            header = next(reader, None)
            unit_row = next(reader, None)
            if header is None or unit_row is None:
                raise ValueError("IBTrACS CSV must contain a header and a units row")
            if len(header) != len(unit_row):
                raise ValueError("IBTrACS header and units row have different column counts")
            missing = sorted(set(IBTRACS_REQUIRED_COLUMNS) - set(header))
            if missing:
                raise ValueError(f"IBTrACS CSV is missing required columns: {missing}")
            field_units = {
                name: (unit.strip() or None)
                for name, unit in zip(header, unit_row, strict=True)
            }
            return field_units

    @staticmethod
    def iter_points(
        path: Path,
        field_units: dict[str, str | None],
    ) -> Iterator[TrackPoint]:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file)
            header = next(reader, None)
            unit_row = next(reader, None)
            if header is None or unit_row is None or len(header) != len(unit_row):
                raise ValueError("IBTrACS CSV must contain matching header and units rows")
            required_units = {
                name: (unit.strip() or None)
                for name, unit in zip(header, unit_row, strict=True)
            }
            if required_units != field_units:
                raise ValueError("IBTrACS units row changed between metadata and record reads")
            missing = sorted(set(IBTRACS_REQUIRED_COLUMNS) - set(header))
            if missing:
                raise ValueError(f"IBTrACS CSV is missing required columns: {missing}")
            for row_number, row in enumerate(reader, start=3):
                if not row or all(not value.strip() for value in row):
                    continue
                if len(row) != len(header):
                    raise ValueError(
                        f"IBTrACS row {row_number} has {len(row)} columns; "
                        f"expected {len(header)}"
                    )
                raw_fields = {
                    name: (value.strip() or None)
                    for name, value in zip(header, row, strict=True)
                }
                basin = raw_fields["BASIN"]
                yield TrackPoint(
                        sid=raw_fields["SID"] or "",
                        season=int(raw_fields["SEASON"] or "0"),
                        basin=basin,
                        subbasin=raw_fields.get("SUBBASIN"),
                        name=raw_fields.get("NAME"),
                        valid_time=parse_track_time(raw_fields.get("ISO_TIME")),
                        latitude=parse_optional_float(raw_fields.get("LAT"), field_name="LAT"),
                        longitude=normalize_longitude(
                            parse_optional_float(raw_fields.get("LON"), field_name="LON")
                        ),
                        track_type=raw_fields.get("TRACK_TYPE"),
                        wmo_wind=parse_optional_float(
                            raw_fields.get("WMO_WIND"), field_name="WMO_WIND"
                        ),
                        wmo_wind_unit=field_units.get("WMO_WIND"),
                        wmo_pressure=parse_optional_float(
                            raw_fields.get("WMO_PRES"), field_name="WMO_PRES"
                        ),
                        wmo_pressure_unit=field_units.get("WMO_PRES"),
                        wmo_agency=raw_fields.get("WMO_AGENCY"),
                        newdelhi_wind=parse_optional_float(
                            raw_fields.get("NEWDELHI_WIND"), field_name="NEWDELHI_WIND"
                        ),
                        newdelhi_wind_unit=field_units.get("NEWDELHI_WIND"),
                        newdelhi_pressure=parse_optional_float(
                            raw_fields.get("NEWDELHI_PRES"), field_name="NEWDELHI_PRES"
                        ),
                        newdelhi_pressure_unit=field_units.get("NEWDELHI_PRES"),
                        raw_fields=raw_fields,
                        field_units=field_units,
                    )

    def describe(self, path: Path, checksum: str, retrieved_at: datetime) -> TrackDataset:
        field_units = self.read_units(path)
        record_count = sum(1 for _ in self.iter_points(path, field_units))
        if record_count == 0:
            raise ValueError("IBTrACS CSV contains no track points")
        return TrackDataset(
            source_url=self.source_url,
            retrieved_at=retrieved_at,
            ingested_at=datetime.now(UTC),
            checksum=checksum,
            data_uri=path.resolve().as_uri(),
            citation=TrackDataset.citation_text(retrieved_at),
            licence_note=IBTRACS_LICENCE_NOTE,
            field_units=field_units,
            record_count=record_count,
        )

    def ingest(self, repository: TrackRepository) -> tuple[TrackDataset, bool]:
        path, checksum, retrieved_at = self.fetch()
        field_units = self.read_units(path)
        record_count = sum(1 for _ in self.iter_points(path, field_units))
        dataset = TrackDataset(
            source_url=self.source_url,
            retrieved_at=retrieved_at,
            ingested_at=datetime.now(UTC),
            checksum=checksum,
            data_uri=path.resolve().as_uri(),
            citation=TrackDataset.citation_text(retrieved_at),
            licence_note=IBTRACS_LICENCE_NOTE,
            field_units=field_units,
            record_count=record_count,
        )
        inserted = repository.insert(dataset, self.iter_points(path, field_units))
        return dataset, inserted