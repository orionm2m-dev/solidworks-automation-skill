"""真实夹持器/THREAD 目录 MCP schema 与目标门禁；不连接 CAD。"""
import json
from unittest.mock import Mock

import pytest

from test_mcp_cam_operation_diagnostics import context, CLSID, server
from scripts import sw_cam_qualification_context as qualification

TOOL = "solidworks_cam_inspect_qualification_context"


@pytest.fixture
def core(context, monkeypatch):
    native = Mock(return_value={"status": "ok", "may_continue": False})
    monkeypatch.setattr(qualification, "inspect_qualification_context", native)
    return native


def params(context, **changes):
    values = dict(addin_clsid=CLSID, expected_document_path=context.document,
                  setup_index=0, operation_index=7, expected_operation_type=2,
                  linked_feature_indices=[0], holder_profile="operation")
    return server.SolidWorksCamQualificationContextInput(**(values | changes))


@pytest.mark.parametrize("choice", ["operation", "down_left", "none"])
def test_exact_readonly_route_and_protocol_schema(context, core, choice):
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
    from scripts.validate_mcp import REQUIRED_TOOLS
    assert TOOL in REQUIRED_TOOLS
    result = json.loads(server.solidworks_cam_inspect_qualification_context(
        params(context, holder_profile=choice, linked_feature_indices=[2, 0])))
    assert result == core.return_value
    core.assert_called_once_with(context.sw, CLSID, typelib_path=str(context.dll.parent / "camworks.tlb"),
        expected_document_path=context.document, setup_index=0, operation_index=7,
        expected_operation_type=2, linked_feature_indices=[2, 0], holder_profile=choice)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("value", [[], [True], [False], ["0"], [0.0], [None], [-1], [64], [0, 0],
                                    None, "0", (0,), list(range(65))])
def test_explicit_unique_bounded_indices_required(context, core, value):
    with pytest.raises(ValueError):
        params(context, linked_feature_indices=value)
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field", ["setup_index", "operation_index", "expected_operation_type"])
@pytest.mark.parametrize("value", [True, False, "1", 1.0, None, -1, 512])
def test_strict_operation_selector(context, core, field, value):
    with pytest.raises(ValueError):
        params(context, **{field: value})
    core.assert_not_called()


@pytest.mark.parametrize("value", [None, "auto", "world", "", 0, True])
def test_holder_source_must_be_explicit_documented_choice(context, core, value):
    with pytest.raises(ValueError):
        params(context, holder_profile=value)
    core.assert_not_called()


@pytest.mark.parametrize("field", ["linked_feature_indices", "holder_profile", "expected_document_path"])
def test_critical_choices_cannot_be_omitted(context, field):
    values = params(context).model_dump()
    values.pop(field)
    with pytest.raises(ValueError):
        server.SolidWorksCamQualificationContextInput(**values)


@pytest.mark.parametrize("field", ["insert_operation", "default_id", "typelib_path", "output_dir", "holder_transform"])
def test_no_mutation_or_guessed_geometry_overrides(context, core, field):
    with pytest.raises(ValueError):
        params(context, **{field: "not allowed"})
    core.assert_not_called()


@pytest.mark.parametrize("failure", ["unbound", "unknown_registration", "discovery_error", "wrong_document", "wrong_version"])
def test_real_target_guard_blocks_core(context, core, monkeypatch, failure):
    changes = {}
    if failure == "unbound": monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "unknown_registration": changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "discovery_error": context.inventory["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document": context.model.GetPathName = str(context.dll.parent / "other.sldprt")
    else: context.sw.RevisionNumber = "33.1.0"
    result = json.loads(server.solidworks_cam_inspect_qualification_context(params(context, **changes)))
    assert result["status"] == "error"
    core.assert_not_called()


def test_response_format_and_exception(context, core):
    assert server.solidworks_cam_inspect_qualification_context(
        params(context, response_format="markdown")).startswith("# ok")
    core.side_effect = RuntimeError("native read failed")
    assert json.loads(server.solidworks_cam_inspect_qualification_context(params(context)))["status"] == "error"
