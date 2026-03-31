"""Peer node orchestration for tracker + P2P transfer workflows."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path

from shardnet.client.core.download_store import DownloadStore
from shardnet.client.core.models import DownloadProgress, FileManifest
from shardnet.client.core.peer_client import PeerClient
from shardnet.client.core.peer_server import PeerServer
from shardnet.client.core.share_store import ShareStore
from shardnet.client.core.tracker_client import TrackerClient
from shardnet.common.errors import TransferError
from shardnet.common.logging import get_logger
from shardnet.tracker.schemas import SwarmPeerResponse, SwarmResponse


class PeerNode:
    """Coordinates local peer lifecycle with tracker and chunk transfer components."""

    def __init__(
        self,
        *,
        peer_id: str,
        host: str,
        port: int,
        tracker_client: TrackerClient,
        share_store: ShareStore,
        download_store: DownloadStore,
        heartbeat_interval_seconds: float = 30.0,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        self.peer_id = peer_id
        self._host = host
        self._tracker_client = tracker_client
        self._share_store = share_store
        self._download_store = download_store
        self._peer_client = PeerClient(
            peer_id=peer_id,
            timeout_seconds=request_timeout_seconds,
            retry_attempts=2,
        )
        self._peer_server = PeerServer(
            host=host,
            port=port,
            peer_id=peer_id,
            share_store=share_store,
        )
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._running = False
        self._logger = get_logger(service="client", component="node", peer_id=peer_id)

    @property
    def port(self) -> int:
        return self._peer_server.port

    async def start(self) -> None:
        """Start peer server and register with tracker."""

        if self._running:
            return

        await self._peer_server.start()
        await self._tracker_client.register_peer(
            peer_id=self.peer_id,
            host=self._host,
            port=self.port,
            client_version="0.1.0",
        )
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._logger.info("peer_node_started", host=self._host, port=self.port)

    async def stop(self) -> None:
        """Stop heartbeat and peer server resources."""

        if not self._running:
            return

        self._running = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        await self._peer_server.stop()
        await self._tracker_client.close()
        self._logger.info("peer_node_stopped")

    async def share_file(self, file_path: str | Path, chunk_size_bytes: int) -> FileManifest:
        """Register a local file and announce complete chunk availability."""

        manifest = self._share_store.register_file(file_path, chunk_size_bytes=chunk_size_bytes)
        await self._tracker_client.announce_file(
            peer_id=self.peer_id,
            manifest=manifest,
            available_chunks=list(range(manifest.total_chunks)),
        )
        self._logger.info("file_shared", info_hash=manifest.info_hash, file_name=manifest.file_name)
        return manifest

    async def download_file(
        self,
        *,
        info_hash: str,
        target_path: str | Path,
        max_chunks: int | None = None,
        progress_callback: (Callable[[DownloadProgress], Awaitable[None] | None] | None) = None,
    ) -> DownloadProgress:
        """Download missing chunks from peers and resume from local state when available."""

        swarm = await self._tracker_client.get_swarm(info_hash=info_hash)
        manifest = FileManifest(
            info_hash=swarm.info_hash,
            file_name=swarm.file_name,
            file_size_bytes=swarm.file_size_bytes,
            chunk_size_bytes=swarm.chunk_size_bytes,
            total_chunks=swarm.total_chunks,
            file_sha256=swarm.file_sha256,
            chunk_sha256=swarm.chunk_sha256,
        )

        progress = self._download_store.create_or_resume_download(manifest, target_path)
        completed_this_call = 0

        for chunk_index in progress.missing_chunks:
            peer = _select_peer_for_chunk(swarm.peers, chunk_index, self.peer_id)
            if peer is None:
                raise TransferError(
                    code="chunk_unavailable",
                    message="No available peer can serve the requested chunk.",
                    context={"chunk_index": chunk_index, "info_hash": info_hash},
                )

            chunk_data = await self._peer_client.request_chunk(
                host=peer.host,
                port=peer.port,
                info_hash=info_hash,
                chunk_index=chunk_index,
            )
            self._download_store.write_chunk(
                manifest,
                chunk_index=chunk_index,
                chunk_data=chunk_data,
            )

            if progress_callback is not None:
                interim_progress = self._download_store.get_progress(info_hash)
                await _dispatch_progress(progress_callback, interim_progress)

            completed_this_call += 1

            if max_chunks is not None and completed_this_call >= max_chunks:
                break

        current = self._download_store.get_progress(info_hash)
        await self._tracker_client.announce_file(
            peer_id=self.peer_id,
            manifest=manifest,
            available_chunks=current.completed_chunks,
        )

        if not current.missing_chunks:
            self._download_store.finalize_download(info_hash)
            current = self._download_store.get_progress(info_hash)
            self._logger.info(
                "download_completed",
                info_hash=info_hash,
                target_path=str(target_path),
            )
        else:
            self._logger.info(
                "download_progress",
                info_hash=info_hash,
                completed_chunks=len(current.completed_chunks),
                missing_chunks=len(current.missing_chunks),
            )

        if progress_callback is not None:
            await _dispatch_progress(progress_callback, current)

        return current

    async def get_swarm(self, info_hash: str) -> SwarmResponse:
        """Return tracker swarm state for an info_hash."""

        return await self._tracker_client.get_swarm(info_hash=info_hash)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await self._tracker_client.heartbeat(peer_id=self.peer_id)
            except Exception as error:
                self._logger.warning("heartbeat_failed", error=str(error))

            await asyncio.sleep(self._heartbeat_interval_seconds)


def _select_peer_for_chunk(
    peers: list[SwarmPeerResponse],
    chunk_index: int,
    local_peer_id: str,
) -> SwarmPeerResponse | None:
    for peer in peers:
        if peer.peer_id == local_peer_id:
            continue
        if chunk_index in peer.available_chunks:
            return peer
    return None


async def _dispatch_progress(
    callback: Callable[[DownloadProgress], Awaitable[None] | None],
    progress: DownloadProgress,
) -> None:
    maybe_awaitable = callback(progress)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable
