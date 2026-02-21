# start src/openviking_mcp_server.py
"""OpenViking MCP Server — FastMCP wrapper for Claude Code.

Reads ~/.openviking/runtime.json for current ports written by start_openviking.sh.
Reads credentials.yml for the API key. Config loaded into Pydantic models at startup.
Uses a class-based connection manager with tenacity retry logic.
"""

import json
import logging
import os
import socket
import tempfile
import threading
import webbrowser
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Literal

import openviking as ov
import yaml
from fastmcp import FastMCP
from openviking_cli.exceptions import OpenVikingError
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent.parent / "logs" / "openviking_mcp.log"),
    ],
)
logger = logging.getLogger("openviking_mcp")


# ─── Config models ────────────────────────────────────────────────────────────


class OpenVikingCreds(BaseModel):
    """Validated secrets from credentials.yml."""

    api_key: str


class RuntimePorts(BaseModel):
    """Validated runtime state from ~/.openviking/runtime.json."""

    openviking_url: str
    embedding_url: str
    openviking_port: int
    embedding_port: int


def _load_credentials() -> OpenVikingCreds:
    """Load and validate credentials.yml.

    Returns:
        Validated credentials model.

    Raises:
        FileNotFoundError: If credentials.yml is missing.
        ValidationError: If credentials fail Pydantic validation.
    """
    creds_path = Path(__file__).parent.parent / "credentials.yml"
    if not creds_path.exists():
        raise FileNotFoundError(
            f"credentials.yml not found at {creds_path}. "
            "Copy credentials.yml.dist to credentials.yml and fill in values."
        )
    raw = yaml.safe_load(creds_path.read_text())
    return OpenVikingCreds(**raw["openviking"])


def _load_runtime() -> RuntimePorts | None:
    """Load current ports from runtime.json written by start_openviking.sh.

    Returns:
        Validated RuntimePorts model, or None if file absent.
    """
    runtime_path = Path.home() / ".openviking" / "runtime.json"
    if not runtime_path.exists():
        logger.warning("runtime.json not found — is the stack running?")
        return None
    raw = json.loads(runtime_path.read_text())
    return RuntimePorts(**raw)


_creds = _load_credentials()
_runtime = _load_runtime()
_DEFAULT_OPENVIKING_URL: str = "http://localhost:1933"
_OPENVIKING_URL = _runtime.openviking_url if _runtime else _DEFAULT_OPENVIKING_URL
_CONTENT_PREVIEW_LEN: int = 300
_DASHBOARD_HOST: str = "127.0.0.1"
_PROJECT: str = os.getenv("KARVE_PROJECT", "")
_DEFAULT_URI: str = f"viking://user/projects/{_PROJECT}/" if _PROJECT else "viking://"


# ─── Connection manager ───────────────────────────────────────────────────────


class VikingClient:
    """Lazy-initialized OpenViking HTTP client with retry logic.

    Defers connection until first use so the FastMCP subprocess can start
    cleanly even when OpenViking is not yet running.
    """

    def __init__(self, url: str, api_key: str) -> None:
        """Store connection parameters; actual connection deferred to first use.

        Args:
            url: Base URL of the OpenViking server.
            api_key: API key for authentication.
        """
        self._url = url
        self._api_key = api_key
        self._client: ov.SyncHTTPClient | None = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _connect(self) -> ov.SyncHTTPClient:
        """Create and initialize a new HTTP client.

        Returns:
            Initialized SyncHTTPClient.
        """
        logger.info("Connecting to OpenViking at %s", self._url)
        client = ov.SyncHTTPClient(url=self._url, api_key=self._api_key)
        client.initialize()
        return client

    def get(self) -> ov.SyncHTTPClient:
        """Return initialized client, connecting on first call.

        Returns:
            Ready-to-use SyncHTTPClient.

        Raises:
            Exception: If connection fails after retries.
        """
        if self._client is None:
            self._client = self._connect()
        return self._client


_viking = VikingClient(url=_OPENVIKING_URL, api_key=_creds.api_key)


# ─── Formatting helpers ───────────────────────────────────────────────────────


def _get_item_content(item: object) -> str:
    """Extract preview text from a result item using content/abstract/overview fallbacks.

    Args:
        item: A result item with optional content, abstract, or overview attributes.

    Returns:
        Content string truncated to _CONTENT_PREVIEW_LEN, or empty string if absent.
    """
    text = (
        getattr(item, "content", None)
        or getattr(item, "abstract", None)
        or getattr(item, "overview", None)
        or ""
    )
    return str(text)[:_CONTENT_PREVIEW_LEN]


