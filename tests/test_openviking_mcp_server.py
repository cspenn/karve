# start tests/test_openviking_mcp_server.py
"""Unit tests for src/openviking_mcp_server.py — targeting 100% coverage."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.openviking_mcp_server as module

# ─── _load_credentials() ──────────────────────────────────────────────────────


def test_load_credentials_success():
    """Happy path: valid credentials.yml is loaded."""
    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_creds_path = MagicMock()
        mock_creds_path.exists.return_value = True
        mock_creds_path.read_text.return_value = "openviking:\n  api_key: test_key_value\n"
        mock_path_cls.return_value.parent.parent.__truediv__.return_value = mock_creds_path

        result = module._load_credentials()
        assert result.api_key == "test_key_value"


def test_load_credentials_file_not_found():
    """Missing credentials.yml raises FileNotFoundError."""
    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_creds_path = MagicMock()
        mock_creds_path.exists.return_value = False
        mock_path_cls.return_value.parent.parent.__truediv__.return_value = mock_creds_path

        with pytest.raises(FileNotFoundError):
            module._load_credentials()


def test_load_credentials_validation_error():
    """Credentials with wrong fields raises Pydantic ValidationError."""
    from pydantic import ValidationError

    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_creds_path = MagicMock()
        mock_creds_path.exists.return_value = True
        mock_creds_path.read_text.return_value = "openviking:\n  wrong_field: value\n"
        mock_path_cls.return_value.parent.parent.__truediv__.return_value = mock_creds_path

        with pytest.raises(ValidationError):
            module._load_credentials()


def test_load_credentials_malformed_yaml():
    """Malformed YAML in credentials.yml raises ValueError with helpful message."""
    import yaml as yaml_module

    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_creds_path = MagicMock()
        mock_creds_path.exists.return_value = True
        mock_creds_path.read_text.return_value = "valid text"
        mock_path_cls.return_value.parent.parent.__truediv__.return_value = mock_creds_path

        with (
            patch(
                "src.openviking_mcp_server.yaml.safe_load",
                side_effect=yaml_module.YAMLError("bad yaml"),
            ),
            pytest.raises(ValueError, match="malformed YAML"),
        ):
            module._load_credentials()


def test_load_credentials_missing_openviking_key():
    """YAML missing top-level 'openviking' key raises ValueError with helpful message."""
    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_creds_path = MagicMock()
        mock_creds_path.exists.return_value = True
        mock_creds_path.read_text.return_value = "other_key:\n  api_key: foo\n"
        mock_path_cls.return_value.parent.parent.__truediv__.return_value = mock_creds_path

        with pytest.raises(ValueError, match="openviking"):
            module._load_credentials()


def test_load_credentials_non_dict_yaml():
    """Non-dict YAML value (e.g., plain string) raises ValueError."""
    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_creds_path = MagicMock()
        mock_creds_path.exists.return_value = True
        mock_creds_path.read_text.return_value = "just a string\n"
        mock_path_cls.return_value.parent.parent.__truediv__.return_value = mock_creds_path

        with pytest.raises(ValueError, match="openviking"):
            module._load_credentials()


# ─── _load_runtime() ──────────────────────────────────────────────────────────


def test_load_runtime_success():
    """Happy path: valid runtime.json is parsed into RuntimePorts."""
    runtime_data = json.dumps(
        {
            "openviking_url": "http://localhost:1933",
            "embedding_url": "http://localhost:8080",
            "openviking_port": 1933,
            "embedding_port": 8080,
        }
    )
    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_runtime_path = MagicMock()
        mock_runtime_path.exists.return_value = True
        mock_runtime_path.read_text.return_value = runtime_data
        mock_path_cls.home.return_value.__truediv__.return_value.__truediv__.return_value = (
            mock_runtime_path
        )

        result = module._load_runtime()
        assert result is not None
        assert result.openviking_url == "http://localhost:1933"
        assert result.embedding_url == "http://localhost:8080"
        assert result.openviking_port == 1933
        assert result.embedding_port == 8080


def test_load_runtime_absent():
    """Missing runtime.json returns None."""
    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_runtime_path = MagicMock()
        mock_runtime_path.exists.return_value = False
        mock_path_cls.home.return_value.__truediv__.return_value.__truediv__.return_value = (
            mock_runtime_path
        )

        result = module._load_runtime()
        assert result is None


def test_load_runtime_validation_error():
    """Invalid runtime.json fields raise Pydantic ValidationError."""
    from pydantic import ValidationError

    runtime_data = json.dumps({"bad_field": "value"})
    with patch("src.openviking_mcp_server.Path") as mock_path_cls:
        mock_runtime_path = MagicMock()
        mock_runtime_path.exists.return_value = True
        mock_runtime_path.read_text.return_value = runtime_data
        mock_path_cls.home.return_value.__truediv__.return_value.__truediv__.return_value = (
            mock_runtime_path
        )

        with pytest.raises(ValidationError):
            module._load_runtime()


# ─── VikingClient ─────────────────────────────────────────────────────────────


def test_viking_client_init():
    """VikingClient initializes with url, api_key, and no client."""
    client = module.VikingClient(url="http://test:1933", api_key="key123")
    assert client._url == "http://test:1933"
    assert client._api_key == "key123"
    assert client._client is None


def test_viking_client_connect_success():
    """_connect() creates and initializes a SyncHTTPClient."""
    import openviking as ov

    with patch.object(ov, "SyncHTTPClient") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        client = module.VikingClient(url="http://test:1933", api_key="key123")
        result = client._connect()

        mock_client_cls.assert_called_once_with(url="http://test:1933", api_key="key123")
        mock_instance.initialize.assert_called_once()
        assert result == mock_instance


def test_viking_client_connect_failure():
    """_connect() re-raises ConnectionError after retries (reraise=True)."""
    import openviking as ov

    with (
        patch.object(ov, "SyncHTTPClient") as mock_client_cls,
        patch("tenacity.nap.sleep"),
    ):
        # Suppress tenacity sleep delays so the test runs fast
        mock_instance = MagicMock()
        mock_instance.initialize.side_effect = ConnectionError("refused")
        mock_client_cls.return_value = mock_instance

        client = module.VikingClient(url="http://bad:1933", api_key="key")
        with pytest.raises(ConnectionError):
            # tenacity will retry 3 times then reraise
            client._connect()


def test_viking_client_get_connects_on_first_call():
    """get() connects on first call and reuses the connection on subsequent calls."""
    import openviking as ov

    with patch.object(ov, "SyncHTTPClient") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        client = module.VikingClient(url="http://test:1933", api_key="key")
        result1 = client.get()
        result2 = client.get()

        assert result1 is result2
        # initialize called once — client reused on second get()
        mock_instance.initialize.assert_called_once()


# ─── _fmt_results() ───────────────────────────────────────────────────────────


def test_fmt_results_empty():
    """All categories empty returns sentinel string."""
    result = MagicMock()
    result.memories = []
    result.resources = []
    result.skills = []
    assert module._fmt_results(result) == "No results found."


def test_fmt_results_memories_only():
    """Memories appear with URI, score, and content."""
    item = MagicMock()
    item.score = 0.95
    item.uri = "viking://user/memory/test"
    item.content = "Test memory content"

    result = MagicMock()
    result.memories = [item]
    result.resources = []
    result.skills = []

    output = module._fmt_results(result)
    assert "## Memories" in output
    assert "viking://user/memory/test" in output
    assert "0.950" in output
    assert "Test memory content" in output


def test_fmt_results_resources_only():
    """Resources appear under ## Resources heading."""
    item = MagicMock()
    item.score = 0.80
    item.uri = "viking://project/resource/doc"
    item.content = "Resource content"

    result = MagicMock()
    result.memories = []
    result.resources = [item]
    result.skills = []

    output = module._fmt_results(result)
    assert "## Resources" in output
    assert "viking://project/resource/doc" in output


