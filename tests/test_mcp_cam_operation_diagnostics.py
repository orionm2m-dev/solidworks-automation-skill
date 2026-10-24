"""操作诊断与停止观察 MCP 输入、路由和门禁；不连接 CAD 或控制进程。"""
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
from scripts import sw_cam_generation as generation, sw_cam_installation, sw_cam_jobs as jobs  # noqa: E402

CLSID = "{00000000-0000-0000-0000-000000000001}"
INSPECT = "solidworks_cam_inspect_operation"
STOP = "solidworks_cam_stop_observation"


@pytest.fixture
def context(tmp_path, monkeypatch):
    """保留真实目标门禁，替换注册表、连接和最终核心函数。"""
    dll = tmp_path / "registered.dll"
    dll.write_bytes(b"fixture; never loaded")
    document = str(tmp_path / "calibration.sldprt")
    model = SimpleNamespace(GetPathName=document, GetTitle="calibration.sldprt", GetType=1)
    sw = SimpleNamespace(ActiveDoc=model, RevisionNumber="34.1.0")
    inventory = {
        "errors": [],
        "addin_registrations": [{"clsid": CLSID,
            "registry_key": rf"SOFTWARE\SOLIDWORKS\SOLIDWORKS 2026\AddIns\{CLSID}"}],
        "com_registrations": [{"clsid": CLSID, "view": "64", "progid": "Fixture.CAM",
            "servers": [{"kind": "inproc", "path": str(dll), "exists": True}]}],
    }
    inspect = Mock(return_value={"status": "ok", "source": "operation_diagnostics"})
    stop = Mock(return_value={"status": "requested", "native_cancelled": False})
    discover = Mock(return_value=inventory)
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
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", discover)
    monkeypatch.setattr(generation, "inspect_operation", inspect)
    monkeypatch.setattr(jobs, "request_observation_stop", stop)
    return SimpleNamespace(dll=dll, document=document, model=model, sw=sw, inventory=inventory,
                           inspect=inspect, stop=stop, discover=discover, connect=connect,
                           runners=runners, job_directory=str(tmp_path / "existing-job"))


def operation_input(context, **changes):
    """构造已指定活动文档和索引的诊断输入。"""
    values = {"addin_clsid": CLSID, "expected_document_path": context.document,
              "setup_index": 1, "operation_index": 2}
    values.update(changes)
    return server.SolidWorksCamOperationInput(**values)


def stop_input(context, **changes):
    """明确确认停止观察不代表取消 CAM 计算。"""
    values = {"job_directory": context.job_directory, "acknowledge_native_not_cancelled": True}
    values.update(changes)
    return server.SolidWorksCamStopObservationInput(**values)


def test_tools_registered_with_correct_schemas_and_mutability():
    tools = server.mcp._tool_manager._tools
    assert tools[INSPECT].annotations.readOnlyHint is True
    assert tools[STOP].annotations.readOnlyHint is False
    assert tools[STOP].annotations.destructiveHint is False
    assert tools[STOP].annotations.idempotentHint is True
    inspection = json.dumps(tools[INSPECT].parameters)
    for field in ("addin_clsid", "expected_document_path", "setup_index", "operation_index", "response_format"):
        assert field in inspection
    stop = json.dumps(tools[STOP].parameters)
    assert "job_directory" in stop
    assert "acknowledge_native_not_cancelled" in stop
    assert "response_format" in stop


@pytest.mark.parametrize("setup,operation", [(0, 0), (1, 2), (511, 511)])
def test_inspection_routes_exact_selector_and_registered_typelib(context, setup, operation):
    result = json.loads(server.solidworks_cam_inspect_operation(operation_input(
        context, setup_index=setup, operation_index=operation)))
    assert result["source"] == "operation_diagnostics"
    context.inspect.assert_called_once_with(
        context.sw, CLSID, str(context.dll.parent / "camworks.tlb"),
        setup_index=setup, operation_index=operation,
    )
    context.connect.assert_called_once_with(wait_seconds=1)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    context.stop.assert_not_called()


@pytest.mark.parametrize("field", ["setup_index", "operation_index"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, -1, 512])
def test_indices_reject_coercion_and_out_of_bounds_before_core(context, field, value):
    with pytest.raises(ValueError):
        operation_input(context, **{field: value})
    context.inspect.assert_not_called()
    context.connect.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("field", ["process_id", "typelib_path", "job_directory"])
def test_diagnostic_input_cannot_override_server_selected_runtime(context, field):
    with pytest.raises(ValueError):
        operation_input(context, **{field: "untrusted override"})
    context.inspect.assert_not_called()


@pytest.mark.parametrize("failure", [
    "unbound", "missing_target", "unknown_registration", "discovery_error", "wrong_document", "wrong_version",
])
def test_real_target_guard_blocks_core_on_mismatch(context, monkeypatch, failure):
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
    result = json.loads(server.solidworks_cam_inspect_operation(operation_input(context, **changes)))
    assert result["status"] == "error"
    context.inspect.assert_not_called()
    context.stop.assert_not_called()
    if failure not in {"wrong_document", "wrong_version"}:
        context.connect.assert_not_called()


def test_stop_request_routes_acknowledgement_without_cad_lock_or_target(context, monkeypatch):
    monkeypatch.setattr(server, "_selected_process_id", None)
    result = json.loads(server.solidworks_cam_stop_observation(stop_input(context)))
    assert result["status"] == "requested"
    assert result["native_cancelled"] is False
    context.stop.assert_called_once_with(context.job_directory, acknowledge_native_not_cancelled=True)
    context.inspect.assert_not_called()
    context.connect.assert_not_called()
    context.discover.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("value", [False, 0, 1, 1.0, "true", "false", None])
def test_stop_acknowledgement_requires_literal_json_true(context, value):
    with pytest.raises(ValueError):
        stop_input(context, acknowledge_native_not_cancelled=value)
    context.stop.assert_not_called()
    context.connect.assert_not_called()


def test_stop_acknowledgement_cannot_be_omitted(context):
    with pytest.raises(ValueError):
        server.SolidWorksCamStopObservationInput(job_directory=context.job_directory)
    context.stop.assert_not_called()


@pytest.mark.parametrize("tool", [INSPECT, STOP])
def test_response_format_is_honoured(context, tool):
    if tool == INSPECT:
        response = server.solidworks_cam_inspect_operation(operation_input(context, response_format="markdown"))
        assert response.startswith("# ok")
        assert context.runners[0]["format"] == server.ResponseFormat.MARKDOWN
    else:
        response = server.solidworks_cam_stop_observation(stop_input(context, response_format="markdown"))
        assert response.startswith("# requested")
        assert context.runners == []


@pytest.mark.parametrize("tool", [INSPECT, STOP])
def test_core_failure_becomes_structured_error(context, tool):
    if tool == INSPECT:
        context.inspect.side_effect = RuntimeError("diagnostic read failed")
        response = server.solidworks_cam_inspect_operation(operation_input(context))
    else:
        context.stop.side_effect = ValueError("job not eligible")
        response = server.solidworks_cam_stop_observation(stop_input(context))
    assert json.loads(response)["status"] == "error"
