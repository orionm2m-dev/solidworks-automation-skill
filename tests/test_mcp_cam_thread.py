"""THREAD 单操作资格 MCP schema/路由/目标门禁；不连接 CAD。"""
import json
from unittest.mock import Mock

import pytest

from test_mcp_cam_operation_diagnostics import context, CLSID, server
from scripts import sw_cam_thread as thread

TOOL = "solidworks_cam_qualify_thread_operation"


@pytest.fixture
def core(context, monkeypatch):
    native = Mock(return_value={"status": "review_required", "may_continue": False})
    monkeypatch.setattr(thread, "qualify_thread_operation", native)
    return native


def params(context, action="prepare", **changes):
    values = dict(addin_clsid=CLSID, expected_document_path=context.document, setup_index=0,
                  operation_index=7, expected_operation_type=2, linked_feature_index=0,
                  action=action, qualification_only=True, message_policy="vendor_default")
    if action == "apply":
        values.update(expected_state_sha256="b" * 64, default_name="Observed Default",
                      expected_default_id=28, receipt_path=str(context.dll.parent / "new-thread.json"))
    return server.SolidWorksCamThreadQualificationInput(**(values | changes))


@pytest.mark.parametrize("action", ["prepare", "apply"])
def test_exact_route_and_mutating_annotation(context, core, action):
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is False and tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    from scripts.validate_mcp import REQUIRED_TOOLS
    assert TOOL in REQUIRED_TOOLS
    p = params(context, action)
    result = json.loads(server.solidworks_cam_qualify_thread_operation(p))
    assert result == core.return_value
    core.assert_called_once_with(context.sw, CLSID, typelib_path=str(context.dll.parent / "camworks.tlb"),
        expected_document_path=context.document, setup_index=0, operation_index=7,
        expected_operation_type=2, linked_feature_index=0, action=action, qualification_only=True,
        message_policy="vendor_default", expected_state_sha256=p.expected_state_sha256,
        default_name=p.default_name, expected_default_id=p.expected_default_id, receipt_path=p.receipt_path)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("field", ["setup_index", "operation_index", "expected_operation_type", "linked_feature_index"])
@pytest.mark.parametrize("value", [True, False, "1", 1.0, None, -1, 512])
def test_strict_native_selectors(context, core, field, value):
    with pytest.raises(ValueError): params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("value", [False, 0, 1, "true", None])
def test_qualification_requires_literal_true(context, core, value):
    with pytest.raises(ValueError): params(context, qualification_only=value)
    core.assert_not_called()


@pytest.mark.parametrize("field", ["expected_state_sha256", "default_name", "expected_default_id", "receipt_path"])
def test_prepare_rejects_insertion_fields_and_apply_requires_all(context, core, field):
    insertion = params(context, "apply").model_dump()
    with pytest.raises(ValueError): params(context, **{field: insertion[field]})
    insertion.pop(field)
    with pytest.raises(ValueError): server.SolidWorksCamThreadQualificationInput(**insertion)
    core.assert_not_called()


@pytest.mark.parametrize("value", [True, False, 0, -1, 2147483648, 1.0, "28", None])
def test_default_id_must_be_observed_positive_long(context, core, value):
    with pytest.raises(ValueError): params(context, "apply", expected_default_id=value)
    core.assert_not_called()


@pytest.mark.parametrize("value", ["", "x" * 1001, 28, True, None])
def test_exact_bstr_name_is_required(context, core, value):
    with pytest.raises(ValueError): params(context, "apply", default_name=value)
    core.assert_not_called()


@pytest.mark.parametrize("value", ["", "A" * 64, "x" * 64, "b" * 63, 1, None])
def test_state_sha256_strict(context, core, value):
    with pytest.raises(ValueError): params(context, "apply", expected_state_sha256=value)
    core.assert_not_called()


