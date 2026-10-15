from typing import Any, Literal

from pydantic import AwareDatetime, Field

from app.contracts import ContractModel, GeoPoint, ProductClass, Unit


class APIErrorResponse(ContractModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class LayerRunSummary(ContractModel):
    source_run_id: str | None
    product_class: ProductClass
    init_time: AwareDatetime | None
    lead_times_hours: list[float]
    valid_times: list[AwareDatetime]
    ingested_at: AwareDatetime


class PointValueResponse(ContractModel):
    layer_id: str
    variable: str
    value: float | None
    unit: Unit
    product_class: ProductClass
    requested_location: GeoPoint
    grid_cell: GeoPoint
    interpolation: Literal["nearest"] = "nearest"
    init_time: AwareDatetime | None
    valid_time: AwareDatetime
    lead_time_hours: float | None
    ingested_at: AwareDatetime
    source_run_id: str | None
    provenance: dict[str, Any]


class TimeSeriesValue(ContractModel):
    valid_time: AwareDatetime
    value: float | None
    unit: Unit
    init_time: AwareDatetime | None
    lead_time_hours: float | None
    ingested_at: AwareDatetime
    source_run_id: str | None


class TimeSeriesResponse(ContractModel):
    layer_id: str
    variable: str
    requested_location: GeoPoint
    grid_cell: GeoPoint
    interpolation: Literal["nearest"] = "nearest"
    values: list[TimeSeriesValue]
    provenance: list[dict[str, Any]]


class FieldFrameResponse(ContractModel):
    layer_id: str
    variable: str
    unit: Unit
    product_class: ProductClass
    init_time: AwareDatetime | None
    valid_time: AwareDatetime
    lead_time_hours: float | None
    ingested_at: AwareDatetime
    source_run_id: str | None
    latitudes: list[float]
    longitudes: list[float]
    values: list[list[float | None]]
    no_data_cells: int
    provenance: dict[str, Any]