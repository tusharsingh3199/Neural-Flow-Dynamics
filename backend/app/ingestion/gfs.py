import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
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

GFS_REGISTRY_URL = "https://registry.opendata.aws/noaa-gfs-bdp-pds/"
GFS_FIELD_SEARCHES = {
    "10m_u_component_of_wind": ("u10", ":UGRD:10 m above ground:"),
    "10m_v_component_of_wind": ("v10", ":VGRD:10 m above ground:"),
    "2m_temperature": ("t2m", ":TMP:2 m above ground:"),
    "mean_sea_level_pressure": ("prmsl", ":PRMSL:mean sea level:"),
}
GFS_FIELD_UNITS = {
    "10m_u_component_of_wind": "m s**-1",
    "10m_v_component_of_wind": "m s**-1",
    "2m_temperature": "K",
    "mean_sea_level_pressure": "Pa",
}


def normalize_cfgrib_field(field: xr.DataArray, valid_time: datetime) -> xr.DataArray:
    if "latitude" not in field.coords or "longitude" not in field.coords:
        raise ValueError("decoded GFS field lacks latitude/longitude coordinates")
    scalar_coords = [name for name in field.coords if name not in field.dims]
    if scalar_coords:
        field = field.drop_vars(scalar_coords)
    return field.expand_dims(
        time=[np.datetime64(valid_time.astimezone(UTC).replace(tzinfo=None), "ns")]
    )


class GFSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    init_time: AwareDatetime
    forecast_hours: tuple[int, ...] = Field(min_length=1)
    output_root: Path
    bounds: GeographicBounds = Field(
        default_factory=lambda: GeographicBounds(
            minimum_latitude=5,
            maximum_latitude=30,
            minimum_longitude=60,
            maximum_longitude=100,
        )
    )
    variables: tuple[str, ...] = tuple(GFS_FIELD_SEARCHES)

    @model_validator(mode="after")
    def selection_is_valid(self) -> "GFSConfig":
        if any(hour < 0 or hour > 384 for hour in self.forecast_hours):
            raise ValueError("GFS forecast hours must be between 0 and 384")
        if len(set(self.forecast_hours)) != len(self.forecast_hours):
            raise ValueError("GFS forecast hours must be unique")
        if tuple(sorted(self.forecast_hours)) != self.forecast_hours:
            raise ValueError("GFS forecast hours must be sorted")
        if not self.variables or any(name not in GFS_FIELD_SEARCHES for name in self.variables):
            raise ValueError("GFS variables must be selected from the supported field list")
        return self


