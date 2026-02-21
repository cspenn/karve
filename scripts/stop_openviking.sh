#!/usr/bin/env bash
# start scripts/stop_openviking.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="$(dirname "$SCRIPT_DIR")/logs"

stop_service() {
    local name=$1
    local pid_file="$LOGS_DIR/${name}.pid"
    if [ ! -f "$pid_file" ]; then
        echo "  $name: no PID file found"
        return
    fi
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
        echo "▶ Stopping $name (PID $pid)..."
        kill "$pid"
        rm -f "$pid_file"
        echo "  ✓ Stopped"
    else
        echo "  $name not running (stale PID file removed)"
        rm -f "$pid_file"
    fi
}

stop_service "openviking"
stop_service "embedding"
echo "Stack stopped."
# end scripts/stop_openviking.sh
