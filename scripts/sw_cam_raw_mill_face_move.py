"""Move one existing FACE operation with a bounded current checkpoint.

Historical evidence is fully verified offline once, before COM connection.
Native scopes check current authority, source, runtime, inputs and replay guards;
archived predecessors are never read from the native capture path.
"""
from copy import deepcopy
from pathlib import Path
import json,re,math
from scripts import sw_cam_raw_mill_face_operation as capture
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_route_context import integer
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity

SCOPE='ONE_EXISTING_FACE_OPERATION_MOVE_V1'
CONTEXT_SCOPE='CURRENT_FACE_MOVE_CONTEXT_V1'
BEFORE_ORDER=(143,144,195,196,247,248,267)
AFTER_ORDER=(143,144,195,196,267,247,248)
OPERATION_ID=267
ANCHOR_ID=196
SETUP_ID=93
FEATURE_ID=265
# These modules validate only earlier lifecycles. No call into them follows cutover.
OFFLINE_ONLY_RUNTIME=frozenset({'sw_cam_finish_recovery.py','sw_cam_upper_cone_save.py',
 'sw_cam_ud14_save.py','sw_cam_raw_mill_face_save.py','sw_cam_raw_mill_face_operation_recovery.py',
 'sw_cam_raw_mill_face_operation_append_recovery.py'})
EXTRA_NATIVE_RUNTIME=('sw_connect.py','sw_cam_installation.py')
CURRENT_KEYS=('state','payload','finish_payload','ownership','ids','observation_pin','holder_recipe',
 'cone_observation','face_observation','cone_sketch_spec','face_sketch_spec','cone_feature_native_id',
 'face_feature_native_id','source_sha256','qualification','read_mode','base_saved_pin')


def _key(path):return str(Path(path).resolve()).casefold()
def _pin(path):return dict(path=str(Path(path).resolve()),sha256=_file_hash(path))
def _self_pin():return _pin(__file__)
def _check(pins):
    for pin in pins:require(_file_hash(pin['path'])==pin['sha256'],'Current dependency changed')
def _projection(loaded):return {key:deepcopy(loaded[key]) for key in CURRENT_KEYS}


def move_marker(source,source_sha256,original_insert_sha256):
    key=_digest(dict(scope=SCOPE,source=_key(source),source_sha256=source_sha256,
      original_insert_sha256=original_insert_sha256,setup=SETUP_ID,operation=OPERATION_ID,after=ANCHOR_ID,make_copy=False))
    return Path(source).resolve().parent/('face_move_'+key+'.json')


def verify_move_delta(before,after,*,diagnostic=None):
    require(len(before['features'])==len(after['features'])==21 and before['operation_count']==after['operation_count']==7,'Exact21/7 required')
    require(tuple(r['native_id'] for r in before['operations'])==BEFORE_ORDER and tuple(r['native_id'] for r in after['operations'])==AFTER_ORDER,'Exact existing267 reorder required')
    require(before['operation_counts']==after['operation_counts']==[7,0,0],'Operation counts changed')
    require(type(before['document']['needs_save']) is bool and type(after['document']['needs_save']) is bool,'Raw strict SW save flags required')
    require(before['document']['needs_save'] is False,'Only current verified clean-flag append parent supported')
    normalized=deepcopy(after);by_id={r['native_id']:deepcopy(r) for r in after['operations']}
    for index,row in enumerate(after['operations']):
        require(type(row['operation_index']) is int and row['operation_index']==index and row['setup_native_id']==SETUP_ID and row['setup_index']==0,'Unexpected native operation index/setup')
    normalized['operations']=[]
    for index,oid in enumerate(BEFORE_ORDER):
        row=by_id[oid];row['operation_index']=index;normalized['operations'].append(row)
    normalized['document']['needs_save']=before['document']['needs_save']
    detail={} if diagnostic is None else diagnostic
    detail['raw_SW_save_flag_before']=before['document']['needs_save'];detail['raw_SW_save_flag_after']=after['document']['needs_save']
    detail['comparison_only_normalization']=['operation_order_and_indices','observed_SW_save_flag']
    capture.cone.require_state_equivalent(before,normalized,diagnostic=detail.setdefault('state_equivalence',{}))
    return dict(order=list(AFTER_ORDER),raw_SW_save_flag_before=before['document']['needs_save'],raw_SW_save_flag_after=after['document']['needs_save'],make_copy=False)