def _fmt_item(item: object) -> list[str]:
    """Format a single result item as Markdown bullet lines.

    Args:
        item: A result item with uri, score, and optional content attributes.

    Returns:
        One or two lines: the URI bullet and optionally an indented content line.
    """
    score = getattr(item, "score", None)
    uri = getattr(item, "uri", "")
    score_str = f" (score: {score:.3f})" if score is not None else ""
    lines = [f"- **{uri}**{score_str}"]
    content = _get_item_content(item)
    if content:
        lines.append(f"  {content}")
    return lines


def _fmt_results(results: object) -> str:
    """Format FindResult or SearchResult into readable Markdown.

    Args:
        results: OpenViking result object with memories/resources/skills attrs.

    Returns:
        Formatted Markdown string.
    """
    lines: list[str] = []
    for category in ("memories", "resources", "skills"):
        items = getattr(results, category, None) or []
        if not items:
            continue
        lines.append(f"\n## {category.capitalize()}")
        for item in items:
            lines.extend(_fmt_item(item))
    return "\n".join(lines) if lines else "No results found."


def _write_temp_resource(text: str, name: str) -> str:
    """Write text to a temporary file for add_resource().

    Args:
        text: Content to write.
        name: Stem appended to the temp filename (empty string for no stem).

    Returns:
        Absolute path to the temp file (caller must delete).
    """
    suffix = f"_{name}.md" if name else ".md"
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as tmp:
        tmp.write(text)
        return tmp.name


# ─── MCP server ───────────────────────────────────────────────────────────────


def _find_free_port() -> int:
    """Find an available TCP port on localhost.

    Returns:
        A free port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _make_dashboard_handler(directory: Path) -> type[SimpleHTTPRequestHandler]:
    """Create an HTTP request handler class bound to a specific directory.

    Args:
        directory: Path to serve files from.

    Returns:
        A SimpleHTTPRequestHandler subclass serving from directory.
    """

    class _Handler(SimpleHTTPRequestHandler):
        """HTTP request handler serving the dashboard with suppressed access logs."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Initialize with a fixed directory."""
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """Suppress HTTP access logs — MCP server uses stdio."""

    return _Handler


@asynccontextmanager
async def _lifespan(server: object) -> AsyncGenerator[None, None]:
    """Start the dashboard HTTP server and open it in a browser on MCP startup.

    Args:
        server: The FastMCP server instance (unused directly).

    Yields:
        None — yields control back to FastMCP during server lifetime.
    """
    dashboard_dir = Path(__file__).parent.parent
    port = _find_free_port()
    httpd = HTTPServer((_DASHBOARD_HOST, port), _make_dashboard_handler(dashboard_dir))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    logger.info("Dashboard served at http://%s:%d/dashboard.html", _DASHBOARD_HOST, port)
    webbrowser.open(f"http://{_DASHBOARD_HOST}:{port}/dashboard.html")
    yield
    httpd.shutdown()


mcp = FastMCP("OpenViking", lifespan=_lifespan)


@mcp.tool
def viking_search(query: str, uri: str | None = None, limit: int = 5) -> str:
    """Search OpenViking for relevant memories, resources, and skills.

    Uses semantic similarity for quick lookups of stored context.

    Args:
        query: What to search for.
        uri: Scope the search. Defaults to the project scope when KARVE_PROJECT
             is set, otherwise the global 'viking://' namespace.
        limit: Max results to return.

    Returns:
        Formatted Markdown list of matching items with relevance scores.
    """
    effective_uri = uri if uri is not None else _DEFAULT_URI
    try:
        results = _viking.get().find(query, target_uri=effective_uri, limit=limit)
        return _fmt_results(results)
    except (OpenVikingError, OSError) as exc:
        logger.error("viking_search failed: %s", exc)
        return f"viking_search failed: {exc}\nRun: ./scripts/start_openviking.sh"


@mcp.tool
def viking_deep_search(query: str, uri: str | None = None, limit: int = 5) -> str:
    """Intent-aware search with query expansion for better recall.

    Slower than viking_search but analyzes context and expands search terms.

    Args:
        query: What to search for — natural language works well.
        uri: Scope the search. Defaults to the project scope when KARVE_PROJECT
             is set, otherwise the global 'viking://' namespace.
        limit: Max results.

    Returns:
        Formatted Markdown with query expansion plan and matching items.
    """
    effective_uri = uri if uri is not None else _DEFAULT_URI
    try:
        results = _viking.get().search(query, target_uri=effective_uri, limit=limit)
        plan = getattr(results, "query_plan", [])
        header = f"Query expansion: {plan}\n" if plan else ""
        return header + _fmt_results(results)
    except (OpenVikingError, OSError) as exc:
        logger.error("viking_deep_search failed: %s", exc)
        return f"viking_deep_search failed: {exc}"


