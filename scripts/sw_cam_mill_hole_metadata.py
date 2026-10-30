"""Bounded, read-only CAM hole metadata; no indexed steps or geometry approval."""
from pathlib import Path
from time import monotonic
import json
import re

from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap, _vector
from scripts.sw_cam_mill_units_qualification import _number, _nonnull
from scripts.sw_cam_mill_inventory import validate_inventory_request, _same_inventory
from scripts.sw_cam_mill_inventory_geometry import _integer, _available
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles, _check_capture_document
from scripts.sw_operation_guard import absolute_document_path, check_document_target

MAX_FEATURES = 5
MAX_CHILDREN = 64
MAX_STEPS = 64
MAX_READS = 4096
CW_OBJ_FEAT = 1
_ALLOWED_TYPES = {1: 'ICWMSHoleFeat', 9: 'ICWMSHoleCtrSunkFeat', 11: 'ICWMultiStepFeature'}


def _clean_messages(value, active=False):
    if (not isinstance(value, dict) or value.get('subscribed') is not True
            or value.get('active') is not active
            or (not active and value.get('disconnected') is not True)
            or any(value.get(k) for k in ('event_count', 'overflow', 'callback_errors',
                'callback_error_count', 'subscription_error', 'disconnect_errors'))):
        raise ValueError('Clean CAM event transport and cleanup required')


