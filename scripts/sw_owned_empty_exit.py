"""Exit one proven owned empty SOLIDWORKS session after verified TURN save/close."""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import hashlib,json,math,re,time
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_lifecycle import _verify_save
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_inprocess_reader import require,key,digest,check_files
from scripts.sw_operation_guard import solidworks_operation_lock
from scripts.sw_owned_process_recovery import Win32ProcessAPI,_match_identity,_EPOCH

SCOPE='OWNED_EMPTY_SESSION_EXIT_V1'
FIELDS={'process_id','expected_creation_filetime','expected_executable_path','expected_document_path','expected_source_sha256','ownership_receipt_path','ownership_receipt_sha256','save_receipt_path','save_receipt_sha256','close_receipt_path','close_receipt_sha256','receipt_path','wait_milliseconds','acknowledge_exit_owned_empty_session'}


VERIFIED_EMPTY_SCOPE='OWNED_VERIFIED_EMPTY_SESSION_EXIT_V1'
VERIFIED_EMPTY_FIELDS=(FIELDS-{'save_receipt_path','save_receipt_sha256','close_receipt_path','close_receipt_sha256'})|{'empty_receipt_path','empty_receipt_sha256','acknowledge_restored_checkpoint_exit'}

def _parameters(value,fields):
    require(type(value) is dict and set(value)==fields,'Exact empty-session exit parameters required');p=deepcopy(value)
    require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict owned PID required')
    require(type(p['expected_creation_filetime']) is int and _EPOCH<p['expected_creation_filetime']<2**63,'Exact creation FILETIME required')
    require(type(p['wait_milliseconds']) is int and 1<=p['wait_milliseconds']<=30000,'Exit observation wait must be1..30000ms')
    require(p['acknowledge_exit_owned_empty_session'] is True,'Explicit empty-session exit acknowledgement required')
    for name,v in p.items():
        if name.endswith('_path'):require(type(v) is str and Path(v).is_absolute() and len(v)<=32767,'Absolute bounded paths required')
        if name.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact lowercase SHA256 required')
    require(Path(p['expected_executable_path']).name.casefold()=='sldworks.exe' and Path(p['expected_document_path']).suffix.casefold()=='.sldprt','Exact SOLIDWORKS/part paths required')
    return p


def parameters(value):return _parameters(value,FIELDS)

def verified_empty_parameters(value):
    p=_parameters(value,VERIFIED_EMPTY_FIELDS)
    require(p['acknowledge_restored_checkpoint_exit'] is True,'Explicit restored-checkpoint exit acknowledgement required')
    return p


def validate_lifecycle(saved,closed,p):
    for value,action in ((saved,'save'),(closed,'close')):
        require(value.get('action')==action and value.get('status')=='review_required' and value.get('phase')=='finished','Completed TURN lifecycle receipt required')
        require(value.get('mutation_attempted') is True and value.get('native_call_attempted') is True and value.get('native_call_returned') is True and value.get('generation_attempted') is False,'Native lifecycle action evidence required')
        require(not any(k in value for k in ('issue','failed_phase','receipt_write_error','cleanup_issue')),'Uncertain lifecycle receipt rejected');clean_events(value)
    require(saved.get('native_save_call_returned') is True and saved.get('save_readback_verified') is True and saved.get('native_close_call_returned') is False and saved.get('native_outcome')=='save_returned_readback_verified','Save readback proof required')
    final=saved['final_state'];require(final==saved['after'],'Save final snapshot differs');_verify_save(saved['before'],final)
    doc=final['document'];require(key(doc['path'])==key(p['expected_document_path']) and type(doc['type']) is int and doc['type']==1 and doc['needs_save'] is False,'Saved clean target required')
    require(type(final['inventory']['machine_type']) is int and final['inventory']['machine_type']==3,'TURN lifecycle required')
    require(final['saved_file_sha256']==p['expected_source_sha256'] and saved['state_sha256']==_digest(final),'Saved source/state fingerprint differs')
    require(closed['before']==final and closed['state_sha256']==_digest(final),'Close must continue the same saved state')
    require(closed.get('native_close_call_returned') is True and closed.get('close_verified') is True and closed.get('native_save_call_returned') is False and closed.get('native_outcome')=='target_absent_from_open_documents','Verified close required')
    require(closed.get('user_control_before_close') is True and closed.get('open_documents_after')==[] and closed.get('open_documents_after_cleanup')==[],'Close must leave an empty user-controlled session')
    return final


