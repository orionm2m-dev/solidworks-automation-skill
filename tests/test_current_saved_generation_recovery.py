"""Completed recovery loader checks; pure history validation is shared with recovery."""
from copy import deepcopy
import json
import pytest
from scripts import sw_cam_current_saved_generation as g
from scripts import sw_cam_current_generation_native as native
from scripts import sw_cam_current_saved_parameter_batch as batch
from scripts import sw_cam_current_parameter_recovery_evidence as history
from test_current_saved_generation_authority import authority,load,save


def recovery(tmp_path,monkeypatch):
    d=authority(tmp_path)
    d['binding']['expected_source_sha256']='b'*64
    d['request_pin']['sha256']=g._digest(d['binding'])
    d.update(action='recover_save',recovery_mode='recover_save',recovery_verified=True,setters_replayed=False,source_before_sha256='b'*64)
    expected=deepcopy(d['saved']);expected['document']['needs_save']=True
    for key in ('before','confirm_before','after','confirm_after'):d[key]=deepcopy(expected)
    records=dict(partial=dict(source_before_sha256='b'*64),old_marker={},original_request={},original_prepare={})
    d['recovery_pins']={}
    for key,record in records.items():
        p=save(tmp_path/(key+'.json'),record)
        d['recovery_pins'][key]=g.read_pin(p['path'],p['sha256'])[1]
    d['original_action_receipt_pin']=deepcopy(d['recovery_pins']['partial'])
    d['historical_before']={'historical':True}
    d['actions']=[dict(kind='SaveActiveDocument',operation_native_id=None,change=None,attempted=True,returned=True,native_dispatch_pending=False,readback_verified=True,return_type='int',return_value=0)]
    data=dict(plan=deepcopy(d['recipe']),pins=deepcopy(d['qualified_read_pins']),baseline={'baseline':True})
    calls=[]
    def inputs(binding):
        assert binding==d['binding'];calls.append('original_inputs');return deepcopy(data)
    def validate(partial,prepare,request,marker,*,base_binding,plan,baseline,pins):
        assert (partial,prepare,request,marker)==tuple(records[k] for k in ('partial','original_prepare','original_request','old_marker'))
        assert base_binding==d['binding'] and plan==data['plan'] and baseline==data['baseline'] and pins==d['recovery_pins']
        calls.append('complete_history')
        return dict(expected_state=deepcopy(expected),historical_before={'historical':True},original_action_receipt_pin=deepcopy(pins['partial']),recovery_pins=deepcopy(pins))
    monkeypatch.setattr(batch,'load_inputs',inputs);monkeypatch.setattr(history,'validate_history',validate)
    return d,calls


def test_completed_explicit_recovery_keeps_history_pins(tmp_path,monkeypatch):
    d,calls=recovery(tmp_path,monkeypatch);out=load(tmp_path,d)
    assert calls==['original_inputs','complete_history'] and out['recovery_pins']==d['recovery_pins']
    assert out['receipt']['action']=='recover_save' and out['state']==d['saved']


@pytest.mark.parametrize('change',[
 lambda d:d.update(action='prepare_recover_save'),
 lambda d:d.update(action='apply'),
 lambda d:d.update(recovery_verified=False),
 lambda d:d.update(setters_replayed=True),
 lambda d:d.update(recovery_mode='apply'),
 lambda d:d.update(source_before_sha256='c'*64),
 lambda d:d['actions'].append(deepcopy(d['actions'][0])),
 lambda d:d['actions'][0].update(kind='SetTool'),
 lambda d:d['actions'][0].update(return_value=True),
 lambda d:d['actions'][0].update(native_dispatch_pending=True),
 lambda d:d['confirm_after']['document'].update(needs_save=False),
 lambda d:d.update(historical_before={}),
 lambda d:d.update(original_action_receipt_pin={}),
 lambda d:d['recovery_pins'].pop('old_marker'),
 lambda d:d['recovery_pins']['old_marker'].update(bytes=999),
])
def test_partial_relabelled_or_changed_recovery_rejected(tmp_path,monkeypatch,change):
    d,_=recovery(tmp_path,monkeypatch);change(d)
    with pytest.raises(ValueError):load(tmp_path,d)


def test_shared_history_failure_never_becomes_authority(tmp_path,monkeypatch):
    d,_=recovery(tmp_path,monkeypatch)
    def reject(*a,**k):raise ValueError('Partial setter outcome is not complete')
    monkeypatch.setattr(history,'validate_history',reject)
    with pytest.raises(ValueError,match='setter outcome'):load(tmp_path,d)


def test_recovery_history_file_drift_is_rejected(tmp_path,monkeypatch):
    d,_=recovery(tmp_path,monkeypatch)
    from pathlib import Path
    Path(d['recovery_pins']['partial']['path']).write_text('{}')
    with pytest.raises(ValueError):load(tmp_path,d)


def test_recovery_saved_delta_must_preserve_other_fields(tmp_path,monkeypatch):
    d,_=recovery(tmp_path,monkeypatch)
    for key in ('saved','confirm_saved'):d[key]['operations'][0]['name']='unexpected'
    with pytest.raises(ValueError,match='Save changed'):load(tmp_path,d)


def test_native_boundary_rechecks_immutable_recovery_file(tmp_path,monkeypatch):
    d,_=recovery(tmp_path,monkeypatch);loaded=load(tmp_path,d)
    ctx=native.NativeGenerationContext.__new__(native.NativeGenerationContext);ctx.loaded=loaded
    monkeypatch.setattr(batch.NativeBatchContext,'verify_files',lambda self:None)
    ctx.verify_files()
    from pathlib import Path
    Path(loaded['recovery_pins']['old_marker']['path']).write_text('{"changed":true}')
    with pytest.raises(ValueError):ctx.verify_files()


def test_scope_guard_receives_all_recovery_pins(tmp_path,monkeypatch):
    d,_=recovery(tmp_path,monkeypatch);loaded=load(tmp_path,d)
    ctx=native.NativeGenerationContext.__new__(native.NativeGenerationContext)
    ctx.loaded=loaded;ctx.data={'pins':loaded['pins']};ctx.v={'process_id':123};ctx.source='a'*64;ctx.sw=None;ctx.tlb=None
    ctx.boundary=lambda:{'needs_save':False};ctx.check=lambda:None
    monkeypatch.setattr(native,'ScopedCamDispatchGuard',lambda *a,**k:k)
    pins=ctx.guard()['evidence_pins']
    assert pins==list(loaded['pins'].values())+[loaded['pin']]+list(loaded['recovery_pins'].values())
