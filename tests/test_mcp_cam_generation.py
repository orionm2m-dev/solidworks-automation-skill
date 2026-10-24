"""单步 CAM 验证 MCP 输入、目标保护和实际闭包路由；不连接真实 CAD。"""
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
TOOLS = ["solidworks_cam_inspect_machining", "solidworks_cam_run_qualification_step"]


@pytest.fixture
def context(tmp_path, monkeypatch):
    """模拟固定进程、活动文档和安装清单，但保留真实 _cam_target 门禁。"""
    dll = tmp_path / "registered.dll"
    dll.write_bytes(b"test fixture; never loaded")
    document = str(tmp_path / "calibration.sldprt")
    model = SimpleNamespace(GetPathName=document, GetTitle="calibration.sldprt", GetType=1)
    sw = SimpleNamespace(ActiveDoc=model, RevisionNumber="34.1.0")
    inventory = {
        "errors": [],
        "addin_registrations": [{"clsid": CLSID,
                                  "registry_key": rf"SOFTWARE\SOLIDWORKS\SOLIDWORKS 2026\AddIns\{CLSID}"}],
        "com_registrations": [{"clsid": CLSID, "view": "64", "progid": "Test.CAM",
                                "servers": [{"kind": "inproc", "path": str(dll), "exists": True}]}],
    }
    inspect = Mock(return_value={"status": "ok", "source": "inspect"})
    run = Mock(return_value={"status": "ok", "source": "qualification", "may_continue": True})
    discovery = Mock(return_value=inventory)
    connect = Mock(return_value=(sw, model))
    runners = []

    def locked(operation, response_format, load_automation=True, **kwargs):
        runners.append({"format": response_format, "automation": load_automation})
        try:
            return server._result(operation(), response_format)
        except Exception as error:
            return server._tool_error(error, response_format)

    monkeypatch.setattr(server, "_run_locked", locked)
    monkeypatch.setattr(server, "_selected_process_id", 731)
    monkeypatch.setattr(server, "connect_solidworks", connect)
    monkeypatch.setattr(server, "get_com_member", lambda obj, name: getattr(obj, name), raising=False)
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", discovery)
    monkeypatch.setattr(generation, "inspect_machining", inspect)
    monkeypatch.setattr(generation, "run_qualification_step", run)
    return SimpleNamespace(
        dll=dll, document=document, receipt=str(tmp_path / "new-receipt.json"),
        model=model, sw=sw, inventory=inventory, inspect=inspect, run=run,
        discovery=discovery, connect=connect, runners=runners,
    )


def inputs(context, tool="solidworks_cam_run_qualification_step", **changes):
    """构造明确同意单步试件验证的输入。"""
    values = {"addin_clsid": CLSID, "expected_document_path": context.document}
    schema = server.SolidWorksCamTargetInput
    if tool == "solidworks_cam_run_qualification_step":
        schema = server.SolidWorksCamQualificationInput
        values.update(step="subscribe", expected_feature_count=0, expected_operation_count=0,
                      receipt_path=context.receipt, qualification_only=True, message_policy="vendor_default")
    values.update(changes)
    return schema(**values)


def test_new_tools_are_registered_with_target_and_qualification_fields():
    for name in TOOLS:
        tool = server.mcp._tool_manager._tools[name]
        schema = json.dumps(tool.parameters)
        assert "expected_document_path" in schema
        assert "response_format" in schema
    tool = server.mcp._tool_manager._tools["solidworks_cam_run_qualification_step"]
    schema = json.dumps(tool.parameters)
    for field in ["step", "expected_feature_count", "expected_operation_count", "expected_operation_setup_count", "receipt_path",
                  "qualification_only", "message_policy"]:
        assert field in schema
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.idempotentHint is False
    assert server.mcp._tool_manager._tools["solidworks_cam_inspect_machining"].annotations.readOnlyHint is True


def test_inspection_routes_registered_installation_and_existing_document(context):
    params = inputs(context, TOOLS[0])
    result = json.loads(server.solidworks_cam_inspect_machining(params))
    assert result["source"] == "inspect"
    context.inspect.assert_called_once_with(context.sw, CLSID, str(context.dll.parent / "camworks.tlb"))
    context.run.assert_not_called()
    context.connect.assert_called_once_with(wait_seconds=1)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("step", ["subscribe", "extract_features", "generate_operations"])
