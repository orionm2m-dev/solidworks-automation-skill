"""Exact-feature, read-only native PROFILE header probe."""
from pathlib import Path
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap, _vector
from scripts.sw_cam_mill_units_qualification import _number, _nonnull
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_inventory_geometry import _integer, MAX_ISLANDS
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles, _check_capture_document
from scripts.sw_operation_guard import check_document_target

MAX_READS = 128
CW_OBJ_FEAT = 1


def validate_profile_headers_request(*, expected_feature_native_id, expected_owner_setup_native_id,
        expected_volume_type, expected_shape, expected_island_count, include_contours=False, **base):
    if type(include_contours) is not bool:
        raise ValueError('Strict include_contours boolean required')
    if include_contours:
        raise ValueError('CONTOUR_INDEX_CONTRACT_NOT_YET_QUALIFIED; use headers first')
    validate_inventory_request(**base)
    for name, value in (('feature ID', expected_feature_native_id),
                        ('owner setup ID', expected_owner_setup_native_id)):
        _integer(value, name, 1)
    if expected_feature_native_id == expected_owner_setup_native_id:
        raise ValueError('Feature and setup identities must differ')
    _integer(expected_volume_type, 'expected volume type')
    _integer(expected_shape, 'expected shape')
    _integer(expected_island_count, 'expected island count', 0, MAX_ISLANDS)


def _sketch_names(value, count):
    """Preserve the marshalled Python shape without inventing native VARTYPE."""
    out = dict(native_vartype=None, native_vartype_status='not_exposed_by_marshaller',
               observed_name_count=None, matches_sketch_count=None, count_relation_verified=False)
    if value is None:
        out.update(observed_representation='python_none', value=None,
                   native_null_or_empty_distinction_verified=False)
    elif type(value) is str:
        if len(value) > 4096:
            raise ValueError('Sketch name text exceeds probe bound')
        out.update(observed_representation='python_str', value=value)
    elif type(value) in (list, tuple):
        if len(value) > 64 or any(type(item) is not str or len(item) > 1024 for item in value):
            raise ValueError('Flat bounded string list required for sketch-name observation')
        out.update(observed_representation='python_' + type(value).__name__,
                   value=list(value), observed_name_count=len(value), matches_sketch_count=len(value)==count)
    else:
        raise ValueError('Unsupported marshalled sketch-name representation; no coercion')
    return out


