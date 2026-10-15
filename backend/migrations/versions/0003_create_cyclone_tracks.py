"""Create provenance and point tables for historical cyclone tracks."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_cyclone_tracks"
down_revision: str | None = "0002_field_catalogue_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "track_dataset",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("basin", sa.String(length=2), nullable=False),
        sa.Column("checksum", sa.String(length=71), nullable=False),
        sa.Column("data_uri", sa.String(length=2048), nullable=False),
        sa.Column("licence_note", sa.String(length=2048), nullable=False),
        sa.Column("citation", sa.String(length=2048), nullable=False),
        sa.Column("field_units", sa.JSON(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checksum", name="uq_track_dataset_checksum"),
    )
    op.create_table(
        "cyclone_track_point",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("sid", sa.String(length=32), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("basin", sa.String(length=2), nullable=False),
        sa.Column("subbasin", sa.String(length=8), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("valid_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("track_type", sa.String(length=32), nullable=True),
        sa.Column("wmo_wind", sa.Float(), nullable=True),
        sa.Column("wmo_wind_unit", sa.String(length=32), nullable=True),
        sa.Column("wmo_pressure", sa.Float(), nullable=True),
        sa.Column("wmo_pressure_unit", sa.String(length=32), nullable=True),
        sa.Column("wmo_agency", sa.String(length=32), nullable=True),
        sa.Column("newdelhi_wind", sa.Float(), nullable=True),
        sa.Column("newdelhi_wind_unit", sa.String(length=32), nullable=True),
        sa.Column("newdelhi_pressure", sa.Float(), nullable=True),
        sa.Column("newdelhi_pressure_unit", sa.String(length=32), nullable=True),
        sa.Column("raw_fields", sa.JSON(), nullable=False),
        sa.Column("field_units", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["track_dataset.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cyclone_track_sid_time",
        "cyclone_track_point",
        ["sid", "valid_time"],
    )
    op.create_index(
        "ix_cyclone_track_basin_time",
        "cyclone_track_point",
        ["basin", "valid_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_cyclone_track_basin_time", table_name="cyclone_track_point")
    op.drop_index("ix_cyclone_track_sid_time", table_name="cyclone_track_point")
    op.drop_table("cyclone_track_point")
    op.drop_table("track_dataset")