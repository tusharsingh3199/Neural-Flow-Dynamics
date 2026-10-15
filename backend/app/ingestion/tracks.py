from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.contracts import ProductClass


class TrackPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sid: str = Field(min_length=1)
    season: int = Field(ge=1840, le=2200)
    basin: str = Field(min_length=2, max_length=2)
    subbasin: str | None = None
    name: str | None = None
    valid_time: AwareDatetime
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    track_type: str | None = None
    wmo_wind: float | None = None
    wmo_wind_unit: str | None = None
    wmo_pressure: float | None = None
    wmo_pressure_unit: str | None = None
    wmo_agency: str | None = None
    newdelhi_wind: float | None = None
    newdelhi_wind_unit: str | None = None
    newdelhi_pressure: float | None = None
    newdelhi_pressure_unit: str | None = None
    raw_fields: dict[str, str | None]
    field_units: dict[str, str | None]
    product_class: Literal[ProductClass.OBSERVATION] = ProductClass.OBSERVATION
    product_type: Literal["historical_best_track"] = "historical_best_track"


class TrackDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = "ibtracs_north_indian_v04r01"
    source_url: str = Field(min_length=1)
    version: str = "v04r01"
    basin: Literal["NI"] = "NI"
    retrieved_at: AwareDatetime
    ingested_at: AwareDatetime
    checksum: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    data_uri: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    licence_note: str = Field(min_length=1)
    field_units: dict[str, str | None]
    record_count: int = Field(ge=1)

    @classmethod
    def citation_text(cls, access_date: datetime) -> str:
        return (
            "Gahtan et al. (2024), International Best Track Archive for Climate "
            "Stewardship (IBTrACS) Project, Version 4r01, North Indian subset, "
            f"NOAA NCEI, doi:10.25921/82ty-9e16; accessed {access_date:%Y-%m-%d}. "
            "Also cite Knapp et al. (2010), BAMS 91, 363-376, "
            "doi:10.1175/2009BAMS2755.1."
        )


def normalize_longitude(longitude: float | None) -> float | None:
    if longitude is None:
        return None
    return longitude - 360 if longitude > 180 else longitude


def parse_optional_float(value: str | None, *, field_name: str) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"invalid numeric value for {field_name}: {value!r}") from error


def parse_track_time(value: str | None) -> datetime:
    if value is None or not value.strip():
        raise ValueError("IBTrACS ISO_TIME is required")
    parsed = datetime.fromisoformat(value.strip().replace(" ", "T"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)