def validate_hole_metadata_request(*, expected_feature_native_ids,
        inventory_receipt_path, inventory_receipt_sha256, **base):
    validate_inventory_request(**base)
    if (type(expected_feature_native_ids) is not list
            or not 1 <= len(expected_feature_native_ids) <= MAX_FEATURES):
        raise ValueError('Explicit bounded list of feature IDs required')
    for value in expected_feature_native_ids:
        _integer(value, 'feature ID', 1)
    if len(set(expected_feature_native_ids)) != len(expected_feature_native_ids):
        raise ValueError('Duplicate feature IDs forbidden')
    p = Path(inventory_receipt_path)
    if (type(inventory_receipt_path) is not str or not absolute_document_path(inventory_receipt_path)
            or p.suffix.lower() != '.json' or not p.is_file() or p.is_symlink()):
        raise ValueError('Existing absolute regular inventory receipt required')
    if (type(inventory_receipt_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', inventory_receipt_sha256) is None):
        raise ValueError('Exact inventory receipt SHA required')
    if p.resolve() == Path(base['receipt_path']).resolve():
        raise ValueError('Input and output receipts must differ')


def load_hole_metadata_anchor(path, sha, *, process_id, expected_document_path,
                              expected_source_sha256, feature_ids):
    """Use a pinned, complete diagnostic enumeration, never promote its geometry."""
    p = Path(path)
    data = p.read_bytes()
    import hashlib
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError('Inventory receipt SHA differs')
    value = json.loads(data.decode('utf-8-sig'))
    if (value.get('phase') != 'finished' or value.get('status') != 'error'
            or value.get('reason') != 'DIAGNOSTIC_CAPABILITY_ERRORS_FULL_GEOMETRY_AND_REBIND_NOT_VERIFIED'
            or value.get('diagnostic_enumeration_complete') is not True
            or value.get('read_only') is not True or type(value.get('process_id')) is not int
            or value.get('process_id') != process_id):
        raise ValueError('Finished diagnostic enumeration for exact current PID required')
    for key in ('mutation_attempted', 'AFR_attempted', 'GOP_attempted', 'GTP_attempted',
                'model_saved', 'TechDB_write_attempted', 'post_cleanup_CAM_getters',
                'inventory_read_complete', 'readback_verified', 'saved_process_rebind_verified'):
        if value.get(key) is not False:
            raise ValueError('Diagnostic anchor flags differ: ' + key)
    _clean_messages(value.get('messages'))
    before, after = value.get('before'), value.get('after')
    if not isinstance(before, dict) or not isinstance(after, dict) or not _same_inventory(before, after):
        raise ValueError('Two stable diagnostic snapshots required')
    doc = before['document']
    check_document_target(doc['path'], doc.get('title'), expected_path=expected_document_path, required=True)
    if (doc.get('needs_save') is not False or type(doc.get('type')) is not int or doc.get('type') != 1
            or before.get('saved_file_sha256') != expected_source_sha256
            or type(before.get('operation_count')) is not int or before.get('operation_count') != 0):
        raise ValueError('Exact clean saved source and zero operations required')
    setups = before.get('feature_setups')
    rows = before.get('features')
    if (type(rows) is not list or type(setups) is not list or len(rows) > 64
            or sum(x['feature_count'] for x in setups) != len(rows)):
        raise ValueError('Complete bounded diagnostic membership required')
    selected = []
    seen = set()
    by_id = {}
    for item in rows:
        row = item['geometry']
        native_id = _integer(row['native_id'], 'anchor feature ID', 1)
        if native_id in seen:
            raise ValueError('Duplicate anchor feature ID')
        seen.add(native_id)
        by_id[native_id] = item
    for native_id in feature_ids:
        if native_id not in by_id:
            raise ValueError('Requested feature missing from anchor')
        item = by_id[native_id]
        row = item['geometry']
        setup_id = _integer(item['setup_native_id'], 'owner setup ID', 1)
        setup = [x for x in setups if x['native_id'] == setup_id]
        if (len(setup) != 1 or row.get('volume_type') not in _ALLOWED_TYPES
                or type(row.get('volume_type')) is not int
                or row.get('shape_raw') != 2 or type(row.get('shape_raw')) is not int
                or row.get('suppressed') is not False):
            raise ValueError('Pinned circular unsuppressed hole classification required')
        selected.append(dict(feature_native_id=native_id, owner_setup_native_id=setup_id,
            volume_type=row['volume_type'], subtype_raw=_integer(row['subtype_raw'], 'subtype'),
            shape_raw=row['shape_raw'], name=row['name'], axis_native=row['axis_native'],
            start_native=row['start_native'], depth_native=row['depth_native']))
    return dict(document=doc, selected=selected, saved_file_sha256=expected_source_sha256,
                diagnostic_anchor_readback_verified=False,
                anchor_geometry_complete=False, source_process_id=process_id)


def _nullable_number(value):
    return dict(status='observed_null', value=None) if value is None else dict(
        status='observed', value=_number(value))


def _nullable_text(value):
    if value is not None and (type(value) is not str or len(value) > 4096):
        raise ValueError('Bounded native text or null required')
    return dict(status='observed_null' if value is None else 'observed', value=value)


def read_hole_metadata(doc, *, selected, read, typed, boundary, diagnostic, progress):
    """Callback-only bounded probe; all references remain tied to the exact CAM doc."""
    out = dict(features=[], metadata_complete=False, full_geometry_complete=False,
               units_verified=False, indexed_step_methods_called=False)
    diagnostic['state'] = out

    def oid(raw):
        return _object_id(doc, raw, read)

    def point(raw):
        if not _available(raw, 'position'):
            return dict(status='observed_null', value=None)
        return dict(status='observed', value=_vector(read(typed(raw, 'ICWPosition'), 'GetCoordinates')))

    def thread(raw):
        if not _available(raw, 'thread'):
            return dict(status='observed_null', value=None, absence_semantics_verified=False)
        obj = typed(raw, 'ICWThread')
        value = dict(status='observed', depth_native=_nullable_number(read(obj, 'GetDepth')),
            tap_form=_nullable_text(read(obj, 'GetTapForm')),
            tap_designation=_nullable_text(read(obj, 'GetTapDesignation')))
        metric = read(obj, 'GetIsMetric')
        if metric is not None and type(metric) is not bool:
            raise ValueError('Native metric Boolean or null required')
        value['is_metric'] = metric
        for method in ('GetTapType', 'GetThreadType'):
            raw_value = read(obj, method)
            value[method] = None if raw_value is None else _integer(raw_value, method, -0x80000000, 0x7fffffff)
        return value

    def header(raw):
        base = typed(raw, 'ICWFeature')
        mill = typed(raw, 'ICWMillFeature')
        value = dict(native_id=oid(base), owner_native_id=oid(_nonnull(read(base, 'GetOwner'), 'feature owner')),
            suppressed=read(base, 'Suppressed'), name=read(base, 'FeatureName'),
            volume_type=_integer(read(mill, 'VolumeType'), 'VolumeType'),
            subtype_raw=_integer(read(mill, 'SubType'), 'SubType'),
            shape_raw=_integer(read(mill, 'Shape'), 'Shape'),
            axis_native=_vector(read(base, 'Axis')),
            start_native=_vector(read(mill, 'GetStartPosition')),
            depth_native=_number(read(mill, 'Depth')),
            is_pattern=read(mill, 'IsPatternFeature'))
        if (type(value['suppressed']) is not bool or type(value['is_pattern']) is not bool
                or type(value['name']) is not str or len(value['name']) > 1024):
            raise ValueError('Strict native header values required')
        _integer(value['native_id'], 'feature identity', 1)
        _integer(value['owner_native_id'], 'owner identity', 1)
        return value

    def parameters(raw, row):
        kind = row['volume_type']
        if kind not in _ALLOWED_TYPES:
            raise ValueError('Unexpected hole volume type')
        obj = typed(raw, _ALLOWED_TYPES[kind])
        value = dict(interface=_ALLOWED_TYPES[kind], units_verified=False,
                     parameter_read_complete=False, full_geometry_complete=False)
        row['parameters'] = value
        if kind == 11:
            value['number_of_steps'] = _integer(read(obj, 'GetNumOfSteps'), 'GetNumOfSteps', 0, MAX_STEPS)
            value['depth_native'] = _nullable_number(read(obj, 'GetDepth'))
            value['start_native'] = point(read(obj, 'GetStartPoint'))
            value['step_parameters_status'] = 'not_requested_index_contract_unqualified'
        else:
            value['diameter_native'] = _nullable_number(read(obj, 'diameter'))
            value['depth_native'] = _nullable_number(read(obj, 'GetDepth'))
            value['start_native'] = point(read(obj, 'GetStartPosition'))
            value['tip_angle_native'] = _nullable_number(read(obj, 'GetTipAngle'))
            value['thread'] = thread(read(obj, 'GetThread'))
            if kind == 9:
                value['diameter_getter_native'] = _nullable_number(read(obj, 'GetDiameter'))
                value['sink_diameter_native'] = _nullable_number(read(obj, 'SinkDiameter'))
                value['sink_angle_native'] = _nullable_number(read(obj, 'SinkAngle'))
        value['parameter_read_complete'] = True

    for index, expected in enumerate(selected):
        boundary()
        diagnostic.update(feature_index=index, feature_native_id=expected['feature_native_id'])
        entry = dict(read_complete=False)
        out['features'].append(entry)
        progress()
        lookup = read(doc, 'GetCWObjectFromID', CW_OBJ_FEAT, expected['feature_native_id'])
        if not isinstance(lookup, (tuple, list)) or len(lookup) != 2 or lookup[1] is not True:
            raise ValueError('Exact feature lookup requires object and true')
        raw = _nonnull(lookup[0], 'exact hole feature')
        row = header(raw)
        entry.update(row)
        if (row['native_id'] != expected['feature_native_id']
                or row['owner_native_id'] != expected['owner_setup_native_id']
                or row['suppressed'] is not False
                or any(row[key] != expected[key] for key in
                    ('volume_type', 'subtype_raw', 'shape_raw', 'name', 'axis_native', 'start_native', 'depth_native'))):
            raise ValueError('Live feature differs from diagnostic anchor')
        if row['is_pattern']:
            pattern = typed(raw, 'ICWPatternFeature')
            collection = typed(_nonnull(read(pattern, 'IGetEnumChildFeatures'), 'pattern children'), 'ICWDispatchCollection')
            count = _integer(read(collection, 'Count'), 'pattern child count', 0, MAX_CHILDREN)
            entry['pattern_children'] = dict(count=count, items=[], read_complete=False)
            child_ids = set()
            for child_index in range(count):
                boundary()
                diagnostic['child_index'] = child_index
                child_raw = _nonnull(read(collection, 'Item', child_index), 'pattern child')
                child = header(child_raw)
                entry['pattern_children']['items'].append(child)
                if (child['native_id'] in child_ids or child['native_id'] == row['native_id']
                        or child['owner_native_id'] not in (row['native_id'], expected['owner_setup_native_id'])
                        or child['volume_type'] != row['volume_type'] or child['shape_raw'] != row['shape_raw']
                        or child['is_pattern'] is not False):
                    raise ValueError('Unexpected or recursive pattern child identity/classification')
                child_ids.add(child['native_id'])
                parameters(child_raw, child)
                if header(child_raw) != {key: child[key] for key in row}:
                    raise ValueError('Pattern child header changed')
                boundary()
                progress()
            diagnostic.pop('child_index', None)
            if _integer(read(collection, 'Count'), 'pattern count', 0, MAX_CHILDREN) != count:
                raise ValueError('Pattern child count changed')
            entry['pattern_children']['read_complete'] = True
            entry['parameters'] = dict(status='pattern_parent_parameters_not_assumed')
        else:
            parameters(raw, entry)
        if header(raw) != row:
            raise ValueError('Feature header changed')
        boundary()
        entry['read_complete'] = True
        progress()
    out['metadata_complete'] = True
    return out


def capture_hole_metadata(sw, app, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, inventory_receipt_path, inventory_receipt_sha256,
        baseline, selected, check, diagnostic, progress):
    """Read-only batched identity guard; event and both file guards per getter/QI."""
    diagnostic.update(native_read_count=0, native_qi_count=0)
    with _CaptureReadFiles(expected_document_path, inventory_receipt_path) as files:
        def light():
            check()
            files.check()
            check()
        def boundary():
            light()
            _check_capture_document(sw, {'process_id': process_id}, {'document': baseline})
            dirty = _member(sw.ActiveDoc, 'GetSaveFlag')
            if type(dirty) is not bool or dirty != baseline['needs_save']:
                raise ValueError('Active document dirty state changed')
            light()
        def consume(name, qi=False):
            if diagnostic['native_read_count'] + diagnostic['native_qi_count'] >= MAX_READS:
                raise ValueError('Hole probe native budget exceeded')
            key = 'native_qi_count' if qi else 'native_read_count'
            diagnostic[key] += 1
            diagnostic['stage'] = name
        def read(obj, name, *args):
            light(); consume(name)
            value = _member(obj, name, *args)
            light()
            return value
        def typed(raw, name):
            light(); consume('QI '+name, True)
            value = _typed(raw, name, typelib_path)
            light()
            return value
        def hashes():
            if (_file_hash(expected_document_path) != expected_source_sha256
                    or _file_hash(inventory_receipt_path) != inventory_receipt_sha256):
                raise ValueError('Pinned source or inventory changed')
        boundary(); hashes()
        doc = typed(_nonnull(read(app, 'IGetActiveDoc'), 'CAM document'), 'ICWDoc3')
        boundary()
        result = read_hole_metadata(doc, selected=selected, read=read, typed=typed,
            boundary=boundary, diagnostic=diagnostic, progress=progress)
        boundary(); hashes()
        if raw_part_identity(sw) != baseline:
            raise ValueError('Document changed during hole capture')
        return result


def inspect_mill_hole_metadata(sw, clsid, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, expected_feature_native_ids, inventory_receipt_path,
        inventory_receipt_sha256, qualification_only, acknowledge_disposable_copy,
        receipt_path, message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    started = monotonic()
    report = dict(status='error', phase='preflight', process_id=process_id, read_only=True,
        mutation_attempted=False, AFR_attempted=False, GOP_attempted=False, GTP_attempted=False,
        model_saved=False, TechDB_write_attempted=False, post_cleanup_CAM_getters=False,
        full_inventory_verified=False, saved_process_rebind_verified=False,
        metadata_read_complete=False, readback_verified=False, full_geometry_complete=False,
        native_behavior_qualified=False, production_qualified=False, may_continue=False,
        apply_eligible=False, units_verified=False, indexed_step_methods_called=False,
        snapshot_diagnostics=[], identity_check_scope='capture_feature_child_boundaries_readonly')
    receipt = None
    created = False
    session = None
    def persist():
        report['elapsed_seconds'] = monotonic() - started
        if created:
            _write_receipt(receipt, report)
    def identity():
        pid = _member(sw, 'GetProcessID')
        if type(pid) is not int or pid != process_id:
            raise ValueError('Exact process differs')
        doc = raw_part_identity(sw)
        check_document_target(doc['path'], doc['title'], expected_path=expected_document_path, required=True)
        if (_file_hash(expected_document_path) != expected_source_sha256
                or _file_hash(inventory_receipt_path) != inventory_receipt_sha256):
            raise ValueError('Pinned source or inventory changed')
        return doc
    def check(active=True):
        report['messages'] = session.summary()
        _clean_messages(report['messages'], active)
    try:
        validate_hole_metadata_request(process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy, receipt_path=receipt_path,
            message_policy=message_policy, expected_feature_native_ids=expected_feature_native_ids,
            inventory_receipt_path=inventory_receipt_path, inventory_receipt_sha256=inventory_receipt_sha256)
        anchor = load_hole_metadata_anchor(inventory_receipt_path, inventory_receipt_sha256,
            process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, feature_ids=expected_feature_native_ids)
        receipt = Path(receipt_path)
        _write_receipt(receipt, report, create=True)
        created = True
        report.update(anchor=anchor, inventory_receipt_path=inventory_receipt_path,
            inventory_receipt_sha256=inventory_receipt_sha256, probe_scope='five_or_fewer_exact_hole_metadata_only')
        baseline = identity()
        if baseline != anchor['document'] or baseline['needs_save'] is not False:
            raise ValueError('Current clean document differs from diagnostic anchor')
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline:
            raise ValueError('Document changed acquiring CAM event host')
        session = CamMessageSession(app, typelib_path)
        with session:
            for phase in ('before', 'after'):
                check()
                report['phase'] = phase
                diagnostic = dict(phase=phase)
                report['snapshot_diagnostics'].append(diagnostic)
                persist()
                report[phase] = capture_hole_metadata(sw, app, typelib_path, process_id=process_id,
                    expected_document_path=expected_document_path, expected_source_sha256=expected_source_sha256,
                    inventory_receipt_path=inventory_receipt_path, inventory_receipt_sha256=inventory_receipt_sha256,
                    baseline=baseline, selected=anchor['selected'], check=check,
                    diagnostic=diagnostic, progress=persist)
                persist(); check()
            if report['before'] != report['after']:
                raise ValueError('Hole metadata changed between snapshots')
        check(active=False)
        if identity() != baseline:
            raise ValueError('Document changed during event cleanup')
        report.update(status='review_required', phase='finished', metadata_read_complete=True,
            readback_verified=True, state_sha256=_digest(report['before']),
            reason='RAW_HOLE_METADATA_ONLY_NOT_FULL_GEOMETRY_INVENTORY_REBIND_OR_MANUFACTURING_APPROVAL')
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], phase='finished',
            issue=_error(exc), metadata_read_complete=False, readback_verified=False)
    finally:
        if session is not None:
            report['messages'] = session.summary()
        try:
            persist()
        except Exception as exc:
            report.update(status='error', receipt_write_error=_error(exc),
                          metadata_read_complete=False, readback_verified=False)
    return report
