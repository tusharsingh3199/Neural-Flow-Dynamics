"""Add per-variable and grid metadata needed by the data catalogue."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_field_catalogue_metadata"
down_revision: str | None = "0001_ingestion_manifest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_manifest", sa.Column("variable", sa.String(length=200)))
    op.add_column("ingestion_manifest", sa.Column("unit", sa.String(length=100)))
    op.add_column("ingestion_manifest", sa.Column("lead_time_hours", sa.Float()))
    op.add_column("ingestion_manifest", sa.Column("source_run_id", sa.String(length=200)))
    op.add_column("ingestion_manifest", sa.Column("grid", sa.JSON()))
    op.add_column("ingestion_manifest", sa.Column("dataset_metadata", sa.JSON()))
    op.execute(
        "UPDATE ingestion_manifest "
        "SET variable = 'unknown', unit = '1', dataset_metadata = '{}' "
        "WHERE variable IS NULL OR unit IS NULL OR dataset_metadata IS NULL"
    )
    op.alter_column("ingestion_manifest", "variable", nullable=False)
    op.alter_column("ingestion_manifest", "unit", nullable=False)
    op.alter_column("ingestion_manifest", "dataset_metadata", nullable=False)
    op.create_index(
        "ix_ingestion_manifest_catalogue",
        "ingestion_manifest",
        ["source_id", "product", "variable", "status", "valid_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_manifest_catalogue", table_name="ingestion_manifest")
    op.drop_column("ingestion_manifest", "dataset_metadata")
    op.drop_column("ingestion_manifest", "grid")
    op.drop_column("ingestion_manifest", "source_run_id")
    op.drop_column("ingestion_manifest", "lead_time_hours")
    op.drop_column("ingestion_manifest", "unit")
    op.drop_column("ingestion_manifest", "variable")