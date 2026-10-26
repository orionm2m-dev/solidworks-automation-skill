"""永久工具的 schema/route 与现有原生目标门禁回归。"""
import json
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID, context, server
from scripts import sw_cam_thread_attributes as cam

@pytest.fixture
def core(context,monkeypatch):
    core=Mock(return_value=dict(status="review_required",may_continue=False))
    monkeypatch.setattr(cam,"inspect_thread_feature_attributes",core)
    return core


def params(context,**changes):
    values=dict(process_id=731,addin_clsid=CLSID,expected_document_path=context.document,setup_index=0,
        operation_index=13,expected_operation_native_id=474,expected_feature_native_id=382,
        expected_source_sha256="ab"*32,receipt_path=str(context.dll.parent/"new-read.json"))
    return server.SolidWorksCamThreadAttributesInput(**(values|changes))


def test_exact_readonly_route_and_real_metadata(context,core):
    request=params(context)
    assert json.loads(server.solidworks_cam_inspect_thread_feature_attributes(request))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        **request.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))
    tool=server.mcp._tool_manager._tools["solidworks_cam_inspect_thread_feature_attributes"]
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint and not tool.annotations.idempotentHint


@pytest.mark.parametrize("field,value",[("process_id",True),("process_id",1.0),("process_id",0),
    ("setup_index",True),("operation_index",512),("expected_operation_native_id",False),
    ("expected_feature_native_id",0),("expected_feature_native_id",2**32),
    ("expected_source_sha256","AB"*32),("expected_document_path","relative.sldprt"),
    ("receipt_path","relative.json"),("message_policy","accept")])
def test_strict_fields_before_connection(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize("field",["value_native","depth","units","expand_dispatch","include_tool","action"])
def test_no_setter_or_unknown_payload_expansion_options(context,field):
    with pytest.raises(ValueError):params(context,**{field:1})


@pytest.mark.parametrize("fault",["pid","unbound","doc","version","registry"])
def test_target_guards_block_core(context,core,monkeypatch,fault):
    request=params(context)
    if fault=="pid":monkeypatch.setattr(server,"_selected_process_id",732)
    elif fault=="unbound":monkeypatch.setattr(server,"_selected_process_id",None)
    elif fault=="doc":context.model.GetPathName="C:/other.sldprt"
    elif fault=="version":context.sw.RevisionNumber="33.1.0"
    else:context.inventory["errors"]=[dict(stage="registry")]
    assert json.loads(server.solidworks_cam_inspect_thread_feature_attributes(request))["status"]=="error"
    core.assert_not_called()


def test_receipt_schema_refuses_existing_file(context):
    receipt=context.dll.parent/"existing.json";receipt.write_text("old")
    with pytest.raises(ValueError):params(context,receipt_path=str(receipt))
