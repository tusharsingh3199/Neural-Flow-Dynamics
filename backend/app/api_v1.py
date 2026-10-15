from collections import defaultdict
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import struct
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname
import zlib

import numpy as np
import xarray as xr
from fastapi import APIRouter, Query, Request, Response
from pydantic import AwareDatetime
from sqlalchemy import Engine

from app.api_models import (
    FieldFrameResponse,
    LayerRunSummary,
    PointValueResponse,
    TimeSeriesResponse,
    TimeSeriesValue,
)
from app.contracts import GeoPoint, GridMetadata, LayerMeta, ProductClass, Unit
from app.ingestion.core import IngestionManifest
from app.ingestion.repository import ManifestRepository
from app.ingestion.track_repository import TrackRepository

router = APIRouter(prefix="/api/v1", tags=["data"])
MAX_FRAME_CELLS = 100_000
MAX_TIME_SERIES_POINTS = 5_000
UNIT_ALIASES = {
    "m s**-1": Unit.METRES_PER_SECOND,
    "m s-1": Unit.METRES_PER_SECOND,
    "km h-1": Unit.KILOMETRES_PER_HOUR,
    "kn": Unit.KNOTS,
    "m": Unit.METRES,
    "mm": Unit.MILLIMETRES,
    "mm h-1": Unit.MILLIMETRES_PER_HOUR,
    "K": Unit.KELVIN,
    "degC": Unit.DEGREES_CELSIUS,
    "Pa": Unit.PASCALS,
    "hPa": Unit.HECTOPASCALS,
    "m**2 s**-2": Unit.SQUARE_METRES_PER_SQUARE_SECOND,
    "m2 s-2": Unit.SQUARE_METRES_PER_SQUARE_SECOND,
    "kg m-2": Unit.KILOGRAMS_PER_SQUARE_METRE,
    "1": Unit.DIMENSIONLESS,
}


