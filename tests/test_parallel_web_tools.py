"""Exercise the builtin loader, agent dispatcher and real MCP HTTP transport."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.core import BaseAgent
from src.definitions import (
    AgentDefinition,
    BackgroundInstruction,
    OutputInstruction,
    ToolCategory,
    ToolDefinition,
    ToolReference,
    ToolReferenceType,
    UserInstruction,
)
from src.tools import RetryPolicy, ToolRegistry, register_builtin_tools
from src.tools.builtin import web_tools
from src.workspace import AgentWorkspace, WorkspaceConfig


class ScriptedModel:
    """Deterministic model fixture, with actual tool results in its next input."""

    def __init__(self):
        self.messages = []
        self.responses = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        self.messages.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return AIMessage(content="Read the source at https://example.org/source")


def make_agent(tmp_path, task="research", references=None):
    registry = ToolRegistry(enable_retry=False)
    register_builtin_tools(registry)
    definition = AgentDefinition(
        agent_id="researcher",
        name="Researcher",
        description="Find and read current sources",
        background_instruction=BackgroundInstruction(
            role_description="Researcher",
            core_capability="Read web sources",
            task_context="One research task",
        ),
        output_instruction=OutputInstruction(),
        user_instruction=UserInstruction(task_description="Find current sources"),
        tool_references=references or [],
    )
    workspace = AgentWorkspace(WorkspaceConfig(task_id=task, base_path=str(tmp_path)))
    model = ScriptedModel()
    return BaseAgent(
        definition=definition,
        workspace=workspace,
        tool_registry=registry,
        llm_client=model,
    )


@pytest.fixture
def mcp_http(monkeypatch):
    """Keep the real SDK/client caller; replace only the remote HTTP server."""
    requests = []
    state = {"error": False, "timeout": False, "block": False}
    real_client = httpx.AsyncClient
    # Keep this deterministic server fixture independent of the test runner's
    # proxy configuration. Production keeps HTTPX's standard proxy/TLS behavior.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)

    async def server(request):
        payload = json.loads(request.content) if request.content else {}
        requests.append(
            {
                "url": str(request.url),
                "method": request.method,
                "userAgent": request.headers.get("user-agent"),
                "authorization": request.headers.get("authorization"),
                "rpc": payload,
            }
        )
        method = payload.get("method")
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": payload["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "parallel-fixture", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "inputSchema": {"type": "object"},
                    }
                    for name in ("web_search", "web_fetch")
                ]
            }
        elif method == "tools/call":
            if state["timeout"]:
                raise httpx.ReadTimeout("fixture timeout", request=request)
            if state["block"]:
                await asyncio.Event().wait()
            name = payload["params"]["name"]
            data = {
                "results": [
                    {
                        "url": "https://example.org/source",
                        "title": "Source",
                        "excerpts": ["A current source excerpt"],
                    }
                ]
            }
            result = {
                "content": [{"type": "text", "text": json.dumps(data)}],
                "isError": state["error"],
            }
            if state["error"]:
                result["content"][0]["text"] = "Anonymous search quota exceeded"
            elif name == "web_search":
                result["structuredContent"] = data
        else:
            return httpx.Response(405)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result}
        )

    def client_factory(*args, **kwargs):
        # Preserve and exercise every production header/URL/timeout argument.
        return real_client(*args, transport=httpx.MockTransport(server), **kwargs)

    monkeypatch.setattr(web_tools.httpx, "AsyncClient", client_factory)
    return SimpleNamespace(requests=requests, state=state)


def calls(fixture):
    return [
        item["rpc"]["params"]
        for item in fixture.requests
        if item["rpc"].get("method") == "tools/call"
    ]


SEARCH_ARGS = {
    "objective": "Find current source information",
    "search_queries": ["current source information"],
}


@pytest.mark.asyncio
async def test_agent_loader_dispatch_and_result_consumption(
    tmp_path, mcp_http, monkeypatch
):
    # Ambient credentials must not change the anonymous runtime path.
    monkeypatch.setenv("PARALLEL_API_KEY", "must-not-be-sent")
    monkeypatch.setenv("QVERIS_API_KEY", "must-not-be-sent")
    agent = make_agent(tmp_path)
    names = {tool.name for tool in agent.tools}
    assert {"parallel_web_search", "parallel_web_fetch"} <= names
    model = agent.graph_builder.langchain_llm
    model.responses = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "parallel_web_fetch",
                    "args": {"urls": ["https://example.org/source"]},
                    "id": "fetch",
                }
            ],
        ),
        AIMessage(content="Read the source at https://example.org/source"),
    ]
    initial = AIMessage(
        content="",
        tool_calls=[
            {"name": "parallel_web_search", "args": SEARCH_ARGS, "id": "search"}
        ],
    )
    result = await agent.graph_builder._execute_tool_calls_loop(
        initial, [HumanMessage(content="Find sources")], agent.workspace
    )
    assert "https://example.org/source" in result
    tool_messages = [msg for msg in model.messages[-1] if isinstance(msg, ToolMessage)]
    assert len(tool_messages) == 2
    assert all("https://example.org/source" in msg.content for msg in tool_messages)
    assert all("A current source excerpt" in msg.content for msg in tool_messages)
    await agent.graph_builder._execute_single_tool(
        "parallel_web_search", SEARCH_ARGS, agent.workspace
    )
    outgoing = calls(mcp_http)
    assert [call["name"] for call in outgoing] == [
        "web_search",
        "web_fetch",
        "web_search",
    ]
    assert len({call["arguments"]["session_id"] for call in outgoing}) == 1
    assert outgoing[1]["arguments"]["urls"] == ["https://example.org/source"]
    methods = {item["rpc"].get("method") for item in mcp_http.requests}
    assert {"initialize", "tools/list", "tools/call"} <= methods
    assert all(item["url"] == web_tools.PARALLEL_MCP_URL for item in mcp_http.requests)
    assert all(item["userAgent"] == "QVerisFlow/1.0.0" for item in mcp_http.requests)
    assert all(item["authorization"] is None for item in mcp_http.requests)
    print("PARALLEL_CALLER_REQUESTS=" + json.dumps(mcp_http.requests))


@pytest.mark.asyncio
async def test_task_sessions_isolate_interleaved_agents_and_resume(tmp_path, mcp_http):
    first = make_agent(tmp_path, task="first")
    second = make_agent(tmp_path, task="second")
    # Both agents intentionally share one cached tool registry/implementations.
    second.graph_builder.tool_registry = first.tool_registry
    await asyncio.gather(
        first.graph_builder._execute_single_tool(
            "parallel_web_search", SEARCH_ARGS, first.workspace
        ),
        second.graph_builder._execute_single_tool(
            "parallel_web_search", SEARCH_ARGS, second.workspace
        ),
    )
    await first.graph_builder._execute_single_tool(
        "parallel_web_fetch", {"urls": ["https://example.org/source"]}, first.workspace
    )
    ids = [item["arguments"]["session_id"] for item in calls(mcp_http)]
    assert ids[0] != ids[1]
    assert ids[2] == first.workspace.web_search_session_id
    reopened = AgentWorkspace.from_path(str(first.workspace.root))
    assert reopened.web_search_session_id == first.workspace.web_search_session_id
    new_task = make_agent(tmp_path, task="new-chat")
    assert new_task.workspace.web_search_session_id not in ids
    # Explicitly resetting task state creates a new identity, without changing
    # unrelated clients or the identity of another concurrent task.
    path = first.workspace.state_dir / "parallel_search_session"
    before = first.workspace.web_search_session_id
    path.unlink()
    assert first.workspace.web_search_session_id != before
    assert second.workspace.web_search_session_id == ids[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_explicit_saved_tools_and_disabled_search(tmp_path, mcp_http, enabled):
    refs = [
        ToolReference(
            tool_id="parallel_web_search",
            alias="网页搜索",
            tool_type=ToolReferenceType.BUILTIN,
            enabled=enabled,
        )
    ]
    agent = make_agent(tmp_path, references=refs)
    names = {tool.name for tool in agent.tools}
    assert ("parallel_web_search" in names) == enabled
    assert "parallel_web_fetch" not in names
    with pytest.raises(PermissionError):
        await agent.graph_builder._execute_single_tool(
            "parallel_web_fetch",
            {"urls": ["https://example.org/source"]},
            agent.workspace,
        )
    if not enabled:
        with pytest.raises(PermissionError):
            await agent.graph_builder._execute_single_tool(
                "parallel_web_search", SEARCH_ARGS, agent.workspace
            )
    assert not calls(mcp_http)


@pytest.mark.asyncio
async def test_custom_provider_is_preserved(tmp_path, mcp_http):
    refs = [
        ToolReference(
            tool_id="saved_search",
            alias="Saved search",
            tool_type=ToolReferenceType.CUSTOM,
        )
    ]
    agent = make_agent(tmp_path, references=refs)

    async def saved_provider(query, _context=None):
        if query == "fail":
            raise RuntimeError("Saved provider failed")
        return {"url": "https://saved.example/source"}

    agent.tool_registry.register(
        ToolDefinition(
            tool_id="saved_search",
            name="Saved search",
            alias="Saved search",
            description="An explicitly selected provider",
            category=ToolCategory.WEB_SEARCH,
            output_schema={"type": "object"},
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        saved_provider,
    )
    agent.tools = agent._get_tools()
    agent.graph_builder.tools = agent.tools
    assert "saved_search" in {tool.name for tool in agent.tools}
    assert not any(tool.name.startswith("parallel_") for tool in agent.tools)
    result = await agent.graph_builder._execute_single_tool(
        "saved_search", {"query": "source"}, agent.workspace
    )
    assert result["url"] == "https://saved.example/source"
    with pytest.raises(RuntimeError, match="Saved provider failed"):
        await agent.graph_builder._execute_single_tool(
            "saved_search", {"query": "fail"}, agent.workspace
        )
    assert not mcp_http.requests


@pytest.mark.asyncio
async def test_quota_retry_keeps_task_identity(tmp_path, mcp_http):
    agent = make_agent(tmp_path)
    mcp_http.state["error"] = True
    with pytest.raises(web_tools.ParallelSearchError, match="quota"):
        await agent.graph_builder._execute_single_tool(
            "parallel_web_search", SEARCH_ARGS, agent.workspace
        )
    mcp_http.state["error"] = False
    result = await agent.graph_builder._execute_single_tool(
        "parallel_web_search", SEARCH_ARGS, agent.workspace
    )
    assert result["results"][0]["url"] == "https://example.org/source"
    assert len({item["arguments"]["session_id"] for item in calls(mcp_http)}) == 1


@pytest.mark.asyncio
async def test_transport_timeout_and_cancellation(tmp_path, mcp_http, monkeypatch):
    agent = make_agent(tmp_path)
    mcp_http.state["block"] = True
    monkeypatch.setattr(web_tools, "REQUEST_TIMEOUT", 0.05)
    with pytest.raises(TimeoutError):
        await agent.graph_builder._execute_single_tool(
            "parallel_web_search", SEARCH_ARGS, agent.workspace
        )
    monkeypatch.setattr(web_tools, "REQUEST_TIMEOUT", 60)
    task = asyncio.create_task(
        agent.graph_builder._execute_single_tool(
            "parallel_web_search", SEARCH_ARGS, agent.workspace
        )
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len({item["arguments"]["session_id"] for item in calls(mcp_http)}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.org/data", "https://user:secret@example.org"],
)
async def test_invalid_page_urls_never_reach_transport(tmp_path, mcp_http, url):
    agent = make_agent(tmp_path)
    with pytest.raises((web_tools.ParallelSearchError, ValueError)):
        await agent.graph_builder._execute_single_tool(
            "parallel_web_fetch", {"urls": [url]}, agent.workspace
        )
    assert not mcp_http.requests


@pytest.mark.asyncio
async def test_http_read_failure_has_no_provider_fallback(tmp_path, mcp_http):
    agent = make_agent(tmp_path)
    mcp_http.state["timeout"] = True
    with pytest.raises(BaseExceptionGroup) as error:
        await agent.graph_builder._execute_single_tool(
            "parallel_web_search", SEARCH_ARGS, agent.workspace
        )
    assert "fixture timeout" in str(error.value.exceptions)
    assert len(calls(mcp_http)) == 1


def test_task_session_creation_is_atomic_across_threads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    workspace = AgentWorkspace(
        WorkspaceConfig(task_id="shared", base_path=str(tmp_path))
    )

    def reopen(_):
        return AgentWorkspace.from_path(str(workspace.root)).web_search_session_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert len(set(executor.map(reopen, range(20)))) == 1


@pytest.mark.asyncio
async def test_invalid_task_session_cannot_fall_back_to_anonymous_call(
    tmp_path, mcp_http
):
    agent = make_agent(tmp_path)
    (agent.workspace.state_dir / "parallel_search_session").write_text(
        "invalid", encoding="utf-8"
    )
    with pytest.raises(web_tools.ParallelSearchError, match="session identity"):
        await agent.graph_builder._execute_single_tool(
            "parallel_web_search", SEARCH_ARGS, agent.workspace
        )
    assert not mcp_http.requests


@pytest.mark.asyncio
async def test_default_registry_timeout_retries_keep_task_identity(
    tmp_path, mcp_http, monkeypatch
):
    agent = make_agent(tmp_path)
    agent.tool_registry._enable_retry = True
    # Keep the production default retry count. Accelerate only the timer and
    # backoff so the real dispatcher/registry/SDK path can be exercised quickly.
    agent.tool_registry.set_tool_retry_policy(
        "parallel_web_search", RetryPolicy(base_delay=0, max_delay=0, jitter=False)
    )
    mcp_http.state["block"] = True
    monkeypatch.setattr(web_tools, "REQUEST_TIMEOUT", 0.02)
    with pytest.raises(TimeoutError):
        await agent.graph_builder._execute_single_tool(
            "parallel_web_search", SEARCH_ARGS, agent.workspace
        )
    outgoing = calls(mcp_http)
    assert len(outgoing) == 4  # initial attempt plus the existing three retries
    assert {item["arguments"]["session_id"] for item in outgoing} == {
        agent.workspace.web_search_session_id
    }
