from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.contracts import (
    GeoPoint,
    LayerLegend,
    LayerMeta,
    ProductClass,
    Provenance,
    Shelter,
    Task,
    TaskStatus,
)

VALID_PROVENANCE = {
    "source_id": "fixture-source",
    "source_url": "https://example.org/data",
    "licence": "fixture licence",
    "retrieved_at": datetime(2026, 10, 15, tzinfo=UTC),
    "ingested_at": datetime(2026, 10, 15, tzinfo=UTC),
    "checksum": "sha256:" + "a" * 64,
}


def test_provenance_rejects_naive_timestamps() -> None:
    values = VALID_PROVENANCE | {"retrieved_at": datetime(2026, 10, 15)}

    with pytest.raises(ValidationError):
        Provenance(**values)


def test_layer_rejects_unknown_unit() -> None:
    values = {
        "id": "wind-10m",
        "name": "10 metre wind speed",
        "variable": "wind_speed",
        "unit": "furlongs per fortnight",
        "product_class": ProductClass.OBSERVATION,
        "grid": {"description": "test grid", "crs": "EPSG:4326"},
        "valid_times": [datetime(2026, 10, 15, tzinfo=UTC)],
        "provenance": VALID_PROVENANCE,
        "description": "Test layer",
        "colormap": "viridis",
        "legend": {"minimum": 0, "maximum": 1, "colours": ["#000000", "#ffffff"]},
    }

    with pytest.raises(ValidationError):
        LayerMeta(**values)


def test_legend_rejects_reversed_range() -> None:
    with pytest.raises(ValidationError):
        LayerLegend(minimum=10, maximum=1, colours=["#000000", "#ffffff"])


def test_coordinates_reject_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        GeoPoint(latitude=91, longitude=80)


def test_shelter_rejects_occupancy_above_capacity() -> None:
    with pytest.raises(ValidationError):
        Shelter(
            id="shelter-1",
            location={"latitude": 20, "longitude": 85},
            capacity=20,
            occupancy=21,
            product_class=ProductClass.SIMULATED,
        )


def test_task_rejects_invalid_transition() -> None:
    task = Task(
        id="task-1",
        title="Review incident",
        status=TaskStatus.PROPOSED,
        product_class=ProductClass.SIMULATED,
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="invalid task transition"):
        task.transition_to(TaskStatus.COMPLETED)


def test_task_returns_new_value_for_valid_transition() -> None:
    task = Task(
        id="task-1",
        title="Review incident",
        status=TaskStatus.PROPOSED,
        product_class=ProductClass.SIMULATED,
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )

    approved = task.transition_to(TaskStatus.APPROVED)

    assert task.status is TaskStatus.PROPOSED
    assert approved.status is TaskStatus.APPROVED
