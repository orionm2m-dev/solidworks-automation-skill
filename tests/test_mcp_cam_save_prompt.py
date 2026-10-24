"""CAM 保存提示 MCP 的严格输入与 PID 门禁；不调用 UI、COM 或进程控制。"""
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


@pytest.fixture
def context(monkeypatch):
    """用隔离替身断言保存提示不依赖 COM 或操作锁。"""
    helper = Mock(return_value={"status": "inspected", "mechanism": "windows_ui_helper"})
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_save_prompt",
                        SimpleNamespace(handle_cam_save_prompt=helper))
    runtime = Mock(return_value={"status": "ready"})
    monkeypatch.setattr(server, "_runtime_identity", SimpleNamespace(assert_current=runtime))
    monkeypatch.setattr(server, "_selected_process_id", 731)
    monkeypatch.delenv("SOLIDWORKS_MCP_PROCESS_ID", raising=False)
    forbidden = {}
    for name in ("_run_locked", "_load_automation_modules", "connect_solidworks",
                 "_cam_target", "_coinitialize", "solidworks_operation_lock"):
        forbidden[name] = Mock(side_effect=AssertionError(f"Unexpected {name}"))
        monkeypatch.setattr(server, name, forbidden[name])
    yield SimpleNamespace(helper=helper, runtime=runtime, forbidden=forbidden)
    for spy in forbidden.values():
        spy.assert_not_called()


def prompt_input(**changes):
    """使用合成 PID 和文件名，不引用工作中的 CAD 文档。"""
    values = {"process_id": 731, "expected_document_basename": "qualification.sldprt"}
    values.update(changes)
    return server.SolidWorksCamSavePromptInput(**values)


def invoke(**changes):
    return json.loads(server.solidworks_cam_save_prompt(prompt_input(**changes)))


def test_registered_schema_labels_ui_and_destructive_operation():
    tool = server.mcp._tool_manager._tools["solidworks_cam_save_prompt"]
    assert "Windows UI" in tool.title
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is False
    schema = server.SolidWorksCamSavePromptInput.model_json_schema()
    assert set(schema["required"]) == {"process_id", "expected_document_basename"}
    assert schema["properties"]["action"]["default"] == "inspect"
    assert schema["properties"]["acknowledge_discard"]["default"] is False
    assert schema["properties"]["response_format"]["default"] == "json"


def test_default_inspection_routes_exact_arguments_without_com_or_lock(context):
    assert invoke() == {"status": "inspected", "mechanism": "windows_ui_helper"}
    context.helper.assert_called_once_with(731, expected_document_basename="qualification.sldprt",
                                           action="inspect", acknowledge_discard=False)
    context.runtime.assert_called_once_with()


def test_discard_routes_only_with_literal_acknowledgement(context):
    context.helper.return_value = {"status": "discarded"}
    assert invoke(action="discard", acknowledge_discard=True)["status"] == "discarded"
    context.helper.assert_called_once_with(731, expected_document_basename="qualification.sldprt",
                                           action="discard", acknowledge_discard=True)


def test_discard_without_acknowledgement_stops_before_helper(context):
    result = invoke(action="discard")
    assert result["status"] == "error"
    assert "acknowledge_discard" in result["message"]
    context.helper.assert_not_called()
    context.runtime.assert_not_called()


@pytest.mark.parametrize("value", [True, False, 0, -1, 731.0, "731", None])
def test_process_id_is_strict_positive_integer(context, value):
    with pytest.raises(ValueError):
        prompt_input(process_id=value)
    context.helper.assert_not_called()


@pytest.mark.parametrize("value", [1, 0, "true", "false", 1.0, None])
def test_acknowledgement_is_strict_boolean(context, value):
    with pytest.raises(ValueError):
        prompt_input(acknowledge_discard=value)
    context.helper.assert_not_called()


@pytest.mark.parametrize("value", ["", ".", "..", "a/b.sldprt", r"a\b.sldprt", "C:a.sldprt",
                                  " file.sldprt", "file.sldprt ", "a\nb.sldprt", "a\x00b.sldprt",
                                  "x" * 256, 123, True, None, b"part.sldprt"])
def test_basename_rejects_paths_coercion_and_ambiguous_text(context, value):
    with pytest.raises(ValueError):
        prompt_input(expected_document_basename=value)
    context.helper.assert_not_called()


@pytest.mark.parametrize("value", ["save", "cancel", "DISCARD", 1, None])
def test_action_is_limited_to_inspection_and_discard(context, value):
    with pytest.raises(ValueError):
        prompt_input(action=value)
    context.helper.assert_not_called()


def test_input_rejects_extra_fields(context):
    with pytest.raises(ValueError):
        prompt_input(force=True)


@pytest.mark.parametrize("selected,environment", [(731, None), (None, "731"), (731, "731")])
def test_accepts_exact_existing_process_binding(context, monkeypatch, selected, environment):
    monkeypatch.setattr(server, "_selected_process_id", selected)
    if environment is not None:
        monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", environment)
    assert invoke()["status"] == "inspected"
    context.helper.assert_called_once()
    assert server._selected_process_id is selected


@pytest.mark.parametrize("selected,environment", [(None, None), (732, None), (None, "732"),
                                                  (731, "732"), (732, "731"), (True, None),
                                                  (0, None), ("731", None)])
def test_missing_or_mismatched_binding_never_calls_helper(context, monkeypatch, selected, environment):
    monkeypatch.setattr(server, "_selected_process_id", selected)
    if environment is not None:
        monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", environment)
    result = invoke()
    assert result["status"] == "error"
    assert "binding" in result["message"]
    context.helper.assert_not_called()


@pytest.mark.parametrize("environment", ["", " 731", "731 ", "0731", "-731", "0", "731.0", "true", "７３１"])
def test_invalid_environment_binding_cannot_be_ignored(context, monkeypatch, environment):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", environment)
    result = invoke()
    assert result["status"] == "error"
    assert "SOLIDWORKS_MCP_PROCESS_ID" in result["message"]
    context.helper.assert_not_called()


def test_runtime_source_mismatch_stops_before_helper(context):
    details = {"status": "blocked", "error_code": "SW_RUNTIME_SOURCE_CHANGED"}
    context.runtime.side_effect = server.RuntimeIdentityError(details)
    assert invoke() == details
    context.helper.assert_not_called()


def test_helper_failure_is_structured_error(context):
    context.helper.side_effect = RuntimeError("ambiguous CAM prompts")
    result = invoke()
    assert result["status"] == "error"
    assert result["error_type"] == "RuntimeError"
    assert result["message"] == "ambiguous CAM prompts"


def test_markdown_format_applies_to_result_and_validation_error(context):
    result = server.solidworks_cam_save_prompt(prompt_input(response_format="markdown"))
    assert result.startswith("# inspected")
    error = server.solidworks_cam_save_prompt(prompt_input(action="discard", response_format="markdown"))
    assert error.startswith("# error")
    assert "acknowledge_discard" in error
    assert context.helper.call_count == 1
