"""One raw native CutDiameter change on a disposable MILL tool.
Reads all current operation tool references; no GTP/GOP/save or physical unit claim.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import re
import math
import time
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_feature_process import capture_mill_feature_state, _integer
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_mill_toolpath import _read_assigned_tool
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _eligible(state, tool_id, old):
    return (all(row['toolpath_generated'] is False and
        all(type(n) is int and n == 0 for n in row['toolpath_record_counts'])
        for row in state['operations']) and
        all(row['tool']['cut_diameter_native'] == old for row in state['assigned_tools']
            if row['tool']['native_id'] == tool_id))


def _assigned_tools(state, native, op_ids, feature_id, tool_id, tool_type, typelib_path, check, diagnostic):
    if [row['native_id'] for row in state['operations']] != op_ids:
        raise ValueError('Exact ordered operation IDs required')
    if any(row['linked_feature_ids'] != [feature_id] or row['suppressed'] is not False for row in state['operations']):
        raise ValueError('Only unsuppressed operations linked solely to exact feature allowed')
    rows=[]; by_id={}; diagnostic['assigned_tools']=[]
    for op_id in op_ids:
        detail=dict(operation_native_id=op_id); diagnostic['assigned_tools'].append(detail)
        tool=_read_assigned_tool(native,op_id,typelib_path,check,detail)
        tid=tool['native_id']
        if tid in by_id and by_id[tid] != tool:
            raise ValueError('Shared tool changed between operation reads')
        by_id[tid]=tool; rows.append(dict(operation_native_id=op_id,tool=tool))
    if tool_id not in by_id or by_id[tool_id]['tool_type_raw'] != tool_type:
        raise ValueError('Exact assigned target tool identity and generic type required')
    state['assigned_tools']=rows
    state['affected_operation_native_ids']=[row['operation_native_id'] for row in rows if row['tool']['native_id']==tool_id]


def _verify_diameter_delta(before,after,tool_id,old,new):
    if not _eligible(before,tool_id,old):raise ValueError('Baseline has paths or stale diameter')
    expected=deepcopy(before)
    for row in expected['assigned_tools']:
        if row['tool']['native_id']==tool_id:row['tool']['cut_diameter_native']=float(new)
    expected['document']['needs_save']=after['document']['needs_save']
    if expected != after:
        raise ValueError('Diameter readback or unaffected captured state differs')
    return deepcopy(after['affected_operation_native_ids'])


def qualify_mill_tool_diameter(sw, clsid, typelib_path, *, process_id,
        expected_document_path, expected_source_sha256, expected_feature_native_id,
        expected_operation_native_ids, expected_tool_native_id, expected_tool_type_raw,
        expected_cut_diameter_native, new_cut_diameter_native,
        action, qualification_only, acknowledge_disposable_copy, message_policy='vendor_default',
        expected_state_sha256=None, receipt_path=None):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(status='error', phase='preflight', action=action, process_id=process_id,
        may_continue=False, mutation_attempted=False, native_dispatch_pending=False,
        native_call_attempted=False, native_call_returned=False, native_hresult_observable=False, property_assignment=True,
        readback_verified=False, diameter_readback_verified=False, model_saved=False,
        AFR_attempted=False, GOP_attempted=False, GTP_attempted=False, simulation_attempted=False, stock_edit_attempted=False,
        units_verified=False, physical_depth_verified=False, tool_or_material_process_qualified=False,
        production_qualified=False, post_cleanup_CAM_getters=False,
        snapshot_scope='current single-feature MILL operation inventory and all assigned generic tools; not whole RAM BRep or external TechDB',
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
        _assigned_tools(state,native,expected_operation_native_ids,expected_feature_native_id,
            expected_tool_native_id,expected_tool_type_raw,typelib_path,check,diagnostic)
        check()
        if identity() != begin:
            raise ValueError('Document/source changed during selected tool read')
        check(); timing.update(completed=True, elapsed_seconds=time.monotonic()-start)
        persist(); return state, native
    try:
        _integer(process_id, positive=True); _integer(expected_feature_native_id, positive=True)
        _integer(expected_tool_native_id, positive=True)
        if (type(expected_operation_native_ids) is not list or not 1 <= len(expected_operation_native_ids) <= 32 or
                any(type(v) is not int or not 1 <= v <= 0xFFFFFFFF for v in expected_operation_native_ids) or
                len(set(expected_operation_native_ids)) != len(expected_operation_native_ids)):
            raise ValueError('Ordered unique strict operation IDs required')
        if type(expected_tool_type_raw) is not int or expected_tool_type_raw != 1:
            raise ValueError('This bounded diagnostic setter requires generic ToolType1')
        for value in (expected_cut_diameter_native,new_cut_diameter_native):
            if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
                raise ValueError('Finite positive native diameters required')
        if expected_cut_diameter_native == new_cut_diameter_native:
            raise ValueError('Different explicit old and new native diameter required')
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
                expected_operation_native_ids=expected_operation_native_ids,expected_tool_native_id=expected_tool_native_id,
                expected_tool_type_raw=expected_tool_type_raw,expected_cut_diameter_native=expected_cut_diameter_native,
                new_cut_diameter_native=new_cut_diameter_native,scope='MILL_SHARED_TOOL_DIAMETER_ONLY')
            report.update(before=before,state_sha256=_digest(state_key),
                apply_eligible=before['document']['needs_save'] is False and
                    _eligible(before,expected_tool_native_id,expected_cut_diameter_native))
            persist()
            if action != 'inspect' and not report['apply_eligible']:
                raise ValueError('Prepare/apply requires clean saved state, old diameter and all operations without calculated records')
            if action == 'apply':
                if report['state_sha256'] != expected_state_sha256:
                    raise ValueError('Prepared scope/process/source/feature state changed')
                current, native = capture('before_mutation_capture')
                if current != before:
                    raise ValueError('State changed immediately before diameter setter')
                def read(obj,name,*args):
                    check(); value=_member(obj,name,*args); check(); return value
                op_id=before['affected_operation_native_ids'][0]
                check(); operation=_typed(native['operations'][op_id],'ICWOperation',typelib_path); check()
                raw=read(operation,'IGetTool')
                check(); target=_typed(raw,'ICWTool',typelib_path); check()
                if (_object_id(native['doc'],target,read) != expected_tool_native_id or
                        read(target,'CutDiameter') != expected_cut_diameter_native):
                    raise ValueError('Target tool changed immediately before setter')
                report.update(phase='put_CutDiameter',native_dispatch_pending=True)
                persist(); check()
                if identity() != before['document']:raise ValueError('Document changed before setter')
                check(); started=time.monotonic()
                report.update(mutation_attempted=True,native_call_attempted=True)
                setattr(target,'CutDiameter',float(new_cut_diameter_native))
                report.update(native_call_returned=True,native_dispatch_pending=False,phase='setter_returned',
                    native_call_seconds=time.monotonic()-started)
                persist(); check()
                after,_=capture('after_mutation_capture')
                report['after']=after; persist()
                report['affected_operation_native_ids']=_verify_diameter_delta(before,after,expected_tool_native_id,
                    expected_cut_diameter_native,new_cut_diameter_native)
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
            readback_verified=action=='apply',diameter_readback_verified=action=='apply',
            reason='DIAGNOSTIC_NATIVE_DIAMETER_ONLY_UNITS_REAL_TOOL_FIT_GEOMETRY_AND_PROCESS_UNQUALIFIED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,diameter_readback_verified=False,apply_eligible=False)
    finally:
        if session is not None:report['messages']=session.summary()
        if created:
            try:persist()
            except Exception as exc:report.update(status='uncertain',receipt_write_error=_error(exc),readback_verified=False,diameter_readback_verified=False)
    return report
