"""CAM 原生生命周期 MCP schema/路由检查；不连接 CAD。"""
import json
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server


@pytest.fixture
def core(context,monkeypatch):
    from scripts import sw_cam_lifecycle as lifecycle
    native=Mock(return_value={"status":"review_required","may_continue":False})
    monkeypatch.setattr(lifecycle,"document_lifecycle",native)
    return native


def params(context,action="prepare",**changes):
    data=dict(addin_clsid=CLSID,expected_document_path=context.document,action=action,message_policy="vendor_default")
    if action!="prepare":data.update(expected_state_sha256="b"*64,receipt_path=str(context.dll.parent/"lifecycle.json"))
    return server.SolidWorksCamDocumentLifecycleInput(**(data|changes))


@pytest.mark.parametrize("action",["prepare","save","close"])
def test_exact_native_route(context,core,action):
    p=params(context,action)
    assert json.loads(server.solidworks_cam_document_lifecycle(p))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        expected_document_path=context.document,action=action,message_policy="vendor_default",
        expected_state_sha256=p.expected_state_sha256,receipt_path=p.receipt_path)
    assert context.runners==[{"format":server.ResponseFormat.JSON,"automation":True}]
    name="solidworks_cam_document_lifecycle"
    annotation=server.mcp._tool_manager._tools[name].annotations
    assert annotation.readOnlyHint is False and annotation.idempotentHint is False
    from scripts.validate_mcp import REQUIRED_TOOLS
    assert name in REQUIRED_TOOLS


@pytest.mark.parametrize("field,value",[("action",value) for value in ["save_close","dismiss",True,1,None]]+
    [("message_policy",value) for value in ["yes","no","cancel",0,1,True,None]]+
    [("expected_document_path",value) for value in ["relative.sldprt","C:/wrong.sldasm","",None]])
def test_no_implicit_response_or_document(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("action",["save","close"])
@pytest.mark.parametrize("field",["expected_state_sha256","receipt_path"])
def test_mutating_action_requires_complete_binding(context,core,action,field):
    with pytest.raises(ValueError):params(context,action,**{field:None})
    core.assert_not_called()


@pytest.mark.parametrize("field,value",[("expected_state_sha256","b"*64),("receipt_path","new.json")])
def test_prepare_is_readonly(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called()


@pytest.mark.parametrize("value",[True,"b"*63,"B"*64,"g"*64,0])
def test_sha256_is_exact(context,core,value):
    with pytest.raises(ValueError):params(context,"save",expected_state_sha256=value)
    core.assert_not_called()


@pytest.mark.parametrize("action",["save","close"])
def test_existing_receipt_remains_immutable(context,core,action):
    path=context.dll.parent/"old.json";path.write_text("original",encoding="utf-8")
    with pytest.raises(ValueError):params(context,action,receipt_path=str(path))
    assert path.read_text()=="original";core.assert_not_called()


@pytest.mark.parametrize("failure",["unbound","wrong_document","wrong_version","unknown_registration","discovery_error"])
def test_target_guard_prevents_native_calls(context,core,monkeypatch,failure):
    changes={}
    if failure=="unbound":monkeypatch.setattr(server,"_selected_process_id",None)
    elif failure=="wrong_document":context.model.GetPathName=str(context.dll.parent/"other.sldprt")
    elif failure=="wrong_version":context.sw.RevisionNumber="33.1.0"
    elif failure=="discovery_error":context.inventory["errors"]=[{"stage":"registry"}]
    else:changes["addin_clsid"]="{00000000-0000-0000-0000-000000000002}"
    assert json.loads(server.solidworks_cam_document_lifecycle(params(context,**changes)))["status"]=="error"
    core.assert_not_called()


@pytest.mark.parametrize("field",["response_code","hwnd","discard","save_changes","force","generate_toolpath"])
def test_no_raw_dialog_controls(context,core,field):
    with pytest.raises(ValueError):params(context,**{field:1})
    core.assert_not_called()
