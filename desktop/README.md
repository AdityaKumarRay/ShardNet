# ShardNet Desktop

The desktop app runs an Electron shell that controls a local `shardnet-agent` service.

## Development

```bash
cd desktop
npm install
npm run start
```

The app starts the Python agent automatically via `shardnet-agent`.

## Environment Overrides

- `SHARDNET_AGENT_COMMAND`: command used to launch the Python agent (default `shardnet-agent`)
- `SHARDNET_AGENT_ARGS`: extra args for the agent command
- `SHARDNET_AGENT_URL`: API URL used by renderer (default `http://127.0.0.1:8765`)

## Packaging

```bash
cd desktop
npm run dist
```

Outputs are generated in `desktop/release`.
