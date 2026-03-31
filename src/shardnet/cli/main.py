"""CLI surface for tracker and peer workflows."""

from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from shardnet.client.core.manifest import build_file_manifest
from shardnet.common.config import ClientSettings, TrackerSettings
from shardnet.common.constants import API_VERSION, PROTOCOL_VERSION
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


def run() -> None:
    """Execute CLI app."""

    app()


if __name__ == "__main__":
    run()
