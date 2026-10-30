"""Read-only compound strategy catalogues and bounded native step dimensions."""
from copy import deepcopy
from functools import partial
from pathlib import Path
from scripts.sw_cam import _member, _error
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request, _same_inventory
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan, read_header
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

SCOPE = 'MILL_SAVED_COMPOUND_STRATEGY_READ_V1'
MAX_CATALOGUE_ITEMS = 128
MAX_NAME_LENGTH = 4096


def bounded_integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(label + ' must be a bounded strict integer')
    return value


def bounded_name(value, label):
    if value is not None and (type(value) is not str or len(value) > MAX_NAME_LENGTH):
        raise ValueError(label + ' must be a bounded BSTR observation')
    return value


def catalogue_observation(value):
    """Retain observed Python representation; do not infer native VARIANT type."""
    out = dict(observed_representation=type(value).__name__, native_vartype=None,
               native_vartype_verified=False, values=None, names_enumeration_verified=False)
    if value is None:
        return out
    if type(value) is str:
        out['values'] = bounded_name(value, 'catalogue string')
        return out
    if type(value) not in (list, tuple) or len(value) > MAX_CATALOGUE_ITEMS:
        raise ValueError('Bounded flat string catalogue required')
    if any(type(v) is not str or len(v) > MAX_NAME_LENGTH for v in value):
        raise ValueError('Catalogue must contain bounded strings only')
    out.update(values=list(value), names_enumeration_verified=True)
    return out


def validate_compound_scope(anchor, feature_id, owner_id, step_count):
    bounded_integer(feature_id, 'compound feature ID', 1, 2**32-1)
    bounded_integer(owner_id, 'compound owner ID', 1, 2**32-1)
    bounded_integer(step_count, 'expected step count', 1, 64)
    rows = [r for r in anchor.state['features'] if r['geometry']['native_id'] == feature_id]
    if (len(rows) != 1 or rows[0]['setup_native_id'] != owner_id
            or rows[0]['geometry']['volume_type'] != 11
            or rows[0]['geometry']['suppressed'] is not False):
        raise ValueError('Saved exact multi-step feature header and owner required')
    return deepcopy(rows[0]['geometry'])


def read_compound_strategy(state, native, read, typed, diagnostic, *,
                           feature_id, owner_id, step_count, expected_header, boundary, observation="strategy"):
    """Read the selected observation; step modes remain explicit qualification probes."""
    boundary()
    doc = native['doc']
    result = diagnostic.setdefault('compound_strategy', {})
    raw = read(doc, 'GetCWObjectFromID', 1, feature_id)
    if not isinstance(raw, (tuple, list)) or len(raw) != 2 or raw[1] is not True or raw[0] is None:
        raise ValueError('Exact compound feature lookup failed')
    header, base = read_header(raw[0], doc, read, typed, owner_id)
    if header != expected_header or _object_id(doc, base, read) != feature_id:
        raise ValueError('Compound identity or header changed')
    current = [r for r in state['features'] if r['geometry']['native_id'] == feature_id]
    if len(current) != 1 or current[0]['geometry'] != expected_header:
        raise ValueError('Compound differs from compact feature capture')
    obj = typed(raw[0], 'ICWMultiStepFeature')
    count = bounded_integer(read(obj, 'GetNumOfSteps'), 'native step count', 1, 64)
    if count != step_count:
        raise ValueError('Compound step count changed')
    if observation in ("interior_step_1","three_step_profile"):
        from scripts.sw_cam_compound_step_probe import read_interior_step, read_three_step_profile
        reader=read_interior_step if observation=="interior_step_1" else read_three_step_profile
        result.update(feature_native_id=feature_id,owner_setup_native_id=owner_id,
                      number_of_steps=count,**reader(obj,count=count,read=read,typed=typed))
        if bounded_integer(read(obj,'GetNumOfSteps'),'after step count',1,64)!=count:
            raise ValueError('Compound count changed during step probe')
        if _object_id(doc,read(base,'GetOwner'),read)!=owner_id:
            raise ValueError('Compound owner changed during step probe')
        boundary()
        result.update(metadata_read_complete=True,catalogues_read_complete=False,
            strategy_assigned=False,strategy_suitability_verified=False,feature_geometry_changed=False)
        return
    if observation != "strategy":raise ValueError('Unknown compound observation')
    attribute = bounded_integer(read(obj, 'Attribute'), 'Attribute', -(2**31), 2**31-1)
    pair = read(obj, 'GetAttribute')
    if not isinstance(pair, (tuple, list)) or len(pair) != 2:
        raise ValueError('GetAttribute must return name and ID')
    name = bounded_name(pair[0], 'attribute name')
    pair_id = bounded_integer(pair[1], 'GetAttribute ID', -(2**31), 2**31-1)
    if pair_id != attribute:
        raise ValueError('Attribute property and GetAttribute disagree')
    result.update(feature_native_id=feature_id, owner_setup_native_id=owner_id,
                  number_of_steps=count, attribute_id=attribute, attribute_name=name,
                  active_attribute_name=bounded_name(read(obj, 'IGetActiveAttribute'), 'active name'))
    result['mill_attributes'] = catalogue_observation(read(obj, 'IGetAllAttributes'))
    result['multi_step_attributes'] = catalogue_observation(read(obj, 'IGetAllAttributes2'))
    # Re-read stable fields after the catalogue calls without changing interpretation.
    after_pair = read(obj, 'GetAttribute')
    after_attribute = bounded_integer(read(obj, 'Attribute'), 'after Attribute', -(2**31), 2**31-1)
    after_count = bounded_integer(read(obj, 'GetNumOfSteps'), 'after step count', 1, 64)
    if (not isinstance(after_pair, (tuple, list)) or len(after_pair) != 2
            or type(after_pair[1]) is not int or after_pair[1] != attribute or after_pair[0] != name
            or after_attribute != attribute):
        raise ValueError('Compound attributes changed while reading catalogues')
    if after_count != count:
        raise ValueError('Compound step count changed after catalogues')
    if _object_id(doc, read(base, 'GetOwner'), read) != owner_id:
        raise ValueError('Compound owner changed after catalogues')
    boundary()
    result.update(metadata_read_complete=True, step_dimensions_read=False,
                  index_base_verified=False, step_dimensions_reason='NO_PRIMARY_INDEX_BASE_CONTRACT',
                  feature_geometry_changed=False, strategy_assigned=False,
                  strategy_suitability_verified=False, production_qualified=False)



