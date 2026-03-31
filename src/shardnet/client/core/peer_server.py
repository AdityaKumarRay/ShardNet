"""Async TCP peer server for serving chunks to other clients."""

from __future__ import annotations

import asyncio
import base64
from contextlib import suppress

from shardnet.client.core.protocol import ProtocolMessage, read_message, send_message
from shardnet.client.core.share_store import ShareStore
from shardnet.common.constants import PROTOCOL_VERSION
from shardnet.common.errors import ProtocolError, TransferError
from shardnet.common.logging import get_logger


class PeerServer:
    """Serve local chunks over the peer protocol."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        peer_id: str,
        share_store: ShareStore,
        read_timeout_seconds: float = 15.0,
    ) -> None:
        self._host = host
        self._port = port
        self._peer_id = peer_id
        self._share_store = share_store
        self._read_timeout_seconds = read_timeout_seconds
        self._server: asyncio.AbstractServer | None = None
        self._logger = get_logger(service="client", component="peer_server", peer_id=peer_id)

    @property
    def port(self) -> int:
        """Return currently bound server port."""

        if self._server is None:
            return self._port

        sockets = getattr(self._server, "sockets", None)
        if not sockets:
            return self._port

        socket = sockets[0]
        return int(socket.getsockname()[1])

    async def start(self) -> None:
        """Start accepting peer protocol connections."""

        if self._server is not None:
            return

        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._host,
            port=self._port,
        )
        self._logger.info("peer_server_started", host=self._host, port=self.port)

    async def stop(self) -> None:
        """Stop server and wait for closure."""

        if self._server is None:
            return

        self._server.close()
        await self._server.wait_closed()
        self._logger.info("peer_server_stopped")
        self._server = None

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            hello = await read_message(reader, timeout_seconds=self._read_timeout_seconds)
            if hello.message_type != "hello":
                await self._send_error(
                    writer,
                    request_id=hello.request_id,
                    code="invalid_handshake",
                    message="First protocol message must be hello.",
                )
                return
            if hello.protocol_version != PROTOCOL_VERSION:
                await self._send_error(
                    writer,
                    request_id=hello.request_id,
                    code="protocol_version_mismatch",
                    message="Peer protocol version is not supported.",
                )
                return

            await send_message(
                writer,
                ProtocolMessage(
                    message_type="hello_ack",
                    protocol_version=PROTOCOL_VERSION,
                    peer_id=self._peer_id,
                    request_id=hello.request_id,
                ),
            )

            while True:
                try:
                    message = await read_message(reader, timeout_seconds=self._read_timeout_seconds)
                except ProtocolError as error:
                    if error.code == "connection_closed":
                        break
                    await self._send_error(
                        writer,
                        request_id=None,
                        code=error.code,
                        message=error.message,
                    )
                    break

                if message.message_type == "piece_request":
                    await self._handle_piece_request(message, writer)
                elif message.message_type == "keepalive":
                    await send_message(
                        writer,
                        ProtocolMessage(
                            message_type="keepalive",
                            protocol_version=PROTOCOL_VERSION,
                            peer_id=self._peer_id,
                            request_id=message.request_id,
                        ),
                    )
                else:
                    await self._send_error(
                        writer,
                        request_id=message.request_id,
                        code="unsupported_message_type",
                        message=f"Unsupported message_type: {message.message_type}",
                    )
                    break
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    async def _handle_piece_request(
        self,
        message: ProtocolMessage,
        writer: asyncio.StreamWriter,
    ) -> None:
        if message.info_hash is None or message.piece_index is None:
            await self._send_error(
                writer,
                request_id=message.request_id,
                code="invalid_piece_request",
                message="piece_request must include info_hash and piece_index.",
            )
            return

        manifest = self._share_store.get_manifest(message.info_hash)
        if manifest is None:
            await self._send_error(
                writer,
                request_id=message.request_id,
                code="info_hash_not_shared",
                message="Requested info_hash is not available on this peer.",
            )
            return

        try:
            chunk_data = self._share_store.read_chunk(message.info_hash, message.piece_index)
        except TransferError as error:
            await self._send_error(
                writer,
                request_id=message.request_id,
                code=error.code,
                message=error.message,
            )
            return

        if chunk_data is None:
            await self._send_error(
                writer,
                request_id=message.request_id,
                code="piece_not_available",
                message="Requested piece is not available on this peer.",
            )
            return

        payload = {
            "chunk_sha256": manifest.chunk_sha256[message.piece_index],
            "data_b64": base64.b64encode(chunk_data).decode("ascii"),
        }
        await send_message(
            writer,
            ProtocolMessage(
                message_type="piece_data",
                protocol_version=PROTOCOL_VERSION,
                request_id=message.request_id,
                peer_id=self._peer_id,
                info_hash=message.info_hash,
                piece_index=message.piece_index,
                payload=payload,
            ),
        )

    async def _send_error(
        self,
        writer: asyncio.StreamWriter,
        *,
        request_id: str | None,
        code: str,
        message: str,
    ) -> None:
        await send_message(
            writer,
            ProtocolMessage(
                message_type="error",
                protocol_version=PROTOCOL_VERSION,
                request_id=request_id,
                peer_id=self._peer_id,
                payload={"code": code, "message": message},
            ),
        )
