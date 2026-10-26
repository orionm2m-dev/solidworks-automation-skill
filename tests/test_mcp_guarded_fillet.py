"""精确圆角 MCP 契约、筛选兼容性和有界边检查；无 CAD。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'mcp-server') not in sys.path:sys.path.insert(0,str(ROOT/'mcp-server'))
import server

SIGNATURE={"length_mm":10.,"endpoints_mm":[[0.,0.,0.],[10.,0.,0.]],
    "box_mm":[0.,0.,0.,10.,0.,0.],"curve_type":"line","curve_parameters_native":[0.,0.,0.,1.,0.,0.]}


@pytest.fixture
def harness(tmp_path,monkeypatch):
    path=tmp_path/'part.sldprt';path.write_bytes(b'offline')
    model=N(GetPathName=str(path),GetTitle=path.name,GetType=1)
    sw=N(ActiveDoc=model)
    configure=Mock(return_value={"status":"review_required","mutation_attempted":False})
    inspect_edge=Mock(return_value={"signature":deepcopy(SIGNATURE),"adjacent_faces":[],"errors":[]})
    monkeypatch.setitem(sys.modules,'scripts.sw_guarded_fillet',N(configure_fillet=configure,inspect_edge=inspect_edge))
    connect=Mock(return_value=(sw,model));runners=[]
    def locked(op,response_format,load_automation=True,**kwargs):
        runners.append((response_format,load_automation))
        try:return server._result(op(),response_format)
        except Exception as exc:return server._tool_error(exc,response_format)
    monkeypatch.setattr(server,'_run_locked',locked)
    monkeypatch.setattr(server,'_selected_process_id',321)
    monkeypatch.setattr(server,'connect_solidworks',connect)
    monkeypatch.setattr(server,'get_com_member',lambda obj,name:getattr(obj,name),raising=False)
    active=Mock(wraps=server._active_part_required);monkeypatch.setattr(server,'_active_part_required',active)
    legacy=Mock(return_value={"status":"ok","legacy":True});monkeypatch.setattr(server,'_run_feature_with_edges',legacy)
    return N(**locals())


def values(h,dry_run=True):
    data=dict(radius_mm=.3,axis='all',process_id=321,expected_document_path=str(h.path),
        edge_signatures=[deepcopy(SIGNATURE)],expected_edge_count=1,dry_run=dry_run)
    if not dry_run:data.update(expected_selection_sha256='a'*64,receipt_path=str(h.tmp_path/'apply.json'))
    return data


def params(h,dry_run=True,**updates):return server.SolidWorksFilletInput(**(values(h,dry_run)|updates))

def call(p):return json.loads(server.solidworks_fillet(p))


@pytest.mark.parametrize('dry_run',[True,False])
def test_exact_routes_only_guarded_core_after_pid_and_part_guard(harness,dry_run):
    p=params(harness,dry_run)
    assert call(p)==harness.configure.return_value
    harness.configure.assert_called_once_with(harness.sw,process_id=321,expected_document_path=str(harness.path),
        radius_mm=.3,edge_signatures=[SIGNATURE],expected_edge_count=1,dry_run=dry_run,
        expected_selection_sha256=None if dry_run else 'a'*64,receipt_path=None if dry_run else str(harness.tmp_path/'apply.json'))
    harness.active.assert_called_once_with(p);harness.connect.assert_called_once_with(wait_seconds=1)
    harness.legacy.assert_not_called();assert harness.runners==[(server.ResponseFormat.JSON,True)]


@pytest.mark.parametrize('selected',[None,999,'321',True])
def test_wrong_pid_precedes_any_document_connection(harness,monkeypatch,selected):
    monkeypatch.setattr(server,'_selected_process_id',selected)
    assert call(params(harness))['status']=='error'
    harness.active.assert_not_called();harness.connect.assert_not_called();harness.configure.assert_not_called();harness.legacy.assert_not_called()


@pytest.mark.parametrize('change',['path','type','none'])
def test_part_guard_prevents_exact_core(harness,change):
    if change=='path':harness.model.GetPathName=str(harness.tmp_path/'foreign.sldprt')
    elif change=='type':harness.model.GetType=2
    else:harness.sw.ActiveDoc=None
    assert call(params(harness))['status']=='error'
    harness.configure.assert_not_called();harness.legacy.assert_not_called()


@pytest.mark.parametrize('field',['process_id','expected_edge_count'])
@pytest.mark.parametrize('bad',[True,False,0,-1,1.0,'1'])
def test_exact_pid_and_count_strict_positive(harness,field,bad):
    with pytest.raises(ValueError):params(harness,**{field:bad})


@pytest.mark.parametrize('field',['process_id','expected_edge_count','expected_document_path'])
def test_exact_requires_target_fields(harness,field):
    data=values(harness);data.pop(field)
    with pytest.raises(ValueError):server.SolidWorksFilletInput(**data)


def test_exact_count_bounded(harness):
    with pytest.raises(ValueError):params(harness,expected_edge_count=65)


@pytest.mark.parametrize('field,value',[('axis','z'),('axis','x'),('min_length_mm',1.),('max_length_mm',10.),('convex_only',True),('concave_only',True)])
def test_exact_cannot_mix_legacy_filters(harness,field,value):
    with pytest.raises(ValueError):params(harness,**{field:value})


def test_exact_requires_explicit_all_axis_instead_of_legacy_default(harness):
    data=values(harness);data.pop('axis')
    with pytest.raises(ValueError):server.SolidWorksFilletInput(**data)


@pytest.mark.parametrize('field',['process_id','expected_edge_count','expected_selection_sha256','receipt_path'])
def test_exact_metadata_cannot_silently_fall_back_to_legacy(harness,field):
    value={'process_id':321,'expected_edge_count':1,'expected_selection_sha256':'a'*64,'receipt_path':str(harness.tmp_path/'x.json')}[field]
    with pytest.raises(ValueError):server.SolidWorksFilletInput(radius_mm=.3,**{field:value})


@pytest.mark.parametrize('bad',[1,0,'true',None])
def test_exact_dry_run_strict_bool(harness,bad):
    data=values(harness);data['dry_run']=bad
    with pytest.raises(ValueError):server.SolidWorksFilletInput(**data)


@pytest.mark.parametrize('bad',[True,False,'0.3',float('nan'),float('inf')])
def test_exact_radius_requires_finite_json_number(harness,bad):
    with pytest.raises(ValueError):params(harness,radius_mm=bad)


@pytest.mark.parametrize('field',['expected_selection_sha256','receipt_path'])
def test_dry_run_forbids_apply_inputs(harness,field):
    value='a'*64 if field=='expected_selection_sha256' else str(harness.tmp_path/'apply.json')
    with pytest.raises(ValueError):params(harness,**{field:value})


@pytest.mark.parametrize('field',['expected_selection_sha256','receipt_path'])
def test_apply_requires_sha_and_receipt(harness,field):
    data=values(harness,False);data.pop(field)
    with pytest.raises(ValueError):server.SolidWorksFilletInput(**data)


@pytest.mark.parametrize('bad',['A'*64,'f'*63,'g'*64,True])
def test_selection_sha_strict_lowercase(harness,bad):
    with pytest.raises(ValueError):params(harness,False,expected_selection_sha256=bad)


def test_saved_target_and_new_receipt_require_exact_file_types_and_parent(harness):
    existing=harness.tmp_path/'prior.json';existing.write_bytes(b'immutable')
    for receipt in (str(existing),'relative.json',str(harness.tmp_path/'absent'/'out.json'),str(harness.tmp_path/'out.txt')):
        with pytest.raises(ValueError):params(harness,False,receipt_path=receipt)
    for target in ('relative.sldprt',str(harness.tmp_path/'absent.sldprt'),str(existing)):
        with pytest.raises(ValueError):params(harness,expected_document_path=target)
    assert existing.read_bytes()==b'immutable'


@pytest.mark.parametrize('bad',[[],(),{},'edges',[SIGNATURE]*65,[[]]])
def test_signatures_require_bounded_json_dict_list(harness,bad):
    with pytest.raises(ValueError):params(harness,edge_signatures=bad)


@pytest.mark.parametrize('field,value',[
    ('length_mm',True),('length_mm',float('inf')),('length_mm','10'),
    ('box_mm',[0]*5),('box_mm',[0,0,0,True,0,0]),('box_mm',[0,0,0,float('nan'),0,0]),
    ('endpoints_mm',[[0,0,0]]),('endpoints_mm',[[0,0,0],[0,0,'1']]),
    ('curve_type','spline'),('curve_type',True),('curve_parameters_native',[0,True]),
    ('curve_parameters_native',[float('inf')]),('curve_parameters_native',[0]*65),
])
def test_signatures_reject_malformed_shape_or_nonfinite_numbers(harness,field,value):
    signature=deepcopy(SIGNATURE);signature[field]=value
    with pytest.raises(ValueError):params(harness,edge_signatures=[signature])


def test_signature_exact_keys_and_nullable_fields(harness):
    signature=deepcopy(SIGNATURE);signature.pop('box_mm')
    with pytest.raises(ValueError):params(harness,edge_signatures=[signature])
    with pytest.raises(ValueError):params(harness,edge_signatures=[SIGNATURE|{'guess':1}])
    signature=SIGNATURE|{'curve_type':'circle','endpoints_mm':None,'curve_parameters_native':None}
    assert params(harness,edge_signatures=[signature]).edge_signatures==[signature]


def test_legacy_defaults_and_route_stay_unchanged(harness):
    p=server.SolidWorksFilletInput(radius_mm='0.5',dry_run='true')
    assert p.axis=='z' and p.dry_run is True and p.edge_signatures is None
    assert call(p)==harness.legacy.return_value
    harness.configure.assert_not_called()
    assert harness.legacy.call_args.args[0] is p


def test_core_failure_and_markdown_response(harness):
    result=server.solidworks_fillet(params(harness,response_format='markdown'))
    assert result.startswith('# review_required')
    harness.configure.side_effect=RuntimeError('Ambiguous native edge match')
    assert call(params(harness))['status']=='error'
    harness.legacy.assert_not_called()


def test_list_edges_inspects_only_selected_returned_limit_and_preserves_errors(harness,monkeypatch):
    edges=[object() for _ in range(4)]
    descriptors=[{'index':i,'edge':edge,'length_mm':10.,'direction':[1.,0.,0.]} for i,edge in enumerate(edges)]
    monkeypatch.setattr(server,'iter_model_edges',Mock(return_value=(descriptors,[])),raising=False)
    monkeypatch.setattr(server,'filter_edges',Mock(return_value=(descriptors[1:],[])),raising=False)
    monkeypatch.setattr(server,'describe_convexity',Mock(side_effect=AssertionError('convexity disabled')),raising=False)
    harness.inspect_edge.side_effect=[{'signature':SIGNATURE,'adjacent_faces':[{'surface_type':'plane'}],'errors':[]},
        {'signature':None,'adjacent_faces':[],'errors':['native signature unavailable']}]
    p=server.SolidWorksEdgeInspectionInput(expected_document_path=str(harness.path),limit=2,include_convexity=False)
    result=json.loads(server.solidworks_list_edges(p))
    assert result['status']=='ok' and result['truncated'] is True
    assert [item.args for item in harness.inspect_edge.call_args_list]==[(edges[1],),(edges[2],)]
    assert result['edges'][0]['signature']==SIGNATURE
    assert result['edges'][0]['adjacent_faces']==[{'surface_type':'plane'}]
    assert result['edges'][1]['signature'] is None and result['edges'][1]['errors']==['native signature unavailable']
    harness.configure.assert_not_called()
