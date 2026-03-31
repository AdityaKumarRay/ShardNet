"""CLI surface for tracker and peer workflows."""

import typer
import uvicorn

from shardnet.common.config import TrackerSettings
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

    typer.echo(
        "Client core is scaffolded for milestone-based delivery. "
        "Chunking and transfer arrive in the next milestones."
    )


def run() -> None:
    """Execute CLI app."""

    app()


if __name__ == "__main__":
    run()