def _role(pin,parent_key):
    path=Path(pin['path'])
    if _key(path)==parent_key:return 'current_terminal_receipt'
    if path.suffix.casefold() in ('.mt','.mh','.stl'):return 'native_geometry_input'
    if path.name.startswith('_FE488661_'):return 'generated_CAM_typelib'
    if path.suffix.casefold()=='.py':return 'native_runtime_helper'
    if path.suffix.casefold()=='.json':
        data,_=read_pin(pin['path'],pin['sha256'])
        if data.get('automatic_replay') is False:return 'durable_replay_guard'
        if path.name=='76_start_receipt.json':return 'owned_process_startup_evidence'
        return 'retained_native_reference_or_authority'
    raise ValueError('Unclassified current dependency')


def _cutover(loaded,parent_pin):
    original_live=canonical_evidence_pins(loaded['pins']);original_history=canonical_evidence_pins(loaded['lineage_pins'])
    require(len(original_live)<=64 and len(original_history)<=16,'Original bounded proof closure required')
    _check(original_live);_check(original_history)
    runtime=Path(capture.__file__).resolve().parent
    live=[];retired=[];roles=[]
    for pin in original_live:
        p=Path(pin['path'])
        is_old_runtime=_key(p.parent)==_key(runtime) and p.name in OFFLINE_ONLY_RUNTIME
        is_server=p.name=='server.py' and p.parent.name=='mcp-server'
        if is_old_runtime or is_server:retired.append(deepcopy(pin));continue
        live.append(deepcopy(pin));roles.append(dict(pin=deepcopy(pin),role=_role(pin,_key(parent_pin['path']))))
    for p in [_self_pin()]+[_pin(runtime/name) for name in EXTRA_NATIVE_RUNTIME]:
        live.append(p);roles.append(dict(pin=p,role='native_runtime_helper'))
    live=canonical_evidence_pins(live)
    require(len(live)+2<=64,'Current closure must reserve receipt and marker slots')
    require(any(_key(p['path'])==_key(parent_pin['path']) for p in live),'Current terminal receipt must stay live')
    ctx=_projection(loaded)
    provenance=dict(parent_pin=deepcopy(parent_pin),original_live_pins=deepcopy(original_live),original_history_pins=deepcopy(original_history),
      retired_live_runtime=retired,history_validation_scope='ONCE_OFFLINE_BEFORE_NATIVE_CONNECT',historical_stability_during_native_not_claimed=True,
      full_predecessor_semantics_verified=True,archive_deleted=False)
    return dict(**ctx,pins=live,lineage_pins=[],current_context_sha256=_digest(ctx),parent_pin=deepcopy(parent_pin),
      dependency_roles=roles,predecessor_validation=provenance,original_insert_pin=deepcopy(loaded['failed_pin']),
      original_insert_marker_pin=deepcopy(loaded['failed_marker_pin']),historical_only=False)


