import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID,context,server
from scripts import sw_cam_turn_cutoff_options as cut
from scripts import sw_cam_turn_variable_allowance as base

@pytest.fixture
def core(context,monkeypatch):
    f=Mock(return_value=dict(status="ok",readback_verified=True,before={"cutoff_options_native":{"DepthClearance":.2}},after={"cutoff_options_native":{"DepthClearance":.2}}))
    monkeypatch.setattr(cut,"inspect_turn_cutoff_options",f)
    monkeypatch.setattr(server,"_runtime_identity",SimpleNamespace(assert_current=lambda:None))
    return f

def params(context,**changes):
    v=dict(process_id=731,expected_process_create_time=100.25,addin_clsid=CLSID,expected_document_path=context.document,expected_source_sha256="ab"*32,setup_index=0,operation_index=10,expected_operation_type=13,expected_operation_native_id=135,expected_linked_feature_ids=[75])
    v.update(changes);return server.SolidWorksCamTurnCutoffOptionsInput(**v)

def test_exact_readonly_public_route(context,core):
    p=params(context);r=json.loads(server.solidworks_cam_inspect_turn_cutoff_options(p))
    assert r["status"]=="ok" and r["runtime_unchanged"]
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),**p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))
    tool=server.mcp._tool_manager._tools["solidworks_cam_inspect_turn_cutoff_options"]
    assert tool.annotations.readOnlyHint and tool.annotations.idempotentHint and not tool.annotations.destructiveHint

@pytest.mark.parametrize("changes",[{"expected_operation_type":5},{"expected_operation_type":13.},{"expected_operation_type":True},{"expected_process_create_time":True},{"expected_process_create_time":float("inf")},{"expected_linked_feature_ids":[True]},{"expected_linked_feature_ids":[75,75]},{"expected_linked_feature_ids":None},{"action":"identify"},{"action":"apply"},{"include_tool_contours":True},{"include_leftover_control":True},{"receipt_path":"a.json"},{"values_native":{}},{"expected_document_path":"relative.sldprt"},{"process_id":True}])
def test_bad_schema_cannot_connect(context,core,changes):
    with pytest.raises(ValueError):params(context,**changes)
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize("pid",[None,True,732])
def test_mismatched_bound_process_stops(context,core,monkeypatch,pid):
    monkeypatch.setattr(server,"_selected_process_id",pid)
    r=json.loads(server.solidworks_cam_inspect_turn_cutoff_options(params(context)))
    assert r["status"]=="error";core.assert_not_called();context.connect.assert_not_called()

def test_post_read_runtime_drift_revokes_success_preserves_native_evidence(context,core,monkeypatch):
    guard=Mock(side_effect=[None,RuntimeError("runtime changed")])
    monkeypatch.setattr(server,"_runtime_identity",SimpleNamespace(assert_current=guard))
    r=json.loads(server.solidworks_cam_inspect_turn_cutoff_options(params(context)))
    assert r["status"]=="error" and r["readback_verified"] is False and r["runtime_unchanged"] is False
    assert r["before"]["cutoff_options_native"]["DepthClearance"]==.2
    assert r["after"]==r["before"] and core.call_count==1

def test_bore_optional_flag_forwarded_without_contours(context,monkeypatch):
    f=Mock(return_value={"status":"ok"});monkeypatch.setattr(base,"inspect_turn_bore_options",f)
    monkeypatch.setattr(server,"_runtime_identity",SimpleNamespace(assert_current=lambda:None))
    v=params(context).model_dump();v.update(expected_operation_type=5,include_leftover_control=True)
    p=server.SolidWorksCamTurnBoreOptionsInput(**v)
    server.solidworks_cam_inspect_turn_bore_options(p)
    assert f.call_args.kwargs["include_leftover_control"] is True
    assert f.call_args.kwargs["include_tool_contours"] is False

@pytest.mark.parametrize("value",[1,0.,None,"true"])
def test_bore_optional_schema_strict(context,value):
    v=params(context).model_dump();v.update(expected_operation_type=5,include_leftover_control=value)
    with pytest.raises(ValueError):server.SolidWorksCamTurnBoreOptionsInput(**v)
