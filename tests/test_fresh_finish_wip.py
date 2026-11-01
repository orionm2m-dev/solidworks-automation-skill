import importlib.util
from pathlib import Path
from copy import deepcopy
import json
import pytest
spec=importlib.util.spec_from_file_location('fresh_wip_under_test',Path(__file__).parents[1]/'scripts/sw_cam_fresh_finish_wip.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixtures():
    ids=[267,247,248,271,143,320]
    generated=[dict(operation_native_id=i,toolpath_record_counts=[n]) for i,n in zip(ids,[760,191,74,29,31196,2284])]
    state=dict(operations=[dict(native_id=r['operation_native_id'],toolpath_generated=True,toolpath_record_counts=r['toolpath_record_counts']) for r in generated],document={'type':1,'needs_save':False},saved_file_sha256='a'*64)
    loaded=dict(state=state,fresh_finish_result=dict(native_id=320,feature_native_id=79,record_counts=[2284]))
    p=dict(process_id=7,checkpoint_receipt_path=str(Path.cwd()/'parent.json'),checkpoint_receipt_sha256='b'*64)
    before=dict(mill_state=deepcopy(state),selected_operation_native_id=320,selected_feature_native_id=79,expected_toolpath_record_counts=[2284],expected_generated_operations=generated)
    cl=dict(scope='SAVED_FRESH_FINISH_CL_EXPORT_V1',status='review_required',phase='finished',native_dispatch_pending=False,process_id=7,saved_checkpoint_pin=dict(path=p['checkpoint_receipt_path'],sha256='b'*64),before=before,after=deepcopy(before),protected_stream_association=dict(prior_five_complete_streams_unchanged=True,added_block=5,added_operation_native_id=320,unchanged=[dict(native_id=i,old_block=n,new_block=n) for n,i in enumerate(ids[:5])]))
    for k in ('native_call_returned','readback_verified','output_verified','phase_proofs_verified_after_export','protected_streams_verified','checkpoint_export_readback_verified'):cl[k]=True
    for k in ('model_saved','GTP_attempted','GOP_attempted','AFR_attempted','simulation_attempted','stock_edit_attempted','tool_edit_attempted','setter_attempted','assignment_attempted','automatic_replay'):cl[k]=False
    return cl,loaded,p,generated


def test_completed_CL_binds_exact_saved_state():
    cl,loaded,p,expected=fixtures();assert m.validate_CL(cl,loaded,p)==expected


@pytest.mark.parametrize('key,value',[('phase','pending'),('readback_verified',False),('native_dispatch_pending',True),('GTP_attempted',True),('process_id',8),('issue',{'error':'uncertain'})])
def test_invalid_CL_refused(key,value):
    cl,loaded,p,_=fixtures();cl[key]=value
    with pytest.raises(ValueError):m.validate_CL(cl,loaded,p)


@pytest.mark.parametrize('field',['state','parent','association','order'])
def test_wrong_CL_proof_refused(field):
    cl,loaded,p,_=fixtures()
    if field=='state':cl['before']['mill_state']['saved_file_sha256']='c'*64
    if field=='parent':cl['saved_checkpoint_pin']['sha256']='c'*64
    if field=='association':cl['protected_stream_association']['added_operation_native_id']=144
    if field=='order':cl['before']['expected_generated_operations'].reverse()
    with pytest.raises(ValueError):m.validate_CL(cl,loaded,p)


def baseline():
    _,_,_,generated=fixtures();before={'saved_file_sha256':'d'*64}
    r=dict(scope='SAVED_ROUGH_POCKET_WIP_EXPORT_V1',status='review_required',phase='finished',native_call_count=1,native_scope='all_wip_parts_all_setups',single_operation_scope_claimed=False,export_quality_raw=0,expected_generated_operations=deepcopy(generated[:5]),before=before,after=deepcopy(before),source_sha256='d'*64,saved_checkpoint_pin={'sha256':'e'*64},files=[dict(sha256='f'*64,bytes=84,stl_extension=True)])
    for k in ('readback_verified','export_files_verified','checkpoint_export_readback_verified','phase_proofs_verified_after_export'):r[k]=True
    for k in ('GTP_attempted','GOP_attempted','model_saved','setter_attempted','assignment_attempted','automatic_replay'):r[k]=False
    prior=dict(before={'mill_state':{'saved_file_sha256':'d'*64}},saved_checkpoint_pin={'sha256':'e'*64})
    return r,prior,dict(sha256='f'*64,bytes=84),generated


def test_baseline_bound_to_same_prior_source_and_checkpoint():m.validate_baseline(*baseline())


@pytest.mark.parametrize('changed',['source','checkpoint','stl','counts','quality'])
def test_wrong_baseline_refused(changed):
    r,prior,wip,expected=baseline()
    if changed=='source':prior['before']['mill_state']['saved_file_sha256']='0'*64
    if changed=='checkpoint':prior['saved_checkpoint_pin']['sha256']='0'*64
    if changed=='stl':wip['sha256']='0'*64
    if changed=='counts':r['expected_generated_operations'][0]['toolpath_record_counts']=[1]
    if changed=='quality':r['export_quality_raw']=1
    with pytest.raises(ValueError):m.validate_baseline(r,prior,wip,expected)


def test_scope_retirement_preserves_offline_proofs(tmp_path):
    names=['sw_cam_fresh_finish_recipe.py','sw_cam_fresh_finish_field_batch.py','sw_cam_chamfer_insert_defaults.py','sw_cam_finish_defaults_progress.py']
    pins=[dict(path=str(tmp_path/n),sha256='a'*64) for n in names]
    loaded=dict(pins=pins+[dict(path=str(tmp_path/'read.py'),sha256='b'*64)],offline_export_proof_pins=[])
    assert m.scope_pins(loaded,[])==pins and len(loaded['pins'])==1 and loaded['offline_export_proof_pins']==pins


def test_real_read_guard_refuses65_and_accepts64(tmp_path):
    pins=[]
    for i in range(65):
        f=tmp_path/(str(i)+'.txt');f.write_text('test');pins.append(dict(path=str(f),sha256=m._file_hash(f)))
    kw=dict(generated_pin=pins[0],progress=lambda *a:None,process_id=7,expected_document=dict(path=pins[0]['path'],title='part',type=1,needs_save=False),source_sha256=pins[0]['sha256'],verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None,retained_objects=(object(),),verify_retained_binding=lambda:None,max_native_calls=400)
    assert not m.lengths.ReadBatch(object(),'unused',evidence_pins=pins[:64],**kw)._entered
    with pytest.raises(ValueError):m.lengths.ReadBatch(object(),'unused',evidence_pins=pins,**kw)


def setup_run(tmp_path,monkeypatch,*,native_return=True,drift=False,empty=False,fail_before=False):
    directory=tmp_path/'output';receipt=tmp_path/'result.json';marker=tmp_path/'once.json';doc={'path':str(tmp_path/'part.SLDPRT'),'type':1,'needs_save':False};trace=[]
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,o,n,*a):return 1 if n in ('GetDocType','MachType') else object()
        def typed(self,o,n):return o
        def dispatch_once(self,call,*,persist_pending):persist_pending();return call()
        def summary(self):return {'dispatch_returned':True}
    class Ctx:
        app=object()
        def guard(self):return Guard()
        def identity(self):return doc
    class Backend:
        ctx=Ctx();session=None;session_active=False
        def __init__(self,*a):pass
        def start(self):trace.append('start')
        def finish(self):trace.append('finish')
        def close(self):trace.append('close')
    def capture(*a):
        label=a[5] if len(a)>5 else None
        trace.append('capture')
        if fail_before:raise ValueError('before inventory failed')
        return {'state':1 if not drift or trace.count('capture')==1 else 2},{'machine':object()}
    def member(obj,name,*args):
        assert name=='CreateSTLOfWIPs2';trace.append(name)
        assert args== (str(directory)+'\\','wip.stl','',0,0)
        if not empty:(directory/'wip.stl').write_bytes(b'x'*84)
        return native_return
    monkeypatch.setattr(m.group,'NativeBackend',Backend);monkeypatch.setattr(m,'capture_compact',capture);monkeypatch.setattr(m,'_member',member);monkeypatch.setattr(m.common,'_check',lambda x:None)
    p=dict(process_id=7,expected_document_path=doc['path'],expected_source_sha256='a'*64,operation_native_id=320,feature_native_id=79,receipt_path=str(receipt))
    loaded=dict(state={'document':doc},parent_pin={'sha256':'b'*64},pins=[],offline_export_proof_pins=[],bootstrap_export_pins=[])
    plan=dict(loaded=loaded,directory=directory,canonical=directory.resolve(),CL_pin={},baseline_wip_pin={},baseline_receipt_pin={},expected_generated_operations=[],retired=[],marker=marker,registration={'clsid':'test'},typelib_path='unused')
    return lambda:m.run(object(),p,plan),trace,marker


