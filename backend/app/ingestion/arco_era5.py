import json
import os
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import ClassVar

import numpy as np
import xarray as xr
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.contracts import ProductClass
from app.ingestion.core import (
    DatasetDescription,
    DatasetValidationSpec,
    GeographicBounds,
    GridDescription,
    SourceAdapter,
    VariableDescription,
)

ARCO_ERA5_STORE = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
ARCO_LICENSE = "Copernicus Licence to Use Copernicus Products"
DEFAULT_VARIABLES = (
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "mean_sea_level_pressure",
    "2m_temperature",
    "sea_surface_temperature",
    "total_precipitation",
)


class ARCOEra5Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_url: str = ARCO_ERA5_STORE
    output_root: Path
    start_time: AwareDatetime
    end_time: AwareDatetime
    bounds: GeographicBounds = Field(
        default_factory=lambda: GeographicBounds(
            minimum_latitude=5,
            maximum_latitude=30,
            minimum_longitude=60,
            maximum_longitude=100,
        )
    )
    variables: tuple[str, ...] = DEFAULT_VARIABLES
    allow_era5t: bool = False

    @model_validator(mode="after")
    def selection_is_valid(self) -> "ARCOEra5Config":
        if self.start_time > self.end_time:
            raise ValueError("start_time must not be after end_time")
        if not self.variables:
            raise ValueError("at least one ARCO variable must be selected")
        if len(set(self.variables)) != len(self.variables):
            raise ValueError("ARCO variables must be unique")
        return self


