"""永久 TURN APT 路由的实际目标门禁；不连接 CAD。"""
import json
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID, context, server
from scripts import sw_cam_turn_apt_postprocess as cam

@pytest.fixture
def core(context,monkeypatch):
    value=Mock(return_value=dict(status="ok",apply_eligible=False))
    monkeypatch.setattr(cam,"qualify_turn_apt_postprocess",value)
    return value

def params(context):
    return server.SolidWorksCamTurnAptPostprocessInput(process_id=731,addin_clsid=CLSID,
        expected_document_path=context.document,setup_index=0,operation_index=3,
        expected_operation_native_id=130,expected_operation_type=2,expected_linked_feature_ids=[75],
        expected_controller_name="turn",expected_record_count=43,expected_source_sha256="ab"*32,
        action="inspect",qualification_only=True)

def test_actual_runtime_route(context,core):
    p=params(context)
    assert json.loads(server.solidworks_cam_qualify_turn_apt_postprocess(p))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        **p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))

@pytest.mark.parametrize("fault",["pid","unbound","doc","version","registry"])
def test_actual_target_guard_stops_before_export(context,core,monkeypatch,fault):
    p=params(context)
    if fault=="pid":monkeypatch.setattr(server,"_selected_process_id",732)
    elif fault=="unbound":monkeypatch.setattr(server,"_selected_process_id",None)
    elif fault=="doc":context.model.GetPathName="C:/other.sldprt"
    elif fault=="version":context.sw.RevisionNumber="33.1.0"
    else:context.inventory["errors"]=[dict(stage="registry")]
    assert json.loads(server.solidworks_cam_qualify_turn_apt_postprocess(p))["status"]=="error"
    core.assert_not_called()
    if fault in {"pid","unbound"}:context.connect.assert_not_called()

def test_registered_metadata(context):
    tool=server.mcp._tool_manager._tools["solidworks_cam_qualify_turn_apt_postprocess"]
    assert not tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    assert not tool.annotations.idempotentHint and not tool.annotations.openWorldHint
