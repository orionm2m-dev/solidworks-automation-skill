"""Bounded single-feature MILL GOP and shared read-only lifecycle snapshot.
No GTP, AFR, tool edits, save, simulation or stock writes. Does not verify the
whole RAM BRep, physical feature depth, manufacturing tools or numerical units.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import re
import time

from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap, _snapshot as _mill_snapshot
from scripts.sw_cam_mill_units_qualification import _feature
from scripts.sw_cam_turn_feature_attribute import _items
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path, check_document_target

MAX_OPERATIONS = 32


def _integer(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 0xFFFFFFFF:
        raise ValueError('Bounded strict native integer required')
    return value


def capture_mill_feature_state(sw, clsid, typelib_path, expected_path, *,
        expected_feature_native_id, check, diagnostic=None):
    """Caller owns the active event session. Never calls tool/unsafe CL getters."""
    diagnostic = {} if diagnostic is None else diagnostic
    _integer(expected_feature_native_id, positive=True)
    def read(obj, name, *args):
        diagnostic['stage'] = name
        check(); value = _member(obj, name, *args); check(); return value
    check()
    state, native = _mill_snapshot(sw, clsid, typelib_path, expected_path,
        check=check, diagnostic=diagnostic, required_machine_type=1)
    diagnostic['capture_complete'] = False
    diagnostic['state'] = state
    if (len(state['feature_setups']) != 1 or state['feature_setups'][0]['feature_count'] != 1 or
            len(state['operation_counts']) > 1 or sum(state['operation_counts']) > MAX_OPERATIONS):
        raise ValueError('Exactly one MILL feature/setup and at most32 operations required')
    setup = _typed(native['setups'][0], 'ICWBaseSetup', typelib_path)
    features = _items(read(setup, 'IGetEnumFeatures'), typelib_path, read, limit=1)
    if len(features) != 1:
        raise ValueError('Selected setup feature count changed')
    feature = _typed(features[0], 'ICWFeature', typelib_path)
    if _object_id(native['doc'], feature, read) != expected_feature_native_id:
        raise ValueError('Exact selected feature identity changed before detailed reads')
    state['selected_feature'] = _feature(feature, native['doc'], typelib_path, read)
    if state['selected_feature']['native_id'] != expected_feature_native_id:
        raise ValueError('Selected feature identity changed during readback')
    op_setups = _items(read(native['machine'], 'IGetEnumOpSetups'), typelib_path, read, limit=1)
    state.update(operation_setup_count=len(op_setups), operations=[])
    raw_operations = {}
    observed_counts = []
    for si, raw in enumerate(op_setups):
        op_setup = _typed(raw, 'ICWBaseOpSetup', typelib_path)
        values = _items(read(op_setup, 'IGetEnumOperations'), typelib_path, read, limit=MAX_OPERATIONS)
        observed_counts.append(len(values))
        for oi, raw_op in enumerate(values):
            operation = _typed(raw_op, 'ICWOperation', typelib_path)
            mill_operation = _typed(raw_op, 'ICWMillOperation', typelib_path)
            native_id = _object_id(native['doc'], operation, read)
            if native_id in raw_operations:
                raise ValueError('Duplicate operation native identity')
            row = dict(setup_index=si, operation_index=oi, native_id=native_id)
            state['operations'].append(row)
            row['mill_operation_type'] = _integer(read(mill_operation, 'OpernType'))
            row['base_operation_type'] = _integer(read(operation, 'OpernType'))
            row['suppressed'] = read(operation, 'Suppressed')
            row['toolpath_generated'] = read(operation, 'GetIsToolpathGenerated')
            if type(row['suppressed']) is not bool or type(row['toolpath_generated']) is not bool:
                raise ValueError('Strict native operation flags required')
            row['linked_feature_ids'] = [_object_id(native['doc'], item, read) for item in
                _items(read(operation, 'IGetAllFeatures'), typelib_path, read, limit=MAX_OPERATIONS)]
            if len(set(row['linked_feature_ids'])) != len(row['linked_feature_ids']):
                raise ValueError('Duplicate linked feature identity')
            row['toolpath_record_counts'] = []
            # Read bounded path containers even when the generated flag is false;
            # never substitute an invented empty list for native record-count evidence.
            for item in _items(read(operation, 'IGetEnumToolpaths'), typelib_path, read, limit=32):
                path = _typed(item, 'ICWToolpath', typelib_path)
                row['toolpath_record_counts'].append(_integer(read(path, 'RecordCount')))
            raw_operations[native_id] = raw_op
    if observed_counts != state['operation_counts']:
        raise ValueError('Operation inventory changed during capture')
    check()
    if document_snapshot(sw) != state['document'] or _file_hash(expected_path) != state['saved_file_sha256']:
        raise ValueError('Document or saved file changed during MILL feature capture')
    check()
    native.update(selected_feature=feature, operations=raw_operations)
    diagnostic.update(capture_complete=True, stage='complete')
    return state, native


def _verify_gop_delta(before, after, feature_id):
    if before['operations'] or any(before['operation_counts']):
        raise ValueError('GOP baseline must have exactly zero operations')
    added = after['operations']
    if not 1 <= len(added) <= MAX_OPERATIONS or after['operation_setup_count'] != 1 or after['operation_counts'] != [len(added)]:
        raise ValueError('Expected1..32 operations in one operation setup; do not replay GOP')
    ids = [row['native_id'] for row in added]
    if any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('New operation identities must be unique and positive')
    for index, row in enumerate(added):
        if (row['setup_index'] != 0 or row['operation_index'] != index or
                row['linked_feature_ids'] != [feature_id] or row['suppressed'] is not False or
                row['toolpath_generated'] is not False or any(row['toolpath_record_counts'])):
            raise ValueError('Every new unsuppressed operation must link only to exact feature and have no path')
    expected = deepcopy(before)
    expected.update(operations=deepcopy(added), operation_setup_count=1, operation_counts=[len(added)])
    expected['document']['needs_save'] = after['document']['needs_save']
    if expected != after:
        raise ValueError('GOP changed captured feature/configuration/file state')
    return deepcopy(added)


def qualify_mill_feature_operation_plan(sw, clsid, typelib_path, *, process_id,
        expected_document_path, expected_source_sha256, expected_feature_native_id,
        action, qualification_only, acknowledge_disposable_copy, message_policy='vendor_default',
        expected_state_sha256=None, receipt_path=None):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(status='error', phase='preflight', action=action, process_id=process_id,
        may_continue=False, mutation_attempted=False, native_dispatch_pending=False,
        native_call_attempted=False, native_call_returned=False, native_hresult=None,
        readback_verified=False, insertion_delta_verified=False, model_saved=False,
        AFR_attempted=False, GTP_attempted=False, simulation_attempted=False, stock_edit_attempted=False,
        units_verified=False, physical_depth_verified=False, tool_or_material_process_qualified=False,
        production_qualified=False, post_cleanup_CAM_getters=False, gop_preference=1,
        snapshot_scope='selected CAM feature/configuration/operation IDs links flags counts/document/disk; not whole RAM BRep',
        snapshot_diagnostics=[], phase_timings=[], apply_eligible=False)
    receipt = session = None
    created = False
    def persist():
        if created: _write_receipt(receipt, report)
    def identity():
        pid = _member(sw, 'GetProcessID')
        if type(pid) is not int or pid != process_id:
            raise ValueError('Exact SOLIDWORKS process changed')
        doc = document_snapshot(sw)
        if doc is None or doc.get('type') != 1 or type(doc.get('needs_save')) is not bool:
            raise ValueError('Active saved part with strict dirty flag required')
        check_document_target(doc.get('path'), doc.get('title'), expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError('Saved source file hash changed')
        return doc
    def check(*, active=True):
        summary = session.summary(); report['messages'] = summary
        if (summary.get('subscribed') is not True or (active and summary.get('active') is not True) or
                (not active and (summary.get('active') is not False or summary.get('disconnected') is not True)) or
                any(summary.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors'))):
            raise ValueError('CAM event/transport requires stop; no retry')
    def capture(phase):
        report['phase'] = phase
        timing = dict(phase=phase, started_unix=time.time(), completed=False)
        report['phase_timings'].append(timing); persist()
        start = time.monotonic(); check(); begin = identity(); check()
        diagnostic = dict(phase=phase); report['snapshot_diagnostics'].append(diagnostic)
        state, native = capture_mill_feature_state(sw, clsid, typelib_path, expected_document_path,
            expected_feature_native_id=expected_feature_native_id, check=check, diagnostic=diagnostic)
        check()
        if state['document'] != begin or identity() != begin or state['saved_file_sha256'] != expected_source_sha256:
            raise ValueError('Document/source changed during phase')
        check(); timing.update(completed=True, elapsed_seconds=time.monotonic()-start)
        persist(); return state, native
    try:
        _integer(process_id, positive=True); _integer(expected_feature_native_id, positive=True)
        if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or
                Path(expected_document_path).suffix.casefold() != '.sldprt'):
            raise ValueError('Exact absolute saved qualification part required')
        if type(expected_source_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_source_sha256) is None:
            raise ValueError('Exact saved source SHA required, including inspect')
        if qualification_only is not True or acknowledge_disposable_copy is not True or message_policy != 'vendor_default':
            raise ValueError('Explicit disposable qualification with vendor_default required')
        if action not in ('inspect','prepare','apply'):
            raise ValueError('Unsupported action')
        if action == 'apply':
            if type(expected_state_sha256) is not str or re.fullmatch('[0-9a-f]{64}',expected_state_sha256) is None:
                raise ValueError('Exact fresh prepare SHA required')
            receipt = Path(receipt_path) if type(receipt_path) is str else None
            if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != '.json' or
                    not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink()):
                raise ValueError('Unique absolute JSON receipt required')
            _write_receipt(receipt,report,create=True); created=True
        elif expected_state_sha256 is not None or receipt_path is not None:
            raise ValueError('Read-only actions reject mutation receipt/hash')
        baseline_document = identity()
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline_document:
            raise ValueError('Document changed acquiring event host')
        session = CamMessageSession(app,typelib_path)
        with session:
            before, native = capture('initial_capture')
            state_key = dict(snapshot=before, process_id=process_id, expected_feature_native_id=expected_feature_native_id,
                scope='MILL_SINGLE_FEATURE_GOP_RETAIN1')
            report.update(before=before,state_sha256=_digest(state_key),
                apply_eligible=before['document']['needs_save'] is False and not before['operations'] and not any(before['operation_counts']))
            persist()
            if action != 'inspect' and not report['apply_eligible']:
                raise ValueError('Prepare/apply requires clean saved MILL feature with zero operations; never replay')
            if action == 'apply':
                if report['state_sha256'] != expected_state_sha256:
                    raise ValueError('Prepared scope/process/source/feature state changed')
                current, native = capture('before_mutation_capture')
                if current != before:
                    raise ValueError('State changed immediately before GOP')
                report.update(phase='GenerateOpPlan', native_dispatch_pending=True)
                persist(); check()
                if identity() != before['document']:
                    raise ValueError('Document changed before dispatch')
                check(); started = time.monotonic()
                report.update(mutation_attempted=True,native_call_attempted=True)
                result = _member(native['selected_feature'], 'GenerateOpPlan', 1)
                report.update(native_call_returned=True,native_dispatch_pending=False,phase='GOP_returned',
                    native_return_type=type(result).__name__,native_hresult=result if type(result) is int else None,
                    native_call_seconds=time.monotonic()-started)
                persist(); check()
                if type(result) is not int or result != 0:
                    raise ValueError('Unexpected HRESULT/no-OUT GOP binding result')
                after, _ = capture('after_mutation_capture')
                report['after'] = after; persist()
                report['new_operations'] = _verify_gop_delta(before,after,expected_feature_native_id)
                final = after
            else:
                final = before
            check()
        report['phase'] = 'after_cleanup'; check(active=False)
        final_document = identity()
        report['after_cleanup_SW_file'] = dict(document=final_document,saved_file_sha256=expected_source_sha256)
        if final_document != final['document']:
            raise ValueError('Document changed during event cleanup')
        check(active=False)
        report.update(status='review_required' if action=='apply' else 'ok',phase='finished',
            readback_verified=action=='apply',insertion_delta_verified=action=='apply',
            reason='OPERATION_DEFINITIONS_ONLY_TOOL_STOCK_MATERIAL_GTP_DEPTH_AND_PERSISTENCE_UNQUALIFIED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,insertion_delta_verified=False,apply_eligible=False)
    finally:
        if session is not None:report['messages']=session.summary()
        if created:
            try:persist()
            except Exception as exc:report.update(status='uncertain',receipt_write_error=_error(exc),readback_verified=False,insertion_delta_verified=False)
    return report
