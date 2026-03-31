from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from shardnet.common.config import TrackerSettings
from shardnet.tracker.api import create_app

INFO_HASH = "7e0e67f8de177f4f74cb5adf4f4a5749eb10c54ad5f2e26567835f1227dc8cf8"
FILE_SHA256 = "22f7d0a4e39ca232f47de31f03ec6e0f58bdf2c56034d713f026ba31f4f5e9aa"
CHUNK_HASHES = [
    "1111111111111111111111111111111111111111111111111111111111111111",
    "2222222222222222222222222222222222222222222222222222222222222222",
    "3333333333333333333333333333333333333333333333333333333333333333",
    "4444444444444444444444444444444444444444444444444444444444444444",
]


@pytest.fixture
def tracker_settings(tmp_path: Path) -> TrackerSettings:
    db_file = tmp_path / "tracker.db"
    return TrackerSettings(
        database_url=f"sqlite:///{db_file}",
        heartbeat_ttl_seconds=120,
        log_level="WARNING",
    )


@pytest.fixture
async def client(tracker_settings: TrackerSettings) -> AsyncIterator[AsyncClient]:
    app = create_app(tracker_settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            yield test_client


async def _register_peer(client: AsyncClient, peer_id: str, port: int) -> None:
    response = await client.post(
        "/api/v1/peers/register",
        json={
            "peer_id": peer_id,
            "host": "127.0.0.1",
            "port": port,
            "client_version": "0.1.0",
        },
    )
    assert response.status_code == 200


def _announce_payload(
    peer_id: str,
    available_chunks: list[int],
    file_size_bytes: int = 4096,
) -> dict[str, object]:
    return {
        "peer_id": peer_id,
        "info_hash": INFO_HASH,
        "file_name": "sample.bin",
        "file_size_bytes": file_size_bytes,
        "chunk_size_bytes": 1024,
        "total_chunks": 4,
        "file_sha256": FILE_SHA256,
        "chunk_sha256": CHUNK_HASHES,
        "available_chunks": available_chunks,
    }


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tracker"}


@pytest.mark.asyncio
async def test_meta_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta")
    payload = response.json()

    assert response.status_code == 200
    assert payload["api_version"] == "v1"
    assert payload["protocol_version"] == 1
    assert payload["service"] == "tracker"


@pytest.mark.asyncio
async def test_register_and_heartbeat_endpoints(client: AsyncClient) -> None:
    register_response = await client.post(
        "/api/v1/peers/register",
        json={
            "peer_id": "peer-a",
            "host": "127.0.0.1",
            "port": 9001,
            "client_version": "0.1.0",
        },
    )
    register_payload = register_response.json()

    heartbeat_response = await client.post(
        "/api/v1/peers/heartbeat",
        json={"peer_id": "peer-a"},
    )

    assert register_response.status_code == 200
    assert register_payload["peer_id"] == "peer-a"
    assert register_payload["heartbeat_ttl_seconds"] == 120
    assert heartbeat_response.status_code == 200
    assert heartbeat_response.json()["peer_id"] == "peer-a"


@pytest.mark.asyncio
async def test_announce_and_swarm_lookup(client: AsyncClient) -> None:
    await _register_peer(client, "peer-a", 9001)
    await _register_peer(client, "peer-b", 9002)

    announce_a = await client.post(
        "/api/v1/files/announce",
        json=_announce_payload("peer-a", [0, 1, 2, 3]),
    )
    announce_b = await client.post(
        "/api/v1/files/announce",
        json=_announce_payload("peer-b", [1, 3]),
    )
    swarm_response = await client.get(f"/api/v1/files/{INFO_HASH}/swarm")
    swarm_payload = swarm_response.json()

    assert announce_a.status_code == 200
    assert announce_a.json()["peers_advertising"] == 1
    assert announce_b.status_code == 200
    assert announce_b.json()["peers_advertising"] == 2
    assert swarm_response.status_code == 200
    assert swarm_payload["swarm_size"] == 2
    assert swarm_payload["seed_count"] == 1
    assert swarm_payload["chunk_sha256"] == CHUNK_HASHES

    peer_ids = {peer["peer_id"] for peer in swarm_payload["peers"]}
    assert peer_ids == {"peer-a", "peer-b"}


@pytest.mark.asyncio
async def test_announce_requires_registered_peer(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/files/announce",
        json=_announce_payload("peer-missing", [0, 1]),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "peer_not_found"


@pytest.mark.asyncio
async def test_metadata_conflict_returns_conflict(client: AsyncClient) -> None:
    await _register_peer(client, "peer-a", 9001)
    await _register_peer(client, "peer-b", 9002)

    first_response = await client.post(
        "/api/v1/files/announce",
        json=_announce_payload("peer-a", [0, 1, 2, 3], file_size_bytes=4096),
    )
    conflict_response = await client.post(
        "/api/v1/files/announce",
        json=_announce_payload("peer-b", [0, 1], file_size_bytes=2048),
    )

    assert first_response.status_code == 200
    assert conflict_response.status_code == 409
    assert conflict_response.json()["detail"]["code"] == "file_metadata_conflict"


@pytest.mark.asyncio
async def test_unknown_swarm_returns_not_found(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/swarm"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "info_hash_not_found"