def test_fmt_results_skills_only():
    """Skills appear under ## Skills heading."""
    item = MagicMock()
    item.score = 0.75
    item.uri = "viking://skill/example"
    item.content = "Skill content"

    result = MagicMock()
    result.memories = []
    result.resources = []
    result.skills = [item]

    output = module._fmt_results(result)
    assert "## Skills" in output
    assert "viking://skill/example" in output


def test_fmt_results_all_categories():
    """All three categories appear when all have items."""

    def make_item(uri, content):
        item = MagicMock()
        item.score = 0.5
        item.uri = uri
        item.content = content
        return item

    result = MagicMock()
    result.memories = [make_item("viking://m1", "mem content")]
    result.resources = [make_item("viking://r1", "res content")]
    result.skills = [make_item("viking://s1", "skill content")]

    output = module._fmt_results(result)
    assert "## Memories" in output
    assert "## Resources" in output
    assert "## Skills" in output


def test_fmt_results_truncation():
    """Content longer than _CONTENT_PREVIEW_LEN (300) is truncated."""
    item = MagicMock()
    item.score = None
    item.uri = "viking://test"
    item.content = "x" * 400  # Longer than 300

    result = MagicMock()
    result.memories = [item]
    result.resources = []
    result.skills = []

    output = module._fmt_results(result)
    # Content should be truncated to 300 chars (the constant value)
    assert "x" * 300 in output
    assert "x" * 400 not in output


