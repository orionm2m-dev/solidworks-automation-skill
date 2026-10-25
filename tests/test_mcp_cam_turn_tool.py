"""单字段车削刀片 MCP 的严格输入与真实目标门禁；不连接 CAD。"""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from test_mcp_cam_operation_diagnostics import CLSID, context, server
from scripts import sw_cam_turn_tool as turn_tool

TOOL = "solidworks_cam_configure_turn_tool"
FIELDS = ("NoseRadius", "Width", "Radius1", "Radius2", "Thickness", "InscribedCircle")
SELECTED = {"setup_index": 0, "operation_index": 6, "expected_operation_type": 3}
SHARED = {"setup_index": 1, "operation_index": 2, "expected_operation_type": 4}
SHA = "ab" * 32


@pytest.fixture
def core(context, monkeypatch):
    result = Mock(return_value={"status": "review_required", "may_continue": False,
                                "mutation_attempted": False})
    monkeypatch.setattr(turn_tool, "configure_turn_tool", result)
    return result


def values(context, *, action="prepare", **changes):
    result = {"addin_clsid": CLSID, "expected_document_path": context.document,
              **SELECTED, "field": "Width", "qualification_only": True,
              "message_policy": "vendor_default", "action": action}
    if action == "apply":
        result.update(value_native=1.25, expected_state_sha256=SHA,
                      allowed_affected_operations=[dict(SELECTED), dict(SHARED)],
                      receipt_path=str(context.dll.parent / "new-tool-receipt.json"))
    result.update(changes)
    return result


def params(context, **changes):
    return server.SolidWorksCamTurnToolInput(**values(context, **changes))


def test_tool_is_registered_as_mutation_and_exposes_exact_field_enum(context):
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is False
    schema = server.SolidWorksCamTurnToolInput.model_json_schema()
    assert set(schema["properties"]["field"]["enum"]) == set(FIELDS)
    assert schema["properties"]["action"]["default"] == "prepare"
    assert schema["properties"]["response_format"]["default"] == "json"
    assert {"field", "qualification_only", "message_policy", "expected_document_path",
            "setup_index", "operation_index", "expected_operation_type"} <= set(schema["required"])
    assert TOOL in server.mcp._tool_manager._tools


@pytest.mark.parametrize("field", FIELDS)
def test_prepare_default_routes_without_mutation_inputs_or_creating_files(context, core, field):
    raw = values(context, field=field)
    del raw["action"]
    before = set(context.dll.parent.iterdir())
    model = server.SolidWorksCamTurnToolInput(**raw)
    report = json.loads(server.solidworks_cam_configure_turn_tool(model))
    assert report == core.return_value
    core.assert_called_once_with(context.sw, CLSID,
        typelib_path=str(context.dll.parent / "camworks.tlb"), expected_document_path=context.document,
        **SELECTED, action="prepare", field=field, value_native=None, expected_state_sha256=None,
        allowed_affected_operations=None, receipt_path=None, qualification_only=True,
        message_policy="vendor_default")
    assert set(context.dll.parent.iterdir()) == before
    context.connect.assert_called_once_with(wait_seconds=1)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    context.inspect.assert_not_called()
    context.stop.assert_not_called()


@pytest.mark.parametrize("field,value", [("NoseRadius", 0), ("Radius1", 0.125), ("Radius2", 0),
                                         ("Width", 1), ("Thickness", 2.5), ("InscribedCircle", 3)])
def test_apply_routes_one_raw_value_and_exact_ordered_shared_references(context, core, field, value):
    refs = [dict(SHARED), dict(SELECTED)]
    original = deepcopy(refs)
    model = params(context, action="apply", field=field, value_native=value,
                   allowed_affected_operations=refs)
    assert not Path(model.receipt_path).exists()
    report = json.loads(server.solidworks_cam_configure_turn_tool(model))
    assert report == core.return_value and refs == original
    core.assert_called_once_with(context.sw, CLSID,
        typelib_path=str(context.dll.parent / "camworks.tlb"), expected_document_path=context.document,
        **SELECTED, action="apply", field=field, value_native=value, expected_state_sha256=SHA,
        allowed_affected_operations=refs, receipt_path=model.receipt_path,
        qualification_only=True, message_policy="vendor_default")
    assert not Path(model.receipt_path).exists()
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("field", ["value_native", "expected_state_sha256", "allowed_affected_operations", "receipt_path"])
def test_prepare_rejects_each_nonnull_mutation_input_before_connection(context, core, field):
    with pytest.raises(ValueError):
        params(context, **{field: values(context, action="apply")[field]})
    core.assert_not_called()
    context.connect.assert_not_called()
    assert context.runners == []


