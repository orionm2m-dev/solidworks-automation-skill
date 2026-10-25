"""特征属性 MCP 严格输入、原生路由和目标门禁；不连接 CAD。"""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_mcp_cam_operation_diagnostics import context, CLSID, server

TOOL = "solidworks_cam_configure_turn_feature_attribute"


@pytest.fixture
def core(context, monkeypatch):
    native = Mock(return_value={"status": "review_required", "qualified": False, "may_continue": False})
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_turn_feature_attribute",
                        SimpleNamespace(configure_turn_feature_attribute=native))
    return native


def params(context, action="inspect", **changes):
    values = dict(addin_clsid=CLSID, expected_document_path=context.document,
        feature_setup_index=0, expected_feature_native_id=382, expected_turn_feature_type=1,
        action=action, qualification_only=True, message_policy="vendor_default")
    if action != "inspect":
        values["attribute_name"] = "Thread"
    if action == "apply":
        values.update(expected_state_sha256="a"*64, receipt_path=str(context.dll.parent/"attribute.json"))
    return server.SolidWorksCamTurnFeatureAttributeInput(**(values | changes))


@pytest.mark.parametrize("action", ["inspect", "prepare", "apply"])
def test_exact_action_route_and_target_lock(context, core, action):
    p = params(context, action)
    assert json.loads(server.solidworks_cam_configure_turn_feature_attribute(p)) == core.return_value
    expected = p.model_dump(exclude={"addin_clsid", "expected_document_title", "response_format"})
    core.assert_called_once_with(context.sw, CLSID,
        typelib_path=str(context.dll.parent/"camworks.tlb"), **expected)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    context.connect.assert_called_once_with(wait_seconds=1)


def test_default_inspect_and_exact_bstr_lookup(context, core):
    values = params(context).model_dump(exclude={"action"})
    p = server.SolidWorksCamTurnFeatureAttributeInput(**(values | {
        "attribute_name": "  Thread exact name  ", "read_techdb_path": True}))
    assert p.action == "inspect"
    server.solidworks_cam_configure_turn_feature_attribute(p)
    assert core.call_args.kwargs["attribute_name"] == "  Thread exact name  "
    assert core.call_args.kwargs["read_techdb_path"] is True


def test_registered_schema_and_mixed_action_annotations():
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    schema = json.dumps(tool.parameters)
    for field in ("feature_setup_index", "expected_feature_native_id", "expected_turn_feature_type",
                  "attribute_name", "read_techdb_path", "expected_state_sha256", "receipt_path"):
        assert field in schema


@pytest.mark.parametrize("field", ["feature_setup_index", "expected_feature_native_id", "expected_turn_feature_type"])
@pytest.mark.parametrize("value", [True, False, "1", 1.0, None, -1])
def test_native_references_are_strict_integers(context, core, field, value):
    with pytest.raises(ValueError):
        params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field,value", [("feature_setup_index",512), ("expected_feature_native_id",0),
    ("expected_feature_native_id",4294967296), ("expected_turn_feature_type",2147483648)])
def test_native_reference_bounds(context, core, field, value):
    with pytest.raises(ValueError):
        params(context, **{field:value})
    core.assert_not_called()


def test_native_reference_boundary_values(context, core):
    p = params(context, feature_setup_index=511, expected_feature_native_id=4294967295,
               expected_turn_feature_type=0)
    server.solidworks_cam_configure_turn_feature_attribute(p)
    assert core.call_args.kwargs["expected_feature_native_id"] == 4294967295
    assert core.call_args.kwargs["expected_turn_feature_type"] == 0


@pytest.mark.parametrize("value", [False, 0, 1, "true", None])
def test_qualification_requires_literal_true(context, core, value):
    with pytest.raises(ValueError):
        params(context, qualification_only=value)
    core.assert_not_called()


@pytest.mark.parametrize("value", [0, 1, "false", "true", None])
def test_techdb_flag_requires_json_boolean(context, core, value):
    with pytest.raises(ValueError):
        params(context, read_techdb_path=value)
    core.assert_not_called()


@pytest.mark.parametrize("action", ["prepare", "apply"])
def test_techdb_path_is_inspection_only(context, core, action):
    with pytest.raises(ValueError):
        params(context, action, read_techdb_path=True)
    core.assert_not_called()


