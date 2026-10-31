"""Keyless web search and page extraction through Parallel Search MCP."""

import asyncio
import json
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation

from ...definitions import ToolCategory
from ..registry import tool

PARALLEL_MCP_URL = "https://search.parallel.ai/mcp"
REQUEST_TIMEOUT = 60


class ParallelSearchError(RuntimeError):
    """The remote search service could not complete a tool call."""


def _session_id(context: dict[str, Any] | None) -> str:
    """A workspace is one research task; a bare call is a standalone task."""
    if context is not None:
        workspace = context.get("workspace")
        if workspace is not None:
            try:
                return workspace.web_search_session_id
            except (ValueError, TypeError) as exc:
                raise ParallelSearchError(
                    "Invalid stored Parallel session identity"
                ) from exc
        # Workflow contexts can group tool nodes without a workspace. Never send
        # workflow/task names or other user-supplied identifiers to the service.
        value = context.setdefault("_parallel_search_session_id", str(uuid4()))
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ParallelSearchError("Invalid Parallel session identity") from exc
    return str(uuid4())


async def _call_parallel(
    name: str, arguments: dict[str, Any], context: dict[str, Any] | None
) -> dict[str, Any]:
    if context is not None and "allowed_tools" in context:
        if "parallel_" + name not in context["allowed_tools"]:
            raise PermissionError("This web tool is disabled for the current agent")
    arguments = {**arguments, "session_id": _session_id(context)}
    # No authentication is configured. Standard HTTPX proxy/TLS settings still
    # apply; QVeris and Claude credentials/configuration remain independent.
    async with asyncio.timeout(REQUEST_TIMEOUT):
        async with httpx.AsyncClient(
            headers={"User-Agent": "QVerisFlow/1.0.0"},
            timeout=httpx.Timeout(REQUEST_TIMEOUT),
        ) as client:
            async with streamable_http_client(PARALLEL_MCP_URL, http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=REQUEST_TIMEOUT),
                    client_info=Implementation(name="QVerisFlow", version="1.0.0"),
                ) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    if name not in {item.name for item in tools.tools}:
                        raise ParallelSearchError(
                            f"Parallel MCP does not expose {name}"
                        )
                    result = await session.call_tool(name, arguments)
    if result.isError:
        message = "\n".join(item.text for item in result.content if item.type == "text")
        raise ParallelSearchError(message or "Parallel MCP tool failed")
    if result.structuredContent is not None:
        return result.structuredContent
    # Older MCP servers return their JSON payload as a text content block.
    if len(result.content) == 1 and result.content[0].type == "text":
        try:
            data = json.loads(result.content[0].text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(data, dict):
                return data
    return {"content": [item.model_dump(exclude_none=True) for item in result.content]}


@tool(
    tool_id="parallel_web_search",
    name="网页搜索",
    alias="网页搜索",
    description=(
        "Search the web for current information using Parallel Search MCP. "
        "Returns source URLs and relevant excerpts. No account or API key required. "
        "Use one focused objective and related keyword queries."
    ),
    category=ToolCategory.WEB_SEARCH,
    input_schema={
        "type": "object",
        "properties": {
            "objective": {"type": "string", "minLength": 1},
            "search_queries": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
        },
        "required": ["objective", "search_queries"],
        "additionalProperties": False,
    },
    is_async=True,
    is_remote=True,
    provider="Parallel",
    timeout=REQUEST_TIMEOUT,
)
async def parallel_web_search(
    objective: str, search_queries: list[str], _context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Search in Fast mode with the anonymous Parallel Search MCP endpoint."""
    return await _call_parallel(
        "web_search",
        {"objective": objective, "search_queries": search_queries},
        _context,
    )


@tool(
    tool_id="parallel_web_fetch",
    name="读取网页",
    alias="读取网页",
    description=(
        "Fetch relevant excerpts from HTTP/HTTPS page URLs using Parallel Search MCP. "
        "Use URLs returned by web search or supplied by the user. "
        "Prefer excerpts; full_content can return large documents."
    ),
    category=ToolCategory.WEB_SEARCH,
    input_schema={
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string", "format": "uri"},
                "minItems": 1,
                "maxItems": 20,
            },
            "objective": {"type": "string", "maxLength": 200},
            "search_queries": {"type": "array", "items": {"type": "string"}},
            "full_content": {"type": "boolean", "default": False},
        },
        "required": ["urls"],
        "additionalProperties": False,
    },
    is_async=True,
    is_remote=True,
    provider="Parallel",
    timeout=REQUEST_TIMEOUT,
)
async def parallel_web_fetch(
    urls: list[str],
    objective: str | None = None,
    search_queries: list[str] | None = None,
    full_content: bool | None = False,
    _context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read web pages without executing page content locally."""
    if not 1 <= len(urls) <= 20:
        raise ParallelSearchError("Provide between 1 and 20 web URLs")
    for url in urls:
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise ParallelSearchError(
                "Page URLs must be valid HTTP/HTTPS URLs"
            ) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ParallelSearchError(
                "Page URLs must be HTTP/HTTPS without credentials"
            )
    arguments: dict[str, Any] = {"urls": urls, "full_content": bool(full_content)}
    if objective is not None:
        arguments["objective"] = objective
    if search_queries is not None:
        arguments["search_queries"] = search_queries
    return await _call_parallel("web_fetch", arguments, _context)
