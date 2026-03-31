"""Persistent local share catalog for serving chunks to peers."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from shardnet.client.core.manifest import build_file_manifest
from shardnet.client.core.models import FileManifest
from shardnet.common.errors import TransferError


class ShareStore:
    """Manage share metadata and read verified chunks for active peer serving."""

    def __init__(self, data_dir: str | Path) -> None:
        base_dir = _resolve_path(data_dir)
        self._state_dir = base_dir / "state"
        self._db_path = self._state_dir / "shares.db"
        self._initialized = False

    def initialize(self) -> None:
        """Create local metadata schema for shared files."""

        self._state_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS shared_files (
                    info_hash TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shared_files_updated_at ON shared_files(updated_at);
                """
            )
            conn.commit()
        finally:
            conn.close()

        self._initialized = True

    def register_file(self, file_path: str | Path, chunk_size_bytes: int) -> FileManifest:
        """Hash a local file and register it in the share catalog."""

        path = _resolve_path(file_path)
        if not path.is_file():
            raise TransferError(
                code="shared_file_not_found",
                message="Cannot register a file that does not exist.",
                context={"file_path": str(path)},
            )

        manifest = build_file_manifest(path, chunk_size_bytes=chunk_size_bytes)
        now = _now_ts()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO shared_files (
                    info_hash,
                    file_path,
                    manifest_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(info_hash) DO UPDATE SET
                    file_path = excluded.file_path,
                    manifest_json = excluded.manifest_json,
                    updated_at = excluded.updated_at
                """,
                (manifest.info_hash, str(path), manifest.model_dump_json(), now, now),
            )
            conn.commit()

        return manifest

    def get_manifest(self, info_hash: str) -> FileManifest | None:
        """Load manifest metadata for a registered share."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT manifest_json FROM shared_files WHERE info_hash = ?",
                (info_hash,),
            ).fetchone()

        if row is None:
            return None
        return FileManifest.model_validate_json(str(row["manifest_json"]))

    def read_chunk(self, info_hash: str, chunk_index: int) -> bytes | None:
        """Read and verify one chunk from a shared file."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT file_path, manifest_json FROM shared_files WHERE info_hash = ?",
                (info_hash,),
            ).fetchone()

        if row is None:
            return None

        file_path = Path(str(row["file_path"]))
        manifest = FileManifest.model_validate_json(str(row["manifest_json"]))
        if chunk_index < 0 or chunk_index >= manifest.total_chunks:
            return None
        if not file_path.is_file():
            raise TransferError(
                code="shared_file_missing",
                message="Registered shared file is no longer present on disk.",
                context={"file_path": str(file_path), "info_hash": info_hash},
            )

        expected_size = manifest.chunk_size_for_index(chunk_index)
        with file_path.open("rb") as file_handle:
            file_handle.seek(chunk_index * manifest.chunk_size_bytes)
            chunk_data = file_handle.read(expected_size)

        actual_hash = hashlib.sha256(chunk_data).hexdigest()
        expected_hash = manifest.chunk_sha256[chunk_index]
        if actual_hash != expected_hash:
            raise TransferError(
                code="shared_chunk_corrupt",
                message="Shared chunk hash does not match manifest metadata.",
                context={"info_hash": info_hash, "chunk_index": chunk_index},
            )

        return chunk_data

    def _connect(self) -> sqlite3.Connection:
        if not self._initialized:
            self.initialize()

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _now_ts() -> int:
    return int(time.time())
