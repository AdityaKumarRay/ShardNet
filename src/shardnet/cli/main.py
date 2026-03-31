"""CLI surface for tracker and peer workflows."""

import asyncio
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
import uvicorn

from shardnet.client.core.download_store import DownloadStore
from shardnet.client.core.manifest import build_file_manifest
from shardnet.client.core.node import PeerNode
from shardnet.client.core.share_store import ShareStore
from shardnet.client.core.tracker_client import TrackerClient
from shardnet.common.config import ClientSettings, TrackerSettings
from shardnet.common.constants import API_VERSION, PROTOCOL_VERSION
from shardnet.common.errors import TransferError
from shardnet.common.logging import configure_logging, get_logger

app = typer.Typer(help="ShardNet command-line interface.")
tracker_app = typer.Typer(help="Tracker service commands.")
client_app = typer.Typer(help="Peer client commands.")

app.add_typer(tracker_app, name="tracker")
app.add_typer(client_app, name="client")


@app.command("version")
def version() -> None:
    """Print API and protocol versions."""

    typer.echo(f"ShardNet API {API_VERSION} | protocol {PROTOCOL_VERSION}")


@tracker_app.command("run")
def tracker_run(
    host: str | None = typer.Option(default=None, help="Tracker bind host."),
    port: int | None = typer.Option(default=None, help="Tracker bind port."),
) -> None:
    """Run the tracker service from the CLI."""

    settings = TrackerSettings()
    bind_host = host or settings.host
    bind_port = port or settings.port

    configure_logging(settings.log_level)
    logger = get_logger(service="cli", component="tracker")
    logger.info("tracker_run_command", host=bind_host, port=bind_port)

    uvicorn.run(
        "shardnet.tracker.api:create_app",
        factory=True,
        host=bind_host,
        port=bind_port,
        log_level=settings.log_level.lower(),
    )


@client_app.command("info")
def client_info() -> None:
    """Show baseline client runtime details."""

    settings = ClientSettings()
    typer.echo(
        "Client core supports manifest + chunk hashing and resumable local download state. "
        f"Default chunk size: {settings.default_chunk_size_bytes} bytes."
    )


@client_app.command("manifest")
def client_manifest(
    file_path: Annotated[
        Path,
        typer.Argument(
            ...,
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="File to hash and split into chunk metadata.",
        ),
    ],
    chunk_size_bytes: Annotated[
        int | None,
        typer.Option(
            "--chunk-size",
            "-c",
            min=1,
            help="Chunk size in bytes. Uses client default when omitted.",
        ),
    ] = None,
) -> None:
    """Generate a file manifest from local disk."""

    settings = ClientSettings()
    resolved_chunk_size = chunk_size_bytes or settings.default_chunk_size_bytes
    manifest = build_file_manifest(file_path, resolved_chunk_size)
    typer.echo(manifest.model_dump_json(indent=2))


