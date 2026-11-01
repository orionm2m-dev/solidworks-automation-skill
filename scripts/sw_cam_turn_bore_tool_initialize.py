"""Assign one observed existing boring tool to a new rough BORE, without Save.

One TURN.SetTool qualification only. No generation, operation creation, tool
editing or automatic retry is performed; successful authority remains in RAM.
"""
from copy import deepcopy
from pathlib import Path
import json,math,re
from scripts import sw_cam_turn_partial_toolcrib as partial
from scripts import sw_cam_turn_tool_reference_repair as binding
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import solidworks_operation_lock
common=partial.common
SCOPE='SINGLE_ROUGH_BORE_TOOL_INITIALIZATION_RAM_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','crib_receipt_path','crib_receipt_sha256','operation_native_id','feature_native_id','tool_native_id','expected_included_angle_native','receipt_path','module_sha256','qualification_only','acknowledge_ram_only'}
FORBIDDEN=('model_saved','GTP_attempted','GOP_attempted','operation_inserted','tool_geometry_changed','automatic_retry','automatic_replay','persistence_qualified','physical_tool_qualified','production_qualified')


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='initialize_single_turn_bore_tool','Exact single BORE tool action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact initialization fields required')
    for key in ('process_id','operation_native_id','feature_native_id','tool_native_id'):require(type(p[key]) is int and 0<p[key]<2**31,'Strict positive identity required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact digest required')
    angle=p['expected_included_angle_native'];require(type(angle) in (int,float) and math.isfinite(angle) and 0<angle<180,'Explicit native insert angle required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True and p['acknowledge_ram_only'] is True,'Exact module and RAM-only qualification required');return p


def observed_crib(observed,p,parent_receipt,loaded):
    require(observed['scope']==partial.SCOPE and observed['status']=='observed' and observed['phase']=='finished' and observed['readback_verified'] is True and observed['read_only'] is True,'Completed current partial-state crib read required')
    require(all(observed[k] is False for k in ('mutation_attempted','model_saved','GTP_attempted','operation_inserted','tool_assignment_attempted','operation_tool_lookup_attempted','persistence_qualified','physical_tool_qualified','production_qualified')),'Read-only partial-state evidence required')
    require(not any(k in observed for k in ('issue','failed_phase','cleanup_error')),'Uncertain crib cannot authorize assignment');clean_events(observed)
    q=observed['request'];require(q['process_id']==p['process_id'] and common._key(q['expected_document_path'])==common._key(p['expected_document_path']) and observed['source_sha256']==q['expected_source_sha256']==p['expected_source_sha256'] and common._key(observed['source_path'])==common._key(p['expected_document_path']),'Same owned source required')
    pq=parent_receipt['request'];require(pq['process_id']==p['process_id'] and common._key(pq['expected_document_path'])==common._key(p['expected_document_path']) and pq['expected_source_sha256']==p['expected_source_sha256'],'Partial parent source differs')
    state=partial.validate_partial(parent_receipt,loaded['catalogue'],loaded['roles'])
    require(observed['before']==observed['after']==state,'Current crib and partial insertion state differ')
    row=parent_receipt['new_operations'][0];kind=next(x['resolved_native_value'] for x in loaded['roles'] if x['role']=='rough_bore')
    require(row['native_id']==p['operation_native_id'] and row['turn_operation_type']==kind and row['linked_feature_ids']==[p['feature_native_id']] and row['suppressed'] is False and pq['feature_native_id']==p['feature_native_id'],'Only the verified first rough BORE may be initialized')
    tools=observed['tools'];require(type(tools) is list and 0<len(tools)<=partial.reader.MAX_TOOLS,'Bounded current toolcrib required')
    indexed={x['native_id']:x for x in tools};require(len(indexed)==len(tools) and sorted(indexed)==observed['tool_ids'] and all(x['complete'] is True for x in tools),'Complete unique current toolcrib required')
    candidate=indexed[p['tool_native_id']]
    require(all(type(candidate[k]) is int for k in ('native_id','tool_type_raw','turn_tool_type_raw','insert_type_raw','holder_type_raw','holder_id_raw')),'Strict native candidate identities and classifications required')
    require(candidate['candidate'] is True and candidate['tool_type_raw']==15 and candidate['turn_tool_type_raw']==1 and candidate['insert_type_raw']==1 and candidate['holder_present'] is True and candidate['holder_type_raw']==2,'Observed TURN diamond boring-bar holder required')
    require(type(candidate['insert_dimensions_native']) is dict and type(candidate['holder_dimensions_native']) is dict,'Observed candidate dimensions required')
    angle=candidate['insert_dimensions_native']['IncludedAngle'];require(type(angle) in (int,float) and math.isfinite(angle) and angle==p['expected_included_angle_native'],'Observed insert angle differs')
    assignment=dict(operation_native_id=p['operation_native_id'],operation_type=kind,feature_native_id=p['feature_native_id'],tool_native_id=p['tool_native_id'])
    return state,candidate,assignment


def load_inputs(p):
    observed,opin=read_pin(p['crib_receipt_path'],p['crib_receipt_sha256']);pp=observed['parent_pin']
    require(common._key(pp['path'])==common._key(observed['request']['parent_receipt_path']) and pp['sha256']==observed['request']['parent_receipt_sha256'],'Parent pin differs')
    parent_receipt,ppin=read_pin(pp['path'],pp['sha256']);loaded=partial.parent.load_catalogue(parent_receipt['request'])
    reference,candidate,assignment=observed_crib(observed,p,parent_receipt,loaded)
    common._check(parent_receipt['runtime_and_evidence_pins']);common._check(observed['runtime_and_evidence_pins'])
    require(parent_receipt['module_pin']==common._pin(partial.parent.__file__),'Insertion implementation changed')
    marker=partial.parent.marker_path(parent_receipt['request']);claim,mpin=read_pin(str(marker),observed['marker_pin']['sha256'])
    require(common._key(observed['marker_pin']['path'])==common._key(marker) and claim==partial.parent.claim_value(parent_receipt['request']),'Original insertion marker differs')
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Source bytes changed')
    registration=partial.parent.prior.catalogue.jobs._validate_registration(loaded['catalogue']['request']);abi=binding.audit(loaded['typelib_path'],loaded['generated_pin'])
    pins=common._merge(observed['runtime_and_evidence_pins'],loaded['pins'],[opin,ppin,mpin,common._pin(partial.__file__),common._pin(binding.__file__),common._pin(__file__)])
    require(len(pins)<=64,'Bounded initialization proof closure required')
    return dict(observed=observed,observed_pin=opin,parent=parent_receipt,parent_pin=ppin,reference=reference,candidate=candidate,assignment=assignment,catalogue=loaded['catalogue'],roles=loaded['roles'],pins=pins,typelib_path=loaded['typelib_path'],generated_pin=loaded['generated_pin'],registration=registration,abi=abi)


def marker_path(p):
    key=_digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha256=p['expected_source_sha256'],operation=p['operation_native_id'],feature=p['feature_native_id']))
    return common.local_evidence_root()/('single_bore_tool_'+key+'.json')