def test_qualification_routes_every_explicit_policy_and_count(context, step):
    params = inputs(context, step=step, expected_feature_count=3, expected_operation_count=2)
    result = json.loads(server.solidworks_cam_run_qualification_step(params))
    assert result["source"] == "qualification"
    context.run.assert_called_once_with(
        context.sw, CLSID, str(context.dll.parent / "camworks.tlb"),
        step=step, expected_feature_count=3, expected_operation_count=2,
        expected_operation_setup_count=0, receipt_path=context.receipt, qualification_only=True, message_policy="vendor_default",
    )
    context.inspect.assert_not_called()
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("tool", TOOLS)
def test_explicit_response_format_is_forwarded(context, tool):
    assert getattr(server, tool)(inputs(context, tool, response_format="markdown")).startswith("# ok")
    assert context.runners[0]["format"] == server.ResponseFormat.MARKDOWN


@pytest.mark.parametrize("field", ["expected_feature_count", "expected_operation_count", "expected_operation_setup_count"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, -1])
def test_counts_are_strict_nonnegative_integers(context, field, value):
    with pytest.raises(ValueError):
        inputs(context, **{field: value})
    context.run.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("field,value", [("expected_feature_count", 262145), ("expected_operation_count", 513), ("expected_operation_setup_count", 513)])
def test_counts_are_bounded(context, field, value):
    with pytest.raises(ValueError):
        inputs(context, **{field: value})


@pytest.mark.parametrize("value", [False, 0, 1, 1.0, None, "true", "false"])
def test_qualification_requires_true(context, value):
    with pytest.raises(ValueError):
        inputs(context, qualification_only=value)
    context.run.assert_not_called()


@pytest.mark.parametrize("value", ["cancel", "auto_yes", "default", "", None])
def test_only_vendor_default_policy_is_allowed(context, value):
    with pytest.raises(ValueError):
        inputs(context, message_policy=value)
    context.run.assert_not_called()


@pytest.mark.parametrize("field", ["qualification_only", "message_policy", "expected_feature_count",
                                   "expected_operation_count", "receipt_path", "step"])
def test_qualification_policy_fields_cannot_be_omitted(context, field):
    values = inputs(context).model_dump()
    del values[field]
    with pytest.raises(ValueError):
        server.SolidWorksCamQualificationInput(**values)


@pytest.mark.parametrize("step", ["generate_toolpaths", "simulate", "postprocess", "all"])
def test_unexposed_actions_are_rejected(context, step):
    with pytest.raises(ValueError):
        inputs(context, step=step)
    context.run.assert_not_called()


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("failure", ["unbound", "missing_target", "unknown_registration", "discovery_error",
                                     "wrong_document", "wrong_version"])
def test_target_guard_blocks_core_invocation(context, monkeypatch, tool, failure):
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
        context.model.GetPathName = str(Path(context.document).with_name("foreign.sldprt"))
    else:
        context.sw.RevisionNumber = "33.1.0"
    result = json.loads(getattr(server, tool)(inputs(context, tool, **changes)))
    assert result["status"] == "error"
    context.inspect.assert_not_called()
    context.run.assert_not_called()
    if failure not in {"wrong_document", "wrong_version"}:
        context.connect.assert_not_called()



def test_explicit_empty_operation_setup_count_is_forwarded(context):
    """原生 EMF 创建的空操作设置必须由调用者明确回读并传入。"""
    assert inputs(context).expected_operation_setup_count == 0
    params = inputs(context, step="generate_operations", expected_feature_count=3,
                    expected_operation_count=0, expected_operation_setup_count=1)
    result = json.loads(server.solidworks_cam_run_qualification_step(params))
    assert result["status"] == "ok"
    context.run.assert_called_once_with(
        context.sw, CLSID, str(context.dll.parent / "camworks.tlb"),
        step="generate_operations", expected_feature_count=3, expected_operation_count=0,
        expected_operation_setup_count=1, receipt_path=context.receipt,
        qualification_only=True, message_policy="vendor_default",
    )
