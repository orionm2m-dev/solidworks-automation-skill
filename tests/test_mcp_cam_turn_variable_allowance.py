"""变量余量只读 MCP strict schema/route 与 typed IID 门禁；不连接 CAD。"""
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID, context, server
from scripts import sw_cam_turn_variable_allowance as core_module
from scripts import sw_cam_comtypes as bridge

TOOL="solidworks_cam_inspect_turn_variable_allowance"

@pytest.fixture
def core(context,monkeypatch):
    value=Mock(return_value=dict(status="ok",may_continue=False,units_verified=False))
    monkeypatch.setattr(core_module,"inspect_turn_variable_allowance",value)
    return value

def params(context,**changes):
    values=dict(process_id=731,addin_clsid=CLSID,expected_document_path=context.document,
        setup_index=0,operation_index=2,expected_operation_type=2,expected_operation_native_id=123,
        expected_linked_feature_ids=[42],expected_source_sha256="ab"*32)
    values.update(changes)
    return server.SolidWorksCamVariableAllowanceInput(**values)

@pytest.mark.parametrize("kind",[1,2])
def test_exact_read_route_pins_operation_features_and_saved_source(context,core,kind):
    request=params(context,expected_operation_type=kind)
    result=json.loads(server.solidworks_cam_inspect_turn_variable_allowance(request))
    assert result==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        **request.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))
    tool=server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint and tool.annotations.idempotentHint
    assert context.runners==[{"format":server.ResponseFormat.JSON,"automation":True}]

@pytest.mark.parametrize("field,value",[("process_id",True),("process_id",1.0),("process_id",0),
    ("setup_index",True),("operation_index",512),("expected_operation_type",True),
    ("expected_operation_type",1.0),("expected_operation_type",0),("expected_operation_type",3),
    ("expected_operation_native_id",True),("expected_operation_native_id",0),
    ("expected_source_sha256","X"*64),("expected_document_path","relative.sldprt"),
    ("message_policy","accept"),("expected_linked_feature_ids",[]),
    ("expected_linked_feature_ids",[True]),("expected_linked_feature_ids",[1.0]),
    ("expected_linked_feature_ids",[42,42]),("expected_linked_feature_ids",[0]),
    ("expected_linked_feature_ids",[2**32]),("expected_linked_feature_ids",list(range(1,66)))])
def test_strict_inputs_before_connection(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize("field",["value_native","mode","units","radial_x","axial_z","receipt_path","include_tool"])
def test_no_write_or_inference_options_exposed(context,field):
    with pytest.raises(ValueError):params(context,**{field:1})

@pytest.mark.parametrize("failure",["wrong_pid","unbound","wrong_doc","wrong_version","registration"])
def test_target_scope_guard_stops_before_core(context,core,monkeypatch,failure):
    request=params(context)
    if failure=="wrong_pid":monkeypatch.setattr(server,"_selected_process_id",732)
    elif failure=="unbound":monkeypatch.setattr(server,"_selected_process_id",None)
    elif failure=="wrong_doc":context.model.GetPathName="C:/other.sldprt"
    elif failure=="wrong_version":context.sw.RevisionNumber="33.1.0"
    else:context.inventory["errors"]=[dict(stage="registry")]
    assert json.loads(server.solidworks_cam_inspect_turn_variable_allowance(request))["status"]=="error"
    core.assert_not_called()
    if failure in {"wrong_pid","unbound"}:context.connect.assert_not_called()

@pytest.mark.parametrize("name,iid",[("ICWTurnRoughOp","{0816F895-0E94-4909-8FF9-B35087BC1B1C}"),
    ("ICWTurnFinishOp","{23663CCB-2A95-4C0C-BE15-ECAD1BFD36EC}")])
def test_exact_primary_allowance_interface_iid(name,iid,monkeypatch):
    interface=SimpleNamespace(_iid_=iid)
    loader=Mock(return_value=SimpleNamespace(**{name:interface}))
    monkeypatch.setattr(bridge,"_load_type_library",loader)
    assert bridge._INTERFACES[name]==iid
    assert bridge._interface_class(name,"fixture.tlb") is interface
    interface._iid_="{00000000-0000-0000-0000-000000000000}"
    with pytest.raises(ValueError):bridge._interface_class(name,"fixture.tlb")


@pytest.mark.parametrize('pinned_id',[None,123])
def test_identify_route_only_requires_selectors_and_source(context,core,pinned_id):
    request=params(context,action='identify',expected_operation_native_id=pinned_id,expected_linked_feature_ids=None)
    result=json.loads(server.solidworks_cam_inspect_turn_variable_allowance(request))
    assert result==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **request.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert request.action=='identify'

@pytest.mark.parametrize('field',['expected_operation_native_id','expected_linked_feature_ids'])
def test_read_still_rejects_missing_exact_ids(context,core,field):
    with pytest.raises(ValueError):params(context,**{field:None})
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize('changes',[{'action':'identify'}, {'action':'unknown'}, {'action':True},
    {'action':'identify','expected_linked_feature_ids':None,'expected_operation_native_id':True}])
def test_identify_strict_scope_rejections(context,core,changes):
    with pytest.raises(ValueError):params(context,**changes)
    core.assert_not_called();context.connect.assert_not_called()
