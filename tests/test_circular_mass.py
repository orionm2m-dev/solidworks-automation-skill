from copy import deepcopy
from pathlib import Path
import hashlib,json,math,os
import pytest
from test_current_circular_pocket import env
from scripts import sw_cam_current_circular_delta as d


def state():
    return dict(sketch_state=dict(solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[.001,.002,.003,.004])],needs_save=False,saved_file_sha256='a'*64),operations=[dict(native_id=10,value=.002)],document=dict(needs_save=False),source='a'*64)


def test_mass_only_noise_reuses_existing_tolerance_preserves_raw():
    a=state();b=deepcopy(a);b['sketch_state']['solids'][0]['mass_raw'][0]*=1.+1e-13
    original=deepcopy(b);assert a!=b and d.circular_state_equal(a,b)
    aligned=d.align_circular_mass(a,b);assert aligned==a and b==original and b!=aligned
    aligned['operations'][0]['value']=5.;assert b==original


@pytest.mark.parametrize('defect',['nan','inf','bool','int','empty','short','tuple','arity','body_count','no_bodies','body_tuple','box_tiny','box_bool','box_nan','box_arity','mass_large','zero_absolute','other_body_key','outside_mass','source'])
def test_invalid_mass_or_any_other_delta_rejected(defect):
    a=state();b=deepcopy(a);body=b['sketch_state']['solids'][0];mass=body['mass_raw']
    if defect in ('nan','inf','bool','int'):mass[0]={'nan':float('nan'),'inf':float('inf'),'bool':True,'int':1}[defect]
    elif defect=='empty':body['mass_raw']=[]
    elif defect=='short':body['mass_raw']=[1.,2.,3.]
    elif defect=='tuple':body['mass_raw']=tuple(mass)
    elif defect=='arity':mass.append(0.)
    elif defect=='body_count':b['sketch_state']['solids'].append(deepcopy(body))
    elif defect=='no_bodies':b['sketch_state']['solids']=[]
    elif defect=='body_tuple':b['sketch_state']['solids']=tuple(b['sketch_state']['solids'])
    elif defect=='box_tiny':body['box_m'][0]=1e-20
    elif defect=='box_bool':body['box_m'][0]=False
    elif defect=='box_nan':body['box_m'][0]=float('nan')
    elif defect=='box_arity':body['box_m'].append(0.)
    elif defect=='mass_large':mass[0]*=1.+1e-8
    elif defect=='zero_absolute':a['sketch_state']['solids'][0]['mass_raw'][0]=0.;mass[0]=1e-30
    elif defect=='other_body_key':body['unrequested']=0.
    elif defect=='outside_mass':b['operations'][0]['value']*=1.+1e-13
    elif defect=='source':b['source']='b'*64
    assert not d.circular_state_equal(a,b)


def test_invalid_mass_rejected_even_when_identical():
    a=state();a['sketch_state']['solids'][0]['mass_raw'][0]=float('nan')
    assert not d.circular_state_equal(a,deepcopy(a))


def test_non_state_values_keep_exact_existing_comparison():
    assert d.circular_state_equal([1.],[1.])
    assert not d.circular_state_equal([1.],[1.+1e-13])
    assert not d.circular_state_equal(state(),{})


def test_full_creation_all_pairs_save_and_prepare_reuse_allow_only_mass_noise(env):
    env['mass_jitter']=True;p=env['run']('prepare');assert p['readback_verified'] and p['before']!=p['confirm_before']
    r=env['run']('apply');assert r['readback_verified'] and r['model_saved'],r
    assert env['calls']==['sketch','feature','insert','save']
    for key in ['before','after_sketch','after_feature','after_insert','saved']:
        assert r[key]!=r['confirm_'+key] and d.circular_state_equal(r[key],r['confirm_'+key])
    saved=json.loads(Path(env['v']['receipt_path']).with_name('apply.json').read_text(encoding='utf-8'))
    assert saved['saved']!=saved['confirm_saved'] and saved['saved']==r['saved']
    assert env['run']('apply')['status']=='error' and len(env['calls'])==4


def test_excessive_mass_change_retained_and_stops_before_insert(env):
    assert env['run']('prepare')['readback_verified'];env['mass_bad_stage']='after_feature';r=env['run']('apply')
    assert r['status']=='uncertain' and not r['model_saved'] and env['calls']==['sketch','feature']
    assert r['after_feature']['sketch_state']['solids'][0]['mass_raw'][0]>r['confirm_after_feature']['sketch_state']['solids'][0]['mass_raw'][0]


def test_optional_actual_failed_prepare_is_mass_only_and_immutable():
    name=os.environ.get('SW_CAM_TEST_CIRCULAR_PREPARE');digest=os.environ.get('SW_CAM_TEST_CIRCULAR_PREPARE_SHA256')
    if not name or not digest:pytest.skip('Optional pinned external native prepare receipt unavailable')
    p=Path(name);raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==digest
    report=json.loads(raw);assert report['mutation_attempted'] is False and report['actions']==[] and report['marker_created'] is False
    a=report['before'];b=report['confirm_before'];assert a!=b and d.circular_state_equal(a,b)
    assert d.align_circular_mass(a,b)==a and p.read_bytes()==raw
