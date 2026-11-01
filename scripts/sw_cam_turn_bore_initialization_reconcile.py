"""Observe one rough BORE tool reference after an uncertain initialization.

Reuse the established single-IGetTool reader. Never retry the setter, insert,
generate or Save, and never convert an RPC failure into a successful return.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_turn_bore_tool_initialize as initializer
from scripts import sw_cam_turn_reference_reconcile as reader
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import solidworks_operation_lock
common=initializer.common
SCOPE='ROUGH_BORE_UNCERTAIN_TOOL_READ_V1'
PARAMS=reader.PARAMS


def validate_failed(failed,plan):
    a=plan['assignment'];label='SetTool_'+str(a['operation_native_id'])
    require(failed['scope']==initializer.SCOPE and failed['status']=='uncertain' and failed['phase']=='finished' and failed['failed_phase']==label and failed['mutation_attempted'] is True and failed['readback_verified'] is False,'Exact terminal uncertain initialization required')
    require(failed['issue'].get('type')=='COMError' and failed['issue'].get('hresult')==-2147417851,'Observed RPC_E_SERVERFAULT required')
    require(failed['native_dispatch_pending'] is True and set(failed['actions'])=={label} and failed['actions'][label]==dict(attempted=True,pending=True,returned=False,readback_verified=False),'Exactly one setter with unknown return required')
    require(all(failed[k] is False for k in initializer.FORBIDDEN) and not any(k in failed for k in ('cleanup_error','proof_error','after','reference_after','tools_after')),'No completed readback or unrelated mutation allowed');clean_events(failed)
    require(failed['assignment']==a and failed['accepted_candidate']==plan['candidate'] and failed['before']==plan['reference'] and failed['tools_before']==plan['observed']['tools'],'Verified pre-attempt state or selected tool differs')
    return deepcopy(a)


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_uncertain_bore_initialization','Exact read-only initialization reconciliation required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact read fields required');require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Reader changed');return p


def prepare(p):
    failed,fpin=read_pin(p['failed_receipt_path'],p['failed_receipt_sha256']);q=failed['request']
    require(q['process_id']==p['process_id'] and common._key(q['expected_document_path'])==common._key(p['expected_document_path']) and q['expected_source_sha256']==p['expected_source_sha256'],'Exact attempted owner/source required')
    loaded=initializer.load_inputs(q);a=validate_failed(failed,loaded);common._check(failed['runtime_and_evidence_pins']);require(failed['module_pin']==common._pin(initializer.__file__),'Initializer code changed')
    marker=initializer.marker_path(q);claim,mpin=read_pin(str(marker),_file_hash(marker));require(claim==initializer.claim_value(q),'Original no-replay initialization marker differs')
    pins=common._merge(failed['runtime_and_evidence_pins'],loaded['pins'],[fpin,mpin,common._pin(initializer.__file__),common._pin(reader.__file__),common._pin(__file__)]);require(len(pins)<=64,'Bounded read closure required')
    output=common._local_receipt(p['receipt_path']);require(output.parent.is_dir() and not output.exists() and not output.is_symlink() and common._key(output) not in {common._key(x['path']) for x in pins}|{common._key(p['expected_document_path'])},'Fresh nonaliased diagnostic receipt required')
    return dict(failed=failed,assignment=a,reference=failed['before'],catalogue=loaded['catalogue'],pins=pins,typelib_path=loaded['typelib_path'],generated_pin=loaded['generated_pin'],abi=loaded['abi'],registration=loaded['registration'],output=output,failed_pin=fpin,marker_pin=mpin)


NativeBackend=reader.NativeBackend


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_count=len(plan['pins']),assignment=plan['assignment'],IGetTool_max_calls=1,mutation_authorized=False)
    from scripts.sw_connect import connect_solidworks
    bp=dict(p,feature_native_id=plan['assignment']['feature_native_id'])
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,read_only=True,mutation_attempted=False,model_saved=False,GTP_attempted=False,operation_inserted=False,assignment_attempted=False,persistence_qualified=False,production_qualified=False,readback_verified=False,source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],runtime_and_evidence_pins=plan['pins'],failed_attempt_pin=plan['failed_pin'],marker_pin=plan['marker_pin'],attempted_assignment=plan['assignment'],protected_route_unchanged=False,limitations=['Read current reference after uncertain setter outcome; original RPC error remains unchanged','No setter/insert/recovery replay or Save/GTP','Observed reference is not successful setter return, physical qualification or persistence proof'])
        _write_receipt(plan['output'],r,create=True);persist=lambda:_write_receipt(plan['output'],r)
        return reader.run_backend(NativeBackend(sw,bp,plan,r,persist),plan,r,persist)


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--request',required=True);ap.add_argument('--validate-only',action='store_true');a=ap.parse_args()
    r=dispatch_request(json.loads(Path(a.request).read_text(encoding='utf-8-sig')),validate_only=a.validate_only)
    print(json.dumps({k:r[k] for k in ('scope','status','phase','readback_verified','native_called','pin_count','reference_observation','issue') if k in r},ensure_ascii=False,indent=2));raise SystemExit(0 if r['status'] in ('validated_offline','observed') else 2)
