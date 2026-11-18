"""Offline contract tests; fake backend only, no COM, runtime writes or native CAD."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import ast
import hashlib
import importlib.util
import json
import math
import os
import sys
import pytest

STAGE = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('SOLIDWORKS_AUTOMATION_ROOT', str(STAGE))).resolve()
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))
spec = importlib.util.spec_from_file_location('caps_under_test', STAGE/'scripts/sw_existing_sketch_caps.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def profile(name, angle):
    r0, r1, w, z = 13.2, 16.2, 2.5, 25.8
    ai, ao = math.asin(w/r0), math.asin(w/r1)
    c, s = math.cos(angle), math.sin(angle)
    def pt(r, t):
        x, y = r*math.cos(t), r*math.sin(t)
        return [x*c-y*s, x*s+y*c, z]
    rows = [dict(kind='arc', start_model_mm=pt(r1,-ao), end_model_mm=pt(r1,ao),
                 mid_model_mm=pt(r1,0), center_model_mm=[0,0,z], radius_mm=r1, sweep_radians=2*ao),
            dict(kind='line', start_model_mm=pt(r1,ao), end_model_mm=pt(r0,ai)),
            dict(kind='arc', start_model_mm=pt(r0,ai), end_model_mm=pt(r0,-ai),
                 mid_model_mm=pt(r0,0), center_model_mm=[0,0,z], radius_mm=r0, sweep_radians=-2*ai),
            dict(kind='line', start_model_mm=pt(r0,-ai), end_model_mm=pt(r1,-ao))]
    for row in rows:
        if row['kind']=='line': row['mid_model_mm']=[(x+y)/2 for x,y in zip(row['start_model_mm'],row['end_model_mm'])]
    return dict(plane_axis='Z', plane_offset_mm=z, sketch_name=name,
                plane_name=name+'_PLANE', profile=dict(kind='closed_mixed', segments=rows))


@pytest.fixture
def params(tmp_path):
    source, target = tmp_path/'source.SLDPRT', tmp_path/'copy.SLDPRT'
    source.write_bytes(b'unchanged saved five sketches'); target.write_bytes(source.read_bytes())
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    return dict(process_id=123, expected_process_creation_time=1000.25,
                expected_document_path=str(target), expected_source_sha256=digest,
                protected_document_path=str(source), protected_source_sha256=digest,
                expected_configuration='one', profile_specs=[profile('LOOP_'+str(i),a) for i,a in enumerate((.2,1.2,3.2,4.2))],
                feature_names=['CAP_'+str(i) for i in range(4)], depth_mm=1.,
                desired_direction_world=[0,0,-1], receipt_path=str(tmp_path/'receipt.json'))


class FakeBackend:
    def __init__(self,p):
        self.p=p;self.calls=[];self.cleans=0;self.failure=None;self.fail_index=1
        self.dirty=False;self.normal=[0,0,1];self.reads=[];self.guard_count=0
        self.features=[dict(name='BASE',type='Imported')]+[dict(name=s['sketch_name'],type='ProfileFeature') for s in p['profile_specs']]
        self.volume=1e-5;self.body_count=1;self.feature_defect=None;self.bad_owner=False
    def boundary(self,dirty):
        self.guard_count+=1
        m.require(not self.bad_owner,'owner mismatch')
        m.require(self.dirty is dirty,'dirty mismatch')
        return dict(process_id=self.p['process_id'],create_time=self.p['expected_process_creation_time'],alive=True)
    def capture(self):
        m.require(self.body_count==1,'one body required')
        return deepcopy(dict(features=self.features,solids=[dict(box_m=[0,0,0,1,1,1],mass_raw=[0,0,0,self.volume])],
                             volume_m3=self.volume,body_check=0,needs_save=self.dirty))
    def read_sketch(self,s):
        self.reads.append(s['sketch_name'])
        return dict(spec=deepcopy(s),sketch_readback={'stable':True},proof={'verified':True},
                    normal_world=list(self.normal),reverse_direction=m.direction_from_normal(self.normal,self.p['desired_direction_world'])),s['sketch_name']
    def existing_features(self,rows):
        m.require(all(any(x==row for x in self.features) for row in rows),'existing feature drift')
    def create(self,ref,depth,reverse):
        i=len(self.calls);self.calls.append((ref,depth,reverse))
        if i==self.fail_index:
            if self.failure=='raise':raise RuntimeError('native dispatch exception')
            if self.failure=='null':return None
            if self.failure=='hash':Path(self.p['protected_document_path']).write_bytes(b'drift')
        self.dirty=True
        if self.failure!='zero_volume' or i!=self.fail_index:self.volume+=1e-8
        if self.failure=='two_bodies' and i==self.fail_index:self.body_count=2
        return SimpleNamespace(i=i)
    def read_feature(self,f,name,observed,persist):
        row=dict(name=name,type='Boss');self.features.append(row)
        out=dict(**row,type_name2='Boss',type_name='Boss',read_complete=True,getter_errors={},depth_m=.001,end_condition=0,reverse_direction=self.calls[-1][2],merge=True,
                 both_directions=False,from_type=0,is_boss=True,is_thin=False,draft=False,
                 parents=[self.p['profile_specs'][f.i]['sketch_name']])
        if self.feature_defect:out.update(self.feature_defect)
        observed.update(out);persist()
        return observed
    def rename_feature(self,f,name):return name
    def cleanup(self):self.cleans+=1


def run(p,b):return m.run(None,p,runtime_check=lambda:None,backend=b)


@pytest.mark.parametrize('normal,desired,reverse',[([0,0,1],[0,0,-1],True),([0,0,-1],[0,0,-1],False),
                                                ([0,0,1],[0,0,1],False),([0,0,-1],[0,0,1],True)])
def test_api_reverse_semantics_both_normal_orientations(normal,desired,reverse):
    assert m.direction_from_normal(normal,desired) is reverse


@pytest.mark.parametrize('normal',[[1,0,0],[0,1,0],[0,0,2],[0,0,0],[.001,0,1],[0,0,float('nan')]])
def test_unsupported_normals_rejected(normal):
    with pytest.raises(ValueError):m.direction_from_normal(normal,[0,0,-1])


@pytest.mark.parametrize('inverted',[False,True])
def test_native_sketch_inverse_is_used_for_normal_and_world_height(monkeypatch,inverted):
    sign=-1 if inverted else 1
    forward=SimpleNamespace(ArrayData=[1,0,0,0,sign,0,0,0,sign,0,0,-sign*.0258,1,0,0,0])
    inverse=SimpleNamespace(ArrayData=[1,0,0,0,sign,0,0,0,sign,0,0,.0258,1,0,0,0])
    calls=[]
    def call(obj,name,*args):
        calls.append(name)
        return inverse if name=='Inverse' else 'math'
    def point(mu,coords,t):
        assert t is inverse
        return [coords[0],coords[1]*sign,coords[2]*sign+.0258]
    monkeypatch.setattr(m,'call',call);monkeypatch.setattr(m.core,'_point',point)
    result=m.sketch_direction(object(),SimpleNamespace(ModelToSketchTransform=forward),
                              {'model_to_sketch_transform':forward.ArrayData},{'plane_offset_mm':25.8},[0,0,-1])
    assert result['reverse_direction'] is (not inverted)
    assert calls==['Inverse','GetMathUtility']


def test_complete_four_existing_profiles_no_redraw(params):
    b=FakeBackend(params);r=run(params,b)
    assert r['status']=='caps_observed_ram_only' and r['completed_count']==4 and r['readback_verified']
    assert [x[0] for x in b.calls]==[s['sketch_name'] for s in params['profile_specs']]
    assert len(b.reads)==12 and b.cleans==1 and all(x[2] is True for x in b.calls)
    assert all(a['attempted'] and a['returned_object'] and a['readback_verified'] and not a['pending'] for a in r['actions'])
    assert r['CAM_calls']==0 and r['Save_attempted'] is False and r['STEP_geometry_verified'] is False
    assert json.loads(Path(params['receipt_path']).read_text())==r
    assert m.marker_path(params).exists()


@pytest.mark.parametrize('field,value',[('process_id',True),('depth_mm',0),('depth_mm',6),('depth_mm',float('nan')),
                                      ('desired_direction_world',[1,0,0]),('profile_specs',[]),('feature_names',['A']*4),
                                      ('protected_source_sha256','b'*64),('expected_document_path','relative.SLDPRT')])
def test_invalid_contract_blocked_before_mutation(params,field,value):
    p=deepcopy(params);p[field]=value;b=FakeBackend(p)
    with pytest.raises(ValueError):run(p,b)
    assert b.calls==[] and not m.marker_path(params).exists()


def test_dirty_and_owner_mismatch_before_mutation(params):
    for issue in ('dirty','owner'):
        p=deepcopy(params);p['receipt_path']=str(Path(params['receipt_path']).with_name(issue+'.json'));b=FakeBackend(p)
        if issue=='dirty':b.dirty=True
        else:b.bad_owner=True
        r=run(p,b);assert r['status']=='error' and not r['mutation_attempted'] and b.calls==[]
    assert not m.marker_path(params).exists()


def test_source_hash_mismatch_before_mutation(params):
    Path(params['protected_document_path']).write_bytes(b'changed')
    b=FakeBackend(params)
    with pytest.raises(ValueError,match='hash'):run(params,b)
    assert b.calls==[]


@pytest.mark.parametrize('failure,pending,returned',[('raise',True,False),('null',False,True)])
def test_second_failure_stops_exact_partial_prefix_without_replay(params,failure,pending,returned):
    b=FakeBackend(params);b.failure=failure;r=run(params,b)
    assert r['status']=='uncertain' and len(b.calls)==2 and r['completed_count']==1 and b.cleans==1
    assert r['actions'][0]['readback_verified'] and r['actions'][1]['pending'] is pending
    assert r['actions'][1]['returned'] is returned and r['native_dispatch_pending'] is pending
    assert r['actions'][1]['returned_object'] is False
    again=deepcopy(params);again['receipt_path']=str(Path(params['receipt_path']).with_name('another.json'))
    with pytest.raises(ValueError,match='prior attempt'):run(again,FakeBackend(again))


@pytest.mark.parametrize('failure',['hash','zero_volume','two_bodies'])
def test_post_create_drift_stops_remaining_items(params,failure):
    b=FakeBackend(params);b.failure=failure;r=run(params,b)
    assert r['status']=='uncertain' and len(b.calls)==2 and r['completed_count']==1
    assert not r['readback_verified'] and b.cleans==1


@pytest.mark.parametrize('defect',[{'depth_m':.002},{'reverse_direction':False},{'merge':False},{'both_directions':True},
                                  {'from_type':3},{'end_condition':1},{'is_thin':True},{'draft':True},{'parents':['wrong']}])
def test_actual_definition_mismatch_blocks_next_feature(params,defect):
    b=FakeBackend(params);b.feature_defect=defect;r=run(params,b)
    assert r['status']=='uncertain' and len(b.calls)==1 and r['completed_count']==0


def test_backend_uses_existing_native_boss_with_retained_reference(monkeypatch,params):
    seen=[]
    monkeypatch.setattr(m.sw_part,'extrude_boss',lambda *a,**k:seen.append((a,k)) or 'feature')
    b=m.NativeBackend(None,params);b.model='model';reference=object()
    assert b.create(reference,1.,False)=='feature'
    assert seen==[(('model',reference,.001),dict(direction=False,merge=True,start_offset=0.0))]
    tree=ast.parse((STAGE/'scripts/sw_existing_sketch_caps.py').read_text(encoding='utf-8-sig'))
    names={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
    assert not names.intersection({'InsertSketch','CreateLine','CreateArc','DeleteSelection2','Save3','SaveAs','GenerateOpPlan','GenerateToolpath','ExitApp'})


def test_unrelated_top_tree_change_rejected(params):
    b=FakeBackend(params);before=b.capture();after=deepcopy(before);after['features'].append(dict(name='UNRELATED',type='Boss'))
    with pytest.raises(ValueError,match='Unexpected'):m.verify_delta(before,after,params,1)


def test_harmless_repeated_capture_float_jitter_accepted(params):
    class Jitter(FakeBackend):
        def capture(self):
            r=super().capture()
            factor=1+(8.55e-13 if self.guard_count%2 else 0)
            r['volume_m3']*=factor;r['solids'][0]['mass_raw'][3]*=factor
            return r
    b=Jitter(params);r=run(params,b)
    assert r['status']=='caps_observed_ram_only' and len(b.calls)==4


def test_real_mass_drift_before_next_call_rejected(params):
    class Drift(FakeBackend):
        def capture(self):
            r=super().capture()
            if len(self.calls)==1 and self.guard_count>=6:
                r['volume_m3']*=1+1e-6;r['solids'][0]['mass_raw'][3]*=1+1e-6
            return r
    b=Drift(params);r=run(params,b)
    assert r['status']=='uncertain' and len(b.calls)==1
    assert 'state drift' in r['issue']['message']


def test_body_box_change_not_hidden_by_mass_tolerance(params):
    b=FakeBackend(params);a=b.capture();z=deepcopy(a);z['solids'][0]['box_m'][0]+=1e-12
    assert not m.same_capture(a,z)


def test_cleanup_failure_revokes_success_and_preserves_created_prefix(params):
    b=FakeBackend(params)
    def cleanup():raise RuntimeError('selection cleanup failed')
    b.cleanup=cleanup;r=run(params,b)
    assert r['status']=='uncertain' and r['completed_count']==4 and not r['readback_verified']
    assert 'cleanup_issue' in r


def test_output_name_conflict_blocks_all_extrusions(params):
    b=FakeBackend(params);b.features.append(dict(name=params['feature_names'][0],type='Boss'));r=run(params,b)
    assert r['status']=='error' and b.calls==[] and not m.marker_path(params).exists()


def test_nonaxial_actual_sketch_preflight_rejects_before_mutation(params):
    b=FakeBackend(params);b.normal=[1,0,0];r=run(params,b)
    assert r['status']=='error' and b.calls==[] and not m.marker_path(params).exists()


def test_single_body_gate_before_mutation(params):
    b=FakeBackend(params);b.body_count=2;r=run(params,b)
    assert r['status']=='error' and b.calls==[]