def test_fmt_results_no_score():
    """Items with score=None show no score string."""
    item = MagicMock()
    item.score = None
    item.uri = "viking://test"
    item.content = "content"

    result = MagicMock()
    result.memories = [item]
    result.resources = []
    result.skills = []

    output = module._fmt_results(result)
    assert "score:" not in output
    assert "viking://test" in output


def test_fmt_results_uses_abstract_fallback():
    """When content is None, abstract is used as fallback."""
    item = MagicMock()
    item.score = None
    item.uri = "viking://test"
    item.content = None
    item.abstract = "Abstract text"
    item.overview = None

    result = MagicMock()
    result.memories = [item]
    result.resources = []
    result.skills = []

    output = module._fmt_results(result)
    assert "Abstract text" in output


def test_fmt_results_uses_overview_fallback():
    """When content and abstract are None, overview is used."""
    item = MagicMock()
    item.score = None
    item.uri = "viking://test"
    item.content = None
    item.abstract = None
    item.overview = "Overview text"

    result = MagicMock()
    result.memories = [item]
    result.resources = []
    result.skills = []

    output = module._fmt_results(result)
    assert "Overview text" in output


def test_fmt_results_all_content_fields_none():
    """When content, abstract, and overview are all None, no content line added."""
    item = MagicMock()
    item.score = None
    item.uri = "viking://test"
    item.content = None
    item.abstract = None
    item.overview = None

    result = MagicMock()
    result.memories = [item]
    result.resources = []
    result.skills = []

    output = module._fmt_results(result)
    # URI line is present but no indented content line
    assert "viking://test" in output


def test_fmt_results_getattr_none_category():
    """getattr fallback: if a category attribute is missing (returns None), it is skipped."""
    result = MagicMock(spec=[])  # no attributes at all
    # getattr will return None for missing attrs, treated as empty
    output = module._fmt_results(result)
    assert output == "No results found."


# ─── _write_temp_resource() ───────────────────────────────────────────────────


def test_write_temp_resource_creates_file():
    """Creates a .md temp file with the correct content and suffix."""
    path = module._write_temp_resource("hello world", "test_stem")
    try:
        assert os.path.exists(path)
        assert path.endswith("_test_stem.md")
        with open(path) as f:
            assert f.read() == "hello world"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_write_temp_resource_empty_name():
    """Empty name produces a file ending in .md (no leading underscore)."""
    path = module._write_temp_resource("content", "")
    try:
        assert path.endswith(".md")
        # Should NOT end with _.md — just .md
        assert not path.endswith("_.md")
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ─── _validate_slug() ─────────────────────────────────────────────────────────


def test_validate_slug_valid_values():
    """Valid alphanumeric, hyphen, and underscore values pass without error."""
    assert module._validate_slug("my-project_123", "KARVE_PROJECT") == "my-project_123"
    assert module._validate_slug("", "KARVE_PROJECT") == ""
    assert module._validate_slug("abc", "test") == "abc"
    assert module._validate_slug("A-B_C", "test") == "A-B_C"


def test_validate_slug_rejects_slashes():
    """Path traversal sequences raise ValueError with the label in the message."""
    with pytest.raises(ValueError, match="KARVE_PROJECT"):
        module._validate_slug("../../admin", "KARVE_PROJECT")


def test_validate_slug_rejects_special_chars():
    """Spaces, percent-encoding, and other special characters are rejected."""
    with pytest.raises(ValueError, match="invalid characters"):
        module._validate_slug("my project", "test")
    with pytest.raises(ValueError, match="invalid characters"):
        module._validate_slug("foo/bar", "test")
    with pytest.raises(ValueError, match="invalid characters"):
        module._validate_slug("a%20b", "test")


# ─── viking_search() ──────────────────────────────────────────────────────────


def test_viking_search_success(mock_viking):
    """Successful search returns formatted results."""
    _, client = mock_viking
    mock_results = MagicMock()
    mock_results.memories = []
    mock_results.resources = []
    mock_results.skills = []
    client.find.return_value = mock_results

    result = module.viking_search("test query")  # type: ignore[operator]
    assert result == "No results found."
    client.find.assert_called_once_with("test query", target_uri=module._DEFAULT_URI, limit=5)


def test_viking_search_custom_args(mock_viking):
    """Custom uri and limit are forwarded to client.find."""
    _, client = mock_viking
    mock_results = MagicMock()
    mock_results.memories = []
    mock_results.resources = []
    mock_results.skills = []
    client.find.return_value = mock_results

    module.viking_search("query", uri="viking://user/", limit=10)  # type: ignore[operator]
    client.find.assert_called_once_with("query", target_uri="viking://user/", limit=10)


def test_viking_search_exception(mock_viking):
    """OSError is caught and returns a user-friendly error message."""
    _, client = mock_viking
    client.find.side_effect = OSError("connection refused")

    result = module.viking_search("test query")  # type: ignore[operator]
    assert "failed" in result.lower()
    assert "start_openviking.sh" in result