class APIProblem(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def _repository(engine: Engine) -> ManifestRepository:
    return ManifestRepository(engine)


def _layer_id(source_id: str, product: str, variable: str) -> str:
    return f"{source_id}::{product}::{variable}"


def _parse_layer_id(layer_id: str) -> tuple[str, str, str]:
    parts = layer_id.split("::", 2)
    if len(parts) != 3 or not all(parts):
        raise APIProblem("invalid_layer", "Layer identifier is malformed", status_code=400)
    return parts[0], parts[1], parts[2]


def _unit(value: str) -> Unit:
    try:
        return UNIT_ALIASES[value]
    except KeyError as error:
        raise APIProblem(
            "unsupported_unit",
            f"No canonical API unit is defined for source unit {value!r}",
            status_code=422,
            details={"source_unit": value},
        ) from error


def _manifest_grid(manifest: IngestionManifest) -> GridMetadata:
    if manifest.grid is None:
        raise APIProblem(
            "insufficient_data",
            "Field metadata does not include a grid description",
            status_code=422,
        )
    return GridMetadata(
        description=(
            f"Rectilinear grid; coordinates {manifest.grid.latitude_coordinate}, "
            f"{manifest.grid.longitude_coordinate}; dimensions "
            f"{manifest.grid.spatial_dimensions}"
        ),
        crs=manifest.grid.crs,
        resolution_degrees=manifest.grid.resolution_degrees,
    )


def _build_layers(manifests: list[IngestionManifest]) -> list[LayerMeta]:
    grouped: dict[tuple[str, str, str], list[IngestionManifest]] = defaultdict(list)
    for manifest in manifests:
        if manifest.grid is not None:
            grouped[(manifest.source_id, manifest.product, manifest.variable)].append(manifest)
    layers: list[LayerMeta] = []
    for (source_id, product, variable), records in sorted(grouped.items()):
        latest = max(records, key=lambda item: item.ingested_at)
        variable_info = latest.dataset_metadata.get("variables", {}).get(variable, {})
        source_type = latest.dataset_metadata.get("source_type", product)
        valid_times = sorted({record.valid_time for record in records})
        layers.append(
            LayerMeta(
                id=_layer_id(source_id, product, variable),
                name=str(variable_info.get("long_name") or variable),
                variable=variable,
                unit=_unit(latest.unit),
                product_class=latest.product_class,
                grid=_manifest_grid(latest),
                valid_times=valid_times,
                provenance=latest.provenance,
                description=f"{source_type}. Source product: {product}.",
            )
        )
    return layers


def _layer_records(repository: ManifestRepository, layer_id: str) -> list[IngestionManifest]:
    source_id, product, variable = _parse_layer_id(layer_id)
    records = repository.list_accepted(
        source_id=source_id,
        product=product,
        variable=variable,
    )
    if not records:
        raise APIProblem("dataset_unavailable", "No accepted data are available for this layer", status_code=404)
    return records


def _select_manifest(
    repository: ManifestRepository,
    layer_id: str,
    valid_time: datetime,
) -> IngestionManifest:
    source_id, product, variable = _parse_layer_id(layer_id)
    latest = repository.find_latest_accepted(
        source_id=source_id,
        product=product,
        variable=variable,
        valid_time=valid_time,
    )
    if latest is not None:
        return latest
    accepted = repository.list_accepted(
        source_id=source_id,
        product=product,
        variable=variable,
    )
    if not accepted:
        raise APIProblem("dataset_unavailable", "No accepted data are available for this layer", status_code=404)
    raise APIProblem(
        "unsupported_time",
        "The requested valid time is not available for this layer",
        status_code=422,
        details={"valid_time": valid_time.isoformat()},
    )


def _artifact_path(storage_uri: str) -> Path:
    parsed = urlsplit(storage_uri)
    if parsed.scheme != "file":
        raise APIProblem(
            "dataset_unavailable",
            "This API instance can only read local field artifacts",
            status_code=503,
            details={"storage_scheme": parsed.scheme},
        )
    path = url2pathname(unquote(parsed.path))
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    result = Path(path)
    if not result.exists():
        raise APIProblem(
            "dataset_unavailable",
            "The accepted field artifact is missing from local storage",
            status_code=503,
        )
    return result


def _open_field(
    manifest: IngestionManifest,
    valid_time: datetime,
    *,
    level: float | None = None,
) -> tuple[xr.Dataset, xr.DataArray]:
    path = _artifact_path(manifest.storage_uri)
    dataset = xr.open_zarr(path, chunks=None)
    if manifest.variable not in dataset.data_vars:
        dataset.close()
        raise APIProblem(
            "insufficient_data",
            "The accepted artifact does not contain the manifest variable",
            status_code=500,
            details={"variable": manifest.variable},
        )
    field = dataset[manifest.variable]
    if "time" in field.dims:
        target_time = np.datetime64(valid_time.astimezone(UTC).replace(tzinfo=None), "ns")
        try:
            field = field.sel(time=target_time)
        except KeyError as error:
            dataset.close()
            raise APIProblem("unsupported_time", "Valid time is absent from the artifact", status_code=422) from error
    if "level" in field.dims:
        if level is None:
            dataset.close()
            raise APIProblem(
                "insufficient_data",
                "A vertical level is required for this field",
                status_code=422,
                details={"available_levels": dataset["level"].values.tolist()},
            )
        field = field.sel(level=level)
    return dataset, field


def _nearest_indices(
    dataset: xr.Dataset,
    latitude: float,
    longitude: float,
) -> tuple[int, int, float, float]:
    if "latitude" not in dataset.coords or "longitude" not in dataset.coords:
        raise APIProblem("insufficient_data", "Field artifact lacks coordinate axes", status_code=422)
    latitudes = np.asarray(dataset.latitude.values)
    longitudes = np.asarray(dataset.longitude.values)
    if latitudes.ndim != 1 or longitudes.ndim != 1:
        raise APIProblem(
            "insufficient_data",
            "Only rectilinear latitude/longitude grids are supported in Phase 2",
            status_code=422,
        )
    if latitude < float(latitudes.min()) or latitude > float(latitudes.max()):
        raise APIProblem("invalid_coordinates", "Latitude is outside this layer's coverage", status_code=422)
    query_longitude = longitude
    if float(longitudes.max()) > 180 and query_longitude < 0:
        query_longitude %= 360
    if query_longitude < float(longitudes.min()) or query_longitude > float(longitudes.max()):
        raise APIProblem("invalid_coordinates", "Longitude is outside this layer's coverage", status_code=422)
    latitude_index = int(np.abs(latitudes - latitude).argmin())
    longitude_index = int(np.abs(longitudes - query_longitude).argmin())
    grid_longitude = float(longitudes[longitude_index])
    if grid_longitude > 180:
        grid_longitude -= 360
    return latitude_index, longitude_index, float(latitudes[latitude_index]), grid_longitude


def _value_or_none(value: Any) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


@router.get("/layers", response_model=list[LayerMeta])
def list_layers(request: Request) -> list[LayerMeta]:
    return _build_layers(_repository(request.app.state.engine).list_accepted())


@router.get("/layers/{layer_id}", response_model=LayerMeta)
def get_layer(layer_id: str, request: Request) -> LayerMeta:
    for layer in _build_layers(_layer_records(_repository(request.app.state.engine), layer_id)):
        if layer.id == layer_id:
            return layer
    raise APIProblem("dataset_unavailable", "Layer is not available", status_code=404)


@router.get("/layers/{layer_id}/runs", response_model=list[LayerRunSummary])
def list_layer_runs(layer_id: str, request: Request) -> list[LayerRunSummary]:
    records = _layer_records(_repository(request.app.state.engine), layer_id)
    grouped: dict[tuple[str | None, datetime | None], list[IngestionManifest]] = defaultdict(list)
    for record in records:
        grouped[(record.source_run_id, record.init_time)].append(record)
    runs: list[LayerRunSummary] = []
    for (source_run_id, init_time), group in grouped.items():
        latest = max(group, key=lambda item: item.ingested_at)
        runs.append(
            LayerRunSummary(
                source_run_id=source_run_id,
                product_class=latest.product_class,
                init_time=init_time,
                lead_times_hours=sorted(
                    {record.lead_time_hours for record in group if record.lead_time_hours is not None}
                ),
                valid_times=sorted({record.valid_time for record in group}),
                ingested_at=latest.ingested_at,
            )
        )
    return sorted(runs, key=lambda item: item.init_time or item.valid_times[0])


@router.get("/layers/{layer_id}/times", response_model=list[AwareDatetime])
def list_layer_times(layer_id: str, request: Request) -> list[datetime]:
    records = _layer_records(_repository(request.app.state.engine), layer_id)
    return sorted({record.valid_time for record in records})


@router.get("/point", response_model=PointValueResponse)
def query_point(
    request: Request,
    layer: str,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    valid_time: AwareDatetime = Query(),
    level: float | None = Query(default=None),
) -> PointValueResponse:
    repository = _repository(request.app.state.engine)
    manifest = _select_manifest(repository, layer, valid_time)
    dataset, field = _open_field(manifest, valid_time, level=level)
    try:
        lat_index, lon_index, grid_latitude, grid_longitude = _nearest_indices(
            dataset,
            latitude,
            longitude,
        )
        value = _value_or_none(field.isel(latitude=lat_index, longitude=lon_index).values)
    finally:
        dataset.close()
    return PointValueResponse(
        layer_id=layer,
        variable=manifest.variable,
        value=value,
        unit=_unit(manifest.unit),
        product_class=manifest.product_class,
        requested_location=GeoPoint(latitude=latitude, longitude=longitude),
        grid_cell=GeoPoint(latitude=grid_latitude, longitude=grid_longitude),
        init_time=manifest.init_time,
        valid_time=manifest.valid_time,
        lead_time_hours=manifest.lead_time_hours,
        ingested_at=manifest.ingested_at,
        source_run_id=manifest.source_run_id,
        provenance=manifest.provenance.model_dump(mode="json"),
    )


@router.get("/timeseries", response_model=TimeSeriesResponse)
def query_timeseries(
    request: Request,
    layer: str,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    start_time: AwareDatetime = Query(),
    end_time: AwareDatetime = Query(),
    level: float | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=MAX_TIME_SERIES_POINTS),
) -> TimeSeriesResponse:
    if start_time > end_time:
        raise APIProblem("invalid_time_range", "start_time must not be after end_time", status_code=422)
    records = [
        record
        for record in _layer_records(_repository(request.app.state.engine), layer)
        if start_time <= record.valid_time <= end_time
    ]
    records.sort(key=lambda item: item.valid_time)
    records = records[:limit]
    if not records:
        raise APIProblem("unsupported_time", "No values are available in the requested interval", status_code=422)
    values: list[TimeSeriesValue] = []
    grid_location: GeoPoint | None = None
    for record in records:
        dataset, field = _open_field(record, record.valid_time, level=level)
        try:
            lat_index, lon_index, grid_latitude, grid_longitude = _nearest_indices(
                dataset,
                latitude,
                longitude,
            )
            value = _value_or_none(field.isel(latitude=lat_index, longitude=lon_index).values)
            grid_location = GeoPoint(latitude=grid_latitude, longitude=grid_longitude)
        finally:
            dataset.close()
        values.append(
            TimeSeriesValue(
                valid_time=record.valid_time,
                value=value,
                unit=_unit(record.unit),
                init_time=record.init_time,
                lead_time_hours=record.lead_time_hours,
                ingested_at=record.ingested_at,
                source_run_id=record.source_run_id,
            )
        )
    if grid_location is None:
        raise APIProblem("insufficient_data", "No point values were produced", status_code=422)
    return TimeSeriesResponse(
        layer_id=layer,
        variable=records[0].variable,
        requested_location=GeoPoint(latitude=latitude, longitude=longitude),
        grid_cell=grid_location,
        values=values,
        provenance=[record.provenance.model_dump(mode="json") for record in records],
    )


