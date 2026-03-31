"""Pydantic schemas for agent API operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from shardnet.client.core.models import DownloadProgress


class AgentHealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "client-agent"


class StartNodeRequest(BaseModel):
    peer_id: str | None = None
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=9000, ge=1, le=65535)
    data_dir: str = Field(default="./data/client")
    tracker_url: str = Field(default="http://127.0.0.1:8000")
    heartbeat_interval_seconds: int = Field(default=30, gt=0)
    request_timeout_seconds: float = Field(default=5.0, gt=0)


class NodeInfoResponse(BaseModel):
    running: bool
    peer_id: str | None = None
    host: str | None = None
    port: int | None = None
    data_dir: str | None = None
    tracker_url: str | None = None


class ShareFileRequest(BaseModel):
    file_path: str
    chunk_size_bytes: int | None = Field(default=None, gt=0)


class ShareFileResponse(BaseModel):
    info_hash: str
    file_name: str
    total_chunks: int


class StartDownloadRequest(BaseModel):
    info_hash: str
    target_path: str
    max_chunks: int | None = Field(default=None, ge=1)


class DownloadJobResponse(BaseModel):
    job_id: str
    info_hash: str
    target_path: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: DownloadProgress | None = None
    error: str | None = None


class DownloadJobsResponse(BaseModel):
    jobs: list[DownloadJobResponse]
