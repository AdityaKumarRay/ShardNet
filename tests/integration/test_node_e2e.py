from pathlib import Path

import pytest
from httpx import ASGITransport

from shardnet.client.core.download_store import DownloadStore
from shardnet.client.core.node import PeerNode
from shardnet.client.core.share_store import ShareStore
from shardnet.client.core.tracker_client import TrackerClient
from shardnet.common.config import TrackerSettings
from shardnet.tracker.api import create_app


@pytest.mark.asyncio
async def test_tracker_to_peer_end_to_end_download(tmp_path: Path) -> None:
    tracker_db = tmp_path / "tracker.db"
    tracker_settings = TrackerSettings(
        database_url=f"sqlite:///{tracker_db}",
        heartbeat_ttl_seconds=120,
        log_level="WARNING",
    )
    tracker_app = create_app(tracker_settings)

    async with tracker_app.router.lifespan_context(tracker_app):
        transport = ASGITransport(app=tracker_app)

        seed_tracker_client = TrackerClient(base_url="http://tracker", transport=transport)
        leecher_tracker_client = TrackerClient(base_url="http://tracker", transport=transport)

        seed_node = PeerNode(
            peer_id="peer-seed",
            host="127.0.0.1",
            port=0,
            tracker_client=seed_tracker_client,
            share_store=ShareStore(tmp_path / "seed"),
            download_store=DownloadStore(tmp_path / "seed"),
        )
        leecher_node = PeerNode(
            peer_id="peer-leecher",
            host="127.0.0.1",
            port=0,
            tracker_client=leecher_tracker_client,
            share_store=ShareStore(tmp_path / "leecher"),
            download_store=DownloadStore(tmp_path / "leecher"),
        )

        await seed_node.start()
        await leecher_node.start()
        try:
            source_file = tmp_path / "source.bin"
            payload = b"ShardNet protocol end-to-end payload"
            source_file.write_bytes(payload)

            manifest = await seed_node.share_file(source_file, chunk_size_bytes=8)
            target_path = tmp_path / "downloads" / "source.bin"
            progress = await leecher_node.download_file(
                info_hash=manifest.info_hash,
                target_path=target_path,
            )

            assert progress.status == "completed"
            assert target_path.read_bytes() == payload
        finally:
            await leecher_node.stop()
            await seed_node.stop()


@pytest.mark.asyncio
async def test_download_resume_after_interruption(tmp_path: Path) -> None:
    tracker_db = tmp_path / "tracker.db"
    tracker_settings = TrackerSettings(
        database_url=f"sqlite:///{tracker_db}",
        heartbeat_ttl_seconds=120,
        log_level="WARNING",
    )
    tracker_app = create_app(tracker_settings)

    async with tracker_app.router.lifespan_context(tracker_app):
        transport = ASGITransport(app=tracker_app)

        seed_tracker_client = TrackerClient(base_url="http://tracker", transport=transport)
        leecher_tracker_client_one = TrackerClient(base_url="http://tracker", transport=transport)
        leecher_tracker_client_two = TrackerClient(base_url="http://tracker", transport=transport)

        seed_node = PeerNode(
            peer_id="peer-seed",
            host="127.0.0.1",
            port=0,
            tracker_client=seed_tracker_client,
            share_store=ShareStore(tmp_path / "seed"),
            download_store=DownloadStore(tmp_path / "seed"),
        )
        leecher_node_first = PeerNode(
            peer_id="peer-leecher",
            host="127.0.0.1",
            port=0,
            tracker_client=leecher_tracker_client_one,
            share_store=ShareStore(tmp_path / "leecher"),
            download_store=DownloadStore(tmp_path / "leecher"),
        )

        await seed_node.start()
        await leecher_node_first.start()
        try:
            source_file = tmp_path / "source.bin"
            payload = b"interruption-resume-flow-for-shardnet"
            source_file.write_bytes(payload)

            manifest = await seed_node.share_file(source_file, chunk_size_bytes=7)
            target_path = tmp_path / "downloads" / "source.bin"

            partial_progress = await leecher_node_first.download_file(
                info_hash=manifest.info_hash,
                target_path=target_path,
                max_chunks=1,
            )
            assert partial_progress.status == "active"
            assert len(partial_progress.completed_chunks) == 1
        finally:
            await leecher_node_first.stop()

        leecher_node_second = PeerNode(
            peer_id="peer-leecher",
            host="127.0.0.1",
            port=0,
            tracker_client=leecher_tracker_client_two,
            share_store=ShareStore(tmp_path / "leecher"),
            download_store=DownloadStore(tmp_path / "leecher"),
        )

        await leecher_node_second.start()
        try:
            resumed_progress = await leecher_node_second.download_file(
                info_hash=manifest.info_hash,
                target_path=target_path,
            )

            assert resumed_progress.status == "completed"
            assert target_path.read_bytes() == payload
        finally:
            await leecher_node_second.stop()
            await seed_node.stop()
