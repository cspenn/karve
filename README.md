<p align="center">
  <img src="karve.webp" alt="karve — Viking semantic memory for Claude Code" width="100%">
</p>

<h1 align="center">karve</h1>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Platform: Apple Silicon" src="https://img.shields.io/badge/platform-Apple%20Silicon-silver">
  <img alt="Coverage: 100%" src="https://img.shields.io/badge/coverage-100%25-brightgreen">
  <img alt="Tests: 64" src="https://img.shields.io/badge/tests-64-green">
  <img alt="mypy: strict" src="https://img.shields.io/badge/mypy-strict-blue">
</p>

<p align="center">
  <em>Persistent semantic memory for Claude Code — local embeddings, zero cloud, six tools.</em>
</p>

---

## What is karve?

Claude Code is powerful but stateless. Every session starts cold: no memory of past decisions, preferred patterns, or project context. You re-explain, re-discover, and re-decide the same things.

**karve** gives Claude Code persistent, searchable memory that lives entirely on your Mac.

It runs two local servers — a 4B-parameter embedding model on Apple Silicon (via MLX) and an agent-native context database (OpenViking) — and exposes them to Claude as six MCP tools. Claude stores notes, searches past context, and retrieves project knowledge across sessions. Nothing leaves your machine.

Named after the [karve](https://en.wikipedia.org/wiki/Karve_(boat)), a light, fast class of Viking longship.

---

## Why local semantic memory?

Cloud AI tools that promise "memory" route your context through remote servers. If your notes contain code decisions, architectural choices, or proprietary system designs, that's a meaningful privacy exposure.

karve is local-first:

- **Embeddings** computed on-device by `Qwen3-Embedding-4B-mxfp8` via MLX — Apple Silicon native, no GPU rental
- **Storage** in OpenViking, an open-source context database that runs entirely on `localhost`
- **Retrieval** by semantic similarity — not keyword matching, not brittle file search

OpenViking isn't a vector store you query with scripts. It uses a file-system interface (`viking://user/memory/`, `viking://resources/`, etc.) that Claude navigates autonomously. Think of it as a filesystem your AI can search by *meaning*.

---

## Is karve right for you?

| Scenario | Fit |
|----------|-----|
| macOS Apple Silicon (M1 / M2 / M3 / M4) | ✅ Required |
| Claude Code as your primary AI client | ✅ Required |
| Single-user, local-only workflow | ✅ Ideal |
| Intel Mac, Linux, or Windows | ❌ MLX won't run |
| Teams sharing memory across machines | ❌ Local stack only |
| Other AI clients (Cursor, Windsurf, etc.) | ❌ MCP server targets Claude Code |
| Real-time or very large-scale retrieval | ❌ Single-user, not designed for this |

---

## Quick Start

**Prerequisites:** macOS Apple Silicon · Python 3.11+ · [uv](https://docs.astral.sh/uv/)

### 1. Clone and install

```zsh
git clone <repo-url>
cd karve
uv sync
```

### 2. Create credentials

```zsh
cp credentials.yml.dist credentials.yml
```

Edit `credentials.yml` — any string works for local use:

```yaml
openviking:
  api_key: my-local-key
```

### 3. Start the stack

```zsh
./scripts/start_openviking.sh
```

The first run downloads ~4 GB of model weights — allow ~5 minutes. Subsequent starts take a few seconds. Logs go to `logs/embedding.log` and `logs/openviking.log`.

### 4. Register the MCP with Claude Code

See [MCP Registration](#mcp-registration) below, then restart Claude Code.

### 5. Verify the connection

In any Claude Code session, ask Claude to run `viking_status()`. A healthy response confirms the stack is reachable.

---

## MCP Registration

Add karve to your `.mcp.json`. For user-wide registration, create or edit `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "openviking": {
      "command": "uv",
      "args": ["--project", "/path/to/karve", "run", "python", "-m", "src.openviking_mcp_server"]
    }
  }
}
```

Replace `/path/to/karve` with the absolute path to your cloned repository. Restart Claude Code after saving.

Alternatively, register via the CLI:

```zsh
claude mcp add openviking -s user -- uv --project /path/to/karve run python -m src.openviking_mcp_server
```

### Project-scoped memory

By default all tools use the global `viking://` namespace, so memories from different projects can mix. To isolate memory per project, add a `KARVE_PROJECT` env var in a **project-level** `.mcp.json` at your project root:

```json
{
  "mcpServers": {
    "openviking": {
      "command": "uv",
      "args": ["--project", "/path/to/karve", "run", "python", "-m", "src.openviking_mcp_server"],
      "env": {
        "KARVE_PROJECT": "my-project-name"
      }
    }
  }
}
```

When `KARVE_PROJECT` is set:

- Searches default to `viking://user/projects/my-project-name/` instead of `viking://`
- `viking_remember` stores at `viking://user/projects/my-project-name/<category>/`
- Global search is still available by passing `uri="viking://"` explicitly

Without `KARVE_PROJECT`, all tools use the global `viking://` namespace (original behaviour).

---

## MCP Tools

Six tools become available once Claude Code restarts with the MCP registered:

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `viking_search` | Fast semantic similarity search | `query`, `uri="viking://"`, `limit=5` |
| `viking_deep_search` | Intent-aware search with query expansion | `query`, `uri="viking://"`, `limit=5` |
| `viking_read` | Read content at a specific URI | `uri`, `depth="overview"` |
| `viking_list` | Browse the context filesystem | `uri="viking://"` |
| `viking_remember` | Store text for future retrieval | `text`, `category="memory"`, `name=""` |
| `viking_status` | Health check — returns server details | — |

### Depth levels for `viking_read`

| Depth | Approx. tokens | Use when |
|-------|----------------|----------|
| `abstract` | ~100 | Quick triage — is this the right resource? |
| `overview` | ~2000 | Default — good balance of context |
| `full` | complete | Full document needed |

### URI scoping

All search and list tools accept a `uri` parameter to scope the query:

```
viking://               # everything
viking://user/          # all user-owned content
viking://user/memory/   # stored memories only
viking://resources/     # indexed resources
```

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Claude Code                                          │
│                                                       │
│  viking_search  viking_deep_search  viking_read       │
│  viking_list    viking_remember     viking_status     │
└──────────────────────┬───────────────────────────────┘
                       │ stdio  (FastMCP subprocess)
                       ▼
┌──────────────────────────────────────────────────────┐
│  src/openviking_mcp_server.py                         │
│  FastMCP wrapper — thin HTTP bridge, no local state   │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP  localhost:1933
                       ▼
┌──────────────────────────────────────────────────────┐
│  OpenViking server                                    │
│  Agent-native context database                        │
│  File-system interface: viking:// URIs                │
│  Three-tier loading: L0 abstract · L1 overview · L2   │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP  localhost:8000
                       ▼
┌──────────────────────────────────────────────────────┐
│  MLX embedding server  (mlx-openai-server)            │
│  mlx-community/Qwen3-Embedding-4B-mxfp8               │
│  OpenAI-compatible API · Apple Silicon native         │
└──────────────────────────────────────────────────────┘

All components run on localhost. No external network calls.
Active ports written to ~/.openviking/runtime.json on each startup.
```

---

## Configuration

### `config.yml` — non-secret settings

| Key | Default | Notes |
|-----|---------|-------|
| `embedding.model` | `mlx-community/Qwen3-Embedding-4B-mxfp8` | MLX model path |
| `embedding.base_port` | `8000` | Scans upward if occupied |
| `openviking.base_port` | `1933` | Scans upward if occupied |
| `logging.level` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

Ports are dynamic: if a base port is occupied, the startup script finds the next free port. The MCP wrapper reads `~/.openviking/runtime.json` at startup to locate the current ports — so restarting the stack never breaks the MCP connection.

### `credentials.yml` — secrets (gitignored)

```yaml
openviking:
  api_key: your-key-here   # any string — local auth only
```

Copy from `credentials.yml.dist`. Never commit this file.

---

## Dashboard

When Claude Code spawns the MCP server, a status dashboard **automatically opens in your browser**. It polls the OpenViking REST API every 5 seconds and displays:

- Server health and system status
- Observer component health (queue, vikingdb, transaction)
- Embedding server status and active model name
- Active session count
- Context filesystem root listing

The dashboard is a single static `dashboard.html` file — no build step, no web server required. It runs entirely client-side.

---

## Development

```zsh
uv sync                    # install all deps including dev tools
uv run pytest              # 64 tests, 100% coverage
```

**Quality gates (all passing):**

| Tool | Result |
|------|--------|
| ruff | zero violations |
| mypy `--strict` | zero errors |
| pytest | 64 tests, 100% coverage |
| bandit | no security issues |
| interrogate | 100% docstring coverage |
| pylint | 9.77 / 10 |
| radon | all grade B or better |
| xenon | max-absolute B |

---

## Acknowledgments

- **[OpenViking](https://github.com/volcengine/openviking)** — open-source agent-native context database by ByteDance Volcano Engine; the core storage and retrieval engine powering karve
- **[FastMCP](https://github.com/jlowin/fastmcp)** — the MCP server framework used here; v3.0 released January 2026, powers 70% of MCP servers with 1M+ downloads/day
- **[MLX](https://github.com/ml-explore/mlx)** — Apple's array framework for fast on-device inference; makes local 4B-parameter embeddings practical on consumer hardware

---

<p align="center">
  <sub>karve — light and fast, like the ship it's named after.</sub>
</p>
