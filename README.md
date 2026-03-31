# ShardNet P2P

ShardNet is a production-minded, BitTorrent-inspired file sharing system with a separately deployed tracker and peer-to-peer chunk transfer between clients.

## Milestone 0 Status

- Repository foundation scaffolded with consistent project conventions.
- Shared Python baseline added for config, logging, errors, and protocol versioning.
- Tracker FastAPI skeleton and CLI entrypoint are runnable.
- Unit tests and quality tooling are configured.

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

Or with CLI:

```bash
shardnet tracker run
```

## Next Milestone

Milestone 1 introduces tracker persistence and peer/file registration endpoints.