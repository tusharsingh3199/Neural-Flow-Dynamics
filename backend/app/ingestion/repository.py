from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ingestion.core import IngestionInsertResult, IngestionManifest
from app.ingestion.database import IngestionManifestRow


class ManifestRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def insert(self, manifest: IngestionManifest) -> IngestionInsertResult:
        row = IngestionManifestRow(
            idempotency_key=manifest.idempotency_key,
            source_id=manifest.source_id,
            product=manifest.product,
            variable=manifest.variable,
            unit=manifest.unit,
            product_class=manifest.product_class.value,
            storage_uri=manifest.storage_uri,
            init_time=manifest.init_time,
            lead_time_hours=manifest.lead_time_hours,
            source_run_id=manifest.source_run_id,
            valid_time=manifest.valid_time,
            grid=manifest.grid.model_dump(mode="json") if manifest.grid else None,
            dataset_metadata=manifest.dataset_metadata,
            ingested_at=manifest.ingested_at,
            checksum=manifest.checksum,
            status=manifest.status.value,
            provenance=manifest.provenance.model_dump(mode="json"),
            validation_errors=manifest.validation_errors,
        )
        with Session(self._engine) as session:
            existing = session.scalar(
                select(IngestionManifestRow.id).where(
                    IngestionManifestRow.idempotency_key == manifest.idempotency_key
                )
            )
            if existing is not None:
                return IngestionInsertResult.DUPLICATE
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(IngestionManifestRow.id).where(
                        IngestionManifestRow.idempotency_key == manifest.idempotency_key
                    )
                )
                if existing is not None:
                    return IngestionInsertResult.DUPLICATE
                raise
        return IngestionInsertResult.INSERTED

    @staticmethod
    def _to_manifest(row: IngestionManifestRow) -> IngestionManifest:
        init_time = row.init_time
        valid_time = row.valid_time
        ingested_at = row.ingested_at
        if init_time is not None and init_time.tzinfo is None:
            init_time = init_time.replace(tzinfo=UTC)
        if valid_time.tzinfo is None:
            valid_time = valid_time.replace(tzinfo=UTC)
        if ingested_at.tzinfo is None:
            ingested_at = ingested_at.replace(tzinfo=UTC)
        provenance = row.provenance.copy()
        for field in ("retrieved_at", "ingested_at"):
            value = datetime.fromisoformat(provenance[field])
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            provenance[field] = value
        return IngestionManifest.model_validate(
            {
                "idempotency_key": row.idempotency_key,
                "source_id": row.source_id,
                "product": row.product,
                "variable": row.variable,
                "unit": row.unit,
                "product_class": row.product_class,
                "storage_uri": row.storage_uri,
                "init_time": init_time,
                "lead_time_hours": row.lead_time_hours,
                "source_run_id": row.source_run_id,
                "valid_time": valid_time,
                "grid": row.grid,
                "dataset_metadata": row.dataset_metadata,
                "ingested_at": ingested_at,
                "checksum": row.checksum,
                "status": row.status,
                "provenance": provenance,
                "validation_errors": row.validation_errors,
            }
        )

    def list_accepted(
        self,
        *,
        source_id: str | None = None,
        product: str | None = None,
        variable: str | None = None,
    ) -> list[IngestionManifest]:
        statement = select(IngestionManifestRow).where(IngestionManifestRow.status == "accepted")
        if source_id is not None:
            statement = statement.where(IngestionManifestRow.source_id == source_id)
        if product is not None:
            statement = statement.where(IngestionManifestRow.product == product)
        if variable is not None:
            statement = statement.where(IngestionManifestRow.variable == variable)
        statement = statement.order_by(
            IngestionManifestRow.valid_time,
            IngestionManifestRow.ingested_at,
        )
        with Session(self._engine) as session:
            rows = session.scalars(statement).all()
        return [self._to_manifest(row) for row in rows]

    def find_latest_accepted(
        self,
        *,
        source_id: str,
        product: str,
        variable: str,
        valid_time: datetime,
        init_time: datetime | None = None,
    ) -> IngestionManifest | None:
        statement = select(IngestionManifestRow).where(
            IngestionManifestRow.status == "accepted",
            IngestionManifestRow.source_id == source_id,
            IngestionManifestRow.product == product,
            IngestionManifestRow.variable == variable,
            IngestionManifestRow.valid_time == valid_time,
        )
        if init_time is not None:
            statement = statement.where(IngestionManifestRow.init_time == init_time)
        statement = statement.order_by(IngestionManifestRow.ingested_at.desc()).limit(1)
        with Session(self._engine) as session:
            row = session.scalar(statement)
        return self._to_manifest(row) if row is not None else None
