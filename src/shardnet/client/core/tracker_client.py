"""HTTP tracker client used by peer runtime flows."""

from __future__ import annotations

import httpx

from shardnet.client.core.models import FileManifest
from shardnet.common.errors import TransferError
from shardnet.tracker.schemas import (
    AnnounceFileRequest,
    AnnounceFileResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    RegisterPeerRequest,
    RegisterPeerResponse,
    SwarmResponse,
)


class TrackerClient:
    """Thin typed wrapper over tracker REST endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def register_peer(
        self,
        *,
        peer_id: str,
        host: str,
        port: int,
        client_version: str,
    ) -> RegisterPeerResponse:
        request = RegisterPeerRequest(
            peer_id=peer_id,
            host=host,
            port=port,
            client_version=client_version,
        )
        response = await self._client.post(
            "/api/v1/peers/register",
            json=request.model_dump(mode="json"),
        )
        data = _parse_response(response)
        return RegisterPeerResponse.model_validate(data)

    async def heartbeat(self, *, peer_id: str) -> HeartbeatResponse:
        request = HeartbeatRequest(peer_id=peer_id)
        response = await self._client.post(
            "/api/v1/peers/heartbeat",
            json=request.model_dump(mode="json"),
        )
        data = _parse_response(response)
        return HeartbeatResponse.model_validate(data)

    async def announce_file(
        self,
        *,
        peer_id: str,
        manifest: FileManifest,
        available_chunks: list[int],
    ) -> AnnounceFileResponse:
        request = AnnounceFileRequest(
            peer_id=peer_id,
            info_hash=manifest.info_hash,
            file_name=manifest.file_name,
            file_size_bytes=manifest.file_size_bytes,
            chunk_size_bytes=manifest.chunk_size_bytes,
            total_chunks=manifest.total_chunks,
            file_sha256=manifest.file_sha256,
            chunk_sha256=manifest.chunk_sha256,
            available_chunks=available_chunks,
        )
        response = await self._client.post(
            "/api/v1/files/announce",
            json=request.model_dump(mode="json"),
        )
        data = _parse_response(response)
        return AnnounceFileResponse.model_validate(data)

    async def get_swarm(self, *, info_hash: str) -> SwarmResponse:
        response = await self._client.get(f"/api/v1/files/{info_hash}/swarm")
        data = _parse_response(response)
        return SwarmResponse.model_validate(data)


def _parse_response(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as error:
        raise TransferError(
            code="tracker_invalid_response",
            message="Tracker returned a non-JSON response.",
            context={"status_code": response.status_code},
        ) from error

    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            code = str(detail.get("code", "tracker_request_failed"))
            message = str(detail.get("message", "Tracker request failed."))
            context = detail.get("context", {})
            if not isinstance(context, dict):
                context = {}
            context["status_code"] = response.status_code
            raise TransferError(code=code, message=message, context=context)

        raise TransferError(
            code="tracker_request_failed",
            message="Tracker request failed.",
            context={"status_code": response.status_code},
        )

    if not isinstance(payload, dict):
        raise TransferError(
            code="tracker_invalid_response",
            message="Tracker returned an unexpected response shape.",
            context={"status_code": response.status_code},
        )

    return payload