@pytest.mark.parametrize("action", ["inspect", "prepare", "apply"])
@pytest.mark.parametrize("value", ["", "x"*1001, 1, True])
def test_attribute_name_is_bounded_exact_nonempty_bstr(context, core, action, value):
    with pytest.raises(ValueError):
        params(context, action, attribute_name=value)
    core.assert_not_called()


@pytest.mark.parametrize("action", ["prepare", "apply"])
def test_prepare_apply_require_attribute_name(context, core, action):
    with pytest.raises(ValueError):
        params(context, action, attribute_name=None)
    core.assert_not_called()


@pytest.mark.parametrize("action", ["inspect", "prepare"])
@pytest.mark.parametrize("extra", [{"expected_state_sha256":"a"*64}, {"receipt_path":"unused.json"}])
def test_read_actions_forbid_mutation_inputs(context, core, action, extra):
    with pytest.raises(ValueError):
        params(context, action, **extra)
    core.assert_not_called()


@pytest.mark.parametrize("field", ["expected_state_sha256", "receipt_path"])
def test_apply_requires_both_state_hash_and_new_receipt(context, core, field):
    with pytest.raises(ValueError):
        params(context, "apply", **{field:None})
    core.assert_not_called()


@pytest.mark.parametrize("value", ["A"*64, "a"*63, "g"*64, 123])
def test_state_hash_requires_exact_lowercase_sha256(context, core, value):
    with pytest.raises(ValueError):
        params(context, "apply", expected_state_sha256=value)
    core.assert_not_called()


@pytest.mark.parametrize("kind", ["relative", "wrong_suffix", "missing_parent", "existing"])
def test_apply_receipt_must_be_new_absolute_json(context, core, kind):
    path = context.dll.parent/"receipt.json"
    if kind == "relative": path = "relative.json"
    elif kind == "wrong_suffix": path = path.with_suffix(".txt")
    elif kind == "missing_parent": path = context.dll.parent/"missing"/"receipt.json"
    else: path.write_text("unchanged", encoding="utf-8")
    with pytest.raises(ValueError):
        params(context, "apply", receipt_path=str(path))
    if kind == "existing": assert path.read_text() == "unchanged"
    core.assert_not_called()


@pytest.mark.parametrize("path", ["relative.sldprt", "C:/parts/file.sldasm", "", None])
def test_saved_part_path_is_required(context, core, path):
    with pytest.raises(ValueError):
        params(context, expected_document_path=path)
    core.assert_not_called()


@pytest.mark.parametrize("failure", ["unbound", "wrong_document", "wrong_version", "unknown_registration", "discovery_error"])
def test_real_target_guard_blocks_core(context, core, monkeypatch, failure):
    changes = {}
    if failure == "unbound": monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "wrong_document": context.model.GetPathName = str(context.dll.parent/"other.sldprt")
    elif failure == "wrong_version": context.sw.RevisionNumber = "33.1.0"
    elif failure == "unknown_registration": changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    else: context.inventory["errors"] = [{"stage":"registry"}]
    result = server.solidworks_cam_configure_turn_feature_attribute(params(context, **changes))
    assert json.loads(result)["status"] == "error"
    core.assert_not_called()


@pytest.mark.parametrize("field", ["process_id", "typelib_path", "generate_toolpath", "save", "thread_condition_id"])
def test_cannot_override_runtime_or_add_unrelated_mutators(context, core, field):
    with pytest.raises(ValueError):
        params(context, **{field:1})
    core.assert_not_called()


def test_policy_and_action_are_closed(context, core):
    with pytest.raises(ValueError): params(context, message_policy="accept")
    with pytest.raises(ValueError): params(context, action="generate")
    core.assert_not_called()


def test_core_failure_becomes_structured_error(context, core):
    core.side_effect = RuntimeError("attribute read failed")
    result = server.solidworks_cam_configure_turn_feature_attribute(params(context))
    assert json.loads(result)["status"] == "error"


def test_response_format_is_preserved(context, core):
    result = server.solidworks_cam_configure_turn_feature_attribute(params(context, response_format="markdown"))
    assert result.startswith("# review_required")
    assert context.runners[0]["format"] == server.ResponseFormat.MARKDOWN
