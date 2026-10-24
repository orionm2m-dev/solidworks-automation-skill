"""CAM MCP 入口的协议、路由和安全门禁回归；不连接真实 CAD。"""
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
from scripts import sw_cam, sw_cam_installation  # noqa: E402

CLSID = "{00000000-0000-0000-0000-000000000001}"
OTHER_CLSID = "{00000000-0000-0000-0000-000000000002}"
TARGET_TOOLS = [
    "solidworks_cam_status", "solidworks_cam_load_addin",
    "solidworks_cam_inspect_turning", "solidworks_cam_set_turn_machine",
]
CAM_TOOLS = {"solidworks_cam_installation", *TARGET_TOOLS}
REAL_INSPECT_TURNING = sw_cam.inspect_turning
REAL_SET_TURN_MACHINE = sw_cam.set_turn_machine


@pytest.fixture
def cam_context(tmp_path, monkeypatch):
    """以模拟进程、文档和注册表执行真实工具闭包，不取得系统 COM。"""
    dll = tmp_path / "registered-cam.dll"
    dll.write_bytes(b"test fixture; never loaded")
    document = str(tmp_path / "owned-part.sldprt")
    model = SimpleNamespace(GetPathName=document, GetTitle="owned-part.sldprt", GetType=1)
    bridge = SimpleNamespace(GetCWApp=Mock())
    sw = SimpleNamespace(
        ActiveDoc=model, RevisionNumber="34.1.0", GetAddInObject=Mock(return_value=bridge),
        LoadAddIn=Mock(),
    )
    inventory = {
        "errors": [],
        "addin_registrations": [{
            "clsid": CLSID, "title": "SOLIDWORKS CAM 2026", "hive": "HKLM", "view": "64",
            "registry_key": rf"SOFTWARE\SOLIDWORKS\SOLIDWORKS 2026\AddIns\{CLSID}",
        }],
        "com_registrations": [{
            "clsid": CLSID, "hive": "HKLM", "view": "64", "progid": "Test.CAM.Addin",
            "servers": [{"kind": "inproc", "path": str(dll), "exists": True}],
        }],
    }
    discover = Mock(return_value=inventory)
    inspect = Mock(return_value={"status": "ok", "operation": "inspect"})
    load = Mock(return_value={"status": "ok", "operation": "load"})
    turning = Mock(return_value={"status": "ok", "operation": "inspect_turning"})
    machine = Mock(return_value={"status": "ok", "operation": "set_turn_machine"})
    connect = Mock(return_value=(sw, model))
    calls = []

    def locked(operation, response_format, load_automation=True, **kwargs):
        calls.append({"response_format": response_format, "load_automation": load_automation})
        try:
            return server._result(operation(), response_format)
        except Exception as error:
            return server._tool_error(error, response_format)

    def member(obj, name, *args):
        value = getattr(obj, name)
        return value(*args) if callable(value) else value

    monkeypatch.setattr(server, "_run_locked", locked)
    monkeypatch.setattr(server, "_selected_process_id", 731)
    monkeypatch.setattr(server, "connect_solidworks", connect)
    monkeypatch.setattr(server, "get_com_member", member, raising=False)
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", discover)
    monkeypatch.setattr(sw_cam, "inspect_cam", inspect)
    monkeypatch.setattr(sw_cam, "load_cam_addin", load)
    monkeypatch.setattr(sw_cam, "inspect_turning", turning)
    monkeypatch.setattr(sw_cam, "set_turn_machine", machine)
    return SimpleNamespace(
        dll=dll, document=document, model=model, sw=sw, bridge=bridge, inventory=inventory,
        discover=discover, inspect=inspect, load=load, connect=connect, calls=calls,
        turning=turning, machine=machine,
    )


def target_params(context, tool=None, **changes):
    """构造完整 CAM 目标输入，并允许各个测试替换指定字段。"""
    values = {"addin_clsid": CLSID, "expected_document_path": context.document}
    schema = server.SolidWorksCamTargetInput
    if tool == "solidworks_cam_set_turn_machine":
        schema = server.SolidWorksCamMachineInput
        values.update(machine_index=1, expected_machine_type=1, expected_catalog_count=3)
    values.update(changes)
    return schema(**values)


