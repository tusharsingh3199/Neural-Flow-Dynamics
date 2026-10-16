# running command - python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

from datetime import date
from functools import lru_cache
from pathlib import Path

import cfgrib
import numpy as np
import pandas as pd
import xarray as xr

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "WeatherData(Oct1-5).grib"

EXPECTED_TIMES = ["00:00", "06:00", "12:00", "18:00"]
VARIABLE_NAMES = ["u10", "v10", "d2m", "t2m", "sp", "tp"]
VARIABLE_UNITS = {
    "u10": "m/s",
    "v10": "m/s",
    "d2m": "degC",
    "t2m": "degC",
    "sp": "hPa",
    "tp": "mm",
    "wind_speed": "m/s",
}

app = FastAPI(
    title="Neural Flow Dynamics API",
    description="Global ERA5 weather data API for NFD.",
    version="0.1.0",
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def load_dataset():
    if not DATA_FILE.is_file():
        raise FileNotFoundError(
            f"GRIB file not found at: {DATA_FILE}"
        )

    groups = cfgrib.open_datasets(
        str(DATA_FILE),
        backend_kwargs={"indexpath": ""},
    )

    if not groups:
        raise RuntimeError("No readable GRIB groups were found.")

    ds = xr.merge(
        groups,
        compat="override",
        join="outer",
    )

    if "step" in ds.dims and ds.sizes["step"] == 1:
        ds = ds.squeeze("step", drop=True)


    if "valid_time" in ds.coords:
        valid_time = ds["valid_time"]

        if valid_time.dims == ("time",):
            ds = ds.assign_coords(time=valid_time.values)

    if "time" not in ds.dims:
        raise RuntimeError(
            "No time dimension found. Inspect the GRIB "
            "coordinates using inspect_grib.py."
        )

    missing = [
        name for name in VARIABLE_NAMES
        if name not in ds.data_vars
    ]

    if missing:
        raise RuntimeError(
            f"Missing expected variables: {missing}. "
            f"Variables found: {list(ds.data_vars)}. "
            "Check inspect_grib.py output."
        )

    ds = ds.sortby("time")

    if "latitude" not in ds.coords or "longitude" not in ds.coords:
        raise RuntimeError(
            "Expected latitude/longitude coordinates were not found."
        )

    return ds


def grid_to_json(values):
    array = np.asarray(values, dtype=float)

    return [
        [
            None if not np.isfinite(value) else float(value)
            for value in row
        ]
        for row in array
    ]


def get_grid(ds, variable, timestamp):
    field = ds[variable].sel(time=timestamp)

    if "step" in field.dims:
        field = field.isel(step=0)

    field = field.squeeze(drop=True)
    field = field.transpose("latitude", "longitude")

    return field.values


def get_timestamps_for_date(ds, requested_date):
    timestamps = pd.to_datetime(ds.time.values, errors="coerce")

    requested_date = pd.Timestamp(requested_date).strftime("%Y-%m-%d")

    return [
        timestamp
        for timestamp in timestamps
        if not pd.isna(timestamp)
        and timestamp.strftime("%Y-%m-%d") == requested_date
    ]

def load_or_http_error():
    try:
        return load_dataset()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Could not read the GRIB dataset: {exc}. "
                "Run python inspect_grib.py to inspect its structure."
            ),
        ) from exc


@app.get("/")
def root():
    return {
        "project": "Neural Flow Dynamics",
        "message": "NFD Weather API is running.",
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/dates")
def available_dates():
    ds = load_or_http_error()

    timestamps = pd.to_datetime(ds.time.values, errors="coerce")

    dates = sorted({
        timestamp.strftime("%Y-%m-%d")
        for timestamp in timestamps
        if not pd.isna(timestamp)
    })

    return {"dates": dates}


@app.get("/api/weather")
def get_weather(requested_date: date = Query(..., alias="date") ):

    ds = load_or_http_error()
    timestamps = get_timestamps_for_date(ds, requested_date)

    if not timestamps:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No weather data found for {requested_date}. "
                "Check /api/dates for available dates."
            ),
        )

    frames = []

    for timestamp in timestamps:
        frame_time = pd.Timestamp(timestamp).strftime("%H:%M")

        # Read all six variables for this timestamp.
        u10 = get_grid(ds, "u10", timestamp)
        v10 = get_grid(ds, "v10", timestamp)

        frame = {
            "time": frame_time,
            "u10": grid_to_json(u10),
            "v10": grid_to_json(v10),
            "d2m": grid_to_json(
                get_grid(ds, "d2m", timestamp)
            ),
            "t2m": grid_to_json(
                get_grid(ds, "t2m", timestamp)
            ),
            "sp": grid_to_json(
                get_grid(ds, "sp", timestamp)
            ),
            "tp": grid_to_json(
                get_grid(ds, "tp", timestamp)
            ),
            "wind_speed": grid_to_json(
                np.hypot(u10, v10)
            ),
        }

        frames.append(frame)

    available_times = [frame["time"] for frame in frames]

    return JSONResponse(
        content={
            "date": requested_date.isoformat(),
            "source": "ERA5 reanalysis",
            "grid": "Global; original dataset resolution",
            "units": VARIABLE_UNITS,
            "expected_times_utc": EXPECTED_TIMES,
            "available_times_utc": available_times,
            "missing_times_utc": [
                time for time in EXPECTED_TIMES
                if time not in available_times
            ],
            "latitude": ds.latitude.values.tolist(),
            "longitude": ds.longitude.values.tolist(),
            "frames": frames,
        }
    )

