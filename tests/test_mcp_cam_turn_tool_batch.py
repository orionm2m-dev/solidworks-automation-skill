"""多字段刀片 MCP schema/路由/目标门禁；不连接 CAD。"""
from decimal import Decimal
import json
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID, context, server
from scripts import sw_cam_turn_tool_batch as batch

SELECTED=dict(setup_index=0,operation_index=6,expected_operation_type=3)
SHARED=dict(setup_index=0,operation_index=7,expected_operation_type=4)
SHA="ab"*32

@pytest.fixture
def core(context,monkeypatch):
    result=Mock(return_value=dict(status="review_required",may_continue=False))
    monkeypatch.setattr(batch,"configure_turn_tool_dimensions",result)
    return result

def raw(context,**changes):
    data=dict(process_id=731,addin_clsid=CLSID,expected_document_path=context.document,
        **SELECTED,action="prepare",values_native={"Radius1":.5,"Radius2":.5},
        qualification_only=True,message_policy="vendor_default")
    data.update(changes)
    if data["action"]=="apply":
        data.setdefault("expected_state_sha256",SHA)
        data.setdefault("allowed_affected_operations",[SELECTED,SHARED])
        data.setdefault("receipt_path",str(context.dll.parent/"batch.json"))
    return data

def model(context,**changes):return server.SolidWorksCamTurnToolDimensionsInput(**raw(context,**changes))

@pytest.mark.parametrize("action",["prepare","apply"])
def test_exact_recipe_route_under_pid_lock(context,core,action):
    params=model(context,action=action)
    result=json.loads(server.solidworks_cam_configure_turn_tool_dimensions(params))
    assert result==core.return_value
    expected=params.model_dump(exclude={"addin_clsid","expected_document_title","response_format"})
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),**expected)
    assert context.runners==[{"format":server.ResponseFormat.JSON,"automation":True}]
    tool=server.mcp._tool_manager._tools["solidworks_cam_configure_turn_tool_dimensions"]
    assert tool.annotations.destructiveHint and not tool.annotations.idempotentHint

@pytest.mark.parametrize("value",[{},[],{"HolderShape":1},{"IncludedAngle":35},{"NoseRadius":True},
    {"NoseRadius":".1"},{"Thickness":0},{"Width":-1},{"Radius1":float("inf")},
    {"Radius1":float("nan")},{"NoseRadius":Decimal(".1")}])
def test_invalid_recipe_rejected_before_connection(context,core,value):
    with pytest.raises(ValueError):model(context,values_native=value)
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize("field,value",[("process_id",True),("process_id",1.0),("process_id",0),
    ("qualification_only",1),("qualification_only",False),("setup_index",True),
    ("expected_operation_type",17),("message_policy","guess"),("expected_document_path","relative.sldprt")])
def test_strict_contract(context,core,field,value):
    with pytest.raises(ValueError):model(context,**{field:value})
    core.assert_not_called()

@pytest.mark.parametrize("field",["expected_state_sha256","allowed_affected_operations","receipt_path"])
def test_prepare_rejects_apply_fields(context,field):
    apply=raw(context,action="apply")
    with pytest.raises(ValueError):model(context,**{field:apply[field]})

@pytest.mark.parametrize("field",["expected_state_sha256","allowed_affected_operations","receipt_path"])
def test_apply_requires_guards(context,field):
    with pytest.raises(ValueError):model(context,action="apply",**{field:None})

@pytest.mark.parametrize("refs",[[SHARED],[SELECTED,SELECTED],[SELECTED,{**SELECTED,"expected_operation_type":4}]])
def test_exact_unique_shared_references(context,refs):
    with pytest.raises(ValueError):model(context,action="apply",allowed_affected_operations=refs)

def test_existing_receipt_blocks_before_connection(context,core):
    path=context.dll.parent/"batch.json";path.write_text("prior")
    with pytest.raises(ValueError):model(context,action="apply")
    assert path.read_text()=="prior";core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize("failure",["wrong_pid","unbound","wrong_doc","wrong_version","registration"])
def test_target_guard_blocks_core(context,core,monkeypatch,failure):
    params=model(context)
    if failure=="wrong_pid":monkeypatch.setattr(server,"_selected_process_id",732)
    elif failure=="unbound":monkeypatch.setattr(server,"_selected_process_id",None)
    elif failure=="wrong_doc":context.model.GetPathName="C:/foreign.sldprt"
    elif failure=="wrong_version":context.sw.RevisionNumber="33.1.0"
    else:context.inventory["errors"]=[dict(stage="registry")]
    result=json.loads(server.solidworks_cam_configure_turn_tool_dimensions(params))
    assert result["status"]=="error";core.assert_not_called()
    if failure in {"wrong_pid","unbound"}:context.connect.assert_not_called()