class GFSGribAdapter(SourceAdapter):
    source_id: ClassVar[str] = "noaa_gfs_bdp_pds"
    product: ClassVar[str] = "gfs-0p25-grib2"
    product_class: ClassVar[ProductClass] = ProductClass.NUMERICAL_FORECAST
    source_url: ClassVar[str] = GFS_REGISTRY_URL
    licence: ClassVar[str] = "NOAA NODD public data; attribution requested, endorsement prohibited"
    transformation_history: ClassVar[tuple[str, ...]] = (
        "Selected parameter messages from NOAA GFS 0.25 degree GRIB2 using Herbie index ranges.",
        "Subset to requested forecast hours and geographic bounds; native units preserved.",
    )

    def __init__(self, config: GFSConfig) -> None:
        self.config = config
        self.validation_spec = DatasetValidationSpec(
            required_variables={
                name: VariableDescription(
                    unit=GFS_FIELD_UNITS[name],
                    dimensions=("time", "latitude", "longitude"),
                )
                for name in config.variables
            },
            required_bounds=config.bounds,
            maximum_missing_fraction=0.05,
        )

    @staticmethod
    def _coordinate_slice(coordinate: xr.DataArray, minimum: float, maximum: float) -> slice:
        first = float(coordinate.values[0])
        last = float(coordinate.values[-1])
        return slice(maximum, minimum) if first > last else slice(minimum, maximum)

    def _download_field(
        self,
        staging: Path,
        forecast_hour: int,
        variable_name: str,
        search_pattern: str,
    ) -> tuple[xr.DataArray, str]:
        from herbie.core import Herbie

        herbie = Herbie(
            self.config.init_time.astimezone(UTC).replace(tzinfo=None),
            model="gfs",
            product="pgrb2.0p25",
            fxx=forecast_hour,
            priority=["aws"],
            save_dir=staging,
            verbose=False,
        )
        remote_url = str(herbie.grib)
        local_path = herbie.download(
            searchString=search_pattern,
            source="aws",
            save_dir=staging,
            errors="raise",
        )
        if local_path is None or not Path(local_path).is_file():
            raise FileNotFoundError(
                f"NOAA GFS field subset missing for hour {forecast_hour}: {search_pattern}"
            )
        with xr.open_dataset(
            local_path,
            engine="cfgrib",
            backend_kwargs={"indexpath": ""},
        ) as decoded:
            if variable_name not in decoded.data_vars:
                raise ValueError(
                    f"decoded GFS subset lacks {variable_name!r}; "
                    f"available fields: {list(decoded.data_vars)}"
                )
            if "latitude" not in decoded.coords or "longitude" not in decoded.coords:
                raise ValueError("decoded GFS field lacks latitude/longitude coordinates")
            bounds = self.config.bounds
            field = decoded[variable_name].sel(
                latitude=self._coordinate_slice(
                    decoded.latitude,
                    bounds.minimum_latitude,
                    bounds.maximum_latitude,
                ),
                longitude=self._coordinate_slice(
                    decoded.longitude,
                    bounds.minimum_longitude,
                    bounds.maximum_longitude,
                ),
            )
            if not field.sizes.get("latitude") or not field.sizes.get("longitude"):
                raise ValueError("requested GFS geographic bounds returned no cells")
            valid_time = self.config.init_time + timedelta(hours=forecast_hour)
            field = normalize_cfgrib_field(field, valid_time)
            return field.load(), remote_url

    def _artifact_path(self) -> Path:
        selection = {
            "init_time": self.config.init_time.astimezone(UTC).isoformat(),
            "forecast_hours": self.config.forecast_hours,
            "variables": self.config.variables,
            "bounds": self.config.bounds.model_dump(mode="json"),
        }
        selection_hash = sha256(
            json.dumps(selection, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return (
            self.config.output_root
            / "gfs"
            / self.config.init_time.strftime("%Y%m%dT%H%MZ")
            / f"f{'-'.join(map(str, self.config.forecast_hours))}_{selection_hash}.zarr"
        )

    def fetch(self) -> Path:
        destination = self._artifact_path()
        if destination.exists():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="gfs-", dir=destination.parent) as temporary_name:
            staging = Path(temporary_name)
            lead_datasets: list[xr.Dataset] = []
            remote_urls: list[str] = []
            for forecast_hour in self.config.forecast_hours:
                fields: list[xr.Dataset] = []
                for output_name in self.config.variables:
                    source_name, search_pattern = GFS_FIELD_SEARCHES[output_name]
                    field, remote_url = self._download_field(
                        staging,
                        forecast_hour,
                        source_name,
                        search_pattern,
                    )
                    fields.append(field.rename(output_name).to_dataset())
                    remote_urls.append(remote_url)
                lead_datasets.append(xr.merge(fields, compat="no_conflicts", join="exact"))
            forecast = xr.concat(lead_datasets, dim="time").sortby("time")
            forecast.attrs.update(
                {
                    "source_id": self.source_id,
                    "source_product": self.product,
                    "source_type": "NOAA Global Forecast System numerical forecast",
                    "source_url": self.source_url,
                    "source_files": json.dumps(sorted(set(remote_urls))),
                    "licence": self.licence,
                    "init_time": self.config.init_time.astimezone(UTC).isoformat(),
                    "source_run_id": f"gfs-{self.config.init_time.astimezone(UTC):%Y%m%d%H}",
                    "forecast_hours": json.dumps(self.config.forecast_hours),
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            )
            with tempfile.TemporaryDirectory(
                prefix="artifact-", dir=destination.parent
            ) as artifact_tmp:
                temporary_artifact = Path(artifact_tmp) / "forecast.zarr"
                forecast.to_zarr(temporary_artifact, mode="w", zarr_format=2)
                os.replace(temporary_artifact, destination)
        return destination

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
            init_time = datetime.fromisoformat(str(dataset.attrs["init_time"]))
            return DatasetDescription(
                retrieved_at=datetime.fromisoformat(str(dataset.attrs["retrieved_at"])),
                init_time=init_time,
                source_run_id=str(dataset.attrs["source_run_id"]),
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
