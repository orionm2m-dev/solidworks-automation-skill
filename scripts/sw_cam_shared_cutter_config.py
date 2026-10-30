"""Bounded shared-tool batch with optional verified native save; no GOP, GTP or library writes."""
from contextlib import ExitStack
from copy import deepcopy
from functools import partial
from pathlib import Path
import time
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_shared_cutter_geometry import FIELDS,INTEGER_FIELDS,values,close,verify_full_delta
from scripts.sw_cam_shared_cutter_evidence import load_cutter_evidence,SCOPE
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import same_saved_context
from scripts.sw_operation_guard import check_document_target
from scripts.sw_cam_shared_holder_geometry import read_holder_recipe,check_holder_pins,apply_holder_reference

MAX_BATCH_GETTERS=1024


def _equal(prop,a,b):
    return type(a) is int and a==b if prop in INTEGER_FIELDS else close(a,b)


def apply_property_batch(*,targets,old_values,target,read,guard,persist,report):
    """Typed-pointer writer with a durable marker and immediate readback per field.

    Native coupling may advance another declared field exactly to its target.
    Any other changed value stops this batch; no replay or rollback is attempted.
    """
    current=dict(old_values)
    for prop,section,_ in FIELDS:
        guard()
        obj=targets['ICWMillTool'] if section else targets['ICWTool']
        actual=read(obj,prop)
        if not _equal(prop,actual,current[prop]):
            raise ValueError('Tool field changed before setter: '+prop)
        entry=dict(property=prop,interface='ICWMillTool' if section else 'ICWTool',
            previous_native=actual,requested_native=target[prop],setter_attempted=False,
            native_call_returned=False,readback_verified=False,native_dispatch_pending=False)
        report['field_attempts'].append(entry)
        report['phase']='field:'+prop
        if _equal(prop,actual,target[prop]):
            entry.update(status='already_observed_at_target',readback_verified=True)
            persist();continue
        guard()
        entry.update(status='dispatch_pending',setter_attempted=True,native_dispatch_pending=True)
        report.update(mutation_attempted=True,native_call_attempted=True,native_dispatch_pending=True)
        persist()
        guard()
        started=time.monotonic()
        setattr(obj,prop,int(target[prop]) if prop in INTEGER_FIELDS else float(target[prop]))
        entry.update(native_call_returned=True,native_dispatch_pending=False,
                     native_call_seconds=time.monotonic()-started,status='returned')
        report.update(native_call_returned=True,native_dispatch_pending=False)
        persist()
        guard()
        immediate=read(obj,prop)
        entry['immediate_readback_native']=immediate
        if not _equal(prop,immediate,target[prop]):
            raise ValueError('Native setter did not read back requested field: '+prop)
        observed={}
        for other,sub,_ in FIELDS:
            pointer=targets['ICWMillTool'] if sub else targets['ICWTool']
            v=read(pointer,other);observed[other]=v
            if not (_equal(other,v,current[other]) or _equal(other,v,target[other])):
                raise ValueError('Undeclared coupled property change: '+other)
        if not _equal(prop,observed[prop],target[prop]):
            raise ValueError('Requested field changed during immediate reread')
        current=observed
        entry.update(status='readback_verified',readback_verified=True,
                     all_declared_fields_after=deepcopy(observed))
        guard();persist()
    if not all(_equal(k,current[k],target[k]) for k in current):
        raise ValueError('Incomplete property batch')
    return current


