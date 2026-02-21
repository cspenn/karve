# karve

> OpenViking semantic memory stack for Claude Code — local embeddings, persistent context, six MCP tools.

Named after the [karve](https://en.wikipedia.org/wiki/Karve_(boat)), a light, fast class of Viking ship.

## What It Does

Karve runs two local servers and exposes them to Claude Code as MCP tools:

- **Embedding server** — serves `mlx-community/Qwen3-Embedding-4B-mxfp8` via an OpenAI-compatible API using MLX (Apple Silicon only)
- **OpenViking server** — agent-native context database that uses those embeddings for semantic search and storage
- **MCP wrapper** — a FastMCP stdio subprocess that Claude Code spawns, connecting it to the OpenViking server

Claude can store memories, search past context, and retrieve project knowledge across sessions.

## Requirements

- macOS with Apple Silicon (MLX requires it)
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Setup

**1. Install dependencies**

```zsh
uv sync
```

**2. Create credentials**

```zsh
cp credentials.yml.dist credentials.yml
```

Edit `credentials.yml` and set your API key (any string for local use):

```yaml
openviking:
  api_key: your-local-key-here
```

**3. Start the stack**

```zsh
./scripts/start_openviking.sh
```

First run downloads ~4 GB of model weights. Subsequent starts take a few seconds.

**4. Register the MCP with Claude Code**

```zsh
claude mcp add openviking -s user -- uv --project /path/to/karve run python src/openviking_mcp_server.py
```

Replace `/path/to/karve` with the absolute path to this repo. Restart Claude Code after running.

**5. Open the dashboard (optional)**

Open `dashboard.html` in any browser to monitor the running stack.

## Configuration

| File | Purpose |
|------|---------|
| `config.yml` | Ports, host, model name, health check timeouts |
| `credentials.yml` | API key (gitignored) |
| `credentials.yml.dist` | Template — commit this, not credentials.yml |

Runtime port assignments are written to `~/.openviking/runtime.json` on each startup, so the MCP wrapper always finds the right ports even if they shift.

## MCP Tools

Once Claude Code restarts with the MCP registered, six tools are available:

| Tool | Description |
|------|-------------|
| `viking_search` | Fast semantic search across stored memories, resources, and skills |
| `viking_deep_search` | Intent-aware search with query expansion for better recall |
| `viking_read` | Read a specific URI at abstract / overview / full depth |
| `viking_list` | Browse the OpenViking context filesystem |
| `viking_remember` | Store text as a persistent resource |
| `viking_status` | Health check — confirms the stack is reachable |

## Architecture

```
Claude Code
    │
    ├─ spawns (stdio)
    │       src/openviking_mcp_server.py   ← FastMCP wrapper
    │               │
    │               └─ HTTP → OpenViking server (port 1933)
    │                               │
    │                               └─ HTTP → Embedding server (port 8001)
    │                                         mlx-openai-server
    │                                         Qwen3-Embedding-4B-mxfp8
    │
    └─ reads ~/.openviking/runtime.json at startup for current ports
```

The MCP wrapper is a thin FastMCP layer. All state lives in OpenViking. The embedding server is stateless and can be restarted independently.

## Dashboard

Open `dashboard.html` in a browser while the stack is running. It polls the OpenViking REST API every 5 seconds and shows:

- Server health and system status
- Observer component health (queue, vikingdb, vlm, transaction)
- Embedding server status and model name
- Active sessions count
- Context filesystem root listing

No web server required — it runs entirely client-side.

## Scripts

```zsh
./scripts/start_openviking.sh    # Start (or restart) the full stack
```

The script:
1. Skips the embedding server if already running
2. Regenerates `~/.openviking/ov.conf` with the current embedding port
3. Starts the OpenViking server
4. Writes `~/.openviking/runtime.json` with active ports

Logs are written to `logs/embedding.log` and `logs/openviking.log`.

## Project Structure

```
karve/
├── src/
│   └── openviking_mcp_server.py   # FastMCP MCP server
├── scripts/
│   └── start_openviking.sh        # Stack startup script
├── dashboard.html                 # Browser status dashboard
├── config.yml                     # General configuration
├── credentials.yml.dist           # Credentials template
├── docs/
│   └── rules-python.md            # Development standards
└── logs/                          # Runtime logs (gitignored)
```
