"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_raw_mill_face_save as m
from test_sw_cam_face_save import chain
@pytest.fixture
def original(chain):return deepcopy(chain.data)

def validate(data):
    return m._failed_feature_fields(data,process_id=data['process_id'],expected_document_path=data['expected_document_path'],
        source_sha256=data['expected_source_sha256'],new_id=data['new_feature_native_id'])

def test_actual_failed_start_is_preserved_not_changed_to_center(original):
    raw=deepcopy(original);obs=original['face_observation']
    out=m.verify_recovered_face_geometry(obs['feature'],obs['sketch_circle_m'],265)
    assert out['raw_start_native']==[32.5,0.,28.] and out['start_on_top_contour_observed']
    assert out['raw_top_center_native']==[0.,0.,28.]
    assert not out['start_coordinate_semantics_qualified'] and not out['geometric_depth_verified']
    assert not out['coordinate_frame_qualified'] and not out['physical_stock_removal_proved']
    assert not out['lower_world_boundary_synthesized'] and original==raw
    assert validate(original)==m.face.FACE_SPEC and original==raw

@pytest.mark.parametrize('start',[[0.,0.,28.],[32.49,0.,28.],[32.5,0.,28.01],[float('nan'),0.,28.],
    [float('inf'),0.,28.],[True,0.,28.],[32.5,0.],[32.5,0.,28.,0.]])
def test_start_predicate_rejects_other_meanings_and_invalid_values(original,start):
    obs=deepcopy(original['face_observation']);obs['feature']['start_native']=start
    with pytest.raises(ValueError):m.verify_recovered_face_geometry(obs['feature'],obs['sketch_circle_m'],265)

@pytest.mark.parametrize('change',['depth','axis','bounds','volume','identity','island','taper','topcenter','bottomplane','radius','sketch'])
def test_recovery_keeps_other_complete_geometry_constraints(original,change):
    obs=deepcopy(original['face_observation']);f=obs['feature']
    if change=='depth':f['depth_native']=1.
    elif change=='axis':f['axis_native']=[0,0,1]
    elif change=='bounds':f['bounds_native'][2]=1.
    elif change=='volume':f['volume_type']=2
    elif change=='identity':f['native_id']=True
    elif change=='island':f['island_count']=1
    elif change=='taper':f['taper_enabled']=True
    elif change=='topcenter':f['top_curves_native'][0]['centre_native'][0]=.1
    elif change=='bottomplane':f['bottom_curves_native'][0]['centre_native'][2]=27.
    elif change=='radius':f['bottom_curves_native'][0]['radius_native']=32.4
    else:obs['sketch_circle_m']['radius_m']=.0324
    with pytest.raises(ValueError):m.verify_recovered_face_geometry(f,obs['sketch_circle_m'],265)

@pytest.mark.parametrize('change',['pending','second_creator','different_failure','incomplete_payload','geometry_acceptance','event','save_attempted'])
def test_only_actual_complete_geometry_assertion_case_can_enter_recovery(original,change):
    d=deepcopy(original)
    if change=='pending':d['native_dispatch_pending']=True
    elif change=='second_creator':d['creator_call_count']=2
    elif change=='different_failure':d['issue']['locations']=[{'file':'sw_cam_raw_mill_face_feature.py','function':'other'}]
    elif change=='incomplete_payload':d['after_payload']['finish']={}
    elif change=='geometry_acceptance':d['geometry_acceptance']={}
    elif change=='event':d['messages']['event_count']=1
    else:d['save_attempted']=True
    with pytest.raises(ValueError):validate(d)