def test_one_export_only_with_before_after_source_proof(tmp_path,monkeypatch):
    call,trace,marker=setup_run(tmp_path,monkeypatch);r=call()
    assert r['status']=='review_required' and r['readback_verified'] and r['export_files_verified'] and marker.exists()
    assert trace==['start','capture','CreateSTLOfWIPs2','capture','finish','close']
    assert r['native_call_count']==1 and r['model_saved'] is False and r['GTP_attempted'] is False and r['geometry_acceptance_complete'] is False


@pytest.mark.parametrize('bad',[False,0,1,None])
def test_nontrue_native_return_never_runs_after_capture(tmp_path,monkeypatch,bad):
    call,trace,marker=setup_run(tmp_path,monkeypatch,native_return=bad);r=call()
    assert r['status']=='uncertain' and not r['readback_verified'] and trace.count('capture')==1 and marker.exists()


def test_before_failure_prevents_export(tmp_path,monkeypatch):
    call,trace,marker=setup_run(tmp_path,monkeypatch,fail_before=True);r=call()
    assert r['status']=='error' and 'CreateSTLOfWIPs2' not in trace and not marker.exists()


def test_changed_readback_refuses_success(tmp_path,monkeypatch):
    call,trace,_=setup_run(tmp_path,monkeypatch,drift=True);r=call();assert not r['readback_verified'] and trace.count('CreateSTLOfWIPs2')==1


def test_empty_export_cannot_succeed(tmp_path,monkeypatch):
    call,trace,_=setup_run(tmp_path,monkeypatch,empty=True);r=call();assert not r['readback_verified'] and trace.count('capture')==1


def test_existing_once_marker_prevents_native_call(tmp_path,monkeypatch):
    call,trace,marker=setup_run(tmp_path,monkeypatch);marker.write_text('{}');r=call()
    assert not r['readback_verified'] and 'CreateSTLOfWIPs2' not in trace