def assert_no_cam_access(context):
    """断言门禁拒绝后没有触及 CAM 原生入口。"""
    context.inspect.assert_not_called()
    context.load.assert_not_called()
    context.turning.assert_not_called()
    context.machine.assert_not_called()
    context.sw.GetAddInObject.assert_not_called()
    context.sw.LoadAddIn.assert_not_called()
    context.bridge.GetCWApp.assert_not_called()


def test_cam_tools_registered_with_response_format_and_target_schema():
    tools = server.mcp._tool_manager._tools
    assert CAM_TOOLS <= set(tools)
    for name in CAM_TOOLS:
        schema = json.dumps(tools[name].parameters)
        assert "response_format" in schema, name
    for name in TARGET_TOOLS:
        schema = json.dumps(tools[name].parameters)
        assert "addin_clsid" in schema
        assert "expected_document_path" in schema
        assert "expected_document_title" in schema
    assert tools["solidworks_cam_status"].annotations.readOnlyHint is True
    assert tools["solidworks_cam_load_addin"].annotations.readOnlyHint is False
    assert tools["solidworks_cam_inspect_turning"].annotations.readOnlyHint is True
    assert tools["solidworks_cam_set_turn_machine"].annotations.readOnlyHint is False
    assert tools["solidworks_cam_set_turn_machine"].annotations.idempotentHint is False
    machine_schema = json.dumps(tools["solidworks_cam_set_turn_machine"].parameters)
    for field in ("machine_index", "expected_machine_type", "expected_catalog_count"):
        assert field in machine_schema


def test_installation_default_invocation_has_response_format_and_skips_automation(cam_context):
    # 回归保护：真实 MCP 曾在进入闭包前因缺少 response_format 直接失败。
    result = json.loads(server.solidworks_cam_installation())
    assert result["status"] == "ok"
    cam_context.discover.assert_called_once_with(None)
    cam_context.connect.assert_not_called()
    assert cam_context.calls == [{"response_format": server.ResponseFormat.JSON, "load_automation": False}]
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("tool", TARGET_TOOLS)
def test_target_tools_execute_closure_and_route_registered_values(cam_context, tool):
    params = target_params(cam_context, tool=tool)
    result = json.loads(getattr(server, tool)(params))
    assert result["status"] == "ok"
    assert cam_context.calls == [{"response_format": server.ResponseFormat.JSON, "load_automation": True}]
    cam_context.connect.assert_called_once_with(wait_seconds=1)
    expected = {
        "solidworks_cam_status": (cam_context.inspect, (cam_context.sw, CLSID)),
        "solidworks_cam_load_addin": (cam_context.load, (cam_context.sw, CLSID, str(cam_context.dll))),
        "solidworks_cam_inspect_turning": (cam_context.turning, (cam_context.sw, CLSID)),
        "solidworks_cam_set_turn_machine": (cam_context.machine, (cam_context.sw, CLSID, 1, 1, 3)),
    }
    chosen, arguments = expected[tool]
    keywords = {}
    if tool in {"solidworks_cam_inspect_turning", "solidworks_cam_set_turn_machine"}:
        keywords["typelib_path"] = str(cam_context.dll.parent / "camworks.tlb")
    chosen.assert_called_once_with(*arguments, **keywords)
    for candidate in (cam_context.inspect, cam_context.load, cam_context.turning, cam_context.machine):
        if candidate is not chosen:
            candidate.assert_not_called()


@pytest.mark.parametrize("tool", sorted(CAM_TOOLS))
def test_explicit_markdown_response_format_reaches_runner(cam_context, tool):
    if tool == "solidworks_cam_installation":
        params = server.SolidWorksCamInstallationInput(response_format="markdown")
    else:
        params = target_params(cam_context, tool=tool, response_format="markdown")
    assert getattr(server, tool)(params).startswith("# ok")
    assert cam_context.calls[0]["response_format"] == server.ResponseFormat.MARKDOWN


