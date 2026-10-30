"""Read-only bounded MILL feature inventory before GOP; staged pilot, no recognition."""
from copy import deepcopy
from pathlib import Path
import re
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap, _snapshot as _mill_snapshot
from scripts.sw_cam_mill_stock import _stock
from scripts.sw_cam_mill_units_qualification import _features, _bodies, _same_bodies, _nonnull
from scripts.sw_cam_mill_inventory_geometry import read_mill_feature
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles, _check_capture_document
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path, check_document_target

MAX_FEATURES=64
MAX_READS=50000


def validate_inventory_request(*, process_id, expected_document_path, expected_source_sha256,
        qualification_only, acknowledge_disposable_copy, receipt_path, message_policy='vendor_default',
        recognition_receipt_path=None,recognition_receipt_sha256=None,
        preservation_save_receipt_path=None,preservation_save_receipt_sha256=None,allow_saved_process_rebind=False,
        diagnostic_continue_known_island_error=False,batched_identity_checks=False,diagnostic_contour_errors=False):
    if type(process_id) is not int or not 0<process_id<2**32:
        raise ValueError('Exact process ID required')
    if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold()!='.sldprt'):
        raise ValueError('Exact saved qualification part path required')
    if type(expected_source_sha256) is not str or re.fullmatch('[0-9a-f]{64}',expected_source_sha256) is None:
        raise ValueError('Exact current source SHA required')
    if qualification_only is not True or acknowledge_disposable_copy is not True or message_policy!='vendor_default':
        raise ValueError('Explicit disposable qualification with vendor_default required')
    if (type(receipt_path) is not str or not absolute_document_path(receipt_path)
            or Path(receipt_path).suffix.casefold()!='.json' or not Path(receipt_path).parent.is_dir()
            or Path(receipt_path).exists() or Path(receipt_path).is_symlink()):
        raise ValueError('Unique absolute JSON receipt in an existing directory required')
    for flag in (diagnostic_continue_known_island_error,batched_identity_checks,diagnostic_contour_errors):
        if type(flag) is not bool:raise ValueError('Strict diagnostic and batched identity booleans required')
    if type(allow_saved_process_rebind) is not bool:
        raise ValueError('Strict saved process rebind boolean required')
    evidence=(recognition_receipt_path,recognition_receipt_sha256,preservation_save_receipt_path,preservation_save_receipt_sha256)
    if allow_saved_process_rebind and any(value is None for value in evidence):
        raise ValueError('Saved process rebind requires the complete pinned recovery lineage')
    if any(value is not None for value in evidence):
        if any(value is None for value in evidence):raise ValueError('All four recovery evidence fields are required together')
        for path,sha in ((evidence[0],evidence[1]),(evidence[2],evidence[3])):
            if (type(path) is not str or not absolute_document_path(path) or Path(path).suffix.casefold()!='.json'
                    or not Path(path).is_file() or Path(path).is_symlink()):
                raise ValueError('Existing absolute regular JSON recovery receipt required')
            if type(sha) is not str or re.fullmatch('[0-9a-f]{64}',sha) is None:
                raise ValueError('Exact recovery receipt SHA required')
        if Path(evidence[0]).resolve()==Path(evidence[2]).resolve():
            raise ValueError('Distinct recognition and preservation receipts required')


def _integer(value, maximum, label):
    if type(value) is not int or not 0<=value<=maximum:raise ValueError('Bounded strict '+label+' required')
    return value


def _items(raw, typed, read, limit):
    collection=typed(raw,'ICWDispatchCollection')
    count=_integer(read(collection,'Count'),limit,'collection count')
    return [read(collection,'Item',index) for index in range(count)]


def _known_island_interface_error(exc,partial):
    """Exactly the observed setter-only profile item; never a generic QI fallback."""
    issue=_error(exc)
    return (partial.get('stage')=='QI ICWIslandInfo'
        and issue.get('code')=='CAM_COM_NATIVE_QI_FAILED'
        and issue.get('bridge_stage')=='native_query_interface'
        and issue.get('hresult')==-2147467262
        and issue.get('input_type')=='POINTER(ICWProfileSketchParam)'
        and issue.get('source_type')=='POINTER(ICWProfileSketchParam)'
        and type(partial.get('state')) is dict
        and type(partial['state'].get('native_id')) is int
        and partial['state']['native_id']>0)