@mcp.tool
def viking_read(
    uri: str,
    depth: Literal["abstract", "overview", "full"] = "overview",
) -> str:
    """Read content from OpenViking at a specific URI.

    Args:
        uri: The viking:// URI to read.
        depth: Content verbosity — 'abstract' (~100 tokens),
               'overview' (~2000 tokens), or 'full' (complete).

    Returns:
        Content string at the requested depth.
    """
    try:
        client = _viking.get()
        dispatch = {
            "abstract": client.abstract,
            "full": client.read,
            "overview": client.overview,
        }
        return str(dispatch[depth](uri))
    except (OpenVikingError, OSError) as exc:
        logger.error("viking_read failed for %s: %s", uri, exc)
        return f"viking_read failed for {uri}: {exc}"


@mcp.tool
def viking_list(uri: str | None = None) -> str:
    """Browse the OpenViking context filesystem at a given URI.

    Args:
        uri: Directory URI to list. Defaults to the project scope when
             KARVE_PROJECT is set, otherwise the global 'viking://' namespace.

    Returns:
        Formatted directory listing with names and types.
    """
    effective_uri = uri if uri is not None else _DEFAULT_URI
    try:
        items = _viking.get().ls(effective_uri)
        if not items:
            return f"Empty: {effective_uri}"
        lines = [f"Contents of {effective_uri}:"]
        for item in items:
            name = getattr(item, "name", str(item))
            kind = getattr(item, "type", "")
            item_uri = getattr(item, "uri", "")
            icon = "📁" if kind == "directory" else "📄"
            lines.append(f"  {icon} {name}  {item_uri}")
        return "\n".join(lines)
    except (OpenVikingError, OSError) as exc:
        logger.error("viking_list failed for %s: %s", effective_uri, exc)
        return f"viking_list failed for {effective_uri}: {exc}"


@mcp.tool
def viking_remember(text: str, category: str = "memory", name: str = "") -> str:
    """Store text as a resource in OpenViking for future retrieval.

    Args:
        text: The content to store.
        category: Storage category (e.g. 'memory', 'preference', 'decision').
        name: Optional filename stem (auto-generated if empty).

    Storage target: ``viking://user/projects/<project>/<category>/`` when
    KARVE_PROJECT is set, otherwise ``viking://user/<category>/``.

    Returns:
        Confirmation string with the stored URI.
    """
    tmp_path = _write_temp_resource(text, name)
    try:
        target = (
            f"viking://user/projects/{_PROJECT}/{category}/"
            if _PROJECT
            else f"viking://user/{category}/"
        )
        result = _viking.get().add_resource(
            path=tmp_path,
            target=target,
            reason=category,
            wait=True,
        )
    except (OpenVikingError, OSError) as exc:
        logger.error("viking_remember failed: %s", exc)
        return f"viking_remember failed: {exc}"
    finally:
        os.unlink(tmp_path)
    stored_uri = result.get("uri", "unknown") if isinstance(result, dict) else str(result)
    logger.info("Stored resource at %s", stored_uri)
    return f"Stored at: {stored_uri}"


@mcp.tool
def viking_status() -> str:
    """Check if OpenViking is running and return server health status.

    Returns:
        Health status string — includes server details when healthy.
    """
    try:
        client = _viking.get()
        if not client.is_healthy():
            return "OpenViking reachable but reports unhealthy status."
        try:
            status = client.get_status()
            return f"✓ OpenViking healthy\n\n{json.dumps(status, indent=2)}"
        except Exception:  # noqa: BLE001
            return f"✓ OpenViking healthy at {_OPENVIKING_URL}"
    except (OpenVikingError, OSError) as exc:
        logger.error("viking_status check failed: %s", exc)
        return (
            f"✗ OpenViking not reachable at {_OPENVIKING_URL}\n"
            f"Error: {exc}\n"
            f"Run: ./scripts/start_openviking.sh"
        )


if __name__ == "__main__":
    mcp.run()  # stdio transport — default for Claude Code subprocess mode
# end src/openviking_mcp_server.py
