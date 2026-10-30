"""Preserve one already observed local UD tool with one native CAM document save.

No creator, MT loader, assignment, generation, close or reopen is present.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity, call
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request, _items
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles, _check_capture_document
from scripts.sw_operation_guard import check_document_target
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_ud14_qualification import (
    read_ud14_tool, capture_protected_context, capture_local_tools, ud14_attempt_marker)
from scripts.sw_cam_ud14_probe_core import verify_one_new_tool

SCOPE = 'isolated_ud14_save_existing'
MAX_READS = 6000


def _pinned_json(path, sha):
    p = Path(path)
    if (not p.is_absolute() or p.suffix.casefold() != '.json' or not p.is_file()
            or p.is_symlink() or type(sha) is not str or re.fullmatch('[0-9a-f]{64}', sha) is None
            or p.stat().st_size > 2 * 1024 * 1024):
        raise ValueError('Pinned bounded regular JSON evidence required')
    if _file_hash(p) != sha:
        raise ValueError('Pinned evidence changed')
    value = json.loads(p.read_text(encoding='utf-8'))
    if type(value) is not dict:
        raise ValueError('Object evidence required')
    return value


def ud14_save_marker(document_path, probe_sha, tool_id):
    source = Path(document_path).resolve()
    key = _digest(dict(scope=SCOPE, action='save_existing',
        document=str(source).casefold(), probe_sha256=probe_sha, tool_native_id=tool_id))
    return source.parent / ('ud14_save_' + key + '.json')


def validate_ud14_save_request(*, process_id, expected_document_path, expected_source_sha256,
        expected_tool_native_id, probe_receipt_path, probe_receipt_sha256, qualification_only,
        acknowledge_disposable_copy, receipt_path, message_policy='vendor_default'):
    validate_inventory_request(process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256, qualification_only=qualification_only,
        acknowledge_disposable_copy=acknowledge_disposable_copy, receipt_path=receipt_path,
        message_policy=message_policy)
    if type(expected_tool_native_id) is not int or not 0 < expected_tool_native_id < 2**32:
        raise ValueError('Exact positive existing tool ID required')
    evidence = _pinned_json(probe_receipt_path, probe_receipt_sha256)
    if (evidence.get('scope') != 'isolated_ud14_specimen' or evidence.get('status') != 'review_required'
            or evidence.get('phase') != 'finished' or evidence.get('process_id') != process_id
            or evidence.get('new_tool_native_id') != expected_tool_native_id
            or evidence.get('expected_source_sha256') != expected_source_sha256):
        raise ValueError('Exact completed UD probe for this process/source/tool required')
    check_document_target(evidence.get('expected_document_path'), None,
                          expected_path=expected_document_path, required=True)
    for key in ('raw_readback_stable', 'exact_one_tool_created', 'protected_context_unchanged',
                'full_profiles_complete', 'creation_returned', 'load_returned'):
        if evidence.get(key) is not True:
            raise ValueError('Incomplete successful UD evidence: ' + key)
    for key in ('creation_pending', 'load_pending', 'operation_assignment_attempted', 'GTP_attempted',
                'GOP_attempted', 'TechDB_write_attempted', 'model_saved', 'post_cleanup_CAM_getters'):
        if evidence.get(key) is not False:
            raise ValueError('Unexpected UD evidence flag: ' + key)
    reads = evidence.get('tool_reads')
    if (type(reads) is not list or len(reads) != 2 or reads[0] != reads[1]
            or reads[0].get('native_id') != expected_tool_native_id
            or reads[0].get('tool_type_raw') != 14 or reads[0].get('profile_complete') is not True):
        raise ValueError('Two identical complete UD captures required')
    verify_one_new_tool(evidence['before_tools'], evidence['after_tools'], expected_tool_native_id)
    events = evidence.get('messages', {})
    if (events.get('subscribed') is not True or events.get('disconnected') is not True
            or events.get('active') is not False or any(events.get(k) for k in
            ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors'))):
        raise ValueError('Completed clean probe event scope required')
    specimen = evidence['specimen']
    if _file_hash(specimen['path']) != specimen['sha256']:
        raise ValueError('Original MT changed')
    creation_marker = ud14_attempt_marker(expected_document_path, expected_source_sha256, specimen['sha256'])
    creation_sha = _file_hash(creation_marker)
    creation = _pinned_json(creation_marker, creation_sha)
    if (creation.get('new_tool_native_id') != expected_tool_native_id
            or creation.get('creation_pending') is not False or creation.get('load_pending') is not False
            or creation.get('creation_returned') is not True or creation.get('load_returned') is not True):
        raise ValueError('Completed original creation marker required')
    check_document_target(creation.get('receipt_path'), None, expected_path=probe_receipt_path, required=True)
    marker = ud14_save_marker(expected_document_path, probe_receipt_sha256, expected_tool_native_id)
    if marker.exists() or marker.is_symlink():
        raise ValueError('Prior save attempt exists; inspect outcome, never replay with a renamed report')
    paths = [expected_document_path, probe_receipt_path, specimen['path'], creation_marker, marker, receipt_path]
    if len({str(Path(x).resolve()).casefold() for x in paths}) != len(paths):
        raise ValueError('Source, MT, evidence, attempt markers and report must be distinct')
    return evidence, marker, dict(path=str(creation_marker), sha256=creation_sha)


def verify_saved_capture(capture, evidence):
    expected = dict(context=evidence['before_context'], tools=evidence['after_tools'],
        tool=evidence['tool_reads'][0], metric_scope=evidence['after_metric_scope'])
    if capture != expected:
        raise ValueError('Existing UD profiles/parameters, local tools or protected context differ from completed probe')


def run_one_existing_save(report, *, capture, verify, guard, claim, persist, save, saved_hash):
    """One capture before/after; capture must release ordinary rb handles on return."""
    report['phase'] = 'before_capture'; persist()
    before = capture('before'); verify(before)
    report['before'] = before; persist(); guard()
    report.update(phase='SaveActiveDocument', save_pending=True, save_attempted=True,
                  mutation_attempted=True, native_call_attempted=True)
    claim(); persist(); guard()
    result = save()
    report.update(native_call_returned=True, save_pending=False,
                  native_return_type=type(result).__name__,
                  native_return_value=result if result is None or type(result) in (bool, int, float, str) else None)
    persist()
    if type(result) is not int or result != 0:
        raise ValueError('Unexpected native SaveActiveDocument HRESULT/no-OUT result; no replay')
    report['saved_file_sha256'] = saved_hash(); persist(); guard()
    report['phase'] = 'after_capture'; persist()
    after = capture('after'); verify(after)
    if after != before:
        raise ValueError('Save changed the observed UD or protected context')
    report['after'] = after; report['save_readback_verified'] = True; persist()


def save_existing_ud14(sw, clsid, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, expected_tool_native_id, probe_receipt_path, probe_receipt_sha256,
        qualification_only, acknowledge_disposable_copy, receipt_path, message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(schema_version=1, scope=SCOPE, action='save_existing', status='error', phase='preflight',
        process_id=process_id, expected_document_path=expected_document_path,
        source_before_sha256=expected_source_sha256, tool_native_id=expected_tool_native_id,
        probe_receipt_path=probe_receipt_path, probe_receipt_sha256=probe_receipt_sha256,
        mutation_attempted=False, save_attempted=False, save_pending=False, native_call_attempted=False,
        native_call_returned=False, model_saved=False, save_readback_verified=False,
        reopen_persistence_verified=False, close_attempted=False, creator_attempted=False,
        MT_load_attempted=False, assignment_attempted=False, GTP_attempted=False, GOP_attempted=False,
        TechDB_write_attempted=False, automatic_replay=False, post_cleanup_CAM_getters=False,
        native_read_count=0, capture_count=0, capture_diagnostics=[], may_continue=False,
        production_qualified=False)
    started = monotonic(); created = False; marker_created = False
    marker = None; session = None; files = None; baseline = None; evidence = None
    source_sha = expected_source_sha256; app = None; save_app = None; creation_pin = None
    def marker_state():
        return dict(scope=SCOPE, action='save_existing', document=expected_document_path,
            probe_sha256=probe_receipt_sha256, tool_native_id=expected_tool_native_id,
            receipt_path=receipt_path, save_pending=report['save_pending'],
            native_call_returned=report['native_call_returned'], phase=report['phase'],
            status='dispatch_pending' if report['save_pending'] else report['status'],
            source_before_sha256=expected_source_sha256,
            saved_file_sha256=report.get('saved_file_sha256'), automatic_replay=False)
    def persist():
        report['elapsed_seconds'] = monotonic() - started
        if created:
            if marker_created:
                _write_receipt(marker, marker_state())
            _write_receipt(receipt_path, report)
    def claim():
        nonlocal marker_created
        _write_receipt(marker, marker_state(), create=True)
        marker_created = True
    def check_pins():
        if (_file_hash(probe_receipt_path) != probe_receipt_sha256
                or _file_hash(evidence['specimen']['path']) != evidence['specimen']['sha256']
                or _file_hash(creation_pin['path']) != creation_pin['sha256']):
            raise ValueError('Pinned probe, MT or original creation marker changed')
    def identity():
        pid = _member(sw, 'GetProcessID')
        if type(pid) is not int or pid != process_id:
            raise ValueError('Exact process changed')
        value = raw_part_identity(sw)
        check_document_target(value['path'], value['title'], expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != source_sha:
            raise ValueError('Saved source differs')
        if baseline is not None and dict(value, needs_save=baseline['needs_save']) != baseline:
            raise ValueError('Document identity changed')
        return value
    def events(active=True):
        value = session.summary(); report['messages'] = value
        if (value.get('subscribed') is not True or value.get('active') is not active
                or (not active and value.get('disconnected') is not True)
                or any(value.get(k) for k in ('event_count','overflow','callback_errors',
                   'callback_error_count','subscription_error','disconnect_errors'))):
            raise ValueError('CAM event/transport requires stop')
    def guard():
        events()
        if files is not None:
            files.check()
        _check_capture_document(sw, {'process_id': process_id}, {'document': baseline})
        events()
    def read(obj, name, *args):
        guard()
        if report['native_read_count'] >= MAX_READS:
            raise ValueError('Bounded native read budget exceeded')
        report['native_read_count'] += 1
        value = _member(obj, name, *args); guard(); return value
    def typed(raw, name):
        guard()
        if report['native_read_count'] >= MAX_READS:
            raise ValueError('Bounded native interface budget exceeded')
        report['native_read_count'] += 1
        value = _typed(raw, name, typelib_path); guard(); return value
    def capture(label):
        nonlocal files, save_app
        check_pins(); identity(); guard()
        report['capture_count'] += 1
        if report['capture_count'] > 2:
            raise ValueError('Only one capture before and after save')
        diagnostic = dict(phase=label); report['capture_diagnostics'].append(diagnostic); persist()
        try:
            with _CaptureReadFiles(expected_document_path, evidence['specimen']['path']) as opened:
                files = opened
                active = read(app, 'IGetActiveDoc'); doc = typed(active, 'ICWDoc3')
                doc_type = read(doc, 'GetDocType')
                if type(doc_type) is not int or doc_type != 1:
                    raise ValueError('CAM part required')
                part = typed(active, 'ICWPartDoc'); machine = typed(read(part, 'IGetMachine'), 'ICWMachine')
                machine_type = read(machine, 'MachType')
                if type(machine_type) is not int or machine_type != 1:
                    raise ValueError('MILL machine required')
                crib = typed(read(machine, 'IGetToolcrib'), 'ICWToolcrib4')
                local = capture_local_tools(crib, doc, read, typed)
                protected = capture_protected_context(machine, doc, read, typed)
                matches = [raw for raw in _items(read(crib, 'GetAllTools'), typed, read, 128)
                           if _object_id(doc, raw, read) == expected_tool_native_id]
                if len(matches) != 1:
                    raise ValueError('Existing exact local UD tool required')
                tool = read_ud14_tool(matches[0], doc=doc, read=read, typed=typed, diagnostic=diagnostic)
                def sw_read(obj, name):
                    guard(); result = call(obj, name); guard(); return result
                units = read_document_cam_unit_scope(sw.ActiveDoc, app, sw_read=sw_read, cam_read=read)
                # The native save owner is prepared during guarded readback, never a new application.
                save_app = typed(app, 'ICWApp')
                state = dict(context=protected, tools=local, tool=tool, metric_scope=units)
                guard()
        finally:
            files = None
        check_pins(); identity(); guard(); return state
    def boundary():
        if files is not None:
            raise ValueError('Read handles must be closed before native save')
        check_pins(); identity(); guard()
    def save():
        boundary()
        return _member(save_app, 'SaveActiveDocument')
    def saved_hash():
        nonlocal source_sha
        events(); check_pins()
        source_sha = _file_hash(expected_document_path)
        identity(); events(); return source_sha
    try:
        args = dict(process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, expected_tool_native_id=expected_tool_native_id,
            probe_receipt_path=probe_receipt_path, probe_receipt_sha256=probe_receipt_sha256,
            qualification_only=qualification_only, acknowledge_disposable_copy=acknowledge_disposable_copy,
            receipt_path=receipt_path, message_policy=message_policy)
        evidence, marker, creation_pin = validate_ud14_save_request(**args)
        report['save_marker_path'] = str(marker); report['creation_marker_pin'] = creation_pin
        _write_receipt(receipt_path, report, create=True); created = True
        baseline = identity()
        if baseline != evidence.get('after_cleanup_document') or baseline['needs_save'] is not False:
            raise ValueError('Exact clean document identity from completed probe required')
        report['before_document'] = baseline; persist()
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline:
            raise ValueError('Identity changed acquiring CAM event host')
        session = CamMessageSession(app, typelib_path)
        with session:
            events()
            run_one_existing_save(report, capture=capture,
                verify=lambda state: verify_saved_capture(state, evidence), guard=boundary,
                claim=claim, persist=persist, save=save, saved_hash=saved_hash)
            report['after_document'] = identity()
            if report['after_document']['needs_save'] is not False:
                raise ValueError('Native save left document dirty')
            events()
        events(active=False)
        report['after_cleanup_document'] = identity()
        check_pins(); events(active=False)
        report.update(status='review_required', phase='finished', model_saved=True,
            reason='ONE_NATIVE_CAM_SAVE_AND_UNCHANGED_UD_READBACK_REOPEN_NOT_VERIFIED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'], phase='finished', issue=_error(exc),
            save_readback_verified=False, model_saved=False)
    finally:
        if session is not None:
            report['messages'] = session.summary()
        try:
            persist()
        except Exception as exc:
            report.update(status='uncertain' if report['mutation_attempted'] else 'error',
                receipt_write_error=_error(exc), model_saved=False, save_readback_verified=False)
    return report
