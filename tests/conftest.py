# start tests/conftest.py
"""Shared fixtures for the karve test suite."""

from unittest.mock import MagicMock

import pytest

import src.openviking_mcp_server as module


@pytest.fixture
def mock_client():
    """A MagicMock standing in for ov.SyncHTTPClient."""
    client = MagicMock()
    client.is_healthy.return_value = True
    return client


@pytest.fixture
def mock_viking(mock_client, monkeypatch):
    """Patch module-level _viking with a mock VikingClient."""
    viking = MagicMock()
    viking.get.return_value = mock_client
    monkeypatch.setattr(module, "_viking", viking)
    return viking, mock_client


# end tests/conftest.py
