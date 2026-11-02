"""通过标准 MCP stdio 顺序执行 JSON 请求，并逐步保存可审查的结果。

用法：python scripts/mcp_request.py --request requests.json --output results.json
输入：{"requests": [{"name": "solidworks_connect", "arguments": {"params": {}}}]}
仅启动本仓库 MCP 服务；本客户端不访问 COM、不控制窗口、不自行启动 CAD。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "mcp-server" / "server.py"
MAX_STRING_LENGTH = 32768


def _load_requests(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or set(document) != {"requests"}:
        raise ValueError("Request must contain only a 'requests' array")
    requests = document["requests"]
    if not isinstance(requests, list) or not requests:
        raise ValueError("'requests' must be a non-empty array")
    for index, request in enumerate(requests):
        if not isinstance(request, dict) or set(request) - {"name", "arguments"}:
            raise ValueError(f"Invalid request at index {index}")
        if not isinstance(request.get("name"), str) or not request["name"].strip():
            raise ValueError(f"Request {index} requires a non-empty tool name")
        if "arguments" in request and not isinstance(request["arguments"], dict):
            raise ValueError(f"Request {index} arguments must be an object")
    return requests


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    """只重试已序列化结果的文件替换；绝不重放任何 MCP 调用。"""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    created = complete = False
    delays = (0.05, 0.10, 0.20, 0.40)
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        complete = True
        for attempt in range(len(delays) + 1):
            try:
                os.replace(temporary, path)
                return
            except OSError as error:
                if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == len(delays):
                    # 保留完整的新结果；旧目标文件不删除，错误说明给出恢复路径。
                    error.atomic_json_temporary = str(temporary)
                    raise
                time.sleep(delays[attempt])
    finally:
        if created and not complete:
            try:
                temporary.unlink()
            except OSError:
                pass


def _small_payload(value: Any) -> Any:
    # 小型结构化结果保持完整；二进制和超长字符串只保留明确的省略说明。
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if (key == "blob" or (key == "data" and value.get("type") in {"image", "audio"})) and isinstance(item, str):
                result[key] = {"omitted": True, "characters": len(item), "reason": "binary payload"}
            else:
                result[key] = _small_payload(item)
        return result
    if isinstance(value, list):
        return [_small_payload(item) for item in value]
    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return {"omitted": True, "characters": len(value), "reason": "oversized string"}
    return value


def _result_documents(payload: dict[str, Any]):
    """Unwrap MCP output envelopes only; do not scan diagnostic/history data."""
    values = [payload.get("structuredContent")]
    values.extend(item.get("parsed_json") for item in payload.get("content", [])
                  if isinstance(item, dict) and item.get("type") == "text")
    for value in values:
        for _ in range(8):
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    break
            elif isinstance(value, dict):
                yield value
                # This reader's current response has its own completion status.
                # It is an explicit output envelope, unlike historical evidence.
                if value.get("scope") == "TURN_INPROCESS_CLIENT_READ_V1" and isinstance(value.get("host_response"), dict):
                    yield value["host_response"]
                # FastMCP string results may have a structured {"result": ...}
                # mirror. A business result's own nested data is not an envelope.
                if set(value) == {"result"}:
                    value = value["result"]
                else:
                    break
            else:
                break


def _classify_result(payload: dict[str, Any]) -> dict[str, Any]:
    outcome = {"status": "success", "may_continue": True}
    if payload.get("isError") is True:
        return dict(status="error", may_continue=False, reason="MCP isError=true")
    for value in _result_documents(payload):
        status = value.get("status")
        status = status.lower() if isinstance(status, str) else None
        if value.get("isError") is True or status in {"error", "blocked", "failed", "timeout", "uncertain"}:
            return dict(status="error", may_continue=False,
                        reason="Structured isError=true" if value.get("isError") is True else f"Structured status={status}")
        if any(value.get(key) for key in ("error", "issue", "terminal_issue", "cleanup_issue")):
            return dict(status="error", may_continue=False, reason="Structured current error/issue")
        if status == "partial" or value.get("nc_parameters_complete") is False:
            outcome.update(status="partial", may_continue=False, reason="Structured result is partial")
        elif status == "review_required" and value.get("may_continue") is False and outcome["status"] == "success":
            outcome.update(status="review_required", reason="Structured result requires review")
        if value.get("may_continue") is False:
            outcome["may_continue"] = False
            outcome.setdefault("reason", "Structured may_continue=false")
    return outcome


def _result_payload(result: Any) -> dict[str, Any]:
    payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    # 一些 FastMCP 工具把结构化返回值包装在 TextContent 中。
    for content in payload.get("content", []):
        if content.get("type") == "text":
            try:
                content["parsed_json"] = json.loads(content["text"])
            except (ValueError, TypeError, KeyError):
                pass
    return payload


def _error_message(error: BaseException) -> str:
    children = getattr(error, "exceptions", None)
    if children:
        return "; ".join(_error_message(child) for child in children)
    message = f"{type(error).__name__}: {str(error)[:2000]}"
    staged = getattr(error, "atomic_json_temporary", None)
    if staged:
        message += f"; complete JSON retained at {staged}"
    return message


async def _execute_requests(
    requests: list[dict[str, Any]], output: Path, timeout_seconds: float
) -> int:
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "request_count": len(requests),
        "results": [],
    }
    # 排他创建保证默认绝不覆盖已有结果，包括与输入路径相同的情况。
    with output.open("x", encoding="utf-8"):
        pass
    _atomic_write(output, report)
    try:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_PATH)],
            cwd=str(ROOT),
            env=os.environ.copy(),
        )
        # MCP SDK 在 Windows 正常启动路径使用 CREATE_NO_WINDOW。
        with anyio.fail_after(timeout_seconds):
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    names: set[str] = set()
                    cursor = None
                    seen_cursors: set[str] = set()
                    while True:
                        listed = await session.list_tools(cursor=cursor)
                        names.update(tool.name for tool in listed.tools)
                        cursor = listed.nextCursor
                        if not cursor:
                            break
                        if cursor in seen_cursors:
                            raise ValueError("MCP tools/list repeated a pagination cursor")
                        seen_cursors.add(cursor)
                    unknown = sorted({request["name"] for request in requests} - names)
                    if unknown:
                        raise ValueError("Unknown MCP tools: " + ", ".join(unknown))
                    for index, request in enumerate(requests):
                        report["current_request"] = {"index": index, "name": request["name"]}
                        _atomic_write(output, report)
                        result = await session.call_tool(
                            request["name"], arguments=request.get("arguments", {})
                        )
                        payload = _result_payload(result)
                        outcome = _classify_result(payload)
                        report["results"].append({
                            "index": index,
                            "name": request["name"],
                            "result": _small_payload(payload),
                            "outcome": outcome,
                        })
                        report.pop("current_request", None)
                        if outcome["status"] == "error":
                            report["status"] = "error"
                            report["error"] = f"{request['name']}: {outcome['reason']}"
                        elif not outcome["may_continue"]:
                            remaining = len(requests) - index - 1
                            report.update(status=outcome["status"], may_continue=False,
                                          remaining_request_count=remaining, stop_reason=outcome.get("reason"))
                            if remaining and report["status"] == "success":
                                report["status"] = "stopped"
                        _atomic_write(output, report)
                        if outcome["status"] == "error":
                            return 1
                        if not outcome["may_continue"]:
                            return 0 if report["status"] == "success" else 2
        report["status"] = "success"
    except TimeoutError:
        report["status"] = "timeout"
        report["error"] = f"MCP request batch exceeded {timeout_seconds:g} seconds"
    except Exception as error:
        report["status"] = "error"
        report["error"] = _error_message(error)
    _atomic_write(output, report)
    return 0 if report["status"] == "success" else 1


def main(argv: list[str] | None = None) -> int:
    """解析命令行并执行请求；参数为命令行列表，返回进程退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120.0,
                        help="整个批次的超时秒数，包括初始化和工具枚举（默认 120）")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
            raise ValueError("--timeout-seconds must be finite and greater than zero")
        requests = _load_requests(args.request)
        if not SERVER_PATH.is_file():
            raise FileNotFoundError(f"MCP server not found: {SERVER_PATH}")
        code = asyncio.run(_execute_requests(requests, args.output, args.timeout_seconds))
    except Exception as error:
        print(f"MCP request failed: {_error_message(error)}", file=sys.stderr)
        return 1
    label = "completed" if code == 0 else "stopped for review or partial result" if code == 2 else "failed"
    print(f"MCP request {label}; results: {args.output}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
