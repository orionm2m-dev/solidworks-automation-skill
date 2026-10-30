"""Assigned-tool readback anchored to a saved compact MILL plan; no mutations."""
from copy import deepcopy
from functools import partial
from pathlib import Path
from scripts.sw_cam import _member,_error
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request,_same_inventory
from scripts.sw_cam_mill_route_context import integer
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_plan_evidence import (
    SCOPE as PLAN_SCOPE,read_pin,clean_events,same_saved_context)
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes,_sha,_require
from scripts.sw_cam_empty_mill_stock_export import _export_stock
from scripts.sw_cam_stock_mesh_compare import _read_pinned
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

SCOPE='MILL_SAVED_PLAN_TOOLS_V1'


def validate_selected_ids(feature_id,operation_ids,setup_id,tool_id):
    for value,label in ((feature_id,'feature ID'),(setup_id,'operation setup ID'),(tool_id,'tool ID')):
        integer(value,label,1)
    _require(type(operation_ids) is list and 1<=len(operation_ids)<=32,
             'Explicit bounded ordered operation IDs required')
    for value in operation_ids:integer(value,'operation ID',1)
    _require(len(set(operation_ids))==len(operation_ids),'Duplicate operation IDs')


class SavedPlanToolsEvidence:
    """Only the saved receipt and its stock file are read; old chains stay provenance."""
    def __init__(self,data,pin,stock_pin,operation_ids,tool_id):
        self.data=deepcopy(data);self.state=deepcopy(data['after'])
        self.selected=deepcopy(data['selected'])
        self.pins=[deepcopy(pin),deepcopy(stock_pin)]
        self.operation_ids=list(operation_ids);self.tool_id=tool_id

    def check_files(self):
        for index,pin in enumerate(self.pins):
            _,current=(_receipt_bytes if index==0 else _read_pinned)(pin['path'])
            _require(current==pin,'Pinned saved plan or stock file changed')

    def read_stock(self,workpiece,tlb,read,diagnostic):
        # This existing helper only reads native getters; it exports nothing.
        stock,native=_export_stock(workpiece,tlb,read,diagnostic)
        _require(stock==self.state['stock'],'Observed stock differs from saved plan')
        return stock,native

    def verify(self,state):
        _require(_same_inventory(self.state,state),
                 'Saved header, sibling operation, assigned tool, stock or SW context changed')
        return True

    def summary(self):
        return dict(scope=SCOPE,saved_plan_receipt=deepcopy(self.pins[0]),
            stock_file=deepcopy(self.pins[1]),selected=deepcopy(self.selected),
            operation_native_ids=self.operation_ids,tool_native_id=self.tool_id,
            saved_source_sha256=self.data['saved_file_sha256'],
            original_source_sha256=self.data['source_before_sha256'],
            original_plan_receipt=deepcopy(self.data['plan_receipt']),
            previous_anchor_reported=deepcopy(self.data['anchor']),
            previous_anchor_replayed=False,full_inventory_verified=False,
            world_geometry_verified=False,production_qualified=False)