@pytest.mark.parametrize("tool", TARGET_TOOLS)
def test_unbound_process_is_rejected_before_discovery_or_connection(cam_context, monkeypatch, tool):
    monkeypatch.setattr(server, "_selected_process_id", None)
    result = json.loads(getattr(server, tool)(target_params(cam_context, tool=tool)))
    assert result["status"] == "error"
    assert "explicit SOLIDWORKS process" in result["message"]
    cam_context.discover.assert_not_called()
    cam_context.connect.assert_not_called()
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("tool", TARGET_TOOLS)
def test_missing_document_target_is_rejected_even_without_global_strict_mode(cam_context, monkeypatch, tool):
    monkeypatch.delenv("SOLIDWORKS_MCP_REQUIRE_DOCUMENT_TARGET", raising=False)
    params = target_params(cam_context, tool=tool, expected_document_path=None)
    result = json.loads(getattr(server, tool)(params))
    assert result["status"] == "error"
    assert "explicit document target" in result["message"]
    cam_context.discover.assert_not_called()
    cam_context.connect.assert_not_called()
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("tool", TARGET_TOOLS)
def test_mismatched_solidworks_major_version_blocks_cam(cam_context, tool):
    cam_context.sw.RevisionNumber = "33.5.0"
    result = json.loads(getattr(server, tool)(target_params(cam_context, tool=tool)))
    assert result["status"] == "error"
    assert "another SOLIDWORKS major version" in result["message"]
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("tool", TARGET_TOOLS)
def test_unknown_registration_never_obtains_cam_application(cam_context, tool):
    result = json.loads(getattr(server, tool)(target_params(cam_context, tool=tool, addin_clsid=OTHER_CLSID)))
    assert result["status"] == "error"
    assert "not a discovered" in result["message"]
    cam_context.connect.assert_not_called()
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("tool", TARGET_TOOLS)
def test_incomplete_registry_discovery_blocks_connection(cam_context, tool):
    cam_context.inventory["errors"] = [{"stage": "registry", "error": "permission denied"}]
    result = json.loads(getattr(server, tool)(target_params(cam_context, tool=tool)))
    assert result["status"] == "error"
    assert "discovery has errors" in result["message"]
    cam_context.connect.assert_not_called()
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("tool", TARGET_TOOLS)
def test_wrong_active_document_blocks_cam(cam_context, tool):
    cam_context.model.GetPathName = str(Path(cam_context.document).with_name("another-part.sldprt"))
    result = json.loads(getattr(server, tool)(target_params(cam_context, tool=tool)))
    assert result["status"] == "error"
    assert result["error_code"] == "SW_DOCUMENT_MISMATCH"
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("relative_path", ["relative-cam", "../cam", "C:cam"])
def test_installation_rejects_relative_path_before_discovery(cam_context, relative_path):
    params = server.SolidWorksCamInstallationInput(install_path=relative_path)
    result = json.loads(server.solidworks_cam_installation(params))
    assert result["status"] == "error"
    assert "must be absolute" in result["message"]
    cam_context.discover.assert_not_called()
    cam_context.connect.assert_not_called()
    assert_no_cam_access(cam_context)


def test_installation_forwards_absolute_path_without_loading(cam_context):
    params = server.SolidWorksCamInstallationInput(install_path=str(cam_context.dll.parent))
    result = json.loads(server.solidworks_cam_installation(params))
    assert result["status"] == "ok"
    cam_context.discover.assert_called_once_with(str(cam_context.dll.parent))
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("clsid", ["", "CAMWorksAddin.MWAddin", "{bad-guid}"])
def test_cam_target_rejects_non_guid_identity(clsid):
    with pytest.raises(ValueError):
        server.SolidWorksCamTargetInput(addin_clsid=clsid)


@pytest.mark.parametrize("field", ["machine_index", "expected_machine_type", "expected_catalog_count"])
@pytest.mark.parametrize("value", [True, False, "1", 1.0, 1.5, None])
def test_machine_integer_inputs_reject_bool_and_coercions(cam_context, field, value):
    with pytest.raises(ValueError):
        target_params(cam_context, tool="solidworks_cam_set_turn_machine", **{field: value})
    assert cam_context.calls == []
    assert_no_cam_access(cam_context)


@pytest.mark.parametrize("field,value", [
    ("machine_index", -1), ("machine_index", 10000),
    ("expected_machine_type", -1), ("expected_machine_type", 11),
    ("expected_catalog_count", 0), ("expected_catalog_count", 10001),
])
def test_machine_integer_bounds(cam_context, field, value):
    with pytest.raises(ValueError):
        target_params(cam_context, tool="solidworks_cam_set_turn_machine", **{field: value})


