"""Single native target/stock/WIP export for a bounded MILL qualification fixture.
Exports entire machine/all setups. No generation, save, simulation or tool edits.
Native files are evidence, not depth/unit/stock-removal/manufacturing proof.
"""
from __future__ import annotations
from pathlib import Path
import os
import re
import time
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_feature_process import capture_mill_feature_state, _integer
from scripts.sw_cam_simulation import _check_output_path, _file_evidence
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path, check_document_target

MAX_FILE_BYTES=128*1024*1024
MAX_TOTAL_BYTES=512*1024*1024


def _ids(values):
    if (type(values) is not list or len(values)>32 or any(type(x) is not int or not 0<x<=0xFFFFFFFF for x in values)
            or len(set(values))!=len(values)):
        raise ValueError('Exact ordered unique operation IDs, zero to32, required')


def _scope(state,feature_id,ids,generated_ids,kind):
    rows=state['operations']
    if ([r['native_id'] for r in rows]!=ids or any(r['linked_feature_ids']!=[feature_id] for r in rows) or
            [r['native_id'] for r in rows if r['toolpath_generated']]!=generated_ids):
        raise ValueError('Exact operation IDs, sole feature links and generated IDs required')
    for row in rows:
        counts=row['toolpath_record_counts']
        if (type(counts) is not list or any(type(n) is not int or n<0 for n in counts) or
                (row['toolpath_generated'] and (row['suppressed'] is not False or not counts or sum(counts)<=0)) or
                (not row['toolpath_generated'] and any(counts))):
            raise ValueError('Generated flags and actual bounded record counts disagree')
    if kind=='wip' and not generated_ids:
        raise ValueError('WIP needs an explicitly generated path; no automatic GTP')


def _output_plan(output_dir):
    if type(output_dir) is not str:
        raise ValueError('Explicit new local output directory required')
    directory=Path(output_dir)
    if not directory.is_absolute() or not directory.parent.is_dir() or directory.exists() or directory.is_symlink():
        raise ValueError('New absolute output directory and existing parent required')
    parent=directory.parent.resolve(strict=True)
    if directory.drive.startswith('\\\\') or parent.drive.startswith('\\\\'):
        raise ValueError('Native geometry output requires a local drive, not UNC/WSL')
    return directory,parent/directory.name


def _collect_files(directory,canonical,kind):
    if directory.is_symlink() or directory.resolve(strict=True)!=canonical:
        raise ValueError('Native output directory identity changed')
    files=[];total=0
    for count,path in enumerate(directory.rglob('*'),1):
        if count>1024 or path.is_symlink() or not path.resolve(strict=True).is_relative_to(canonical):
            raise ValueError('Export output tree exceeds the verified boundary')
        if path.is_file():
            size=path.stat().st_size;total+=size
            if path.suffix.casefold()!='.stl' or len(files)>=512 or size>MAX_FILE_BYTES or total>MAX_TOTAL_BYTES:
                raise ValueError('Unexpected or oversized native export output')
            files.append(path)
    files.sort(key=str)
    if kind!='wip' and files and files!=[directory/(kind+'.stl')]:
        raise ValueError('Unexpected target/stock output file set')
    return [_file_evidence(path) for path in files]


