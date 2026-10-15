"""Create the idempotent ingestion manifest table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_ingestion_manifest"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_manifest",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("product", sa.String(length=200), nullable=False),
        sa.Column("product_class", sa.String(length=32), nullable=False),
        sa.Column("storage_uri", sa.String(length=2048), nullable=False),
        sa.Column("init_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum", sa.String(length=71), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_ingestion_manifest_idempotency_key"),
    )
    op.create_index("ix_ingestion_manifest_source_id", "ingestion_manifest", ["source_id"])
    op.create_index("ix_ingestion_manifest_valid_time", "ingestion_manifest", ["valid_time"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_manifest_valid_time", table_name="ingestion_manifest")
    op.drop_index("ix_ingestion_manifest_source_id", table_name="ingestion_manifest")
    op.drop_table("ingestion_manifest")
