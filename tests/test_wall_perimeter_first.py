from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util,json
import pytest
S=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('perimeter_staged',S/'scripts/sw_cam_wall_perimeter_first.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
from wall_test_fixtures import failed_wall_receipt

def state(generated=False,bg=True):return dict(operation_native_id=144,feature_native_id=79,tool_native_id=273,background_over_before=bg,background_over_after=bg,generated=generated,generated_for_feature=generated,record_counts=[200] if generated else [])

@pytest.fixture
def prior():return failed_wall_receipt()

def test_prior_receipt_is_exact_no_output(prior):m.outcome.validate_failed(prior)

def test_full_capture_allows_only_perimeter_delta(prior):
    loaded=prior['loaded_context_before'];actual=deepcopy(prior['configured']);m.verify_capture(loaded,actual)
    actual['parameters']['144']['finish']['PerimeterPassType']=2
    m.verify_capture(loaded,actual,corrected=True)
    with pytest.raises(ValueError):m.verify_capture(loaded,actual)
    assert loaded['pocket_parameters']['144']['finish']['PerimeterPassType']==1

@pytest.mark.parametrize('group,key,value',[('finish','PerimeterPassType',3),('finish','BottomFinOpt',True),('finish','SideAllow',.01),('finish','MaxDepthCut',.4)])
def test_unapproved_parameter_change_rejected(prior,group,key,value):
    actual=deepcopy(prior['configured']);actual['parameters']['144']['finish']['PerimeterPassType']=2;actual['parameters']['144'][group][key]=value
    with pytest.raises(ValueError):m.verify_capture(prior['loaded_context_before'],actual,corrected=True)

@pytest.mark.parametrize('kind',['rough_records','assignment','operation_order','generated_without_stream'])
def test_protected_state_rejected(prior,kind):
    actual=deepcopy(prior['configured']);actual['parameters']['144']['finish']['PerimeterPassType']=2
    if kind=='rough_records':actual['state']['operations'][-2]['toolpath_record_counts']=[1]
    if kind=='assignment':actual['state']['operations'][-1]['assigned_tool']['native_id']=145
    if kind=='operation_order':actual['state']['operations'].reverse()
    if kind=='generated_without_stream':actual['state']['operations'][-1]['toolpath_generated']=True
    with pytest.raises(ValueError):m.verify_capture(prior['loaded_context_before'],actual,corrected=True)

@pytest.mark.parametrize('field,value',[('background_over_before',False),('background_over_after',False),('generated',True),('generated_for_feature',True),('record_counts',[10]),('tool_native_id',145)])
def test_no_output_gate_rejects_unknown_or_changed_state(field,value):
    x=state();x[field]=value
    with pytest.raises(ValueError):m.no_output(x)


def test_native_setter_scope_is_one_exact_field():
    b=object.__new__(m.NativeBackend)
    with patch.object(m.original.NativeBackend,'set_field',return_value=0) as call:
        assert b.set_field(m.SPEC,None)==0
        call.assert_called_once_with(b,m.SPEC,None)
    for candidate in (m.original.FIELDS[6],m.SPEC[:-1]+(3,)):
        with pytest.raises(ValueError):b.set_field(candidate,None)
    with pytest.raises(RuntimeError):b.assign(None)

class J:
    def __init__(self):self.report={'configuration_readback_verified':True,'initial_full_capture_verified':True,'actions':{}}
    def persist(self):pass
    def pending(self,label):
        if label in self.report['actions']:raise ValueError('repeated')
        self.report['actions'][label]={'attempted':True};self.report['phase']=label
    def returned(self,label,value):self.report['actions'][label]['value']=value

@pytest.mark.parametrize('after',[state(False),dict(state(True),generated_for_feature=False)])
def test_empty_or_unknown_post_gtp_never_saves(after):
    j=J();calls=[];statuses=iter([state(),after])
    def generate(pending):pending();calls.append('GTP');return 0
    b=SimpleNamespace(outcome=lambda:next(statuses),generate=generate,refresh_dirty=lambda:None,save=lambda:calls.append('Save'))
    with patch.object(m.wall,'run_one_existing_save',side_effect=AssertionError('save forbidden')):
        with pytest.raises(ValueError):m.generate_and_save(b,j,{})
    assert calls==['GTP'] and j.report['generation_status']==after
    assert 'SaveActiveDocument' not in j.report['actions']


def test_unknown_initial_status_does_not_capture_or_write():
    j=J();b=SimpleNamespace(outcome=lambda:dict(state(),background_over_after=False),capture_full=lambda *_:pytest.fail('capture unnecessary'),set_field=lambda *_:pytest.fail('write forbidden'))
    with pytest.raises(ValueError):m.configure(b,j,{})
    assert j.report['actions']=={}


def test_failed_setter_readback_is_retained_before_gtp():
    j=J();j.report['expected_status']=state();values=iter([1,1]);calls=[]
    def setter(spec,pending):pending();calls.append(spec);return 0
    b=SimpleNamespace(outcome=lambda:state(),capture_full=lambda _: {},field=lambda _:next(values),set_field=setter,refresh_dirty=lambda:None)
    with patch.object(m,'verify_capture'):
        with pytest.raises(ValueError):m.configure(b,j,{})
    assert calls==[m.SPEC] and j.report['actions'][m.ACTIONS[0]]['observed']==1
    assert 'GenerateToolpath' not in j.report['actions']


def test_attempt_marker_rejects_second_receipt(tmp_path):
    r=dict(source_path='C:/test.sldprt',initial_source_sha256='a'*64,failed_pin={},status_pin={},diagnosis_pin={},actions={},status='prepared',phase='prepared',model_saved=False,readback_verified=False)
    marker=tmp_path/'once.json';a=m.Journal(deepcopy(r),tmp_path/'first.json',marker);a.pending(m.ACTIONS[0])
    b=m.Journal(deepcopy(r),tmp_path/'second.json',marker)
    with pytest.raises(ValueError):b.pending(m.ACTIONS[0])
    assert json.loads(marker.read_text())['actions'][m.ACTIONS[0]]['pending'] is True


def test_stable_false_global_flag_is_telemetry_for_scoped_25d():
    assert m.no_output(state(bg=False))['background_over_before'] is False
    assert m.status_25d(state(True,False))['generated'] is True

@pytest.mark.parametrize('kind',['turning','surface','wrong_profile'])
def test_only_exact_profile_finish_scope_is_qualified(prior,kind):
    loaded=deepcopy(prior['loaded_context_before'])
    if kind=='turning': loaded['state']['current_machine']['machine_type']=3
    if kind=='surface': loaded['state']['operations'][-1]['mill_operation_type']=99
    if kind=='wrong_profile': loaded['state']['selected_profile_headers']['native_id']=80
    with pytest.raises(ValueError): m.qualify_scope(loaded)
