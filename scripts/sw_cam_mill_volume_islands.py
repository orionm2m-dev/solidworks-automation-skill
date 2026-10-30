"""Exact-feature, read-only ICWVolumeFeature island representation probe."""
from pathlib import Path
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap, _vector
from scripts.sw_cam_mill_units_qualification import _number, _nonnull
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains, _integer, _available, MAX_ISLANDS
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles, _check_capture_document
from scripts.sw_operation_guard import check_document_target

MAX_READS = 2048
CW_OBJ_FEAT = 1
CONTOURS = (('top', 'IGetTopSegChain'), ('bottom', 'IGetBottomSegChain'),
            ('wall', 'IGetWallSegChain'))


def validate_volume_islands_request(*, expected_feature_native_id, expected_owner_setup_native_id,
        expected_volume_type, expected_shape, expected_island_count, include_contours=False, **base):
    if type(include_contours) is not bool:
        raise ValueError('Strict include_contours boolean required')
    validate_inventory_request(**base)
    for name, value in (('feature ID', expected_feature_native_id),
                        ('owner setup ID', expected_owner_setup_native_id)):
        _integer(value, name, 1)
    if expected_feature_native_id == expected_owner_setup_native_id:
        raise ValueError('Feature and setup identities must differ')
    _integer(expected_volume_type, 'expected volume type')
    _integer(expected_shape, 'expected shape')
    _integer(expected_island_count, 'expected island count', 0, MAX_ISLANDS)


def read_volume_feature_islands(doc, *, selected, read, typed, diagnostic, progress=lambda: None):
    """One documented interface route; failure never attempts another representation."""
    out = dict(native_id=selected['feature_native_id'], items=[], read_complete=False,
               representation='ICWVolumeFeature.IGetIslands/ICWDispatchCollection/ICWIslandInfo',
               representation_native_qualified=False, units_verified=False,
               include_contours=selected['include_contours'], island_headers_read_complete=False,
               islands_geometry_complete=False,
               closed_loops_verified=False, island_nesting_verified=False)
    diagnostic.update(state=out, stage='GetCWObjectFromID')
    result = read(doc, 'GetCWObjectFromID', CW_OBJ_FEAT, selected['feature_native_id'])
    if (not isinstance(result, (tuple, list)) or len(result) != 2 or result[1] is not True):
        raise ValueError('Exact CAM feature lookup requires object and status=true')
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
    if (out['volume_type'] != selected['volume_type'] or out['shape'] != selected['shape']):
        raise ValueError('Feature classification differs')
    count = _integer(read(mill, 'IGetIslandCount'), 'IGetIslandCount', 0, MAX_ISLANDS)
    if count != selected['island_count']:
        raise ValueError('Feature island count differs from expected observation')
    out['declared_count'] = count
    diagnostic['stage'] = 'QI ICWVolumeFeature'
    volume = _nonnull(typed(raw, 'ICWVolumeFeature'), 'ICWVolumeFeature')
    diagnostic['stage'] = 'ICWVolumeFeature.IGetIslands'
    collection_raw = read(volume, 'IGetIslands')
    if not _available(collection_raw, 'volume islands'):
        out['collection_representation'] = 'null'
        if count:
            raise ValueError('Positive island count returned a null collection')
        collection = None
    else:
        collection = _nonnull(typed(collection_raw, 'ICWDispatchCollection'), 'island collection')
        observed = _integer(read(collection, 'Count'), 'collection Count', 0, MAX_ISLANDS)
        if observed != count:
            raise ValueError('Volume island collection and MILL feature counts differ')
        out.update(collection_representation='ICWDispatchCollection', collection_count=observed)
    budget = dict(curves=0, chains=0, islands=0)
    diagnostic['geometry_budget'] = budget
    for index in range(count):
        entry = dict(index=index, contours={}, read_complete=False)
        out['items'].append(entry)
        diagnostic.update(stage='island', island_index=index)
        progress()
        island = _nonnull(typed(read(collection, 'Item', index), 'ICWIslandInfo'), 'ICWIslandInfo')
        pos = _nonnull(typed(read(island, 'GetStartPosition'), 'ICWPosition'), 'ICWPosition')
        entry['start_native'] = _vector(read(pos, 'GetCoordinates'))
        entry['depth_native'] = _number(read(island, 'GetDepth'))
        budget['islands'] += 1
        for name, method in (CONTOURS if selected['include_contours'] else ()):
            detail = dict(state={})
            entry['contours'][name] = detail['state']
            diagnostic.update(stage=method, contour=name, contour_diagnostic=detail)
            progress()
            read_segment_chains(island, method, read=read, typed=typed,
                                diagnostic=detail, budget=budget)
        entry['read_complete'] = True
        progress()
    if collection is not None and _integer(read(collection, 'Count'), 'collection Count', 0, MAX_ISLANDS) != count:
        raise ValueError('Volume island collection count changed')
    if _integer(read(mill, 'IGetIslandCount'), 'IGetIslandCount', 0, MAX_ISLANDS) != count:
        raise ValueError('MILL feature island count changed')
    if _object_id(doc, base, read) != selected['feature_native_id']:
        raise ValueError('Feature identity changed')
    if _object_id(doc, _nonnull(read(base, 'GetOwner'), 'owner setup'), read) != selected['owner_setup_native_id']:
        raise ValueError('Feature owner changed')
    out['all_contours_available'] = selected['include_contours'] and all(c['status'] == 'observed'
        for item in out['items'] for c in item['contours'].values())
    out['island_headers_read_complete'] = True
    out['islands_geometry_complete'] = bool(out['all_contours_available'])
    out['contour_status'] = 'observed' if selected['include_contours'] else 'not_requested'
    out['read_complete'] = True
    diagnostic['stage'] = 'complete'
    return out


