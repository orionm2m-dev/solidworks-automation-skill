from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest

from scripts import sw_owned_process_recovery as m

class FakeAPI:
    def __init__(self,identity): self.value=identity; self.calls=[]; self.fail=None; self.wait_result=True; self.after_identity=None
    def open(self,pid,*,terminate=False):
        self.calls.append(('open',pid,terminate))
        if self.fail=='open': raise OSError('denied')
        return 'owned-handle'
    def identity(self,handle):
        self.calls.append(('identity',handle))
        if self.fail=='identity': raise OSError('identity failed')
        result=deepcopy(self.value)
        if self.after_identity: self.after_identity(self)
        return result
    def terminate(self,handle):
        self.calls.append(('terminate',handle))
        if self.fail=='terminate': raise OSError('denied')
    def wait(self,handle,ms):
        self.calls.append(('wait',handle,ms))
        if self.fail=='wait': raise OSError('failed')
        return self.wait_result
    def close(self,handle):
        self.calls.append(('close',handle))
        if self.fail=='close': raise OSError('close failed')

@pytest.fixture
def case(tmp_path):
    pid=123; exe=r'C:\Vendor\SOLIDWORKS\SLDWORKS.exe'
    iso='2026-10-26T08:52:37.4011237+05:00'; ticks=m._filetime_from_iso(iso)
    def pin(name,data):
        p=tmp_path/name; p.write_text(json.dumps(data),encoding='utf-8')
        return {'path':str(p),'sha256':m._hash_file(p)}
    checkpoint=tmp_path/'checkpoint.SLDPRT'; checkpoint.write_bytes(b'proven checkpoint')
    sha=m._hash_file(checkpoint)
    save={'native_save_call_returned':True,'save_readback_verified':True,
          'after':{'document':{'path':str(checkpoint),'needs_save':False},'saved_file_sha256':sha}}
    save_ref=pin('save.json',save)
    source_ref=pin('unsaved_gop.json',{'status':'ok','operations':9,'generation_attempted':False})
    manifest={'process_id':pid,'complete_known_document_inventory':True,'no_other_unsaved_work_known':True,
       'documents':[{'path':str(checkpoint),'sha256':sha,'saved_evidence':save_ref}],
       'known_unsaved_items':[{'id':'gop-definitions','document_path':str(checkpoint),
                              'description':'Nine unsaved definitions; no generated paths','evidence':[source_ref]}]}
    owned={'status':'ok','phase':'connected','launch_mode':'executable','launch_attempted':True,'new_process_verified':True,
       'process_id':pid,'executable':exe,'known_process_ids_before':[1,2,777],
       'launch_intent_time':1792986757.383633,
       'process_identity':{'process_id':pid,'executable':exe,'create_time':1792986757.401,'alive':True}}
    observed={'process':{'Id':pid,'Path':exe,'StartTime':iso}}
    request={'process_id':pid,'expected_executable_path':exe,'expected_creation_filetime':ticks,
             'ownership_receipt':pin('startup.json',owned),
             'process_identity_evidence':pin('identity.json',observed),
             'recovery_manifest':pin('manifest.json',manifest)}
    api=FakeAPI({'process_id':pid,'executable':exe,'creation_filetime':ticks,'alive':True})
    def run(action='prepare',**kw):
        return m.recover_owned_process(action=action,spec=request,_api=api,_lock_factory=lambda pid:nullcontext(),**kw)
    def change(key,data): request[key]=pin({'ownership_receipt':'startup.json','process_identity_evidence':'identity.json','recovery_manifest':'manifest.json'}[key],data)
    def apply(**kw):
        prepared=run(); args={'expected_state_sha256':prepared.get('state_sha256','0'*64),
            'acknowledge_terminate_owned_process':True,'acknowledged_discard_ids':['gop-definitions'],
            'receipt_path':str(tmp_path/'termination.json')}; args.update(kw)
        return run('apply',**args)
    return locals()

