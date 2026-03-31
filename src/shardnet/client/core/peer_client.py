"""Async peer client for requesting verified chunks from remote peers."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from contextlib import suppress
from uuid import uuid4

from shardnet.client.core.protocol import ProtocolMessage, read_message, send_message
from shardnet.common.constants import PROTOCOL_VERSION
from shardnet.common.errors import ProtocolError


class PeerClient:
    """Client-side helper for point-to-point chunk retrieval."""

    def __init__(
        self,
        *,
        peer_id: str,
        timeout_seconds: float = 5.0,
        retry_attempts: int = 2,
    ) -> None:
        self._peer_id = peer_id
        self._timeout_seconds = timeout_seconds
        self._retry_attempts = retry_attempts

    async def request_chunk(
        self,
        *,
        host: str,
        port: int,
        info_hash: str,
        chunk_index: int,
    ) -> bytes:
        """Request a chunk with retry-on-failure behavior."""

        last_error: Exception | None = None
        for attempt in range(self._retry_attempts + 1):
            try:
                return await self._request_chunk_once(
                    host=host,
                    port=port,
                    info_hash=info_hash,
                    chunk_index=chunk_index,
                )
            except (TimeoutError, OSError, ProtocolError) as error:
                last_error = error
                if attempt >= self._retry_attempts:
                    break
                await asyncio.sleep(min(0.1 * (2**attempt), 1.0))

        if isinstance(last_error, ProtocolError):
            raise last_error

        raise ProtocolError(
            code="chunk_request_failed",
            message="Failed to fetch chunk from peer after retries.",
            context={
                "host": host,
                "port": port,
                "info_hash": info_hash,
                "chunk_index": chunk_index,
                "retries": self._retry_attempts,
                "last_error": str(last_error) if last_error is not None else "unknown",
            },
        )

    async def _request_chunk_once(
        self,
        *,
        host: str,
        port: int,
        info_hash: str,
        chunk_index: int,
    ) -> bytes:
        request_id = str(uuid4())
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=host, port=port),
            timeout=self._timeout_seconds,
        )

        try:
            await send_message(
                writer,
                ProtocolMessage(
                    message_type="hello",
                    protocol_version=PROTOCOL_VERSION,
                    request_id=request_id,
                    peer_id=self._peer_id,
                ),
            )
            hello_ack = await read_message(reader, timeout_seconds=self._timeout_seconds)
            if hello_ack.message_type != "hello_ack":
                raise ProtocolError(
                    code="handshake_failed",
                    message="Peer did not acknowledge hello handshake.",
                )

            await send_message(
                writer,
                ProtocolMessage(
                    message_type="piece_request",
                    protocol_version=PROTOCOL_VERSION,
                    request_id=request_id,
                    peer_id=self._peer_id,
                    info_hash=info_hash,
                    piece_index=chunk_index,
                ),
            )

            while True:
                response = await read_message(reader, timeout_seconds=self._timeout_seconds)
                if response.message_type == "keepalive":
                    continue

                if response.request_id != request_id:
                    continue

                if response.message_type == "error":
                    error_code = str(response.payload.get("code", "peer_error"))
                    error_message = str(response.payload.get("message", "Peer returned an error."))
                    raise ProtocolError(code=error_code, message=error_message)

                if response.message_type != "piece_data":
                    raise ProtocolError(
                        code="unexpected_response",
                        message=f"Unexpected message_type: {response.message_type}",
                    )

                data_b64 = response.payload.get("data_b64")
                if not isinstance(data_b64, str):
                    raise ProtocolError(
                        code="invalid_piece_payload",
                        message="piece_data message missing base64 payload.",
                    )

                chunk_data = base64.b64decode(data_b64.encode("ascii"))
                expected_hash = response.payload.get("chunk_sha256")
                if isinstance(expected_hash, str):
                    actual_hash = hashlib.sha256(chunk_data).hexdigest()
                    if actual_hash != expected_hash:
                        raise ProtocolError(
                            code="chunk_hash_mismatch",
                            message="Peer chunk payload failed hash verification.",
                            context={"expected_hash": expected_hash, "actual_hash": actual_hash},
                        )

                return chunk_data
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