def test_viking_search_openviking_error(mock_viking):
    """OpenVikingError is caught and returns an error message."""
    from openviking_cli.exceptions import OpenVikingError

    _, client = mock_viking
    client.find.side_effect = OpenVikingError("internal error")

    result = module.viking_search("test query")  # type: ignore[operator]
    assert "failed" in result.lower()


# ─── viking_deep_search() ─────────────────────────────────────────────────────


def test_viking_deep_search_with_query_plan(mock_viking):
    """Results with a non-empty query_plan prepend the expansion header."""
    _, client = mock_viking
    mock_results = MagicMock()
    mock_results.query_plan = ["expanded", "terms"]
    mock_results.memories = []
    mock_results.resources = []
    mock_results.skills = []
    client.search.return_value = mock_results

    result = module.viking_deep_search("test query")  # type: ignore[operator]
    assert "Query expansion:" in result
    assert "expanded" in result


def test_viking_deep_search_no_query_plan(mock_viking):
    """Results with empty query_plan do not include expansion header."""
    _, client = mock_viking
    mock_results = MagicMock()
    mock_results.query_plan = []
    mock_results.memories = []
    mock_results.resources = []
    mock_results.skills = []
    client.search.return_value = mock_results

    result = module.viking_deep_search("test query")  # type: ignore[operator]
    assert "Query expansion:" not in result


def test_viking_deep_search_exception(mock_viking):
    """OSError is caught and returns an error message."""
    _, client = mock_viking
    client.search.side_effect = OSError("network error")

    result = module.viking_deep_search("test")  # type: ignore[operator]
    assert "failed" in result.lower()


def test_viking_deep_search_openviking_error(mock_viking):
    """OpenVikingError is caught and returns an error message."""
    from openviking_cli.exceptions import OpenVikingError

    _, client = mock_viking
    client.search.side_effect = OpenVikingError("search failed")

    result = module.viking_deep_search("test")  # type: ignore[operator]
    assert "failed" in result.lower()


def test_viking_deep_search_custom_args(mock_viking):
    """Custom uri and limit are forwarded to client.search."""
    _, client = mock_viking
    mock_results = MagicMock()
    mock_results.query_plan = []
    mock_results.memories = []
    mock_results.resources = []
    mock_results.skills = []
    client.search.return_value = mock_results

    module.viking_deep_search("query", uri="viking://project/", limit=3)  # type: ignore[operator]
    client.search.assert_called_once_with("query", target_uri="viking://project/", limit=3)


# ─── viking_read() ────────────────────────────────────────────────────────────


def test_viking_read_abstract(mock_viking):
    """depth='abstract' calls client.abstract."""
    _, client = mock_viking
    client.abstract.return_value = "abstract content"

    result = module.viking_read("viking://test", depth="abstract")  # type: ignore[operator]
    assert result == "abstract content"
    client.abstract.assert_called_once_with("viking://test")


def test_viking_read_overview(mock_viking):
    """depth='overview' (default) calls client.overview."""
    _, client = mock_viking
    client.overview.return_value = "overview content"

    result = module.viking_read("viking://test", depth="overview")  # type: ignore[operator]
    assert result == "overview content"
    client.overview.assert_called_once_with("viking://test")


def test_viking_read_full(mock_viking):
    """depth='full' calls client.read."""
    _, client = mock_viking
    client.read.return_value = "full content"

    result = module.viking_read("viking://test", depth="full")  # type: ignore[operator]
    assert result == "full content"
    client.read.assert_called_once_with("viking://test")


def test_viking_read_default_depth(mock_viking):
    """Default depth is 'overview'."""
    _, client = mock_viking
    client.overview.return_value = "default overview"

    result = module.viking_read("viking://test")  # type: ignore[operator]
    assert result == "default overview"
    client.overview.assert_called_once_with("viking://test")


def test_viking_read_exception(mock_viking):
    """OSError is caught and returns an error message including the URI."""
    _, client = mock_viking
    client.overview.side_effect = OSError("read error")

    result = module.viking_read("viking://test")  # type: ignore[operator]
    assert "failed" in result.lower()
    assert "viking://test" in result


def test_viking_read_openviking_error(mock_viking):
    """OpenVikingError is caught and returns an error message."""
    from openviking_cli.exceptions import OpenVikingError

    _, client = mock_viking
    client.abstract.side_effect = OpenVikingError("not found")

    result = module.viking_read("viking://test", depth="abstract")  # type: ignore[operator]
    assert "failed" in result.lower()


def test_viking_read_invalid_depth(mock_viking):
    """Invalid depth value returns a user-friendly error message without raising."""
    _, client = mock_viking
    result = module.viking_read("viking://test", depth="bogus")  # type: ignore[arg-type, operator]
    assert "invalid depth" in result
    assert "bogus" in result
    client.abstract.assert_not_called()
    client.overview.assert_not_called()
    client.read.assert_not_called()


