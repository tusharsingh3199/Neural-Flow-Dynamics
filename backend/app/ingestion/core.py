from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from random import random
from time import sleep
from typing import ClassVar, Protocol, TypeVar
from urllib.error import URLError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.contracts import ProductClass, Provenance


class IngestionStatus(StrEnum):
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"


class IngestionInsertResult(StrEnum):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GeographicBounds(ContractModel):
    minimum_latitude: float = Field(ge=-90, le=90)
    maximum_latitude: float = Field(ge=-90, le=90)
    minimum_longitude: float = Field(ge=-180, le=180)
    maximum_longitude: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> "GeographicBounds":
        if self.minimum_latitude >= self.maximum_latitude:
            raise ValueError("minimum latitude must be lower than maximum latitude")
        if self.minimum_longitude >= self.maximum_longitude:
            raise ValueError("minimum longitude must be lower than maximum longitude")
        return self

    def contains(self, other: "GeographicBounds") -> bool:
        return (
            self.minimum_latitude <= other.minimum_latitude
            and self.maximum_latitude >= other.maximum_latitude
            and self.minimum_longitude <= other.minimum_longitude
            and self.maximum_longitude >= other.maximum_longitude
        )


class VariableDescription(ContractModel):
    unit: str = Field(min_length=1)
    dimensions: tuple[str, ...] = Field(min_length=1)
    long_name: str | None = None
    standard_name: str | None = None


class GridDescription(ContractModel):
    crs: str = Field(min_length=1)
    latitude_coordinate: str = Field(min_length=1)
    longitude_coordinate: str = Field(min_length=1)
    spatial_dimensions: tuple[str, str]
    resolution_degrees: tuple[float, float] | None = None

    @model_validator(mode="after")
    def resolution_is_positive(self) -> "GridDescription":
        if self.resolution_degrees and any(value <= 0 for value in self.resolution_degrees):
            raise ValueError("grid resolution must be positive")
        return self


class DatasetDescription(ContractModel):
    retrieved_at: AwareDatetime
    init_time: AwareDatetime | None = None
    source_run_id: str | None = None
    valid_times: list[AwareDatetime] = Field(min_length=1)
    variables: dict[str, VariableDescription]
    grid: GridDescription | None = None
    geographic_bounds: GeographicBounds | None = None
    missing_fraction_by_variable: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def forecast_times_are_consistent(self) -> "DatasetDescription":
        if self.init_time is not None and any(
            valid_time < self.init_time for valid_time in self.valid_times
        ):
            raise ValueError("valid times must not precede forecast initialization time")
        if len(set(self.valid_times)) != len(self.valid_times):
            raise ValueError("valid times must be unique")
        if any(not 0 <= fraction <= 1 for fraction in self.missing_fraction_by_variable.values()):
            raise ValueError("missing-value fractions must be between 0 and 1")
        return self


class DatasetValidationSpec(ContractModel):
    required_variables: dict[str, VariableDescription] = Field(min_length=1)
    required_bounds: GeographicBounds | None = None
    maximum_missing_fraction: float = Field(default=0.05, ge=0, le=1)
    maximum_missing_fraction_by_variable: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def variable_thresholds_are_valid(self) -> "DatasetValidationSpec":
        if any(
            not 0 <= fraction <= 1
            for fraction in self.maximum_missing_fraction_by_variable.values()
        ):
            raise ValueError("variable missing-value thresholds must be between 0 and 1")
        return self


class IngestionManifest(ContractModel):
    idempotency_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_id: str = Field(min_length=1)
    product: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    product_class: ProductClass
    storage_uri: str = Field(min_length=1)
    init_time: AwareDatetime | None = None
    lead_time_hours: float | None = Field(default=None, ge=0)
    source_run_id: str | None = None
    valid_time: AwareDatetime
    grid: GridDescription | None = None
    dataset_metadata: dict[str, object] = Field(default_factory=dict)
    ingested_at: AwareDatetime
    checksum: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    status: IngestionStatus
    provenance: Provenance
    validation_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def provenance_matches_product(self) -> "IngestionManifest":
        if self.provenance.source_id != self.source_id:
            raise ValueError("provenance source_id must match manifest source_id")
        if self.provenance.checksum != self.checksum:
            raise ValueError("provenance checksum must match manifest checksum")
        if self.provenance.ingested_at != self.ingested_at:
            raise ValueError("provenance ingested_at must match manifest ingested_at")
        return self


class SourceAdapter(Protocol):
    source_id: ClassVar[str]
    product: ClassVar[str]
    product_class: ClassVar[ProductClass]
    source_url: ClassVar[str]
    licence: ClassVar[str]
    transformation_history: ClassVar[tuple[str, ...]]
    validation_spec: DatasetValidationSpec

    def fetch(self) -> Path: ...

    def inspect(self, path: Path) -> DatasetDescription: ...


def validate_dataset(
    dataset: DatasetDescription,
    requirements: DatasetValidationSpec,
) -> list[str]:
    errors: list[str] = []
    for name, expected in requirements.required_variables.items():
        actual = dataset.variables.get(name)
        if actual is None:
            errors.append(f"missing required variable: {name}")
            continue
        if actual.unit != expected.unit:
            errors.append(f"{name}: expected unit {expected.unit!r}, received {actual.unit!r}")
        if actual.dimensions != expected.dimensions:
            errors.append(
                f"{name}: expected dimensions {expected.dimensions!r}, "
                f"received {actual.dimensions!r}"
            )
        missing_fraction = dataset.missing_fraction_by_variable.get(name)
        maximum_missing_fraction = requirements.maximum_missing_fraction_by_variable.get(
            name,
            requirements.maximum_missing_fraction,
        )
        if missing_fraction is None:
            errors.append(f"{name}: missing-value fraction was not measured")
        elif missing_fraction > maximum_missing_fraction:
            errors.append(
                f"{name}: missing-value fraction {missing_fraction:.4f} exceeds "
                f"maximum {maximum_missing_fraction:.4f}"
            )

    if requirements.required_bounds is not None:
        actual_bounds = dataset.geographic_bounds
        if actual_bounds is None:
            errors.append("geographic coverage was not provided")
        elif not actual_bounds.contains(requirements.required_bounds):
            errors.append("dataset geographic coverage does not contain the required bounds")
    return errors


def compute_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def make_idempotency_key(
    *,
    source_id: str,
    product: str,
    init_time: datetime | None,
    valid_time: datetime,
    checksum: str,
    variable: str = "",
) -> str:
    canonical_values = (
        source_id,
        product,
        init_time.astimezone(UTC).isoformat() if init_time else "",
        valid_time.astimezone(UTC).isoformat(),
        variable,
        checksum,
    )
    return sha256("\0".join(canonical_values).encode("utf-8")).hexdigest()


T = TypeVar("T")
RetryableError = (TimeoutError, ConnectionError, URLError)


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.25,
    maximum_delay_seconds: float = 5,
    sleep_function: Callable[[float], None] = sleep,
    random_function: Callable[[], float] = random,
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    if base_delay_seconds < 0 or maximum_delay_seconds < 0:
        raise ValueError("retry delays must not be negative")
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except RetryableError:
            if attempt == attempts:
                raise
            delay = min(base_delay_seconds * (2 ** (attempt - 1)), maximum_delay_seconds)
            sleep_function(min(delay * (0.5 + random_function()), maximum_delay_seconds))
    raise AssertionError("retry loop exited without a result")
