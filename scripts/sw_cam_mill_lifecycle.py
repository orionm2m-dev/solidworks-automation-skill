"""Single native save/close of an explicit MILL qualification copy with zero operations.
All CAM snapshots run under one event subscription. No generation or implicit save.
The returned snapshot covers machine/catalogue/setup axes/material and feature counts,
not complete feature geometry, and a save is not a reopen/persistence qualification.
"""
from __future__ import annotations

from pathlib import Path
import re

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_lifecycle import _MessageBlocked, _open_documents, _target, _verify_save
from scripts.sw_cam_mill_qualification import _bootstrap, _snapshot as _mill_snapshot
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path


def _zero_operations(state):
    if state['current_machine']['machine_type'] != 1:
        raise ValueError('MILL qualification lifecycle requires native machine type 1')
    counts = state['operation_counts']
    setups = state['feature_setups']
    if not isinstance(counts, list) or len(counts) > 8 or any(type(n) is not int or n != 0 for n in counts):
        raise ValueError('MILL qualification lifecycle requires exactly zero operations')
    if (not isinstance(setups, list) or len(setups) > 8 or
            any(type(row.get('feature_count')) is not int or not 0 <= row['feature_count'] <= 256 for row in setups)):
        raise ValueError('Bounded MILL setup/feature inventory required')
    if type(state['document'].get('needs_save')) is not bool:
        raise ValueError('Strict SOLIDWORKS saved-state flag required')