# ─── viking_list() ────────────────────────────────────────────────────────────


def test_viking_list_nonempty(mock_viking):
    """Non-empty directory listing returns formatted content."""
    _, client = mock_viking
    item = MagicMock()
    item.name = "test_memory"
    item.type = "file"
    item.uri = "viking://user/memory/test_memory"
    client.ls.return_value = [item]

    result = module.viking_list("viking://user/")  # type: ignore[operator]
    assert "test_memory" in result
    assert "viking://user/" in result
    assert "Contents of viking://user/:" in result


def test_viking_list_directory_item(mock_viking):
    """Directory items show folder icon."""
    _, client = mock_viking
    item = MagicMock()
    item.name = "subdir"
    item.type = "directory"
    item.uri = "viking://user/subdir/"
    client.ls.return_value = [item]

    result = module.viking_list("viking://user/")  # type: ignore[operator]
    assert "subdir" in result
    # Directory uses folder icon
    assert "📁" in result


def test_viking_list_empty(mock_viking):
    """Empty directory returns Empty: prefix with URI."""
    _, client = mock_viking
    client.ls.return_value = []

    result = module.viking_list("viking://empty/")  # type: ignore[operator]
    assert "Empty:" in result
    assert "viking://empty/" in result


def test_viking_list_exception(mock_viking):
    """OSError is caught and returns an error message."""
    _, client = mock_viking
    client.ls.side_effect = OSError("network error")

    result = module.viking_list("viking://test/")  # type: ignore[operator]
    assert "failed" in result.lower()


def test_viking_list_openviking_error(mock_viking):
    """OpenVikingError is caught and returns an error message."""
    from openviking_cli.exceptions import OpenVikingError

    _, client = mock_viking
    client.ls.side_effect = OpenVikingError("list failed")

    result = module.viking_list("viking://test/")  # type: ignore[operator]
    assert "failed" in result.lower()


def test_viking_list_default_uri(mock_viking):
    """Default URI comes from _DEFAULT_URI (global namespace when no project set)."""
    _, client = mock_viking
    client.ls.return_value = []

    module.viking_list()  # type: ignore[operator]
    client.ls.assert_called_once_with(module._DEFAULT_URI)


# ─── viking_remember() ────────────────────────────────────────────────────────


def test_viking_remember_success_dict_result(mock_viking):
    """Success with dict result uses result.get('uri', ...) for stored URI."""
    _, client = mock_viking
    client.add_resource.return_value = {"uri": "viking://user/memory/test"}

    result = module.viking_remember("remember this", "memory", "test")  # type: ignore[operator]
    assert "Stored at:" in result
    assert "viking://user/memory/test" in result


def test_viking_remember_success_non_dict_result(mock_viking):
    """Success with non-dict result uses str(result) as URI."""
    _, client = mock_viking
    # Return a non-dict object
    mock_result = MagicMock()
    mock_result.__str__ = lambda self: "viking://user/memory/auto"  # type: ignore[method-assign]
    client.add_resource.return_value = mock_result

    result = module.viking_remember("some content", "memory", "auto")  # type: ignore[operator]
    assert "Stored at:" in result
    assert "viking://user/memory/auto" in result


def test_viking_remember_exception_cleans_up(mock_viking, monkeypatch):
    """Exception path: temp file must still be deleted via finally block."""
    _, client = mock_viking
    client.add_resource.side_effect = OSError("storage error")

    deleted_paths = []
    original_unlink = os.unlink

    def tracking_unlink(path):
        deleted_paths.append(path)
        original_unlink(path)

    monkeypatch.setattr(os, "unlink", tracking_unlink)

    result = module.viking_remember("remember this", "memory", "test")  # type: ignore[operator]
    assert "failed" in result.lower()
    assert len(deleted_paths) == 1  # temp file was cleaned up


def test_viking_remember_openviking_error_cleans_up(mock_viking, monkeypatch):
    """OpenVikingError path: temp file must still be deleted."""
    from openviking_cli.exceptions import OpenVikingError

    _, client = mock_viking
    client.add_resource.side_effect = OpenVikingError("store failed")

    deleted_paths = []
    original_unlink = os.unlink

    def tracking_unlink(path):
        deleted_paths.append(path)
        original_unlink(path)

    monkeypatch.setattr(os, "unlink", tracking_unlink)

    result = module.viking_remember("remember this", "memory", "test")  # type: ignore[operator]
    assert "failed" in result.lower()
    assert len(deleted_paths) == 1