def validate_ownership(owned,p):
    require(owned.get('status')=='ok' and owned.get('phase')=='connected' and owned.get('launch_mode')=='executable' and owned.get('launch_attempted') is True and owned.get('new_process_verified') is True,'Existing successful owned executable startup required')
    require(type(owned.get('process_id')) is int and owned['process_id']==p['process_id'] and type(owned.get('known_process_ids_before')) is list and p['process_id'] not in owned['known_process_ids_before'],'Startup must prove newly owned PID')
    identity=owned['process_identity'];require(identity.get('process_id')==p['process_id'] and identity.get('alive') is True and key(identity['executable'])==key(p['expected_executable_path']) and key(owned['executable'])==key(p['expected_executable_path']),'Startup image/PID differs')
    created=identity['create_time'];intent=owned['launch_intent_time']
    require(type(created) in (int,float) and type(intent) in (int,float) and math.isfinite(created) and math.isfinite(intent) and 0<=created-intent<=120,'Startup timing invalid')
    exact=Decimal(p['expected_creation_filetime']-_EPOCH)/Decimal(10_000_000)
    require(abs(Decimal(str(created))-exact)<Decimal('0.001'),'Startup creation time differs from exact FILETIME')


def prepare(p):
    values={};pins=[dict(path=p['expected_document_path'],sha256=p['expected_source_sha256'])]
    for name in ('ownership','save','close'):
        values[name],pin=read_pin(p[name+'_receipt_path'],p[name+'_receipt_sha256']);pins.append(dict(path=pin['path'],sha256=pin['sha256']))
    require(len({key(v['path']) for v in pins})==len(pins),'Source/evidence aliases forbidden');check_files(pins)
    validate_ownership(values['ownership'],p);state=validate_lifecycle(values['save'],values['close'],p)
    out=Path(p['receipt_path']);marker=out.parent/('owned_empty_exit_'+str(p['process_id'])+'_'+str(p['expected_creation_filetime'])+'.json')
    require(out.suffix.casefold()=='.json' and out.parent.is_dir() and key(out)!=key(marker),'Fresh JSON output required')
    for file in (out,marker):require(not file.exists() and not file.is_symlink() and key(file) not in {key(v['path']) for v in pins},'Existing/aliased exit receipt or marker; do not replay')
    return dict(values=values,pins=pins,state=state,output=out,marker=marker)


class NativeBackend:
    def __init__(self,p):self.p=p;self.api=None;self.handle=None;self.sw=None
    def start(self):
        self.api=Win32ProcessAPI();self.handle=self.api.open(self.p['process_id'],terminate=False)
        _match_identity(self.p,self.api.identity(self.handle))
        from scripts.sw_connect import connect_solidworks
        self.sw,_=connect_solidworks(process_id=self.p['process_id'],launch_new_instance=False,wait_seconds=1)
    def owner(self):return self.api.identity(self.handle)
    def empty(self):
        require(_member(self.sw,'GetProcessID')==self.p['process_id'],'Bound application PID differs')
        require(_member(self.sw,'UserControl') is True,'UserControl=true required before exit')
        docs=_member(self.sw,'GetDocuments')
        require(docs is None or (type(docs) in (tuple,list) and len(docs)==0),'Other/open documents forbid exit')
        return []
    def exit_once(self):return _member(self.sw,'ExitApp')
    def wait_exit(self,milliseconds):return self.api.wait(self.handle,milliseconds)
    def close(self):
        if self.handle is not None:self.api.close(self.handle);self.handle=None


def run_exit(params,*,backend=None):
    p=parameters(params);return _run_prepared_exit(p,prepare(p),backend=backend)


def _run_prepared_exit(p,plan,*,backend=None):
    engine=backend or NativeBackend(p)
    r=dict(scope=plan.get('scope',SCOPE),status='prepared',phase='prepared',request=p,pins=plan['pins'],marker_path=str(plan['marker']),exit_attempted=False,exit_call_count=0,exit_returned=False,process_exit_verified=False,empty_session_verified=False,saved_files_preserved=None,readback_verified=False,terminate_rights_requested=False,termination_attempted=False,save_attempted=False,close_document_attempted=False,launch_attempted=False,automatic_retry=False,client_module_sha256=digest(__file__))
    if 'empty_observation' in plan:r.update(evidence_mode='verified_empty_session_after_checkpoint_restore',empty_observation=plan['empty_observation'],save_close_evidence_required=False)
    _write_receipt(plan['output'],r,create=True)
    try:
        engine.start();before=engine.owner();_match_identity(p,before);r['owner_before']=before
        r['open_documents_before']=engine.empty();check_files(plan['pins'])
        _write_receipt(plan['marker'],dict(scope=r['scope'],process_id=p['process_id'],creation_filetime=p['expected_creation_filetime'],receipt_path=p['receipt_path'],intent='one_graceful_exit_no_replay'),create=True)
        require(engine.owner()==before,'Owned process identity changed');r['open_documents_final']=engine.empty();check_files(plan['pins']);r['empty_session_verified']=True
        r.update(phase='ExitApp',exit_attempted=True,exit_call_count=1,native_dispatch_pending=True);_write_receipt(plan['output'],r)
        try:
            value=engine.exit_once();r.update(exit_returned=True,native_dispatch_pending=False,exit_return_type=type(value).__name__)
        except Exception as exc:r['exit_error']=_error(exc)
        # After the single ExitApp, only the retained OS handle and file evidence are read.
        r['phase']='observe_exact_process_exit';_write_receipt(plan['output'],r)
        signalled=engine.wait_exit(p['wait_milliseconds']);require(type(signalled) is bool,'Strict OS wait result required')
        r['process_exit_verified']=signalled
        r['exit_observation_source']='WaitForSingleObject_on_retained_verified_process_handle'
        if not signalled:
            r['owner_after_timeout']=engine.owner();_match_identity(p,r['owner_after_timeout'])
        check_files(plan['pins']);r['saved_files_preserved']=True
        if r['process_exit_verified']:r.update(status='exited',phase='finished',readback_verified=True)
        else:r.update(status='exit_not_observed',phase='finished',readback_verified=False,reason='ExitApp was attempted once; do not automatically retry or terminate.')
    except Exception as exc:r.update(status='uncertain' if r['exit_attempted'] else 'error',phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:engine.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
        _write_receipt(plan['output'],r)
    return r


def safely_exit_owned_empty_session(params):
    p=parameters(params)
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):return run_exit(p)


