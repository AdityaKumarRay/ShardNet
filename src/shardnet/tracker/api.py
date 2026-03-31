"""FastAPI app factory for the tracker service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request

from shardnet.common.config import TrackerSettings
from shardnet.common.constants import (
    API_PREFIX,
    API_VERSION,
    PROTOCOL_VERSION,
    TRACKER_SERVICE_NAME,
)
from shardnet.common.errors import ShardNetError
from shardnet.common.logging import configure_logging, get_logger
from shardnet.tracker.errors import (
    FileMetadataConflictError,
    InfoHashNotFoundError,
    PeerNotFoundError,
)
from shardnet.tracker.schemas import (
    AnnounceFileRequest,
    AnnounceFileResponse,
    HealthResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    MetaResponse,
    RegisterPeerRequest,
    RegisterPeerResponse,
    SwarmPeerResponse,
    SwarmResponse,
)
from shardnet.tracker.store import TrackerStore


def _error_detail(error: ShardNetError) -> dict[str, Any]:
    return error.to_dict()


def _get_store(request: Request) -> TrackerStore:
    return cast(TrackerStore, request.app.state.tracker_store)


def create_app(settings: TrackerSettings | None = None) -> FastAPI:
    """Create and configure a tracker FastAPI application."""

    resolved_settings = settings or TrackerSettings()
    configure_logging(resolved_settings.log_level)
    logger = get_logger(service=TRACKER_SERVICE_NAME, component="api")
    store = TrackerStore(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await store.initialize()
        app.state.tracker_store = store
        logger.info(
            "tracker_startup",
            host=resolved_settings.host,
            port=resolved_settings.port,
            database_url=resolved_settings.database_url,
            api_prefix=resolved_settings.api_prefix,
        )
        yield
        logger.info("tracker_shutdown")

    app = FastAPI(
        title="ShardNet Tracker",
        version=API_VERSION,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(service=TRACKER_SERVICE_NAME)

    @app.get(f"{API_PREFIX}/meta", response_model=MetaResponse, tags=["system"])
    async def meta() -> MetaResponse:
        return MetaResponse(
            api_version=API_VERSION,
            protocol_version=PROTOCOL_VERSION,
            service=TRACKER_SERVICE_NAME,
        )

    @app.post(
        f"{API_PREFIX}/peers/register",
        response_model=RegisterPeerResponse,
        tags=["peers"],
    )
    async def register_peer(payload: RegisterPeerRequest, request: Request) -> RegisterPeerResponse:
        store = _get_store(request)
        last_seen_at = await store.register_peer(
            peer_id=payload.peer_id,
            host=payload.host,
            port=payload.port,
            client_version=payload.client_version,
        )
        logger.info(
            "peer_registered",
            peer_id=payload.peer_id,
            host=payload.host,
            port=payload.port,
        )
        return RegisterPeerResponse(
            peer_id=payload.peer_id,
            last_seen_at=last_seen_at,
            heartbeat_ttl_seconds=resolved_settings.heartbeat_ttl_seconds,
        )

    @app.post(
        f"{API_PREFIX}/peers/heartbeat",
        response_model=HeartbeatResponse,
        tags=["peers"],
    )
    async def heartbeat_peer(payload: HeartbeatRequest, request: Request) -> HeartbeatResponse:
        store = _get_store(request)
        try:
            last_seen_at = await store.heartbeat_peer(peer_id=payload.peer_id)
        except PeerNotFoundError as error:
            raise HTTPException(status_code=404, detail=_error_detail(error)) from error

        return HeartbeatResponse(
            peer_id=payload.peer_id,
            last_seen_at=last_seen_at,
            heartbeat_ttl_seconds=resolved_settings.heartbeat_ttl_seconds,
        )

    @app.post(
        f"{API_PREFIX}/files/announce",
        response_model=AnnounceFileResponse,
        tags=["files"],
    )
    async def announce_file(payload: AnnounceFileRequest, request: Request) -> AnnounceFileResponse:
        store = _get_store(request)
        try:
            peers_advertising = await store.announce_file(
                peer_id=payload.peer_id,
                info_hash=payload.info_hash,
                file_name=payload.file_name,
                file_size_bytes=payload.file_size_bytes,
                chunk_size_bytes=payload.chunk_size_bytes,
                total_chunks=payload.total_chunks,
                file_sha256=payload.file_sha256,
                chunk_sha256=payload.chunk_sha256,
                available_chunks=payload.available_chunks,
            )
        except PeerNotFoundError as error:
            raise HTTPException(status_code=404, detail=_error_detail(error)) from error
        except FileMetadataConflictError as error:
            raise HTTPException(status_code=409, detail=_error_detail(error)) from error

        logger.info(
            "file_announced",
            peer_id=payload.peer_id,
            info_hash=payload.info_hash,
            available_chunks=len(payload.available_chunks),
        )
        return AnnounceFileResponse(
            info_hash=payload.info_hash,
            peers_advertising=peers_advertising,
        )

    @app.get(
        f"{API_PREFIX}/files/{{info_hash}}/swarm",
        response_model=SwarmResponse,
        tags=["files"],
    )
    async def get_swarm(info_hash: str, request: Request) -> SwarmResponse:
        store = _get_store(request)
        try:
            snapshot = await store.get_swarm(
                info_hash=info_hash,
                ttl_seconds=resolved_settings.heartbeat_ttl_seconds,
            )
        except InfoHashNotFoundError as error:
            raise HTTPException(status_code=404, detail=_error_detail(error)) from error

        return SwarmResponse(
            info_hash=snapshot.file.info_hash,
            file_name=snapshot.file.file_name,
            file_size_bytes=snapshot.file.file_size_bytes,
            chunk_size_bytes=snapshot.file.chunk_size_bytes,
            total_chunks=snapshot.file.total_chunks,
            file_sha256=snapshot.file.file_sha256,
            chunk_sha256=snapshot.file.chunk_sha256,
            swarm_size=len(snapshot.peers),
            seed_count=snapshot.seed_count,
            peers=[
                SwarmPeerResponse(
                    peer_id=peer.peer_id,
                    host=peer.host,
                    port=peer.port,
                    available_chunks=peer.available_chunks,
                    completed=peer.completed,
                    last_seen_at=peer.last_seen_at,
                )
                for peer in snapshot.peers
            ],
        )

    return app