@client_app.command("run")
def client_run(
    peer_id: Annotated[
        str | None,
        typer.Option(help="Peer ID. Generates one automatically when omitted."),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option(help="Bind host for incoming peer connections."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(help="Bind port for incoming peer connections."),
    ] = None,
    data_dir: Annotated[
        str | None,
        typer.Option(help="Local runtime state directory."),
    ] = None,
    tracker_url: Annotated[
        str | None,
        typer.Option(help="Tracker base URL."),
    ] = None,
    share_files: Annotated[
        list[Path] | None,
        typer.Option(
            "--share-file",
            "-s",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="File(s) to announce immediately after startup.",
        ),
    ] = None,
    chunk_size_bytes: Annotated[
        int | None,
        typer.Option("--chunk-size", "-c", min=1, help="Chunk size for new shared files."),
    ] = None,
) -> None:
    """Run a peer node and optionally start sharing one or more files."""

    settings = ClientSettings()
    resolved_peer_id = _resolve_peer_id(peer_id)
    resolved_host = host or settings.bind_host
    resolved_port = port or settings.bind_port
    resolved_data_dir = data_dir or settings.data_dir
    resolved_tracker_url = tracker_url or settings.tracker_base_url
    resolved_chunk_size = chunk_size_bytes or settings.default_chunk_size_bytes
    files_to_share = share_files or []

    async def _run() -> None:
        tracker_client = TrackerClient(
            base_url=resolved_tracker_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
        node = PeerNode(
            peer_id=resolved_peer_id,
            host=resolved_host,
            port=resolved_port,
            tracker_client=tracker_client,
            share_store=ShareStore(resolved_data_dir),
            download_store=DownloadStore(resolved_data_dir),
            heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
        await node.start()
        try:
            for file_path in files_to_share:
                manifest = await node.share_file(file_path, chunk_size_bytes=resolved_chunk_size)
                typer.echo(f"Shared {manifest.file_name} ({manifest.info_hash})")

            typer.echo(
                f"Peer node running as {resolved_peer_id} on {resolved_host}:{node.port}. "
                "Press Ctrl+C to stop."
            )
            await asyncio.Event().wait()
        finally:
            await node.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


@client_app.command("share")
def client_share(
    file_path: Annotated[
        Path,
        typer.Argument(
            ...,
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="File to share.",
        ),
    ],
    chunk_size_bytes: Annotated[
        int | None,
        typer.Option("--chunk-size", "-c", min=1, help="Chunk size for this share operation."),
    ] = None,
    peer_id: Annotated[
        str | None,
        typer.Option(help="Peer ID. Generates one automatically when omitted."),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option(help="Bind host for incoming peer connections."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(help="Bind port for incoming peer connections."),
    ] = None,
    data_dir: Annotated[
        str | None,
        typer.Option(help="Local runtime state directory."),
    ] = None,
    tracker_url: Annotated[
        str | None,
        typer.Option(help="Tracker base URL."),
    ] = None,
) -> None:
    """Share a file and keep serving until interrupted."""

    settings = ClientSettings()
    resolved_peer_id = _resolve_peer_id(peer_id)
    resolved_host = host or settings.bind_host
    resolved_port = port or settings.bind_port
    resolved_data_dir = data_dir or settings.data_dir
    resolved_tracker_url = tracker_url or settings.tracker_base_url
    resolved_chunk_size = chunk_size_bytes or settings.default_chunk_size_bytes

    async def _run() -> None:
        tracker_client = TrackerClient(
            base_url=resolved_tracker_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
        node = PeerNode(
            peer_id=resolved_peer_id,
            host=resolved_host,
            port=resolved_port,
            tracker_client=tracker_client,
            share_store=ShareStore(resolved_data_dir),
            download_store=DownloadStore(resolved_data_dir),
            heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
        await node.start()
        try:
            manifest = await node.share_file(file_path, chunk_size_bytes=resolved_chunk_size)
            typer.echo(
                f"Sharing {manifest.file_name} as {manifest.info_hash} on "
                f"{resolved_host}:{node.port}. Press Ctrl+C to stop."
            )
            await asyncio.Event().wait()
        finally:
            await node.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


@client_app.command("download")
def client_download(
    info_hash: Annotated[str, typer.Argument(help="Info-hash to download.")],
    target_path: Annotated[
        Path,
        typer.Argument(help="Target output file path.", resolve_path=True),
    ],
    peer_id: Annotated[
        str | None,
        typer.Option(help="Peer ID. Generates one automatically when omitted."),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option(help="Bind host for incoming peer connections."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(help="Bind port for incoming peer connections."),
    ] = None,
    data_dir: Annotated[
        str | None,
        typer.Option(help="Local runtime state directory."),
    ] = None,
    tracker_url: Annotated[
        str | None,
        typer.Option(help="Tracker base URL."),
    ] = None,
    max_chunks: Annotated[
        int | None,
        typer.Option(min=1, help="Optional cap for chunks downloaded in this invocation."),
    ] = None,
) -> None:
    """Download a file by info-hash using tracker-discovered peers."""

    settings = ClientSettings()
    resolved_peer_id = _resolve_peer_id(peer_id)
    resolved_host = host or settings.bind_host
    resolved_port = port or settings.bind_port
    resolved_data_dir = data_dir or settings.data_dir
    resolved_tracker_url = tracker_url or settings.tracker_base_url

    async def _run() -> None:
        tracker_client = TrackerClient(
            base_url=resolved_tracker_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
        node = PeerNode(
            peer_id=resolved_peer_id,
            host=resolved_host,
            port=resolved_port,
            tracker_client=tracker_client,
            share_store=ShareStore(resolved_data_dir),
            download_store=DownloadStore(resolved_data_dir),
            heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
        await node.start()
        try:
            progress = await node.download_file(
                info_hash=info_hash,
                target_path=target_path,
                max_chunks=max_chunks,
            )
        finally:
            await node.stop()

        typer.echo(progress.model_dump_json(indent=2))

    try:
        asyncio.run(_run())
    except TransferError as error:
        typer.echo(f"Download failed [{error.code}]: {error.message}", err=True)
        raise typer.Exit(code=1) from error


@client_app.command("status")
def client_status(
    info_hash: Annotated[str, typer.Argument(help="Info-hash to inspect.")],
    data_dir: Annotated[
        str | None,
        typer.Option(help="Local runtime state directory."),
    ] = None,
) -> None:
    """Show local resumable download progress state."""

    settings = ClientSettings()
    store = DownloadStore(data_dir or settings.data_dir)
    try:
        progress = store.get_progress(info_hash)
    except TransferError as error:
        typer.echo(f"Status unavailable [{error.code}]: {error.message}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(progress.model_dump_json(indent=2))


def run() -> None:
    """Execute CLI app."""

    app()


def _resolve_peer_id(peer_id: str | None) -> str:
    if peer_id:
        return peer_id
    return f"peer-{uuid4().hex[:8]}"


if __name__ == "__main__":
    run()
