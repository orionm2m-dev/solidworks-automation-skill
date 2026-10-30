"""Read-only reconciliation of a returned but unqualified operation-order call.

The original mutation evidence and no-replay marker are immutable. This reader
classifies observed current state; it neither retries nor assumes the lost return.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_raw_mill_face_move as move
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity

SCOPE='READONLY_CURRENT_OPERATION_RECONCILIATION_V2'
HISTORICAL_MOVE_SHA256='958f9bd88112599f4fa2ac1db0498c2e7f85ad02fcc08640dd18c2fbcf226003'
CURRENT_MOVE_SHA256='b2d3d3fa27d4f04e1e50c50d091fb657d96df18d3790239998e364acdec63770'

def _key(path):return move._key(path)
def _self_pin():return move._pin(__file__)


def bind_move_runtime(data, historical_move_module_path, historical_move_module_sha256):
    """历史代码仅校验字节，不导入或执行；当前读取器使用固定新版本。"""
    current=move._self_pin();historical=data['module_pin'];archive=Path(historical_move_module_path)
    require(current['sha256']==CURRENT_MOVE_SHA256,'Current Move runtime differs')
    require(historical.get('sha256')==HISTORICAL_MOVE_SHA256 and _key(historical['path'])==_key(current['path']),
      'Exact original Move module pin required')
    require(type(historical_move_module_sha256) is str and historical_move_module_sha256==HISTORICAL_MOVE_SHA256,
      'Exact historical Move SHA required')
    require(archive.is_absolute() and archive.is_file() and not archive.is_symlink()
      and _key(archive)!=_key(current['path']),'Separate immutable historical Move bytes required')
    archived=move._pin(archive)
    require(archived['sha256']==HISTORICAL_MOVE_SHA256,'Historical Move archive changed')
    return dict(historical_module_pin=deepcopy(historical),archive_pin=archived,current_module_pin=current,
      archived_code_executed=False,allowed_runtime_replacement_count=1,
      archive_verification_scope='OFFLINE_BEFORE_CONNECT_AND_COMPLETED_LOAD')


def require_historical_authority(data,loaded):
    """只把一个已知运行时 pin 映射回历史身份，其余证明逐字段相等。"""
    current=move._self_pin();historical=data['module_pin']
    require(current['sha256']==CURRENT_MOVE_SHA256 and historical['sha256']==HISTORICAL_MOVE_SHA256
      and _key(current['path'])==_key(historical['path']),'Exact single runtime replacement required')
    def restore(pins):
        matches=[p for p in pins if _key(p['path'])==_key(current['path'])]
        require(matches==[current],'Exactly one current Move pin required')
        return [deepcopy(historical if _key(p['path'])==_key(current['path']) else p) for p in pins]
    old_live=restore(loaded['pins'])
    roles=deepcopy(loaded['dependency_roles'])
    role_pins=restore([v['pin'] for v in roles])
    for row,pin in zip(roles,role_pins):row['pin']=pin
    require(loaded['predecessor_validation']==data['predecessor_validation']
      and roles==data['dependency_roles']
      and canonical_evidence_pins(old_live)==canonical_evidence_pins(data['live_pins']),
      'Unapproved historical/current authority difference')

def verify_observed_order(reference,observed,*,diagnostic=None):
    detail={} if diagnostic is None else diagnostic
    require(type(observed['document'].get('needs_save')) is bool,'Actual strict bool SW flag required')
    order=tuple(row['native_id'] for row in observed['operations'])
    if order==move.AFTER_ORDER:
        move.verify_move_delta(reference,observed,diagnostic=detail)
        return dict(outcome='requested_order_observed',order_verified=True)
    require(order==move.BEFORE_ORDER,'Neither permitted exact operation order observed')
    normalized=deepcopy(observed);normalized['document']['needs_save']=reference['document']['needs_save']
    detail.update(raw_SW_save_flag_before=reference['document']['needs_save'],raw_SW_save_flag_after=observed['document']['needs_save'],comparison_only_normalization=['observed_SW_save_flag'])
    move.capture.cone.require_state_equivalent(reference,normalized,diagnostic=detail.setdefault('state_equivalence',{}))
    return dict(outcome='original_order_observed',order_verified=False)


def _flat_authority(data):
    """Verify the already captured authority without executing older loaders."""
    parent,parentpin=read_pin(data['parent_pin']['path'],data['parent_pin']['sha256'])
    require(parent.get('scope')=='RAW_MILL_FACE_APPEND_READONLY_RECOVERY_V1' and parent.get('status')=='observed' and parent.get('phase')=='finished'
      and all(parent.get(k) is True for k in ('read_only','readback_verified','state_recovered','original_failure_resolved')),'Completed current parent required')
    cp=parent['checkpoint'];current=data['current_before']
    require(parent['checkpoint_sha256']==_digest(cp) and data['current_before_sha256']==_digest(current) and set(current)==set(move.CURRENT_KEYS),'Current checkpoint digest/schema differs')
    require(current['state']==cp['state'] and dict(rough=current['payload'],finish=current['finish_payload'])==cp['payload'],'Current authority payload differs')
    for key in ('cone_observation','face_observation','cone_sketch_spec','face_sketch_spec','cone_feature_native_id','face_feature_native_id','source_sha256'):
        require(current[key]==cp[key],'Current geometry/source binding differs')
    failed=parent['failed_pin'];require(data['original_insert_pin']==failed and data['original_insert_marker_pin']==parent['failed_marker_pin'],'Original insertion evidence differs')
    original_live=canonical_evidence_pins([v for v in parent['evidence_pins'] if _key(v['path'])!=_key(failed['path'])],[parentpin])
    original_history=canonical_evidence_pins(parent['lineage_pins'],[failed])
    reconstructed=dict(current,pins=original_live,lineage_pins=original_history,failed_pin=failed,failed_marker_pin=parent['failed_marker_pin'])
    loaded=move._cutover(reconstructed,parentpin)
    require_historical_authority(data,loaded)
    return loaded


def _failed_base(path,digest,*,process_id,expected_document_path,expected_source_sha256,full_parent,historical_move_module_path,historical_move_module_sha256):
    data,pin=read_pin(path,digest)
    binding=bind_move_runtime(data,historical_move_module_path,historical_move_module_sha256)
    require(data.get('scope')==move.SCOPE and data.get('status')=='uncertain' and data.get('phase')=='finished'
      and data.get('failed_phase')=='InsertOperationAfter' and data.get('native_return_type')=='int' and data.get('native_return_is_none') is False,'Exact returned unqualified move required')
    require(data['process_id']==process_id and _key(data['source_path'])==_key(expected_document_path) and data['source_sha256']==expected_source_sha256,'Exact failed source/PID required')
    require(type(data.get('move_call_count')) is int and data['move_call_count']==1
      and all(data.get(k) is True for k in ('mutation_attempted','native_call_attempted','native_call_returned'))
      and all(data.get(k) is False for k in ('native_dispatch_pending','readback_verified','order_verified','make_copy','creator_attempted','copy_attempted','tool_assignment_attempted',
        'GOP_attempted','GTP_attempted','save_attempted','model_saved','set_save_flag_attempted','automatic_replay','automatic_retry','automatic_rollback')),'Uncertain/pending or broadened lifecycle required stop')
    require(data['operation_native_id']==267 and data['after_operation_native_id']==196 and data['setup_native_id']==93,'Move target differs')
    require(not any(k in data for k in ('after_context','after_payload','receipt_write_error','native_return_value')),'Different failure scope or unrecorded value assumption')
    issue=data['issue'];require(issue.get('type')=='ValueError' and any(v.get('function')=='require_move_return' for v in issue.get('locations',[])),'Only return-contract validation failure supported')
    guard=data['dispatch_guard'];require(guard.get('claimed') is True and guard.get('native_call_attempted') is True and guard.get('native_call_returned') is True and guard.get('invalid') is False,'Exact completed one-call guard required')
    clean_events(data)
    marker=move.move_marker(expected_document_path,expected_source_sha256,data['original_insert_pin']['sha256'])
    mark,markpin=read_pin(str(marker),_file_hash(marker))
    require(_key(data['marker_path'])==_key(marker) and mark.get('scope')==move.SCOPE and mark.get('status')=='uncertain'
      and mark.get('readback_verified') is False and mark.get('automatic_replay') is False and mark.get('native_call_attempted') is True
      and mark.get('native_call_returned') is True and mark.get('make_copy') is False and _key(mark['receipt_path'])==_key(path)
      and mark['receipt_sha256']==digest and _key(mark['source'])==_key(expected_document_path) and mark['source_sha256']==expected_source_sha256
      and mark['original_insert_sha256']==data['original_insert_pin']['sha256'] and mark['operation_native_id']==267
      and mark['after_operation_native_id']==196 and mark['setup_native_id']==93,'Original no-replay marker differs')
    if full_parent:
        loaded=move.load_move_parent(data['parent_pin']['path'],data['parent_pin']['sha256'],process_id=process_id,
          expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
        require(move._projection(loaded)==data['current_before'],'Frozen failed current context differs')
        require_historical_authority(data,loaded)
    else:loaded=_flat_authority(data)
    move.capture.cone.require_state_equivalent(loaded['state'],data['before_context'])
    require(data['before_payload']==move.capture._payload(loaded),'Verified before payload differs')
    for name in ('cone','face'):require(data['before_'+name+'_observation']==loaded[name+'_observation'],'Before geometry differs')
    require(_file_hash(expected_document_path)==expected_source_sha256,'Current saved source changed')
    loaded.update(pins=canonical_evidence_pins(loaded['pins'],[pin,markpin,_self_pin()]),failed_move_pin=pin,failed_move_marker_pin=markpin,failed_move_receipt=data,runtime_binding=binding)
    require(len(loaded['pins'])<=64,'Read-only current guard bound exceeded');move._check(loaded['pins'])
    return loaded


def load_reconciliation_parent(path,digest,**args):
    return _failed_base(path,digest,full_parent=True,**args)


def _fresh(loaded,path):
    target=Path(path);protected=loaded['pins']+loaded['predecessor_validation']['original_live_pins']+loaded['predecessor_validation']['original_history_pins']
    require(target.is_absolute() and target.parent.is_dir() and target.suffix.lower()=='.json' and not target.exists() and not target.is_symlink(),'Fresh read-only receipt required')
    require(_key(target) not in {_key(p['path']) for p in protected}|{_key(loaded['state']['document']['path'])},'Receipt aliases authority/source')
    return target


def capture_current_readonly(ctx,clsid,loaded,diagnostic,record,persist):
    """One reusable complete read, persisting observations before comparisons."""
    state,native=move.capture._capture_headers(ctx,clsid,loaded['state'],21,diagnostic,nullable_operation_id=267)
    record['observed_context']=deepcopy(state);persist()
    payload=move.capture._capture_payload(ctx,state,native,diagnostic,nullable_operation_id=267)
    record['observed_payload']=deepcopy(payload);persist()
    co=move.capture.cone._read_sketch_and_cone(ctx,native,loaded['cone_sketch_spec'],loaded['cone_feature_native_id'])
    record['observed_cone_observation']=deepcopy(co);persist()
    face_diag={};record['observed_face_observation']=face_diag
    fo=move.capture.face._read_face(ctx,native,loaded['face_sketch_spec'],265,diagnostic=face_diag,persist=persist)
    record['observed_face_observation']=deepcopy(fo);persist()
    return state,payload,co,fo


def reconcile_readonly(sw,clsid,typelib_path,*,loaded,process_id,expected_document_path,expected_source_sha256,receipt_path):
    from scripts.sw_cam_events import CamMessageSession
    target=_fresh(loaded,receipt_path);args=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,**loaded['ids'])
    report=dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',module_pin=_self_pin(),process_id=process_id,
      source_path=expected_document_path,source_sha256=expected_source_sha256,receipt_path=str(target),
      failed_move_pin=deepcopy(loaded['failed_move_pin']),failed_move_marker_pin=deepcopy(loaded['failed_move_marker_pin']),
      runtime_binding=deepcopy(loaded['runtime_binding']),
      current_before=move._projection(loaded),current_before_sha256=loaded['current_context_sha256'],live_pins=deepcopy(loaded['pins']),
      read_only=True,mutation_attempted=False,native_mutation_call_count=0,save_attempted=False,GTP_attempted=False,
      automatic_replay=False,original_return_value_known=False,original_return_accepted=False,readback_verified=False,
      order_verified=False,physical_sequence_qualified=False,recipe_qualified=False,production_qualified=False,snapshot_diagnostics={})
    created=False;session=None
    def persist():
        if created:_write_receipt(target,report)
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
          and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event requires stop')
    try:
        _write_receipt(target,report,create=True);created=True
        actual=raw_part_identity(sw);report['initial_document_observation']=deepcopy(actual);persist()
        require(type(actual.get('needs_save')) is bool,'Strict observed SW save flag required')
        expected=deepcopy(loaded['state']['document']);expected['needs_save']=actual['needs_save']
        require(actual==expected and _file_hash(expected_document_path)==expected_source_sha256,'Readonly document identity/source mismatch')
        ctx=move.CurrentMoveContext(loaded,args,sw,typelib_path,None,events,loaded['state']);ctx.expected_document=deepcopy(actual)
        ctx.files();ctx.identity();ctx.app=move.capture.cone._bootstrap(sw,clsid,typelib_path,expected_document_path);ctx.identity()
        session=CamMessageSession(ctx.app,typelib_path)
        with session:
            report['phase']='readonly_full_current_capture';persist()
            try:state,payload,co,fo=capture_current_readonly(ctx,clsid,loaded,report['snapshot_diagnostics'],report,persist)
            finally:persist()
            report['comparison']={};outcome=verify_observed_order(loaded['state'],state,diagnostic=report['comparison']);report.update(outcome);persist()
            require(payload==move.capture._payload(loaded) and co==loaded['cone_observation'] and fo==loaded['face_observation'],'Protected data changed')
        events(False);ctx.files();require(ctx.identity()==state['document'],'Current identity changed during cleanup')
        current=move._projection(loaded);current['state']=deepcopy(state)
        report.update(status='observed',phase='finished',readback_verified=True,current_after=current,current_after_sha256=_digest(current),
          source_after_sha256=_file_hash(expected_document_path),original_failure_reconciled=outcome['order_verified'],
          reason='CURRENT_STATE_READBACK_WITHOUT_REPLAY_OR_RETURN_ASSUMPTION')
    except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,order_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        persist()
    return report


def load_completed_reconciliation(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    data,pin=read_pin(path,digest)
    require(data.get('scope')==SCOPE and data.get('status')=='observed' and data.get('phase')=='finished' and data.get('module_pin')==_self_pin(),'Completed current readback required')
    require(data['process_id']==process_id and _key(data['source_path'])==_key(expected_document_path)
      and data['source_sha256']==data['source_after_sha256']==expected_source_sha256,'Exact source/PID differs')
    require(all(data.get(k) is True for k in ('read_only','readback_verified','order_verified','original_failure_reconciled'))
      and all(data.get(k) is False for k in ('mutation_attempted','save_attempted','GTP_attempted','automatic_replay','original_return_value_known','original_return_accepted','recipe_qualified','production_qualified'))
      and type(data.get('native_mutation_call_count')) is int and data['native_mutation_call_count']==0
      and not any(k in data for k in ('issue','failed_phase','receipt_write_error')),'Only reconciled requested order may continue')
    clean_events(data)
    loaded=_failed_base(data['failed_move_pin']['path'],data['failed_move_pin']['sha256'],process_id=process_id,
      expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,full_parent=False,
      historical_move_module_path=data['runtime_binding']['archive_pin']['path'],
      historical_move_module_sha256=data['runtime_binding']['archive_pin']['sha256'])
    require(data['runtime_binding']==loaded['runtime_binding'],'Runtime migration evidence differs')
    require(data['failed_move_marker_pin']==loaded['failed_move_marker_pin'] and data['current_before']==move._projection(loaded)
      and data['current_before_sha256']==loaded['current_context_sha256'] and canonical_evidence_pins(data['live_pins'])==canonical_evidence_pins(loaded['pins']),'Readback authority differs')
    result=verify_observed_order(loaded['state'],data['observed_context']);require(result['order_verified'] and data['outcome']==result['outcome'],'Requested order not verified')
    require(data['observed_payload']==move.capture._payload(loaded),'Full protected payload differs')
    for name in ('cone','face'):require(data['observed_'+name+'_observation']==loaded[name+'_observation'],'Protected geometry differs')
    current=move._projection(loaded);current['state']=deepcopy(data['observed_context'])
    require(data['current_after']==current and data['current_after_sha256']==_digest(current),'Observed current checkpoint differs')
    oldparent=loaded['parent_pin'];live=[p for p in loaded['pins'] if _key(p['path'])!=_key(oldparent['path'])]
    require(len(live)==len(loaded['pins'])-1,'Only previous completed current authority may retire')
    loaded.update(current,current_context_sha256=_digest(current),pins=canonical_evidence_pins(live,[pin]),parent_pin=pin,
      reconciliation_pin=pin,reconciliation_receipt=data,retired_current_authority_pin=oldparent)
    require(len(loaded['pins'])<=64,'Reconciled current guard bound exceeded');move._check(loaded['pins']);return loaded

PARAMS={'failed_move_receipt_path','failed_move_receipt_sha256','process_id','expected_document_path','expected_source_sha256','receipt_path','addin_clsid','module_sha256','historical_move_module_path','historical_move_module_sha256'}
def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='reconcile_current_operation_order','Only readonly order reconciliation supported')
    p=dict(request['params']);require(set(p)==PARAMS,'Exact readonly request fields required')
    move.integer(p['process_id'],'Owned PID',1)
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_self_pin()['sha256'] and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact module and CLSID required')
    require(p['historical_move_module_sha256']==HISTORICAL_MOVE_SHA256,'Exact historical module SHA required')
    return p


def dispatch_request(request):
    p=validate_request(request)
    history={k:p.pop(k) for k in ('historical_move_module_path','historical_move_module_sha256')}
    loaded=load_reconciliation_parent(p.pop('failed_move_receipt_path'),p.pop('failed_move_receipt_sha256'),
      **history,**{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
    _fresh(loaded,p['receipt_path'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        move._check(loaded['pins']);inventory=discover_cam_installations();require(not inventory['errors'],'Installation discovery errors')
        registration=select_registration(inventory,p.pop('addin_clsid'));p.pop('module_sha256')
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return reconcile_readonly(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),loaded=loaded,**p)

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    args=parser.parse_args(argv);result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({k:result.get(k) for k in ('scope','status','phase','readback_verified','order_verified','outcome','issue','receipt_path')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1
if __name__=='__main__':raise SystemExit(main())
