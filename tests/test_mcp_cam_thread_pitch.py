"""THREAD Pitch MCP 的单字段范围、强类型和原生目标门禁。"""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context, CLSID, server

@pytest.fixture
def core(context,monkeypatch):
    result=Mock(return_value={"status":"review_required","may_continue":False})
    monkeypatch.setitem(sys.modules,"scripts.sw_cam_thread_parameters",SimpleNamespace(configure_thread_pitch=result))
    return result

def params(context,action="inspect",**changes):
    values=dict(addin_clsid=CLSID,expected_document_path=context.document,feature_setup_index=0,
        expected_feature_native_id=382,expected_turn_feature_type=1,attribute_name="Thread",
        expected_feature_count=9,expected_operation_count=16,expected_operation_setup_count=2,
        setup_index=0,operation_index=13,expected_operation_native_id=474,
        qualification_only=True,message_policy="vendor_default",action=action)
    if action!="inspect":values.update(expected_old_pitch=.4,new_pitch=1.5)
    if action=="apply":values.update(expected_state_sha256="a"*64,receipt_path=str(context.dll.parent/"pitch.json"))
    return server.SolidWorksCamThreadPitchInput(**(values|changes))

@pytest.mark.parametrize("action",["inspect","prepare","apply"])
def test_exact_route(context,core,action):
    p=params(context,action)
    assert json.loads(server.solidworks_cam_configure_thread_pitch(p))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        **p.model_dump(exclude={"addin_clsid","expected_document_title","response_format","read_techdb_path"}))
    assert context.runners==[{"format":server.ResponseFormat.JSON,"automation":True}]

@pytest.mark.parametrize("field",["setup_index","operation_index","expected_operation_native_id"])
@pytest.mark.parametrize("value",[True,"1",1.0,None])
def test_exact_operation_selectors(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize("field,value",[("new_pitch",None),("new_pitch",True),("new_pitch",0),("new_pitch",-1),
    ("new_pitch","1.5"),("new_pitch",float("nan")),("new_pitch",float("inf")),("new_pitch",.4),
    ("expected_old_pitch",None),("expected_old_pitch",True),("expected_old_pitch",-1),
    ("expected_operation_native_id",0),("expected_operation_count",0),("qualification_only",1),
    ("entry_angle",60),("thread_depth",.92),("right_hand",True),("save",True)])
def test_single_field_scope_and_values(context,core,field,value):
    with pytest.raises(ValueError):params(context,"prepare",**{field:value})
    core.assert_not_called()

@pytest.mark.parametrize("field",["expected_old_pitch","new_pitch","receipt_path","expected_state_sha256"])
def test_inspect_rejects_mutation_inputs(context,core,field):
    with pytest.raises(ValueError):params(context,**{field:1.5 if "pitch" in field else "x"})
    core.assert_not_called()

@pytest.mark.parametrize("failure",["unbound","wrong_document","wrong_version"])
def test_target_guard_stops_core(context,core,monkeypatch,failure):
    if failure=="unbound":monkeypatch.setattr(server,"_selected_process_id",None)
    elif failure=="wrong_document":context.model.GetPathName=str(context.dll.parent/"foreign.sldprt")
    else:context.sw.RevisionNumber="33.1.0"
    assert json.loads(server.solidworks_cam_configure_thread_pitch(params(context)))["status"]=="error"
    core.assert_not_called()


def test_tool_is_not_advertised_as_idempotent():
    tool=server.mcp._tool_manager._tools["solidworks_cam_configure_thread_pitch"]
    assert not tool.annotations.readOnlyHint and not tool.annotations.idempotentHint
