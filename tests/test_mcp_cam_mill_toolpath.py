"""MILL single-feature GOP schema and routing; all CAD operations mocked."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context, CLSID, server

@pytest.fixture
def core(context, monkeypatch):
    value = Mock(return_value={"status": "review_required", "may_continue": False})
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_mill_toolpath",
                        SimpleNamespace(qualify_mill_operation_toolpath=value))
    return value

def params(context, action="inspect", **changes):
    data = dict(addin_clsid=CLSID, process_id=731, expected_document_path=context.document,
        expected_source_sha256="b"*64, expected_feature_native_id=111, expected_operation_native_id=114, expected_mill_operation_type=0, action=action,
        qualification_only=True, acknowledge_disposable_copy=True, message_policy="vendor_default")
    if action == "apply":
        data.update(expected_state_sha256="a"*64, receipt_path=str(context.dll.parent/"gop.json"))
    return server.SolidWorksCamMillOperationToolpathInput(**(data|changes))

@pytest.mark.parametrize("action", ["inspect", "prepare", "apply"])
def test_exact_registered_target_route(context, core, action):
    p=params(context, action)
    assert json.loads(server.solidworks_cam_qualify_mill_operation_toolpath(p)) == core.return_value
    core.assert_called_once_with(context.sw, CLSID, typelib_path=str(context.dll.parent/"camworks.tlb"),
        **p.model_dump(exclude={"addin_clsid", "expected_document_title", "response_format"}))
    assert context.runners == [{"format":server.ResponseFormat.JSON,"automation":True}]

@pytest.mark.parametrize("field", ["process_id", "expected_feature_native_id", "expected_operation_native_id"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, 0, -1, 4294967296])
def test_strict_identity_fields(context, core, field, value):
    with pytest.raises(ValueError): params(context, **{field:value})
    core.assert_not_called(); context.connect.assert_not_called()

@pytest.mark.parametrize("field,value", [
    ("qualification_only",False), ("qualification_only",1), ("qualification_only","true"),
    ("acknowledge_disposable_copy",False), ("acknowledge_disposable_copy",1),
    ("expected_source_sha256","bad"), ("expected_source_sha256","A"*64),
    ("expected_source_sha256",None), ("expected_source_sha256",True),
    ("expected_document_path","relative.SLDPRT"), ("expected_document_path","C:/wrong.txt"),
    ("expected_document_title","unsaved"), ("message_policy","accept"),
    ("action","regenerate"), ("save",True), ("generate_toolpath",True),
    ("gop_preference",2), ("typelib_path","external.tlb")])
def test_closed_scope_rejects_unsupported_inputs(context, core, field, value):
    with pytest.raises(ValueError): params(context, **{field:value})
    core.assert_not_called(); context.connect.assert_not_called()

@pytest.mark.parametrize("action",["inspect","prepare"])
@pytest.mark.parametrize("field,value",[("expected_state_sha256","a"*64),("receipt_path","C:/new.json")])
def test_read_only_rejects_mutation_inputs(context,core,action,field,value):
    with pytest.raises(ValueError): params(context,action,**{field:value})
    core.assert_not_called()

@pytest.mark.parametrize("field,value",[("expected_state_sha256",None),("expected_state_sha256","bad"),
    ("receipt_path",None),("receipt_path","relative.json"),("receipt_path","C:/new.txt")])
def test_apply_requires_new_receipt_and_prepared_state(context,core,field,value):
    with pytest.raises(ValueError): params(context,"apply",**{field:value})
    core.assert_not_called()

def test_existing_receipt_not_reused(context,core):
    path=context.dll.parent/"prior.json";path.write_text("unchanged")
    with pytest.raises(ValueError): params(context,"apply",receipt_path=str(path))
    assert path.read_text()=="unchanged";core.assert_not_called()

@pytest.mark.parametrize("failure",["unbound","wrong_pid","wrong_document","wrong_version","unknown_registration"])
def test_target_mismatch_stops_before_core(context,core,monkeypatch,failure):
    changes={}
    if failure=="unbound": monkeypatch.setattr(server,"_selected_process_id",None)
    elif failure=="wrong_pid": changes["process_id"]=732
    elif failure=="wrong_document": context.model.GetPathName=str(context.dll.parent/"foreign.sldprt")
    elif failure=="wrong_version": context.sw.RevisionNumber="33.1.0"
    else: changes["addin_clsid"]="{00000000-0000-0000-0000-000000000002}"
    result=json.loads(server.solidworks_cam_qualify_mill_operation_toolpath(params(context,**changes)))
    assert result["status"]=="error";core.assert_not_called()
    if failure in ("unbound","wrong_pid"): context.connect.assert_not_called()

@pytest.mark.parametrize("value",[True,False,1.0,"1",None,-1,2147483648])
def test_operation_type_is_strict_bounded(context,core,value):
    with pytest.raises(ValueError):params(context,expected_mill_operation_type=value)
    core.assert_not_called();context.connect.assert_not_called()