def load_saved_plan_tools_evidence(path,sha,*,process_id,expected_document_path,
        expected_source_sha256,expected_feature_native_id,expected_operation_native_ids,
        expected_operation_setup_native_id,expected_tool_native_id,
        session_rebind_receipt_path=None,session_rebind_receipt_sha256=None):
    if session_rebind_receipt_path is not None or session_rebind_receipt_sha256 is not None:
        _require(session_rebind_receipt_path is not None and session_rebind_receipt_sha256 is not None,
                 'Both explicit session rebind pin fields are required')
        candidate, _ = read_pin(path, sha)
        _require(candidate.get('scope') in (PLAN_SCOPE, 'MILL_APPEND_OPERATIONS_V1'),
                 'Explicit rebind only supports original or appended saved plans')
        from scripts.sw_cam_mill_saved_plan_rebind import load_rebound_saved_plan_tools_evidence
        return load_rebound_saved_plan_tools_evidence(
            session_rebind_receipt_path,session_rebind_receipt_sha256,
            saved_plan_receipt_path=path,saved_plan_receipt_sha256=sha,process_id=process_id,
            expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
            expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id)
    candidate, _ = read_pin(path, sha)
    if candidate.get("scope") in ("MILL_ADDED_CIRCULAR_POCKET_PLAN_V1","MILL_ADDED_CIRCLE_SKETCH_V1"):
        _require(session_rebind_receipt_path is None and session_rebind_receipt_sha256 is None,
                 "Added pocket plan requires its recorded current session")
        from scripts.sw_cam_added_pocket_evidence import load_added_pocket_evidence
        return load_added_pocket_evidence(path,sha,process_id=process_id,
            expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
            expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id)
    if candidate.get("scope") == "MILL_REPLACED_COMPOUND_PLAN_V1":
        _require(session_rebind_receipt_path is None and session_rebind_receipt_sha256 is None,
                 "Replaced plan requires its recorded current session")
        from scripts.sw_cam_replaced_plan_evidence import load_replaced_plan_evidence
        return load_replaced_plan_evidence(path,sha,process_id=process_id,
            expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
            expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id)
    # Insert in load_saved_plan_tools_evidence immediately after candidate = read_pin(...).
    if candidate.get("scope") == "MILL_APPEND_OPERATIONS_V1":
        _require(session_rebind_receipt_path is None and session_rebind_receipt_sha256 is None,
                 "Appended plan requires its recorded current session")
        from scripts.sw_cam_mill_appended_plan_evidence import load_appended_plan_evidence
        return load_appended_plan_evidence(path, sha, process_id=process_id,
            expected_document_path=expected_document_path, expected_source_sha256=expected_source_sha256,
            expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id)
    if candidate.get('scope') == 'MILL_SAVED_SHARED_CUTTER_CONFIG_V1':
        _require(session_rebind_receipt_path is None and session_rebind_receipt_sha256 is None,
                 'Configuration continuation requires its recorded current session')
        from scripts.sw_cam_configured_plan_evidence import load_configured_plan_evidence
        return load_configured_plan_evidence(path, sha, process_id=process_id,
            expected_document_path=expected_document_path, expected_source_sha256=expected_source_sha256,
            expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id)
    integer(process_id,'process ID',1);_sha(expected_source_sha256)
    validate_selected_ids(expected_feature_native_id,expected_operation_native_ids,
                          expected_operation_setup_native_id,expected_tool_native_id)
    data,pin=read_pin(path,sha)
    _require(data.get('scope')==PLAN_SCOPE and data.get('action')=='save_checked'
        and data.get('status')=='review_required' and data.get('phase')=='finished',
        'Completed selected-plan saved receipt required')
    for key in ('mutation_attempted','native_call_attempted','native_call_returned','save_attempted',
                'readback_verified','save_readback_verified','model_saved'):
        _require(data.get(key) is True,'Successful save flag required: '+key)
    for key in ('native_dispatch_pending','GOP_attempted','GTP_attempted','AFR_attempted',
                'tool_assignment_attempted','stock_edit_attempted','geometry_edit_attempted',
                'TechDB_write_attempted','full_inventory_verified','world_geometry_verified',
                'production_qualified','post_cleanup_CAM_getters'):
        _require(data.get(key) is False,'Unexpected saved-plan flag: '+key)
    _require(not any(k in data for k in ('issue','failed_phase','receipt_write_error')),
             'Saved receipt contains failure evidence')
    _require(type(data.get('native_hresult')) is int and data['native_hresult']==0,
             'Strict successful native save result required')
    _require(type(data.get('process_id')) is int and data['process_id']==process_id,
             'Saved plan process differs; no implicit rebind')
    _require(type(data.get('expected_operation_setup_native_id')) is int
        and data['expected_operation_setup_native_id']==expected_operation_setup_native_id,
        'Saved operation setup differs')
    clean_events(data)
    before,after=data.get('before'),data.get('after')
    _require(type(before) is dict and type(after) is dict and same_saved_context(before,after),
             'Save changed observed model or operation context')
    _require(data.get('state_sha256')==_digest(after),'Saved state digest differs')
    _require(data.get('saved_file_sha256')==data.get('source_after_sha256')
        ==after.get('saved_file_sha256')==expected_source_sha256,'Current saved source differs')
    _sha(data['source_before_sha256'])
    _require(before.get('saved_file_sha256')==data['source_before_sha256'],
             'Original source lineage differs')
    _require(type(after.get('document',{}).get('type')) is int and after['document']['type']==1
        and after['document'].get('needs_save') is False,'Clean saved part required')
    check_document_target(after['document']['path'],after['document']['title'],
                          expected_path=expected_document_path,required=True)
    selected=data.get('selected')
    _require(type(selected) is dict and type(selected.get('feature_native_id')) is int
        and selected['feature_native_id']==expected_feature_native_id
        and selected.get('include_contours') is False,'Selected feature scope differs')
    features=after.get('features')
    _require(type(features) is list and len(features)==18,'Exact 18-header scope required')
    ids=[integer(r['geometry']['native_id'],'feature ID',1) for r in features]
    _require(len(set(ids))==18,'Unique feature IDs required')
    matched=[r for r in features if r['geometry']['native_id']==expected_feature_native_id]
    _require(len(matched)==1 and matched[0]['setup_native_id']==selected['owner_setup_native_id']
        and matched[0]['geometry']['volume_type']==selected['volume_type']
        and matched[0]['geometry']['shape_raw']==selected['shape']
        and matched[0]['geometry']['suppressed'] is False,'Selected owner/classification differs')
    rows=after.get('operations')
    _require(type(rows) is list and 1<=len(rows)<=32 and type(after.get('operation_count')) is int
        and len(rows)==after['operation_count'],'Complete bounded operation context required')
    ids=[integer(r['native_id'],'operation ID',1) for r in rows]
    _require(len(set(ids))==len(ids),'Unique operation IDs required')
    related=[r for r in rows if r['linked_feature_ids']==[expected_feature_native_id]]
    _require([r['native_id'] for r in related]==expected_operation_native_ids,
             'Selected ordered operation membership differs')
    _require([r['native_id'] for r in rows if r['assigned_tool']['native_id']==expected_tool_native_id]
        ==expected_operation_native_ids,'All users of the shared assigned tool must be in scope')
    for row in related:
        _require(type(row['setup_native_id']) is int and row['setup_native_id']==expected_operation_setup_native_id
            and row['suppressed'] is False and row['toolpath_generated'] is False
            and row['toolpath_record_counts']==[] and row['assigned_tool']['native_id']==expected_tool_native_id
            and row['assigned_tool'].get('native_read_complete') is True,
            'Selected operation owner, tool or no-toolpath state differs')
    _require(type(data.get('plan_receipt')) is dict and type(data.get('anchor')) is dict,
             'Original saved-plan provenance required')
    _sha(data['plan_receipt']['sha256'])
    stock=after['stock'];_,stock_pin=_read_pinned(stock['stl_path'])
    _require(stock_pin['sha256']==stock['stl_sha256'],'Pinned stock file changed')
    result=SavedPlanToolsEvidence(data,pin,stock_pin,expected_operation_native_ids,expected_tool_native_id)
    result.check_files()
    return result