def _read_frame(
    layer: str,
    manifest: IngestionManifest,
    *,
    level: float | None,
) -> tuple[FieldFrameResponse, np.ndarray]:
    dataset, field = _open_field(manifest, manifest.valid_time, level=level)
    try:
        values = np.asarray(field.values)
        if values.ndim != 2:
            raise APIProblem(
                "insufficient_data",
                "Only two-dimensional surface frames are supported in Phase 2",
                status_code=422,
                details={"shape": list(values.shape)},
            )
        if values.size > MAX_FRAME_CELLS:
            raise APIProblem(
                "frame_too_large",
                "Requested field frame exceeds the Phase 2 response limit",
                status_code=413,
                details={"cell_count": int(values.size), "maximum": MAX_FRAME_CELLS},
            )
        latitudes = np.asarray(dataset.latitude.values, dtype=float)
        longitudes = np.asarray(dataset.longitude.values, dtype=float)
        rows = [
            [_value_or_none(value) for value in row]
            for row in values
        ]
        response = FieldFrameResponse(
            layer_id=layer,
            variable=manifest.variable,
            unit=_unit(manifest.unit),
            product_class=manifest.product_class,
            init_time=manifest.init_time,
            valid_time=manifest.valid_time,
            lead_time_hours=manifest.lead_time_hours,
            ingested_at=manifest.ingested_at,
            source_run_id=manifest.source_run_id,
            latitudes=latitudes.tolist(),
            longitudes=longitudes.tolist(),
            values=rows,
            no_data_cells=int(np.isnan(values).sum()),
            provenance=manifest.provenance.model_dump(mode="json"),
        )
        return response, values
    finally:
        dataset.close()


