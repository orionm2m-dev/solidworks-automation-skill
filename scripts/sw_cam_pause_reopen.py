"""Read and verify a reopened owned MILL document against its saved pause receipt.

No document opening, parameter setters, generation, save, close or application exit.
"""
from copy import deepcopy
from pathlib import Path
import json
import os
import re
from scripts import sw_cam_pause_session as pause
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash

SCOPE = 'OWNED_MILL_PAUSE_REOPEN_V1'
PARAMS = {'process_id', 'expected_document_path', 'expected_source_sha256',
          'addin_clsid', 'typelib_path', 'receipt_path', 'module_sha256',
          'pause_receipt_path', 'pause_receipt_sha256',
          'startup_receipt_path', 'startup_receipt_sha256'}
FLAGS = ('mutation_attempted', 'open_attempted', 'GTP_attempted', 'save_attempted', 'close_attempted')
require = pause.require
exact = pause.exact


def pin(path):
    return {'path': str(path), 'sha256': _file_hash(path)}


def read_pin(path, sha):
    require(type(sha) is str and re.fullmatch('[0-9a-f]{64}', sha), 'Exact file hash required')
    p = Path(path)
    require(p.is_absolute() and p.is_file() and not p.is_symlink(), 'Existing absolute evidence file required')
    require(_file_hash(p) == sha, 'Pinned evidence changed')
    result = json.loads(p.read_text(encoding='utf-8-sig'))
    require(_file_hash(p) == sha, 'Pinned evidence changed during read')
    return result


def inventory_contract(snapshot):
    return {'expected_operation_ids': snapshot['operation_ids'],
            'expected_tool_count': len(snapshot['tool_ids']),
            'expected_feature_count': len(snapshot['feature_ids']),
            'expected_generated_path_count': sum(len(v['record_counts']) for v in snapshot['operations']),
            'expected_finish_fields': snapshot['finish_fields']}


def verify_saved_snapshot(snapshot, source, sha):
    require(type(snapshot) is dict and snapshot['saved_file_sha256'] == sha, 'Saved source hash mismatch')
    d = snapshot['document']
    require(os.path.normcase(os.path.abspath(d['path'])) == os.path.normcase(os.path.abspath(source)), 'Saved document target mismatch')
    require(d['type'] == 1 and d['needs_save'] is False, 'Saved clean part required')
    # The existing bounded reader and fixed paused finish contract remain authoritative.
    p = inventory_contract(snapshot)
    require(p['expected_operation_ids'] == [195, 196, 267, 247, 248, 271, 143, 144]
            and p['expected_tool_count'] == 19 and p['expected_feature_count'] == 21
            and p['expected_generated_path_count'] == 5
            and exact(p['expected_finish_fields'], pause.FIELDS), 'Exact paused MILL inventory required')
    pause.verify_snapshot(snapshot, p)


def load_evidence(p):
    saved = read_pin(p['pause_receipt_path'], p['pause_receipt_sha256'])
    require(saved.get('scope') == pause.SCOPE and saved.get('status') == 'paused_saved_closed'
            and saved.get('save_verified') is True and saved.get('close_verified') is True,
            'Verified saved and closed pause receipt required')
    require(saved.get('saved_source_sha256') == p['expected_source_sha256'], 'Pause saved source differs')
    require(os.path.normcase(os.path.abspath(saved['source_path'])) == os.path.normcase(os.path.abspath(p['expected_document_path'])), 'Pause target differs')
    verify_saved_snapshot(saved['after'], p['expected_document_path'], p['expected_source_sha256'])
    startup = read_pin(p['startup_receipt_path'], p['startup_receipt_sha256'])
    require(startup.get('status') == 'ok' and startup.get('phase') == 'connected'
            and startup.get('new_process_verified') is True and startup.get('user_control_verified') is True
            and startup.get('visible_verified') is True and startup.get('process_id') == p['process_id'],
            'Verified new owned process required')
    identity = startup.get('process_identity', {})
    require(identity.get('process_id') == p['process_id'] and identity.get('alive') is True
            and type(identity.get('create_time')) in (int, float) and identity['create_time'] > 0
            and type(identity.get('executable')) is str and identity['executable'], 'Exact startup process identity required')
    require(p['process_id'] not in startup.get('known_process_ids_before', [])
            and p['process_id'] != saved['process_id'], 'New process must differ from saved and preexisting sessions')
    return saved, startup


def validate_request(request):
    require(type(request) is dict and set(request) == {'action', 'params'}
            and request['action'] == 'verify_reopened_owned', 'Exact read-only reopen action required')
    p = deepcopy(request['params'])
    require(type(p) is dict and set(p) == PARAMS, 'Exact reopen request fields required')
    require(type(p['process_id']) is int and p['process_id'] > 0, 'Exact owned PID required')
    require(p['module_sha256'] == _file_hash(__file__), 'Reviewed reopen module changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}', p['addin_clsid']), 'Exact CAM CLSID required')
    source, tlb, out = [Path(p[k]) for k in ('expected_document_path', 'typelib_path', 'receipt_path')]
    require(source.is_absolute() and source.is_file() and source.suffix.lower() == '.sldprt', 'Existing saved part required')
    require(tlb.is_absolute() and tlb.is_file() and tlb.suffix.lower() == '.tlb', 'Installed type library required')
    require(out.is_absolute() and out.parent.is_dir() and not out.exists() and not out.is_symlink(), 'New receipt path required')
    require(not source.is_symlink() and not tlb.is_symlink(), 'Input symlinks are not accepted')
    require(_file_hash(source) == p['expected_source_sha256'], 'Saved source changed before reopen read')
    load_evidence(p)
    return p


