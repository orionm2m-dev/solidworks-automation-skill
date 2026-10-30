"""One selected MILL GOP or one checked native save in an observed 18-feature scope."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_profile_headers import validate_profile_headers_request
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan,exact_dispatch_target
from scripts.sw_cam_mill_selected_plan_evidence import (
    SCOPE,load_selected_plan_evidence,load_plan_receipt,read_pin,same,same_saved_context)
from scripts.sw_operation_guard import check_document_target

def verify_plan_delta(before,after,feature_id,operation_setup_id):
    if before['operations'] or any(before['operation_counts']) or before['operation_count']!=0:
        raise ValueError('Plan is one-shot from exactly zero operations; do not replay')
    rows=after['operations']
    if not 1<=len(rows)<=32 or after['operation_count']!=len(rows):
        raise ValueError('Expected 1..32 newly observed operation definitions')
    old_setups=before['operation_setups'];new_setups=after['operation_setups']
    if (len(old_setups)!=len(new_setups) or
        [(r['index'],r['native_id']) for r in old_setups]!=[(r['index'],r['native_id']) for r in new_setups]):
        raise ValueError('Unexpected operation-setup insertion, removal or identity change')
    if len(after['operation_counts'])!=len(old_setups) or sum(after['operation_counts'])!=len(rows):
        raise ValueError('Operation setup counts differ')
    ids=[r['native_id'] for r in rows]
    if any(type(v) is not int or not 0<v<2**32 for v in ids) or len(set(ids))!=len(ids):
        raise ValueError('Unique bounded new operation IDs required')
    for si,setup in enumerate(new_setups):
        current=[r for r in rows if r['setup_index']==si]
        if (len(current)!=after['operation_counts'][si] or setup['operation_count']!=len(current)
            or [r['operation_index'] for r in current]!=list(range(len(current)))):
            raise ValueError('Operation order/count drift')
        if any(r['setup_native_id']!=setup['native_id'] for r in current):
            raise ValueError('Operation setup linkage drift')
    for r in rows:
        if (r['setup_native_id']!=operation_setup_id or r['linked_feature_ids']!=[feature_id] or r['suppressed'] is not False
            or r['toolpath_generated'] is not False or any(r['toolpath_record_counts'])):
            raise ValueError('New definitions must link only to selected feature and contain no generated paths')
    expected=deepcopy(before)
    for k in ('operations','operation_setups','operation_counts','operation_count','operation_setup_count',
              'operation_inventory_scope'):
        expected[k]=deepcopy(after[k])
    expected['document']['needs_save']=after['document']['needs_save']
    if not same(expected,after):raise ValueError('Unrequested observed context change after GOP')
    return deepcopy(rows)

def validate_selected_plan_request(*,action,expected_operation_setup_native_id,profile_headers_receipt_path,profile_headers_receipt_sha256,
        profile_indexed_receipt_path,profile_indexed_receipt_sha256,
        diagnostic_inventory_receipt_path,diagnostic_inventory_receipt_sha256,
        plan_receipt_path=None,plan_receipt_sha256=None,**base):
    validate_profile_headers_request(**base)
    if type(expected_operation_setup_native_id) is not int or not 0<expected_operation_setup_native_id<2**32:
        raise ValueError("Exact bounded expected operation setup ID required")
    if action not in ('plan_once','save_checked'):raise ValueError('Only plan_once/save_checked supported')
    pairs=[(profile_headers_receipt_path,profile_headers_receipt_sha256),
           (profile_indexed_receipt_path,profile_indexed_receipt_sha256),
           (diagnostic_inventory_receipt_path,diagnostic_inventory_receipt_sha256)]
    if action=='save_checked':
        if plan_receipt_path is None or plan_receipt_sha256 is None:raise ValueError('Successful pinned plan receipt required')
        pairs.append((plan_receipt_path,plan_receipt_sha256))
    elif plan_receipt_path is not None or plan_receipt_sha256 is not None:
        raise ValueError('plan_once rejects a prior-plan receipt')
    resolved=[]
    for p,s in pairs:
        _,pin=read_pin(p,s);resolved.append(pin['canonical_path'].casefold())
    if len(set(resolved))!=len(resolved):raise ValueError('Distinct evidence receipts required')
    if str(Path(base['receipt_path']).resolve()).casefold() in resolved:
        raise ValueError('Output cannot replace input evidence')

def selected_mill_plan_lifecycle(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,expected_feature_native_id,expected_owner_setup_native_id,
        expected_volume_type,expected_shape,expected_island_count,expected_operation_setup_native_id,action,qualification_only,
        acknowledge_disposable_copy,receipt_path,profile_headers_receipt_path,
        profile_headers_receipt_sha256,profile_indexed_receipt_path,profile_indexed_receipt_sha256,
        diagnostic_inventory_receipt_path,diagnostic_inventory_receipt_sha256,
        plan_receipt_path=None,plan_receipt_sha256=None,message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status='error',phase='preflight',action=action,process_id=process_id,
        expected_operation_setup_native_id=expected_operation_setup_native_id,
        mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        native_dispatch_pending=False,native_hresult=None,GOP_attempted=False,save_attempted=False,
        readback_verified=False,operation_delta_verified=False,save_readback_verified=False,
        model_saved=False,GTP_attempted=False,AFR_attempted=False,tool_assignment_attempted=False,
        stock_edit_attempted=False,geometry_edit_attempted=False,TechDB_write_attempted=False,
        full_inventory_verified=False,world_geometry_verified=False,units_verified=False,
        actual_incoming_WIP_verified=False,holder_clearance_verified=False,production_qualified=False,
        reopen_persistence_verified=False,post_cleanup_CAM_getters=False,may_continue=False,
        diagnostic_baseline_promoted=False,snapshot_diagnostics=[],
        snapshot_scope='18 observed feature headers, selected PROFILE metadata, setup/stock/options/SW fingerprints and operation definitions; not full BRep or world contours')
    session=None;created=False;receipt=None;evidence=None;plan=None;plan_pin=None
    current_source=expected_source_sha256
    selected=dict(feature_native_id=expected_feature_native_id,owner_setup_native_id=expected_owner_setup_native_id,
                  volume_type=expected_volume_type,shape=expected_shape,island_count=expected_island_count,
                  include_contours=False)
    anchor_args=dict(profile_headers_receipt_path=profile_headers_receipt_path,
        profile_headers_receipt_sha256=profile_headers_receipt_sha256,
        profile_indexed_receipt_path=profile_indexed_receipt_path,
        profile_indexed_receipt_sha256=profile_indexed_receipt_sha256,
        diagnostic_inventory_receipt_path=diagnostic_inventory_receipt_path,
        diagnostic_inventory_receipt_sha256=diagnostic_inventory_receipt_sha256)
    def persist():
        if created:_write_receipt(receipt,report)
    def check_pins():
        evidence.check_files()
        if plan_pin is not None:
            _,pin=read_pin(plan_receipt_path,plan_receipt_sha256)
            if pin!=plan_pin:raise ValueError('Pinned successful plan changed')
    def identity():
        pid=_member(sw,'GetProcessID')
        if type(pid) is not int or pid!=process_id:raise ValueError('Exact process changed')
        doc=raw_part_identity(sw)
        check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True)
        if _file_hash(expected_document_path)!=current_source:raise ValueError('Saved source differs')
        return doc
    def check(active=True):
        s=session.summary();report['messages']=s
        if (s.get('subscribed') is not True or (active and s.get('active') is not True)
            or (not active and (s.get('active') is not False or s.get('disconnected') is not True))
            or any(s.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count',
                                      'subscription_error','disconnect_errors'))):
            raise ValueError('CAM event/transport requires stop; no replay')
    def capture(phase):
        check();check_pins();report['phase']=phase
        diagnostic=dict(phase=phase);report['snapshot_diagnostics'].append(diagnostic);persist()
        state,native=capture_selected_plan(sw,clsid,typelib_path,expected_document_path,
            process_id=process_id,expected_source_sha256=current_source,evidence=evidence,
            check=check,diagnostic=diagnostic,progress=persist)
        check();check_pins();evidence.verify(state);return state,native
    try:
        base=dict(process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id,
            expected_owner_setup_native_id=expected_owner_setup_native_id,expected_volume_type=expected_volume_type,
            expected_shape=expected_shape,expected_island_count=expected_island_count,
            qualification_only=qualification_only,acknowledge_disposable_copy=acknowledge_disposable_copy,
            receipt_path=receipt_path,message_policy=message_policy)
        validate_selected_plan_request(action=action,expected_operation_setup_native_id=expected_operation_setup_native_id,plan_receipt_path=plan_receipt_path,
            plan_receipt_sha256=plan_receipt_sha256,**anchor_args,**base)
        evidence=load_selected_plan_evidence(process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,selected=selected,**anchor_args)
        if action=='save_checked':
            plan,plan_pin=load_plan_receipt(plan_receipt_path,plan_receipt_sha256,
                                          evidence=evidence,process_id=process_id,expected_operation_setup_native_id=expected_operation_setup_native_id)
        report.update(anchor=evidence.summary(),selected=selected,source_before_sha256=current_source,
                      plan_receipt=plan_pin)
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        baseline=identity();check_pins()
        if action=='plan_once' and baseline['needs_save'] is not False:
            raise ValueError('Plan requires clean saved qualification part')
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Document changed acquiring event host')
        session=CamMessageSession(app,typelib_path)
        with session:
            before,native=capture('before')
            report['before']=before;persist()
            if before['document']!=baseline:raise ValueError('Initial identity changed')
            if action=='plan_once':
                if expected_operation_setup_native_id not in [r['native_id'] for r in before['operation_setups']]:
                    raise ValueError('Expected operation setup is absent')
                if before['operations'] or before['operation_count']!=0 or any(before['operation_counts']):
                    raise ValueError('One-shot planning requires zero operations; do not replay')
            elif not same(before,plan['after']):
                raise ValueError('Current definitions/context differ from successful plan receipt')
            check();check_pins()
            def dispatch_read(obj,name,*args):
                check()
                if identity()!=before['document']:raise ValueError('Identity changed before native dispatch')
                value=_member(obj,name,*args)
                check()
                if identity()!=before['document']:raise ValueError('Identity changed during target check')
                return value
            if action=='plan_once':
                target=exact_dispatch_target(native,evidence,dispatch_read)
                method='GenerateOpPlan';args=(1,)
            else:
                check();target=_typed(native['app'],'ICWApp',typelib_path);check()
                method='SaveActiveDocument';args=()
            if identity()!=before['document']:raise ValueError('Document changed before dispatch')
            check_pins();check()
            report.update(phase=method,native_dispatch_pending=True,mutation_attempted=True,
                          native_call_attempted=True)
            report['GOP_attempted' if action=='plan_once' else 'save_attempted']=True
            persist()
            result=_member(target,method,*args)
            report.update(native_call_returned=True,native_dispatch_pending=False,
                          native_hresult=result if type(result) is int else None,
                          native_return_type=type(result).__name__,phase='native_returned')
            persist();check()
            if type(result) is not int or result!=0:raise ValueError('Unexpected HRESULT/no-OUT result; do not replay')
            if action=='save_checked':
                current_source=_file_hash(expected_document_path)
                report['source_after_sha256']=current_source;persist()
            after,_=capture('after')
            report['after']=after;persist()
            if action=='plan_once':
                report['new_operations']=verify_plan_delta(before,after,expected_feature_native_id,expected_operation_setup_native_id)
            elif not same_saved_context(before,after) or after['document']['needs_save'] is not False:
                raise ValueError('Save changed observed CAM context or left document dirty')
            check()
        check(active=False);check_pins()
        if identity()!=after['document']:raise ValueError('Identity changed during event cleanup')
        check(active=False)
        report.update(status='review_required',phase='finished',readback_verified=True,
            operation_delta_verified=action=='plan_once',save_readback_verified=action=='save_checked',
            model_saved=action=='save_checked',state_sha256=_digest(after),
            saved_file_sha256=current_source,original_source_sha256=evidence.original_source,
            continuation_scope=SCOPE,continuation_state=deepcopy(after),
            reason='SCOPED_OPERATION_DEFINITIONS_ONLY_NO_GTP_WORLD_GEOMETRY_OR_MANUFACTURING_QUALIFICATION')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,
            operation_delta_verified=False,save_readback_verified=False,model_saved=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:
            report.update(status='uncertain' if report['mutation_attempted'] else 'error',
                          receipt_write_error=_error(exc),readback_verified=False,
                          operation_delta_verified=False,save_readback_verified=False,model_saved=False)
    return report