@pytest.mark.parametrize('action',['inspect','prepare'])
def test_readonly(case,action):
    before={p.name for p in case['tmp_path'].iterdir()}; r=case['run'](action)
    assert r['status']=='ok' and r['apply_eligible'] and not r['termination_attempted']
    assert case['api'].calls[0]==('open',123,False)
    assert not any(c[0]=='terminate' for c in case['api'].calls)
    assert {p.name for p in case['tmp_path'].iterdir()}==before

def test_apply_one_verified_handle(case):
    r=case['apply'](); calls=case['api'].calls
    assert r['status']=='ok' and r['process_exit_verified'] and r['termination_returned']
    assert calls.count(('terminate','owned-handle'))==1
    assert all(c[1]=='owned-handle' for c in calls if c[0] in ('identity','terminate','wait','close'))
    assert json.loads((case['tmp_path']/'termination.json').read_text())['process_exit_verified']
    assert r['COM_calls']==r['UI_calls']==0 and not r['restart_attempted']

@pytest.mark.parametrize('field,value',[
 ('status','error'),('phase','launch_intent'),('launch_mode','rot'),('launch_attempted',False),
 ('new_process_verified',False),('process_id',777),('known_process_ids_before',[123]),
 ('known_process_ids_before',None),('executable',r'C:\Wrong\SLDWORKS.exe'),('launch_intent_time',0)])
def test_ownership_refuses(case,field,value):
    owned=case['owned']; owned[field]=value; case['change']('ownership_receipt',owned)
    r=case['apply'](); assert r['status']=='blocked'; assert not case['api'].calls

@pytest.mark.parametrize('field,value',[('process_id',777),('executable',r'C:\Other\SLDWORKS.exe'),('create_time',1792986757.4)])
def test_startup_identity_refuses(case,field,value):
    case['owned']['process_identity'][field]=value; case['change']('ownership_receipt',case['owned'])
    assert case['apply']()['status']=='blocked' and not case['api'].calls

@pytest.mark.parametrize('field,value',[('Id',777),('Path',r'C:\Other\SLDWORKS.exe'),
 ('StartTime','2026-10-26T08:52:37.4011238+05:00'),('StartTime','2026-10-26T08:52:37.401+05:00')])
def test_exact_os_record(case,field,value):
    case['observed']['process'][field]=value; case['change']('process_identity_evidence',case['observed'])
    assert case['apply']()['status']=='blocked' and not case['api'].calls

@pytest.mark.parametrize('field,value',[('process_id',777),('executable',r'C:\Other\SLDWORKS.exe'),
 ('creation_filetime',1),('alive',False)])
def test_same_pid_reused_or_wrong_live_identity(case,field,value):
    case['api'].value[field]=value; r=case['apply']()
    assert r['status']=='blocked' and not any(c[0]=='terminate' for c in case['api'].calls)
    assert case['api'].calls[-1][0]=='close'

@pytest.mark.parametrize('field,value',[('complete_known_document_inventory',False),('no_other_unsaved_work_known',False),
 ('process_id',777),('documents',[]),('known_unsaved_items',[])])
def test_incomplete_inventory(case,field,value):
    case['manifest'][field]=value; case['change']('recovery_manifest',case['manifest'])
    assert case['apply']()['status']=='blocked' and not case['api'].calls

@pytest.mark.parametrize('change',['duplicate_document','duplicate_item','unknown_document','no_evidence','bad_id','empty_description'])
def test_discard_manifest(case,change):
    v=case['manifest']; item=v['known_unsaved_items'][0]
    if change=='duplicate_document': v['documents'].append(v['documents'][0])
    elif change=='duplicate_item': v['known_unsaved_items'].append(item)
    elif change=='unknown_document': item['document_path']=str(case['tmp_path']/'other.SLDPRT')
    elif change=='no_evidence': item['evidence']=[]
    elif change=='bad_id': item['id']='.. slash /'
    elif change=='empty_description': item['description']=''
    case['change']('recovery_manifest',v)
    assert case['apply']()['status']=='blocked' and not case['api'].calls

