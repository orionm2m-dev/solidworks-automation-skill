"""Portable remaining-three continuation tests; fake native backends only."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from test_existing_sketch_caps import m,params,FakeBackend
from test_existing_sketch_caps_inspection import inspection,Inspector,sha,FakeFeature


class Remaining(Inspector):
    def create(self,ref,depth,reverse):
        feature=super().create(ref,depth,reverse)
        if feature is not None:feature.i=[s['sketch_name'] for s in self.p['profile_specs']].index(ref)
        return feature


@pytest.fixture
def continuation(inspection):
    q,b=inspection
    r=m.run_inspection(None,q,runtime_check=lambda:None,backend=b)
    assert r['readback_verified']
    p=deepcopy(q);p.update(inspection_receipt_path=q['receipt_path'],inspection_receipt_sha256=sha(q['receipt_path']),
                          receipt_path=str(Path(q['receipt_path']).with_name('continue.json')))
    backend=Remaining(b.p,b)
    return p,backend


def run(q,b):return m.run_continuation(None,q,runtime_check=lambda:None,backend=b)


def test_only_remaining_three_created_and_original_evidence_immutable(continuation):
    q,b=continuation
    paths=[q['partial_receipt_path'],q['inspection_receipt_path'],m.marker_path(b.p)]
    old=[Path(p).read_bytes() for p in paths]
    r=run(q,b)
    assert r['status']=='caps_observed_ram_only' and r['readback_verified']
    assert r['adopted_count']==1 and r['completed_count']==4
    assert [a['index'] for a in r['actions']]==[1,2,3]
    assert [x[0] for x in b.calls]==[s['sketch_name'] for s in b.p['profile_specs'][1:]]
    assert [Path(p).read_bytes() for p in paths]==old and b.cleans==1
    assert r['adopted_feature']['type_name2']=='ICE' and r['adopted_feature']['type_name']=='Boss'
    assert r['after']['features'][-4]['type']=='ICE'
    assert r['Save_attempted'] is False and r['CAM_calls']==0 and r['STEP_geometry_verified'] is False


@pytest.mark.parametrize('field',['partial_receipt_sha256','inspection_receipt_sha256','original_marker_sha256'])
def test_altered_authority_before_native_reads(continuation,field):
    q,b=continuation;q[field]='0'*64
    with pytest.raises(ValueError):run(q,b)
    assert b.calls==[] and b.guard_count==0


@pytest.mark.parametrize('drift',['tree','volume','first_type','first_parent','first_depth','profile'])
def test_live_adoption_drift_blocks_all_remaining_extrusions(continuation,drift):
    q,b=continuation
    if drift=='tree':b.features.append(dict(name='UNRELATED',type='Boss'))
    if drift=='volume':b.volume*=1.01
    if drift=='first_type':b.feature.GetTypeName=lambda:'Cut'
    if drift=='first_parent':b.feature.GetParents=lambda:[SimpleNamespace(Name='wrong')]
    if drift=='first_depth':
        from test_existing_sketch_caps_inspection import FakeDefinition
        d=FakeDefinition();d.GetDepth=lambda x:.002;b.feature.GetDefinition=lambda:d
    if drift=='profile':
        old=b.read_sketch
        def read(spec):
            r,ref=old(spec);r['sketch_readback']['stable']=False;return r,ref
        b.read_sketch=read
    r=run(q,b)
    assert r['status']=='error' and b.calls==[] and not m.continuation_marker_path(b.p).exists()
    assert b.cleans==0


@pytest.mark.parametrize('failure,pending',[('null',False),('raise',True)])
def test_first_remaining_failure_exact_index_one_and_no_replay(continuation,failure,pending):
    q,b=continuation;b.failure=failure;b.fail_index=0
    r=run(q,b)
    assert r['status']=='uncertain' and r['completed_count']==1 and len(b.calls)==1
    assert [a['index'] for a in r['actions']]==[1] and r['native_dispatch_pending'] is pending
    q2=dict(q,receipt_path=str(Path(q['receipt_path']).with_name('retry.json')))
    with pytest.raises(ValueError,match='unused remaining-three'):run(q2,b)
    assert len(b.calls)==1


@pytest.mark.parametrize('pair,ok',[(('ICE','Boss'),True),(('Boss','Boss'),True),(('ICE','Cut'),False),(('Boss','Cut'),False)])
def test_documented_pair_only_and_raw_types_preserved(pair,ok):
    observed=dict(type_name2=pair[0],type_name=pair[1],read_complete=True,getter_errors={})
    saved=deepcopy(observed)
    if ok:assert m.canonical_boss_type(observed)=='Boss'
    else:
        with pytest.raises(ValueError):m.canonical_boss_type(observed)
    assert observed==saved


def test_native_raw_metadata_is_persisted_before_validation_and_rename(params):
    feature=FakeFeature(params);b=m.NativeBackend(None,params);record={};snapshots=[]
    b.read_feature(feature,params['feature_names'][0],record,lambda:snapshots.append(deepcopy(record)))
    assert snapshots[0]['name']==feature.Name and snapshots[1]['type_name2']=='ICE'
    assert record['type']=='ICE' and record['type_name']=='Boss'
    m.verify_feature(record,params,0,True)
    feature.GetTypeName=lambda:'Cut';record={}
    b.read_feature(feature,params['feature_names'][0],record,lambda:None)
    assert record['type_name']=='Cut'
    with pytest.raises(ValueError):m.verify_feature(record,params,0,True)


def test_raw_ice_tree_requires_separately_verified_definition(params):
    b=FakeBackend(params);before=b.capture();after=deepcopy(before)
    after['features'].append(dict(name=params['feature_names'][0],type='ICE'))
    with pytest.raises(ValueError):m.verify_delta(before,after,params,1)
    obs=dict(name=params['feature_names'][0],type_name2='ICE',type_name='Boss',read_complete=True,getter_errors={})
    m.verify_delta(before,after,params,1,[obs])
    obs['type_name']='Cut'
    with pytest.raises(ValueError):m.verify_delta(before,after,params,1,[obs])
