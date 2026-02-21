# start main.py
"""karve entry point — orchestration only.

Invokes the OpenViking MCP server via its own __main__ guard.
Run with: python -m karve.main  (or via uv run)
"""
import subprocess
import sys


def main() -> None:
    """Launch the OpenViking MCP server as a subprocess."""
    subprocess.run(
        [sys.executable, "-m", "src.openviking_mcp_server"],
        check=True,
    )


if __name__ == "__main__":
    main()
# end main.py
