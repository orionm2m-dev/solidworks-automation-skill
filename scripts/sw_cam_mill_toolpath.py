"""One selected native MILL GTP on a saved disposable single-feature fixture.
No GOP/AFR/save/post/stock or tool edit. Exact snapshots surround one dispatch;
timeout/unknown completion never authorizes a retry or implies cancellation.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import re
import math
import time
import json
from scripts.sw_cam_mill_feature_context import (load_selected_mill_context,
    capture_selected_mill_context, selected_context_identity)
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_feature_process import capture_mill_feature_state, _integer
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _selected(state, feature_id, operation_id, operation_type):
    rows = state['operations']
    if not 1 <= len(rows) <= 32 or any(r['linked_feature_ids'] != [feature_id] for r in rows):
        raise ValueError('One selected feature and 1..32 solely linked operations required')
    matches = [r for r in rows if r['native_id'] == operation_id]
    if len(matches) != 1:
        raise ValueError('Exact unique selected operation native identity required')
    selected = matches[0]
    if selected['mill_operation_type'] != operation_type or selected['suppressed'] is not False:
        raise ValueError('Exact selected MILL operation type and unsuppressed state required')
    return selected


def _eligible(selected):
    counts = selected['toolpath_record_counts']
    return (selected['toolpath_generated'] is False and type(counts) is list and
        all(type(n) is int and n == 0 for n in counts))


def _record_counts(value):
    if (type(value) is not list or not 1 <= len(value) <= 32
            or any(type(n) is not int or not 0 <= n <= 100000 for n in value)
            or not 0 < sum(value) <= 100000):
        raise ValueError('Exact bounded positive-total native record counts required')
    return value


def _percent(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 150:
        raise ValueError('Strict finite tool-diameter percentage in 0..150 required')
    return value


def _regenerate_eligible(selected, counts):
    return selected['toolpath_generated'] is True and selected['toolpath_record_counts'] == counts


def _read_regeneration_percent(native, operation_id, typelib_path, check, diagnostic, persist):
    # Reuse the qualified rough-boundary feature QI; no parameter setters.
    from scripts.sw_cam_mill_rough_boundary import _dispatch_feature, _nonnull
    row = dict(native_read_complete=False)
    diagnostic['selected_rough_boundary'] = row
    row['reads'] = []
    def read(label, call, validator):
        diagnostic['stage'] = label
        attempt = dict(name=label, attempted=False, returned=False, validated=False)
        row['reads'].append(attempt)
        persist(); check()
        attempt['attempted'] = True
        persist()
        value = call()
        attempt.update(returned=True, return_type=type(value).__name__)
        if type(value) in (int, float, bool, str) or value is None:
            attempt['native_value'] = value
        persist()  # Preserve returned value even if event or validation fails.
        check()
        decoded = validator(value)
        attempt['validated'] = True
        persist()
        return decoded
    feature = read('rough.QueryInterface.IDispatch.feature',
                   lambda: _dispatch_feature(native['selected_feature']), _nonnull)
    operation = read('rough.QueryInterface.ICWRghMillOp',
                     lambda: _typed(native['operations'][operation_id], 'ICWRghMillOp', typelib_path), _nonnull)
    value = read('rough.GetToolDiameterPercent',
                 lambda: _member(operation, 'GetToolDiameterPercent', feature), _percent)
    row.update(tool_diameter_percent_native=_percent(value), native_read_complete=True)
    persist()
    return dict(native_read_complete=True, tool_diameter_percent_native=value)


def _load_regenerate_prepare(path, sha, state_sha):
    prep = Path(path) if type(path) is str else None
    if (prep is None or not prep.is_absolute() or prep.suffix.casefold() != '.json'
            or not prep.is_file() or prep.is_symlink() or prep.stat().st_size > 4*1024*1024):
        raise ValueError('Exact existing bounded prepare receipt required')
    if type(sha) is not str or re.fullmatch('[0-9a-f]{64}', sha) is None or _file_hash(prep) != sha:
        raise ValueError('Exact immutable prepare receipt SHA required')
    prepared = json.loads(prep.read_text(encoding='utf-8'))
    if (prepared.get('status') != 'ok' or prepared.get('action') != 'prepare'
            or prepared.get('phase') != 'finished' or prepared.get('generation_mode') != 'regenerate'
            or prepared.get('apply_eligible') is not True or prepared.get('mutation_attempted') is not False
            or prepared.get('state_sha256') != state_sha
            or _digest(prepared.get('prepared_state')) != state_sha
            or prepared.get('messages', {}).get('disconnected') is not True):
        raise ValueError('Complete immutable regenerate preparation required')
    marker = Path(str(prep) + '.apply_attempt.json')
    if marker.exists() or marker.is_symlink():
        raise ValueError('Prepared regeneration already consumed; no replay')
    return prep, marker, prepared


def _read_assigned_tool(native, operation_id, typelib_path, check, diagnostic):
    # Generic ICWTool only. No insert/subtype/holder/unsafe-unit or raw CL getters.
    row = dict(native_read_complete=False, units_verified=False, holder_geometry_verified=False)
    diagnostic['selected_tool'] = row
    def read(obj, name, *args):
        diagnostic['stage'] = 'selected_tool.' + name
        check(); value = _member(obj, name, *args); check(); return value
    check(); operation = _typed(native['operations'][operation_id], 'ICWOperation', typelib_path); check()
    raw_tool = read(operation, 'IGetTool')
    if raw_tool is None:
        raise ValueError('Assigned tool was not returned; no GTP')
    check(); tool = _typed(raw_tool, 'ICWTool', typelib_path); check()
    row['native_id'] = _object_id(native['doc'], tool, read)
    row['is_mill_tool'] = read(tool, 'IsMillTool')
    if row['is_mill_tool'] is not True:
        raise ValueError('Explicit native MILL tool required before dimensional reads')
    row['tool_type_raw'] = _integer(read(tool, 'ToolType'))
    for key, name in (('cut_diameter_native', 'CutDiameter'), ('protrusion_native', 'Protrusion')):
        value = read(tool, name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Finite nonnegative generic tool scalar required')
        row[key] = value
    if row['cut_diameter_native'] <= 0:
        raise ValueError('Positive native cutting diameter required')
    row['native_read_complete'] = True
    return deepcopy(row)


def _verify_gtp_delta(before, after, feature_id, operation_id, operation_type,
                      generation_mode='initial', expected_toolpath_record_counts=None):
    original = _selected(before, feature_id, operation_id, operation_type)
    selected = _selected(after, feature_id, operation_id, operation_type)
    if generation_mode == 'initial':
        if not _eligible(original):
            raise ValueError('Existing calculated records are never regenerated in initial mode')
    elif generation_mode == 'regenerate':
        _record_counts(expected_toolpath_record_counts)
        if not _regenerate_eligible(original, expected_toolpath_record_counts):
            raise ValueError('Exact prepared previously generated records required')
    else:
        raise ValueError('Unsupported generation mode')
    counts = selected['toolpath_record_counts']
    if (selected['toolpath_generated'] is not True or type(counts) is not list or
            not counts or any(type(n) is not int or n < 0 for n in counts) or sum(counts) <= 0):
        raise ValueError('Selected generation not observed with positive native records; no retry/cancel claim')
    expected = deepcopy(before)
    target = next(r for r in expected['operations'] if r['native_id'] == operation_id)
    target['toolpath_generated'] = True
    target['toolpath_record_counts'] = deepcopy(counts)
    expected['document']['needs_save'] = after['document']['needs_save']
    if expected != after:
        raise ValueError('GTP changed another operation, selected definition/tool, feature/configuration or saved file')
    return deepcopy(selected)


def qualify_mill_operation_toolpath(sw, clsid, typelib_path, *, process_id,
        expected_document_path, expected_source_sha256, expected_feature_native_id,
        expected_operation_native_id, expected_mill_operation_type,
        action, qualification_only, acknowledge_disposable_copy, message_policy='vendor_default',
        expected_state_sha256=None, receipt_path=None, generation_mode='initial',
        expected_toolpath_record_counts=None, expected_tool_diameter_percent=None,
        prepare_receipt_path=None, prepare_receipt_sha256=None,
        feature_kind='open_pocket', circle_creation_receipt_path=None, circle_creation_receipt_sha256=None):
    from scripts.sw_cam_events import CamMessageSession
    selected_context=None
    report = dict(status='error', phase='preflight', action=action, process_id=process_id,
        generation_mode=generation_mode, fresh_path_geometry_verified=False,
        fresh_CL_WIP_required=generation_mode == 'regenerate',
        may_continue=False, mutation_attempted=False, native_dispatch_pending=False,
        native_call_attempted=False, native_call_returned=False, native_hresult=None,
        readback_verified=False, selected_toolpath_verified=False, model_saved=False,
        AFR_attempted=False, GOP_attempted=False, GTP_attempted=False, simulation_attempted=False, stock_edit_attempted=False,
        units_verified=False, physical_depth_verified=False, tool_or_material_process_qualified=False,
        production_qualified=False, post_cleanup_CAM_getters=False,
        snapshot_scope='selected CAM feature/configuration/operation IDs links flags counts/document/disk; not whole RAM BRep',
        snapshot_diagnostics=[], phase_timings=[], apply_eligible=False)
    receipt = session = prep = marker = prepared = None
    created = False
    def persist():
        if created: _write_receipt(receipt, report)
    def identity():
        if selected_context is not None:
            strict_selected_document=selected_context_identity(sw,selected_context)['document']
        pid = _member(sw, 'GetProcessID')
        if type(pid) is not int or pid != process_id:
            raise ValueError('Exact SOLIDWORKS process changed')
        if generation_mode == 'regenerate':
            model = _member(sw, 'ActiveDoc')
            if model is None:
                raise ValueError('Active saved part required')
            doc = dict(path=_member(model, 'GetPathName'), title=_member(model, 'GetTitle'),
                       type=_member(model, 'GetType'), needs_save=_member(model, 'GetSaveFlag'))
            if type(doc['type']) is not int or doc['type'] != 1 or type(doc['needs_save']) is not bool:
                raise ValueError('Strict raw part type and dirty flag required')
        else:
            doc = document_snapshot(sw)
        if doc is None or doc.get('type') != 1 or type(doc.get('needs_save')) is not bool:
            raise ValueError('Active saved part with strict dirty flag required')
        check_document_target(doc.get('path'), doc.get('title'), expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError('Saved source file hash changed')
        if selected_context is not None and doc!=strict_selected_document:
            raise ValueError('Selected context document changed during identity check')
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
        state, native = capture_selected_mill_context(sw, clsid, typelib_path, expected_document_path,
            expected_feature_native_id=expected_feature_native_id, check=check, diagnostic=diagnostic,
            context=selected_context,legacy_capture=capture_mill_feature_state)
        check()
        if state['document'] != begin or identity() != begin or state['saved_file_sha256'] != expected_source_sha256:
            raise ValueError('Document/source changed during phase')
        selected = _selected(state, expected_feature_native_id, expected_operation_native_id, expected_mill_operation_type)
        state['selected_tool'] = _read_assigned_tool(native, expected_operation_native_id, typelib_path, check, diagnostic)
        if generation_mode == 'regenerate':
            def parameter_guard():
                check()
                if identity() != begin:
                    raise ValueError('Document/source changed during rough parameter read')
                check()
            state['selected_rough_boundary'] = _read_regeneration_percent(native,
                expected_operation_native_id, typelib_path, parameter_guard, diagnostic, persist)
            if state['selected_rough_boundary']['tool_diameter_percent_native'] != expected_tool_diameter_percent:
                raise ValueError('Expected rough tool-diameter percentage is stale')
        check()
        if identity() != begin:
            raise ValueError('Document/source changed during selected tool read')
        check(); timing.update(completed=True, elapsed_seconds=time.monotonic()-start)
        persist(); return state, native
    try:
        selected_context=load_selected_mill_context(process_id=process_id,
            expected_document_path=expected_document_path,expected_feature_native_id=expected_feature_native_id,
            expected_source_sha256=expected_source_sha256,feature_kind=feature_kind,
            circle_creation_receipt_path=circle_creation_receipt_path,
            circle_creation_receipt_sha256=circle_creation_receipt_sha256)
        _integer(process_id, positive=True); _integer(expected_feature_native_id, positive=True)
        _integer(expected_operation_native_id, positive=True)
        if type(expected_mill_operation_type) is not int or not 0 <= expected_mill_operation_type <= 2147483647:
            raise ValueError('Strict nonnegative expected MILL operation type required')
        if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or
                Path(expected_document_path).suffix.casefold() != '.sldprt'):
            raise ValueError('Exact absolute saved qualification part required')
        if type(expected_source_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_source_sha256) is None:
            raise ValueError('Exact saved source SHA required, including inspect')
        if qualification_only is not True or acknowledge_disposable_copy is not True or message_policy != 'vendor_default':
            raise ValueError('Explicit disposable qualification with vendor_default required')
        if action not in ('inspect','prepare','apply'):
            raise ValueError('Unsupported action')
        if generation_mode not in ('initial', 'regenerate'):
            raise ValueError('Unsupported generation mode')
        if generation_mode == 'initial':
            if any(value is not None for value in (expected_toolpath_record_counts,
                    expected_tool_diameter_percent, prepare_receipt_path, prepare_receipt_sha256)):
                raise ValueError('Initial mode rejects regeneration credentials')
        else:
            _record_counts(expected_toolpath_record_counts)
            _percent(expected_tool_diameter_percent)
            if expected_mill_operation_type != 0:
                raise ValueError('Regeneration is bounded to exact ROUGH MILL type 0')
            if action == 'apply':
                prep, marker, prepared = _load_regenerate_prepare(
                    prepare_receipt_path, prepare_receipt_sha256, expected_state_sha256)
            elif any(value is not None for value in
                     (expected_state_sha256, prepare_receipt_path, prepare_receipt_sha256)):
                raise ValueError('Inspect/prepare rejects apply credentials')
        if action == 'apply':
            if type(expected_state_sha256) is not str or re.fullmatch('[0-9a-f]{64}',expected_state_sha256) is None:
                raise ValueError('Exact fresh prepare SHA required')
            receipt = Path(receipt_path) if type(receipt_path) is str else None
            if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != '.json' or
                    not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink()):
                raise ValueError('Unique absolute JSON receipt required')
            _write_receipt(receipt,report,create=True); created=True
        elif generation_mode == 'regenerate' and action == 'prepare':
            receipt = Path(receipt_path) if type(receipt_path) is str else None
            if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != '.json'
                    or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink()):
                raise ValueError('New absolute JSON prepare receipt required')
            _write_receipt(receipt, report, create=True); created=True
        elif expected_state_sha256 is not None or receipt_path is not None:
            raise ValueError('Read-only inspect or initial prepare rejects receipt/hash')
        baseline_document = identity()
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline_document:
            raise ValueError('Document changed acquiring event host')
        session = CamMessageSession(app,typelib_path)
        with session:
            before, native = capture('initial_capture')
            state_key = dict(snapshot=before, process_id=process_id, expected_feature_native_id=expected_feature_native_id,
                expected_operation_native_id=expected_operation_native_id, expected_mill_operation_type=expected_mill_operation_type,
                scope='MILL_SELECTED_OPERATION_GTP')
            if generation_mode == 'regenerate':
                state_key.update(scope='MILL_SELECTED_ROUGH_OPERATION_REGENERATE',
                    generation_mode=generation_mode,
                    expected_toolpath_record_counts=deepcopy(expected_toolpath_record_counts),
                    expected_tool_diameter_percent=expected_tool_diameter_percent)
                report['prepared_state'] = deepcopy(state_key)
            selected_before = _selected(before, expected_feature_native_id,
                expected_operation_native_id, expected_mill_operation_type)
            eligible = (_eligible(selected_before) if generation_mode == 'initial'
                else _regenerate_eligible(selected_before, expected_toolpath_record_counts))
            report.update(before=before,state_sha256=_digest(state_key),
                apply_eligible=before['document']['needs_save'] is False and
                    eligible)
            persist()
            if action != 'inspect' and not report['apply_eligible']:
                raise ValueError('Prepare/apply requires clean saved state and mode-specific exact record eligibility')
            if action == 'apply':
                if report['state_sha256'] != expected_state_sha256:
                    raise ValueError('Prepared scope/process/source/feature state changed')
                if generation_mode == 'regenerate' and prepared['prepared_state'] != state_key:
                    raise ValueError('Prepared regeneration request differs')
                current, native = capture('before_mutation_capture')
                if current != before:
                    raise ValueError('State changed immediately before selected GTP')
                selected_native = _typed(native['operations'][expected_operation_native_id], 'ICWMillOperation', typelib_path)
                if generation_mode == 'regenerate':
                    if _file_hash(prep) != prepare_receipt_sha256:
                        raise ValueError('Prepare receipt changed before dispatch')
                    _write_receipt(marker, dict(status='consumed', process_id=process_id,
                        state_sha256=expected_state_sha256, apply_receipt_path=str(receipt),
                        automatic_replay_allowed=False), create=True)
                    report['regeneration_prepare_consumed'] = True
                report.update(phase='GenerateToolpath', native_dispatch_pending=True)
                persist(); check()
                if identity() != before['document']:
                    raise ValueError('Document changed before dispatch')
                check(); started = time.monotonic()
                report.update(mutation_attempted=True,native_call_attempted=True,GTP_attempted=True)
                if generation_mode == 'regenerate':
                    persist()  # Durable one-attempt intent before the native call.
                result = _member(selected_native, 'GenerateToolpath')
                report.update(native_call_returned=True,native_dispatch_pending=False,phase='GTP_returned',
                    native_return_type=type(result).__name__,native_hresult=result if type(result) is int else None,
                    native_call_seconds=time.monotonic()-started)
                persist(); check()
                if type(result) is not int or result != 0:
                    raise ValueError('Unexpected HRESULT/no-OUT MILL GTP binding result')
                after, _ = capture('after_mutation_capture')
                report['after'] = after; persist()
                verify_args = (before, after, expected_feature_native_id,
                               expected_operation_native_id, expected_mill_operation_type)
                if generation_mode == 'regenerate':
                    report['selected_result'] = _verify_gtp_delta(*verify_args,
                        generation_mode=generation_mode,
                        expected_toolpath_record_counts=expected_toolpath_record_counts)
                else:
                    report['selected_result'] = _verify_gtp_delta(*verify_args)
                final = after
            else:
                final = before
                if generation_mode == 'regenerate' and action == 'prepare':
                    current, _ = capture('prepare_readback')
                    if current != before:
                        raise ValueError('Regeneration state changed during preparation')
                    report['after'] = current
                    final = current
            check()
        report['phase'] = 'after_cleanup'; check(active=False)
        final_document = identity()
        report['after_cleanup_SW_file'] = dict(document=final_document,saved_file_sha256=expected_source_sha256)
        if final_document != final['document']:
            raise ValueError('Document changed during event cleanup')
        check(active=False)
        report.update(status='review_required' if action=='apply' else 'ok',phase='finished',
            readback_verified=action=='apply',selected_toolpath_verified=action=='apply',
            reason='SELECTED_GENERATED_FLAG_AND_RECORD_COUNTS_ONLY_PATH_GEOMETRY_DEPTH_UNITS_AND_PROCESS_UNQUALIFIED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,selected_toolpath_verified=False,apply_eligible=False)
    finally:
        if session is not None:report['messages']=session.summary()
        if created:
            try:persist()
            except Exception as exc:report.update(status='uncertain',receipt_write_error=_error(exc),readback_verified=False,selected_toolpath_verified=False)
    return report
