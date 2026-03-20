"""Unit tests for main.py — subprocess launcher."""

import subprocess
import sys
from unittest.mock import patch

import pytest

from main import main

# ─── main() ───────────────────────────────────────────────────────────────────


def test_main_calls_subprocess_run() -> None:
    """main() launches the MCP server module as a subprocess using sys.executable."""
    with patch("main.subprocess.run") as mock_run:
        main()
        mock_run.assert_called_once_with(
            [sys.executable, "-m", "src.openviking_mcp_server"],
            check=True,
        )


def test_main_propagates_calledprocesserror() -> None:
    """CalledProcessError raised by subprocess.run propagates to the caller."""
    with patch("main.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
        with pytest.raises(subprocess.CalledProcessError):
            main()
