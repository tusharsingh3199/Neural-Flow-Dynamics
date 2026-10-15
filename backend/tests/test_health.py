import asyncio

from httpx import ASGITransport, AsyncClient

from app import main


def request_health():
    async def send_request():
        async with AsyncClient(
            transport=ASGITransport(app=main.app),
            base_url="http://test",
        ) as client:
            return await client.get("/health")

    return asyncio.run(send_request())


def test_health_reports_all_services_healthy(monkeypatch) -> None:
    monkeypatch.setattr(main, "check_database", lambda: True)
    monkeypatch.setattr(main, "check_redis", lambda: True)

    response = request_health()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}


def test_health_returns_service_unavailable_when_dependency_fails(monkeypatch) -> None:
    monkeypatch.setattr(main, "check_database", lambda: False)
    monkeypatch.setattr(main, "check_redis", lambda: True)

    response = request_health()

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error", "redis": "ok"}
