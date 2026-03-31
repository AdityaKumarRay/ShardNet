"""Typed models shared by client core components."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HASH_PATTERN = r"^[a-fA-F0-9]{64}$"


class FileManifest(BaseModel):
    """Stable metadata used by tracker and peers for chunk validation."""

    info_hash: str = Field(pattern=HASH_PATTERN)
    file_name: str = Field(min_length=1, max_length=256)
    file_size_bytes: int = Field(gt=0)
    chunk_size_bytes: int = Field(gt=0)
    total_chunks: int = Field(gt=0)
    file_sha256: str = Field(pattern=HASH_PATTERN)
    chunk_sha256: list[str] = Field(min_length=1)

    @field_validator("info_hash", "file_sha256")
    @classmethod
    def normalize_hashes(cls, value: str) -> str:
        return value.lower()

    @field_validator("chunk_sha256")
    @classmethod
    def normalize_chunk_hashes(cls, value: list[str]) -> list[str]:
        return [chunk_hash.lower() for chunk_hash in value]

    @model_validator(mode="after")
    def validate_chunk_shape(self) -> "FileManifest":
        if len(self.chunk_sha256) != self.total_chunks:
            raise ValueError("chunk_sha256 length must equal total_chunks")

        max_size = self.chunk_size_bytes * self.total_chunks
        min_size = (self.chunk_size_bytes * (self.total_chunks - 1)) + 1
        if not (min_size <= self.file_size_bytes <= max_size):
            raise ValueError("file_size_bytes does not match chunk_size_bytes/total_chunks")

        return self

    def chunk_size_for_index(self, chunk_index: int) -> int:
        """Return expected byte size for a chunk index."""

        if chunk_index < 0 or chunk_index >= self.total_chunks:
            raise IndexError("chunk index out of range")

        if chunk_index < self.total_chunks - 1:
            return self.chunk_size_bytes

        remainder = self.file_size_bytes % self.chunk_size_bytes
        return remainder if remainder != 0 else self.chunk_size_bytes


class DownloadProgress(BaseModel):
    """Snapshot of resumable state for a tracked download."""

    info_hash: str
    total_chunks: int
    completed_chunks: list[int]
    missing_chunks: list[int]
    status: Literal["active", "completed"]