def inspect_saved_plan_tools(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,saved_plan_receipt_path,saved_plan_receipt_sha256,
        expected_feature_native_id,expected_operation_native_ids,expected_operation_setup_native_id,
        expected_tool_native_id,qualification_only,acknowledge_disposable_copy,receipt_path,
        message_policy='vendor_default',session_rebind_receipt_path=None,session_rebind_receipt_sha256=None):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status='error',phase='preflight',process_id=process_id,read_only=True,
        may_continue=False,mutation_attempted=False,AFR_attempted=False,GOP_attempted=False,
        GTP_attempted=False,model_saved=False,save_attempted=False,stock_edit_attempted=False,
        material_edit_attempted=False,tool_assignment_attempted=False,TechDB_write_attempted=False,
        post_cleanup_CAM_getters=False,readback_verified=False,tools_readback_verified=False,
        tool_geometry_read_complete=False,tool_profile_complete=False,full_inventory_verified=False,
        world_geometry_verified=False,units_verified=False,physical_tool_identity_verified=False,
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
        if doc.get('needs_save') is not False or _file_hash(expected_document_path)!=expected_source_sha256:
            raise ValueError('Clean saved source changed')
        anchor.check_files()
        if hasattr(anchor,'check_runtime_identity'):anchor.check_runtime_identity()
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
        if Path(receipt_path).resolve()==Path(saved_plan_receipt_path).resolve():
            raise ValueError('Output cannot overwrite saved-plan evidence')
        anchor=load_saved_plan_tools_evidence(saved_plan_receipt_path,saved_plan_receipt_sha256,
            process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id,
            session_rebind_receipt_path=session_rebind_receipt_path,
            session_rebind_receipt_sha256=session_rebind_receipt_sha256)
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        report['anchor']=anchor.summary()
        baseline=identity()
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Identity changed acquiring CAM event host')
        session=CamMessageSession(app,typelib_path)
        with session:
            for phase in ('before','after'):
                check();report['phase']=phase;diag=dict(phase=phase)
                report['snapshot_diagnostics'].append(diag);persist()
                state,_=capture_selected_plan(sw,clsid,typelib_path,expected_document_path,
                    process_id=process_id,expected_source_sha256=expected_source_sha256,
                    evidence=anchor,check=check,diagnostic=diag,progress=persist,
                    operation_details_reader=partial(read_selected_operation_tool_details,
                                                      feature_native_id=expected_feature_native_id))
                if state['document']!=baseline:raise ValueError('Document changed during tool inspection')
                anchor.verify(state)
                details=deepcopy(diag['operation_details']['selected_tool_details'])
                if ([r['operation_native_id'] for r in details['items']]!=expected_operation_native_ids
                    or details['generic_operation_context_unchanged'] is not True
                    or details['canonical_state_changed'] is not False):
                    raise ValueError('Tool detail scope or operation context differs')
                report[phase]=state;report[phase+'_tool_details']=details;persist();check()
            if not _same_inventory(report['before'],report['after']):
                raise ValueError('Compact model/operation context changed')
            if report['before_tool_details']!=report['after_tool_details']:
                raise ValueError('Tool or partial observation changed between reads')
            fulls=[r['full_tool'] for r in report['before_tool_details']['items']]
            if any(value!=fulls[0] for value in fulls[1:]):
                raise ValueError('Shared tool observations disagree')
        check(active=False)
        if identity()!=baseline:raise ValueError('Identity changed during event cleanup')
        details=report['before_tool_details'];complete=details['metadata_read_complete'] is True
        report.update(status='review_required',phase='finished',readback_verified=True,
            tools_readback_verified=complete,tool_geometry_read_complete=complete,
            tool_profile_complete=details['profile_complete'] is True,
            state_sha256=_digest(report['before']),tool_details_sha256=_digest(details),
            saved_file_sha256=expected_source_sha256,
            reason=('STABLE_RAW_TOOL_METADATA_UNITS_PHYSICAL_IDENTITY_AND_CLEARANCE_UNQUALIFIED'
                    if complete else 'STABLE_PARTIAL_TOOL_OBSERVATIONS_NOT_COMPLETE'))
    except Exception as exc:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,tools_readback_verified=False,tool_geometry_read_complete=False,
            tool_profile_complete=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:report.update(status='error',receipt_write_error=_error(exc),
            readback_verified=False,tools_readback_verified=False,tool_geometry_read_complete=False,
            tool_profile_complete=False)
    return report