def validate_empty_observation(value,p):
    # Accept the existing batch receipt, or the exact parsed tool result.
    if 'results' in value:
        require(value.get('schema_version')==1 and value.get('status')=='success' and type(value.get('results')) is list,'Completed inspection batch required')
        rows=value['results']
        require(type(value.get('request_count')) is int and value['request_count']==len(rows) and 1<=len(rows)<=2,'Bounded completed inspection batch required')
        require(all(row.get('name') in ('solidworks_connect','solidworks_inspect_open_documents') for row in rows),'Only connection and document inspection evidence accepted')
        selected=[row for row in rows if row.get('name')=='solidworks_inspect_open_documents']
        require(len(selected)==1,'Exactly one document inspection result required')
        result=selected[0]['result'];require(result.get('isError') is not True,'Failed inspection result rejected')
        payloads=[block['parsed_json'] for block in result.get('content',[]) if type(block) is dict and type(block.get('parsed_json')) is dict]
        require(len(payloads)==1,'One parsed document inspection payload required');value=payloads[0]
    require(type(value) is dict and value.get('status')=='ok' and type(value.get('process_id')) is int and value['process_id']==p['process_id'],'Successful inspection of exact owned PID required')
    require(value.get('active_document') is None and 'active_document' in value and value.get('documents')==[] and type(value.get('document_count')) is int and value['document_count']==0,'Inspection must prove no active or open documents')
    require(value.get('user_control') is True and value.get('mutation_attempted') is False,'Read-only user-controlled inspection required')
    require(not any(name in value for name in ('issue','error','failed_phase','receipt_write_error')),'Uncertain inspection rejected')
    return {name:value[name] for name in ('status','process_id','active_document','documents','document_count','user_control','mutation_attempted')}


def prepare_verified_empty(p,*,now=None):
    values={};pins=[dict(path=p['expected_document_path'],sha256=p['expected_source_sha256'])]
    for name in ('ownership','empty'):
        values[name],pin=read_pin(p[name+'_receipt_path'],p[name+'_receipt_sha256']);pins.append(dict(path=pin['path'],sha256=pin['sha256']))
    require(len({key(v['path']) for v in pins})==len(pins),'Source/evidence aliases forbidden');check_files(pins)
    validate_ownership(values['ownership'],p);observation=validate_empty_observation(values['empty'],p)
    # File age is only an artifact recency gate. Two live empty/process checks remain authoritative.
    age=(time.time() if now is None else now)-Path(p['empty_receipt_path']).stat().st_mtime
    require(0<=age<=300,'Empty inspection artifact must have been written within the last five minutes')
    observation.update(artifact_age_seconds=age,recency_basis='file_mtime_only_live_empty_checks_still_required')
    out=Path(p['receipt_path']);marker=out.parent/('owned_empty_exit_'+str(p['process_id'])+'_'+str(p['expected_creation_filetime'])+'.json')
    require(out.suffix.casefold()=='.json' and out.parent.is_dir() and key(out)!=key(marker),'Fresh JSON output required')
    for file in (out,marker):require(not file.exists() and not file.is_symlink() and key(file) not in {key(v['path']) for v in pins},'Existing/aliased exit receipt or marker; do not replay')
    return dict(values=values,pins=pins,output=out,marker=marker,scope=VERIFIED_EMPTY_SCOPE,empty_observation=observation)


def run_verified_empty_exit(params,*,backend=None):
    p=verified_empty_parameters(params)
    return _run_prepared_exit(p,prepare_verified_empty(p),backend=backend)


def safely_exit_verified_empty_session(params):
    p=verified_empty_parameters(params)
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):return run_verified_empty_exit(p)
