"""Chunk manifest generation and hashing helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from shardnet.client.core.models import FileManifest


def build_file_manifest(file_path: str | Path, chunk_size_bytes: int) -> FileManifest:
    """Create deterministic file/chunk hashes and return a manifest."""

    path = _resolve_path(file_path)
    if chunk_size_bytes <= 0:
        raise ValueError("chunk_size_bytes must be a positive integer")

    file_size = path.stat().st_size
    if file_size <= 0:
        raise ValueError("cannot create a manifest for an empty file")

    file_hasher = hashlib.sha256()
    chunk_hashes: list[str] = []
    for chunk in iter_file_chunks(path, chunk_size_bytes):
        file_hasher.update(chunk)
        chunk_hashes.append(hashlib.sha256(chunk).hexdigest())

    file_sha256 = file_hasher.hexdigest()
    info_hash = _compute_info_hash(
        file_name=path.name,
        file_size_bytes=file_size,
        chunk_size_bytes=chunk_size_bytes,
        file_sha256=file_sha256,
        chunk_sha256=chunk_hashes,
    )

    return FileManifest(
        info_hash=info_hash,
        file_name=path.name,
        file_size_bytes=file_size,
        chunk_size_bytes=chunk_size_bytes,
        total_chunks=len(chunk_hashes),
        file_sha256=file_sha256,
        chunk_sha256=chunk_hashes,
    )


def iter_file_chunks(file_path: str | Path, chunk_size_bytes: int) -> Iterator[bytes]:
    """Yield chunks in deterministic order from disk."""

    path = _resolve_path(file_path)
    with path.open("rb") as file_handle:
        while True:
            chunk = file_handle.read(chunk_size_bytes)
            if not chunk:
                break
            yield chunk


def _compute_info_hash(
    *,
    file_name: str,
    file_size_bytes: int,
    chunk_size_bytes: int,
    file_sha256: str,
    chunk_sha256: list[str],
) -> str:
    payload = {
        "chunk_sha256": chunk_sha256,
        "chunk_size_bytes": chunk_size_bytes,
        "file_name": file_name,
        "file_sha256": file_sha256,
        "file_size_bytes": file_size_bytes,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _resolve_path(file_path: str | Path) -> Path:
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path
