"""Tracker API schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HASH_PATTERN = r"^[a-fA-F0-9]{64}$"


class ErrorResponse(BaseModel):
    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class RegisterPeerRequest(BaseModel):
    peer_id: str = Field(min_length=3, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    client_version: str = Field(default="unknown", min_length=1, max_length=64)


class RegisterPeerResponse(BaseModel):
    peer_id: str
    last_seen_at: int
    heartbeat_ttl_seconds: int


class HeartbeatRequest(BaseModel):
    peer_id: str = Field(min_length=3, max_length=128)


class HeartbeatResponse(BaseModel):
    peer_id: str
    last_seen_at: int
    heartbeat_ttl_seconds: int


class AnnounceFileRequest(BaseModel):
    peer_id: str = Field(min_length=3, max_length=128)
    info_hash: str = Field(pattern=HASH_PATTERN)
    file_name: str = Field(min_length=1, max_length=256)
    file_size_bytes: int = Field(gt=0)
    chunk_size_bytes: int = Field(gt=0)
    total_chunks: int = Field(gt=0)
    file_sha256: str = Field(pattern=HASH_PATTERN)
    available_chunks: list[int] = Field(default_factory=list)

    @field_validator("info_hash", "file_sha256")
    @classmethod
    def normalize_hash(cls, value: str) -> str:
        return value.lower()

    @field_validator("available_chunks")
    @classmethod
    def normalize_chunks(cls, value: list[int]) -> list[int]:
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_chunk_bounds(self) -> "AnnounceFileRequest":
        for chunk in self.available_chunks:
            if chunk < 0 or chunk >= self.total_chunks:
                raise ValueError("available_chunks entries must satisfy 0 <= chunk < total_chunks")
        return self


class AnnounceFileResponse(BaseModel):
    info_hash: str
    peers_advertising: int


class SwarmPeerResponse(BaseModel):
    peer_id: str
    host: str
    port: int
    available_chunks: list[int]
    completed: bool
    last_seen_at: int


class SwarmResponse(BaseModel):
    info_hash: str
    file_name: str
    file_size_bytes: int
    chunk_size_bytes: int
    total_chunks: int
    file_sha256: str
    swarm_size: int
    seed_count: int
    peers: list[SwarmPeerResponse]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str


class MetaResponse(BaseModel):
    api_version: str
    protocol_version: int
    service: str
