# ShardNet P2P

ShardNet is a production-minded, BitTorrent-inspired file sharing system with a separately deployed tracker and peer-to-peer chunk transfer between clients.

## Milestone 0 Status

- Repository foundation scaffolded with consistent project conventions.
- Shared Python baseline added for config, logging, errors, and protocol versioning.
- Tracker FastAPI skeleton and CLI entrypoint are runnable.
- Unit tests and quality tooling are configured.

## Milestone 1 Status

- Tracker persistence implemented with SQLite.
- Peer coordination endpoints added for register, heartbeat, file announce, and swarm discovery.
- Integration-style API tests added for success and error paths.
- Docker image and compose flow added for tracker deployment/local runtime.

## Repository Layout

- `src/shardnet/common`: shared constants, settings, logging, and error model.
- `src/shardnet/tracker`: tracker API factory and process entrypoint.
- `src/shardnet/cli`: CLI surface powered by shared core modules.
- `tests/unit`: baseline test coverage for constants, settings, and tracker endpoints.

## Local Development

```bash
python -m pip install -e ".[dev]"
make lint
make format-check
make typecheck
make test
```

Run tracker locally:

```bash
make run-tracker
```

Run tracker in Docker:

```bash
make docker-tracker-up
```

Stop Docker services:

```bash
make docker-tracker-down
```

Or with CLI:

```bash
shardnet tracker run
```

## Tracker API (MVP)

- `POST /api/v1/peers/register`: register or refresh peer endpoint metadata.
- `POST /api/v1/peers/heartbeat`: update peer liveness timestamp.
- `POST /api/v1/files/announce`: advertise file metadata and available chunk indexes for a peer.
- `GET /api/v1/files/{info_hash}/swarm`: fetch active peers and chunk availability for download planning.
- `GET /api/v1/meta` and `GET /health`: service metadata and health.

## Configuration

Tracker environment variables:

- `TRACKER_HOST` (default `0.0.0.0`)
- `TRACKER_PORT` (default `8000`)
- `TRACKER_DATABASE_URL` (default `sqlite:///./data/tracker.db`)
- `TRACKER_HEARTBEAT_TTL_SECONDS` (default `120`)
- `TRACKER_LOG_LEVEL` (default `INFO`)

Client-related milestones continue next; current CLI tracker command remains available.

```bash
shardnet tracker run --host 0.0.0.0 --port 8000
```

## Next Milestone

Milestone 2 introduces chunk manifesting, hashing, and resumable client-side state in the shared client core.