def test_viking_remember_target_uri(mock_viking, monkeypatch):
    """Category is used in the target URI; no project → user-scoped path."""
    _, client = mock_viking
    monkeypatch.setattr(module, "_PROJECT", "")
    client.add_resource.return_value = {"uri": "viking://user/decision/foo"}

    module.viking_remember("content", "decision", "foo")  # type: ignore[operator]
    call_kwargs = client.add_resource.call_args.kwargs
    assert call_kwargs["target"] == "viking://user/decision/"
    assert call_kwargs["reason"] == "decision"
    assert call_kwargs["wait"] is True


def test_viking_remember_project_scoped(mock_viking, monkeypatch):
    """When _PROJECT is set, target URI is scoped to the project namespace."""
    _, client = mock_viking
    monkeypatch.setattr(module, "_PROJECT", "myapp")
    client.add_resource.return_value = {"uri": "viking://user/projects/myapp/memory/x"}

    module.viking_remember("content", "memory", "x")  # type: ignore[operator]
    call_kwargs = client.add_resource.call_args.kwargs
    assert call_kwargs["target"] == "viking://user/projects/myapp/memory/"
    assert call_kwargs["reason"] == "memory"


def test_viking_search_project_scoped(mock_viking, monkeypatch):
    """When _DEFAULT_URI is project-scoped, search defaults to that scope."""
    _, client = mock_viking
    monkeypatch.setattr(module, "_DEFAULT_URI", "viking://user/projects/myapp/")
    mock_results = MagicMock()
    mock_results.memories = []
    mock_results.resources = []
    mock_results.skills = []
    client.find.return_value = mock_results

    module.viking_search("test")  # type: ignore[operator]  # no explicit uri → reads _DEFAULT_URI at call time
    client.find.assert_called_once_with("test", target_uri="viking://user/projects/myapp/", limit=5)


def test_viking_remember_dict_missing_uri(mock_viking):
    """Dict result without 'uri' key returns 'unknown'."""
    _, client = mock_viking
    client.add_resource.return_value = {}  # no 'uri' key

    result = module.viking_remember("text", "memory", "name")  # type: ignore[operator]
    assert "Stored at: unknown" in result


def test_viking_remember_rejects_invalid_category(mock_viking):
    """Category with invalid characters returns error without calling add_resource."""
    _, client = mock_viking
    result = module.viking_remember("text", category="../../evil", name="test")  # type: ignore[operator]
    assert "failed" in result.lower()
    assert "invalid characters" in result
    client.add_resource.assert_not_called()


def test_viking_remember_accepts_valid_category(mock_viking):
    """Valid category with hyphens and underscores proceeds to add_resource."""
    _, client = mock_viking
    client.add_resource.return_value = {"uri": "viking://user/my-decision_2/x"}
    result = module.viking_remember("text", category="my-decision_2", name="x")  # type: ignore[operator]
    assert "Stored at:" in result
    client.add_resource.assert_called_once()


# ─── viking_status() ──────────────────────────────────────────────────────────


def test_viking_status_healthy_with_status(mock_viking):
    """Healthy server with get_status() returns version info."""
    _, client = mock_viking
    client.is_healthy.return_value = True
    client.get_status.return_value = {"version": "1.0", "uptime": 42}

    result = module.viking_status()  # type: ignore[operator]
    assert "healthy" in result.lower()
    assert "version" in result


def test_viking_status_healthy_without_status(mock_viking):
    """get_status() raises an exception — should still report healthy."""
    _, client = mock_viking
    client.is_healthy.return_value = True
    client.get_status.side_effect = Exception("not available")

    result = module.viking_status()  # type: ignore[operator]
    assert "healthy" in result.lower()


def test_viking_status_unhealthy(mock_viking):
    """Server reachable but reports unhealthy."""
    _, client = mock_viking
    client.is_healthy.return_value = False

    result = module.viking_status()  # type: ignore[operator]
    assert "unhealthy" in result.lower()


def test_viking_status_unreachable(mock_viking):
    """OSError from get() means server is not reachable."""
    viking, client = mock_viking
    # Make .get() itself fail
    viking.get.side_effect = OSError("connection refused")

    result = module.viking_status()  # type: ignore[operator]
    assert "not reachable" in result.lower()


def test_viking_status_openviking_error(mock_viking):
    """OpenVikingError from get() means server is not reachable."""
    from openviking_cli.exceptions import OpenVikingError

    viking, client = mock_viking
    viking.get.side_effect = OpenVikingError("service unavailable")

    result = module.viking_status()  # type: ignore[operator]
    assert "not reachable" in result.lower()


# ─── _find_free_port() ────────────────────────────────────────────────────────


def test_find_free_port():
    """Returns a valid integer port in the valid range."""
    port = module._find_free_port()
    assert isinstance(port, int)
    assert 1024 <= port <= 65535


