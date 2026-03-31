"""Tracker process entrypoint."""

import uvicorn

from shardnet.common.config import TrackerSettings
from shardnet.tracker.api import create_app


def run() -> None:
    """Run the tracker service with configured bind values."""

    settings = TrackerSettings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