@pytest.mark.parametrize('change',['save_returned','save_verified','dirty','path','sha'])
def test_checkpoint_evidence(case,change):
    s=case['save']
    if change=='save_returned': s['native_save_call_returned']=False
    elif change=='save_verified': s['save_readback_verified']=False
    elif change=='dirty': s['after']['document']['needs_save']=True
    elif change=='path': s['after']['document']['path']=str(case['tmp_path']/'other.SLDPRT')
    else: s['after']['saved_file_sha256']='f'*64
    case['manifest']['documents'][0]['saved_evidence']=case['pin']('save.json',s)
    case['change']('recovery_manifest',case['manifest'])
    assert case['apply']()['status']=='blocked' and not case['api'].calls

@pytest.mark.parametrize('field,value',[('acknowledge_terminate_owned_process',False),('acknowledged_discard_ids',[]),
 ('acknowledged_discard_ids',['gop-definitions','unknown']),('acknowledged_discard_ids',['gop-definitions','gop-definitions']),
 ('expected_state_sha256','0'*64),('wait_milliseconds',10001),('receipt_path','relative.json')])
def test_apply_ack_and_state_gates(case,field,value):
    r=case['apply'](**{field:value}); assert r['status']=='blocked'
    assert not any(c[0]=='terminate' for c in case['api'].calls)

def test_new_receipt_no_replay(case):
    assert case['apply']()['status']=='ok'
    before=len(case['api'].calls); assert case['apply']()['status']=='blocked'
    assert not any(c[0]=='terminate' for c in case['api'].calls[before:])

def test_file_changed_after_prepare(case):
    prepared=case['run'](); case['checkpoint'].write_bytes(b'changed')
    r=case['run']('apply',expected_state_sha256=prepared['state_sha256'],acknowledge_terminate_owned_process=True,
       acknowledged_discard_ids=['gop-definitions'],receipt_path=str(case['tmp_path']/'new.json'))
    assert r['status']=='blocked' and not any(c[0]=='terminate' for c in case['api'].calls)

def test_change_after_intent_refuses(case):
    state=case['run']()['state_sha256']; count=[0]
    def race(api):
        count[0]+=1
        if count[0]==2: case['checkpoint'].write_bytes(b'race')
    case['api'].after_identity=race
    r=case['run']('apply',expected_state_sha256=state,acknowledge_terminate_owned_process=True,
       acknowledged_discard_ids=['gop-definitions'],receipt_path=str(case['tmp_path']/'new.json'))
    assert r['status']=='blocked' and not any(c[0]=='terminate' for c in case['api'].calls)
    assert (case['tmp_path']/'new.json').exists()

@pytest.mark.parametrize('failure',['open','identity','terminate','wait','close'])
def test_os_errors_bounded(case,failure):
    state=case['run']()['state_sha256']; case['api'].fail=failure
    r=case['run']('apply',expected_state_sha256=state,acknowledge_terminate_owned_process=True,
       acknowledged_discard_ids=['gop-definitions'],receipt_path=str(case['tmp_path']/'new.json'))
    assert r['status'] in ('blocked','review_required')
    assert len([c for c in case['api'].calls if c[0]=='terminate'])<=1

def test_timeout_no_retry_restart(case):
    case['api'].wait_result=False; r=case['apply']()
    assert r['status']=='review_required' and not r['process_exit_verified'] and not r['restart_attempted']
    assert len([c for c in case['api'].calls if c[0]=='terminate'])==1

def test_receipt_initial_write_failure_prevents_kill(case,monkeypatch):
    monkeypatch.setattr(m,'_write',lambda *a,**kw:(_ for _ in ()).throw(OSError('disk full')))
    r=case['apply'](); assert not any(c[0]=='terminate' for c in case['api'].calls)
    assert r['status']=='blocked'

def test_final_receipt_failure_structured(case,monkeypatch):
    orig=m._write
    def write(path,report,**kw):
        if report['process_exit_verified']: raise OSError('disk full at final')
        return orig(path,report,**kw)
    monkeypatch.setattr(m,'_write',write); r=case['apply']()
    assert r['status']=='review_required' and r['process_exit_verified'] and 'receipt_finalize_error' in r