class Journal:
    def __init__(self, p, saved, startup):
        self.path = Path(p['receipt_path'])
        self.report = dict(schema_version=1, scope=SCOPE, status='prepared', phase='prepared',
                           process_id=p['process_id'], source_path=p['expected_document_path'],
                           source_sha256=p['expected_source_sha256'], module_pin=pin(__file__),
                           pause_receipt=pin(p['pause_receipt_path']), startup_receipt=pin(p['startup_receipt_path']),
                           startup_identity=deepcopy(startup['process_identity']), before=deepcopy(saved['after']),
                           reopen_verified=False, automatic_replay=False, **{k: False for k in FLAGS})
        _write_receipt(self.path, self.report, create=True)
    def persist(self):
        _write_receipt(self.path, self.report)


class NativeBackend(pause.NativeBackend):
    def owned(self):
        super().owned()
        from scripts.sw_executable_launch import _process_identity
        require(exact(_process_identity(self.p['process_id']), self.journal.report['startup_identity']),
                'Owned process identity no longer matches startup')
    def save(self):
        raise RuntimeError('Read-only reopen verifier cannot save')
    def close_target(self, *args):
        raise RuntimeError('Read-only reopen verifier cannot close')
    def exit_owned(self):
        raise RuntimeError('Read-only reopen verifier cannot exit')


def run_steps(backend, journal, p):
    # Revalidate durable inputs immediately before any native read.
    saved, startup = load_evidence(p)
    require(exact(saved['after'], journal.report['before']) and exact(startup['process_identity'], journal.report['startup_identity']), 'Evidence changed before native read')
    require(_file_hash(p['expected_document_path']) == p['expected_source_sha256'], 'Saved source changed before native read')
    backend.start()
    actual = backend.capture('read_reopened')
    journal.report['actual'] = actual
    journal.persist()  # Preserve native mismatch before any comparison can fail.
    verify_saved_snapshot(actual, p['expected_document_path'], p['expected_source_sha256'])
    require(exact(actual, saved['after']), 'Reopened native CAM state differs from saved pause state')
    backend.boundary(actual['document'], p['expected_source_sha256'])
    journal.report['comparison_verified'] = True
    journal.persist()


def execute(sw, p, *, backend_factory=NativeBackend):
    saved, startup = load_evidence(p)
    journal = Journal(p, saved, startup)
    backend = backend_factory(sw, p, journal)
    try:
        run_steps(backend, journal, p)
    except Exception as exc:
        journal.report.update(status='error', failed_phase=journal.report['phase'], issue=_error(exc))
    finally:
        try:
            backend.stop_events()
        except Exception as exc:
            journal.report.update(status='error', cleanup_issue=_error(exc))
        if journal.report.get('comparison_verified') is True and not journal.report.get('issue') and not journal.report.get('cleanup_issue'):
            journal.report.update(status='reopen_verified', reopen_verified=True)
        journal.report['phase'] = 'finished'
        journal.persist()
    return journal.report


def load_verified_reopen(path, sha256):
    """Return a source-pinned successful reopen receipt, without native calls."""
    r = read_pin(path, sha256)
    require(r.get('scope') == SCOPE and r.get('status') == 'reopen_verified'
            and r.get('reopen_verified') is True and r.get('comparison_verified') is True,
            'Verified native reopen receipt required')
    require(all(r.get(k) is False for k in FLAGS) and not r.get('issue') and not r.get('cleanup_issue'), 'Read-only successful receipt required')
    require(r['module_pin']['sha256'] == _file_hash(__file__), 'Reopen verifier module changed')
    require(_file_hash(r['module_pin']['path']) == r['module_pin']['sha256'], 'Pinned reopen module file changed')
    p = dict(process_id=r['process_id'], expected_document_path=r['source_path'], expected_source_sha256=r['source_sha256'],
             pause_receipt_path=r['pause_receipt']['path'], pause_receipt_sha256=r['pause_receipt']['sha256'],
             startup_receipt_path=r['startup_receipt']['path'], startup_receipt_sha256=r['startup_receipt']['sha256'])
    saved, startup = load_evidence(p)
    require(exact(r['before'], saved['after']) and exact(r['actual'], r['before']), 'Reopen comparison differs from saved evidence')
    require(exact(r['startup_identity'], startup['process_identity']), 'Reopen startup identity differs')
    verify_saved_snapshot(r['actual'], r['source_path'], r['source_sha256'])
    require(_file_hash(r['source_path']) == r['source_sha256'], 'Reopened source has since changed')
    m = r.get('messages', {})
    require(m.get('subscribed') is True and m.get('disconnected') is True and m.get('active') is False
            and not any(m.get(k) for k in ('event_count', 'overflow', 'callback_errors', 'callback_error_count', 'subscription_error', 'disconnect_errors')), 'Clean disconnected CAM message capture required')
    return r


def dispatch_request(request, *, validate_only=False):
    p = validate_request(request)
    if validate_only:
        return dict(status='validated_offline', native_called=False)
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1, process_id=p['process_id']):
        sw, _ = connect_solidworks(process_id=p['process_id'], launch_new_instance=False, wait_seconds=1)
        return execute(sw, p)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(argv)
    result = dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')), validate_only=args.validate_only)
    print(json.dumps({k: result.get(k) for k in ('status', 'reopen_verified', 'issue')}, ensure_ascii=False))
    return 0 if result['status'] in ('validated_offline', 'reopen_verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
