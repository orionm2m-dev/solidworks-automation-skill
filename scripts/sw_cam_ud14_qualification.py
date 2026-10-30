"""Bounded native UD specimen qualification in one clean, isolated saved MILL part.

Creates one local UD tool and references one pinned existing MT. No operation
assignment, GTP, TechDB/library write, document save, rollback or replay.
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import math
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity, call
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request, _items
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles, _check_capture_document
from scripts.sw_operation_guard import check_document_target
from scripts.sw_cam_ud14_specimen import read_mt_specimen
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_ud14_probe_core import run_single_probe

MAX_READS = 12000


def ud14_attempt_marker(document_path, source_sha, mt_sha):
    """A source-local immutable attempt key; receipt renaming cannot authorize replay."""
    source = Path(document_path).resolve()
    key = _digest(dict(scope='isolated_ud14_specimen', action='create_and_load',
        document=str(source).casefold(), source_sha256=source_sha, mt_sha256=mt_sha))
    return source.parent / ('ud14_attempt_' + key + '.json')


def claim_ud14_attempt(marker, report, receipt_path):
    """Exclusive durable dispatch claim using the existing project receipt publisher."""
    pending = dict(scope='isolated_ud14_specimen', status='dispatch_pending',
        receipt_path=str(receipt_path), automatic_replay=False,
        document=report['expected_document_path'], source_sha256=report['expected_source_sha256'],
        mt_sha256=report['specimen']['sha256'], creation_pending=True,
        load_pending=False, new_tool_native_id=None)
    _write_receipt(marker, pending, create=True)


def validate_ud14_request(*, process_id, expected_document_path, expected_source_sha256,
                         mt_specimen_path, mt_specimen_sha256, expected_sw_document_units_raw,
                         expected_cam_use_document_units, qualification_only,
                         acknowledge_disposable_copy, receipt_path, message_policy='vendor_default'):
    validate_inventory_request(process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256, qualification_only=qualification_only,
        acknowledge_disposable_copy=acknowledge_disposable_copy, receipt_path=receipt_path,
        message_policy=message_policy)
    units = expected_sw_document_units_raw
    if (type(units) is not list or len(units) != 5 or any(type(x) is not int for x in units)
            or units[0] != 0 or expected_cam_use_document_units is not True):
        raise ValueError('Explicit five-value millimetre SW unit scope and CAM GetUseDocumentUnit=true required')
    specimen = read_mt_specimen(mt_specimen_path, mt_specimen_sha256)
    if len({Path(x).resolve() for x in (expected_document_path, mt_specimen_path, receipt_path)}) != 3:
        raise ValueError('Source, MT and receipt must be distinct files')
    marker = ud14_attempt_marker(expected_document_path, expected_source_sha256, mt_specimen_sha256)
    if marker.exists() or marker.is_symlink():
        raise ValueError('Prior UD dispatch marker exists; inspect the outcome, never replay with a new receipt')
    if marker.resolve() == Path(receipt_path).resolve():
        raise ValueError('Independent dispatch marker and report must be separate')
    return specimen


def _integer(value, label, minimum=0, maximum=0xFFFFFFFF):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Strict bounded integer required: ' + label)
    return value


def _scalar(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite native scalar required: ' + label)
    return value


def read_ud14_tool(raw, *, doc, read, typed, diagnostic):
    """Raw UD parameters and complete native tool/shank profiles; no interpretation."""
    tool = typed(raw, 'ICWTool')
    ud = typed(raw, 'ICWMillUDTool')
    row = dict(native_id=_object_id(doc, tool, read), parameters={}, profiles={},
               units_verified=False, cutting_partition_verified=False)
    diagnostic['state'] = row
    row['tool_type_raw'] = _integer(read(tool, 'ToolType'), 'ToolType')
    if row['tool_type_raw'] != 14 or read(tool, 'IsMillTool') is not True:
        raise ValueError('Exact native MILL UD14 required')
    name = read(ud, 'GetToolName')
    if type(name) is not str or not name or len(name) > 4096:
        raise ValueError('Bounded existing MT path readback required')
    row['mt_path_raw'] = name
    for owner, fields in ((tool, ('CutDiameter', 'Protrusion')),
                         (ud, ('ShankDia', 'CutLength', 'OverallLength', 'TipOffset', 'TipLength'))):
        for field in fields:
            diagnostic['stage'] = field
            row['parameters'][field] = _scalar(read(owner, field), field)
    for field in ('Flutes', 'MillUDToolOutputType'):
        row['parameters'][field] = _integer(read(ud, field), field, 0, 1024)
    # ShoulderLength is deliberately omitted: product help says UD does not support it.
    budget = dict(curves=0, chains=0, islands=0)
    for label, method in (('tool', 'GetToolProfile'), ('shank', 'GetShankProfile')):
        partial = {}; row['profiles'][label] = partial
        diagnostic['stage'] = method
        read_segment_chains(tool, method, read=read, typed=typed,
                            diagnostic={'state': partial}, budget=budget)
    row['profile_complete'] = all(x['status'] == 'observed' for x in row['profiles'].values())
    diagnostic.update(stage='complete', capture_complete=True)
    return deepcopy(row)


def capture_protected_context(machine, doc, read, typed):
    """Observe setup/feature IDs and operation links/tools/counts, not CAD geometry."""
    def oid(raw):
        return _object_id(doc, raw, read)
    def collection(owner, name, limit):
        return _items(read(owner, name), typed, read, limit)
    state = dict(feature_setups=[], operation_setups=[], scope='IDs_links_flags_tools_path_counts')
    for raw in collection(machine, 'IGetEnumSetups', 8):
        setup = typed(raw, 'ICWBaseSetup')
        features = collection(setup, 'IGetEnumFeatures', 64)
        state['feature_setups'].append(dict(native_id=oid(setup), feature_ids=[oid(x) for x in features]))
    count = 0
    for raw in collection(machine, 'IGetEnumOpSetups', 8):
        setup = typed(raw, 'ICWBaseOpSetup')
        rows = []; state['operation_setups'].append(dict(native_id=oid(setup), operations=rows))
        for raw_op in collection(setup, 'IGetEnumOperations', 32):
            count += 1
            if count > 32:
                raise ValueError('At most 32 protected operations')
            op = typed(raw_op, 'ICWOperation'); mill = typed(raw_op, 'ICWMillOperation')
            tool = typed(read(op, 'IGetTool'), 'ICWTool')
            row = dict(native_id=oid(op), mill_type=_integer(read(mill, 'OpernType'), 'operation type'),
                tool_native_id=oid(tool), feature_ids=[oid(x) for x in collection(op, 'IGetAllFeatures', 64)],
                suppressed=read(op, 'Suppressed'), generated=read(op, 'GetIsToolpathGenerated'), path_records=[])
            if type(row['suppressed']) is not bool or type(row['generated']) is not bool:
                raise ValueError('Strict operation flags required')
            for path in collection(op, 'IGetEnumToolpaths', 32):
                row['path_records'].append(_integer(read(typed(path, 'ICWToolpath'), 'RecordCount'),
                                                    'RecordCount', 0, 100000))
            rows.append(row)
    return state


def capture_local_tools(crib, doc, read, typed):
    rows = []
    for raw in _items(read(crib, 'GetAllTools'), typed, read, 128):
        tool = typed(raw, 'ICWTool')
        row = dict(native_id=_object_id(doc, tool, read),
                   tool_type_raw=_integer(read(tool, 'ToolType'), 'ToolType'))
        for name in ('CutDiameter', 'Protrusion', 'StnNo'):
            row[name] = _scalar(read(tool, name), name)
        rows.append(row)
    if len({x['native_id'] for x in rows}) != len(rows):
        raise ValueError('Duplicate local tool IDs')
    return rows


def qualify_ud14_specimen(sw, clsid, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, mt_specimen_path, mt_specimen_sha256,
        expected_sw_document_units_raw, expected_cam_use_document_units, qualification_only,
        acknowledge_disposable_copy, receipt_path, message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(schema_version=1, scope='isolated_ud14_specimen', status='error', phase='preflight',
        process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256, mutation_attempted=False,
        creation_attempted=False, creation_pending=False, creation_returned=False,
        load_attempted=False, load_pending=False, load_returned=False, new_tool_native_id=None,
        operation_assignment_attempted=False, GTP_attempted=False, GOP_attempted=False,
        TechDB_write_attempted=False, model_saved=False, automatic_replay=False, automatic_rollback=False,
        post_cleanup_CAM_getters=False, raw_readback_stable=False, exact_one_tool_created=False,
        protected_context_unchanged=False, full_profiles_complete=False, units_verified=False, cutting_partition_verified=False,
        physical_tool_qualified=False, production_qualified=False, may_continue=False,
        native_read_count=0, tool_reads=[], tool_read_diagnostics=[])
    created = False; session = None; files = None; baseline = None; receipt = None
    marker = None; marker_created = False
    started = monotonic()
    def persist():
        nonlocal marker_created
        report['elapsed_seconds'] = monotonic() - started
        if created:
            if report['creation_pending'] and not marker_created:
                claim_ud14_attempt(marker, report, receipt)
                marker_created = True
            if marker_created:
                _write_receipt(marker, dict(scope='isolated_ud14_specimen',
                    status=('dispatch_pending' if report['creation_pending'] or report['load_pending'] else report['status']),
                    phase=report['phase'], receipt_path=str(receipt),
                    automatic_replay=False, document=expected_document_path,
                    source_sha256=expected_source_sha256, mt_sha256=mt_specimen_sha256,
                    creation_pending=report['creation_pending'], load_pending=report['load_pending'],
                    creation_returned=report['creation_returned'], load_returned=report['load_returned'],
                    new_tool_native_id=report['new_tool_native_id']))
            _write_receipt(receipt, report)
    def identity():
        actual_pid = _member(sw, 'GetProcessID')
        if type(actual_pid) is not int or actual_pid != process_id:
            raise ValueError('Exact process changed')
        actual = raw_part_identity(sw)
        check_document_target(actual['path'], actual['title'], expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError('Saved source changed')
        if _file_hash(mt_specimen_path) != mt_specimen_sha256:
            raise ValueError('Pinned MT changed')
        if baseline is not None:
            expected = dict(baseline, needs_save=actual['needs_save'])
            if actual != expected:
                raise ValueError('Active document identity changed')
        return actual
    def events(active=True):
        value = session.summary(); report['messages'] = value
        if (value.get('subscribed') is not True or value.get('active') is not active
                or (not active and value.get('disconnected') is not True)
                or any(value.get(x) for x in ('event_count','overflow','callback_errors',
                    'callback_error_count','subscription_error','disconnect_errors'))):
            raise ValueError('CAM event/transport requires stop')
    def guard():
        events(); files.check()
        _check_capture_document(sw, {'process_id': process_id}, {'document': baseline})
        events()
    def read(obj, name, *args):
        guard()
        if report['native_read_count'] >= MAX_READS:
            raise ValueError('Bounded native read budget exceeded')
        report['native_read_count'] += 1
        value = _member(obj, name, *args)
        guard()
        return value
    def typed(raw, name):
        guard()
        if report['native_read_count'] >= MAX_READS:
            raise ValueError('Bounded native interface budget exceeded')
        report['native_read_count'] += 1
        value = _typed(raw, name, typelib_path)
        guard()
        return value
    def metric_scope(app):
        def sw_read(obj, name):
            guard(); value = call(obj, name); guard(); return value
        row = read_document_cam_unit_scope(sw.ActiveDoc, app, sw_read=sw_read, cam_read=read)
        if (row['SW_document_units_raw'] != expected_sw_document_units_raw
                or row['CAM_use_document_units_raw'] is not True):
            raise ValueError('Explicit metric document/CAM scope differs')
        return row
    try:
        args = dict(process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, mt_specimen_path=mt_specimen_path,
            mt_specimen_sha256=mt_specimen_sha256, expected_sw_document_units_raw=expected_sw_document_units_raw,
            expected_cam_use_document_units=expected_cam_use_document_units, qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy, receipt_path=receipt_path,
            message_policy=message_policy)
        report['specimen'] = validate_ud14_request(**args)
        marker = ud14_attempt_marker(expected_document_path, expected_source_sha256, mt_specimen_sha256)
        report['dispatch_marker_path'] = str(marker)
        receipt = Path(receipt_path); _write_receipt(receipt, report, create=True); created = True
        baseline = identity()
        if baseline['needs_save'] is not False:
            raise ValueError('Clean saved isolated qualification part required')
        report['before_document'] = baseline; persist()
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline:
            raise ValueError('Identity changed acquiring CAM event host')
        session = CamMessageSession(app, typelib_path)
        with ExitStack() as stack:
            files = stack.enter_context(_CaptureReadFiles(expected_document_path, mt_specimen_path))
            stack.enter_context(session)
            events(); report['metric_scope'] = metric_scope(app)
            active = read(app, 'IGetActiveDoc')
            doc = typed(active, 'ICWDoc3')
            if _integer(read(doc, 'GetDocType'), 'CAM document type') != 1:
                raise ValueError('CAM part required')
            part = typed(active, 'ICWPartDoc')
            machine = typed(read(part, 'IGetMachine'), 'ICWMachine')
            if _integer(read(machine, 'MachType'), 'CAM machine type') != 1:
                raise ValueError('Exact MILL machine required before creating any tool')
            crib = typed(read(machine, 'IGetToolcrib'), 'ICWToolcrib4')
            def boundary():
                guard(); identity(); metric_scope(app); guard()
            def create():
                # CWDBToolType_e value19, NOT the observed CWToolType_e value14.
                return _member(crib, 'AddNewTool3', 19)
            def load(raw, path):
                ud = typed(raw, 'ICWMillUDTool')
                _member(ud, 'SetToolName', path)
                guard()
            def observe(raw, diagnostic):
                row = read_ud14_tool(raw, doc=doc, read=read, typed=typed, diagnostic=diagnostic)
                check_document_target(row['mt_path_raw'], None, expected_path=mt_specimen_path, required=True)
                return row
            run_single_probe(report=report, guard=boundary, persist=persist, create=create, load=load,
                identify=lambda raw: _object_id(doc, raw, read), read_tool=observe,
                context=lambda: capture_protected_context(machine, doc, read, typed),
                tools=lambda: capture_local_tools(crib, doc, read, typed), specimen_path=mt_specimen_path)
            report['after_metric_scope'] = metric_scope(app)
            if report['after_metric_scope'] != report['metric_scope']:
                raise ValueError('Metric scope changed')
            report['after_document'] = identity(); persist()
        events(active=False)  # No CAM getters after disconnect.
        report['after_cleanup_document'] = identity()
        report.update(status='review_required', phase='finished',
            reason=('RAW_UD_SPECIMEN_OBSERVED_UNITS_AND_CUTTING_PARTITION_UNQUALIFIED'
                    if report['full_profiles_complete'] else
                    'RAW_UD_OBSERVED_PROFILE_UNAVAILABLE_UNITS_AND_CUTTING_PARTITION_UNQUALIFIED'))
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'], phase='finished', issue=_error(exc), raw_readback_stable=False)
    finally:
        if session is not None:
            report['messages'] = session.summary()
        try:
            persist()
        except Exception as exc:
            report.update(status='uncertain' if report['mutation_attempted'] else 'error',
                          receipt_write_error=_error(exc), raw_readback_stable=False)
    return report