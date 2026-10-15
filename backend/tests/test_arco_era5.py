from datetime import UTC, datetime
import os
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from app.ingestion.arco_era5 import ARCOEra5Adapter, ARCOEra5Config
from app.ingestion.core import validate_dataset


def make_source_dataset() -> xr.Dataset:
    times = np.array(
        ["2023-06-15T00:00:00", "2023-06-15T01:00:00"],
        dtype="datetime64[ns]",
    )
    latitude = np.array([30.0, 20.0, 10.0, 5.0])
    longitude = np.array([60.0, 80.0, 100.0])
    shape = (len(times), len(latitude), len(longitude))
    land_masked_sst = np.full(shape, 300.0)
    land_masked_sst[:, 0, :] = np.nan
    variables = {
        "10m_u_component_of_wind": ("m s**-1", np.full(shape, 3.5)),
        "10m_v_component_of_wind": ("m s**-1", np.full(shape, -1.0)),
        "mean_sea_level_pressure": ("Pa", np.full(shape, 100_500.0)),
        "2m_temperature": ("K", np.full(shape, 298.0)),
        "sea_surface_temperature": ("K", land_masked_sst),
        "total_precipitation": ("m", np.zeros(shape)),
    }
    dataset = xr.Dataset(
        {
            name: xr.DataArray(
                values,
                dims=("time", "latitude", "longitude"),
                attrs={"units": unit, "long_name": name},
            )
            for name, (unit, values) in variables.items()
        },
        coords={"time": times, "latitude": latitude, "longitude": longitude},
        attrs={
            "last_updated": "2023-07-01T00:00:00Z",
            "valid_time_start": "1940-01-01",
            "valid_time_stop": "2026-06-30",
            "valid_time_stop_era5t": "2026-06-30",
        },
    )
    return dataset


def make_adapter(tmp_path: Path) -> ARCOEra5Adapter:
    return ARCOEra5Adapter(
        ARCOEra5Config(
            output_root=tmp_path,
            start_time=datetime(2023, 6, 15, tzinfo=UTC),
            end_time=datetime(2023, 6, 15, 1, tzinfo=UTC),
        )
    )


def test_arco_adapter_writes_and_reopens_bounded_zarr(tmp_path, monkeypatch) -> None:
    adapter = make_adapter(tmp_path)
    monkeypatch.setattr(adapter, "_open_source", make_source_dataset)

    artifact = adapter.fetch()
    description = adapter.inspect(artifact)

    assert artifact.is_dir()
    assert description.valid_times == [
        datetime(2023, 6, 15, 0, tzinfo=UTC),
        datetime(2023, 6, 15, 1, tzinfo=UTC),
    ]
    assert description.grid is not None
    assert description.grid.resolution_degrees == (10.0, 20.0)
    assert description.geographic_bounds is not None
    assert description.geographic_bounds.minimum_latitude == 5.0
    assert description.geographic_bounds.maximum_latitude == 30.0
    assert description.variables["10m_u_component_of_wind"].unit == "m s**-1"
    assert description.missing_fraction_by_variable["sea_surface_temperature"] == 0.25
    assert validate_dataset(description, adapter.validation_spec) == []


def test_arco_adapter_rejects_stable_coverage_overrun(tmp_path, monkeypatch) -> None:
    config = ARCOEra5Config(
        output_root=tmp_path,
        start_time=datetime(2026, 7, 1, tzinfo=UTC),
        end_time=datetime(2026, 7, 1, 1, tzinfo=UTC),
    )
    adapter = ARCOEra5Adapter(config)
    monkeypatch.setattr(adapter, "_open_source", make_source_dataset)

    with pytest.raises(ValueError, match="outside the available stable ERA5 coverage"):
        adapter.fetch()


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("NFD_RUN_SOURCE_INTEGRATION") != "1",
    reason="set NFD_RUN_SOURCE_INTEGRATION=1 to download a bounded public ARCO chunk",
)
def test_live_arco_metadata_and_bounded_read(tmp_path) -> None:
    adapter = ARCOEra5Adapter(
        ARCOEra5Config(
            output_root=tmp_path,
            start_time=datetime(2026, 6, 30, tzinfo=UTC),
            end_time=datetime(2026, 6, 30, tzinfo=UTC),
            variables=("10m_u_component_of_wind",),
        )
    )

    artifact = adapter.fetch()
    description = adapter.inspect(artifact)

    assert description.variables["10m_u_component_of_wind"].unit == "m s**-1"
    assert description.geographic_bounds is not None
    assert description.geographic_bounds.minimum_latitude >= 5
    assert description.geographic_bounds.maximum_latitude <= 30