def _end_condition(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(name + ' must return depth,type,name,reversed')
    depth, kind, label, reversed_flag = value
    if (label is not None and (type(label) is not str or len(label) > 1024)) or type(reversed_flag) is not bool:
        raise ValueError('Strict bounded end-condition name and Boolean required')
    return dict(depth_native=_number(depth),
                type_raw=_integer(kind, name + ' type', -0x80000000, 0x7FFFFFFF),
                name=label, name_observed_representation='python_none' if label is None else 'python_str',
                is_reversed=reversed_flag, units_verified=False)


def read_profile_feature_headers(doc, *, selected, read, typed, diagnostic, progress=lambda: None):
    """Read the exact PROFILE metadata route; no indices or contour API calls."""
    out = dict(native_id=selected['feature_native_id'], read_complete=False,
        representation='ICWProfileFeature metadata', profile_headers_read_complete=False,
        profile_geometry_complete=False, contour_status='not_requested',
        indexed_methods_called=False, native_behavior_qualified=False, units_verified=False)
    diagnostic.update(state=out, stage='GetCWObjectFromID')
    result = read(doc, 'GetCWObjectFromID', CW_OBJ_FEAT, selected['feature_native_id'])
    if not isinstance(result, (list, tuple)) or len(result) != 2 or result[1] is not True:
        raise ValueError('Exact feature lookup requires object and status=true')
    raw = _nonnull(result[0], 'exact feature')
    base = _nonnull(typed(raw, 'ICWFeature'), 'ICWFeature')
    if _object_id(doc, base, read) != selected['feature_native_id']:
        raise ValueError('Feature lookup identity differs')
    owner = _nonnull(read(base, 'GetOwner'), 'feature owner setup')
    out['owner_setup_native_id'] = _object_id(doc, owner, read)
    if out['owner_setup_native_id'] != selected['owner_setup_native_id']:
        raise ValueError('Feature owner setup differs')
    out['suppressed'] = read(base, 'Suppressed')
    if out['suppressed'] is not False:
        raise ValueError('Exact feature must be explicitly unsuppressed')
    mill = _nonnull(typed(raw, 'ICWMillFeature'), 'ICWMillFeature')
    out['volume_type'] = _integer(read(mill, 'VolumeType'), 'VolumeType')
    out['shape'] = _integer(read(mill, 'Shape'), 'Shape')
    if out['volume_type'] != selected['volume_type'] or out['shape'] != selected['shape']:
        raise ValueError('Feature classification differs')
    out['island_count'] = _integer(read(mill, 'IGetIslandCount'), 'IGetIslandCount', 0, MAX_ISLANDS)
    if out['island_count'] != selected['island_count']:
        raise ValueError('Feature island count differs')
    diagnostic['stage'] = 'QI ICWProfileFeature'
    profile = _nonnull(typed(raw, 'ICWProfileFeature'), 'ICWProfileFeature')
    count = _integer(read(profile, 'GetSketchCount'), 'GetSketchCount', 0, 64)
    out['sketch_count'] = count
    diagnostic['stage'] = 'GetSketchNameList'
    raw_names = read(profile, 'GetSketchNameList')
    out['sketch_names_return_python_type'] = type(raw_names).__name__
    out['sketch_names'] = _sketch_names(raw_names, count)
    progress()
    out['end_conditions'] = {}
    for name in ('GetEndCondition1', 'GetEndCondition2'):
        diagnostic['stage'] = name
        out['end_conditions'][name] = _end_condition(read(profile, name), name)
        progress()
    if _integer(read(profile, 'GetSketchCount'), 'GetSketchCount', 0, 64) != count:
        raise ValueError('Sketch count changed')
    if _integer(read(mill, 'IGetIslandCount'), 'IGetIslandCount', 0, MAX_ISLANDS) != out['island_count']:
        raise ValueError('Island count changed')
    if _object_id(doc, base, read) != selected['feature_native_id']:
        raise ValueError('Feature identity changed')
    if _object_id(doc, _nonnull(read(base, 'GetOwner'), 'owner setup'), read) != selected['owner_setup_native_id']:
        raise ValueError('Feature owner changed')
    out['profile_headers_read_complete'] = True
    out['read_complete'] = True
    diagnostic['stage'] = 'complete'
    return out


def capture_profile_feature_headers(sw, app, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, baseline, selected, check, diagnostic, progress):
    diagnostic['native_read_count'] = 0
    with _CaptureReadFiles(expected_document_path) as files:
        def guard():
            check()
            _check_capture_document(sw, {'process_id': process_id}, {'document': baseline})
            dirty = _member(sw.ActiveDoc, 'GetSaveFlag')
            if type(dirty) is not bool or dirty != baseline['needs_save']:
                raise ValueError('Active document dirty state changed')
            files.check()
            check()
        def read(obj, name, *args):
            guard()
            if diagnostic['native_read_count'] >= MAX_READS:
                raise ValueError('Exact-feature probe read budget exceeded')
            diagnostic.update(stage=name, native_read_count=diagnostic['native_read_count'] + 1)
            value = _member(obj, name, *args)
            guard()
            return value
        def typed(raw, name):
            guard()
            if diagnostic['native_read_count'] >= MAX_READS:
                raise ValueError('Exact-feature probe read budget exceeded')
            diagnostic.update(stage='QI '+name, native_read_count=diagnostic['native_read_count'] + 1)
            value = _typed(raw, name, typelib_path)
            guard()
            return value
        doc = typed(_nonnull(read(app, 'IGetActiveDoc'), 'active CAM document'), 'ICWDoc3')
        result = read_profile_feature_headers(doc, selected=selected, read=read, typed=typed,
                                            diagnostic=diagnostic, progress=progress)
        guard()
        if raw_part_identity(sw) != baseline or _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError('Document or saved source changed during probe')
        return result


def inspect_mill_profile_headers(sw, clsid, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, expected_feature_native_id, expected_owner_setup_native_id,
        expected_volume_type, expected_shape, expected_island_count, qualification_only,
        acknowledge_disposable_copy, receipt_path, message_policy='vendor_default', include_contours=False):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(status='error', phase='preflight', process_id=process_id, read_only=True,
        mutation_attempted=False, AFR_attempted=False, GOP_attempted=False, GTP_attempted=False,
        model_saved=False, TechDB_write_attempted=False, post_cleanup_CAM_getters=False,
        full_inventory_verified=False, profile_read_complete=False, readback_verified=False,
        profile_headers_read_complete=False, representation_readback_verified=False,
        profile_geometry_complete=False, include_contours=include_contours,
        contour_index_contract_verified=False, contour_limitation='CONTOUR_INDEX_CONTRACT_NOT_YET_QUALIFIED',
        native_behavior_qualified=False, production_qualified=False, may_continue=False,
        apply_eligible=False, units_verified=False, snapshots_diagnostics=[])
    receipt = None
    created = False
    session = None
    def persist():
        if created:
            _write_receipt(receipt, report)
    def identity():
        pid = _member(sw, 'GetProcessID')
        if type(pid) is not int or pid != process_id:
            raise ValueError('Exact process differs')
        doc = raw_part_identity(sw)
        check_document_target(doc['path'], doc['title'], expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError('Saved source changed')
        return doc
    def check(active=True):
        value = session.summary()
        report['messages'] = value
        if (value.get('subscribed') is not True or
            (active and value.get('active') is not True) or
            (not active and (value.get('active') is not False or value.get('disconnected') is not True)) or
            any(value.get(k) for k in ('event_count', 'overflow', 'callback_errors',
                'callback_error_count', 'subscription_error', 'disconnect_errors'))):
            raise ValueError('CAM event or cleanup requires stop')
    try:
        validate_profile_headers_request(process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy, receipt_path=receipt_path,
            message_policy=message_policy, expected_feature_native_id=expected_feature_native_id,
            expected_owner_setup_native_id=expected_owner_setup_native_id,
            expected_volume_type=expected_volume_type, expected_shape=expected_shape,
            expected_island_count=expected_island_count, include_contours=include_contours)
        selected = dict(feature_native_id=expected_feature_native_id,
            owner_setup_native_id=expected_owner_setup_native_id, volume_type=expected_volume_type,
            shape=expected_shape, island_count=expected_island_count, include_contours=include_contours)
        receipt = Path(receipt_path)
        _write_receipt(receipt, report, create=True)
        created = True
        report['selected'] = selected
        report['probe_scope'] = 'profile_headers_only'
        baseline = identity()
        if baseline['needs_save'] is not False:
            raise ValueError('Clean saved part required for exact-feature probe')
        report.update(document=baseline, saved_file_sha256=expected_source_sha256)
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline:
            raise ValueError('Document changed acquiring event host')
        session = CamMessageSession(app, typelib_path)
        with session:
            for phase in ('before', 'after'):
                check()
                report['phase'] = phase
                diagnostic = dict(phase=phase)
                report['snapshots_diagnostics'].append(diagnostic)
                persist()
                report[phase] = capture_profile_feature_headers(sw, app, typelib_path,
                    process_id=process_id, expected_document_path=expected_document_path,
                    expected_source_sha256=expected_source_sha256, baseline=baseline,
                    selected=selected, check=check, diagnostic=diagnostic, progress=persist)
                persist()
                check()
            if report['before'] != report['after']:
                raise ValueError('Exact feature island observations changed between snapshots')
        check(active=False)
        if identity() != baseline:
            raise ValueError('Document changed during cleanup')
        report.update(status='review_required', phase='finished', profile_read_complete=True,
            readback_verified=True, profile_headers_read_complete=True, representation_readback_verified=True,
            profile_geometry_complete=report['before']['profile_geometry_complete'],
            state_sha256=_digest(report['before']),
            reason='RAW_PROFILE_HEADERS_ONLY_NOT_CONTOURS_INVENTORY_OR_MANUFACTURING_APPROVAL')
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], phase='finished',
                      issue=_error(exc), profile_read_complete=False, readback_verified=False,
                      profile_headers_read_complete=False, representation_readback_verified=False, profile_geometry_complete=False)
    finally:
        if session is not None:
            report['messages'] = session.summary()
        try:
            persist()
        except Exception as exc:
            report.update(status='error', receipt_write_error=_error(exc),
                          profile_read_complete=False, readback_verified=False,
                          profile_headers_read_complete=False, representation_readback_verified=False, profile_geometry_complete=False)
    return report


