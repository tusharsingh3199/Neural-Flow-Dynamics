from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Float, ForeignKey, Index, Integer, JSON, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IngestionManifestRow(Base):
    __tablename__ = "ingestion_manifest"
    __table_args__ = (Index("ix_ingestion_manifest_valid_time", "valid_time"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    variable: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(100), nullable=False)
    product_class: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    init_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lead_time_hours: Mapped[float | None] = mapped_column(nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    valid_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grid: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    dataset_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum: Mapped[str] = mapped_column(String(71), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class TrackDatasetRow(Base):
    __tablename__ = "track_dataset"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    basin: Mapped[str] = mapped_column(String(2), nullable=False)
    checksum: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    data_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    licence_note: Mapped[str] = mapped_column(String(2048), nullable=False)
    citation: Mapped[str] = mapped_column(String(2048), nullable=False)
    field_units: Mapped[dict[str, str | None]] = mapped_column(JSON, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CycloneTrackPointRow(Base):
    __tablename__ = "cyclone_track_point"
    __table_args__ = (
        Index("ix_cyclone_track_sid_time", "sid", "valid_time"),
        Index("ix_cyclone_track_basin_time", "basin", "valid_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("track_dataset.id", ondelete="CASCADE"), nullable=False
    )
    sid: Mapped[str] = mapped_column(String(32), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    basin: Mapped[str] = mapped_column(String(2), nullable=False)
    subbasin: Mapped[str | None] = mapped_column(String(8), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    valid_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    track_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wmo_wind: Mapped[float | None] = mapped_column(Float, nullable=True)
    wmo_wind_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wmo_pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    wmo_pressure_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wmo_agency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    newdelhi_wind: Mapped[float | None] = mapped_column(Float, nullable=True)
    newdelhi_wind_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    newdelhi_pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    newdelhi_pressure_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_fields: Mapped[dict[str, str | None]] = mapped_column(JSON, nullable=False)
    field_units: Mapped[dict[str, str | None]] = mapped_column(JSON, nullable=False)