@router.get("/fields/{layer_id}/{valid_time}/frame", response_model=FieldFrameResponse)
def get_field_frame(
    layer_id: str,
    valid_time: AwareDatetime,
    request: Request,
    level: float | None = Query(default=None),
) -> FieldFrameResponse:
    manifest = _select_manifest(_repository(request.app.state.engine), layer_id, valid_time)
    frame, _ = _read_frame(layer_id, manifest, level=level)
    return frame


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)


def _grayscale_png(values: np.ndarray) -> tuple[bytes, float | None, float | None]:
    finite = np.isfinite(values)
    if not finite.any():
        minimum = maximum = None
    else:
        minimum = float(values[finite].min())
        maximum = float(values[finite].max())
    height, width = values.shape
    raw = bytearray()
    for row in values:
        raw.append(0)
        for value in row:
            if not math.isfinite(float(value)):
                raw.extend((0, 0, 0, 0))
                continue
            scaled = 0 if minimum is None or maximum == minimum else round(
                255 * (float(value) - minimum) / (maximum - minimum)
            )
            raw.extend((scaled, scaled, scaled, 255))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw)))
        + _png_chunk(b"IEND", b"")
    )
    return png, minimum, maximum


@router.get("/fields/{layer_id}/{valid_time}/image")
def get_field_image(
    layer_id: str,
    valid_time: AwareDatetime,
    request: Request,
    level: float | None = Query(default=None),
) -> Response:
    manifest = _select_manifest(_repository(request.app.state.engine), layer_id, valid_time)
    frame, values = _read_frame(layer_id, manifest, level=level)
    image, minimum, maximum = _grayscale_png(values)
    headers = {
        "X-NFD-Unit": frame.unit.value,
        "X-NFD-Color-Scale": "linear grayscale, per-frame min/max; missing cells transparent",
        "X-NFD-Valid-Time": frame.valid_time.isoformat(),
    }
    if minimum is not None and maximum is not None:
        headers["X-NFD-Value-Minimum"] = str(minimum)
        headers["X-NFD-Value-Maximum"] = str(maximum)
    return Response(content=image, media_type="image/png", headers=headers)


