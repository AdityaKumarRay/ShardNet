"""Resumable local download state and chunk persistence."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Literal, cast

from shardnet.client.core.models import DownloadProgress, FileManifest
from shardnet.common.errors import TransferError


class DownloadStore:
    """Persist resumable download metadata and chunk completion state."""

    def __init__(self, data_dir: str | Path) -> None:
        base_dir = _resolve_path(data_dir)
        self._state_dir = base_dir / "state"
        self._partials_dir = base_dir / "partials"
        self._db_path = self._state_dir / "downloads.db"
        self._initialized = False

    def initialize(self) -> None:
        """Create local directories and database schema."""

        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._partials_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    info_hash TEXT PRIMARY KEY,
                    manifest_json TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    temp_path TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'completed')),
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS download_chunks (
                    info_hash TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'complete')),
                    completed_at INTEGER,
                    PRIMARY KEY (info_hash, chunk_index),
                    FOREIGN KEY(info_hash) REFERENCES downloads(info_hash) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_download_chunks_status
                    ON download_chunks(info_hash, status);
                """
            )
            conn.commit()
        finally:
            conn.close()

        self._initialized = True

    def create_or_resume_download(
        self,
        manifest: FileManifest,
        target_path: str | Path,
    ) -> DownloadProgress:
        """Create download metadata if missing and return current progress."""

        target = _resolve_path(target_path)
        temp_path = self._partials_dir / f"{manifest.info_hash}.part"
        now = _now_ts()

        with self._connect() as conn:
            row = conn.execute(
                "SELECT manifest_json FROM downloads WHERE info_hash = ?",
                (manifest.info_hash,),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO downloads (
                        info_hash,
                        manifest_json,
                        target_path,
                        temp_path,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        manifest.info_hash,
                        manifest.model_dump_json(),
                        str(target),
                        str(temp_path),
                        now,
                        now,
                    ),
                )
                conn.executemany(
                    """
                    INSERT INTO download_chunks (info_hash, chunk_index, status, completed_at)
                    VALUES (?, ?, 'pending', NULL)
                    """,
                    [(manifest.info_hash, index) for index in range(manifest.total_chunks)],
                )
            else:
                stored_manifest = FileManifest.model_validate_json(str(row["manifest_json"]))
                if stored_manifest != manifest:
                    raise TransferError(
                        code="manifest_mismatch",
                        message="Existing download manifest differs from provided manifest.",
                        context={"info_hash": manifest.info_hash},
                    )
                conn.execute(
                    """
                    UPDATE downloads
                    SET target_path = ?, updated_at = ?
                    WHERE info_hash = ?
                    """,
                    (str(target), now, manifest.info_hash),
                )

            conn.commit()

        _ensure_partial_file(temp_path=temp_path, file_size_bytes=manifest.file_size_bytes)
        return self.get_progress(manifest.info_hash)

    def write_chunk(self, manifest: FileManifest, chunk_index: int, chunk_data: bytes) -> None:
        """Validate and persist a downloaded chunk, then mark it complete."""

        if chunk_index < 0 or chunk_index >= manifest.total_chunks:
            raise TransferError(
                code="invalid_chunk_index",
                message="Chunk index is outside manifest bounds.",
                context={"chunk_index": chunk_index, "total_chunks": manifest.total_chunks},
            )

        expected_size = manifest.chunk_size_for_index(chunk_index)
        if len(chunk_data) != expected_size:
            raise TransferError(
                code="invalid_chunk_size",
                message="Chunk length does not match manifest expectations.",
                context={"chunk_index": chunk_index, "expected_size": expected_size},
            )

        expected_hash = manifest.chunk_sha256[chunk_index]
        actual_hash = hashlib.sha256(chunk_data).hexdigest()
        if actual_hash != expected_hash:
            raise TransferError(
                code="chunk_hash_mismatch",
                message="Chunk failed SHA-256 verification.",
                context={
                    "chunk_index": chunk_index,
                    "expected_hash": expected_hash,
                    "actual_hash": actual_hash,
                },
            )

        with self._connect() as conn:
            download_row = conn.execute(
                "SELECT temp_path FROM downloads WHERE info_hash = ?",
                (manifest.info_hash,),
            ).fetchone()
            if download_row is None:
                raise TransferError(
                    code="download_not_initialized",
                    message="Download must be initialized before writing chunks.",
                    context={"info_hash": manifest.info_hash},
                )

            temp_path = Path(str(download_row["temp_path"]))
            _ensure_partial_file(temp_path=temp_path, file_size_bytes=manifest.file_size_bytes)
            with temp_path.open("r+b") as file_handle:
                file_handle.seek(chunk_index * manifest.chunk_size_bytes)
                file_handle.write(chunk_data)

            conn.execute(
                """
                UPDATE download_chunks
                SET status = 'complete', completed_at = ?
                WHERE info_hash = ? AND chunk_index = ?
                """,
                (_now_ts(), manifest.info_hash, chunk_index),
            )
            conn.execute(
                "UPDATE downloads SET updated_at = ? WHERE info_hash = ?",
                (_now_ts(), manifest.info_hash),
            )
            conn.commit()

    def missing_chunks(self, info_hash: str) -> list[int]:
        """Return chunk indexes not yet marked complete."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_index
                FROM download_chunks
                WHERE info_hash = ? AND status = 'pending'
                ORDER BY chunk_index ASC
                """,
                (info_hash,),
            ).fetchall()

        return [int(row["chunk_index"]) for row in rows]

    def completed_chunks(self, info_hash: str) -> list[int]:
        """Return chunk indexes already marked complete."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_index
                FROM download_chunks
                WHERE info_hash = ? AND status = 'complete'
                ORDER BY chunk_index ASC
                """,
                (info_hash,),
            ).fetchall()

        return [int(row["chunk_index"]) for row in rows]

    def get_progress(self, info_hash: str) -> DownloadProgress:
        """Build a progress snapshot for a tracked download."""

        with self._connect() as conn:
            download_row = conn.execute(
                "SELECT manifest_json, status FROM downloads WHERE info_hash = ?",
                (info_hash,),
            ).fetchone()

        if download_row is None:
            raise TransferError(
                code="download_not_found",
                message="No download state exists for the requested info_hash.",
                context={"info_hash": info_hash},
            )

        manifest = FileManifest.model_validate_json(str(download_row["manifest_json"]))
        completed = self.completed_chunks(info_hash)
        missing = self.missing_chunks(info_hash)
        status = str(download_row["status"])
        if status not in {"active", "completed"}:
            raise TransferError(
                code="invalid_download_state",
                message="Download state has an invalid status value.",
                context={"info_hash": info_hash, "status": status},
            )

        return DownloadProgress(
            info_hash=info_hash,
            total_chunks=manifest.total_chunks,
            completed_chunks=completed,
            missing_chunks=missing,
            status=cast(Literal["active", "completed"], status),
        )

    def finalize_download(self, info_hash: str) -> Path:
        """Verify final file hash and move partial file to target path."""

        with self._connect() as conn:
            download_row = conn.execute(
                "SELECT manifest_json, temp_path, target_path FROM downloads WHERE info_hash = ?",
                (info_hash,),
            ).fetchone()
            if download_row is None:
                raise TransferError(
                    code="download_not_found",
                    message="No download state exists for the requested info_hash.",
                    context={"info_hash": info_hash},
                )

            pending_row = conn.execute(
                """
                SELECT COUNT(*) AS pending_count
                FROM download_chunks
                WHERE info_hash = ? AND status = 'pending'
                """,
                (info_hash,),
            ).fetchone()

            pending_count = int(pending_row["pending_count"]) if pending_row is not None else 0
            if pending_count > 0:
                raise TransferError(
                    code="download_incomplete",
                    message="Cannot finalize download while chunks are still pending.",
                    context={"info_hash": info_hash, "pending_chunks": pending_count},
                )

            manifest = FileManifest.model_validate_json(str(download_row["manifest_json"]))
            temp_path = Path(str(download_row["temp_path"]))
            target_path = Path(str(download_row["target_path"]))

            actual_file_hash = _sha256_file(temp_path)
            if actual_file_hash != manifest.file_sha256:
                raise TransferError(
                    code="file_hash_mismatch",
                    message="Final file hash verification failed.",
                    context={
                        "info_hash": info_hash,
                        "expected_hash": manifest.file_sha256,
                        "actual_hash": actual_file_hash,
                    },
                )

            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_path), str(target_path))

            conn.execute(
                "UPDATE downloads SET status = 'completed', updated_at = ? WHERE info_hash = ?",
                (_now_ts(), info_hash),
            )
            conn.commit()

        return target_path

    def _connect(self) -> sqlite3.Connection:
        if not self._initialized:
            self.initialize()

        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _ensure_partial_file(temp_path: Path, file_size_bytes: int) -> None:
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("a+b") as file_handle:
        file_handle.truncate(file_size_bytes)


def _sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file_handle:
        while True:
            chunk = file_handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _now_ts() -> int:
    return int(time.time())