class ARCOEra5Adapter(SourceAdapter):
    source_id: ClassVar[str] = "arco_era5"
    product: ClassVar[str] = "era5-arco-0p25-hourly"
    product_class: ClassVar[ProductClass] = ProductClass.OBSERVATION
    source_url: ClassVar[str] = "https://github.com/google-research/arco-era5"
    licence: ClassVar[str] = ARCO_LICENSE
    transformation_history: ClassVar[tuple[str, ...]] = (
        "Selected variables, UTC interval, and geographic bounds from public ARCO-ERA5 Zarr.",
        "No unit conversion or precipitation-rate derivation applied.",
    )

    def __init__(self, config: ARCOEra5Config) -> None:
        self.config = config
        self.validation_spec = self._validation_spec()

    def _validation_spec(self) -> DatasetValidationSpec:
        expected_units = {
            "10m_u_component_of_wind": "m s**-1",
            "10m_v_component_of_wind": "m s**-1",
            "mean_sea_level_pressure": "Pa",
            "2m_temperature": "K",
            "sea_surface_temperature": "K",
            "total_precipitation": "m",
            "u_component_of_wind": "m s**-1",
            "v_component_of_wind": "m s**-1",
            "geopotential": "m**2 s**-2",
        }
        expected_dimensions = {
            "u_component_of_wind": ("time", "level", "latitude", "longitude"),
            "v_component_of_wind": ("time", "level", "latitude", "longitude"),
            "geopotential": ("time", "level", "latitude", "longitude"),
        }
        required = {
            name: VariableDescription(
                unit=expected_units.get(name, ""),
                dimensions=expected_dimensions.get(name, ("time", "latitude", "longitude")),
            )
            for name in self.config.variables
        }
        return DatasetValidationSpec(
            required_variables=required,
            required_bounds=self.config.bounds,
            maximum_missing_fraction=0.05,
            maximum_missing_fraction_by_variable={"sea_surface_temperature": 0.55},
        )

    def _open_source(self) -> xr.Dataset:
        return xr.open_zarr(
            self.config.store_url,
            chunks=None,
            storage_options={"token": "anon"},
        )

    @staticmethod
    def _coordinate_slice(coordinate: xr.DataArray, minimum: float, maximum: float) -> slice:
        first = float(coordinate.values[0])
        last = float(coordinate.values[-1])
        return slice(maximum, minimum) if first > last else slice(minimum, maximum)

    def _select_region(self, source: xr.Dataset) -> xr.Dataset:
        if "latitude" not in source.coords or "longitude" not in source.coords:
            raise ValueError("ARCO store must provide latitude and longitude coordinates")
        bounds = self.config.bounds
        latitude_slice = self._coordinate_slice(
            source.latitude, bounds.minimum_latitude, bounds.maximum_latitude
        )
        longitude_slice = self._coordinate_slice(
            source.longitude, bounds.minimum_longitude, bounds.maximum_longitude
        )
        selected = source.sel(
            time=slice(
                self.config.start_time.astimezone(UTC).replace(tzinfo=None),
                self.config.end_time.astimezone(UTC).replace(tzinfo=None),
            ),
            latitude=latitude_slice,
            longitude=longitude_slice,
        )
        missing = set(self.config.variables) - set(selected.data_vars)
        if missing:
            raise ValueError(f"ARCO store is missing requested variables: {sorted(missing)}")
        selected = selected[list(self.config.variables)]
        for variable in self.config.variables:
            if "level" in selected[variable].dims:
                selected[variable] = selected[variable].sel(level=[850, 500])
        if not selected.sizes.get("time"):
            raise ValueError("requested time interval returned no ARCO records")
        if not selected.sizes.get("latitude") or not selected.sizes.get("longitude"):
            raise ValueError("requested geographic bounds returned no ARCO cells")
        return selected

    def _artifact_path(self, source: xr.Dataset) -> Path:
        updated = (
            str(source.attrs.get("last_updated", "unknown")).replace(":", "-").replace(" ", "_")
        )
        selection = {
            "store": self.config.store_url,
            "start": self.config.start_time.isoformat(),
            "end": self.config.end_time.isoformat(),
            "bounds": self.config.bounds.model_dump(mode="json"),
            "variables": self.config.variables,
            "updated": updated,
        }
        selection_hash = sha256(
            json.dumps(selection, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return (
            self.config.output_root
            / "arco-era5"
            / updated
            / f"{self.config.start_time:%Y%m%dT%H%M%SZ}_{self.config.end_time:%Y%m%dT%H%M%SZ}_{selection_hash}.zarr"
        )

    def fetch(self) -> Path:
        source = self._open_source()
        try:
            stable_stop = source.attrs.get("valid_time_stop")
            preliminary_stop = source.attrs.get("valid_time_stop_era5t")
            if stable_stop:
                allowed_stop = preliminary_stop if self.config.allow_era5t else stable_stop
                if allowed_stop and self.config.end_time.date().isoformat() > str(allowed_stop):
                    version = "ERA5T" if self.config.allow_era5t else "stable ERA5"
                    raise ValueError(
                        f"requested end time is outside the available {version} coverage"
                    )
            selected = self._select_region(source)
            selected.attrs.update(
                {
                    "source_id": self.source_id,
                    "source_product": self.product,
                    "source_type": "ERA5 reanalysis; not observation truth",
                    "source_url": self.source_url,
                    "licence": self.licence,
                    "source_last_updated": str(source.attrs.get("last_updated", "")),
                    "source_valid_time_start": str(source.attrs.get("valid_time_start", "")),
                    "source_valid_time_stop": str(source.attrs.get("valid_time_stop", "")),
                    "source_valid_time_stop_era5t": str(
                        source.attrs.get("valid_time_stop_era5t", "")
                    ),
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "precipitation_note": (
                        "Raw total_precipitation values in metres; no rate conversion or "
                        "accumulation-window assumption applied."
                    ),
                }
            )
            destination = self._artifact_path(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                return destination
            with tempfile.TemporaryDirectory(
                prefix="arco-", dir=destination.parent
            ) as temporary_name:
                temporary_path = Path(temporary_name) / "dataset.zarr"
                selected.to_zarr(temporary_path, mode="w", zarr_format=2)
                os.replace(temporary_path, destination)
            return destination
        finally:
            source.close()

    def inspect(self, path: Path) -> DatasetDescription:
        dataset = xr.open_zarr(path, chunks=None)
        try:
            variables = {
                name: VariableDescription(
                    unit=str(dataset[name].attrs.get("units", "")),
                    dimensions=tuple(dataset[name].dims),
                    long_name=dataset[name].attrs.get("long_name"),
                    standard_name=dataset[name].attrs.get("standard_name"),
                )
                for name in dataset.data_vars
            }
            missing = {
                name: float(dataset[name].isnull().mean().item()) for name in dataset.data_vars
            }
            latitudes = np.asarray(dataset.latitude.values)
            longitudes = np.asarray(dataset.longitude.values)
            valid_times = [
                datetime.fromtimestamp(
                    np.datetime64(value, "us").astype(np.int64) / 1_000_000,
                    tz=UTC,
                )
                for value in dataset.time.values
            ]
            retrieved_at = datetime.fromisoformat(str(dataset.attrs["retrieved_at"]))
            last_updated = str(dataset.attrs.get("source_last_updated", ""))
            return DatasetDescription(
                retrieved_at=retrieved_at,
                source_run_id=f"arco-era5:{last_updated}",
                valid_times=valid_times,
                variables=variables,
                grid=GridDescription(
                    crs="EPSG:4326",
                    latitude_coordinate="latitude",
                    longitude_coordinate="longitude",
                    spatial_dimensions=("latitude", "longitude"),
                    resolution_degrees=(
                        abs(float(latitudes[1] - latitudes[0])),
                        abs(float(longitudes[1] - longitudes[0])),
                    ),
                ),
                geographic_bounds=GeographicBounds(
                    minimum_latitude=float(np.min(latitudes)),
                    maximum_latitude=float(np.max(latitudes)),
                    minimum_longitude=float(np.min(longitudes)),
                    maximum_longitude=float(np.max(longitudes)),
                ),
                missing_fraction_by_variable=missing,
            )
        finally:
            dataset.close()
