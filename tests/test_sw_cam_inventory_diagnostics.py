"""Read-only synthetic diagnostics, progress and grouped identity contracts."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from test_sw_cam_mill_inventory import probe,native
from test_sw_cam_mill_inventory_recovery import recovery
from test_mcp_cam_mill_inventory import probe as schema_probe,MODEL,TOOL
from scripts import sw_cam_mill_inventory as cam

ISSUE=dict(code='CAM_COM_NATIVE_QI_FAILED',bridge_stage='native_query_interface',
    hresult=-2147467262,input_type='POINTER(ICWProfileSketchParam)',
    source_type='POINTER(ICWProfileSketchParam)')
class KnownError(Exception):pass

def partial_error(native,monkeypatch,**changes):
    issue=ISSUE|changes
    monkeypatch.setattr(cam,'_error',lambda exc:deepcopy(issue) if isinstance(exc,KnownError) else dict(type=type(exc).__name__,message=str(exc)))
    def decode(raw,**kw):
        if raw.id==101:
            kw['diagnostic'].update(stage='QI ICWIslandInfo',capture_complete=False,state=dict(native_id=raw.id,contours={},islands={'status':'reading'}))
            raise KnownError('observed profile item has no island interface')
        kw['diagnostic'].update(capture_complete=True,state=dict(native_id=raw.id))
        return dict(native_id=raw.id)
    native.decoder.side_effect=decode

def capture(native,**options):
    return cam.capture_mill_inventory(native.sw,'clsid','tlb','C:/part.sldprt',
        check=lambda:None,diagnostic=native.diagnostic,**options)

def test_default_known_error_remains_fail_closed(native,monkeypatch):
    partial_error(native,monkeypatch)
    with pytest.raises(KnownError):capture(native)
    assert native.decoder.call_count==1
    assert native.diagnostic['capture_complete'] is False

def test_explicit_diagnostic_preserves_error_then_reads_other_features(native,monkeypatch):
    partial_error(native,monkeypatch)
    out=capture(native,diagnostic_continue_known_island_error=True)
    assert [row['geometry']['native_id'] for row in out['features']]==[101,102]
    assert out['feature_errors'][0]['feature_native_id']==101
    assert out['feature_errors'][0]['issue']==ISSUE
    assert native.diagnostic['features'][0]['known_island_error_continued'] is True
    assert native.diagnostic['capture_complete'] is False
    assert native.diagnostic['diagnostic_enumeration_complete'] is True

@pytest.mark.parametrize('field,value',[
    ('code','OTHER'),('bridge_stage','other'),('hresult',-1),
    ('input_type','POINTER(ICWFeature)'),('source_type','POINTER(ICWFeature)')])
def test_unrecognized_error_is_never_continued(native,monkeypatch,field,value):
    partial_error(native,monkeypatch,**{field:value})
    with pytest.raises(KnownError):capture(native,diagnostic_continue_known_island_error=True)
    assert native.decoder.call_count==1

def test_diagnostic_requires_exact_island_stage(native,monkeypatch):
    partial_error(native,monkeypatch)
    original=native.decoder.side_effect
    def changed(raw,**kw):
        try:return original(raw,**kw)
        finally:kw['diagnostic']['stage']='QI ICWFeature'
    native.decoder.side_effect=changed
    with pytest.raises(KnownError):capture(native,diagnostic_continue_known_island_error=True)

def test_unknown_errors_do_not_skip_whole_features(native):
    native.decoder.side_effect=ValueError('bad contour')
    with pytest.raises(ValueError,match='bad contour'):capture(native,diagnostic_continue_known_island_error=True)
    assert native.decoder.call_count==1

def test_partial_diagnostic_is_forbidden_for_operation_reader(native):
    reader=Mock()
    with pytest.raises(ValueError,match='operation reader'):
        capture(native,diagnostic_continue_known_island_error=True,operation_reader=reader)
    reader.assert_not_called()

def test_checkpoints_include_every_feature_and_return_complete_state(native):
    seen=[]
    result=capture(native,progress=lambda diag:seen.append(deepcopy(diag)))
    assert len(result['features'])==2 and 'feature_errors' not in result
    assert len([x for x in seen if x['checkpoint']=='feature_begin'])==2
    assert len([x for x in seen if x['checkpoint']=='feature_end'])==2
    assert {'setup_begin','setup_end','stock_begin','stock_end','machine_snapshot_begin',
        'machine_snapshot_end','solidworks_reference_begin','solidworks_reference_end',
        'final_snapshot_begin','final_snapshot_end','capture_end'}<={x['checkpoint'] for x in seen}
    assert all(x['elapsed_seconds']>=0 for x in seen)
    assert seen[-1]['native_read_count']>0 and seen[-1]['native_qi_count']>0

def test_progress_write_failure_prevents_following_feature(native):
    def progress(diag):
        if diag.get('checkpoint')=='feature_end':raise OSError('checkpoint persistence failure')
    with pytest.raises(OSError):capture(native,progress=progress)
    assert native.decoder.call_count==1

def test_heartbeat_is_bounded_but_updates_between_calls(native,monkeypatch):
    ticks=iter(range(10000))
    monkeypatch.setattr(cam,'monotonic',lambda:float(next(ticks)))
    seen=[]
    capture(native,progress=lambda d:seen.append(deepcopy(d)))
    beats=[d for d in seen if d['checkpoint']=='native_read']
    assert beats and all(d['native_read_count']>=0 for d in beats)

@pytest.mark.parametrize('flag',['diagnostic_continue_known_island_error','batched_identity_checks'])
@pytest.mark.parametrize('value',[None,0,1,'true',[]])
def test_invalid_opt_ins_rejected_before_native(probe,flag,value):
    out=probe.run(**{flag:value})
    assert out['status']=='error' and probe.calls==[]

def test_diagnostic_two_captures_never_promote_partial_recovery(recovery):
    recovery.proof.summary.return_value={'saved_process_rebind_required':True}
    recovery.probe.state['feature_errors']=[dict(feature_native_id=101,issue=deepcopy(ISSUE))]
    out=recovery.run(allow_saved_process_rebind=True,diagnostic_continue_known_island_error=True,
        batched_identity_checks=True)
    assert len(recovery.probe.calls)==2 and out['diagnostic_enumeration_complete'] is True
    assert out['status']=='error'
    assert out['before']['feature_errors']==out['after']['feature_errors']
    recovery.proof.verify_inventory.assert_not_called()
    assert not any(out[k] for k in ('inventory_read_complete','readback_verified','recovery_delta_verified',
        'saved_process_rebind_verified','may_continue','mutation_attempted'))
    assert out['messages']['disconnected'] is True

@pytest.mark.parametrize('batched',[False,True])
def test_guard_frequency_and_file_hash_bound_are_explicit(probe,monkeypatch,batched):
    native_guard=Mock()
    monkeypatch.setattr(cam,'_check_capture_document',native_guard)
    original=cam.capture_mill_inventory
    def checked(*args,**kw):
        if 'batch_boundary' in kw:kw['batch_boundary']()
        for _ in range(20):kw['check']()
        if 'batch_boundary' in kw:kw['batch_boundary']()
        return original(*args,**kw)
    monkeypatch.setattr(cam,'capture_mill_inventory',checked)
    out=probe.run(batched_identity_checks=batched)
    assert out['readback_verified'],out
    assert (native_guard.call_count==0) if batched else (native_guard.call_count>=40)
    assert out['batched_identity_checks'] is batched
    assert out['identity_check_scope']==('feature_setup_phase_boundaries' if batched else 'each_native_getter')

@pytest.mark.parametrize('change',['pid','path','dirty','file','event'])
def test_batched_checks_stop_on_next_boundary(probe,monkeypatch,change):
    def capture_mutation(*args,**kw):
        kw['batch_boundary']()
        if change=='pid':probe.sw.GetProcessID=lambda:732
        elif change=='path':probe.doc['path']=str(probe.part)+'other'
        elif change=='dirty':probe.doc['needs_save']=True
        elif change=='file':probe.part.write_bytes(b'changed saved source')
        else:probe.flags['event_count']=1
        kw['batch_boundary']()
        raise AssertionError('unsafe boundary passed')
    monkeypatch.setattr(cam,'capture_mill_inventory',capture_mutation)
    out=probe.run(batched_identity_checks=True)
    assert out['status']=='error' and not out['readback_verified']
    assert 'unsafe boundary passed' not in str(out.get('issue'))

def test_opt_ins_forward_through_schema_with_strict_defaults(schema_probe):
    model=MODEL(**schema_probe.data)
    assert model.batched_identity_checks is False and model.diagnostic_continue_known_island_error is False
    model=MODEL(**(schema_probe.data|{'batched_identity_checks':True,'diagnostic_continue_known_island_error':True}))
    schema_probe.ns[TOOL](model)
    assert schema_probe.core.call_args.kwargs['batched_identity_checks'] is True
    assert schema_probe.core.call_args.kwargs['diagnostic_continue_known_island_error'] is True

@pytest.mark.parametrize('field',['batched_identity_checks','diagnostic_continue_known_island_error'])
@pytest.mark.parametrize('value',[0,1,None,'true'])
def test_schema_rejects_nonbool(schema_probe,field,value):
    with pytest.raises(ValueError):MODEL(**(schema_probe.data|{field:value}))


def test_clean_opt_in_still_requires_and_performs_two_recovery_checks(recovery):
    recovery.proof.summary.return_value={'saved_process_rebind_required':True}
    out=recovery.run(allow_saved_process_rebind=True,diagnostic_continue_known_island_error=True,batched_identity_checks=True)
    assert len(recovery.probe.calls)==2 and recovery.proof.verify_inventory.call_count==2
    assert out['status']=='review_required' and out['saved_process_rebind_verified'] is True
    assert out['inventory_read_complete'] is True and out['readback_verified'] is True


def test_batched_mode_rejects_operation_reader(probe):
    with pytest.raises(ValueError,match='zero-operation inventory'):
        cam.capture_guarded_mill_inventory(probe.sw,'clsid','tlb',str(probe.part),process_id=731,
            expected_source_sha256=cam._file_hash(probe.part),check=lambda:None,diagnostic={},
            operation_reader=lambda *args:None,batched_identity_checks=True)
