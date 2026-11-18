"""Offline four-name branch and backwards-compatible six-name default."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import os
import pytest
from test_sw_cam_pocket_pair_read import m,Ref,association_fakes,FIXTURE

NAMES=['Current face '+str(i) for i in range(4)]

def run(names=NAMES,expected_count=4,**options):
    read,typed,log=association_fakes(**options);diag={}
    out=m.read_face_associations(Ref(),names,read=read,typed=typed,diagnostic=diag,expected_count=expected_count)
    return out,diag,log

@pytest.mark.parametrize('kind',['line','circle'])
def test_four_explicit_names_preserve_raw_world_geometry_without_role_promotion(kind):
    out,diag,log=run(curve_kind=kind)
    assert [r['name'] for r in out['rows']]==NAMES and log.count('FeatureByName')==4
    assert out['all_four_faces_observed'] is True and out['all_four_analytic_geometry_complete'] is True
    assert 'all_six_faces_observed' not in out and out['total_edges']==4 and diag['complete'] is True
    assert all(r['model_coordinate_units']=='metre' and r['cam_chain_transform_inferred'] is False for r in out['rows'])
    assert out['geometric_role_mapping_verified'] is False and out['production_qualified'] is False

@pytest.mark.parametrize('count',[True,False,0,1,3,5,7,4.,None,'4'])
def test_invalid_count_is_rejected_before_any_callback(count):
    calls=[]
    with pytest.raises(ValueError):m.read_face_associations(Ref(),NAMES,read=lambda *a:calls.append(a),typed=lambda *a:calls.append(a),diagnostic={},expected_count=count)
    assert calls==[]

@pytest.mark.parametrize('names',[NAMES[:3],NAMES+['Extra'],NAMES+['X','Y'],['A','a','B','C'],['A','A','B','C'],['',*NAMES[1:]],[' '+NAMES[0],*NAMES[1:]],['x'*129,*NAMES[1:]],[1,*NAMES[1:]],['nul\x00x',*NAMES[1:]],tuple(NAMES)])
def test_names_fail_closed_before_native_lookup(names):
    calls=[]
    with pytest.raises(ValueError):m.read_face_associations(Ref(),names,read=lambda *a:calls.append(a),typed=lambda *a:calls.append(a),diagnostic={},expected_count=4)
    assert calls==[]

@pytest.mark.parametrize('failure,forbidden',[('absent','GetTypeName2'),('not_attribute','GetSpecificFeature2'),('ambiguous','GetEntity'),('null','GetType'),('edge','GetSurface'),('nonplanar','PlaneParams')])
def test_four_unavailable_links_remain_unresolved_without_fallback(failure,forbidden):
    out,diag,log=run(failure=failure)
    assert out['all_four_faces_observed'] is False and out['all_four_analytic_geometry_complete'] is False
    assert len(out['rows'])==4 and all(r['status']=='unresolved' for r in out['rows'])
    assert forbidden not in log

def test_unknown_curve_is_not_analytic_acceptance():
    out,_,_=run(curve_kind='spline')
    assert out['all_four_faces_observed'] is True and out['all_four_analytic_geometry_complete'] is False

def test_wrong_named_feature_throws_without_association_getter():
    read,typed,log=association_fakes()
    def wrong(obj,name,*args):return 'another' if name=='Name' else read(obj,name,*args)
    with pytest.raises(ValueError):m.read_face_associations(Ref(),NAMES,read=wrong,typed=typed,diagnostic={},expected_count=4)
    assert 'GetSpecificFeature2' not in log

def test_existing_total_edge_budget_not_relaxed_for_four_faces():
    read,typed,log=association_fakes();diag={}
    def many(obj,name,*args):return tuple(Ref()for _ in range(33)) if name=='GetEdges' else read(obj,name,*args)
    with pytest.raises(ValueError,match='edge budget'):m.read_face_associations(Ref(),NAMES,read=many,typed=typed,diagnostic=diag,expected_count=4)
    assert diag.get('complete') is not True

def test_default_six_output_and_getter_sequence_equal_unmodified_installed_helper():
    rt=Path(os.environ['SWMCP_RUNTIME_ROOT']);spec=importlib.util.spec_from_file_location('legacy_pocket_associations',rt/'scripts/sw_cam_pocket_pair_read.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    old_read,old_typed,old_log=association_fakes();new_read,new_typed,new_log=association_fakes()
    before=legacy.read_face_associations(Ref(),FIXTURE['names'],read=old_read,typed=old_typed,diagnostic={})
    after=m.read_face_associations(Ref(),FIXTURE['names'],read=new_read,typed=new_typed,diagnostic={})
    assert before==after and old_log==new_log