@pytest.fixture
def turning_graph(cam_context, monkeypatch):
    """真实 CAM 算法通过受限模拟接口执行，明确禁止其他文档或刀路操作。"""
    context = cam_context
    context.model.GetSaveFlag = False
    empty_setups = SimpleNamespace(Count=0)
    empty_operations = SimpleNamespace(Count=0)
    current = SimpleNamespace(
        MachType=1, IGetEnumSetups=Mock(return_value=empty_setups),
        IGetEnumOpSetups=Mock(return_value=empty_operations),
    )
    chosen = object()
    candidates = SimpleNamespace(Count=3, Item=Mock(return_value=chosen))
    active = SimpleNamespace(GetDocType=1, IGetMachine=Mock(return_value=current))

    def assign(machine):
        assert machine is chosen
        current.MachType = 3
        context.model.GetSaveFlag = True

    active.SetMachine2 = Mock(side_effect=assign)
    app = SimpleNamespace(IGetActiveDoc=active, GetMachines=Mock(return_value=candidates))
    context.bridge.GetCWApp.return_value = app
    def interface(obj, name, typelib_path=None):
        assert typelib_path == str(context.dll.parent / "camworks.tlb")
        return obj

    monkeypatch.setattr(sw_cam, "_interface", interface)
    monkeypatch.setattr(sw_cam, "inspect_turning", REAL_INSPECT_TURNING)
    monkeypatch.setattr(sw_cam, "set_turn_machine", REAL_SET_TURN_MACHINE)
    return SimpleNamespace(
        context=context, active=active, current=current, candidates=candidates, app=app,
        setups=empty_setups, operations=empty_operations,
    )


def invoke_machine(graph, **changes):
    """调用真实 MCP станок 入口并返回解析后的响应。"""
    params = target_params(graph.context, tool="solidworks_cam_set_turn_machine", **changes)
    return json.loads(server.solidworks_cam_set_turn_machine(params))


def test_turning_inspection_reads_catalogue_without_assignment(turning_graph):
    graph = turning_graph
    result = json.loads(server.solidworks_cam_inspect_turning(target_params(graph.context)))
    assert result["status"] == "ok"
    assert result["current_machine_type"] == 1
    assert result["turn_machine_count"] == 3
    assert result["turning_entitlement"] == "unknown"
    assert result["active_document_unchanged"] is True
    graph.app.GetMachines.assert_called_once_with(3)
    graph.active.SetMachine2.assert_not_called()
    graph.candidates.Item.assert_not_called()


@pytest.mark.parametrize("state", ["unsaved", "assembly", "dirty"])
def test_machine_assignment_requires_saved_clean_part(turning_graph, state):
    graph = turning_graph
    changes = {}
    if state == "unsaved":
        graph.context.model.GetPathName = ""
        changes = {"expected_document_path": None, "expected_document_title": "owned-part.sldprt"}
    elif state == "assembly":
        graph.context.model.GetType = 2
    else:
        graph.context.model.GetSaveFlag = True
    result = invoke_machine(graph, **changes)
    assert result["status"] == "error"
    assert result["assignment_attempted"] is False
    graph.active.SetMachine2.assert_not_called()
    graph.candidates.Item.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"expected_machine_type": 2}, {"expected_catalog_count": 4}, {"machine_index": 3},
])
def test_machine_assignment_rechecks_observed_preconditions(turning_graph, changes):
    result = invoke_machine(turning_graph, **changes)
    assert result["status"] == "error"
    assert result["assignment_attempted"] is False
    turning_graph.active.SetMachine2.assert_not_called()
    turning_graph.candidates.Item.assert_not_called()


@pytest.mark.parametrize("collection", ["setups", "operations"])
def test_machine_assignment_refuses_any_existing_setup(turning_graph, collection):
    getattr(turning_graph, collection).Count = 1
    result = invoke_machine(turning_graph)
    assert result["status"] == "error"
    assert result["assignment_attempted"] is False
    turning_graph.active.SetMachine2.assert_not_called()
    turning_graph.candidates.Item.assert_not_called()


def test_machine_assignment_readback_does_not_claim_machining_or_save(turning_graph):
    graph = turning_graph
    result = invoke_machine(graph)
    assert result["status"] == "ok"
    assert result["machine_assignment_verified"] is True
    assert result["current_machine_type"] == 3
    assert result["model_saved"] is False
    assert result["toolpath_verified"] is False
    assert result["turning_entitlement"] == "unknown"
    assert graph.setups.Count == graph.operations.Count == 0
    graph.candidates.Item.assert_called_once_with(1)
    graph.active.SetMachine2.assert_called_once()
    graph.context.sw.LoadAddIn.assert_not_called()
    assert result["document_before"]["needs_save"] is False
    assert result["document_after"]["needs_save"] is True