def test_find_free_port_returns_different_values():
    """Two successive calls may return same or different ports — both valid."""
    port1 = module._find_free_port()
    port2 = module._find_free_port()
    assert isinstance(port1, int)
    assert isinstance(port2, int)


# ─── _make_dashboard_handler() ────────────────────────────────────────────────


def test_make_dashboard_handler_returns_subclass():
    """Returns a class that is a subclass of SimpleHTTPRequestHandler."""
    from http.server import SimpleHTTPRequestHandler

    handler_cls = module._make_dashboard_handler(Path("/tmp"))
    assert issubclass(handler_cls, SimpleHTTPRequestHandler)


def test_make_dashboard_handler_log_message_suppressed():
    """log_message is overridden and returns None (suppresses output)."""
    handler_cls = module._make_dashboard_handler(Path("/tmp"))

    # Instantiate a minimal handler instance bypassing __init__
    with patch.object(handler_cls, "__init__", return_value=None):
        h = handler_cls.__new__(handler_cls)
        result = handler_cls.log_message(h, "%s", "test message")
        assert result is None


def test_make_dashboard_handler_different_directories():
    """Two handlers bound to different directories are distinct classes."""
    handler1 = module._make_dashboard_handler(Path("/tmp"))
    handler2 = module._make_dashboard_handler(Path("/var"))
    # Each call returns a fresh class
    assert handler1 is not handler2


# ─── _lifespan() ──────────────────────────────────────────────────────────────


def test_lifespan_starts_and_stops():
    """_lifespan starts HTTPServer, opens browser, then shuts down."""
    with (
        patch("src.openviking_mcp_server.HTTPServer") as mock_http_server_cls,
        patch("src.openviking_mcp_server.threading.Thread") as mock_thread_cls,
        patch("src.openviking_mcp_server.webbrowser.open") as mock_browser,
        patch("src.openviking_mcp_server._find_free_port", return_value=9999),
    ):
        mock_httpd = MagicMock()
        mock_http_server_cls.return_value = mock_httpd
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        async def run_lifespan():
            async with module._lifespan(object()):
                pass

        asyncio.run(run_lifespan())

        # Verify server was started and stopped
        mock_thread.start.assert_called_once()
        mock_httpd.shutdown.assert_called_once()
        mock_browser.assert_called_once()
        # Verify browser was opened with correct URL
        call_args = mock_browser.call_args[0][0]
        assert "9999" in call_args
        assert "dashboard.html" in call_args


def test_lifespan_uses_dashboard_host():
    """_lifespan passes _DASHBOARD_HOST to HTTPServer."""
    with (
        patch("src.openviking_mcp_server.HTTPServer") as mock_http_server_cls,
        patch("src.openviking_mcp_server.threading.Thread"),
        patch("src.openviking_mcp_server.webbrowser.open"),
        patch("src.openviking_mcp_server._find_free_port", return_value=8888),
    ):
        mock_httpd = MagicMock()
        mock_http_server_cls.return_value = mock_httpd

        async def run_lifespan():
            async with module._lifespan(object()):
                pass

        asyncio.run(run_lifespan())

        # HTTPServer called with (host, port, handler_class)
        call_args = mock_http_server_cls.call_args
        host, port = call_args[0][0]
        assert host == module._DASHBOARD_HOST
        assert port == 8888


def test_lifespan_thread_is_daemon():
    """The dashboard thread is started as a daemon thread."""
    with (
        patch("src.openviking_mcp_server.HTTPServer") as mock_http_server_cls,
        patch("src.openviking_mcp_server.threading.Thread") as mock_thread_cls,
        patch("src.openviking_mcp_server.webbrowser.open"),
        patch("src.openviking_mcp_server._find_free_port", return_value=7777),
    ):
        mock_httpd = MagicMock()
        mock_http_server_cls.return_value = mock_httpd
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        async def run_lifespan():
            async with module._lifespan(object()):
                pass

        asyncio.run(run_lifespan())

        # Thread was constructed with daemon=True and target=httpd.serve_forever
        call_kwargs = mock_thread_cls.call_args.kwargs
        assert call_kwargs.get("daemon") is True
        assert call_kwargs.get("target") == mock_httpd.serve_forever


def test_make_dashboard_handler_init_calls_super(tmp_path):
    """_Handler.__init__ passes directory kwarg to SimpleHTTPRequestHandler."""
    from http.server import SimpleHTTPRequestHandler

    handler_cls = module._make_dashboard_handler(tmp_path)
    with patch.object(SimpleHTTPRequestHandler, "__init__", return_value=None) as mock_super:
        h = handler_cls.__new__(handler_cls)
        h.__init__(MagicMock(), MagicMock(), MagicMock())
        mock_super.assert_called_once()
        assert mock_super.call_args.kwargs.get("directory") == str(tmp_path)