def mill_document_lifecycle(sw, clsid, typelib_path, *, expected_document_path, action,
        process_id, acknowledge_qualification_copy, message_policy='vendor_default',
        expected_state_sha256=None, receipt_path=None):
    from scripts.sw_cam_events import CamMessageSession

    report = dict(status='error', machine_kind='mill_qualification', process_id=process_id,
        action=action, phase='preflight', may_continue=False, mutation_attempted=False,
        native_dispatch_pending=False, native_call_attempted=False, native_call_returned=False,
        native_save_call_returned=False, native_close_call_returned=False,
        native_return_type=None, native_return_value=None, native_hresult=None,
        save_readback_verified=False, close_verified=False, persistence_verified=False,
        generation_attempted=False, AFR_attempted=False, GOP_attempted=False, GTP_attempted=False,
        native_outcome='not_called', response='default_unknown', cam_save_restore_flag='unknown',
        cam_dirty_state='unknown', message_policy=message_policy, post_cleanup_CAM_getters=False,
        snapshot_scope='MILL configuration and bounded feature counts; no complete feature geometry',
        last_CAM_snapshot_scope='inside active event subscription before cleanup', snapshot_diagnostics=[])
    receipt = None
    receipt_created = False
    session = None

    def identity():
        actual = _member(sw, 'GetProcessID')
        if type(actual) is not int or actual != process_id:
            raise ValueError('Exact SOLIDWORKS process identity changed')
        doc = document_snapshot(sw)
        _target(doc, expected_document_path)
        return dict(document=doc, saved_file_sha256=_file_hash(expected_document_path))

    def check(*, active=True):
        summary = session.summary()
        report['messages'] = summary
        if (summary.get('subscribed') is not True or
                (active and summary.get('active') is not True) or
                (not active and (summary.get('disconnected') is not True or summary.get('active') is not False)) or
                any(summary.get(key) for key in ('event_count', 'overflow', 'callback_errors',
                    'callback_error_count', 'subscription_error', 'disconnect_errors'))):
            raise _MessageBlocked('CAM message or event transport requires review; stop native calls')

    def capture(phase):
        report['phase'] = phase
        check()
        before_identity = identity()
        check()
        diagnostic = dict(phase=phase)
        report['snapshot_diagnostics'].append(diagnostic)
        state, native = _mill_snapshot(sw, clsid, typelib_path, expected_document_path,
            check=check, diagnostic=diagnostic, required_machine_type=1)
        check()
        _zero_operations(state)
        after_identity = identity()
        check()
        observed = {key: state[key] for key in ('document', 'saved_file_sha256')}
        if before_identity != observed or after_identity != observed:
            raise ValueError('Document or saved file changed during MILL lifecycle capture')
        state.update(machine_kind='mill_qualification', process_id=process_id)
        return state, native

    def close_identity():
        actual = _member(sw, 'GetProcessID')
        if type(actual) is not int or actual != process_id:
            raise ValueError('Exact process changed after close')
        return _file_hash(expected_document_path)

    def require_user_control():
        value = _member(sw, 'UserControl')
        report['user_control_before_close'] = value if type(value) is bool else 'unverified'
        if value is not True:
            raise ValueError('Close requires verified UserControl=true without changing it')

    try:
        if type(process_id) is not int or not 0 < process_id <= 0xFFFFFFFF or acknowledge_qualification_copy is not True:
            raise ValueError('Exact positive process ID and explicit qualification-copy acknowledgement required')
        if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold() != '.sldprt'):
            raise ValueError('Exact absolute saved qualification .sldprt required')
        if action not in ('prepare', 'save', 'close') or message_policy != 'vendor_default':
            raise ValueError('Explicit prepare/save/close with vendor_default required')
        if action == 'prepare':
            if expected_state_sha256 is not None or receipt_path is not None:
                raise ValueError('Prepare rejects mutation inputs')
        else:
            if not isinstance(expected_state_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_state_sha256):
                raise ValueError('Exact prepared state SHA-256 required')
            receipt = Path(receipt_path) if isinstance(receipt_path, str) else None
            if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != '.json'
                    or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink()):
                raise ValueError('Unique absolute JSON receipt in an existing directory required')
            _write_receipt(receipt, report, create=True)
            receipt_created = True
        initial_identity = identity()
        # Only the event-host acquisition precedes subscription; no CAM document reads here.
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != initial_identity:
            raise ValueError('Document or saved file changed while acquiring the event host')
        session = CamMessageSession(app, typelib_path)
        with session:
            before, native = capture('initial_capture')
            report.update(before=before, state_sha256=_digest(before), phase='prepared')
            if action != 'prepare':
                if report['state_sha256'] != expected_state_sha256:
                    raise ValueError('Prepared MILL scope, process, document, file or CAM state changed')
                if action == 'close':
                    if before['document']['needs_save'] is not False:
                        raise ValueError('Close requires needs_save=false; CAM dirty state remains unknown')
                    require_user_control()
                    check()
                current, native = capture('before_native_action')
                if current != before:
                    raise ValueError('MILL state changed immediately before native action')
                check()
                app = _typed(native['app'], 'ICWApp', typelib_path)
                check()
                report.update(phase='SaveActiveDocument' if action == 'save' else 'CloseActiveDocument',
                    native_dispatch_pending=True, native_outcome='unknown')
                _write_receipt(receipt, report)
                check()
                if identity() != {key: before[key] for key in ('document', 'saved_file_sha256')}:
                    raise ValueError('Document/file changed immediately before native dispatch')
                check()
                if action == 'close':
                    require_user_control()
                    check()
                report.update(mutation_attempted=True, native_call_attempted=True)
                returned = _member(app, 'SaveActiveDocument' if action == 'save' else 'CloseActiveDocument')
                report.update(native_call_returned=True, native_dispatch_pending=False, phase='native_returned',
                    native_return_type=type(returned).__name__,
                    native_return_value=returned if type(returned) in (int, bool, str, float, type(None)) else None,
                    native_hresult=returned if type(returned) is int else None)
                report['native_save_call_returned' if action == 'save' else 'native_close_call_returned'] = True
                _write_receipt(receipt, report)
                check()
                # Installed generated HRESULT/no-OUT vtable binding is tested with
                # an in-memory ICWApp server; S_OK returns a strict Python int 0.
                if type(returned) is not int or returned != 0:
                    raise ValueError('Unexpected native lifecycle HRESULT binding result')
                if action == 'save':
                    after, _ = capture('after_native_save')
                    report['after'] = after
                    _verify_save(before, after)
                    if after['document']['needs_save'] is not False:
                        raise ValueError('Native save returned but document remains dirty')
                    final_cam = after
                else:
                    report['open_documents_after'] = _open_documents(sw, expected_document_path, check=check)
                    if close_identity() != before['saved_file_sha256']:
                        raise ValueError('Saved file changed during close')
                    check()
            else:
                final_cam = before
            check()
        report['phase'] = 'after_cleanup'
        check(active=False)
        # No CAM getter, QI or new subscription beyond this boundary.
        if action == 'close':
            final_documents = _open_documents(sw, expected_document_path, check=lambda: check(active=False))
            report['open_documents_after_cleanup'] = final_documents
            if final_documents != report['open_documents_after'] or close_identity() != before['saved_file_sha256']:
                raise ValueError('Open documents or saved file changed during event cleanup')
            report.update(close_verified=True, native_outcome='target_absent_from_open_documents',
                reason='CLOSE_VERIFIED_CAM_PERSISTENCE_UNVERIFIED')
        else:
            final = identity()
            report['after_cleanup_sw_file'] = final
            if final != {key: final_cam[key] for key in ('document', 'saved_file_sha256')}:
                raise ValueError('Document or saved file changed during event cleanup')
            if action == 'save':
                report.update(final_state=final_cam, state_sha256=_digest(final_cam), save_readback_verified=True,
                    saved_file_changed=before['saved_file_sha256'] != final_cam['saved_file_sha256'],
                    native_outcome='save_returned_readback_verified', reason='SAVE_RETURNED_PERSISTENCE_REQUIRES_REOPEN')
        check(active=False)
        report.update(status='ok' if action == 'prepare' else 'review_required', phase='finished')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else
            ('review_required' if isinstance(exc, _MessageBlocked) else 'error'),
            failed_phase=report['phase'], phase='finished', reason='CAM_MILL_LIFECYCLE_FAILED', issue=_error(exc),
            save_readback_verified=False, close_verified=False)
        if report['mutation_attempted']:
            report['native_outcome'] = 'unknown'
    finally:
        if session is not None:
            report['messages'] = session.summary()
        if receipt_created:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status='uncertain', receipt_write_error=_error(exc), save_readback_verified=False,
                    close_verified=False, native_outcome='unknown')
    return report
