"""独立车削毛坯 MCP 只读路由与目标门禁；不连接真实 CAD。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "mcp-server") not in sys.path:
    sys.path.insert(0, str(ROOT / "mcp-server"))

import server  # noqa: E402
from scripts import sw_cam_generation as generation, sw_cam_installation  # noqa: E402

CLSID = "{00000000-0000-0000-0000-000000000001}"
TOOL = "solidworks_cam_inspect_turn_stock"


@pytest.fixture
def context(tmp_path, monkeypatch):
    """保留真实目标门禁，替换注册表、连接和只读核心。"""
    dll = tmp_path / "registered.dll"
    dll.write_bytes(b"fixture; never loaded")
    document = str(tmp_path / "qualification.sldprt")
    model = SimpleNamespace(GetPathName=document, GetTitle="qualification.sldprt", GetType=1)
    sw = SimpleNamespace(ActiveDoc=model, RevisionNumber="34.1.0")
    inventory = {"errors": [],
        "addin_registrations": [{"clsid": CLSID,
            "registry_key": rf"SOFTWARE\SOLIDWORKS\SOLIDWORKS 2026\AddIns\{CLSID}"}],
        "com_registrations": [{"clsid": CLSID, "view": "64", "progid": "Fixture.CAM",
            "servers": [{"kind": "inproc", "path": str(dll), "exists": True}]}]}
    inspect = Mock(return_value={"status": "ok", "stock": {"type": 3},
                                 "mutation_attempted": False, "generation_attempted": False})
    connect = Mock(return_value=(sw, model))
    discovery = Mock(return_value=inventory)
    forbidden = Mock(side_effect=AssertionError("No operation generation in stock inspection"))
    runners = []

    def locked(operation, response_format, load_automation=True, **kwargs):
        runners.append({"format": response_format, "automation": load_automation})
        try:
            return server._result(operation(), response_format)
        except Exception as exc:
            return server._tool_error(exc, response_format)

    monkeypatch.setattr(server, "_run_locked", locked)
    monkeypatch.setattr(server, "_selected_process_id", 731)
    monkeypatch.setattr(server, "connect_solidworks", connect)
    monkeypatch.setattr(server, "get_com_member", lambda obj, name: getattr(obj, name), raising=False)
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", discovery)
    monkeypatch.setattr(generation, "inspect_turn_stock", inspect, raising=False)
    monkeypatch.setattr(generation, "run_qualification_step", forbidden)
    yield SimpleNamespace(dll=dll, document=document, model=model, sw=sw, inventory=inventory,
                          inspect=inspect, connect=connect, discovery=discovery, runners=runners)
    forbidden.assert_not_called()


def inputs(context, **changes):
    values = {"addin_clsid": CLSID, "expected_document_path": context.document}
    values.update(changes)
    return server.SolidWorksCamTargetInput(**values)


def test_stock_inspection_is_readonly_and_uses_existing_target_schema():
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
    schema = json.dumps(tool.parameters)
    assert "expected_document_path" in schema and "addin_clsid" in schema
    assert "response_format" in schema
    assert "operation_index" not in schema and "setup_index" not in schema
    assert "expected_generated_operation_count" not in schema
    from scripts.validate_mcp import REQUIRED_TOOLS
    assert TOOL in REQUIRED_TOOLS


def test_routes_stock_inspection_without_selected_operation_or_generated_count(context):
    result = json.loads(server.solidworks_cam_inspect_turn_stock(inputs(context)))
    assert result == context.inspect.return_value
    context.inspect.assert_called_once_with(context.sw, CLSID,
        typelib_path=str(context.dll.parent / "camworks.tlb"))
    context.connect.assert_called_once_with(wait_seconds=1)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("failure", ["unbound", "missing_target", "unknown_registration", "discovery_error",
                                     "wrong_document", "wrong_version"])
def test_target_guards_prevent_stock_core_invocation(context, monkeypatch, failure):
    changes = {}
    if failure == "unbound":
        monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "missing_target":
        changes["expected_document_path"] = None
    elif failure == "unknown_registration":
        changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "discovery_error":
        context.inventory["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document":
        context.model.GetPathName = str(Path(context.document).with_name("other.sldprt"))
    else:
        context.sw.RevisionNumber = "33.1.0"
    result = json.loads(server.solidworks_cam_inspect_turn_stock(inputs(context, **changes)))
    assert result["status"] == "error"
    context.inspect.assert_not_called()
    if failure not in {"wrong_document", "wrong_version"}:
        context.connect.assert_not_called()


def test_response_format_is_forwarded(context):
    result = server.solidworks_cam_inspect_turn_stock(inputs(context, response_format="markdown"))
    assert result.startswith("# ok")
    assert context.runners == [{"format": server.ResponseFormat.MARKDOWN, "automation": True}]


def test_core_failure_is_structured(context):
    context.inspect.side_effect = RuntimeError("stock getter unavailable")
    result = json.loads(server.solidworks_cam_inspect_turn_stock(inputs(context)))
    assert result["status"] == "error" and result["error_type"] == "RuntimeError"


@pytest.mark.parametrize("field", ["operation_index", "setup_index", "set_stock", "generate_toolpaths"])
def test_readonly_tool_has_no_operation_selection_or_mutation_fields(context, field):
    with pytest.raises(ValueError):
        inputs(context, **{field: 0})
    context.inspect.assert_not_called()