def load_move_parent(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    """Full predecessor proof once offline. Never called from native capture."""
    from scripts.sw_cam_raw_mill_face_operation_append_recovery import load_completed_face_operation_recovery
    loaded=load_completed_face_operation_recovery(path,digest,process_id=process_id,expected_document_path=expected_document_path,
      expected_source_sha256=expected_source_sha256,expected_feature_native_id=FEATURE_ID,expected_operation_native_id=OPERATION_ID)
    state=loaded['state'];require(tuple(row['native_id'] for row in state['operations'])==BEFORE_ORDER and state['document']['needs_save'] is False,'Exact terminal appended route required')
    require(loaded['failure_resolved'] is True and loaded['face_feature_native_id']==FEATURE_ID,'Actual completed recovery required')
    return _cutover(loaded,loaded['recovery_pin'])


class CurrentMoveContext(capture.cone.UpperConeContext):
    def files(self):
        require(_digest(_projection(self.loaded))==self.loaded['current_context_sha256'],'Current immutable context changed')
        _check(self.loaded['pins'])


def _fresh_output(loaded,path,marker,source):
    target=Path(path);allpins=loaded['pins']+loaded['predecessor_validation']['original_live_pins']+loaded['predecessor_validation']['original_history_pins']
    protected={_key(p['path']) for p in allpins}|{_key(source)}
    require(target.is_absolute() and target.parent.is_dir() and target.suffix.casefold()=='.json' and not target.exists() and not target.is_symlink(), 'Fresh move receipt required')
    require(not marker.exists() and not marker.is_symlink() and _key(target)!=_key(marker) and _key(target) not in protected and _key(marker) not in protected,'Attempt exists or outputs alias evidence')
    return target


def native_return_observation(value):
    """先保存有界的原始返回值，再验证 HRESULT；不调用未知对象的表示方法。"""
    kind=type(value)
    exact=(value is None or kind is bool or (kind is int and -(2**63)<=value<2**63)
      or (kind is float and math.isfinite(value)) or (kind is str and len(value)<=256))
    return dict(native_return_type=kind.__name__[:128],native_return_value=value if exact else None,
      native_return_value_recorded=exact,native_return_is_none=value is None,
      native_return_limit_reason='' if exact else 'unsupported_or_unbounded_native_value')


def require_move_return(value):
    require(type(value) is int and value==0,'InsertOperationAfter requires strict HRESULT S_OK integer zero')


def _run_move(sw,clsid,typelib_path,*,loaded,process_id,expected_document_path,expected_source_sha256,
        receipt_path,qualification_only,acknowledge_disposable_copy):
    from scripts.sw_cam_events import CamMessageSession
    require(qualification_only is True and acknowledge_disposable_copy is True,'Explicit disposable qualification required')
    marker=move_marker(expected_document_path,expected_source_sha256,loaded['original_insert_pin']['sha256'])
    receipt=_fresh_output(loaded,receipt_path,marker,expected_document_path)
    args=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,**loaded['ids'])
    report=dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',process_id=process_id,
      source_path=expected_document_path,source_sha256=expected_source_sha256,module_pin=_self_pin(),
      parent_pin=deepcopy(loaded['parent_pin']),current_before=_projection(loaded),current_before_sha256=loaded['current_context_sha256'],
      live_pins=deepcopy(loaded['pins']),dependency_roles=deepcopy(loaded['dependency_roles']),
      predecessor_validation=deepcopy(loaded['predecessor_validation']),original_insert_pin=deepcopy(loaded['original_insert_pin']),
      original_insert_marker_pin=deepcopy(loaded['original_insert_marker_pin']),receipt_path=str(receipt),marker_path=str(marker),
      operation_native_id=OPERATION_ID,after_operation_native_id=ANCHOR_ID,setup_native_id=SETUP_ID,make_copy=False,
      mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,move_call_count=0,
      creator_attempted=False,copy_attempted=False,tool_assignment_attempted=False,GOP_attempted=False,GTP_attempted=False,
      save_attempted=False,model_saved=False,set_save_flag_attempted=False,automatic_replay=False,automatic_retry=False,
      automatic_rollback=False,readback_verified=False,order_verified=False,recipe_qualified=False,production_qualified=False,
      snapshot_diagnostics=[],archive_reads_during_native_phase=0,archive_stability_during_native_phase_claimed=False)
    created=claimed=False;ctx=session=None
    def persist():
        if created:_write_receipt(receipt,report)
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
          and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM events require stop')
    def observe(phase):
        report['phase']=phase;diag=dict(phase=phase);report['snapshot_diagnostics'].append(diag);persist()
        try:
            state,native=capture._capture_headers(ctx,clsid,loaded['state'],21,diag,nullable_operation_id=OPERATION_ID)
            report[phase+'_context']=deepcopy(state);persist()
            payload=capture._capture_payload(ctx,state,native,diag,nullable_operation_id=OPERATION_ID)
            report[phase+'_payload']=deepcopy(payload);persist()
            co=capture.cone._read_sketch_and_cone(ctx,native,loaded['cone_sketch_spec'],loaded['cone_feature_native_id'])
            report[phase+'_cone_observation']=deepcopy(co);persist();fd={};report[phase+'_face_observation']=fd
            fo=capture.face._read_face(ctx,native,loaded['face_sketch_spec'],FEATURE_ID,diagnostic=fd,persist=persist)
            report[phase+'_face_observation']=deepcopy(fo);persist()
            require(co==loaded['cone_observation'] and fo==loaded['face_observation'],'Protected cone/FACE geometry changed')
            return state,native,payload
        finally:persist()
    def pending():
        nonlocal claimed
        require(report['move_call_count']==0,'Exactly one move allowed')
        _write_receipt(marker,dict(scope=SCOPE,status='dispatch_pending',source=expected_document_path,source_sha256=expected_source_sha256,
          original_insert_sha256=loaded['original_insert_pin']['sha256'],operation_native_id=OPERATION_ID,after_operation_native_id=ANCHOR_ID,
          setup_native_id=SETUP_ID,make_copy=False,receipt_path=str(receipt),automatic_replay=False),create=True)
        claimed=True;report.update(phase='InsertOperationAfter',mutation_attempted=True,native_call_attempted=True,native_dispatch_pending=True,move_call_count=1);persist()
    try:
        _write_receipt(receipt,report,create=True);created=True
        ctx=CurrentMoveContext(loaded,args,sw,typelib_path,None,events,loaded['state'])
        ctx.files();ctx.identity();ctx.app=capture.cone._bootstrap(sw,clsid,typelib_path,expected_document_path);ctx.identity()
        session=CamMessageSession(ctx.app,typelib_path)
        with session:
            before,native,bp=observe('before');report['before_equivalence']={}
            capture.cone.require_state_equivalent(loaded['state'],before,diagnostic=report['before_equivalence']);persist()
            require(bp==capture._payload(loaded),'Protected before payload changed')
            from comtypes.automation import IDispatch
            with ctx.guard() as g:
                setups=capture._items(g.read(native['machine'],'IGetEnumOpSetups'),g.typed,g.read,3)
                typed=[g.typed(v,'ICWBaseOpSetup') for v in setups]
                require([_object_id(native['doc'],v,g.read) for v in typed]==[93,94,95],'Current operation setups changed')
                moving=g.typed(native['operations'][OPERATION_ID],'ICWOperation');anchor=g.typed(native['operations'][ANCHOR_ID],'ICWOperation')
                require(_object_id(native['doc'],moving,g.read)==OPERATION_ID and _object_id(native['doc'],anchor,g.read)==ANCHOR_ID,'Current existing operation identities changed')
                moving_dispatch=g.read(moving,'QueryInterface',IDispatch);anchor_dispatch=g.read(anchor,'QueryInterface',IDispatch)
                require(_object_id(native['doc'],moving_dispatch,g.read)==OPERATION_ID and _object_id(native['doc'],anchor_dispatch,g.read)==ANCHOR_ID,'Dispatch identities changed')
                result=g.dispatch_once(lambda:_member(typed[0],'InsertOperationAfter',moving_dispatch,anchor_dispatch,False),persist_pending=pending)
                report.update(native_call_returned=True,native_dispatch_pending=False,**native_return_observation(result));persist()
            report['dispatch_guard']=g.summary();persist();require_move_return(result)
            actual=raw_part_identity(sw);report['document_after_move']=deepcopy(actual);persist()
            require(type(actual.get('needs_save')) is bool,'Strict actual SW save flag required')
            expected=deepcopy(before['document']);expected['needs_save']=actual['needs_save']
            require(actual==expected and _file_hash(expected_document_path)==expected_source_sha256,'Move changed document identity or disk source')
            ctx.expected_document=deepcopy(actual);ctx.files();ctx.identity();events()
            after,native,ap=observe('after');report['move_delta']={}
            verify_move_delta(before,after,diagnostic=report['move_delta'])
            require(ap==bp,'Protected old payload changed')
        events(False);ctx.files();require(ctx.identity()==after['document'],'Document changed during cleanup')
        current=_projection(loaded);current['state']=deepcopy(after)
        report.update(status='review_required',phase='finished',readback_verified=True,order_verified=True,
          current_after=current,current_after_sha256=_digest(current),source_after_sha256=_file_hash(expected_document_path),
          reason='EXISTING267_MOVED_AFTER196_NO_COPY_OR_GENERATION',native_order_only=True,physical_sequence_qualified=False)
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,order_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:
            persist()
            if claimed:_write_receipt(marker,dict(scope=SCOPE,status=report['status'],source=expected_document_path,source_sha256=expected_source_sha256,
              original_insert_sha256=loaded['original_insert_pin']['sha256'],operation_native_id=OPERATION_ID,after_operation_native_id=ANCHOR_ID,
              setup_native_id=SETUP_ID,make_copy=False,receipt_path=str(receipt),receipt_sha256=_file_hash(receipt),
              native_call_attempted=report['native_call_attempted'],native_call_returned=report['native_call_returned'],readback_verified=report['readback_verified'],automatic_replay=False))
        except Exception as exc:report.update(status='uncertain',readback_verified=False,order_verified=False,receipt_write_error=_error(exc))
    return report


