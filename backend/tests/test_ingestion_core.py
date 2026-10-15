from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ingestion.core import (
    DatasetDescription,
    DatasetValidationSpec,
    GeographicBounds,
    compute_sha256,
    make_idempotency_key,
    retry_with_backoff,
    validate_dataset,
)

NOW = datetime(2026, 10, 15, tzinfo=UTC)
BOUNDS = GeographicBounds(
    minimum_latitude=5,
    maximum_latitude=30,
    minimum_longitude=60,
    maximum_longitude=100,
)


def make_dataset(**updates) -> DatasetDescription:
    values = {
        "retrieved_at": NOW,
        "init_time": NOW,
        "valid_times": [datetime(2026, 10, 15, 6, tzinfo=UTC)],
        "variables": {"u10": {"unit": "m s**-1", "dimensions": ["time", "latitude", "longitude"]}},
        "geographic_bounds": BOUNDS,
        "missing_fraction_by_variable": {"u10": 0.0},
    }
    return DatasetDescription(**(values | updates))


def make_spec(**updates) -> DatasetValidationSpec:
    values = {
        "required_variables": {
            "u10": {"unit": "m s**-1", "dimensions": ["time", "latitude", "longitude"]}
        },
        "required_bounds": BOUNDS,
        "maximum_missing_fraction": 0.05,
    }
    return DatasetValidationSpec(**(values | updates))


def test_validation_accepts_matching_descriptor() -> None:
    assert validate_dataset(make_dataset(), make_spec()) == []


def test_validation_rejects_wrong_unit_dimensions_and_missing_fraction() -> None:
    dataset = make_dataset(
        variables={"u10": {"unit": "kn", "dimensions": ["latitude", "longitude"]}},
        missing_fraction_by_variable={"u10": 0.2},
    )

    errors = validate_dataset(dataset, make_spec())

    assert any("expected unit" in error for error in errors)
    assert any("expected dimensions" in error for error in errors)
    assert any("exceeds maximum" in error for error in errors)


def test_validation_rejects_missing_variable_and_insufficient_coverage() -> None:
    dataset = make_dataset(
        variables={},
        geographic_bounds=GeographicBounds(
            minimum_latitude=10,
            maximum_latitude=20,
            minimum_longitude=70,
            maximum_longitude=90,
        ),
        missing_fraction_by_variable={},
    )

    errors = validate_dataset(dataset, make_spec())

    assert "missing required variable: u10" in errors
    assert any("does not contain" in error for error in errors)


def test_forecast_valid_time_must_follow_initialization() -> None:
    with pytest.raises(ValidationError, match="valid times must not precede"):
        make_dataset(valid_times=[datetime(2026, 10, 14, 18, tzinfo=UTC)])


def test_dataset_rejects_naive_retrieval_timestamp() -> None:
    with pytest.raises(ValidationError):
        make_dataset(retrieved_at=datetime(2026, 10, 15))


def test_checksum_is_stable_and_prefixed(tmp_path: Path) -> None:
    source = tmp_path / "sample.bin"
    source.write_bytes(b"nfd fixture")

    assert compute_sha256(source) == f"sha256:{sha256(b'nfd fixture').hexdigest()}"


def test_idempotency_key_normalizes_equivalent_utc_offsets() -> None:
    utc_key = make_idempotency_key(
        source_id="fixture",
        product="wind",
        init_time=datetime(2026, 10, 15, tzinfo=UTC),
        valid_time=datetime(2026, 10, 15, 6, tzinfo=UTC),
        checksum="sha256:" + "a" * 64,
    )
    offset_key = make_idempotency_key(
        source_id="fixture",
        product="wind",
        init_time=datetime.fromisoformat("2026-10-15T05:30:00+05:30"),
        valid_time=datetime.fromisoformat("2026-10-15T11:30:00+05:30"),
        checksum="sha256:" + "a" * 64,
    )

    assert utc_key == offset_key


def test_retry_uses_exponential_backoff_and_jitter() -> None:
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary")
        return "ok"

    result = retry_with_backoff(
        operation,
        attempts=3,
        base_delay_seconds=0.1,
        sleep_function=delays.append,
        random_function=lambda: 0.5,
    )

    assert result == "ok"
    assert delays == [0.1, 0.2]


def test_retry_does_not_retry_non_network_errors() -> None:
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise PermissionError("not a transient network failure")

    with pytest.raises(PermissionError):
        retry_with_backoff(operation, attempts=3, sleep_function=lambda _: None)

    assert attempts == 1
