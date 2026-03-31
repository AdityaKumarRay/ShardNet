"""Agent runtime orchestration for desktop-facing API endpoints."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, cast
from uuid import uuid4

from shardnet.client.agent.schemas import (
    DownloadJobResponse,
    DownloadJobsResponse,
    NodeInfoResponse,
    ShareFileRequest,
    ShareFileResponse,
    StartDownloadRequest,
    StartNodeRequest,
)
from shardnet.client.core.download_store import DownloadStore
from shardnet.client.core.models import DownloadProgress
from shardnet.client.core.node import PeerNode
from shardnet.client.core.share_store import ShareStore
from shardnet.client.core.tracker_client import TrackerClient
from shardnet.common.config import ClientSettings
from shardnet.common.errors import TransferError
from shardnet.common.logging import get_logger
from shardnet.tracker.schemas import SwarmResponse


@dataclass
class DownloadJob:
    job_id: str
    info_hash: str
    target_path: str
    status: str
    progress: DownloadProgress | None
    error: str | None
    created_at: int
    updated_at: int


class AgentRuntime:
    """Holds mutable runtime state for the local desktop agent."""

    def __init__(self, settings: ClientSettings) -> None:
        self._settings = settings
        self._node: PeerNode | None = None
        self._node_info = NodeInfoResponse(running=False)
        self._jobs: dict[str, DownloadJob] = {}
        self._job_tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._logger = get_logger(service="client-agent", component="runtime")

    async def shutdown(self) -> None:
        """Cancel background jobs and stop node resources."""

        async with self._lock:
            tasks = list(self._job_tasks.values())
            self._job_tasks.clear()

        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

        await self.stop_node()

    async def start_node(self, request: StartNodeRequest) -> NodeInfoResponse:
        """Start or replace the current node session."""

        async with self._lock:
            if self._node is not None:
                await self._stop_node_locked()

            resolved_peer_id = request.peer_id or f"peer-{uuid4().hex[:8]}"
            tracker_client = TrackerClient(
                base_url=request.tracker_url,
                timeout_seconds=request.request_timeout_seconds,
            )
            node = PeerNode(
                peer_id=resolved_peer_id,
                host=request.host,
                port=request.port,
                tracker_client=tracker_client,
                share_store=ShareStore(request.data_dir),
                download_store=DownloadStore(request.data_dir),
                heartbeat_interval_seconds=request.heartbeat_interval_seconds,
                request_timeout_seconds=request.request_timeout_seconds,
            )
            await node.start()

            self._node = node
            self._node_info = NodeInfoResponse(
                running=True,
                peer_id=resolved_peer_id,
                host=request.host,
                port=node.port,
                data_dir=request.data_dir,
                tracker_url=request.tracker_url,
            )
            self._logger.info("node_started", peer_id=resolved_peer_id, port=node.port)
            return self._node_info

    async def stop_node(self) -> NodeInfoResponse:
        """Stop current node session if running."""

        async with self._lock:
            await self._stop_node_locked()
            return self._node_info

    async def share_file(self, request: ShareFileRequest) -> ShareFileResponse:
        """Share a file through active node session."""

        node = await self._require_node()
        chunk_size = request.chunk_size_bytes or self._settings.default_chunk_size_bytes
        manifest = await node.share_file(request.file_path, chunk_size_bytes=chunk_size)
        return ShareFileResponse(
            info_hash=manifest.info_hash,
            file_name=manifest.file_name,
            total_chunks=manifest.total_chunks,
        )

    async def start_download(self, request: StartDownloadRequest) -> DownloadJobResponse:
        """Create and run a background download job."""

        await self._require_node()
        now = int(time.time())
        job_id = uuid4().hex
        job = DownloadJob(
            job_id=job_id,
            info_hash=request.info_hash,
            target_path=request.target_path,
            status="queued",
            progress=None,
            error=None,
            created_at=now,
            updated_at=now,
        )

        async with self._lock:
            self._jobs[job_id] = job
            task = asyncio.create_task(self._run_download_job(job_id, request))
            self._job_tasks[job_id] = task

        return self._serialize_job(job)

    async def get_download_job(self, job_id: str) -> DownloadJobResponse:
        async with self._lock:
            job = self._jobs.get(job_id)

        if job is None:
            raise TransferError(
                code="job_not_found",
                message="Download job was not found.",
                context={"job_id": job_id},
            )

        return self._serialize_job(job)

    async def list_download_jobs(self) -> DownloadJobsResponse:
        async with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
        return DownloadJobsResponse(jobs=[self._serialize_job(job) for job in jobs])

    async def get_node_info(self) -> NodeInfoResponse:
        return self._node_info

    async def get_swarm(self, info_hash: str) -> SwarmResponse:
        node = await self._require_node()
        return await node.get_swarm(info_hash)

    async def _run_download_job(self, job_id: str, request: StartDownloadRequest) -> None:
        async with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.updated_at = int(time.time())

        node = await self._require_node()

        async def on_progress(progress: DownloadProgress) -> None:
            async with self._lock:
                running_job = self._jobs[job_id]
                running_job.progress = progress
                running_job.updated_at = int(time.time())

        try:
            final_progress = await node.download_file(
                info_hash=request.info_hash,
                target_path=request.target_path,
                max_chunks=request.max_chunks,
                progress_callback=on_progress,
            )
            async with self._lock:
                completed_job = self._jobs[job_id]
                completed_job.status = "completed"
                completed_job.progress = final_progress
                completed_job.updated_at = int(time.time())
        except Exception as error:
            async with self._lock:
                failed_job = self._jobs[job_id]
                failed_job.status = "failed"
                failed_job.error = str(error)
                failed_job.updated_at = int(time.time())
            self._logger.warning("download_job_failed", job_id=job_id, error=str(error))
        finally:
            async with self._lock:
                self._job_tasks.pop(job_id, None)

    async def _require_node(self) -> PeerNode:
        async with self._lock:
            node = self._node

        if node is None:
            raise TransferError(
                code="node_not_running",
                message="Client node is not running.",
            )
        return node

    async def _stop_node_locked(self) -> None:
        if self._node is not None:
            await self._node.stop()
            self._node = None

        self._node_info = NodeInfoResponse(running=False)

    @staticmethod
    def _serialize_job(job: DownloadJob) -> DownloadJobResponse:
        status = job.status
        if status not in {"queued", "running", "completed", "failed"}:
            status = "failed"

        return DownloadJobResponse(
            job_id=job.job_id,
            info_hash=job.info_hash,
            target_path=job.target_path,
            status=cast(Literal["queued", "running", "completed", "failed"], status),
            progress=job.progress,
            error=job.error,
        )
