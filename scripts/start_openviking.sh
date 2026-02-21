#!/usr/bin/env bash
# start scripts/start_openviking.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOGS_DIR="$PROJECT_DIR/logs"
RUNTIME_CONF="$HOME/.openviking/runtime.json"
OV_CONF_DIR="$HOME/.openviking"

mkdir -p "$LOGS_DIR"
mkdir -p "$OV_CONF_DIR"

# ─── Read config.yml via uv run ───────────────────────────────────────────────
# All tunable values come from config.yml — no magic numbers in this script.

read_config() {
    uv --project "$PROJECT_DIR" run python -c "
import yaml, sys
cfg = yaml.safe_load(open('$PROJECT_DIR/config.yml'))
key = sys.argv[1].split('.')
val = cfg
for k in key:
    val = val[k]
print(val)
" "$1"
}

EMBED_MODEL=$(read_config "embedding.model")
EMBED_BASE_PORT=$(read_config "embedding.base_port")
EMBED_HOST=$(read_config "embedding.host")
EMBED_TIMEOUT=$(read_config "embedding.health_timeout_seconds")
EMBED_DIMENSION=$(read_config "embedding.dimension")
OV_BASE_PORT=$(read_config "openviking.base_port")
OV_HOST=$(read_config "openviking.host")
OV_TIMEOUT=$(read_config "openviking.health_timeout_seconds")

# ─── Port detection ───────────────────────────────────────────────────────────
# Scans upward from base port until an unoccupied port is found.

find_free_port() {
    local port=$1
    while lsof -ti :"$port" >/dev/null 2>&1; do
        port=$((port + 1))
    done
    echo "$port"
}

wait_for_http() {
    local url=$1
    local max_seconds=$2
    local elapsed=0
    echo "  Waiting for $url ..."
    while ! curl -sf "$url" >/dev/null 2>&1; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [ "$elapsed" -ge "$max_seconds" ]; then
            echo "  ✗ Timed out after ${max_seconds}s — check $LOGS_DIR/*.log"
            return 1
        fi
    done
    echo "  ✓ Ready after ${elapsed}s"
}

# ─── [1] Embedding server ─────────────────────────────────────────────────────

EMBED_PID_FILE="$LOGS_DIR/embedding.pid"
EMBED_LOG="$LOGS_DIR/embedding.log"

if [ -f "$EMBED_PID_FILE" ] && kill -0 "$(cat "$EMBED_PID_FILE")" 2>/dev/null; then
    echo "↺ Embedding server already running (PID $(cat "$EMBED_PID_FILE"))"
    EMBED_PORT=$(cat "$LOGS_DIR/embedding.port" 2>/dev/null || echo "$EMBED_BASE_PORT")
else
    EMBED_PORT=$(find_free_port "$EMBED_BASE_PORT")
    echo "▶ Starting embedding server on port $EMBED_PORT ..."
    uv --project "$PROJECT_DIR" run mlx-openai-server launch \
        --model-type embeddings \
        --model-path "$EMBED_MODEL" \
        --port "$EMBED_PORT" \
        >> "$EMBED_LOG" 2>&1 &
    echo $! > "$EMBED_PID_FILE"
    echo "$EMBED_PORT" > "$LOGS_DIR/embedding.port"
    if ! wait_for_http "http://${EMBED_HOST}:${EMBED_PORT}/v1/models" "$EMBED_TIMEOUT"; then
        echo "  ⚠ Health check timed out — server may still be loading, continuing"
    fi
fi

# ─── Write ov.conf ────────────────────────────────────────────────────────────
# Regenerated each run so embedding port is always accurate.
# Delete first to prevent stale keys from prior versions accumulating.

rm -f "$OV_CONF_DIR/ov.conf"
cat > "$OV_CONF_DIR/ov.conf" <<EOF
{
  "embedding": {
    "dense": {
      "api_base": "http://${EMBED_HOST}:${EMBED_PORT}/v1",
      "api_key": "not-needed",
      "provider": "openai",
      "model": "${EMBED_MODEL}",
      "dimension": ${EMBED_DIMENSION}
    }
  }
}
EOF

# ─── [2] OpenViking server ────────────────────────────────────────────────────

OV_PID_FILE="$LOGS_DIR/openviking.pid"
OV_LOG="$LOGS_DIR/openviking.log"

if [ -f "$OV_PID_FILE" ] && kill -0 "$(cat "$OV_PID_FILE")" 2>/dev/null; then
    echo "↺ OpenViking server already running (PID $(cat "$OV_PID_FILE"))"
    OV_PORT=$(cat "$LOGS_DIR/openviking.port" 2>/dev/null || echo "$OV_BASE_PORT")
else
    OV_PORT=$(find_free_port "$OV_BASE_PORT")
    echo "▶ Starting OpenViking server on port $OV_PORT ..."
    uv --project "$PROJECT_DIR" run python -m openviking serve \
        --host "$OV_HOST" --port "$OV_PORT" \
        >> "$OV_LOG" 2>&1 &
    echo $! > "$OV_PID_FILE"
    echo "$OV_PORT" > "$LOGS_DIR/openviking.port"
    if ! wait_for_http "http://${OV_HOST}:${OV_PORT}/health" "$OV_TIMEOUT"; then
        echo "  ⚠ Health check timed out — server may still be starting, continuing"
    fi
fi

# ─── Write runtime.json ───────────────────────────────────────────────────────
# FastMCP wrapper reads this at startup to find current ports.
# This is runtime state, not configuration — ports are dynamic.

cat > "$RUNTIME_CONF" <<EOF
{
  "embedding_port": ${EMBED_PORT},
  "embedding_url": "http://${EMBED_HOST}:${EMBED_PORT}/v1",
  "openviking_port": ${OV_PORT},
  "openviking_url": "http://${OV_HOST}:${OV_PORT}"
}
EOF

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✓ OpenViking stack is ready                        ║"
echo "║                                                      ║"
printf "║  Embedding server : http://%s:%-5s              ║\n" "$EMBED_HOST" "$EMBED_PORT"
printf "║  OpenViking       : http://%s:%-5s              ║\n" "$OV_HOST" "$OV_PORT"
echo "║  Runtime config   : ~/.openviking/runtime.json      ║"
echo "║                                                      ║"
echo "║  Restart Claude Code to activate MCP tools.         ║"
echo "╚══════════════════════════════════════════════════════╝"
# end scripts/start_openviking.sh
