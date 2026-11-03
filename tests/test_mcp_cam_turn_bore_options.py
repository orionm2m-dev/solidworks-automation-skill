"""Strict public read-only bore option schema and routing."""
import json
from unittest.mock import Mock
from types import SimpleNamespace
import pytest
from test_mcp_cam_operation_diagnostics import CLSID,context,server
from scripts import sw_cam_turn_variable_allowance as core_module


@pytest.fixture
def core(context,monkeypatch):
    f=Mock(return_value=dict(status="ok",readback_verified=True,units_verified=False))
    monkeypatch.setattr(core_module,"inspect_turn_bore_options",f)
    monkeypatch.setattr(server,"_runtime_identity",SimpleNamespace(assert_current=lambda:None))
    return f


def params(context,**changes):
    values=dict(process_id=731,expected_process_create_time=100.25,addin_clsid=CLSID,
        expected_document_path=context.document,expected_source_sha256="ab"*32,
        setup_index=0,operation_index=6,expected_operation_type=5,expected_operation_native_id=328,
        expected_linked_feature_ids=[76])
    values.update(changes)
    return server.SolidWorksCamTurnBoreOptionsInput(**values)


def test_exact_read_route_with_lifetime_and_ids(context,core):
    p=params(context);r=json.loads(server.solidworks_cam_inspect_turn_bore_options(p))
    assert r==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        **p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))
    tool=server.mcp._tool_manager._tools["solidworks_cam_inspect_turn_bore_options"]
    assert tool.annotations.readOnlyHint and tool.annotations.idempotentHint and not tool.annotations.destructiveHint


@pytest.mark.parametrize("field,value",[("expected_process_create_time",True),("expected_process_create_time",0),
 ("expected_process_create_time",float("inf")),("expected_operation_type",True),("expected_operation_type",5.0),
 ("expected_operation_type",1),("expected_operation_type",6),("expected_operation_native_id",None),
 ("expected_linked_feature_ids",None),("expected_linked_feature_ids",[True]),("expected_linked_feature_ids",[76,76]),
 ("action","identify"),("action","apply"),("values_native",{}),("include_tool",True),("receipt_path","a.json"),
 ("process_id",True),("expected_document_path","relative.sldprt"),("expected_source_sha256","a")])
def test_reject_unknown_mutation_and_coerced_scope(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize("pid",[None,True,732])
def test_bound_process_mismatch_before_connection(context,core,monkeypatch,pid):
    monkeypatch.setattr(server,"_selected_process_id",pid)
    r=json.loads(server.solidworks_cam_inspect_turn_bore_options(params(context)))
    assert r["status"]=="error";core.assert_not_called();context.connect.assert_not_called()


def test_legacy_schema_stays_od_only(context):
    with pytest.raises(ValueError):server.SolidWorksCamVariableAllowanceInput(**params(context).model_dump(exclude={"expected_process_create_time"}))
