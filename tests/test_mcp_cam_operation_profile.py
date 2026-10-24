"""关联轮廓 MCP schema 与真实目标门禁；不调用 CAD。"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from test_mcp_cam_operation_diagnostics import context, CLSID, server
from scripts import sw_cam_operation_profile as profile

TOOL = "solidworks_cam_inspect_operation_profile"


@pytest.fixture
def core(context, monkeypatch):
    read = Mock(return_value={"status": "ok", "may_continue": False})
    monkeypatch.setattr(profile, "inspect_operation_profile", read)
    return read


def params(context, **changes):
    values = {"addin_clsid": CLSID, "expected_document_path": context.document,
              "setup_index": 0, "operation_index": 6, "expected_operation_type": 3}
    values.update(changes)
    return server.SolidWorksCamOperationProfileInput(**values)


def test_registered_readonly_schema_and_exact_route(context, core):
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert "expected_operation_type" in json.dumps(tool.parameters)
    result = json.loads(server.solidworks_cam_inspect_operation_profile(params(context)))
    assert result == {"status": "ok", "may_continue": False}
    core.assert_called_once_with(context.sw, CLSID, str(context.dll.parent / "camworks.tlb"),
                                setup_index=0, operation_index=6, expected_operation_type=3)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("field", ["setup_index", "operation_index", "expected_operation_type"])
@pytest.mark.parametrize("value", [True, False, "1", 1.0, None, -1, 512])
def test_strict_selectors(context, core, field, value):
    with pytest.raises(ValueError):
        params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("value", [0, 17])
def test_type_bounds(context, core, value):
    with pytest.raises(ValueError):
        params(context, expected_operation_type=value)
    core.assert_not_called()


@pytest.mark.parametrize("failure", [
    "unbound", "missing_target", "unknown_registration", "discovery_error", "wrong_document", "wrong_version",
])
def test_real_target_guard_blocks_core(context, core, monkeypatch, failure):
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
        context.model.GetPathName = str(context.dll.parent / "foreign.sldprt")
    else:
        context.sw.RevisionNumber = "33.1.0"
    result = json.loads(server.solidworks_cam_inspect_operation_profile(params(context, **changes)))
    assert result["status"] == "error"
    core.assert_not_called()


@pytest.mark.parametrize("field", ["process_id", "typelib_path", "frame_offset", "units"])
def test_runtime_and_geometry_cannot_be_overridden(context, core, field):
    with pytest.raises(ValueError):
        params(context, **{field: "untrusted"})
    core.assert_not_called()


def test_markdown_and_exception_routing(context, core):
    assert server.solidworks_cam_inspect_operation_profile(
        params(context, response_format="markdown")).startswith("# ok")
    core.side_effect = RuntimeError("native failure")
    assert json.loads(server.solidworks_cam_inspect_operation_profile(params(context)))["status"] == "error"
