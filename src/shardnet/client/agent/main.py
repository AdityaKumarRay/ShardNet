"""FastAPI app for the local desktop-facing client agent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from shardnet.client.agent.schemas import (
    AgentHealthResponse,
    DownloadJobResponse,
    DownloadJobsResponse,
    NodeInfoResponse,
    ShareFileRequest,
    ShareFileResponse,
    StartDownloadRequest,
    StartNodeRequest,
)
from shardnet.client.agent.service import AgentRuntime
from shardnet.common.config import ClientSettings
from shardnet.common.errors import ShardNetError
from shardnet.common.logging import configure_logging, get_logger


def create_app(settings: ClientSettings | None = None) -> FastAPI:
    """Create the local agent API app."""

    resolved_settings = settings or ClientSettings()
    configure_logging(resolved_settings.log_level)
    logger = get_logger(service="client-agent", component="api")
    runtime = AgentRuntime(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("agent_startup")
        yield
        await runtime.shutdown()
        logger.info("agent_shutdown")

    app = FastAPI(
        title="ShardNet Client Agent",
        version="v1",
        lifespan=lifespan,
    )

    def translate_error(error: ShardNetError, status_code: int = 400) -> HTTPException:
        return HTTPException(status_code=status_code, detail=error.to_dict())

    @app.get("/health", response_model=AgentHealthResponse)
    async def health() -> AgentHealthResponse:
        return AgentHealthResponse()

    @app.get("/api/v1/node", response_model=NodeInfoResponse)
    async def get_node_info() -> NodeInfoResponse:
        return await runtime.get_node_info()

    @app.post("/api/v1/node/start", response_model=NodeInfoResponse)
    async def start_node(request_data: StartNodeRequest) -> NodeInfoResponse:
        try:
            return await runtime.start_node(request_data)
        except ShardNetError as error:
            raise translate_error(error) from error

    @app.post("/api/v1/node/stop", response_model=NodeInfoResponse)
    async def stop_node() -> NodeInfoResponse:
        return await runtime.stop_node()

    @app.post("/api/v1/share", response_model=ShareFileResponse)
    async def share_file(request_data: ShareFileRequest) -> ShareFileResponse:
        try:
            return await runtime.share_file(request_data)
        except ShardNetError as error:
            raise translate_error(error) from error

    @app.post("/api/v1/downloads", response_model=DownloadJobResponse)
    async def start_download(request_data: StartDownloadRequest) -> DownloadJobResponse:
        try:
            return await runtime.start_download(request_data)
        except ShardNetError as error:
            raise translate_error(error) from error

    @app.get("/api/v1/downloads", response_model=DownloadJobsResponse)
    async def list_downloads() -> DownloadJobsResponse:
        return await runtime.list_download_jobs()

    @app.get("/api/v1/downloads/{job_id}", response_model=DownloadJobResponse)
    async def get_download(job_id: str) -> DownloadJobResponse:
        try:
            return await runtime.get_download_job(job_id)
        except ShardNetError as error:
            raise translate_error(error, status_code=404) from error

    @app.get("/api/v1/swarm/{info_hash}")
    async def get_swarm(info_hash: str) -> dict[str, Any]:
        try:
            swarm = await runtime.get_swarm(info_hash)
        except ShardNetError as error:
            raise translate_error(error) from error
        return swarm.model_dump(mode="json")

    return app


def run() -> None:
    """Run the local desktop-facing agent API."""

    settings = ClientSettings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8765,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