def capture_compound_target(app, typelib_path, *, identity, check, diagnostic,
        feature_id, owner_id, step_count, expected_header, observation="strategy"):
    """Read the target only; the previously verified plan remains provenance."""
    from scripts.sw_cam_generation import _typed
    diagnostic.update(capture_complete=False, native_read_count=0,
                      scope='selected_compound_only', full_plan_reread=False)
    initial = identity()
    def boundary():
        check()
        if identity() != initial:
            raise ValueError('Target read document identity changed')
    def read(obj, name, *args):
        check()
        diagnostic['native_read_count'] += 1
        diagnostic['stage'] = name
        if diagnostic['native_read_count'] > 256:
            raise ValueError('Selected compound read budget exceeded')
        value = _member(obj, name, *args)
        check()
        return value
    def typed(obj, name):
        check()
        result = _typed(obj, name, typelib_path)
        if result is None:
            raise ValueError('Missing typed compound context')
        check()
        return result
    doc = typed(read(app, 'IGetActiveDoc'), 'ICWDoc3')
    doc_type = read(doc, 'GetDocType')
    if type(doc_type) is not int or doc_type != 1:
        raise ValueError('Exact CAM part required')
    raw = read(doc, 'GetCWObjectFromID', 1, feature_id)
    if not isinstance(raw, (tuple, list)) or len(raw) != 2 or raw[1] is not True:
        raise ValueError('Exact target lookup failed')
    header, _ = read_header(raw[0], doc, read, typed, owner_id)
    if header != expected_header:
        raise ValueError('Current compound header differs from saved evidence')
    state = dict(document=deepcopy(initial), capture_scope='selected_compound_only',
        features=[dict(setup_native_id=owner_id, geometry=deepcopy(header))])
    details = diagnostic.setdefault('operation_details', {})
    read_compound_strategy(state, {'doc': doc}, read, typed, details,
        feature_id=feature_id, owner_id=owner_id, step_count=step_count,
        expected_header=expected_header, boundary=boundary, observation=observation)
    boundary()
    diagnostic.update(capture_complete=True, stage='complete')
    return state


