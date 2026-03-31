"""SQLite persistence layer for tracker coordination state."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import aiosqlite
from aiosqlite import Row

from shardnet.common.errors import ConfigurationError
from shardnet.tracker.errors import (
    FileMetadataConflictError,
    InfoHashNotFoundError,
    PeerNotFoundError,
)


@dataclass(frozen=True)
class FileRecord:
    """Canonical file metadata keyed by info_hash."""

    info_hash: str
    file_name: str
    file_size_bytes: int
    chunk_size_bytes: int
    total_chunks: int
    file_sha256: str


@dataclass(frozen=True)
class SwarmPeerRecord:
    """Peer state for a specific file swarm."""

    peer_id: str
    host: str
    port: int
    available_chunks: list[int]
    completed: bool
    last_seen_at: int


@dataclass(frozen=True)
class SwarmSnapshot:
    """Swarm view returned to API handlers."""

    file: FileRecord
    peers: list[SwarmPeerRecord]

    @property
    def seed_count(self) -> int:
        return sum(1 for peer in self.peers if peer.completed)


class TrackerStore:
    """Persistence service for tracker APIs."""

    def __init__(self, database_url: str) -> None:
        self._db_path = self._resolve_sqlite_path(database_url)

    @staticmethod
    def _resolve_sqlite_path(database_url: str) -> Path:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ConfigurationError(
                code="invalid_database_url",
                message="Tracker database_url must start with sqlite:///.",
                context={"database_url": database_url},
            )

        raw_path = database_url[len(prefix) :]
        if not raw_path:
            raise ConfigurationError(
                code="invalid_database_url",
                message="Tracker database_url is missing a database path.",
                context={"database_url": database_url},
            )

        db_path = Path(raw_path).expanduser()
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        return db_path

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await aiosqlite.connect(self._db_path)
        conn.row_factory = Row
        await conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            await conn.close()

    async def initialize(self) -> None:
        """Create tracker tables and indexes if missing."""

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._connection() as conn:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS peers (
                    peer_id TEXT PRIMARY KEY,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    client_version TEXT NOT NULL,
                    registered_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS files (
                    info_hash TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    chunk_size_bytes INTEGER NOT NULL,
                    total_chunks INTEGER NOT NULL,
                    file_sha256 TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS peer_file_state (
                    peer_id TEXT NOT NULL,
                    info_hash TEXT NOT NULL,
                    available_chunks TEXT NOT NULL,
                    completed INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (peer_id, info_hash),
                    FOREIGN KEY(peer_id) REFERENCES peers(peer_id) ON DELETE CASCADE,
                    FOREIGN KEY(info_hash) REFERENCES files(info_hash) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_peers_last_seen ON peers(last_seen_at);
                CREATE INDEX IF NOT EXISTS idx_peer_file_state_info_hash
                    ON peer_file_state(info_hash);
                """
            )
            await conn.commit()

    async def cleanup_stale_peers(self, ttl_seconds: int) -> int:
        """Remove peers older than the configured heartbeat TTL."""

        cutoff = int(time.time()) - ttl_seconds
        async with self._connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM peers WHERE last_seen_at < ?",
                (cutoff,),
            )
            await conn.commit()
            rowcount = cursor.rowcount
            if rowcount is None or rowcount < 0:
                return 0
            return rowcount

    async def register_peer(
        self,
        *,
        peer_id: str,
        host: str,
        port: int,
        client_version: str,
    ) -> int:
        """Insert or update a peer and return the last-seen timestamp."""

        now = int(time.time())
        async with self._connection() as conn:
            await conn.execute(
                """
                INSERT INTO peers (peer_id, host, port, client_version, registered_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_id) DO UPDATE SET
                    host = excluded.host,
                    port = excluded.port,
                    client_version = excluded.client_version,
                    last_seen_at = excluded.last_seen_at
                """,
                (peer_id, host, port, client_version, now, now),
            )
            await conn.commit()
        return now

    async def heartbeat_peer(self, *, peer_id: str) -> int:
        """Update peer heartbeat timestamp and return the new timestamp."""

        now = int(time.time())
        async with self._connection() as conn:
            cursor = await conn.execute(
                "UPDATE peers SET last_seen_at = ? WHERE peer_id = ?",
                (now, peer_id),
            )
            await conn.commit()
            rowcount = cursor.rowcount if cursor.rowcount is not None else 0

        if rowcount <= 0:
            raise PeerNotFoundError(peer_id)
        return now

    async def announce_file(
        self,
        *,
        peer_id: str,
        info_hash: str,
        file_name: str,
        file_size_bytes: int,
        chunk_size_bytes: int,
        total_chunks: int,
        file_sha256: str,
        available_chunks: list[int],
    ) -> int:
        """Upsert file metadata and update peer chunk availability."""

        now = int(time.time())
        normalized_chunks = _normalize_chunks(available_chunks, total_chunks)
        completed = 1 if len(normalized_chunks) == total_chunks else 0

        async with self._connection() as conn:
            peer_cursor = await conn.execute(
                "SELECT peer_id FROM peers WHERE peer_id = ?",
                (peer_id,),
            )
            peer_row = await peer_cursor.fetchone()
            if peer_row is None:
                raise PeerNotFoundError(peer_id)

            metadata_cursor = await conn.execute(
                """
                SELECT file_name, file_size_bytes, chunk_size_bytes, total_chunks, file_sha256
                FROM files
                WHERE info_hash = ?
                """,
                (info_hash,),
            )
            metadata_row = await metadata_cursor.fetchone()

            if metadata_row is None:
                await conn.execute(
                    """
                    INSERT INTO files (
                        info_hash,
                        file_name,
                        file_size_bytes,
                        chunk_size_bytes,
                        total_chunks,
                        file_sha256,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        info_hash,
                        file_name,
                        file_size_bytes,
                        chunk_size_bytes,
                        total_chunks,
                        file_sha256,
                        now,
                        now,
                    ),
                )
            elif _has_metadata_conflict(
                metadata_row,
                file_name=file_name,
                file_size_bytes=file_size_bytes,
                chunk_size_bytes=chunk_size_bytes,
                total_chunks=total_chunks,
                file_sha256=file_sha256,
            ):
                raise FileMetadataConflictError(info_hash)
            else:
                await conn.execute(
                    "UPDATE files SET updated_at = ? WHERE info_hash = ?",
                    (now, info_hash),
                )

            await conn.execute(
                """
                INSERT INTO peer_file_state (
                    peer_id,
                    info_hash,
                    available_chunks,
                    completed,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(peer_id, info_hash) DO UPDATE SET
                    available_chunks = excluded.available_chunks,
                    completed = excluded.completed,
                    updated_at = excluded.updated_at
                """,
                (
                    peer_id,
                    info_hash,
                    json.dumps(normalized_chunks, separators=(",", ":")),
                    completed,
                    now,
                ),
            )

            count_cursor = await conn.execute(
                "SELECT COUNT(*) AS peers_advertising FROM peer_file_state WHERE info_hash = ?",
                (info_hash,),
            )
            count_row = await count_cursor.fetchone()

            await conn.commit()

        if count_row is None:
            return 0
        return int(cast(Any, count_row["peers_advertising"]))

    async def get_swarm(self, *, info_hash: str, ttl_seconds: int) -> SwarmSnapshot:
        """Fetch metadata and currently active peers for an info_hash."""

        cutoff = int(time.time()) - ttl_seconds
        async with self._connection() as conn:
            await conn.execute(
                "DELETE FROM peers WHERE last_seen_at < ?",
                (cutoff,),
            )

            file_cursor = await conn.execute(
                """
                SELECT
                    info_hash,
                    file_name,
                    file_size_bytes,
                    chunk_size_bytes,
                    total_chunks,
                    file_sha256
                FROM files
                WHERE info_hash = ?
                """,
                (info_hash,),
            )
            file_row = await file_cursor.fetchone()
            if file_row is None:
                raise InfoHashNotFoundError(info_hash)

            peer_cursor = await conn.execute(
                """
                SELECT
                    p.peer_id,
                    p.host,
                    p.port,
                    p.last_seen_at,
                    s.available_chunks,
                    s.completed
                FROM peer_file_state AS s
                INNER JOIN peers AS p ON p.peer_id = s.peer_id
                WHERE s.info_hash = ?
                ORDER BY s.completed DESC, p.last_seen_at DESC, p.peer_id ASC
                """,
                (info_hash,),
            )
            peer_rows = cast(list[Row], await peer_cursor.fetchall())

            await conn.commit()

        assert file_row is not None

        file_record = FileRecord(
            info_hash=str(file_row["info_hash"]),
            file_name=str(file_row["file_name"]),
            file_size_bytes=int(file_row["file_size_bytes"]),
            chunk_size_bytes=int(file_row["chunk_size_bytes"]),
            total_chunks=int(file_row["total_chunks"]),
            file_sha256=str(file_row["file_sha256"]),
        )

        peers = [
            SwarmPeerRecord(
                peer_id=str(row["peer_id"]),
                host=str(row["host"]),
                port=int(row["port"]),
                available_chunks=_parse_chunks(
                    str(row["available_chunks"]),
                    file_record.total_chunks,
                ),
                completed=bool(row["completed"]),
                last_seen_at=int(row["last_seen_at"]),
            )
            for row in peer_rows
        ]
        return SwarmSnapshot(file=file_record, peers=peers)


def _has_metadata_conflict(
    row: Row,
    *,
    file_name: str,
    file_size_bytes: int,
    chunk_size_bytes: int,
    total_chunks: int,
    file_sha256: str,
) -> bool:
    return any(
        [
            str(row["file_name"]) != file_name,
            int(row["file_size_bytes"]) != file_size_bytes,
            int(row["chunk_size_bytes"]) != chunk_size_bytes,
            int(row["total_chunks"]) != total_chunks,
            str(row["file_sha256"]) != file_sha256,
        ]
    )


def _normalize_chunks(chunks: list[int], total_chunks: int) -> list[int]:
    unique_chunks = {chunk for chunk in chunks if 0 <= chunk < total_chunks}
    return sorted(unique_chunks)


def _parse_chunks(raw_chunks: str, total_chunks: int) -> list[int]:
    try:
        parsed = json.loads(raw_chunks)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    normalized: set[int] = set()
    for value in parsed:
        if isinstance(value, int) and 0 <= value < total_chunks:
            normalized.add(value)
    return sorted(normalized)
