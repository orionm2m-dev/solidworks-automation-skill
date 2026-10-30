"""Read only document GetUnits and ICWApp4.GetUseDocumentUnit; no UnitRecord getter."""
from pathlib import Path
import re
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity, call
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles
from scripts.sw_cam_thread import _file_hash
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def read_document_cam_unit_scope(model, app, *, sw_read, cam_read):
    """Two exact known getter contracts; never infer MT or native offset units."""
    units = sw_read(model, 'GetUnits')
    if not isinstance(units, (list, tuple)) or len(units) != 5 or any(type(x) is not int for x in units):
        raise ValueError('Exactly five native document unit integers required')
    use = cam_read(app, 'GetUseDocumentUnit')
    if type(use) is not bool:
        raise ValueError('Strict ICWApp4.GetUseDocumentUnit boolean required')
    return dict(SW_document_units_raw=list(units), CAM_use_document_units_raw=use,
                metric_document_scope_observed=(units[0] == 0 and use),
                MT_units_verified=False, native_CAM_geometry_units_verified=False)


def validate_unit_scope_request(*, process_id, expected_document_path, expected_source_sha256,
                                receipt_path, message_policy='vendor_default'):
    if type(process_id) is not int or not 0 < process_id < 2**32:
        raise ValueError('Exact process ID required')
    if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.lower() != '.sldprt'):
        raise ValueError('Exact absolute saved part path required')
    if type(expected_source_sha256) is not str or not re.fullmatch('[0-9a-f]{64}',expected_source_sha256):
        raise ValueError('Exact source SHA256 required')
    if message_policy != 'vendor_default':
        raise ValueError('Default vendor message policy required')
    if (type(receipt_path) is not str or not absolute_document_path(receipt_path)
            or Path(receipt_path).suffix.lower() != '.json' or not Path(receipt_path).parent.is_dir()
            or Path(receipt_path).exists() or Path(receipt_path).is_symlink()):
        raise ValueError('Unique absolute JSON receipt in an existing directory required')


def inspect_document_cam_unit_scope(sw, clsid, typelib_path, *, process_id,
        expected_document_path, expected_source_sha256, receipt_path, message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(schema_version=1, scope='read_only_document_cam_unit_scope', status='error',
        phase='preflight', mutation_attempted=False, tool_created=False, MT_loaded=False,
        model_saved=False, TechDB_write_attempted=False, GTP_attempted=False,
        UnitRecord_getter_called=False, post_cleanup_CAM_getters=False,
        source_sha256=expected_source_sha256, process_id=process_id, scope_reads=[],
        raw_readback_stable=False, MT_units_verified=False, may_continue=False)
    receipt = None; created = False; session = None; baseline = None; files = None
    def persist():
        if created: _write_receipt(receipt,report)
    def identity():
        pid = _member(sw,'GetProcessID')
        if type(pid) is not int or pid != process_id: raise ValueError('Exact process changed')
        current = raw_part_identity(sw)
        check_document_target(current['path'],current['title'],expected_path=expected_document_path,required=True)
        if _file_hash(expected_document_path) != expected_source_sha256: raise ValueError('Saved source changed')
        if baseline is not None and current != baseline: raise ValueError('Read-only document identity changed')
        return current
    def events(active=True):
        state = session.summary(); report['messages']=state
        if (state.get('subscribed') is not True or state.get('active') is not active
                or (not active and state.get('disconnected') is not True)
                or any(state.get(k) for k in ('event_count','overflow','callback_errors',
                    'callback_error_count','subscription_error','disconnect_errors'))):
            raise ValueError('CAM events require stop')
    def guard():
        events(); files.check(); identity(); events()
    def read(obj,name,*args):
        guard(); report['last_native_getter']=name
        result = _member(obj,name,*args); guard(); return result
    def sw_read(obj,name):
        guard(); report['last_native_getter']='IModelDoc2.'+name
        result=call(obj,name); guard(); return result
    def typed(obj,name):
        guard(); result=_typed(obj,name,typelib_path); guard(); return result
    try:
        validate_unit_scope_request(process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,receipt_path=receipt_path,message_policy=message_policy)
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        baseline=identity(); report['document_before']=baseline
        if baseline['needs_save'] is not False: raise ValueError('Clean saved part required for pinned unit scope')
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        identity();session=CamMessageSession(app,typelib_path)
        with _CaptureReadFiles(expected_document_path) as files:
            with session:
                raw=read(app,'IGetActiveDoc');doc=typed(raw,'ICWDoc3')
                kind=read(doc,'GetDocType')
                if type(kind) is not int or kind!=1: raise ValueError('CAM part required')
                part=typed(raw,'ICWPartDoc');machine=typed(read(part,'IGetMachine'),'ICWMachine')
                kind=read(machine,'MachType')
                if type(kind) is not int or kind!=1: raise ValueError('MILL machine required')
                for index in range(2):
                    report['phase']='scope_read_'+str(index+1);persist();guard()
                    row=read_document_cam_unit_scope(sw.ActiveDoc,app,sw_read=sw_read,cam_read=read)
                    report['scope_reads'].append(row);persist()
                if report['scope_reads'][0]!=report['scope_reads'][1]: raise ValueError('Unit scope changed between reads')
                report['raw_readback_stable']=True;report['document_after']=identity();persist()
            events(active=False)
            report['document_after_cleanup']=identity()
        report.update(status='observed',phase='finished',metric_document_scope_observed=
            report['scope_reads'][0]['metric_document_scope_observed'])
    except Exception as exc:
        report.update(status='error',failed_phase=report['phase'],phase='finished',
                      issue=_error(exc),raw_readback_stable=False)
    finally:
        if session is not None: report['messages']=session.summary()
        try: persist()
        except Exception as exc: report.update(status='error',receipt_write_error=_error(exc),raw_readback_stable=False)
    return report