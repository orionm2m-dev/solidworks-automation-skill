"""Read one assigned MILL tool/holder in an immutable multi-feature route context."""
from pathlib import Path
from scripts.sw_cam import _member,_error
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request,_same_inventory
from scripts.sw_cam_mill_route_context import capture_mill_route_state,integer
from scripts.sw_cam_mill_route_evidence import load_mill_route_anchor
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target


def inspect_mill_route_tool(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,inventory_receipt_path,inventory_receipt_sha256,
        expected_feature_native_id,expected_operation_native_id,expected_mill_operation_type,
        qualification_only,acknowledge_disposable_copy,receipt_path,message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status='error',phase='preflight',process_id=process_id,read_only=True,
        may_continue=False,apply_eligible=False,mutation_attempted=False,AFR_attempted=False,
        GOP_attempted=False,GTP_attempted=False,model_saved=False,stock_edit_attempted=False,
        material_edit_attempted=False,tool_assignment_attempted=False,TechDB_write_attempted=False,
        post_cleanup_CAM_getters=False,readback_verified=False,inventory_read_complete=False,
        tool_geometry_read_complete=False,native_behavior_qualified=False,
        units_verified=False,physical_depth_verified=False,physical_tool_identity_verified=False,
        holder_clearance_verified=False,actual_incoming_WIP_verified=False,production_qualified=False,
        snapshot_diagnostics=[])
    receipt=None;created=False;session=None;anchor=None;baseline=None
    def persist():
        if created:_write_receipt(receipt,report)
    def identity():
        pid=_member(sw,'GetProcessID')
        if type(pid) is not int or pid!=process_id:raise ValueError('Exact process changed')
        doc=raw_part_identity(sw)
        check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True)
        if _file_hash(expected_document_path)!=expected_source_sha256:raise ValueError('Saved source changed')
        anchor.check_files()
        return doc
    def check(active=True):
        value=session.summary();report['messages']=value
        if (value.get('subscribed') is not True or (active and value.get('active') is not True)
            or (not active and (value.get('active') is not False or value.get('disconnected') is not True))
            or any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count',
                                         'subscription_error','disconnect_errors'))):
            raise ValueError('CAM event/transport requires stop')
    try:
        validate_inventory_request(process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy,receipt_path=receipt_path,
            message_policy=message_policy)
        selected=dict(feature_native_id=integer(expected_feature_native_id,'selected feature ID',1),
            operation_native_id=integer(expected_operation_native_id,'selected operation ID',1),
            mill_operation_type=integer(expected_mill_operation_type,'selected MILL operation type'))
        anchor=load_mill_route_anchor(inventory_receipt_path,inventory_receipt_sha256,process_id=process_id,
            expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
        if expected_feature_native_id not in [r['geometry']['native_id'] for r in anchor.state['features']]:
            raise ValueError('Selected feature not present in pinned inventory')
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        report.update(selected=selected,route_anchor=anchor.summary());persist()
        baseline=identity()
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Identity changed acquiring CAM event host')
        session=CamMessageSession(app,typelib_path)
        with session:
            for phase in ('before','after'):
                check();report['phase']=phase;diag=dict(phase=phase)
                report['snapshot_diagnostics'].append(diag);persist();anchor.check_files()
                state,_=capture_mill_route_state(sw,clsid,typelib_path,expected_document_path,
                    process_id=process_id,expected_source_sha256=expected_source_sha256,
                    check=check,diagnostic=diag,selected=selected,
                    stock_reader=lambda wp,tlb,read:anchor.read_stock(wp,tlb,read,diag))
                if state['document']!=baseline:raise ValueError('Document changed during read-only tool inspection')
                anchor.verify(state);report[phase]=state;persist();check()
            if not _same_inventory(report['before'],report['after']):
                raise ValueError('Feature, sibling operation, selected tool or source changed')
        check(active=False)
        if identity()!=baseline:raise ValueError('Identity changed during event cleanup')
        selected_row=next(r for r in report['before']['operations'] if r['native_id']==expected_operation_native_id)
        full=selected_row['full_tool']
        report.update(status='review_required',phase='finished',readback_verified=True,
            inventory_read_complete=True,tool_geometry_read_complete=full['geometry_read_complete'],
            tool_profile_complete=full['profile_complete'],selected_tool=full,
            state_sha256=_digest(report['before']),
            reason='RAW_ASSIGNED_MILL_TOOL_HOLDER_ONLY_UNITS_PHYSICAL_IDENTITY_AND_CLEARANCE_UNQUALIFIED')
    except Exception as exc:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,inventory_read_complete=False,tool_geometry_read_complete=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:report.update(status='error',receipt_write_error=_error(exc),readback_verified=False,
            inventory_read_complete=False,tool_geometry_read_complete=False)
    return report
