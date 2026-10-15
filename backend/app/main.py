from typing import Literal

import psycopg
import redis
from fastapi import FastAPI, Response
from pydantic import BaseModel

from app.settings import get_settings

settings = get_settings()
app = FastAPI(title="Neural Flow Dynamics API", version="0.1.0")


class HealthResponse(BaseModel):
    status: Literal["ok", "error"]
    database: Literal["ok", "error"]
    redis: Literal["ok", "error"]


def check_database() -> bool:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error:
        return False
    return True


def check_redis() -> bool:
    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        client.ping()
    except redis.RedisError:
        return False
    finally:
        client.close()
    return True


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health(response: Response) -> HealthResponse:
    database_ok = check_database()
    redis_ok = check_redis()
    healthy = database_ok and redis_ok
    if not healthy:
        response.status_code = 503
    return HealthResponse(
        status="ok" if healthy else "error",
        database="ok" if database_ok else "error",
        redis="ok" if redis_ok else "error",
    )
