# Deployment Guide

## Tracker Deployment

### Option 1: Docker Compose (recommended)

```bash
docker compose up --build tracker
```

Tracker runs on `http://127.0.0.1:8000` by default.

### Option 2: Python process

```bash
python -m pip install -e .
python -m shardnet.tracker.main
```

## Desktop Agent Deployment

Run the local agent manually (desktop app usually starts it automatically):

```bash
python -m shardnet.client.agent.main
```

## CLI Client Runtime

Start a peer node:

```bash
shardnet client run --tracker-url http://127.0.0.1:8000
```

Share a file:

```bash
shardnet client share ./seed.bin --tracker-url http://127.0.0.1:8000
```

Download a file:

```bash
shardnet client download <INFO_HASH> ./downloads/seed.bin --tracker-url http://127.0.0.1:8000
```
