"""FastAPI app factory for the tracker service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shardnet.common.config import TrackerSettings
from shardnet.common.constants import (
    API_PREFIX,
    API_VERSION,
    PROTOCOL_VERSION,
    TRACKER_SERVICE_NAME,
)
from shardnet.common.logging import configure_logging, get_logger
from shardnet.tracker.schemas import HealthResponse, MetaResponse


def create_app(settings: TrackerSettings | None = None) -> FastAPI:
    """Create and configure a tracker FastAPI application."""

    resolved_settings = settings or TrackerSettings()
    configure_logging(resolved_settings.log_level)
    logger = get_logger(service=TRACKER_SERVICE_NAME, component="api")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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

    return app