def configure_shared_cutter(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,saved_plan_receipt_path,saved_plan_receipt_sha256,
        tools_receipt_path,tools_receipt_sha256,nominal_geometry_receipt_path,
        nominal_geometry_receipt_sha256,expected_feature_native_id,expected_operation_native_ids,
        expected_operation_setup_native_id,expected_tool_native_id,target_geometry,
        qualification_only,acknowledge_disposable_copy,receipt_path,message_policy='vendor_default',
        session_rebind_receipt_path=None,session_rebind_receipt_sha256=None,
        holder_file_path=None,holder_file_sha256=None,holder_recipe_path=None,holder_recipe_sha256=None,save_after_verified=False):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status='error',phase='preflight',process_id=process_id,
        mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        native_dispatch_pending=False,native_hresult_observable=False,property_assignment=True,
        readback_verified=False,cutter_profile_readback_verified=False,holder_profile_readback_verified=False,model_saved=False,
        AFR_attempted=False,GOP_attempted=False,GTP_attempted=False,simulation_attempted=False,
        stock_edit_attempted=False,material_edit_attempted=False,tool_assignment_attempted=False,
        TechDB_write_attempted=False,post_cleanup_CAM_getters=False,
        native_units_qualified=False,physical_tool_identity_verified=False,
        physical_holder_qualified=False,holder_clearance_verified=False,
        assembled_tool_qualified=False,production_qualified=False,may_continue=False,
        automatic_replay=False,automatic_rollback=False,holder_assignment_performed=False,
        field_attempts=[],snapshot_diagnostics=[],native_batch_getters=0)
    created=False;receipt=None;session=None;evidence=None;baseline=None;files=[];holder_recipe=None
    current_source=expected_source_sha256
    def persist():
        if created:_write_receipt(receipt,report)
    def identity():
        pid=_member(sw,'GetProcessID')
        if type(pid) is not int or pid!=process_id:raise ValueError('Exact process changed')
        d=raw_part_identity(sw)
        check_document_target(d['path'],d['title'],expected_path=expected_document_path,required=True)
        if type(d.get('type')) is not int or d['type']!=1 or type(d.get('needs_save')) is not bool:
            raise ValueError('Strict active part identity required')
        if _file_hash(expected_document_path)!=current_source:raise ValueError('Saved source changed')
        evidence.check_files()
        evidence.check_runtime_identity()
        if holder_recipe is not None:check_holder_pins(holder_recipe)
        if baseline is not None:
            expected=deepcopy(baseline);expected['needs_save']=d['needs_save']
            if d!=expected:raise ValueError('Active document identity changed')
        return d
    def check(active=True):
        s=session.summary();report['messages']=s
        if (s.get('subscribed') is not True or (active and s.get('active') is not True)
            or (not active and (s.get('active') is not False or s.get('disconnected') is not True))
            or any(s.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count',
                                     'subscription_error','disconnect_errors'))):
            raise ValueError('CAM event/transport requires stop')
    def fast_guard():
        check()
        for f in files:f.check()
        check()
    def read(obj,name,*args):
        fast_guard()
        if report['native_batch_getters']>=MAX_BATCH_GETTERS:raise ValueError('Native getter budget exceeded')
        report['native_batch_getters']+=1
        v=_member(obj,name,*args);fast_guard();return v
    def typed(obj,name):
        fast_guard();v=_typed(obj,name,typelib_path);fast_guard()
        if v is None:raise ValueError('Missing typed tool/operation pointer')
        return v
    def capture(phase):
        report['phase']=phase;diag=dict(phase=phase);report['snapshot_diagnostics'].append(diag);persist()
        check();begin=identity()
        state,native=capture_selected_plan(sw,clsid,typelib_path,expected_document_path,
            process_id=process_id,expected_source_sha256=current_source,evidence=evidence,
            check=check,diagnostic=diag,progress=persist,
            operation_details_reader=partial(read_selected_operation_tool_details,
                                              feature_native_id=expected_feature_native_id))
        details=deepcopy(diag['operation_details']['selected_tool_details'])
        if identity()!=begin or state['document']!=begin:raise ValueError('Capture identity changed')
        if (details.get('metadata_read_complete') is not True or details.get('profile_complete') is not True
            or details.get('generic_operation_context_unchanged') is not True
            or details.get('canonical_state_changed') is not False
            or [x['operation_native_id'] for x in details['items']]!=expected_operation_native_ids):
            raise ValueError('Complete equal shared tool captures required')
        full=details['items'][0]['full_tool']
        if any(x['full_tool']!=full or x.get('status')!='observed' for x in details['items']):
            raise ValueError('Shared tool users disagree')
        report[phase]=state;report[phase+'_tool_details']=details;persist()
        return state,native,details,full
    try:
        if type(save_after_verified) is not bool:raise ValueError('Explicit strict save policy required')
        report.update(save_attempted=False,save_readback_verified=False,save_after_verified=save_after_verified)
        validate_inventory_request(process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy,receipt_path=receipt_path,
            message_policy=message_policy)
        evidence=load_cutter_evidence(saved_plan_receipt_path=saved_plan_receipt_path,
            saved_plan_receipt_sha256=saved_plan_receipt_sha256,tools_receipt_path=tools_receipt_path,
            tools_receipt_sha256=tools_receipt_sha256,nominal_geometry_receipt_path=nominal_geometry_receipt_path,
            nominal_geometry_receipt_sha256=nominal_geometry_receipt_sha256,target_geometry=target_geometry,
            process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id,
            session_rebind_receipt_path=session_rebind_receipt_path,
            session_rebind_receipt_sha256=session_rebind_receipt_sha256)
        hp=(holder_file_path,holder_file_sha256,holder_recipe_path,holder_recipe_sha256)
        if any(v is not None for v in hp):
            if not all(type(v) is str and v for v in hp):raise ValueError('Complete explicit holder binding required')
            holder_recipe=read_holder_recipe(*hp)
            report['holder_asset_binding']=deepcopy(holder_recipe)
            if any(Path(receipt_path).resolve()==Path(p['path']).resolve() for p in holder_recipe['pins']):
                raise ValueError('Receipt cannot overwrite holder asset')
        if any(Path(receipt_path).resolve()==Path(p['path']).resolve() for p in evidence.pins):
            raise ValueError('Output cannot overwrite pinned evidence')
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        report['anchor']=evidence.summary()
        report['selected']=deepcopy(evidence.selected)
        report['source_before_sha256']=expected_source_sha256
        baseline=identity()
        if baseline['needs_save'] is not False:raise ValueError('Clean saved pre-state required; never replay')
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Identity changed acquiring event host')
        session=CamMessageSession(app,typelib_path)
        with session,ExitStack() as stack:
            files.append(stack.enter_context(_CaptureReadFiles(expected_document_path)))
            files.extend(stack.enter_context(_CaptureReadFiles(p['path'])) for p in evidence.pins)
            if holder_recipe is not None:
                files.extend(stack.enter_context(_CaptureReadFiles(p['path'])) for p in holder_recipe['pins'])
            before,native,details,full=capture('before')
            evidence.verify_before(before,details)
            old=values(full)
            if all(_equal(k,old[k],target_geometry[k]) for k in old):
                raise ValueError('Cutter already matches request; replay rejected')
            def exact_targets():
                fast_guard();identity();first=None
                for op_id in expected_operation_native_ids:
                    raw=native['operations'][op_id]
                    operation=typed(raw,'ICWOperation')
                    if _object_id(native['doc'],operation,read)!=op_id:raise ValueError('Operation identity changed')
                    tool=typed(read(operation,'IGetTool'),'ICWTool')
                    if (_object_id(native['doc'],tool,read)!=expected_tool_native_id
                        or read(tool,'IsMillTool') is not True):
                        raise ValueError('Shared assigned tool identity changed')
                    if first is None:first=tool
                fast_guard()
                return dict(ICWTool=first,ICWMillTool=typed(first,'ICWMillTool'))
            targets=exact_targets()
            def field_guard():
                fast_guard();identity()
                current=exact_targets()
                for key,pointer in current.items():
                    if _object_id(native['doc'],pointer,read)!=expected_tool_native_id:
                        raise ValueError('Typed tool identity changed')
                fast_guard()
            report['requested_property_order']=[x[0] for x in FIELDS]
            persist()
            apply_property_batch(targets=targets,old_values=old,target=target_geometry,
                read=read,guard=field_guard,persist=persist,report=report)
            if holder_recipe is not None:
                holder=typed(read(targets['ICWTool'],'IGetMillToolHolder'),'ICWMillToolHolder')
                apply_holder_reference(holder,holder_recipe,read=read,invoke=_member,
                    guard=field_guard,persist=persist,report=report)
            after,_,after_details,after_full=capture('after')
            evidence.verify_after_context(after)
            report['profile_comparison']=verify_full_delta(full,after_full,target_geometry,holder_recipe)
            check()
            if save_after_verified:
                stack.close();files.clear()
                if identity()!=after['document']:raise ValueError('Identity changed before save')
                target=typed(app,'ICWApp')
                report.update(phase='save',save_attempted=True,native_dispatch_pending=True)
                persist();check()
                result=_member(target,'SaveActiveDocument')
                report.update(save_call_returned=True,native_dispatch_pending=False,
                    save_hresult=result if type(result) is int else None)
                persist();check()
                if type(result) is not int or result!=0:raise ValueError('Save HRESULT uncertain; do not replay')
                current_source=_file_hash(expected_document_path)
                report['source_after_sha256']=current_source
                saved,_,saved_details,_=capture('saved')
                if not same_saved_context(after,saved) or saved['document']['needs_save'] is not False or saved_details!=after_details:
                    raise ValueError('Native save readback changed tool or CAM context')
                report['save_readback_verified']=True
                persist();check()
        check(active=False)
        if identity()!=report['saved' if save_after_verified else 'after']['document']:raise ValueError('Identity changed during cleanup')
        report.update(status='review_required',phase='finished',readback_verified=True,
            cutter_profile_readback_verified=True,holder_profile_readback_verified=holder_recipe is not None,state_sha256=_digest(report['saved' if save_after_verified else 'after']),
            tool_details_sha256=_digest(report['after_tool_details']),
            saved_file_sha256=current_source,model_saved=save_after_verified,
            continuation_state=deepcopy(report['saved' if save_after_verified else 'after']),
            reason='NOMINAL_TOOL_ASSEMBLY_READBACK_VERIFIED_PHYSICAL_SETUP_UNQUALIFIED' if holder_recipe is not None else 'NOMINAL_CUTTER_ONLY_PHYSICAL_SETUP_UNQUALIFIED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,cutter_profile_readback_verified=False,save_readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:
            report.update(status='uncertain' if report['mutation_attempted'] else 'error',
                receipt_write_error=_error(exc),readback_verified=False,cutter_profile_readback_verified=False,save_readback_verified=False)
    return report