def test_handler_do_get_serves_dashboard_html(tmp_path):
    """GET /dashboard.html returns 200 and serves the dashboard content."""
    import threading
    from http.server import HTTPServer
    from urllib.request import urlopen

    (tmp_path / "dashboard.html").write_text("<html>DASHBOARD</html>")
    handler_cls = module._make_dashboard_handler(tmp_path)
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/dashboard.html") as resp:
            assert resp.status == 200
            assert b"DASHBOARD" in resp.read()
    finally:
        httpd.shutdown()


def test_handler_do_get_returns_404_for_other_paths(tmp_path):
    """GET any path other than / or /dashboard.html returns 404."""
    import threading
    from http.server import HTTPServer
    from urllib.error import HTTPError
    from urllib.request import urlopen

    handler_cls = module._make_dashboard_handler(tmp_path)
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"http://127.0.0.1:{port}/credentials.yml")
        assert exc_info.value.code == 404
    finally:
        httpd.shutdown()


def test_handler_do_get_root_redirects_to_dashboard(tmp_path):
    """GET / serves dashboard.html content (path rewritten internally)."""
    import threading
    from http.server import HTTPServer
    from urllib.request import urlopen

    (tmp_path / "dashboard.html").write_text("<html>ROOT</html>")
    handler_cls = module._make_dashboard_handler(tmp_path)
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/") as resp:
            assert resp.status == 200
            assert b"ROOT" in resp.read()
    finally:
        httpd.shutdown()


# ─── _MCP_INSTRUCTIONS ────────────────────────────────────────────────────────


def test_mcp_instructions_constant_exists() -> None:
    """_MCP_INSTRUCTIONS is a non-empty string mentioning key tools."""
    assert isinstance(module._MCP_INSTRUCTIONS, str)
    assert len(module._MCP_INSTRUCTIONS) > 100
    assert "viking_search" in module._MCP_INSTRUCTIONS
    assert "viking_remember" in module._MCP_INSTRUCTIONS


# ─── viking_initial_instructions() ───────────────────────────────────────────


def test_viking_initial_instructions_returns_instructions() -> None:
    """Returns the full _MCP_INSTRUCTIONS string."""
    result = module.viking_initial_instructions()  # type: ignore[operator]
    assert result == module._MCP_INSTRUCTIONS
    assert "viking_search" in result


# ─── viking_check_context() ───────────────────────────────────────────────────


def test_viking_check_context_nonempty(mock_viking: tuple) -> None:
    """Non-empty scope returns formatted summary with next steps."""
    _, client = mock_viking
    item = MagicMock()
    item.name = "memory"
    item.type = "directory"
    item.uri = "viking://user/projects/test/memory/"
    client.ls.return_value = [item]

    result = module.viking_check_context("viking://user/projects/test/")  # type: ignore[operator]
    assert "Context available" in result
    assert "Next steps" in result


def test_viking_check_context_empty(mock_viking: tuple) -> None:
    """Empty scope returns guidance to start storing context."""
    _, client = mock_viking
    client.ls.return_value = []

    result = module.viking_check_context("viking://user/")  # type: ignore[operator]
    assert "No context stored" in result
    assert "viking_remember" in result


def test_viking_check_context_default_uri(mock_viking: tuple) -> None:
    """Default URI comes from _DEFAULT_URI when no uri arg given."""
    _, client = mock_viking
    client.ls.return_value = []

    module.viking_check_context()  # type: ignore[operator]
    client.ls.assert_called_once_with(module._DEFAULT_URI)


def test_viking_check_context_exception(mock_viking: tuple) -> None:
    """OSError is caught and returns user-friendly error with status hint."""
    _, client = mock_viking
    client.ls.side_effect = OSError("connection refused")

    result = module.viking_check_context("viking://test/")  # type: ignore[operator]
    assert "failed" in result.lower()
    assert "viking_status" in result


def test_viking_check_context_openviking_error(mock_viking: tuple) -> None:
    """OpenVikingError is caught and returns user-friendly error."""
    from openviking_cli.exceptions import OpenVikingError

    _, client = mock_viking
    client.ls.side_effect = OpenVikingError("not found")

    result = module.viking_check_context("viking://test/")  # type: ignore[operator]
    assert "failed" in result.lower()


def test_viking_check_context_file_items(mock_viking: tuple) -> None:
    """Non-directory items increment the parent category count."""
    _, client = mock_viking
    item = MagicMock()
    item.name = "note.md"
    item.type = "file"
    item.uri = "viking://user/projects/test/memory/note.md"
    client.ls.return_value = [item]

    result = module.viking_check_context("viking://user/projects/test/memory/")  # type: ignore[operator]
    assert "Context available" in result
    assert "Next steps" in result
    # The parent category name extracted from the URI should appear in the output
    assert "memory" in result


# end tests/test_openviking_mcp_server.py
