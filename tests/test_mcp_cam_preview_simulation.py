"""原生仿真预览 MCP 的动作选择、输入与目标门禁；不连接 CAD。"""
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
from scripts import sw_cam_installation  # noqa: E402

CLSID = "{00000000-0000-0000-0000-000000000001}"
TOOL = "solidworks_cam_preview_simulation"


@pytest.fixture
def context(tmp_path, monkeypatch):
    """保留真实 _cam_target，替换注册表、连接和仿真核心。"""
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
    run = Mock(return_value={"status": "review_required", "reason": "SIMULATION_OUTPUTS_REQUIRE_REVIEW",
                            "export_files_verified": True, "may_continue": False})
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_simulation", SimpleNamespace(preview_simulation=run))
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
    return SimpleNamespace(dll=dll, document=document, model=model, sw=sw, inventory=inventory,
                           run=run, discovery=discovery, connect=connect, runners=runners,
                           output_dir=str(tmp_path / "new-simulation"))


def inputs(context, **changes):
    """明确同意整份试件仿真并传入已观察到的数量。"""
    values = {"action": "launch_play", "addin_clsid": CLSID, "expected_document_path": context.document,
              "expected_feature_count": 3, "expected_operation_count": 5,
              "expected_operation_setup_count": 1, "expected_generated_operation_count": 2,
              "output_dir": context.output_dir, "qualification_only": True,
              "acknowledge_document_wide_simulation": True, "message_policy": "vendor_default"}
    values.update(changes)
    return server.SolidWorksCamPreviewSimulationInput(**values)


def test_schema_inherits_all_simulation_guards_and_requires_explicit_action():
    assert issubclass(server.SolidWorksCamPreviewSimulationInput, server.SolidWorksCamSimulationInput)
    schema = server.SolidWorksCamPreviewSimulationInput.model_json_schema()
    base = server.SolidWorksCamSimulationInput.model_json_schema()
    assert set(schema["required"]) == set(base["required"]) | {"action"}
    assert schema["properties"]["action"]["enum"] == ["launch_play", "export_state"]
    assert "default" not in schema["properties"]["action"]
    assert schema["properties"]["response_format"]["default"] == "json"
    tool = server.mcp._tool_manager._tools[TOOL]
    assert "Document-Wide" in tool.title
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False


@pytest.mark.parametrize("action", ["launch_play", "export_state"])
def test_routes_exact_action_registered_typelib_and_all_guard_parameters(context, action):
    result = json.loads(server.solidworks_cam_preview_simulation(inputs(context, action=action)))
    assert result == context.run.return_value
    assert result["may_continue"] is False
    context.run.assert_called_once_with(
        context.sw, CLSID, str(context.dll.parent / "camworks.tlb"), action=action,
        expected_document_path=context.document, expected_feature_count=3,
        expected_operation_count=5, expected_operation_setup_count=1,
        expected_generated_operation_count=2, output_dir=context.output_dir,
        qualification_only=True, acknowledge_document_wide_simulation=True,
        message_policy="vendor_default",
    )
    context.connect.assert_called_once_with(wait_seconds=1)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    assert not Path(context.output_dir).exists()


@pytest.mark.parametrize("action", [None, "", "launch", "play", "close", "silent", "all", True, 1])
def test_action_is_not_coerced_or_extended_to_other_native_calls(context, action):
    with pytest.raises(ValueError):
        inputs(context, action=action)
    context.run.assert_not_called()
    assert context.runners == []


def test_omitted_action_is_rejected(context):
    values = inputs(context).model_dump()
    del values["action"]
    with pytest.raises(ValueError):
        server.SolidWorksCamPreviewSimulationInput(**values)
    context.run.assert_not_called()


@pytest.mark.parametrize("field", ["qualification_only", "acknowledge_document_wide_simulation"])
@pytest.mark.parametrize("value", [False, 1, 0, "true", 1.0, None])
def test_inherited_acknowledgements_are_strict_true(context, field, value):
    with pytest.raises(ValueError):
        inputs(context, **{field: value})
    context.run.assert_not_called()


@pytest.mark.parametrize("field,maximum", [("expected_feature_count", 262144),
    ("expected_operation_count", 512), ("expected_operation_setup_count", 512),
    ("expected_generated_operation_count", 512)])
def test_inherited_counts_keep_strict_type_and_bounds(context, field, maximum):
    assert getattr(inputs(context, **{field: maximum}), field) == maximum
    for value in (True, "1", 1.0, 0, -1, maximum + 1):
        with pytest.raises(ValueError):
            inputs(context, **{field: value})
    context.run.assert_not_called()


@pytest.mark.parametrize("field", ["expected_document_path", "qualification_only",
    "acknowledge_document_wide_simulation", "message_policy", "output_dir"])
def test_inherited_required_guards_cannot_be_omitted(context, field):
    values = inputs(context).model_dump()
    del values[field]
    with pytest.raises(ValueError):
        server.SolidWorksCamPreviewSimulationInput(**values)


@pytest.mark.parametrize("case", ["relative", "exists", "missing_parent"])
def test_each_action_requires_new_absolute_output_directory(context, case):
    path = Path(context.output_dir)
    if case == "relative":
        value = "relative-output"
    elif case == "exists":
        path.mkdir()
        value = str(path)
    else:
        value = str(path / "missing" / "output")
    for action in ("launch_play", "export_state"):
        with pytest.raises(ValueError):
            inputs(context, action=action, output_dir=value)
    context.run.assert_not_called()


@pytest.mark.parametrize("action", ["launch_play", "export_state"])
@pytest.mark.parametrize("failure", ["unbound", "unknown_registration", "discovery_error", "wrong_document", "wrong_version"])
def test_target_guards_block_both_actions_before_core(context, monkeypatch, action, failure):
    changes = {"action": action}
    if failure == "unbound":
        monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "unknown_registration":
        changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "discovery_error":
        context.inventory["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document":
        context.model.GetPathName = str(Path(context.document).with_name("foreign.sldprt"))
    else:
        context.sw.RevisionNumber = "33.1.0"
    result = json.loads(server.solidworks_cam_preview_simulation(inputs(context, **changes)))
    assert result["status"] == "error"
    context.run.assert_not_called()
    if failure not in {"wrong_document", "wrong_version"}:
        context.connect.assert_not_called()


def test_invalid_message_policy_stops_before_core(context):
    with pytest.raises(ValueError):
        inputs(context, message_policy="auto_yes")
    context.run.assert_not_called()


def test_core_error_is_structured_and_response_format_is_preserved(context):
    context.run.side_effect = RuntimeError("preview preflight rejected document")
    result = server.solidworks_cam_preview_simulation(inputs(context, response_format="markdown"))
    assert result.startswith("# error")
    assert "preview preflight rejected document" in result
    assert context.runners == [{"format": server.ResponseFormat.MARKDOWN, "automation": True}]


def test_extra_options_cannot_request_save_close_or_generation(context):
    for field in ("save_model", "close_simulation", "generate_toolpaths", "operation_index"):
        with pytest.raises(ValueError):
            inputs(context, **{field: True})
    context.run.assert_not_called()
