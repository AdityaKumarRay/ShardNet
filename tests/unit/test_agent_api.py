from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from shardnet.client.agent.main import create_app
from shardnet.common.config import ClientSettings


@pytest.mark.asyncio
async def test_agent_health_and_default_node_state(tmp_path: Path) -> None:
    settings = ClientSettings(log_level="WARNING", data_dir=str(tmp_path / "agent-data"))
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            health = await client.get("/health")
            node = await client.get("/api/v1/node")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert node.status_code == 200
    assert node.json()["running"] is False


@pytest.mark.asyncio
async def test_agent_share_requires_running_node(tmp_path: Path) -> None:
    settings = ClientSettings(log_level="WARNING", data_dir=str(tmp_path / "agent-data"))
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/share",
                json={"file_path": str(tmp_path / "missing.bin")},
            )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "node_not_running"