def _known_contour_getter_error(exc,partial,diagnostic):
    """Only direct contour E_FAIL; an identity/event/RPC failure is never catalogued."""
    issue=_error(exc);failure=diagnostic.get('last_native_failure',{})
    state=partial.get('state',{})
    method=partial.get('stage')
    return (method in ('IGetTopSegChain','IGetBottomSegChain','IGetWallSegChain')
        and issue.get('type')=='COMError' and issue.get('hresult')==-2147467259
        and failure.get('method')==method
        and failure.get('native_read_count')==diagnostic.get('native_read_count')
        and failure.get('issue',{}).get('type')=='COMError'
        and failure.get('issue',{}).get('hresult')==-2147467259
        and type(state) is dict and type(state.get('native_id')) is int and state['native_id']>0
        and all(type(state.get(key)) is int for key in ('volume_type','subtype_raw','shape_raw')))


def capture_mill_inventory(sw, clsid, typelib_path, expected_path, *, check, diagnostic, stock_reader=None, operation_reader=None,
        diagnostic_continue_known_island_error=False,progress=None,batch_boundary=None,diagnostic_contour_errors=False):
    """Default stays zero-operation; an internal bounded route reader is opt-in."""
    if type(diagnostic_continue_known_island_error) is not bool or type(diagnostic_contour_errors) is not bool:
        raise ValueError('Strict diagnostic continuation boolean required')
    if (diagnostic_continue_known_island_error or diagnostic_contour_errors) and operation_reader is not None:
        raise ValueError('Partial diagnostic inventory cannot feed an operation reader')
    for callback in (progress,batch_boundary):
        if callback is not None and not callable(callback):raise ValueError('Internal callback must be callable')
    started=monotonic();last_progress=started
    diagnostic.update(capture_complete=False,features=[],native_read_count=0,native_qi_count=0)
    def checkpoint(stage,*,force=True,boundary=True):
        nonlocal last_progress
        if boundary:
            (batch_boundary or check)()
        now=monotonic();diagnostic['elapsed_seconds']=now-started
        if force or now-last_progress>=5.0:
            diagnostic['checkpoint']=stage
            if progress is not None:progress(diagnostic)
            last_progress=now
    def heartbeat():checkpoint('native_read',force=False,boundary=False)
    def read(obj,name,*args):
        if diagnostic['native_read_count']>=MAX_READS:raise ValueError('Native read budget exceeded')
        diagnostic.update(last_native_method=name,native_read_count=diagnostic['native_read_count']+1)
        diagnostic.pop('last_native_failure',None)
        heartbeat();check()
        try:value=_member(obj,name,*args)
        except Exception as exc:
            diagnostic['last_native_failure']=dict(method=name,native_read_count=diagnostic['native_read_count'],issue=_error(exc))
            raise
        check();return value
    def typed(raw,name):
        diagnostic.update(last_native_interface=name,native_qi_count=diagnostic['native_qi_count']+1)
        heartbeat();_nonnull(raw,name+' raw');check();value=_typed(raw,name,typelib_path);_nonnull(value,name);check();return value
    checkpoint('machine_snapshot_begin')
    state,native=_mill_snapshot(sw,clsid,typelib_path,expected_path,check=check,
        diagnostic=diagnostic,required_machine_type=1)
    checkpoint('machine_snapshot_end')
    # The initial machine snapshot is not a complete feature inventory.
    if sum(row['feature_count'] for row in state['feature_setups'])>MAX_FEATURES:
        raise ValueError('Feature inventory exceeds pilot bound')
    diagnostic.update(capture_complete=False,stage='feature_inventory')
    checkpoint('operation_setups_begin')
    if operation_reader is None:
        if any(state['operation_counts']):raise ValueError('Discovery inventory requires exactly zero operations; no generated-operation policy extension')
        if sum(row['feature_count'] for row in state['feature_setups'])>MAX_FEATURES:
            raise ValueError('Feature inventory exceeds pilot bound')
        # Count-level operation readback is sufficient only because no operations are admitted.
        state.update(operation_count=0,operation_inventory_scope='zero_operations_and_empty_setup_ids_verified')
        state['operation_setups']=[]
        op_setups=_items(read(native['machine'],'IGetEnumOpSetups'),typed,read,8)
        if len(op_setups)!=len(state['operation_counts']):raise ValueError('Operation setup count changed')
        for index,raw_setup in enumerate(op_setups):
            setup=typed(raw_setup,'ICWBaseOpSetup');setup_id=_object_id(native['doc'],setup,read)
            operations=_items(read(setup,'IGetEnumOperations'),typed,read,0)
            if operations or setup_id in [r['native_id'] for r in state['operation_setups']]:raise ValueError('Invalid empty operation setup inventory')
            state['operation_setups'].append(dict(index=index,native_id=setup_id,operation_count=0))
    elif not callable(operation_reader):
        raise ValueError('Internal operation reader must be callable')
    checkpoint('operation_setups_end')
    checkpoint('recognition_options_begin')
    state['recognition_options']={}
    for getter,values in [('GetEMFFeatTypeOptions',range(6)),('GetEMFPartPeriTypeOptions',range(2)),('GetEMFTypeOptions',range(4))]:
        result=[];state['recognition_options'][getter]=result
        for index in values:
            value=read(native['doc'],getter,index)
            if type(value) is not bool:raise ValueError('Strict raw recognition option bool required')
            result.append(dict(enum_value=index,enabled=value))
    creation_style=read(native['doc'],'FeatureCreationStyle')
    if type(creation_style) is not int or creation_style not in (0,1):
        raise ValueError('FeatureCreationStyle requires strict native AFR0 or MFGVIEW1 enum')
    state['recognition_method']={'value':creation_style,
        'name':'AFR' if creation_style==0 else 'MFGVIEW',
        'status':'observed_via_ICWDoc3_FeatureCreationStyle'}
    for prop in ['EMFHoleMaxDiameter','EMFHoleMinimumIncludedAngle']:
        import math
        value=read(native['doc'],prop)
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Finite raw EMF scalar required')
        state['recognition_options'][prop]=value
    checkpoint('recognition_options_end')
    checkpoint('stock_begin')
    # Internal export-only observer; default public readers remain strict.
    stock, _=(stock_reader or _stock)(read(native['machine'],'IGetWorkpiece'),typelib_path,read)
    state['stock']=stock
    state['stock_geometry_verified']=False
    state['material_production_qualified']=False
    checkpoint('stock_end')
    state['features']=[];ids=set();budget=dict(curves=0,chains=0,islands=0)
    native['features']={}
    for index,raw_setup in enumerate(native['setups']):
        diagnostic['current_setup_index']=index
        checkpoint('setup_begin')
        setup=typed(raw_setup,'ICWBaseSetup')
        setup_id=_object_id(native['doc'],setup,read)
        if setup_id!=state['feature_setups'][index]['native_id']:raise ValueError('Setup identity changed')
        values=_items(read(setup,'IGetEnumFeatures'),typed,read,MAX_FEATURES)
        if len(values)!=state['feature_setups'][index]['feature_count']:raise ValueError('Feature count changed')
        for feature_index,raw in enumerate(values):
            diagnostic['current_feature_index']=feature_index
            checkpoint('feature_begin')
            partial=dict(setup_index=index,feature_index=feature_index,setup_native_id=setup_id)
            diagnostic['features'].append(partial)
            try:
                row=read_mill_feature(raw,read=read,typed=typed,
                    object_id=lambda value:_object_id(native['doc'],value,read),diagnostic=partial,budget=budget)
            except Exception as exc:
                island_error=diagnostic_continue_known_island_error and _known_island_interface_error(exc,partial)
                contour_error=diagnostic_contour_errors and _known_contour_getter_error(exc,partial,diagnostic)
                if not (island_error or contour_error):raise
                row=deepcopy(partial['state'])
                state.setdefault('feature_errors',[]).append(dict(setup_index=index,feature_index=feature_index,
                    feature_native_id=row['native_id'],stage=partial['stage'],issue=_error(exc),
                    category='island_interface' if island_error else 'native_contour_getter_E_FAIL'))
                if island_error:partial['known_island_error_continued']=True
                if contour_error:
                    partial['known_contour_error_continued']=True
                    partial['native_failure_origin']=deepcopy(diagnostic['last_native_failure'])
                    partial['bounds_physical_verified']=False
                    partial['bounds_status']='native_raw_unqualified'

            feature_id=row['native_id']
            if type(feature_id) is not int or feature_id<=0 or feature_id in ids:raise ValueError('Duplicate or invalid feature identity')
            native['features'][feature_id]=raw
            ids.add(feature_id);state['features'].append(dict(setup_index=index,feature_index=feature_index,setup_native_id=setup_id,geometry=row))
            checkpoint('feature_end')
        checkpoint('setup_end')
    if operation_reader is not None:
        checkpoint('operations_begin')
        operation_reader(state,native,read,typed)
        checkpoint('operations_end')
    checkpoint('solidworks_reference_begin')
    check();model=sw.ActiveDoc;tree,_=_features(model);check();solids=_bodies(model);check()
    state['sw_reference']=dict(feature_tree=tree,solids=solids)
    visible=read(model,'GetBodies2',0,True)
    if visible is None:visible_count=0
    elif isinstance(visible,(tuple,list)) and len(visible)<=64:visible_count=len(visible)
    else:raise ValueError('Bounded actual visible-solid collection required')
    state.update(visible_solid_body_count=visible_count,all_solid_body_count=len(solids))
    state['geometry_snapshot_scope']='Feature tree and solid box/mass fingerprints; not complete BRep'
    checkpoint('solidworks_reference_end')
    checkpoint('final_snapshot_begin')
    final,_=_mill_snapshot(sw,clsid,typelib_path,expected_path,check=check,required_machine_type=1)
    for key in final:
        if final[key]!=state[key]:raise ValueError('Base MILL state changed while reading inventory')
    checkpoint('final_snapshot_end')
    diagnostic.update(capture_complete=not bool(state.get('feature_errors')),
        diagnostic_enumeration_complete=True,stage='incomplete' if state.get('feature_errors') else 'complete',geometry_budget=budget)
    checkpoint('capture_end')
    return state