def test_exact_creation_ticks():
    assert m._filetime_from_iso('2026-10-26T08:52:37.4011237+05:00')==int('1DD64FD70DCE565',16)

def test_no_import_side_effects(monkeypatch):
    def forbidden(*a,**kw): raise AssertionError('live API called')
    monkeypatch.setattr(m,'Win32ProcessAPI',forbidden)
    assert m.recover_owned_process(action='apply',spec={})['status']=='blocked'

def test_post_exit_checkpoint_change_review_required(case):
    old_wait=case['api'].wait
    def wait(handle,ms):
        result=old_wait(handle,ms); case['checkpoint'].write_bytes(b'changed after termination'); return result
    case['api'].wait=wait
    r=case['apply']()
    assert r['status']=='review_required' and r['process_exit_verified'] and r['saved_files_preserved'] is None
    assert len([c for c in case['api'].calls if c[0]=='terminate'])==1

def test_durable_intent_not_api_entry_claim(case,monkeypatch):
    old_terminate=case['api'].terminate
    def terminate(handle):
        durable=json.loads((case['tmp_path']/'termination.json').read_text())
        assert durable['termination_intent_recorded'] is True
        assert durable['termination_attempted'] is False and durable['termination_returned'] is False
        return old_terminate(handle)
    case['api'].terminate=terminate
    r=case['apply'](); assert r['status']=='ok' and r['saved_files_preserved'] is True

def test_pre_api_intent_write_failure_no_attempt(case,monkeypatch):
    orig=m._write
    def write(path,report,**kw):
        if report['phase']=='before_terminate': raise OSError('intent flush failed')
        return orig(path,report,**kw)
    monkeypatch.setattr(m,'_write',write)
    r=case['apply']()
    assert r['termination_attempted'] is False and r['status']=='review_required' and 'receipt_finalize_error' in r
    assert not any(c[0]=='terminate' for c in case['api'].calls)

def install_clean(case, *, batch=True):
    payload={'status':'ok','process_id':case['pid'],'mutation_attempted':False,
        'document_count':1,'documents':[{'path':str(case['checkpoint']),'needs_save':False,'type':1}],
        'active_document':{'path':str(case['checkpoint']),'type':1}}
    def publish(value=None):
        value=deepcopy(payload if value is None else value)
        if batch:
            text=json.dumps(value)
            value={'status':'success','request_count':1,'results':[{'name':'solidworks_inspect_open_documents',
                'result':{'isError':False,'content':[{'type':'text','text':text,'parsed_json':deepcopy(value)}],
                          'structuredContent':{'result':text}}}]}
        case['manifest'].update(known_unsaved_items=[],clean_inventory_is_last_known=True,
            no_known_unsaved_changes_since_inventory=True,
            clean_inventory_evidence=case['pin']('clean_inventory.json',value))
        case['change']('recovery_manifest',case['manifest'])
        return value
    publish()
    return payload,publish


@pytest.mark.parametrize('batch',[False,True])
def test_empty_unsaved_list_requires_and_accepts_clean_native_proof(case,batch):
    install_clean(case,batch=batch)
    result=case['apply'](acknowledged_discard_ids=[])
    assert result['status']=='ok' and result['saved_files_preserved'] is True
    assert result['evidence']['discard_ids']==[]
    assert result['evidence']['clean_inventory']['last_known_clean'] is True
    assert result['evidence']['clean_inventory']['live_document_state_verified'] is False
    assert case['api'].calls.count(('terminate','owned-handle'))==1


@pytest.mark.parametrize('field,value',[
    ('clean_inventory_is_last_known',None),('clean_inventory_is_last_known',1),
    ('no_known_unsaved_changes_since_inventory',False),
    ('clean_inventory_evidence',None)])
