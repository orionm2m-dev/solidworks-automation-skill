"""Bind saved partial CAM history to a newly owned process before full live capture.
The projected PID is comparison metadata, never a claimed native observation.
"""
from copy import deepcopy
from pathlib import Path
from decimal import Decimal
import math
from scripts import sw_cam_current_circular_finish_authority as history
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_owned_empty_exit import validate_ownership
from scripts.sw_owned_process_recovery import _EPOCH
require=history.require;exact=history.exact
SCOPE='SAVED_PARTIAL_CURRENT_OWNER_CONTINUATION_V1'
PROVENANCE='saved_state_owner_comparison_projection_only'
FIELDS={'scope','current_owner','source_pin','historical_authority_pin','startup_pin','opened_inspection_pin','previous_exit_pin','previous_late_exit_pin','native_calls','historical_receipts_modified','fresh_full_capture_required_before_mutation'}
OWNER_FIELDS={'process_id','expected_process_create_time','expected_creation_filetime','expected_executable_path'}

def pin_read(p):
    require(type(p)is dict and set(p)=={'path','sha256'},'Exact explicit file pin required')
    return read_pin(p['path'],p['sha256'])

def same_pin(a,b):return history.common.same_path(a['path'],b['path'])and a['sha256']==b['sha256']

def inspect_payload(value):
    if 'results'in value:
        require(value.get('schema_version')==1 and value.get('status')=='success'and type(value.get('results'))is list and 1<=len(value['results'])<=2 and type(value.get('request_count'))is int and value['request_count']==len(value['results']),'Bounded successful inspection batch required')
        rows=value['results'];require(all(r.get('name')in('solidworks_connect','solidworks_inspect_open_documents')for r in rows),'Only explicit connection/inspection evidence accepted')
        selected=[r for r in rows if r['name']=='solidworks_inspect_open_documents'];require(len(selected)==1 and selected[0]['result'].get('isError')is not True,'One successful inspection required')
        payload=[b['parsed_json']for b in selected[0]['result'].get('content',[])if type(b)is dict and type(b.get('parsed_json'))is dict];require(len(payload)==1,'One parsed inspection required');value=payload[0]
    return value

def validate_opened(value,owner,source_path,expected_document):
    value=inspect_payload(value)
    require(value.get('status')=='ok'and type(value.get('process_id'))is int and value['process_id']==owner['process_id']and value.get('mutation_attempted')is False and value.get('user_control')is True,'Exact readonly current-owned inspection required')
    require(not any(k in value for k in('issue','error','failed_phase','receipt_write_error')),'Uncertain document inspection rejected')
    rows=value.get('documents');require(type(rows)is list and len(rows)==1 and type(value.get('document_count'))is int and value['document_count']==1,'Exactly one target document required')
    d=rows[0];active=value.get('active_document');require(type(active)is dict and d.get('needs_save')is False and d.get('visible')is True and type(d.get('type'))is int and d['type']==1,'Clean visible saved part required')
    for observed in(d,active):
        require(history.common.same_path(observed.get('path',''),source_path)and observed.get('title')==expected_document['title']and type(observed.get('type'))is int and observed['type']==1,'Inspection target identity differs')
    require(expected_document['needs_save']is False and history.common.same_path(expected_document['path'],source_path),'Historical clean target required')

def projection(state,owner):
    before=deepcopy(state);old=before['sketch_state']['pid'];require(type(old)is int and old>0 and old!=owner['process_id'],'Distinct original/current PID required')
    projected=deepcopy(before);projected['sketch_state']['pid']=owner['process_id']
    proof=dict(scope='EXPLICIT_OWNER_COMPARISON_PROJECTION_V1',historical_process_id=old,current_process_id=owner['process_id'],changed_paths=['/sketch_state/pid'],historical_state_sha256=_digest(before),comparison_state_sha256=_digest(projected),native_observation_performed=False,fresh_full_capture_required_before_mutation=True)
    return projected,proof

