"""Strict read-only TURN tool-contour schema/routing; never connects to CAD."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_mcp_cam_operation_diagnostics import CLSID, context, server
from scripts import sw_cam_turn_variable_allowance as core_module


TOOL = "solidworks_cam_inspect_turn_tool_contours"


@pytest.fixture
def core(context, monkeypatch):
    result = Mock(return_value=dict(status="ok", readback_verified=True, units_verified=False))
    monkeypatch.setattr(core_module, "inspect_turn_tool_contours", result)
    monkeypatch.setattr(server, "_runtime_identity", SimpleNamespace(assert_current=Mock()))
    return result


def params(context, **changes):
    values = dict(process_id=731, expected_process_create_time=100.25, addin_clsid=CLSID,
        expected_document_path=context.document, expected_source_sha256="ab" * 32,
        setup_index=0, operation_index=7, expected_operation_type=6,
        expected_operation_native_id=329, expected_tool_native_id=330,
        expected_linked_feature_ids=[76])
    values.update(changes)
    return server.SolidWorksCamTurnToolContoursInput(**values)


@pytest.mark.parametrize("kind", [5, 6])
def test_exact_read_route_binds_lifetime_source_operation_tool_and_features(context, core, kind):
    request = params(context, expected_operation_type=kind)
    result = json.loads(server.solidworks_cam_inspect_turn_tool_contours(request))
    assert result == core.return_value
    core.assert_called_once_with(context.sw, CLSID, typelib_path=str(context.dll.parent / "camworks.tlb"),
        **request.model_dump(exclude={"addin_clsid", "expected_document_title", "response_format"}))
    assert "include_tool_contours" not in core.call_args.kwargs
    assert core.call_args.kwargs["action"] == "read"
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    assert server._runtime_identity.assert_current.call_count == 2


def test_registered_tool_is_read_only_and_has_no_contour_toggle(context):
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
    schema = tool.parameters
    model = schema.get("$defs", {}).get("SolidWorksCamTurnToolContoursInput", schema)
    properties = model["properties"]
    assert "expected_tool_native_id" in properties
    assert "include_tool_contours" not in properties


@pytest.mark.parametrize("field,value", [
    ("process_id", True), ("process_id", 731.), ("process_id", 0),
    ("expected_process_create_time", True), ("expected_process_create_time", 0),
    ("expected_process_create_time", float("inf")),
    ("expected_operation_type", True), ("expected_operation_type", 6.),
    ("expected_operation_type", 4), ("expected_operation_type", 7),
    ("setup_index", True), ("operation_index", 512),
    ("expected_operation_native_id", None), ("expected_operation_native_id", True),
    ("expected_operation_native_id", 2**32), ("expected_tool_native_id", None),
    ("expected_tool_native_id", True), ("expected_tool_native_id", 330.),
    ("expected_tool_native_id", 0), ("expected_tool_native_id", 2**32),
    ("expected_linked_feature_ids", None), ("expected_linked_feature_ids", []),
    ("expected_linked_feature_ids", [True]), ("expected_linked_feature_ids", [76.]),
    ("expected_linked_feature_ids", [76, 76]), ("expected_linked_feature_ids", [0]),
    ("expected_linked_feature_ids", [2**32]),
    ("expected_document_path", "relative.sldprt"), ("expected_source_sha256", "a"),
    ("expected_source_sha256", "X" * 64), ("message_policy", "accept"),
    ("action", "identify"), ("action", "prepare"), ("action", "apply"),
    ("action", True), ("include_tool_contours", True), ("include_tool_contours", False),
    ("values_native", {}), ("include_tool", True), ("receipt_path", "a.json"),
    ("save", True), ("retry", True), ("generate_toolpath", True),
])
def test_bad_pins_toggles_and_mutation_options_fail_before_connection(context, core, field, value):
    with pytest.raises(ValueError):
        params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("field", ["process_id", "expected_process_create_time", "expected_source_sha256",
    "expected_operation_native_id", "expected_tool_native_id", "expected_linked_feature_ids"])
def test_required_identity_pins_cannot_be_omitted(context, core, field):
    values = params(context).model_dump()
    del values[field]
    with pytest.raises(ValueError):
        server.SolidWorksCamTurnToolContoursInput(**values)
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("pid", [None, True, 732])
def test_explicit_process_binding_rejects_mismatch_before_connection(context, core, monkeypatch, pid):
    monkeypatch.setattr(server, "_selected_process_id", pid)
    result = json.loads(server.solidworks_cam_inspect_turn_tool_contours(params(context)))
    assert result["status"] == "error"
    core.assert_not_called()
    context.connect.assert_not_called()


def test_runtime_guard_precedes_target_and_core(context, core):
    server._runtime_identity.assert_current.side_effect = ValueError("runtime changed before read")
    result = json.loads(server.solidworks_cam_inspect_turn_tool_contours(params(context)))
    assert result["status"] == "error"
    core.assert_not_called()
    context.connect.assert_not_called()
    assert server._runtime_identity.assert_current.call_count == 1


def test_runtime_guard_after_core_revokes_returned_result(context, core):
    server._runtime_identity.assert_current.side_effect = [None, ValueError("runtime changed during read")]
    result = json.loads(server.solidworks_cam_inspect_turn_tool_contours(params(context)))
    assert result["status"] == "error"
    core.assert_called_once()
    assert server._runtime_identity.assert_current.call_count == 2


@pytest.mark.parametrize("failure", ["wrong_document", "registration"])
def test_existing_target_guards_still_stop_core(context, core, failure):
    if failure == "wrong_document":
        context.model.GetPathName = "C:/other.sldprt"
    else:
        context.inventory["errors"] = [dict(stage="registry")]
    result = json.loads(server.solidworks_cam_inspect_turn_tool_contours(params(context)))
    assert result["status"] == "error"
    core.assert_not_called()


def test_old_bore_options_schema_remains_rough_only(context):
    values = params(context, expected_operation_type=5).model_dump(exclude={"expected_tool_native_id"})
    assert server.SolidWorksCamTurnBoreOptionsInput(**values).expected_operation_type == 5
    values["expected_operation_type"] = 6
    with pytest.raises(ValueError):
        server.SolidWorksCamTurnBoreOptionsInput(**values)
