from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_mill_qualification as cam
from test_sw_cam_mill_qualification import probe


@pytest.fixture
def observed():
    return json.loads((Path(__file__).parent/'fixtures/mill_setup_empty_opsetup_observed.json').read_text(encoding='utf-8'))


def test_actual_saved_independent_delta_accepts_one_empty_operation_setup(observed):
    cam._verify(observed['before'],observed['after'],'setup',None,observed['direction'],64)


@pytest.mark.parametrize('counts',[[1],[0,0],[False],[0.0],[-1]])
def test_counts_other_than_one_strict_zero_rejected(observed,counts):
    after=deepcopy(observed['after']);after['operation_counts']=counts
    with pytest.raises(ValueError):cam._verify(observed['before'],after,'setup',None,observed['direction'],64)


@pytest.mark.parametrize('field',['axis','origin','feature_count','extra_setup','material','saved_file'])
def test_empty_operation_setup_never_masks_other_state_changes(observed,field):
    after=deepcopy(observed['after'])
    if field=='axis':after['feature_setups'][0]['axis_native']=[0.,1.,0.]
    if field=='origin':after['feature_setups'][0]['origin_native']=[0.,0.,1.]
    if field=='feature_count':after['feature_setups'][0]['feature_count']=1
    if field=='extra_setup':after['feature_setups'].append(deepcopy(after['feature_setups'][0]))
    if field=='material':after['material_raw']='changed'
    if field=='saved_file':after['saved_file_sha256']='0'*64
    with pytest.raises(ValueError):cam._verify(observed['before'],after,'setup',None,observed['direction'],64)


def test_existing_operation_counts_cannot_gain_extra_setup(observed):
    before=deepcopy(observed['before']);before['operation_counts']=[0]
    after=deepcopy(observed['after']);after['operation_counts']=[0,0]
    with pytest.raises(ValueError):cam._verify(before,after,'setup',None,observed['direction'],64)


def test_legacy_no_operation_setup_delta_remains_valid(observed):
    after=deepcopy(observed['after']);after['operation_counts']=[]
    cam._verify(observed['before'],after,'setup',None,observed['direction'],64)


def test_native_setup_success_accepts_zero_count_and_durable_snapshot_before_verify(probe,monkeypatch):
    probe.setup()
    probe.state['on_write']=lambda:probe.state['current'].update(operation_counts=[0])
    verifier=cam._verify;observations=[]
    def verify(before,after,*args):
        durable=json.loads(probe.receipt.read_text())
        assert durable['after']==after
        assert durable['readback_verified'] is False
        observations.append(deepcopy(durable['after']))
        verifier(before,after,*args)
    monkeypatch.setattr(cam,'_verify',verify)
    out=probe.run(operation='setup',machine_index=None,direction=[0,0,1])
    assert out['readback_verified'] and out['after']['operation_counts']==[0]
    assert len(probe.state['writes'])==1 and len(observations)==2


def test_post_mutation_failure_retains_complete_snapshot_receipt_and_never_replays(probe):
    probe.setup()
    probe.state['on_write']=lambda:probe.state['current'].update(operation_counts=[1])
    out=probe.run(operation='setup',machine_index=None,direction=[0,0,1])
    assert out['status']=='uncertain' and out['readback_verified'] is False
    assert out['after']['operation_counts']==[1]
    assert json.loads(probe.receipt.read_text())['after']==out['after']
    assert out['failed_phase']=='after_mutation_validation'
    assert probe.snapshots.call_count==3 and len(probe.state['writes'])==1
    with pytest.raises(ValueError):probe.run(operation='setup',machine_index=None,direction=[0,0,1])
    assert len(probe.state['writes'])==1


def test_durable_after_snapshot_failure_stops_further_capture(probe,monkeypatch):
    probe.setup();writer=cam._write_receipt
    def fail(path,report,**kwargs):
        if report.get('phase')=='after_mutation_validation':raise OSError('receipt unavailable')
        return writer(path,report,**kwargs)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    out=probe.run(operation='setup',machine_index=None,direction=[0,0,1])
    assert out['status']=='uncertain' and not out['readback_verified'] and 'after' in out
    assert probe.snapshots.call_count==3 and len(probe.state['writes'])==1