@router.get("/sources")
def list_sources() -> dict[str, Any]:
    registry_path = Path(__file__).resolve().parents[2] / "source_registry.json"
    if not registry_path.exists():
        raise APIProblem("dataset_unavailable", "Source registry is missing", status_code=503)
    return json.loads(registry_path.read_text(encoding="utf-8"))


@router.get("/provenance/{layer_id}/{valid_time}")
def get_provenance(layer_id: str, valid_time: AwareDatetime, request: Request) -> dict[str, Any]:
    manifest = _select_manifest(_repository(request.app.state.engine), layer_id, valid_time)
    return {
        "source_id": manifest.source_id,
        "product": manifest.product,
        "variable": manifest.variable,
        "product_class": manifest.product_class.value,
        "init_time": manifest.init_time.isoformat() if manifest.init_time else None,
        "valid_time": manifest.valid_time.isoformat(),
        "lead_time_hours": manifest.lead_time_hours,
        "ingested_at": manifest.ingested_at.isoformat(),
        "checksum": manifest.checksum,
        "transformations": manifest.provenance.transformation_history,
        "licence": manifest.provenance.licence,
        "source_url": str(manifest.provenance.source_url),
    }


@router.get("/cyclones")
def list_cyclones(request: Request) -> dict[str, Any]:
    storms = TrackRepository(request.app.state.engine).list_storms()
    features = []
    for storm in storms:
        track_result = TrackRepository(request.app.state.engine).get_track(str(storm["sid"]))
        if track_result is None:
            continue
        dataset, points = track_result
        coordinates = [
            [point.longitude, point.latitude]
            for point in points
            if point.longitude is not None and point.latitude is not None
        ]
        geometry = (
            {"type": "LineString", "coordinates": coordinates}
            if len(coordinates) >= 2
            else {"type": "Point", "coordinates": coordinates[0]}
            if coordinates
            else None
        )
        if geometry is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    **storm,
                    "source_id": dataset.source_id,
                    "product_class": ProductClass.OBSERVATION.value,
                    "product_type": "historical_best_track",
                    "forecast_track": None,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "product_class": ProductClass.OBSERVATION.value,
        "product_type": "historical_best_track",
        "forecast_track": None,
        "features": features,
    }


@router.get("/cyclones/{sid}/track")
def get_cyclone_track(sid: str, request: Request) -> dict[str, Any]:
    result = TrackRepository(request.app.state.engine).get_track(sid)
    if result is None:
        raise APIProblem("dataset_unavailable", f"No best-track record found for {sid!r}", status_code=404)
    dataset, points = result
    features = []
    for point in points:
        geometry = (
            {"type": "Point", "coordinates": [point.longitude, point.latitude]}
            if point.longitude is not None and point.latitude is not None
            else None
        )
        if geometry is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "sid": point.sid,
                    "name": point.name,
                    "season": point.season,
                    "basin": point.basin,
                    "valid_time": point.valid_time.isoformat(),
                    "track_type": point.track_type,
                    "wmo_wind": point.wmo_wind,
                    "wmo_wind_unit": point.wmo_wind_unit,
                    "wmo_pressure": point.wmo_pressure,
                    "wmo_pressure_unit": point.wmo_pressure_unit,
                    "wmo_agency": point.wmo_agency,
                    "newdelhi_wind": point.newdelhi_wind,
                    "newdelhi_wind_unit": point.newdelhi_wind_unit,
                    "newdelhi_pressure": point.newdelhi_pressure,
                    "newdelhi_pressure_unit": point.newdelhi_pressure_unit,
                    "agency_fields": point.raw_fields,
                    "field_units": point.field_units,
                    "product_class": ProductClass.OBSERVATION.value,
                    "product_type": "historical_best_track",
                    "forecast_track": None,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "product_class": ProductClass.OBSERVATION.value,
        "product_type": "historical_best_track",
        "source_id": dataset.source_id,
        "source_url": dataset.source_url,
        "source_version": dataset.version,
        "retrieved_at": dataset.retrieved_at.isoformat(),
        "ingested_at": dataset.ingested_at.isoformat(),
        "checksum": dataset.checksum,
        "citation": dataset.citation,
        "licence_note": dataset.licence_note,
        "forecast_track": None,
        "features": features,
    }