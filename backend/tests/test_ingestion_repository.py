from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine

from app.contracts import ProductClass, Provenance
from app.ingestion.core import (
    DatasetDescription,
    DatasetValidationSpec,
    GeographicBounds,
    IngestionManifest,
    IngestionStatus,
    VariableDescription,
    make_idempotency_key,
)
from app.ingestion.database import Base, IngestionManifestRow
from app.ingestion.repository import ManifestRepository
from app.ingestion.runner import run_ingestion

NOW = datetime(2026, 10, 15, tzinfo=UTC)
BOUNDS = GeographicBounds(
    minimum_latitude=5,
    maximum_latitude=30,
    minimum_longitude=60,
    maximum_longitude=100,
)


class FixtureAdapter:
    source_id = "fixture-source"
    product = "wind"
    product_class = ProductClass.NUMERICAL_FORECAST
    source_url = "https://example.org/fixture"
    licence = "fixture licence"
    transformation_history: tuple[str, ...] = ()
    validation_spec = DatasetValidationSpec(
        required_variables={
            "u10": VariableDescription(
                unit="m s**-1",
                dimensions=("time", "latitude", "longitude"),
            )
        },
        required_bounds=BOUNDS,
    )

    def __init__(self, path: Path, *, valid_unit: bool = True) -> None:
        self.path = path
        self.valid_unit = valid_unit

    def fetch(self) -> Path:
        return self.path

    def inspect(self, path: Path) -> DatasetDescription:
        unit = "m s**-1" if self.valid_unit else "kn"
        return DatasetDescription(
            retrieved_at=NOW,
            init_time=NOW,
            valid_times=[datetime(2026, 10, 15, 6, tzinfo=UTC)],
            variables={
                "u10": VariableDescription(
                    unit=unit,
                    dimensions=("time", "latitude", "longitude"),
                )
            },
            geographic_bounds=BOUNDS,
            missing_fraction_by_variable={"u10": 0},
        )


def create_repository() -> tuple[ManifestRepository, Engine]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return ManifestRepository(engine), engine


def test_manifest_insert_is_idempotent_for_same_product(tmp_path: Path) -> None:
    artifact = tmp_path / "field.bin"
    artifact.write_bytes(b"valid forecast data")
    repository, engine = create_repository()
    adapter = FixtureAdapter(artifact)

    first = run_ingestion(adapter, engine)
    second = run_ingestion(adapter, engine)

    assert first.status == "accepted"
    assert first.records_inserted == 1
    assert second.records_inserted == 0
    assert second.records_unchanged == 1
    with engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(IngestionManifestRow))
    assert count == 1
    engine.dispose()


def test_invalid_new_version_is_quarantined_without_overwriting_valid(tmp_path: Path) -> None:
    artifact = tmp_path / "field.bin"
    artifact.write_bytes(b"first valid version")
    repository, engine = create_repository()
    accepted = run_ingestion(FixtureAdapter(artifact), engine)
    artifact.write_bytes(b"second invalid version")
    quarantined = run_ingestion(FixtureAdapter(artifact, valid_unit=False), engine)

    assert accepted.status == "accepted"
    assert quarantined.status == "quarantined"
    latest_accepted = repository.find_latest_accepted(
        source_id="fixture-source",
        product="wind",
        variable="u10",
        valid_time=datetime(2026, 10, 15, 6, tzinfo=UTC),
        init_time=NOW,
    )
    assert latest_accepted is not None
    assert latest_accepted.checksum == accepted.checksum
    with engine.connect() as connection:
        statuses = list(
            connection.scalars(
                select(IngestionManifestRow.status).order_by(IngestionManifestRow.id)
            )
        )
    assert sorted(statuses) == ["accepted", "quarantined"]
    engine.dispose()


def test_manifest_rejects_mismatched_provenance_checksum() -> None:
    checksum = "sha256:" + "a" * 64
    different_checksum = "sha256:" + "b" * 64
    provenance = Provenance(
        source_id="fixture-source",
        source_url="https://example.org/fixture",
        licence="fixture licence",
        retrieved_at=NOW,
        ingested_at=NOW,
        checksum=checksum,
    )
    with pytest.raises(ValidationError, match="provenance checksum"):
        IngestionManifest(
            idempotency_key=make_idempotency_key(
                source_id="fixture-source",
                product="wind",
                init_time=NOW,
                valid_time=datetime(2026, 10, 15, 6, tzinfo=UTC),
                checksum=different_checksum,
            ),
            source_id="fixture-source",
            product="wind",
            variable="u10",
            unit="m s**-1",
            product_class=ProductClass.NUMERICAL_FORECAST,
            storage_uri="file:///tmp/field.bin",
            init_time=NOW,
            valid_time=datetime(2026, 10, 15, 6, tzinfo=UTC),
            ingested_at=NOW,
            checksum=different_checksum,
            status=IngestionStatus.ACCEPTED,
            provenance=provenance,
        )