def claim_value(p):
    return dict(scope=SCOPE,status='claimed_no_replay',source_sha256=p['expected_source_sha256'],operation_native_id=p['operation_native_id'],feature_native_id=p['feature_native_id'],tool_native_id=p['tool_native_id'],receipt_path=p['receipt_path'])


def prepare(p):
    plan=load_inputs(p);output,marker=common._local_receipt(p['receipt_path']),marker_path(p)
    forbidden={common._key(x['path']) for x in plan['pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(output),common._key(marker)})==2 and not forbidden.intersection((common._key(output),common._key(marker))),'Outputs alias source or evidence')
    require(all(x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in (output,marker)),'Fresh output and no earlier initialization attempt required')
    plan.update(output=output,marker=marker);return plan


# Reuse the bounded assignment and immediate reference-read methods.
# The old pair repair loader and its historical operation semantics are not used.
NativeBackend=binding.NativeBackend


def run_backend(backend,p,plan,r,persist,claim):
    a=plan['assignment'];label='SetTool_'+str(a['operation_native_id'])
    def pending():
        require(not r['actions'],'Exactly one assignment attempt permitted');claim()
        r.update(phase=label,mutation_attempted=True,native_dispatch_pending=True);r['actions'][label]=dict(attempted=True,pending=True,returned=False,readback_verified=False);persist()
    try:
        backend.start();r['phase']='before';r['before']=backend.capture('before');persist();require(r['before']==plan['reference'],'Current partial operation state changed')
        r['tools_before']=backend.tool_snapshot('before');persist();require(r['tools_before']==plan['observed']['tools'],'Current toolcrib differs from observation')
        result=backend.assign(a,pending);r['actions'][label].update(returned=True,pending=False,native_return=result);r['native_dispatch_pending']=False;persist()
        require(type(result) is int and result==0,'Strict successful TURN SetTool HRESULT required')
        r['phase']='immediate_tool_reference';persist();actual=backend.assigned(a);r['reference_after']=deepcopy(actual);persist()
        require(actual==binding.expected_reference(a,plan['candidate']),'Immediate tool identity or classification differs');r['actions'][label]['readback_verified']=True
        r['tools_after']=backend.tool_snapshot('after');persist();require(r['tools_after']==r['tools_before'],'Tool geometry or crib changed during assignment')
        r['phase']='after';r['after']=backend.capture('after');persist();binding.unchanged_route(r['before'],r['after'])
        backend.finish();r.update(status='initialized_ram_no_save',phase='finished',readback_verified=True)
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',cleanup_error=_error(exc),readback_verified=False)
        persist()
    return r


def validate_initialized(r,plan):
    p=r['request'];a=plan['assignment'];label='SetTool_'+str(a['operation_native_id'])
    require(r['scope']==SCOPE and r['status']=='initialized_ram_no_save' and r['phase']=='finished' and r['readback_verified'] is True,'Completed single RAM tool initialization required')
    require(r['mutation_attempted'] is True and r['native_dispatch_pending'] is False and not any(k in r for k in ('issue','failed_phase','cleanup_error','proof_error')),'Uncertain initialization cannot authorize continuation')
    require(all(r[k] is False for k in FORBIDDEN),'Initialization authority must remain RAM-only');clean_events(r)
    require(r['source_sha256']==p['expected_source_sha256'] and common._key(r['source_path'])==common._key(p['expected_document_path']),'Receipt source differs')
    require(r['assignment']==a and r['accepted_candidate']==plan['candidate'],'Assigned target/candidate differs')
    require(r['before']==plan['reference'],'Initialization baseline differs');binding.unchanged_route(r['before'],r['after'])
    require(r['tools_before']==r['tools_after']==plan['observed']['tools'],'Tool data changed');require(set(r['actions'])=={label},'Only one assignment may have occurred')
    action=r['actions'][label];require(action['attempted'] is True and action['returned'] is True and action['pending'] is False and action['readback_verified'] is True and type(action['native_return']) is int and action['native_return']==0,'Assignment needs strict successful return and readback')
    require(r['reference_after']==binding.expected_reference(a,plan['candidate']),'Assigned reference differs');return r['after']


def load_initialized(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,rpin=read_pin(path,digest);p=r['request']
    require(p['process_id']==process_id and common._key(p['expected_document_path'])==common._key(expected_document_path) and p['expected_source_sha256']==expected_source_sha256,'Same initialized source/owner required')
    plan=load_inputs(p);state=validate_initialized(r,plan);common._check(r['runtime_and_evidence_pins']);require(r['module_pin']==common._pin(__file__),'Initializer implementation changed')
    marker=marker_path(p);value,mpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(value==claim_value(p) and common._key(value['receipt_path'])==common._key(path),'Original durable initialization marker required')
    pins=common._merge(r['runtime_and_evidence_pins'],[rpin,mpin]);require(len(pins)<=64,'Bounded continuation evidence required')
    return dict(authority='single_rough_bore_tool_initialized_ram_no_save',receipt=r,reference=deepcopy(state),state=deepcopy(state),assignment=deepcopy(plan['assignment']),tool_reference=deepcopy(r['reference_after']),tool_snapshot=deepcopy(r['tools_after']),partial_insertion_receipt=plan['parent'],catalogue=plan['catalogue'],roles=plan['roles'],typelib_path=plan['typelib_path'],pins=pins,source_sha256=expected_source_sha256,persistence_qualified=False,GTP_authorized=False)


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_count=len(plan['pins']),assignment=plan['assignment'],abi=plan['abi'],save_authorized=False,GTP_authorized=False)
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],module_pin=common._pin(__file__),runtime_and_evidence_pins=plan['pins'],crib_receipt_pin=plan['observed_pin'],parent_receipt_pin=plan['parent_pin'],abi=plan['abi'],assignment=deepcopy(plan['assignment']),accepted_candidate=deepcopy(plan['candidate']),actions={},mutation_attempted=False,native_dispatch_pending=False,readback_verified=False,**{k:False for k in FORBIDDEN})
        _write_receipt(plan['output'],r,create=True);persist=lambda:_write_receipt(plan['output'],r);claim=lambda:_write_receipt(plan['marker'],claim_value(p),create=True)
        run_backend(NativeBackend(sw,p,plan,r,persist),p,plan,r,persist,claim)
        if r['readback_verified']:
            try:r['marker_pin']=common._pin(plan['marker']);validate_initialized(r,plan);common._check(plan['pins'])
            except Exception as exc:r.update(status='uncertain',readback_verified=False,proof_error=_error(exc))
            persist()
        return r


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--request',required=True);ap.add_argument('--validate-only',action='store_true');a=ap.parse_args()
    r=dispatch_request(json.loads(Path(a.request).read_text(encoding='utf-8-sig')),validate_only=a.validate_only)
    print(json.dumps({k:r[k] for k in ('scope','status','phase','readback_verified','native_called','pin_count','assignment','issue') if k in r},ensure_ascii=False,indent=2));raise SystemExit(0 if r['status'] in ('validated_offline','initialized_ram_no_save') else 2)
