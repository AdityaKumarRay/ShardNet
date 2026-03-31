"""Centralized configuration models."""

from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

from shardnet.common.constants import API_PREFIX, DEFAULT_CHUNK_SIZE_BYTES, PROTOCOL_VERSION


class ShardNetSettings(BaseSettings):
    """Base settings shared across services."""

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class TrackerSettings(ShardNetSettings):
    """Settings for the tracker API service."""

    host: str = Field(default="0.0.0.0")
    port: PositiveInt = Field(default=8000)
    database_url: str = Field(default="sqlite:///./data/tracker.db")
    heartbeat_ttl_seconds: PositiveInt = Field(default=120)
    api_prefix: str = Field(default=API_PREFIX)

    model_config = SettingsConfigDict(
        env_prefix="TRACKER_",
        env_file=".env",
        extra="ignore",
    )


class ClientSettings(ShardNetSettings):
    """Settings for peer-side client processes."""

    bind_host: str = Field(default="0.0.0.0")
    bind_port: PositiveInt = Field(default=9000)
    data_dir: str = Field(default="./data/client")
    tracker_base_url: str = Field(default="http://127.0.0.1:8000")
    protocol_version: int = Field(default=PROTOCOL_VERSION)
    default_chunk_size_bytes: PositiveInt = Field(default=DEFAULT_CHUNK_SIZE_BYTES)

    model_config = SettingsConfigDict(
        env_prefix="CLIENT_",
        env_file=".env",
        extra="ignore",
    )