def capture_guarded_mill_inventory(sw,clsid,typelib_path,expected_path,*,process_id,
        expected_source_sha256,check,diagnostic,stock_reader=None,operation_reader=None,
        diagnostic_continue_known_island_error=False,batched_identity_checks=False,progress=None,diagnostic_contour_errors=False):
    """Boundary SHA always; optional read-only grouping retains events/file checks per getter."""
    if type(batched_identity_checks) is not bool:raise ValueError('Strict batched identity boolean required')
    if type(diagnostic_contour_errors) is not bool:raise ValueError('Strict contour diagnostic boolean required')
    if batched_identity_checks and operation_reader is not None:
        raise ValueError('Batched identities are limited to zero-operation inventory')
    def identity():
        pid=_member(sw,'GetProcessID')
        if type(pid) is not int or pid!=process_id:raise ValueError('Exact process changed')
        doc=raw_part_identity(sw)
        check_document_target(doc['path'],doc['title'],expected_path=expected_path,required=True)
        source=_file_hash(expected_path)
        if source!=expected_source_sha256:raise ValueError('Saved source changed')
        return dict(document=doc,saved_file_sha256=source)
    with _CaptureReadFiles(expected_path) as files:
        check();begin=identity();check();files.check()
        def guarded():
            check()
            if not batched_identity_checks:_check_capture_document(sw,{'process_id':process_id},begin)
            files.check();check()
        def boundary():
            guarded()
            if batched_identity_checks:
                pid=_member(sw,'GetProcessID')
                if type(pid) is not int or pid!=process_id:raise ValueError('Exact process changed at read boundary')
                if raw_part_identity(sw)!=begin['document']:
                    raise ValueError('Document identity or dirty state changed at read boundary')
                files.check();check()

        capture_args=dict(check=guarded,diagnostic=diagnostic)
        if batched_identity_checks:capture_args['batch_boundary']=boundary
        if progress is not None:capture_args['progress']=progress
        if diagnostic_continue_known_island_error:capture_args['diagnostic_continue_known_island_error']=True
        if diagnostic_contour_errors:capture_args['diagnostic_contour_errors']=True
        if stock_reader is not None:capture_args['stock_reader']=stock_reader
        if operation_reader is not None:capture_args['operation_reader']=operation_reader
        state=capture_mill_inventory(sw,clsid,typelib_path,expected_path,**capture_args)
        guarded();end=identity();check();files.check()
        if begin!=end or any(state[key]!=begin[key] for key in begin):
            raise ValueError('Document/source changed across complete inventory capture')
    return state


