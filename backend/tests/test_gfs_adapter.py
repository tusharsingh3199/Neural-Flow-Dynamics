from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from app.ingestion.core import validate_dataset
from app.ingestion.gfs import GFSConfig, GFSGribAdapter, normalize_cfgrib_field

INIT_TIME = datetime(2026, 10, 15, tzinfo=UTC)


def make_config(tmp_path: Path, *, forecast_hours: tuple[int, ...] = (0, 3)) -> GFSConfig:
    return GFSConfig(
        init_time=INIT_TIME,
        forecast_hours=forecast_hours,
        output_root=tmp_path,
        bounds={
            "minimum_latitude": 5,
            "maximum_latitude": 30,
            "minimum_longitude": 60,
            "maximum_longitude": 100,
        },
        variables=("10m_u_component_of_wind",),
    )


def test_gfs_config_rejects_unsorted_or_unsupported_hours(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be sorted"):
        make_config(tmp_path, forecast_hours=(3, 0))
    with pytest.raises(ValueError, match="between 0 and 384"):
        make_config(tmp_path, forecast_hours=(385,))


def test_normalize_cfgrib_field_moves_valid_time_to_dimension() -> None:
    field = xr.DataArray(
        np.ones((3, 2), dtype=np.float32),
        dims=("latitude", "longitude"),
        coords={
            "latitude": [30.0, 5.0, 0.0],
            "longitude": [60.0, 80.0],
            "time": np.datetime64("2026-10-15T00:00:00"),
            "step": np.timedelta64(3, "h"),
            "valid_time": np.datetime64("2026-10-15T03:00:00"),
        },
    )

    normalized = normalize_cfgrib_field(field, datetime(2026, 10, 15, 3, tzinfo=UTC))

    assert normalized.dims == ("time", "latitude", "longitude")
    assert normalized.sizes["time"] == 1
    assert np.datetime_as_string(normalized.time.values[0]) == "2026-10-15T03:00:00.000000000"


def test_gfs_adapter_publishes_all_configured_hours_as_one_zarr_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = GFSGribAdapter(make_config(tmp_path))

    def download_field(staging, forecast_hour, variable_name, search_pattern):
        values = np.full((4, 3), float(forecast_hour), dtype=np.float32)
        field = xr.DataArray(
            values,
            dims=("latitude", "longitude"),
            coords={
                "latitude": [30.0, 20.0, 10.0, 5.0],
                "longitude": [60.0, 80.0, 100.0],
            },
            name=variable_name,
            attrs={"units": "m s**-1", "long_name": "10 metre U wind"},
        )
        return (
            normalize_cfgrib_field(field, INIT_TIME + timedelta(hours=forecast_hour)),
            f"https://example.org/gfs/f{forecast_hour:03d}",
        )

    monkeypatch.setattr(adapter, "_download_field", download_field)

    artifact = adapter.fetch()
    description = adapter.inspect(artifact)

    assert artifact.is_dir()
    assert description.init_time == INIT_TIME
    assert description.source_run_id == "gfs-2026101500"
    assert description.valid_times == [
        INIT_TIME,
        datetime(2026, 10, 15, 3, tzinfo=UTC),
    ]
    assert description.variables["10m_u_component_of_wind"].unit == "m s**-1"
    assert validate_dataset(description, adapter.validation_spec) == []
    with xr.open_zarr(artifact, chunks=None) as dataset:
        assert dataset["10m_u_component_of_wind"].shape == (2, 4, 3)
        assert float(dataset["10m_u_component_of_wind"].sel(time="2026-10-15T03").values[0, 0]) == 3


def test_gfs_adapter_does_not_publish_when_a_configured_hour_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = GFSGribAdapter(make_config(tmp_path))
    calls = 0

    def download_field(staging, forecast_hour, variable_name, search_pattern):
        nonlocal calls
        calls += 1
        if forecast_hour == 3:
            raise FileNotFoundError("incomplete run")
        field = xr.DataArray(
            np.ones((4, 3), dtype=np.float32),
            dims=("latitude", "longitude"),
            coords={"latitude": [30.0, 20.0, 10.0, 5.0], "longitude": [60.0, 80.0, 100.0]},
            name=variable_name,
            attrs={"units": "m s**-1"},
        )
        return normalize_cfgrib_field(field, INIT_TIME), "https://example.org/gfs/f000"

    monkeypatch.setattr(adapter, "_download_field", download_field)

    with pytest.raises(FileNotFoundError, match="incomplete run"):
        adapter.fetch()

    assert calls == 2
    assert not adapter._artifact_path().exists()