def verify_projection(data,v):
    owner=data.get('current_owner')
    if owner is None:
        require('owner_comparison_projection'not in data and 'historical_state'not in data,'Unexpected owner projection without owner');return None
    require(type(owner)is dict and set(owner)==OWNER_FIELDS and type(owner['process_id'])is int and owner['process_id']==v['process_id']and type(owner['expected_process_create_time'])is type(v['expected_process_create_time'])and owner['expected_process_create_time']==v['expected_process_create_time'],'Explicit current owner differs')
    expected,proof=projection(data['historical_state'],owner)
    require(exact(expected,data['state'])and exact(proof,data['owner_comparison_projection']),'Only explicitly recorded sketch PID may be projected')
    require(type(data.get('owner_manifest_pin'))is dict and same_pin(data['owner_manifest_pin'],data['authority_pin']),'Current owner manifest authority required')
    require(exact(history._full_pin(data['owner_manifest_pin']),data['owner_manifest_pin']),'Current owner manifest file changed')
    return proof

def prepare_provenance(data):return PROVENANCE if data.get('current_owner')is not None else 'completed_saved_result_receipt_only'

def prepare_projection(data):return deepcopy(data.get('owner_comparison_projection'))

def apply_live_owner(context,v,data):
    proof=verify_projection(data,v)
    if proof is None:return
    owner={k:data['current_owner'][k]for k in('process_id','expected_process_create_time')}
    for name in('v','request','args'):
        current=getattr(context,name,None)
        if current is not None:
            require(type(current)is dict,'Expected live request mapping required');current=deepcopy(current);current.update(owner);setattr(context,name,current)
    require(context.v['process_id']==v['process_id']and context.request['process_id']==v['process_id'],'Live reader PID must be rebound before enter')

