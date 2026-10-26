"""单特征 MILL 尺寸实验的严格 schema/路由；不连接 CAD。"""
import json,sys
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server
from scripts import sw_cam_comtypes as bridge

SPEC=dict(plane_axis='Z',plane_offset_mm=2,sketch_name='UnitRect',plane_name='UnitPlane',
    profile=dict(kind='closed_polyline',points_model_mm=[[1,1,2],[4,1,2],[4,6,2],[1,6,2]]))

@pytest.fixture
def core(context,monkeypatch):
    result=Mock(return_value=dict(status='ok',may_continue=False))
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_mill_units_qualification',N(qualify_mill_feature_units=result))
    return result

def params(context,action='inspect',**changes):
    data=dict(addin_clsid=CLSID,process_id=731,expected_document_path=context.document,expected_source_sha256='a'*64,
        action=action,expected_setup_native_id=17,sketch_spec=deepcopy(SPEC),depth_native=3,
        qualification_only=True,acknowledge_disposable_copy=True)
    if action=='apply':data.update(expected_state_sha256='b'*64,receipt_path=str(context.dll.parent/'units.json'))
    return server.SolidWorksCamMillUnitsInput(**(data|changes))

@pytest.mark.parametrize('action',['inspect','prepare','apply'])
def test_exact_route(context,core,action):
    p=params(context,action)
    assert json.loads(server.solidworks_cam_qualify_mill_feature_units(p))['status']=='ok'
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))

@pytest.mark.parametrize('change',[{'process_id':True},{'process_id':0},{'expected_setup_native_id':True},
    {'depth_native':3.0},{'depth_native':'3'},{'depth_native':True},{'depth_native':0},{'depth_native':101},
    {'expected_source_sha256':'bad'},{'qualification_only':False},{'qualification_only':1},
    {'acknowledge_disposable_copy':False},{'acknowledge_disposable_copy':1},
    {'expected_document_path':'relative.sldprt'},{'message_policy':'accept'},{'save':True}])
def test_strict_schema_before_core(context,core,change):
    with pytest.raises(ValueError):params(context,**change)
    core.assert_not_called()

@pytest.mark.parametrize('guard',['pid','path','version'])
def test_native_target_guard(context,core,monkeypatch,guard):
    if guard=='pid':monkeypatch.setattr(server,'_selected_process_id',732)
    elif guard=='path':context.model.GetPathName=str(context.dll.parent/'other.sldprt')
    else:context.sw.RevisionNumber='33.1.0'
    assert json.loads(server.solidworks_cam_qualify_mill_feature_units(params(context)))['status']=='error'
    core.assert_not_called()
    if guard=='pid':context.connect.assert_not_called()

@pytest.mark.parametrize('profile',[
    dict(kind='circle',center_model_mm=[1,1,2],radius_mm=1),
    dict(kind='closed_polyline',points_model_mm=[[0,0,2],[2,0,2],[2,2,2],[0,2,2]]),
    dict(kind='closed_polyline',points_model_mm=[[0,0,2],[2,0,2],[3,5,2],[0,5,2]]),
    dict(kind='closed_polyline',points_model_mm=[[0,0,2],[2,0,2],[2,5,3],[0,5,2]])])
def test_only_asymmetric_rectangle(context,core,profile):
    spec=deepcopy(SPEC);spec['profile']=profile
    with pytest.raises(ValueError):params(context,sketch_spec=spec)
    core.assert_not_called()

@pytest.mark.parametrize('action',['prepare','apply'])
def test_existing_feature_id_inspect_only(context,core,action):
    with pytest.raises(ValueError):params(context,action,expected_feature_native_id=99)
    core.assert_not_called()


def test_existing_id_inspection_routes(context,core):
    server.solidworks_cam_qualify_mill_feature_units(params(context,expected_feature_native_id=99))
    assert core.call_args.kwargs['expected_feature_native_id']==99


def test_mutation_evidence_and_no_overwrite(context,core):
    with pytest.raises(ValueError):params(context,'apply',expected_state_sha256=None)
    with pytest.raises(ValueError):params(context,'prepare',expected_state_sha256='b'*64)
    receipt=context.dll.parent/'units.json';receipt.write_text('previous outcome')
    with pytest.raises(ValueError):params(context,'apply')
    assert receipt.read_text()=='previous outcome'


def test_exact_primary_interface_and_no_replay_annotation():
    assert bridge._INTERFACES['ICWMillFeature']=='{682686E2-3685-11D6-A9AA-00062999E55F}'
    a=server.mcp._tool_manager._tools['solidworks_cam_qualify_mill_feature_units'].annotations
    assert not a.idempotentHint and not a.readOnlyHint