def export_mill_feature_geometry(sw, clsid, typelib_path, *, process_id,
        expected_document_path, expected_source_sha256, expected_feature_native_id,
        expected_operation_native_ids, expected_generated_operation_native_ids, export_kind, output_dir,
        action, qualification_only, acknowledge_document_wide_export, message_policy='vendor_default',
        expected_state_sha256=None, receipt_path=None):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(status='error', phase='preflight', action=action, process_id=process_id,
        may_continue=False, mutation_attempted=False, native_dispatch_pending=False,
        native_call_attempted=False, native_call_returned=False, native_return=None,
        readback_verified=False, export_files_verified=False, model_saved=False,
        AFR_attempted=False, GOP_attempted=False, GTP_attempted=False, simulation_attempted=False, stock_edit_attempted=False,
        units_verified=False, physical_depth_verified=False, tool_or_material_process_qualified=False,
        production_qualified=False, post_cleanup_CAM_getters=False, export_kind=export_kind, scope='entire_machine_all_setups_single_feature_fixture',
        mesh_content_verified=False, frame_verified=False, removal_verified=False,
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
        if phase=='after_export_capture':
            report['after']=state;persist()
        _scope(state, expected_feature_native_id, expected_operation_native_ids, expected_generated_operation_native_ids, export_kind)
        check(); native['export_machine']=_typed(native['machine'], 'ICWMachine5', typelib_path); check()
        timing.update(completed=True, elapsed_seconds=time.monotonic()-start)
        persist(); return state, native
    try:
        _integer(process_id, positive=True); _integer(expected_feature_native_id, positive=True)
        _ids(expected_operation_native_ids); _ids(expected_generated_operation_native_ids)
        if export_kind not in ('target','stock','wip') or (export_kind=='wip' and not expected_generated_operation_native_ids):
            raise ValueError('One exact export kind; WIP requires an explicitly generated operation')
        if any(i not in expected_operation_native_ids for i in expected_generated_operation_native_ids):
            raise ValueError('Generated operation IDs must be a subset of explicit operation IDs')
        directory, canonical_directory = _output_plan(output_dir)
        if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or
                Path(expected_document_path).suffix.casefold() != '.sldprt'):
            raise ValueError('Exact absolute saved qualification part required')
        if type(expected_source_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_source_sha256) is None:
            raise ValueError('Exact saved source SHA required, including inspect')
        if qualification_only is not True or acknowledge_document_wide_export is not True or message_policy != 'vendor_default':
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
                expected_operation_native_ids=expected_operation_native_ids,
                expected_generated_operation_native_ids=expected_generated_operation_native_ids,
                export_kind=export_kind,output_dir=str(directory),canonical_output_dir=str(canonical_directory),
                scope='MILL_SINGLE_FEATURE_MACHINE_GEOMETRY_EXPORT')
            report.update(before=before,state_sha256=_digest(state_key),
                apply_eligible=before['document']['needs_save'] is False)
            persist()
            if not report['apply_eligible']:
                raise ValueError('Geometry export requires clean saved MILL qualification part')
            if action == 'apply':
                if report['state_sha256'] != expected_state_sha256:
                    raise ValueError('Prepared scope/process/source/feature state changed')
                current, native = capture('before_mutation_capture')
                if current != before:
                    raise ValueError('State changed immediately before geometry export')
                check(); machine5 = native['export_machine']; check()
                observed, canonical = _output_plan(output_dir)
                if observed != directory or canonical != canonical_directory:
                    raise ValueError('Output directory mapping changed since prepare')
                directory.mkdir()  # Exclusive: unknown export is never replayed in an old directory.
                if directory.resolve(strict=True) != canonical_directory:
                    raise ValueError('Output directory mapping changed on creation')
                output_path = directory / (export_kind + '.stl')
                _check_output_path(output_path,directory,canonical_directory)
                methods = dict(target=('CreateSTLOfTargetInFCSSpace',(str(output_path),0)),
                    stock=('CreateSTLOfStock',(str(output_path),'',0)),
                    wip=('CreateSTLOfWIPs2',(str(directory)+os.sep,'wip.stl','',0,0)))
                method,args = methods[export_kind]
                report.update(phase=method,native_method=method,native_parameters=list(args),
                    output_dir=str(directory),canonical_output_dir=str(canonical_directory),
                    native_dispatch_pending=True,native_call_started_unix=time.time())
                persist(); check()
                if identity() != before['document'] or any(directory.iterdir()):
                    raise ValueError('Document/output changed before dispatch')
                _check_output_path(output_path,directory,canonical_directory)
                check(); started=time.monotonic()
                report.update(mutation_attempted=True,native_call_attempted=True)
                result = _member(machine5,method,*args)
                report.update(native_call_returned=True,native_dispatch_pending=False,phase='export_returned',
                    native_return_type=type(result).__name__,native_return=result if type(result) is bool else None,
                    native_call_seconds=time.monotonic()-started)
                persist(); check()
                report['files'] = _collect_files(directory,canonical_directory,export_kind)
                persist()
                if result is not True or not report['files']:
                    raise ValueError('Native export requires strict True and nonempty regular STL output')
                after,_ = capture('after_export_capture')
                report['after']=after;persist()
                if before != after:
                    raise ValueError('Geometry export changed captured CAM/document/saved-file state')
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
        if action=='apply' and _collect_files(directory,canonical_directory,export_kind) != report['files']:
            raise ValueError('Output changed during event cleanup')
        report.update(status='review_required' if action=='apply' else 'ok',phase='finished',
            readback_verified=action=='apply',export_files_verified=action=='apply',
            reason='EXPORTED_BYTES_ONLY_MESH_FRAME_UNITS_REMOVAL_DEPTH_AND_PRODUCTION_UNQUALIFIED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,export_files_verified=False,apply_eligible=False)
    finally:
        if session is not None:report['messages']=session.summary()
        if created:
            try:persist()
            except Exception as exc:report.update(status='uncertain',receipt_write_error=_error(exc),readback_verified=False,export_files_verified=False)
    return report