def test_prepare_accepts_explicit_null_mutation_fields(context):
    model = params(context, value_native=None, expected_state_sha256=None,
                   allowed_affected_operations=None, receipt_path=None)
    assert model.action == "prepare"


@pytest.mark.parametrize("field", ["value_native", "expected_state_sha256", "allowed_affected_operations", "receipt_path"])
@pytest.mark.parametrize("missing", [True, False])
def test_apply_requires_all_authorization_and_receipt_inputs(context, core, field, missing):
    raw = values(context, action="apply")
    if missing: del raw[field]
    else: raw[field] = None
    with pytest.raises(ValueError): server.SolidWorksCamTurnToolInput(**raw)
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field", ["field", "qualification_only", "message_policy", "expected_document_path"])
def test_required_inputs_cannot_be_omitted(context, core, field):
    raw = values(context)
    del raw[field]
    with pytest.raises(ValueError): server.SolidWorksCamTurnToolInput(**raw)
    core.assert_not_called()


@pytest.mark.parametrize("value", [True, False, "1", Decimal("1.25"), float("nan"), float("inf"), -float("inf"), -1])
def test_apply_value_must_be_finite_nonnegative_json_number(context, core, value):
    with pytest.raises(ValueError): params(context, action="apply", value_native=value)
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field", ["Width", "Thickness", "InscribedCircle"])
def test_positive_dimensions_reject_zero(context, core, field):
    with pytest.raises(ValueError): params(context, action="apply", field=field, value_native=0)
    core.assert_not_called()


@pytest.mark.parametrize("value", [False, 0, 1, "true", None])
def test_qualification_requires_literal_true_boolean(context, core, value):
    with pytest.raises(ValueError): params(context, qualification_only=value)
    core.assert_not_called()


@pytest.mark.parametrize("field,value", [("field", "width"), ("field", "length"), ("field", "HolderShape"),
    ("field", None), ("action", "commit"), ("action", True), ("message_policy", "accept"),
    ("message_policy", True), ("message_policy", None)])
def test_enums_reject_unapproved_fields_actions_or_message_policy(context, core, field, value):
    with pytest.raises(ValueError): params(context, **{field: value})
    core.assert_not_called()


@pytest.mark.parametrize("value", ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "", True, 123])
def test_state_hash_requires_exact_lowercase_sha256(context, core, value):
    with pytest.raises(ValueError): params(context, action="apply", expected_state_sha256=value)
    core.assert_not_called()


@pytest.mark.parametrize("field", ["setup_index", "operation_index", "expected_operation_type"])
@pytest.mark.parametrize("value", [True, False, "1", 1., None, -1, 512])
def test_top_level_selectors_remain_strict(context, core, field, value):
    with pytest.raises(ValueError): params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field", ["setup_index", "operation_index", "expected_operation_type"])
@pytest.mark.parametrize("value", [True, False, "1", 1., None, -1, 512])
def test_affected_reference_selectors_are_strict(context, core, field, value):
    invalid = dict(SHARED, **{field: value})
    with pytest.raises(ValueError):
        params(context, action="apply", allowed_affected_operations=[dict(SELECTED), invalid])
    core.assert_not_called()


@pytest.mark.parametrize("value", [0, 17])
def test_operation_type_bounds_apply_to_selected_and_shared_references(context, core, value):
    with pytest.raises(ValueError): params(context, expected_operation_type=value)
    with pytest.raises(ValueError):
        params(context, action="apply", allowed_affected_operations=[dict(SELECTED), dict(SHARED, expected_operation_type=value)])
    core.assert_not_called()