def load_completed_move(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    """Flat current-state successor. Archive hashes are checked only offline."""
    data,pin=read_pin(path,digest)
    require(data.get('scope')==SCOPE and data.get('status')=='review_required' and data.get('phase')=='finished'
      and data.get('module_pin')==_self_pin(),'Exact completed move required')
    require(data.get('process_id')==process_id and _key(data['source_path'])==_key(expected_document_path)
      and data['source_sha256']==data['source_after_sha256']==expected_source_sha256,'Exact source/PID binding required')
    require(type(data.get('move_call_count')) is int and data['move_call_count']==1 and data.get('native_return_type')=='int' and type(data.get('native_return_value')) is int and data['native_return_value']==0
      and data.get('native_return_value_recorded') is True and data.get('native_return_limit_reason')==''
      and all(data.get(k) is True for k in ('mutation_attempted','native_call_attempted','native_call_returned','readback_verified','order_verified'))
      and all(data.get(k) is False for k in ('native_return_is_none','native_dispatch_pending','make_copy','creator_attempted','copy_attempted','tool_assignment_attempted','GOP_attempted',
      'GTP_attempted','save_attempted','model_saved','set_save_flag_attempted','automatic_replay','automatic_retry','automatic_rollback','recipe_qualified','production_qualified'))
      and not any(k in data for k in ('issue','failed_phase','receipt_write_error')),'Uncertain or broadened move forbidden')
    require(data['operation_native_id']==OPERATION_ID and data['after_operation_native_id']==ANCHOR_ID and data['setup_native_id']==SETUP_ID,'Move target differs')
    clean_events(data);parent,parentpin=read_pin(data['parent_pin']['path'],data['parent_pin']['sha256'])
    require(parent.get('scope')=='RAW_MILL_FACE_APPEND_READONLY_RECOVERY_V1' and parent.get('phase')=='finished' and parent.get('status')=='observed'
      and all(parent.get(k) is True for k in ('read_only','readback_verified','state_recovered','original_failure_resolved'))
      and parent.get('route_order_qualified') is False and parent.get('placement_verified')=='APPENDED267_AFTER248_NOT_REQUESTED_AFTER196'
      and parent['process_id']==process_id and parent['source_sha256']==expected_source_sha256
      and parent['face_feature_native_id']==FEATURE_ID and parent['new_operation_native_id']==OPERATION_ID,'Completed append authority differs')
    cp=parent['checkpoint'];require(parent['checkpoint_sha256']==_digest(cp),'Parent current checkpoint changed')
    current=data['current_before'];require(set(current)==set(CURRENT_KEYS) and data['current_before_sha256']==_digest(current),'Current before digest/schema differs')
    require(current['state']==cp['state'] and dict(rough=current['payload'],finish=current['finish_payload'])==cp['payload']
      and current['cone_observation']==cp['cone_observation'] and current['face_observation']==cp['face_observation']
      and current['source_sha256']==expected_source_sha256,'Current before differs from parent authority')
    for key in ('cone_sketch_spec','face_sketch_spec','cone_feature_native_id','face_feature_native_id'):
        require(current[key]==cp[key],'Current geometry binding differs')
    failed=parent['failed_pin']
    require(data['original_insert_pin']==failed and data['original_insert_marker_pin']==parent['failed_marker_pin'],'Original insertion provenance differs')
    original_live=canonical_evidence_pins([v for v in parent['evidence_pins'] if _key(v['path'])!=_key(failed['path'])],[parentpin])
    original_history=canonical_evidence_pins(parent['lineage_pins'],[failed]);proof=data['predecessor_validation']
    require(canonical_evidence_pins(proof['original_live_pins'])==original_live and canonical_evidence_pins(proof['original_history_pins'])==original_history,'Original grouped archive closure differs')
    reconstructed=dict(current,pins=original_live,lineage_pins=original_history,failed_pin=failed,failed_marker_pin=parent['failed_marker_pin'])
    loaded=_cutover(reconstructed,parentpin)
    require(data['predecessor_validation']==loaded['predecessor_validation'] and data['dependency_roles']==loaded['dependency_roles']
      and canonical_evidence_pins(data['live_pins'])==canonical_evidence_pins(loaded['pins']),'Current dependency roles differ')
    capture.cone.require_state_equivalent(current['state'],data['before_context'])
    verify_move_delta(data['before_context'],data['after_context'])
    require(data['before_payload']==data['after_payload']==dict(rough=current['payload'],finish=current['finish_payload']),'Protected payload differs')
    for label in ('cone','face'):
        require(data['before_'+label+'_observation']==data['after_'+label+'_observation']==current[label+'_observation'],'Protected geometry differs')
    after=deepcopy(current);after['state']=deepcopy(data['after_context'])
    require(data['current_after']==after and data['current_after_sha256']==_digest(after),'Current after checkpoint differs')
    marker=move_marker(expected_document_path,expected_source_sha256,failed['sha256']);mark,markpin=read_pin(str(marker),_file_hash(marker))
    require(_key(data['marker_path'])==_key(marker) and mark.get('scope')==SCOPE and mark.get('status')=='review_required'
      and _key(mark['source'])==_key(expected_document_path) and mark['source_sha256']==expected_source_sha256
      and mark['original_insert_sha256']==failed['sha256'] and mark['operation_native_id']==OPERATION_ID and mark['after_operation_native_id']==ANCHOR_ID
      and mark['setup_native_id']==SETUP_ID and mark.get('make_copy') is False and mark.get('native_call_attempted') is True
      and mark.get('native_call_returned') is True and mark.get('readback_verified') is True and mark.get('automatic_replay') is False
      and _key(mark['receipt_path'])==_key(path) and mark['receipt_sha256']==digest,'Completed one-shot move marker differs')
    require(_file_hash(expected_document_path)==expected_source_sha256,'Current saved source changed')
    loaded.update(after,current_context_sha256=_digest(after),parent_pin=pin,move_marker_pin=markpin,move_receipt=data)
    loaded['pins']=canonical_evidence_pins(loaded['pins'],[pin,markpin]);require(len(loaded['pins'])<=64,'Completed current guard bound exceeded')
    _check(loaded['pins']);return loaded

PARAMS={'recovery_receipt_path','recovery_receipt_sha256','process_id','expected_document_path','expected_source_sha256',
 'receipt_path','qualification_only','acknowledge_disposable_copy','addin_clsid','module_sha256'}

def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='move_existing_face_after196','Only one existing FACE move supported')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact move fields required');integer(p['process_id'],'Owned PID',1)
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_self_pin()['sha256'] and p['qualification_only'] is True and p['acknowledge_disposable_copy'] is True,'Exact module and disposable qualification required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact CLSID required')
    return dict(p)


def dispatch_request(request):
    p=validate_request(request)
    loaded=load_move_parent(p.pop('recovery_receipt_path'),p.pop('recovery_receipt_sha256'),**{key:p[key] for key in ('process_id','expected_document_path','expected_source_sha256')})
    marker=move_marker(p['expected_document_path'],p['expected_source_sha256'],loaded['original_insert_pin']['sha256'])
    _fresh_output(loaded,p['receipt_path'],marker,p['expected_document_path'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        _check(loaded['pins']);inventory=discover_cam_installations();require(not inventory['errors'],'Installation discovery errors')
        registration=select_registration(inventory,p.pop('addin_clsid'));p.pop('module_sha256')
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return _run_move(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),loaded=loaded,**p)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    args=parser.parse_args(argv);result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({key:result.get(key) for key in ('scope','status','phase','readback_verified','order_verified','issue','receipt_path')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1

if __name__=='__main__':raise SystemExit(main())


