"""MCP 请求客户端的无 CAD 回归测试。"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, TextContent

SPEC = importlib.util.spec_from_file_location(
    "mcp_request", Path(__file__).resolve().parents[1] / "scripts" / "mcp_request.py"
)
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


@pytest.fixture
def fake_server(monkeypatch):
    session = SimpleNamespace(
        initialize=AsyncMock(),
        list_tools=AsyncMock(return_value=SimpleNamespace(
            tools=[SimpleNamespace(name="first"), SimpleNamespace(name="second")], nextCursor=None
        )),
        call_tool=AsyncMock(return_value=CallToolResult(
            content=[TextContent(type="text", text='{"status": "success", "value": 3}')],
            structuredContent={"status": "success", "value": 3},
        )),
    )
    captured = []

    @asynccontextmanager
    async def transport(parameters):
        captured.append(parameters)
        yield object(), object()

    @asynccontextmanager
    async def session_context(*args):
        yield session

    monkeypatch.setattr(client, "stdio_client", transport)
    monkeypatch.setattr(client, "ClientSession", session_context)
    return session, captured


def run_batch(tmp_path, requests, timeout=10):
    """执行模拟请求，返回退出码及磁盘上的结果。"""
    output = tmp_path / "results.json"
    code = asyncio.run(client._execute_requests(requests, output, timeout))
    return code, json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.parametrize("document", [
    [], {}, {"requests": []}, {"requests": [None]}, {"requests": [{"name": ""}]},
    {"requests": [{"name": "first", "arguments": []}]},
    {"requests": [{"name": "first", "extra": True}]},
    {"requests": [{"name": "first"}], "extra": True},
])
def test_invalid_request_never_starts_server(tmp_path, fake_server, document):
    request = tmp_path / "request.json"
    request.write_text(json.dumps(document), encoding="utf-8")
    assert client.main(["--request", str(request), "--output", str(tmp_path / "out.json")]) == 1
    assert fake_server[1] == []
    assert not (tmp_path / "out.json").exists()


def test_unknown_tool_prevents_all_calls(tmp_path, fake_server):
    code, report = run_batch(tmp_path, [{"name": "first"}, {"name": "unknown"}])
    assert code == 1
    assert report["status"] == "error"
    assert "unknown" in report["error"]
    assert report["results"] == []
    fake_server[0].call_tool.assert_not_awaited()


def test_success_preserves_each_result_and_environment(tmp_path, fake_server, monkeypatch):
    monkeypatch.setenv("SOLIDWORKS_MCP_REQUIRE_DOCUMENT_TARGET", "1")
    session, captured = fake_server
    saved = []

    async def call(name, arguments):
        saved.append(json.loads((tmp_path / "results.json").read_text(encoding="utf-8")))
        return CallToolResult(content=[], structuredContent={"status": "success", "name": name})

    session.call_tool.side_effect = call
    code, report = run_batch(tmp_path, [{"name": "first", "arguments": {"params": {"process_id": 1}}},
                                         {"name": "second"}])
    assert code == 0
    assert report["status"] == "success"
    assert len(saved[0]["results"]) == 0
    assert len(saved[1]["results"]) == 1
    assert [item["name"] for item in report["results"]] == ["first", "second"]
    assert captured[0].cwd == str(client.ROOT)
    assert captured[0].args == [str(client.SERVER_PATH)]
    assert captured[0].env["SOLIDWORKS_MCP_REQUIRE_DOCUMENT_TARGET"] == "1"
    assert not (tmp_path / "results.json.tmp").exists()
    assert session.call_tool.await_args_list[0].kwargs["arguments"] == {"params": {"process_id": 1}}


@pytest.mark.parametrize("result", [
    CallToolResult(content=[], isError=True),
    CallToolResult(content=[], structuredContent={"status": "error"}),
    CallToolResult(content=[], structuredContent={"result": {"status": "blocked"}}),
    CallToolResult(content=[TextContent(type="text", text='{"status": "error"}')]),
])
def test_error_stops_chain_and_preserves_failure(tmp_path, fake_server, result):
    fake_server[0].call_tool.return_value = result
    code, report = run_batch(tmp_path, [{"name": "first"}, {"name": "second"}])
    assert code == 1
    assert report["status"] == "error"
    assert len(report["results"]) == 1
    assert report["results"][0]["name"] == "first"
    assert fake_server[0].call_tool.await_count == 1


def test_existing_output_is_not_overwritten(tmp_path, fake_server):
    output = tmp_path / "results.json"
    output.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        asyncio.run(client._execute_requests([{"name": "first"}], output, 10))
    assert output.read_text(encoding="utf-8") == "original"
    assert fake_server[1] == []


def test_timeout_preserves_completed_results(tmp_path, fake_server):
    async def call(name, arguments):
        if name == "second":
            await asyncio.sleep(10)
        return CallToolResult(content=[], structuredContent={"status": "success"})

    fake_server[0].call_tool.side_effect = call
    code, report = run_batch(tmp_path, [{"name": "first"}, {"name": "second"}], timeout=0.05)
    assert code == 1
    assert report["status"] == "timeout"
    assert len(report["results"]) == 1
    assert report["current_request"]["name"] == "second"


def test_binary_and_large_text_are_explicitly_omitted():
    assert client._small_payload({"type": "image", "data": "abcdef", "value": 4}) == {
        "type": "image", "data": {"omitted": True, "characters": 6, "reason": "binary payload"}, "value": 4,
    }
    assert client._small_payload("x" * 40000)["omitted"] is True


def test_atomic_write_does_not_consume_existing_temporary(tmp_path):
    output = tmp_path / "results.json"
    temporary = tmp_path / "results.json.tmp"
    output.write_text("original", encoding="utf-8")
    temporary.write_text("unrelated", encoding="utf-8")
    with pytest.raises(FileExistsError):
        client._atomic_write(output, {"status": "success"})
    assert output.read_text(encoding="utf-8") == "original"
    assert temporary.read_text(encoding="utf-8") == "unrelated"


def test_list_tools_pagination_checks_entire_list(tmp_path, fake_server):
    fake_server[0].list_tools.side_effect = [
        SimpleNamespace(tools=[SimpleNamespace(name="first")], nextCursor="page2"),
        SimpleNamespace(tools=[SimpleNamespace(name="second")], nextCursor=None),
    ]
    code, report = run_batch(tmp_path, [{"name": "second"}])
    assert code == 0
    assert report["results"][0]["name"] == "second"
    assert fake_server[0].list_tools.await_args_list[1].kwargs == {"cursor": "page2"}


def test_transport_exception_preserves_previous_result(tmp_path, fake_server):
    fake_server[0].call_tool.side_effect = [
        CallToolResult(content=[], structuredContent={"status": "success"}),
        RuntimeError("transport disconnected"),
    ]
    code, report = run_batch(tmp_path, [{"name": "first"}, {"name": "second"}])
    assert code == 1
    assert report["status"] == "error"
    assert "transport disconnected" in report["error"]
    assert len(report["results"]) == 1
    assert report["current_request"]["name"] == "second"


def test_small_plain_data_value_is_preserved():
    assert client._small_payload({"data": "ordinary structured value"}) == {
        "data": "ordinary structured value"
    }
