from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, HttpUrl, TypeAdapter
from sqlalchemy import Engine

from app.contracts import Provenance
from app.ingestion.core import (
    DatasetDescription,
    IngestionInsertResult,
    IngestionManifest,
    IngestionStatus,
    SourceAdapter,
    compute_sha256,
    make_idempotency_key,
    retry_with_backoff,
    validate_dataset,
)
from app.ingestion.repository import ManifestRepository

HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class IngestionReport(BaseModel):
    source_id: str
    product: str
    status: Literal["accepted", "quarantined"]
    checksum: str
    validation_errors: list[str]
    records_inserted: int
    records_unchanged: int


def _build_manifest(
    adapter: SourceAdapter,
    path: Path,
    dataset: DatasetDescription,
    valid_time: datetime,
    checksum: str,
    variable: str,
    ingested_at: datetime,
    validation_errors: list[str],
) -> IngestionManifest:
    status = IngestionStatus.QUARANTINED if validation_errors else IngestionStatus.ACCEPTED
    provenance = Provenance(
        source_id=adapter.source_id,
        source_url=HTTP_URL_ADAPTER.validate_python(adapter.source_url),
        licence=adapter.licence,
        retrieved_at=dataset.retrieved_at,
        ingested_at=ingested_at,
        checksum=checksum,
        transformation_history=list(adapter.transformation_history),
    )
    return IngestionManifest(
        idempotency_key=make_idempotency_key(
            source_id=adapter.source_id,
            product=adapter.product,
            init_time=dataset.init_time,
            valid_time=valid_time,
            checksum=checksum,
            variable=variable,
        ),
        source_id=adapter.source_id,
        product=adapter.product,
        variable=variable,
        unit=dataset.variables[variable].unit,
        product_class=adapter.product_class,
        storage_uri=path.resolve().as_uri(),
        init_time=dataset.init_time,
        lead_time_hours=(valid_time - dataset.init_time).total_seconds() / 3600
        if dataset.init_time
        else None,
        source_run_id=dataset.source_run_id,
        valid_time=valid_time,
        grid=dataset.grid,
        dataset_metadata=dataset.model_dump(mode="json"),
        ingested_at=ingested_at,
        checksum=checksum,
        status=status,
        provenance=provenance,
        validation_errors=validation_errors,
    )


def run_ingestion(adapter: SourceAdapter, engine: Engine) -> IngestionReport:
    path = retry_with_backoff(adapter.fetch)
    if not path.is_file():
        raise FileNotFoundError(f"adapter {adapter.source_id!r} did not produce a file")
    checksum = compute_sha256(path)
    dataset = adapter.inspect(path)
    errors = validate_dataset(dataset, adapter.validation_spec)
    ingested_at = datetime.now(UTC)
    repository = ManifestRepository(engine)
    inserted = 0
    unchanged = 0
    for valid_time in dataset.valid_times:
        for variable in dataset.variables:
            manifest = _build_manifest(
                adapter,
                path,
                dataset,
                valid_time,
                checksum,
                variable,
                ingested_at,
                errors,
            )
            result = repository.insert(manifest)
            if result is IngestionInsertResult.INSERTED:
                inserted += 1
            else:
                unchanged += 1
    return IngestionReport(
        source_id=adapter.source_id,
        product=adapter.product,
        status="quarantined" if errors else "accepted",
        checksum=checksum,
        validation_errors=errors,
        records_inserted=inserted,
        records_unchanged=unchanged,
    )
