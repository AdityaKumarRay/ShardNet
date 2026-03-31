import pytest
from httpx import ASGITransport, AsyncClient

from shardnet.common.config import TrackerSettings
from shardnet.tracker.api import create_app


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    app = create_app(TrackerSettings(log_level="WARNING"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tracker"}


@pytest.mark.asyncio
async def test_meta_endpoint() -> None:
    app = create_app(TrackerSettings(log_level="WARNING"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/meta")

    payload = response.json()

    assert response.status_code == 200
    assert payload["api_version"] == "v1"
    assert payload["protocol_version"] == 1
    assert payload["service"] == "tracker"
