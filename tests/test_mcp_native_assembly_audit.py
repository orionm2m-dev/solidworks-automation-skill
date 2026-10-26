"""装配/动画 MCP 的显式进程、文件与只读路由测试；不调用 CAD。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'mcp-server') not in sys.path:sys.path.insert(0,str(ROOT/'mcp-server'))
import server


@pytest.fixture
def setup(tmp_path,monkeypatch):
    assembly=tmp_path/'owned.sldasm';assembly.write_bytes(b'native')
    baseline=tmp_path/'baseline.json';baseline.write_text('{}')
    model=N(GetPathName=str(assembly),GetTitle=assembly.name,GetType=2)
    sw=N(ActiveDoc=model)
    inspect=Mock(return_value={'status':'review_required','readback_complete':True})
    motion=Mock(return_value={'status':'review_required','animation_comparison_verified':True})
    monkeypatch.setitem(sys.modules,'scripts.sw_native_assembly_audit',N(inspect_native_assembly=inspect,audit_native_animation=motion))
    monkeypatch.setattr(server,'_selected_process_id',71)
    monkeypatch.setattr(server,'connect_solidworks',Mock(return_value=(sw,model)))
    monkeypatch.setattr(server,'get_com_member',lambda obj,name:getattr(obj,name),raising=False)
    def locked(op,response_format,**kwargs):
        try:return server._result(op(),response_format)
        except Exception as exc:return server._tool_error(exc,response_format)
    monkeypatch.setattr(server,'_run_locked',locked)
    active=Mock(wraps=server._active_model_required);monkeypatch.setattr(server,'_active_model_required',active)
    return N(**locals())


def arguments(p,kind):
    args=dict(process_id=71,expected_document_path=str(p.assembly),expected_file_sha256='a'*64,receipt_path=str(p.tmp_path/'receipt.json'))
    if kind=='motion':args.update(study_name=' Exact Study ',explode_view_name='ExplView',
        baseline_samples_path=str(p.baseline),baseline_samples_sha256='b'*64,
        tracked_components=[dict(key='part',reference=' Native ref ',path=str(p.tmp_path/'part.sldprt'))])
    return args


def schema(kind):return server.SolidWorksNativeAssemblyInspectionInput if kind=='inspect' else server.SolidWorksNativeAnimationAuditInput

def invoke(kind,params):return json.loads((server.solidworks_inspect_native_assembly if kind=='inspect' else server.solidworks_audit_native_animation)(params))


@pytest.mark.parametrize('kind',['inspect','motion'])
def test_route_preserves_exact_bstr_and_response_format(setup,kind):
    p=setup;params=schema(kind)(**arguments(p,kind))
    result=invoke(kind,params);native=getattr(p,kind)
    assert result==native.return_value
    native.assert_called_once_with(p.sw,**params.model_dump(exclude={'response_format','expected_document_title'}))
    assert params.response_format==server.ResponseFormat.JSON
    if kind=='motion':assert params.study_name==' Exact Study ' and params.tracked_components[0].reference==' Native ref '


@pytest.mark.parametrize('kind',['inspect','motion'])
@pytest.mark.parametrize('selected',[None,999,True,'71'])
def test_wrong_bound_pid_stops_before_connection(setup,monkeypatch,kind,selected):
    p=setup;monkeypatch.setattr(server,'_selected_process_id',selected)
    assert invoke(kind,schema(kind)(**arguments(p,kind)))['status']=='error'
    p.active.assert_not_called();getattr(p,kind).assert_not_called()


@pytest.mark.parametrize('kind',['inspect','motion'])
def test_wrong_document_stops_before_core(setup,kind):
    p=setup;p.model.GetPathName=str(p.tmp_path/'foreign.sldasm')
    assert invoke(kind,schema(kind)(**arguments(p,kind)))['status']=='error'
    getattr(p,kind).assert_not_called()


@pytest.mark.parametrize('kind',['inspect','motion'])
@pytest.mark.parametrize('field,value',[('process_id',True),('process_id',0),('process_id','71'),
    ('expected_file_sha256','g'*64),('receipt_path','relative.json'),('expected_document_path','relative.sldasm')])
def test_invalid_identity_or_path_fails_schema(setup,kind,field,value):
    with pytest.raises(ValueError):schema(kind)(**(arguments(setup,kind)|{field:value}))


@pytest.mark.parametrize('kind',['inspect','motion'])
def test_existing_receipt_cannot_be_overwritten(setup,kind):
    p=setup;target=p.tmp_path/'receipt.json';target.write_bytes(b'keep')
    with pytest.raises(ValueError):schema(kind)(**arguments(p,kind))
    assert target.read_bytes()==b'keep'


@pytest.mark.parametrize('value',[True,0,-1,1e-5,float('nan'),float('inf'),'0.00000001'])
def test_matrix_tolerance_is_finite_strict_and_bounded(setup,value):
    with pytest.raises(ValueError):schema('motion')(**(arguments(setup,'motion')|dict(matrix_tolerance=value)))


def test_snapshot_path_map_requires_exact_baseline_pair(setup):
    p=setup;base=arguments(p,'inspect');mapping={str(p.assembly):str(p.tmp_path/'new.sldasm')}
    with pytest.raises(ValueError):schema('inspect')(**(base|dict(path_replacements=mapping)))
    with pytest.raises(ValueError):schema('inspect')(**(base|dict(expected_snapshot_path=str(p.baseline))))
    params=schema('inspect')(**(base|dict(expected_snapshot_path=str(p.baseline),expected_snapshot_sha256='b'*64,path_replacements=mapping)))
    invoke('inspect',params);assert p.inspect.call_args.kwargs['path_replacements']==mapping


@pytest.mark.parametrize('count',[0,17])
def test_tracking_count_is_bounded(setup,count):
    args=arguments(setup,'motion');args['tracked_components']*=count
    with pytest.raises(ValueError):schema('motion')(**args)