@pytest.mark.parametrize("field", ["setup_index", "operation_index", "expected_operation_type"])
def test_affected_references_require_every_exact_key(context, core, field):
    invalid = dict(SHARED)
    del invalid[field]
    with pytest.raises(ValueError):
        params(context, action="apply", allowed_affected_operations=[dict(SELECTED), invalid])
    core.assert_not_called()


def test_reference_extra_fields_cannot_expand_authorization(context, core):
    invalid = dict(SHARED, allow_all=True)
    with pytest.raises(ValueError):
        params(context, action="apply", allowed_affected_operations=[dict(SELECTED), invalid])
    core.assert_not_called()


@pytest.mark.parametrize("refs", [[], True, "all", SELECTED, [None], [dict(SHARED)],
    [dict(SELECTED, expected_operation_type=4)], [dict(SELECTED), dict(SELECTED)],
    [dict(SELECTED), dict(SELECTED, expected_operation_type=4)]])
def test_affected_list_requires_selected_exact_unique_operations(context, core, refs):
    with pytest.raises(ValueError): params(context, action="apply", allowed_affected_operations=refs)
    core.assert_not_called()
    context.connect.assert_not_called()


def test_affected_reference_count_is_bounded(context, core):
    with pytest.raises(ValueError):
        params(context, action="apply", allowed_affected_operations=[dict(SELECTED)] * 513)
    core.assert_not_called()


@pytest.mark.parametrize("kind", ["relative", "suffix", "missing_parent", "existing_file", "existing_directory"])
def test_receipt_is_new_absolute_json_with_existing_parent(context, core, kind):
    base = context.dll.parent
    path = {"relative": "new.json", "suffix": str(base / "new.txt"),
            "missing_parent": str(base / "missing" / "new.json"),
            "existing_file": str(base / "old.json"), "existing_directory": str(base / "folder.json")}[kind]
    if kind == "existing_file": Path(path).write_bytes(b"keep evidence")
    if kind == "existing_directory": Path(path).mkdir()
    with pytest.raises(ValueError): params(context, action="apply", receipt_path=path)
    if kind == "existing_file": assert Path(path).read_bytes() == b"keep evidence"
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("value", [None, "relative.sldprt", "", True, 1])
def test_document_target_is_required_absolute_part(context, core, value):
    with pytest.raises(ValueError): params(context, expected_document_path=value)
    core.assert_not_called()


def test_nonpart_saved_document_is_rejected(context, core):
    with pytest.raises(ValueError): params(context, expected_document_path=str(context.dll.parent / "assembly.sldasm"))
    core.assert_not_called()


@pytest.mark.parametrize("action", ["prepare", "apply"])
@pytest.mark.parametrize("failure", ["unbound", "unknown_registration", "discovery_error", "wrong_document", "wrong_version"])
def test_real_target_guard_blocks_prepare_and_apply_core(context, core, monkeypatch, action, failure):
    changes = {}
    if failure == "unbound": monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "unknown_registration": changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "discovery_error": context.inventory["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document": context.model.GetPathName = str(context.dll.parent / "foreign.sldprt")
    else: context.sw.RevisionNumber = "33.1.0"
    report = json.loads(server.solidworks_cam_configure_turn_tool(params(context, action=action, **changes)))
    assert report["status"] == "error"
    core.assert_not_called()


@pytest.mark.parametrize("name", ["process_id", "typelib_path", "units", "save", "generate", "fields"])
def test_runtime_and_write_scope_cannot_be_overridden(context, core, name):
    with pytest.raises(ValueError): params(context, **{name: "untrusted"})
    core.assert_not_called()


def test_markdown_and_native_exception_use_standard_result_routes(context, core):
    assert server.solidworks_cam_configure_turn_tool(params(context, response_format="markdown")).startswith("# review_required")
    core.side_effect = RuntimeError("native failure")
    report = json.loads(server.solidworks_cam_configure_turn_tool(params(context)))
    assert report["status"] == "error"