def test_empty_list_without_explicit_clean_proof_never_opens_process(case,field,value):
    install_clean(case)
    case['manifest'][field]=value;case['change']('recovery_manifest',case['manifest'])
    assert case['apply'](acknowledged_discard_ids=[])['status']=='blocked'
    assert case['api'].calls==[]


@pytest.mark.parametrize('change',[
    'pid','pid_float','count','count_bool','count_float','dirty','missing_dirty','dirty_zero',
    'type_bool','type_float','unknown_path','duplicate','mutating','mutation_zero','failed',
    'empty','active_unknown'])
def test_malformed_or_dirty_clean_inventory_refuses(case,change):
    payload,publish=install_clean(case)
    if change=='pid':payload['process_id']=456
    elif change=='pid_float':payload['process_id']=float(case['pid'])
    elif change=='count':payload['document_count']=2
    elif change=='count_bool':payload['document_count']=True
    elif change=='count_float':payload['document_count']=1.0
    elif change=='dirty':payload['documents'][0]['needs_save']=True
    elif change=='missing_dirty':del payload['documents'][0]['needs_save']
    elif change=='dirty_zero':payload['documents'][0]['needs_save']=0
    elif change=='type_bool':payload['documents'][0]['type']=True
    elif change=='type_float':payload['documents'][0]['type']=1.0
    elif change=='unknown_path':payload['documents'][0]['path']=str(case['tmp_path']/'other.SLDPRT')
    elif change=='duplicate':payload['documents'].append(payload['documents'][0]);payload['document_count']=2
    elif change=='mutating':payload['mutation_attempted']=True
    elif change=='mutation_zero':payload['mutation_attempted']=0
    elif change=='failed':payload['status']='error'
    elif change=='empty':payload['documents']=[];payload['document_count']=0
    elif change=='active_unknown':payload['active_document']['path']=str(case['tmp_path']/'other.SLDPRT')
    publish()
    assert case['apply'](acknowledged_discard_ids=[])['status']=='blocked'
    assert case['api'].calls==[]


@pytest.mark.parametrize('change',['parsed','structured','coercible','duplicate_result','batch_count','error'])
def test_inventory_batch_representations_and_scope_must_agree(case,change):
    _,publish=install_clean(case)
    batch=publish(); wrapped=batch['results'][0]['result']
    if change=='parsed':wrapped['content'][0]['parsed_json']['process_id']=456
    elif change=='structured':wrapped['structuredContent']['result']='{}'
    elif change=='coercible':wrapped['content'][0]['parsed_json']['mutation_attempted']=0
    elif change=='duplicate_result':batch['results'].append(deepcopy(batch['results'][0]));batch['request_count']=2
    elif change=='batch_count':batch['request_count']=2
    elif change=='error':wrapped['isError']=True
    case['manifest']['clean_inventory_evidence']=case['pin']('clean_inventory.json',batch)
    case['change']('recovery_manifest',case['manifest'])
    assert case['apply'](acknowledged_discard_ids=[])['status']=='blocked'
    assert case['api'].calls==[]


def test_clean_case_still_requires_save_and_current_file_hash(case):
    install_clean(case)
    case['checkpoint'].write_bytes(b'changed since save')
    assert case['apply'](acknowledged_discard_ids=[])['status']=='blocked'
    assert case['api'].calls==[]


def test_clean_inventory_change_after_intent_blocks_termination(case):
    install_clean(case)
    state=case['run']()['state_sha256'];count=[0]
    def race(api):
        count[0]+=1
        if count[0]==2:(case['tmp_path']/'clean_inventory.json').write_text('{}')
    case['api'].after_identity=race
    result=case['run']('apply',expected_state_sha256=state,acknowledge_terminate_owned_process=True,
        acknowledged_discard_ids=[],receipt_path=str(case['tmp_path']/'new.json'))
    assert result['status']=='blocked' and not any(x[0]=='terminate' for x in case['api'].calls)


def test_dirty_case_cannot_acknowledge_empty_discard_list(case):
    result=case['apply'](acknowledged_discard_ids=[])
    assert result['status']=='blocked' and not any(x[0]=='terminate' for x in case['api'].calls)