def _bind_validated_history(manifest,manifest_pin,data,old,*,process_id,process_create_time,source_path,source_sha256,physical_source_sha256):
    require(type(manifest)is dict and set(manifest)==FIELDS and manifest['scope']==SCOPE,'Exact file-only owner continuation manifest required')
    require(type(manifest['native_calls'])is int and manifest['native_calls']==0 and manifest['historical_receipts_modified']is False and manifest['fresh_full_capture_required_before_mutation']is True,'File-only continuation cannot claim RAM verification')
    owner=manifest['current_owner'];require(type(owner)is dict and set(owner)==OWNER_FIELDS and type(owner['process_id'])is int and 0<owner['process_id']<2**31 and owner['process_id']==process_id,'Exact current PID required')
    time=owner['expected_process_create_time'];require(type(time)in(int,float)and math.isfinite(time)and time>0 and type(time)is type(process_create_time)and time==process_create_time,'Exact current process lifetime required')
    require(type(owner['expected_creation_filetime'])is int and owner['expected_creation_filetime']>_EPOCH and type(owner['expected_executable_path'])is str and Path(owner['expected_executable_path']).is_absolute(),'Exact current executable/FILETIME required')
    require(type(manifest['source_pin'])is dict and set(manifest['source_pin'])=={'path','sha256'}and history.common.same_path(manifest['source_pin']['path'],source_path)and manifest['source_pin']['sha256']==source_sha256,'Manifest source differs')
    source=Path(source_path);require(source.is_file()and not source.is_symlink()and _file_hash(source)==physical_source_sha256,'Exact unchanged saved source required')
    require(data.get('source_sha256')==source_sha256 and data['state']['sketch_state']['saved_file_sha256']==source_sha256,'Validated historical source required')
    prior_pin=history._full_pin(manifest['historical_authority_pin'])
    startup,startup_pin=pin_read(manifest['startup_pin']);validate_ownership(startup,owner)
    require(type(startup['process_identity']['create_time'])is type(time)and startup['process_identity']['create_time']==time,'Startup lifetime differs')
    if startup.get('startup_ownership_reconciled')is True:require(startup.get('ownership_verified')is True and startup.get('readback_verified')is True and startup.get('original_receipt_preserved')is True,'Completed reconciled startup required')
    opened,opened_pin=pin_read(manifest['opened_inspection_pin']);validate_opened(opened,owner,source_path,data['state']['document'])
    exited,exit_pin=pin_read(manifest['previous_exit_pin']);late,late_pin=pin_read(manifest['previous_late_exit_pin'])
    er=exited['request'];require(exited.get('scope')=='OWNED_VERIFIED_EMPTY_SESSION_EXIT_V1'and exited.get('phase')=='finished'and exited.get('status')in('exited','exit_not_observed')and er['process_id']==old['process_id'],'Exact previous owned exit required')
    require(abs(Decimal(er['expected_creation_filetime']-_EPOCH)/Decimal(10000000)-Decimal(str(old['expected_process_create_time'])))<Decimal('.001'),'Previous lifetime differs')
    require(not any(k in exited for k in('issue','cleanup_issue','runtime_error','receipt_write_error','exit_error')),'Unresolved previous exit failure rejected')
    require(exited.get('exit_attempted')is True and exited.get('exit_returned')is True and exited.get('empty_session_verified')is True and exited.get('saved_files_preserved')is True and type(exited.get('exit_call_count'))is int and exited['exit_call_count']==1 and exited.get('native_dispatch_pending')is False and exited.get('termination_attempted')is False,'One completed graceful exit with saved files required')
    require(history.common.same_path(er['expected_document_path'],source_path)and er['expected_source_sha256']==source_sha256,'Previous exit saved source differs')
    require(late.get('scope')=='POST_GRACEFUL_EXIT_OS_OBSERVATION_V1'and type(late.get('process_id'))is int and late['process_id']==old['process_id']and type(late.get('creation_filetime'))is int and late['creation_filetime']==er['expected_creation_filetime']and late.get('process_exit_verified')is True and late.get('process_signalled')is True and late.get('original_exit_returned')is True and late.get('exit_replayed')is False and late.get('termination_attempted')is False and late.get('saved_files_preserved')is True,'Verified exact previous process termination required')
    require(same_pin(late['exit_receipt'],exit_pin)and same_pin(late['source'],manifest['source_pin']),'Previous exit observation pins differ')
    historical=deepcopy(data['state']);require(historical['sketch_state']['pid']==old['process_id'],'Historical snapshot owner differs')
    projected,proof=projection(historical,owner)
    pins=list(data['pins'])+[manifest_pin,startup_pin,opened_pin,exit_pin,late_pin,dict(path=__file__,sha256=_file_hash(__file__))]
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting owner continuation pins');unique[key]=history._full_pin(p)
    data.update(historical_state=historical,state=projected,owner_comparison_projection=proof,current_owner=deepcopy(owner),owner_manifest_pin=manifest_pin,authority_pin=manifest_pin,historical_authority_pin=prior_pin,pins=list(unique.values()),fresh_full_capture_required_before_mutation=True)
    verify_projection(data,dict(process_id=process_id,expected_process_create_time=process_create_time));return data

def _load_manifest(manifest,manifest_pin,*,process_id,process_create_time,source_path,source_sha256):
    require(type(manifest)is dict and set(manifest)==FIELDS and manifest['scope']==SCOPE,'Exact file-only owner continuation manifest required')
    prior,prior_pin=pin_read(manifest['historical_authority_pin']);require(prior.get('scope')=='PARTIAL_FLOOR_CL_FILE_RECONCILIATION_V1','Exact partial saved CL authority required')
    raw,rawpin=history._pin_record(prior['raw_partial_save_receipt_pin']);old=raw['request']['params']
    require(type(old['process_id'])is int and old['process_id']!=process_id and old['expected_process_create_time']!=process_create_time,'Distinct saved-history/current sessions required')
    data=history.load_completed(prior_pin['path'],prior_pin['sha256'],process_id=old['process_id'],process_create_time=old['expected_process_create_time'],source_path=source_path,source_sha256=source_sha256)
    return _bind_validated_history(manifest,manifest_pin,data,old,process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=source_sha256,physical_source_sha256=source_sha256)

def load_completed(path,sha,*,process_id,process_create_time,source_path,source_sha256):
    outer,pin=read_pin(path,sha)
    args=dict(process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=source_sha256)
    if outer.get('scope')==SCOPE:return _load_manifest(outer,pin,**args)
    return history.load_completed(path,sha,**args)
