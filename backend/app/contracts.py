from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductClass(StrEnum):
    OBSERVATION = "observation"
    OFFICIAL_WARNING = "official_warning"
    NUMERICAL_FORECAST = "numerical_forecast"
    EXPERIMENTAL_AI = "experimental_ai"
    SIMULATED = "simulated"
    UNVALIDATED_RISK = "unvalidated_risk"


class Unit(StrEnum):
    METRES_PER_SECOND = "m s-1"
    KILOMETRES_PER_HOUR = "km h-1"
    KNOTS = "kn"
    METRES = "m"
    MILLIMETRES = "mm"
    MILLIMETRES_PER_HOUR = "mm h-1"
    KILOGRAMS_PER_SQUARE_METRE = "kg m-2"
    KELVIN = "K"
    DEGREES_CELSIUS = "degC"
    PASCALS = "Pa"
    HECTOPASCALS = "hPa"
    WATTS_PER_SQUARE_METRE = "W m-2"
    KILOGRAMS_PER_KILOGRAM = "kg kg-1"
    SQUARE_METRES_PER_SQUARE_SECOND = "m2 s-2"
    DEGREES_EAST = "degrees_east"
    DEGREES_NORTH = "degrees_north"
    PEOPLE = "people"
    COUNT = "count"
    DIMENSIONLESS = "1"


class Provenance(ContractModel):
    source_id: str = Field(min_length=1)
    source_url: HttpUrl
    licence: str = Field(min_length=1)
    retrieved_at: AwareDatetime
    ingested_at: AwareDatetime
    checksum: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    transformation_history: list[str] = Field(default_factory=list)


class ForecastRun(ContractModel):
    model: str = Field(min_length=1)
    init_time: AwareDatetime
    lead_times_hours: list[int] = Field(min_length=1)
    source_run_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def lead_times_are_positive_and_unique(self) -> "ForecastRun":
        if any(lead < 0 for lead in self.lead_times_hours):
            raise ValueError("forecast lead times must be non-negative")
        if len(set(self.lead_times_hours)) != len(self.lead_times_hours):
            raise ValueError("forecast lead times must be unique")
        return self


class GridMetadata(ContractModel):
    description: str = Field(min_length=1)
    crs: str = Field(min_length=1)
    resolution_degrees: tuple[float, float] | None = None

    @model_validator(mode="after")
    def resolution_is_positive(self) -> "GridMetadata":
        if self.resolution_degrees and any(value <= 0 for value in self.resolution_degrees):
            raise ValueError("grid resolution must be positive")
        return self


class LayerLegend(ContractModel):
    minimum: float
    maximum: float
    colours: list[str] = Field(min_length=2)

    @model_validator(mode="after")
    def range_is_ordered(self) -> "LayerLegend":
        if self.minimum >= self.maximum:
            raise ValueError("legend minimum must be lower than maximum")
        return self


class LayerMeta(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    unit: Unit
    product_class: ProductClass
    grid: GridMetadata
    valid_times: list[AwareDatetime] = Field(min_length=1)
    provenance: Provenance
    description: str = Field(min_length=1)
    colormap: str | None = None
    legend: LayerLegend | None = None


class HazardAssessment(ContractModel):
    id: str = Field(min_length=1)
    product_class: Literal[ProductClass.UNVALIDATED_RISK] = ProductClass.UNVALIDATED_RISK
    source_layer_id: str = Field(min_length=1)
    forecast_run_id: str = Field(min_length=1)
    valid_start: AwareDatetime
    valid_end: AwareDatetime
    threshold: float
    unit: Unit
    resolution_description: str = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_window_is_ordered(self) -> "HazardAssessment":
        if self.valid_start > self.valid_end:
            raise ValueError("valid_start must not be after valid_end")
        return self


class ExposureSummary(ContractModel):
    hazard_id: str = Field(min_length=1)
    geography_id: str = Field(min_length=1)
    exposed_population: int = Field(ge=0)
    population_reference_year: int = Field(ge=1900, le=2200)
    exposed_facilities: int = Field(ge=0)
    vulnerability_limitations: list[str] = Field(default_factory=list)
    provenance: Provenance


class GeoPoint(ContractModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Incident(ContractModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    location: GeoPoint
    severity: int = Field(ge=1, le=5)
    status: Literal["unverified", "verified", "closed"] = "unverified"
    product_class: ProductClass
    reported_at: AwareDatetime


class Team(ContractModel):
    id: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    location: GeoPoint
    location_source: Literal["live", "last_known", "manual", "simulated"]
    location_observed_at: AwareDatetime
    available: bool
    product_class: ProductClass


class Shelter(ContractModel):
    id: str = Field(min_length=1)
    location: GeoPoint
    capacity: int = Field(ge=0)
    occupancy: int = Field(ge=0)
    product_class: ProductClass

    @model_validator(mode="after")
    def occupancy_does_not_exceed_capacity(self) -> "Shelter":
        if self.occupancy > self.capacity:
            raise ValueError("shelter occupancy cannot exceed capacity")
        return self


class TaskStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELAYED = "delayed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PROPOSED: {TaskStatus.APPROVED, TaskStatus.CANCELLED, TaskStatus.REJECTED},
    TaskStatus.APPROVED: {TaskStatus.ACKNOWLEDGED, TaskStatus.CANCELLED},
    TaskStatus.ACKNOWLEDGED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {
        TaskStatus.DELAYED,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.DELAYED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.REJECTED: set(),
}


class Task(ContractModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: TaskStatus
    assigned_team_ids: list[str] = Field(default_factory=list)
    product_class: ProductClass
    created_at: AwareDatetime

    def transition_to(self, new_status: TaskStatus) -> "Task":
        if new_status not in TASK_TRANSITIONS[self.status]:
            raise ValueError(f"invalid task transition: {self.status} -> {new_status}")
        return self.model_copy(update={"status": new_status})


class AuditEvent(ContractModel):
    id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    occurred_at: AwareDatetime
    details: dict[str, str] = Field(default_factory=dict)


class OfficialWarning(ContractModel):
    id: str = Field(min_length=1)
    sender: str = Field(min_length=1)
    sent: AwareDatetime
    effective: AwareDatetime
    expires: AwareDatetime
    message_type: Literal["Alert", "Update", "Cancel"]
    scope: Literal["Public", "Restricted", "Private"]
    event: str = Field(min_length=1)
    severity: Literal["Extreme", "Severe", "Moderate", "Minor", "Unknown"]
    urgency: Literal["Immediate", "Expected", "Future", "Past", "Unknown"]
    certainty: Literal["Observed", "Likely", "Possible", "Unlikely", "Unknown"]
    headline: str = Field(min_length=1)
    description: str = Field(min_length=1)
    product_class: Literal[ProductClass.OFFICIAL_WARNING] = ProductClass.OFFICIAL_WARNING
    provenance: Provenance

    @model_validator(mode="after")
    def warning_times_are_ordered(self) -> "OfficialWarning":
        if self.effective > self.expires:
            raise ValueError("warning effective time must not be after expiry")
        return self