def inspect_saved_compound_strategy(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,saved_plan_receipt_path,saved_plan_receipt_sha256,
        expected_feature_native_id,expected_operation_native_ids,expected_operation_setup_native_id,
        expected_tool_native_id,expected_compound_feature_native_id,
        expected_compound_owner_setup_native_id,expected_compound_step_count,
        qualification_only,acknowledge_disposable_copy,receipt_path,message_policy='vendor_default',session_rebind_receipt_path=None,session_rebind_receipt_sha256=None,
        strategy_capture_mode="full_plan", compound_observation="strategy"):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status='error',phase='preflight',process_id=process_id,read_only=True,
        may_continue=False,mutation_attempted=False,AFR_attempted=False,GOP_attempted=False,
        GTP_attempted=False,model_saved=False,save_attempted=False,stock_edit_attempted=False,
        geometry_edit_attempted=False,material_edit_attempted=False,tool_assignment_attempted=False,
        strategy_assignment_attempted=False,TechDB_write_attempted=False,
        post_cleanup_CAM_getters=False,readback_verified=False,catalogues_read_complete=False,
        step_dimensions_read=False,index_base_verified=False,full_inventory_verified=False,
        world_geometry_verified=False,units_verified=False,strategy_suitability_verified=False,
        actual_incoming_WIP_verified=False,production_qualified=False,snapshot_diagnostics=[])
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
        if compound_observation not in ("strategy","interior_step_1","three_step_profile"):
            raise ValueError("Explicit supported compound observation required")
        report["compound_observation"]=compound_observation
        if strategy_capture_mode not in ('full_plan','target_only'):
            raise ValueError('Explicit supported strategy capture mode required')
        report.update(strategy_capture_mode=strategy_capture_mode,
                      full_plan_reread=strategy_capture_mode=='full_plan')
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
        expected_header=validate_compound_scope(anchor,expected_compound_feature_native_id,
            expected_compound_owner_setup_native_id,expected_compound_step_count)
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        report['anchor']=anchor.summary()
        report['compound_scope']=dict(feature_native_id=expected_compound_feature_native_id,
            owner_setup_native_id=expected_compound_owner_setup_native_id,
            expected_step_count=expected_compound_step_count,expected_header=expected_header,observation=compound_observation)
        baseline=identity()
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Identity changed acquiring CAM event host')
        session=CamMessageSession(app,typelib_path)
        with session:
            for phase in ('before','after'):
                check();report['phase']=phase;diag=dict(phase=phase)
                report['snapshot_diagnostics'].append(diag);persist()
                if strategy_capture_mode == 'target_only':
                    state = capture_compound_target(app,typelib_path,identity=identity,check=check,
                        diagnostic=diag,feature_id=expected_compound_feature_native_id,
                        owner_id=expected_compound_owner_setup_native_id,
                        step_count=expected_compound_step_count,expected_header=expected_header,observation=compound_observation)
                else:
                    state,_=capture_selected_plan(sw,clsid,typelib_path,expected_document_path,
                        process_id=process_id,expected_source_sha256=expected_source_sha256,
                        evidence=anchor,check=check,diagnostic=diag,progress=persist,
                        operation_details_reader=partial(read_compound_strategy,
                            feature_id=expected_compound_feature_native_id,
                            owner_id=expected_compound_owner_setup_native_id,
                            step_count=expected_compound_step_count,expected_header=expected_header,observation=compound_observation))
                    if state['document']!=baseline:raise ValueError('Document changed during strategy inspection')
                    anchor.verify(state)
                details=deepcopy(diag['operation_details']['compound_strategy'])
                if details.get('metadata_read_complete') is not True:
                    raise ValueError('Compound metadata read incomplete')
                report[phase]=state;report[phase+'_compound_strategy']=details;persist();check()
            if strategy_capture_mode == 'target_only':
                unchanged = report['before'] == report['after']
            else:
                unchanged = _same_inventory(report['before'],report['after'])
            if not unchanged:
                raise ValueError('Captured context changed')
            if report['before_compound_strategy']!=report['after_compound_strategy']:
                raise ValueError('Compound strategy observation changed between reads')
        check(active=False)
        if identity()!=baseline:raise ValueError('Identity changed during event cleanup')
        report.update(status='review_required',phase='finished',readback_verified=True,
            catalogues_read_complete=compound_observation=="strategy",
            step_dimensions_read=compound_observation!="strategy",
            index_base_verified=compound_observation=="three_step_profile",
            complete_step_coverage=compound_observation=="three_step_profile",state_sha256=_digest(report['before']),
            compound_strategy_sha256=_digest(report['before_compound_strategy']),
            saved_file_sha256=expected_source_sha256,
            reason='STABLE_RAW_COMPOUND_OBSERVATION_NO_MACHINING_QUALIFICATION')
    except Exception as exc:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,catalogues_read_complete=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:report.update(status='error',receipt_write_error=_error(exc),
            readback_verified=False,catalogues_read_complete=False)
    return report