def _same_inventory(before,after):
    if not _same_bodies(before['sw_reference']['solids'],after['sw_reference']['solids']):return False
    a=deepcopy(before);b=deepcopy(after)
    a['sw_reference'].pop('solids');b['sw_reference'].pop('solids')
    return a==b


def inspect_mill_feature_inventory(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,qualification_only,acknowledge_disposable_copy,receipt_path,message_policy='vendor_default',
        recognition_receipt_path=None,recognition_receipt_sha256=None,
        preservation_save_receipt_path=None,preservation_save_receipt_sha256=None,allow_saved_process_rebind=False,
        diagnostic_continue_known_island_error=False,batched_identity_checks=False,diagnostic_contour_errors=False):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status='error',phase='preflight',read_only=True,may_continue=False,mutation_attempted=False,
        AFR_attempted=False,GOP_attempted=False,GTP_attempted=False,model_saved=False,stock_edit_attempted=False,
        material_edit_attempted=False,TechDB_write_attempted=False,inventory_read_complete=False,readback_verified=False,
        native_behavior_qualified=False,physical_depth_verified=False,production_qualified=False,
        post_cleanup_CAM_getters=False,snapshot_diagnostics=[],process_id=process_id,
        allow_saved_process_rebind=allow_saved_process_rebind,saved_process_rebind_verified=False,
        diagnostic_continue_known_island_error=diagnostic_continue_known_island_error,
        diagnostic_contour_errors=diagnostic_contour_errors,batched_identity_checks=batched_identity_checks,diagnostic_enumeration_complete=False,
        identity_check_scope='feature_setup_phase_boundaries' if batched_identity_checks else 'each_native_getter')
    receipt=None;created=False;session=None;baseline=None;recovery=None
    started=monotonic()
    def persist():
        report['elapsed_seconds']=monotonic()-started
        if created:_write_receipt(receipt,report)
    def progress(diag):
        report['progress']={key:deepcopy(diag[key]) for key in
            ('phase','checkpoint','current_setup_index','current_feature_index','last_native_method',
             'last_native_interface','native_read_count','native_qi_count','elapsed_seconds') if key in diag}
        persist()
    def identity():
        pid=_member(sw,'GetProcessID')
        if type(pid) is not int or pid!=process_id:raise ValueError('Exact process changed')
        doc=raw_part_identity(sw)
        check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True)
        if _file_hash(expected_document_path)!=expected_source_sha256:raise ValueError('Source SHA changed')
        return doc
    def check(active=True):
        s=session.summary();report['messages']=s
        if (s.get('subscribed') is not True or (active and s.get('active') is not True)
            or (not active and (s.get('active') is not False or s.get('disconnected') is not True))
            or any(s.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors'))):
            raise ValueError('CAM message/event transport requires stop')
    try:
        validate_inventory_request(process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy,receipt_path=receipt_path,message_policy=message_policy,
            recognition_receipt_path=recognition_receipt_path,recognition_receipt_sha256=recognition_receipt_sha256,
            preservation_save_receipt_path=preservation_save_receipt_path,preservation_save_receipt_sha256=preservation_save_receipt_sha256,
            allow_saved_process_rebind=allow_saved_process_rebind,
            diagnostic_continue_known_island_error=diagnostic_continue_known_island_error,
            batched_identity_checks=batched_identity_checks,diagnostic_contour_errors=diagnostic_contour_errors)
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        if recognition_receipt_path is not None:
            from scripts.sw_cam_mill_inventory_recovery_evidence import load_mill_inventory_recovery_evidence
            recovery=load_mill_inventory_recovery_evidence(recognition_receipt_path,recognition_receipt_sha256,
                preservation_save_receipt_path,preservation_save_receipt_sha256,process_id=process_id,
                expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
                allow_saved_process_rebind=allow_saved_process_rebind)
            report.update(recovery_evidence=recovery.summary(),EMF_replayed=False,
                original_recognition_readback_verified=False,recovery_delta_verified=False,
                stock_offsets_verified=False,actual_incoming_WIP_verified=False)
            persist()
        baseline=identity()
        if baseline['needs_save'] is not False:raise ValueError('Clean saved qualification copy required')
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Identity changed acquiring event host')
        session=CamMessageSession(app,typelib_path)
        with session:
            for phase in ('before','after'):
                check();report['phase']=phase;diag=dict(phase=phase);report['snapshot_diagnostics'].append(diag);persist()
                capture_args=dict(progress=progress,batched_identity_checks=batched_identity_checks,
                    diagnostic_continue_known_island_error=diagnostic_continue_known_island_error,
                    diagnostic_contour_errors=diagnostic_contour_errors)
                if recovery is not None:
                    recovery.check_files()
                    capture_args['stock_reader']=lambda wp,tlb,read:recovery.read_stock(wp,tlb,read,diag)
                state=capture_guarded_mill_inventory(sw,clsid,typelib_path,expected_document_path,process_id=process_id,
                    expected_source_sha256=expected_source_sha256,check=check,diagnostic=diag,**capture_args)
                if state['document']!=baseline:raise ValueError('Document changed during read-only inventory')
                report[phase]=state
                if recovery is not None and not state.get('feature_errors'):
                    report.setdefault('recovery_delta',{})[phase]=recovery.verify_inventory(state,captured_process_id=process_id)
                    recovery.check_files()
                persist();check()
            if not _same_inventory(report['before'],report['after']):raise ValueError('Inventory changed during read-only inspection')
        check(active=False)
        if identity()!=baseline:raise ValueError('Document/source changed during event cleanup')
        report['diagnostic_enumeration_complete']=True
        if report['before'].get('feature_errors') or report['after'].get('feature_errors'):
            report['reason']='DIAGNOSTIC_CAPABILITY_ERRORS_FULL_GEOMETRY_AND_REBIND_NOT_VERIFIED'
            raise ValueError('Diagnostic enumeration completed with recorded native capability errors')
        if recovery is not None:
            recovery.check_files();report['recovery_delta_verified']=True
            report['saved_process_rebind_verified']=recovery.summary().get('saved_process_rebind_required') is True
        report.update(status='review_required',phase='finished',inventory_read_complete=True,readback_verified=True,
            state_sha256=_digest(report['before']),reason='RAW_MILL_INVENTORY_ONLY_GEOMETRY_AND_MACHINING_UNQUALIFIED')
    except Exception as exc:
        if recovery is not None:
            report['recovery_delta_verified']=False;report['saved_process_rebind_verified']=False
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),
            inventory_read_complete=False,readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:
            report.update(status='error',receipt_write_error=_error(exc),readback_verified=False,inventory_read_complete=False)
            if recovery is not None:
                report['recovery_delta_verified']=False;report['saved_process_rebind_verified']=False
    return report
