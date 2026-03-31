import socket
from pathlib import Path

import pytest

from shardnet.client.core.peer_client import PeerClient
from shardnet.client.core.peer_server import PeerServer
from shardnet.client.core.share_store import ShareStore
from shardnet.common.errors import ProtocolError


@pytest.mark.asyncio
async def test_peer_protocol_chunk_roundtrip(tmp_path: Path) -> None:
    source_file = tmp_path / "seed.bin"
    payload = b"abcdefghij"
    source_file.write_bytes(payload)

    share_store = ShareStore(tmp_path / "seed-data")
    manifest = share_store.register_file(source_file, chunk_size_bytes=4)
    peer_server = PeerServer(
        host="127.0.0.1",
        port=0,
        peer_id="peer-seed",
        share_store=share_store,
    )
    await peer_server.start()

    try:
        peer_client = PeerClient(peer_id="peer-leech", timeout_seconds=1.0, retry_attempts=1)
        chunk = await peer_client.request_chunk(
            host="127.0.0.1",
            port=peer_server.port,
            info_hash=manifest.info_hash,
            chunk_index=1,
        )
    finally:
        await peer_server.stop()

    assert chunk == payload[4:8]


@pytest.mark.asyncio
async def test_peer_protocol_missing_piece_returns_error(tmp_path: Path) -> None:
    source_file = tmp_path / "seed.bin"
    source_file.write_bytes(b"abcdefghij")

    share_store = ShareStore(tmp_path / "seed-data")
    manifest = share_store.register_file(source_file, chunk_size_bytes=4)
    peer_server = PeerServer(
        host="127.0.0.1",
        port=0,
        peer_id="peer-seed",
        share_store=share_store,
    )
    await peer_server.start()

    try:
        peer_client = PeerClient(peer_id="peer-leech", timeout_seconds=1.0, retry_attempts=0)
        with pytest.raises(ProtocolError, match="piece") as error_info:
            await peer_client.request_chunk(
                host="127.0.0.1",
                port=peer_server.port,
                info_hash=manifest.info_hash,
                chunk_index=99,
            )
    finally:
        await peer_server.stop()

    assert error_info.value.code == "piece_not_available"


@pytest.mark.asyncio
async def test_peer_client_retries_and_raises_on_unreachable_peer() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        _, free_port = sock.getsockname()

    peer_client = PeerClient(peer_id="peer-leech", timeout_seconds=0.1, retry_attempts=2)

    with pytest.raises(ProtocolError, match="retries") as error_info:
        await peer_client.request_chunk(
            host="127.0.0.1",
            port=free_port,
            info_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            chunk_index=0,
        )

    assert error_info.value.code == "chunk_request_failed"
