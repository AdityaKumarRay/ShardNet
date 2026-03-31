"""Length-prefixed peer protocol primitives."""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from shardnet.common.constants import PROTOCOL_VERSION
from shardnet.common.errors import ProtocolError

MAX_FRAME_SIZE_BYTES = 16 * 1024 * 1024


MessageType = Literal[
    "hello",
    "hello_ack",
    "piece_request",
    "piece_data",
    "error",
    "keepalive",
]


class ProtocolMessage(BaseModel):
    """Wire-format message payload serialized as JSON."""

    protocol_version: int = Field(default=PROTOCOL_VERSION)
    message_type: MessageType
    request_id: str | None = None
    peer_id: str | None = None
    info_hash: str | None = None
    piece_index: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_shape(self) -> ProtocolMessage:
        if self.message_type in {"piece_request", "piece_data"}:
            if self.info_hash is None:
                raise ValueError("info_hash is required for piece messages")
            if self.piece_index is None:
                raise ValueError("piece_index is required for piece messages")
        return self


async def send_message(writer: asyncio.StreamWriter, message: ProtocolMessage) -> None:
    """Serialize and write a single framed message."""

    payload = json.dumps(message.model_dump(mode="json"), separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_SIZE_BYTES:
        raise ProtocolError(
            code="frame_too_large",
            message="Protocol frame exceeds maximum size.",
            context={"frame_size": len(payload), "max_frame_size": MAX_FRAME_SIZE_BYTES},
        )

    writer.write(struct.pack(">I", len(payload)))
    writer.write(payload)
    await writer.drain()


async def read_message(
    reader: asyncio.StreamReader,
    timeout_seconds: float | None = None,
) -> ProtocolMessage:
    """Read, decode, and validate one framed message."""

    try:
        header = await _read_exactly(reader, 4, timeout_seconds)
        frame_size = struct.unpack(">I", header)[0]
        if frame_size <= 0 or frame_size > MAX_FRAME_SIZE_BYTES:
            raise ProtocolError(
                code="invalid_frame_size",
                message="Frame size is invalid.",
                context={"frame_size": frame_size},
            )

        payload = await _read_exactly(reader, frame_size, timeout_seconds)
    except asyncio.IncompleteReadError as error:
        raise ProtocolError(
            code="connection_closed",
            message="Peer closed the connection while reading a frame.",
        ) from error
    except TimeoutError as error:
        raise ProtocolError(
            code="read_timeout",
            message="Timed out while waiting for peer message.",
        ) from error

    try:
        return ProtocolMessage.model_validate_json(payload)
    except ValidationError as error:
        raise ProtocolError(
            code="invalid_message",
            message="Peer message failed schema validation.",
        ) from error


async def _read_exactly(
    reader: asyncio.StreamReader,
    size: int,
    timeout_seconds: float | None,
) -> bytes:
    if timeout_seconds is None:
        return await reader.readexactly(size)
    return await asyncio.wait_for(reader.readexactly(size), timeout=timeout_seconds)
