"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,sys
import pytest
from scripts import sw_cam_raw_mill_face_move as m


@pytest.fixture
def before():
    from cam_face_test_fixtures import state
    return state(21,True)

def moved(before,flag=False):
    a=deepcopy(before);rows={r['native_id']:r for r in a['operations']}
    a['operations']=[rows[i] for i in m.AFTER_ORDER]
    for i,row in enumerate(a['operations']):row['operation_index']=i
    a['document']['needs_save']=flag
    return a

@pytest.mark.parametrize('flag',[False,True])
def test_only_existing_reorder_and_observed_bool_flag(before,flag):
    a=moved(before,flag);raw=deepcopy(a);diag={}
    delta=m.verify_move_delta(before,a,diagnostic=diag)
    assert delta['raw_SW_save_flag_after'] is flag and delta['make_copy'] is False
    assert a==raw and before['document']['needs_save'] is False
    assert [r['native_id'] for r in a['operations']]==[143,144,195,196,267,247,248]

@pytest.mark.parametrize('change',[
 lambda a:a['operations'][4].update(native_id=268),
 lambda a:a['operations'][4].update(operation_index=6),
 lambda a:a['operations'][4].update(setup_native_id=94),
 lambda a:a['operations'][4].update(linked_feature_ids=[264]),
 lambda a:a['operations'][4].update(toolpath_generated=True),
 lambda a:a['operations'][4]['assigned_tool'].update(native_id=249),
 lambda a:a['operations'][5].update(toolpath_record_counts=[192]),
 lambda a:a['operations'][6]['assigned_tool'].update(protrusion_native=24),
 lambda a:a['features'][-1]['geometry'].update(depth_native=1.5),
 lambda a:a['document'].update(needs_save=0),
 lambda a:a.update(saved_file_sha256='0'*64),
 lambda a:a['operation_counts'].__setitem__(1,1),
 lambda a:a['sw_reference']['solids'][0]['mass_raw'].__setitem__(0,1.0),
])
def test_other_mutations_rejected(before,change):
    a=moved(before);original=deepcopy(a);change(a);assert m._digest(a)!=m._digest(original)
    with pytest.raises(ValueError):m.verify_move_delta(before,a)

def test_unchanged_append_is_not_a_successful_move(before):
    with pytest.raises(ValueError):m.verify_move_delta(before,deepcopy(before))

def test_stable_marker_and_distinct_source_lineage(tmp_path):
    source=tmp_path/'part.sldprt'
    marker=m.move_marker(source,'a'*64,'b'*64)
    assert marker==m.move_marker(source.parent/'.'/source.name,'a'*64,'b'*64)
    assert marker!=m.move_marker(source,'a'*64,'c'*64)
    assert marker!=m.move_marker(source,'c'*64,'b'*64)

def guard_fixture():return dict(pins=[],predecessor_validation=dict(original_live_pins=[],original_history_pins=[]))

def test_existing_attempt_never_replayed(tmp_path):
    marker=tmp_path/'marker.json';marker.write_bytes(b'uncertain previous attempt')
    output=tmp_path/'fresh.json'
    with pytest.raises(ValueError):m._fresh_output(guard_fixture(),str(output),marker,str(tmp_path/'part.sldprt'))
    assert marker.read_bytes()==b'uncertain previous attempt' and not output.exists()

def test_existing_receipt_preserved(tmp_path):
    output=tmp_path/'receipt.json';output.write_bytes(b'previous evidence')
    with pytest.raises(ValueError):m._fresh_output(guard_fixture(),str(output),tmp_path/'newmarker.json',str(tmp_path/'part.sldprt'))
    assert output.read_bytes()==b'previous evidence'

def test_native_hresult_zero_only():assert m.require_move_return(0) is None

@pytest.mark.parametrize('value',[False,True,None,1,-1,0.0,'None',[],{},object()])
def test_nonzero_or_wrong_type_native_return_is_uncertain(value):
    with pytest.raises(ValueError):m.require_move_return(value)

@pytest.mark.parametrize('value',[0,1,-1,None,True,False,1.5,'diagnostic'])
def test_raw_return_observation_keeps_exact_primitive_before_validation(value):
    observed=m.native_return_observation(value)
    assert observed['native_return_type']==type(value).__name__
    assert observed['native_return_value_recorded'] is True
    assert type(observed['native_return_value']) is type(value) and observed['native_return_value']==value
    assert observed['native_return_limit_reason']==''
    json.dumps(observed,allow_nan=False)

@pytest.mark.parametrize('value',[float('nan'),float('inf'),2**63,-2**63-1,'x'*257,object()])
def test_unbounded_return_is_diagnosed_without_unsafe_serialization(value):
    observed=m.native_return_observation(value)
    assert observed['native_return_value_recorded'] is False and observed['native_return_value'] is None
    assert observed['native_return_limit_reason']=='unsupported_or_unbounded_native_value'
    json.dumps(observed,allow_nan=False)
