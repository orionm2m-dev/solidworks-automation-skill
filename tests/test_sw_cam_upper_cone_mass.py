"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
import json,math
import pytest
from scripts import sw_cam_upper_cone_feature as m

from cam_face_test_fixtures import mass_pair

@pytest.fixture
def actual():return mass_pair()

def test_actual_v4_eight_mass_deltas_only(actual):
    a,b=deepcopy(actual);original_a=deepcopy(a);original_b=deepcopy(b);diag={}
    normalized=m.require_state_equivalent(a,b,diagnostic=diag)
    assert normalized==a and normalized is not b and a==original_a and b==original_b
    expected=[{'path':f'/sw_reference/solids/0/mass_raw/{i}'} for i in range(8)]
    assert len(diag['accepted_numeric_deltas'])==len(expected)==8
    assert {r['path'] for r in diag['accepted_numeric_deltas']}=={r['path'] for r in expected}
    assert 5e-14<max(r['relative_delta'] for r in diag['accepted_numeric_deltas'])<1e-12
    assert diag['state_equivalent'] and not diag['manufacturing_tolerance']

@pytest.mark.parametrize('change',['zero_nonzero','nonzero_zero','nan','inf','bool','int','short','long','tuple','body_count','missing'])
def test_invalid_mass_values_rejected(actual,change):
    a,b=deepcopy(actual);x=a['sw_reference']['solids'][0]['mass_raw'];y=b['sw_reference']['solids'][0]['mass_raw']
    if change=='zero_nonzero':x[11]=0.;y[11]=5e-324
    elif change=='nonzero_zero':x[11]=5e-324;y[11]=0.
    elif change in ('nan','inf'):y[11]=float(change)
    elif change=='bool':y[11]=True
    elif change=='int':y[11]=1
    elif change=='short':y.pop()
    elif change=='long':y.append(0.)
    elif change=='tuple':b['sw_reference']['solids'][0]['mass_raw']=tuple(y)
    elif change=='body_count':b['sw_reference']['solids'].append(deepcopy(b['sw_reference']['solids'][0]))
    else:del b['sw_reference']['solids'][0]['mass_raw']
    with pytest.raises(ValueError):m.require_state_equivalent(a,b)

@pytest.mark.parametrize('change',['box','native_id','stock','source','dirty','feature_tree','numeric_type','other_mass_path','mass_over_tolerance'])
def test_nonmass_state_remains_exact(actual,change):
    a,b=deepcopy(actual)
    if change=='box':b['sw_reference']['solids'][0]['box_m'][0]+=1e-15
    elif change=='native_id':b['operations'][0]['native_id']+=1
    elif change=='stock':b['stock']['stl_sha256']='0'*64
    elif change=='source':b['saved_file_sha256']='0'*64
    elif change=='dirty':b['document']['needs_save']=False
    elif change=='feature_tree':b['sw_reference']['feature_tree'][0]['name']+='x'
    elif change=='numeric_type':b['operations'][0]['native_id']=float(b['operations'][0]['native_id'])
    elif change=='other_mass_path':a['unrelated']={'mass_raw':[1.]};b['unrelated']={'mass_raw':[1.+1e-13]}
    else:b['sw_reference']['solids'][0]['mass_raw'][11]=a['sw_reference']['solids'][0]['mass_raw'][11]*(1.+1e-11)
    diag={}
    with pytest.raises(ValueError):m.require_state_equivalent(a,b,diagnostic=diag)
    assert diag['state_equivalent'] is False

def test_exact_zero_and_tiny_same_sign_relative_noise(actual):
    a,b=deepcopy(actual);a['sw_reference']['solids'][0]['mass_raw'][0]=0.;b['sw_reference']['solids'][0]['mass_raw'][0]=0.
    a['sw_reference']['solids'][0]['mass_raw'][11]=1e-100;b['sw_reference']['solids'][0]['mass_raw'][11]=1e-100*(1.+1e-13)
    assert m.require_state_equivalent(a,b)==a

def test_same_policy_on_postcreation_feature_delta(actual):
    a,b=deepcopy(actual);new=deepcopy(b['features'][12]);new['feature_index']=13;new['geometry']['native_id']=700
    b['features'].insert(13,new);b['feature_setups'][0]['feature_count']+=1
    diag={};got=m.verify_feature_delta(a,b,700,69,diagnostic=diag)
    assert got==new and len(diag['accepted_numeric_deltas'])==8
    b['operations'][0]['suppressed']=not b['operations'][0]['suppressed']
    with pytest.raises(ValueError):m.verify_feature_delta(a,b,700,69)