@pytest.mark.parametrize("action", ["prepare", "apply"])
@pytest.mark.parametrize("failure", ["unbound", "unknown_registration", "discovery_error", "wrong_document", "wrong_version"])
def test_existing_target_guard_blocks_before_core(context, core, monkeypatch, action, failure):
    changes = {}
    if failure == "unbound": monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "unknown_registration": changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "discovery_error": context.inventory["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document": context.model.GetPathName = str(context.dll.parent / "other.sldprt")
    else: context.sw.RevisionNumber = "33.1.0"
    assert json.loads(server.solidworks_cam_qualify_thread_operation(params(context, action, **changes)))["status"] == "error"
    core.assert_not_called()


@pytest.mark.parametrize("field", ["pitch", "thread_diameter", "thread_depth", "generate_toolpath", "save", "typelib_path", "operation_type"])
def test_no_parameter_setter_generation_or_raw_interface_override(context, core, field):
    with pytest.raises(ValueError): params(context, **{field: 1})
    core.assert_not_called()


def test_existing_receipt_and_wrong_extension_are_rejected(context, core):
    path = context.dll.parent / "used.json"
    path.write_text("immutable", encoding="utf-8")
    for name in (str(path), str(context.dll.parent / "other.txt"), "relative.json"):
        with pytest.raises(ValueError): params(context, "apply", receipt_path=name)
    assert path.read_text() == "immutable"
    core.assert_not_called()


def test_response_format_and_exception(context, core):
    assert server.solidworks_cam_qualify_thread_operation(
        params(context, response_format="markdown")).startswith("# review_required")
    core.side_effect = RuntimeError("native error")
    assert json.loads(server.solidworks_cam_qualify_thread_operation(params(context)))["status"] == "error"


@pytest.fixture
def inspection_core(context, monkeypatch):
    native = Mock(return_value={"status": "review_required", "may_continue": False})
    monkeypatch.setattr(thread, "inspect_thread_operation", native)
    return native


def inspection_params(context, **changes):
    values = dict(addin_clsid=CLSID, expected_document_path=context.document, setup_index=0,
                  operation_index=8, expected_operation_type=12, expected_thread_native_id=382)
    return server.SolidWorksCamThreadInspectionInput(**(values | changes))


def test_existing_thread_readonly_route(context, inspection_core):
    name = "solidworks_cam_inspect_thread_operation"
    tool = server.mcp._tool_manager._tools[name]
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False and tool.annotations.idempotentHint is True
    from scripts.validate_mcp import REQUIRED_TOOLS
    assert name in REQUIRED_TOOLS
    result = json.loads(server.solidworks_cam_inspect_thread_operation(inspection_params(context)))
    assert result == inspection_core.return_value
    inspection_core.assert_called_once_with(context.sw, CLSID,
        typelib_path=str(context.dll.parent / "camworks.tlb"), expected_document_path=context.document,
        setup_index=0, operation_index=8, expected_operation_type=12, expected_thread_native_id=382)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("field,value", [("expected_operation_type", value)
    for value in [True, False, 11, 13, 12.0, "12", None]] + [("expected_thread_native_id", value)
    for value in [True, False, 0, -1, 4294967296, 382.0, "382", None]])
def test_inspection_strict_type_and_identity(context, inspection_core, field, value):
    with pytest.raises(ValueError): inspection_params(context, **{field: value})
    inspection_core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("failure", ["unbound", "unknown_registration", "discovery_error", "wrong_document", "wrong_version"])
def test_inspection_target_guard_prevents_metadata(context, inspection_core, monkeypatch, failure):
    changes = {}
    if failure == "unbound": monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "unknown_registration": changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "discovery_error": context.inventory["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document": context.model.GetPathName = str(context.dll.parent / "other.sldprt")
    else: context.sw.RevisionNumber = "33.1.0"
    assert json.loads(server.solidworks_cam_inspect_thread_operation(inspection_params(context, **changes)))["status"] == "error"
    inspection_core.assert_not_called()


@pytest.mark.parametrize("field", ["action", "expected_state_sha256", "default_name", "receipt_path", "generate_toolpath", "save"])
def test_inspection_rejects_mutating_inputs(context, inspection_core, field):
    with pytest.raises(ValueError): inspection_params(context, **{field: "unused"})
    inspection_core.assert_not_called()


@pytest.mark.parametrize("value", ["relative.sldprt", "C:/wrong.sldasm", "", None])
def test_inspection_requires_exact_saved_part_path(context, inspection_core, value):
    with pytest.raises(ValueError): inspection_params(context, expected_document_path=value)
    inspection_core.assert_not_called()
