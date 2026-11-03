"""Public TURN setup-context contract: strict pins, read-only routing, no CAD calls."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_mcp_cam_operation_diagnostics import CLSID, context, server
from scripts import sw_cam_turn_setup_context as core_module


TOOL = "solidworks_cam_inspect_turn_setup_context"
COUNT_BOUNDS = {
    "expected_feature_count": (1, 64),
    "expected_operation_count": (1, 512),
    "expected_feature_setup_count": (1, 64),
    "expected_operation_setup_count": (1, 64),
    "expected_generated_operation_count": (0, 512),
    "expected_toolpath_record_count": (0, 2147483647),
}
SETUP_IDS = ("expected_feature_setup_native_id", "expected_operation_setup_native_id")


@pytest.fixture
def core(context, monkeypatch):
    result = Mock(return_value={"status": "ok", "coordinate_frame_verified": False,
                               "native_transform_values_decoded": False})
    monkeypatch.setattr(core_module, "inspect_turn_setup_context", result)
    monkeypatch.setattr(server, "_runtime_identity", SimpleNamespace(assert_current=Mock()))
    return result


def params(context, **changes):
    values = dict(process_id=731, expected_process_create_time=100.25, addin_clsid=CLSID,
        expected_document_path=context.document, expected_source_sha256="ab" * 32,
        setup_index=0, operation_index=0, expected_operation_type=6,
        expected_operation_native_id=19, expected_linked_feature_ids=[23],
        expected_feature_count=3, expected_operation_count=8,
        expected_feature_setup_count=1, expected_operation_setup_count=1,
        expected_generated_operation_count=2, expected_toolpath_record_count=40)
    values.update(changes)
    return server.SolidWorksCamTurnSetupContextInput(**values)


@pytest.mark.parametrize("kind", [5, 6])
@pytest.mark.parametrize("setup_pins", [{}, dict(expected_feature_setup_native_id=43,
                                               expected_operation_setup_native_id=44)])
def test_exact_setup_read_routes_pins_counts_and_optional_discovered_ids(context, core, kind, setup_pins):
    request = params(context, expected_operation_type=kind, **setup_pins)
    result = json.loads(server.solidworks_cam_inspect_turn_setup_context(request))
    assert result == core.return_value
    core.assert_called_once_with(context.sw, CLSID, typelib_path=str(context.dll.parent / "camworks.tlb"),
        **request.model_dump(exclude={"addin_clsid", "expected_document_title", "response_format"}))
    assert core.call_args.kwargs["action"] == "read"
    assert core.call_args.kwargs["message_policy"] == "vendor_default"
    for field in SETUP_IDS:
        assert core.call_args.kwargs[field] == setup_pins.get(field)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    assert server._runtime_identity.assert_current.call_count == 2


def test_registered_schema_is_read_only_and_exposes_no_mutation_or_tool_controls(context):
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
    schema = tool.parameters
    model = schema.get("$defs", {}).get("SolidWorksCamTurnSetupContextInput", schema)
    properties = model["properties"]
    assert set(COUNT_BOUNDS) | set(SETUP_IDS) <= properties.keys()
    assert not {"expected_tool_native_id", "include_tool_contours", "include_tool", "decode_matrix",
                "transform_values", "receipt_path", "save", "generate_toolpath"} & properties.keys()


@pytest.mark.parametrize("field", list(COUNT_BOUNDS))
@pytest.mark.parametrize("value", [True, False, 1., "1", None])
def test_count_pins_reject_coercion_before_connection(context, core, field, value):
    with pytest.raises(ValueError):
        params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("field,bounds", list(COUNT_BOUNDS.items()))
def test_count_pin_inclusive_limits_and_rejected_outside_values(context, core, field, bounds):
    lower, upper = bounds
    for value in (lower, upper):
        changes = {field: value}
        if field == "expected_operation_count":
            changes["expected_generated_operation_count"] = 0
        elif field == "expected_generated_operation_count":
            changes["expected_operation_count"] = max(8, value)
        assert getattr(params(context, **changes), field) == value
    for value in (lower - 1, upper + 1):
        with pytest.raises(ValueError):
            params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field", SETUP_IDS)
@pytest.mark.parametrize("value", [True, False, 1., "1", 0, -1, 2**32])
def test_optional_setup_ids_are_strict_positive_ulong_or_none(context, core, field, value):
    with pytest.raises(ValueError):
        params(context, **{field: value})
    for valid in (None, 1, 2**32 - 1):
        assert getattr(params(context, **{field: valid}), field) == valid
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("process_id", True), ("process_id", 731.), ("process_id", 0),
    ("expected_process_create_time", True), ("expected_process_create_time", 0),
    ("expected_process_create_time", float("inf")), ("expected_process_create_time", float("nan")),
    ("setup_index", True), ("operation_index", 512),
    ("expected_operation_type", True), ("expected_operation_type", 6.),
    ("expected_operation_type", 4), ("expected_operation_type", 7),
    ("expected_operation_native_id", None), ("expected_operation_native_id", True),
    ("expected_operation_native_id", 0), ("expected_operation_native_id", 2**32),
    ("expected_linked_feature_ids", None), ("expected_linked_feature_ids", []),
    ("expected_linked_feature_ids", [True]), ("expected_linked_feature_ids", [23.]),
    ("expected_linked_feature_ids", [23, 23]), ("expected_linked_feature_ids", [0]),
    ("expected_linked_feature_ids", [2**32]),
    ("expected_document_path", "relative.sldprt"), ("expected_source_sha256", "a"),
    ("expected_source_sha256", "X" * 64), ("message_policy", "accept"),
    ("action", "identify"), ("action", "prepare"), ("action", "apply"), ("action", True),
    ("expected_tool_native_id", 21), ("include_tool_contours", True), ("include_tool_contours", False),
    ("include_tool", True), ("decode_matrix", True), ("transform_values", [1, 0, 0]),
    ("values_native", {}), ("receipt_path", "unused.json"), ("save", True),
    ("retry", True), ("generate_toolpath", True),
])
def test_invalid_pins_modes_and_controls_fail_before_core_or_connection(context, core, field, value):
    with pytest.raises(ValueError):
        params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("field", ["process_id", "expected_process_create_time", "expected_document_path",
    "expected_source_sha256", "expected_operation_native_id", "expected_linked_feature_ids", *COUNT_BOUNDS])
def test_required_pins_and_counts_cannot_be_omitted(context, core, field):
    values = params(context).model_dump()
    del values[field]
    with pytest.raises(ValueError):
        server.SolidWorksCamTurnSetupContextInput(**values)
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("pid", [None, True, 732])
def test_process_binding_mismatch_precedes_connection(context, core, monkeypatch, pid):
    monkeypatch.setattr(server, "_selected_process_id", pid)
    result = json.loads(server.solidworks_cam_inspect_turn_setup_context(params(context)))
    assert result["status"] == "error"
    core.assert_not_called()
    context.connect.assert_not_called()


def test_runtime_drift_before_read_stops_target_access(context, core):
    server._runtime_identity.assert_current.side_effect = ValueError("runtime changed before read")
    result = json.loads(server.solidworks_cam_inspect_turn_setup_context(params(context)))
    assert result["status"] == "error"
    core.assert_not_called()
    context.connect.assert_not_called()
    assert server._runtime_identity.assert_current.call_count == 1


def test_runtime_drift_after_read_revokes_success(context, core):
    server._runtime_identity.assert_current.side_effect = [None, ValueError("runtime changed during read")]
    result = json.loads(server.solidworks_cam_inspect_turn_setup_context(params(context)))
    assert result["status"] == "error"
    core.assert_called_once()
    assert server._runtime_identity.assert_current.call_count == 2


@pytest.mark.parametrize("failure", ["wrong_document", "registration"])
def test_existing_target_guard_stops_core(context, core, failure):
    if failure == "wrong_document":
        context.model.GetPathName = str(Path(context.document).with_name("other.sldprt"))
    else:
        context.inventory["errors"] = [dict(stage="registry")]
    result = json.loads(server.solidworks_cam_inspect_turn_setup_context(params(context)))
    assert result["status"] == "error"
    core.assert_not_called()


def test_generated_count_cannot_exceed_total_operations(context, core):
    with pytest.raises(ValueError):
        params(context, expected_operation_count=2, expected_generated_operation_count=3)
    core.assert_not_called()
    context.connect.assert_not_called()