def capture_volume_feature_islands(sw, app, typelib_path, *, process_id, expected_document_path,
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
        result = read_volume_feature_islands(doc, selected=selected, read=read, typed=typed,
                                            diagnostic=diagnostic, progress=progress)
        guard()
        if raw_part_identity(sw) != baseline or _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError('Document or saved source changed during probe')
        return result


def inspect_mill_volume_islands(sw, clsid, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, expected_feature_native_id, expected_owner_setup_native_id,
        expected_volume_type, expected_shape, expected_island_count, qualification_only,
        acknowledge_disposable_copy, receipt_path, message_policy='vendor_default', include_contours=False):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(status='error', phase='preflight', process_id=process_id, read_only=True,
        mutation_attempted=False, AFR_attempted=False, GOP_attempted=False, GTP_attempted=False,
        model_saved=False, TechDB_write_attempted=False, post_cleanup_CAM_getters=False,
        full_inventory_verified=False, islands_read_complete=False, readback_verified=False,
        island_headers_read_complete=False, representation_readback_verified=False,
        islands_geometry_complete=False, include_contours=include_contours,
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
        validate_volume_islands_request(process_id=process_id, expected_document_path=expected_document_path,
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
        report['probe_scope'] = 'island_contours' if include_contours else 'island_headers_only'
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
                report[phase] = capture_volume_feature_islands(sw, app, typelib_path,
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
        report.update(status='review_required', phase='finished', islands_read_complete=True,
            readback_verified=True, island_headers_read_complete=True, representation_readback_verified=True,
            islands_geometry_complete=report['before']['islands_geometry_complete'],
            state_sha256=_digest(report['before']),
            reason='RAW_VOLUME_ISLAND_REPRESENTATION_ONLY_NOT_FULL_INVENTORY_OR_MANUFACTURING_APPROVAL')
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], phase='finished',
                      issue=_error(exc), islands_read_complete=False, readback_verified=False,
                      island_headers_read_complete=False, representation_readback_verified=False, islands_geometry_complete=False)
    finally:
        if session is not None:
            report['messages'] = session.summary()
        try:
            persist()
        except Exception as exc:
            report.update(status='error', receipt_write_error=_error(exc),
                          islands_read_complete=False, readback_verified=False,
                          island_headers_read_complete=False, representation_readback_verified=False, islands_geometry_complete=False)
    return report
