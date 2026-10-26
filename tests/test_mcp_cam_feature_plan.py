"""精确单特征 GOP 的 MCP 路由、强类型和无重放契约。"""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context, CLSID, server

@pytest.fixture
def core(context,monkeypatch):
    value=Mock(return_value={"status":"review_required","may_continue":False})
    monkeypatch.setitem(sys.modules,"scripts.sw_cam_feature_plan",SimpleNamespace(qualify_feature_operation_plan=value))
    return value

def params(context,action="inspect",**changes):
    values=dict(addin_clsid=CLSID,expected_document_path=context.document,feature_setup_index=0,
        expected_feature_native_id=382,expected_turn_feature_type=1,attribute_name="Thread",
        expected_feature_count=9,expected_operation_count=15,expected_operation_setup_count=2,
        qualification_only=True,message_policy="vendor_default",action=action)
    if action=="apply":values.update(expected_state_sha256="a"*64,receipt_path=str(context.dll.parent/"gop.json"))
    return server.SolidWorksCamFeaturePlanInput(**(values|changes))

@pytest.mark.parametrize("action",["inspect","prepare","apply"])
def test_route_exact_registration_and_lock(context,core,action):
    p=params(context,action)
    assert json.loads(server.solidworks_cam_qualify_feature_operation_plan(p))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        **p.model_dump(exclude={"addin_clsid","expected_document_title","response_format","read_techdb_path"}))
    assert context.runners==[{"format":server.ResponseFormat.JSON,"automation":True}]

@pytest.mark.parametrize("field",["feature_setup_index","expected_feature_native_id","expected_turn_feature_type",
    "expected_feature_count","expected_operation_count","expected_operation_setup_count"])
@pytest.mark.parametrize("value",[True,"1",1.0,None])
def test_selectors_are_strict(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize("field,value",[("expected_feature_count",0),("expected_feature_count",65),
    ("expected_operation_count",512),("expected_operation_setup_count",0),("qualification_only",1),
    ("qualification_only",False),("read_techdb_path",True),("read_techdb_path",0),("attribute_name",None),("attribute_name","Rough-Finish"),
    ("gop_preference",2),("save",True),("generate_toolpath",True)])
def test_closed_scope_and_bounds(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called()

@pytest.mark.parametrize("action",["inspect","prepare"])
def test_readonly_cannot_accept_mutation_inputs(context,core,action):
    with pytest.raises(ValueError):params(context,action,receipt_path=str(context.dll.parent/"new.json"))
    core.assert_not_called()

@pytest.mark.parametrize("field",["expected_state_sha256","receipt_path"])
def test_apply_requires_state_and_receipt(context,core,field):
    with pytest.raises(ValueError):params(context,"apply",**{field:None})
    core.assert_not_called()

@pytest.mark.parametrize("failure",["unbound","wrong_document","wrong_version","unknown_registration"])
def test_target_failures_block_core(context,core,monkeypatch,failure):
    changes={}
    if failure=="unbound":monkeypatch.setattr(server,"_selected_process_id",None)
    elif failure=="wrong_document":context.model.GetPathName=str(context.dll.parent/"foreign.sldprt")
    elif failure=="wrong_version":context.sw.RevisionNumber="33.1.0"
    else:changes["addin_clsid"]="{00000000-0000-0000-0000-000000000002}"
    assert json.loads(server.solidworks_cam_qualify_feature_operation_plan(params(context,**changes)))["status"]=="error"
    core.assert_not_called()

def test_annotations_do_not_promise_idempotence():
    tool=server.mcp._tool_manager._tools["solidworks_cam_qualify_feature_operation_plan"]
    assert not tool.annotations.readOnlyHint and not tool.annotations.idempotentHint
    assert tool.annotations.destructiveHint
