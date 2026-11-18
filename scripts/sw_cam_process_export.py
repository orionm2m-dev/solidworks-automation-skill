"""Export one current saved MILL process archive; no import or model changes."""
from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
import hashlib
from scripts import sw_cam_mill_current_compound_read as current
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_comtypes import _interface_class, _INTERFACES
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import check_document_target, solidworks_operation_lock

SCOPE = 'MILL_CURRENT_SAVED_PROCESS_EXPORT_V1'
KEYS = {'process_id','expected_process_create_time','expected_document_path',
        'expected_source_sha256','expected_feature_native_id',
        'expected_feature_setup_native_id','expected_operation_setup_native_id',
        'expected_operation_native_ids','expected_generated_operation_count',
        'expected_total_record_count','output_path','receipt_path',
        'attempt_registry_path','provenance_pins','qualification_only','message_policy'}
MAX_BYTES = 128 * 1024 * 1024


def require(value, message):
    if not value:
        raise ValueError(message)


def reader_values(v):
    names = KEYS - {'output_path','receipt_path','attempt_registry_path','provenance_pins'}
    values = {k: deepcopy(v[k]) for k in names}
    values.update(read_mode='current_saved', observation='three_step_profile',
        parameters_authority_receipt_path=None, parameters_authority_receipt_sha256=None,
        parameter_operation_native_ids=None)
    return values


def fresh_archive(value):
    require(type(value) is str, 'Explicit process archive path required')
    p = Path(value)
    require(p.is_absolute() and p.suffix.lower() == '.prtcam' and len(str(p)) < 240
        and '..' not in p.parts and 1 <= len(p.name) <= 100
        and not any(c in p.name for c in '<>:"/\\|?*\x00')
        and p.drive and not p.drive.startswith('\\')
        and not p.exists() and not p.parent.exists()
        and not p.is_symlink() and not p.parent.is_symlink()
        and p.parent.parent.is_dir() and not str(p.resolve()).startswith('\\\\'),
        'Fresh local .prtcam in a new exclusive directory required')
    return p


def validate(v):
    require(type(v) is dict and set(v) == KEYS, 'Exact process export fields required')
    current.validate(reader_values(v))
    source = Path(v['expected_document_path'])
    require(source.is_file() and not source.is_symlink()
        and _file_hash(source) == v['expected_source_sha256'], 'Exact saved source bytes required')
    output = fresh_archive(v['output_path'])
    receipt = Path(v['receipt_path'])
    require(receipt.is_absolute() and receipt.suffix.lower() == '.json'
        and receipt.parent.is_dir() and not receipt.exists()
        and not receipt.is_symlink(), 'Fresh absolute JSON receipt required')
    directory = Path(v['attempt_registry_path'])
    require(directory.is_absolute() and directory.is_dir() and not directory.is_symlink(),
        'Existing absolute attempt registry required')
    require(type(v['provenance_pins']) is list and len(v['provenance_pins']) <= 4,
        'At most four explicit provenance receipts allowed')
    pins = []
    for row in v['provenance_pins']:
        require(type(row) is dict and set(row) == {'path','sha256'}, 'Exact provenance file pin required')
        _, actual = read_pin(row['path'], row['sha256'])
        pins.append(actual)
    implementation = dict(path=str(Path(__file__).resolve()), sha256=_file_hash(__file__))
    pins.append(implementation)
    marker = directory / ('process_export_' + _digest(dict(scope=SCOPE,
        source=str(source.resolve()).casefold(), source_sha256=v['expected_source_sha256'])) + '.json')
    require(not marker.exists() and not marker.is_symlink(), 'Prior process export attempt exists; no replay')
    protected = {source.resolve()} | {Path(p['path']).resolve() for p in pins}
    destinations = [receipt, marker, output]
    require(len({p.resolve() for p in destinations}) == len(destinations)
        and not protected.intersection(p.resolve() for p in destinations),
        'Export outputs alias source or evidence')
    require(not any(p.resolve().parent == output.parent.resolve() for p in [receipt, marker]),
        'Only the archive may occupy its exclusive directory')
    return dict(source=source, output=output, receipt=receipt, marker=marker, pins=pins)


def preflight(tlb):
    from ctypes import HRESULT
    from comtypes import BSTR
    current._abi(tlb)
    cls = _interface_class('ICWApp4', tlb)
    require(str(cls._iid_).upper() == _INTERFACES['ICWApp4'].upper(), 'Exact ICWApp4 IID required')
    methods = [m for m in cls._methods_ if m.name == 'ExportCAMData']
    require(len(methods) == 1, 'One declared ExportCAMData required')
    m = methods[0]
    require(m.restype is HRESULT and m.idlflags[0] == 59 and m.argtypes == (BSTR,)
        and tuple(p[0] for p in m.paramflags) == (1,)
        and not any(x in m.idlflags for x in ('propget','propput','propputref')),
        'Exact HRESULT ExportCAMData(BSTR) DISP59 ABI required')
    return dict(interface='ICWApp4', method='ExportCAMData', dispid=59, native_calls=0)


class CurrentExportContext:
    """The existing current-source compound reader inside one event/owner scope."""
    def __init__(self, sw, clsid, tlb, v, loaded, report, persist, runtime_check):
        self.sw, self.clsid, self.tlb = sw, clsid, tlb
        self.v, self.loaded, self.report = v, loaded, report
        self.persist, self.runtime_check = persist, runtime_check
        self.stack = ExitStack()
        self.session = None
        self.initial = None

    def verify_files(self):
        for pin in self.loaded['pins']:
            require(_file_hash(pin['path']) == pin['sha256'], 'Provenance or export implementation changed')

    def identity(self):
        self.runtime_check()
        v = self.v
        p = _process_identity(v['process_id'])
        require(p.get('alive') is True and p.get('process_id') == v['process_id']
            and p.get('create_time') == v['expected_process_create_time']
            and Path(p.get('executable','')).name.casefold() == 'sldworks.exe',
            'Exact selected process lifetime changed')
        pid = _member(self.sw, 'GetProcessID')
        require(type(pid) is int and pid == v['process_id'], 'Selected PID changed')
        doc = document_snapshot(self.sw)
        require(type(doc) is dict and type(doc.get('type')) is int
            and doc['type'] == 1 and doc.get('needs_save') is False, 'Clean saved part required')
        check_document_target(doc['path'], doc['title'], expected_path=v['expected_document_path'], required=True)
        require(_file_hash(v['expected_document_path']) == v['expected_source_sha256'], 'Saved source bytes changed')
        self.verify_files()
        return doc

    def check(self):
        s = self.session.summary()
        self.report['messages'] = s
        require(s.get('active') is True and s.get('subscribed') is True
            and not any(s.get(k) for k in current._EVENT_ERRORS), 'CAM event requires stop')

    def boundary(self):
        self.check()
        require(self.identity() == self.initial, 'Current document identity changed')
        self.check()

    def start(self):
        try:
            self.stack.enter_context(solidworks_operation_lock(timeout_seconds=1, process_id=self.v['process_id']))
            self.initial = self.identity()
            addin = _member(self.sw, 'GetAddInObject', self.clsid)
            require(addin is not None, 'CAM must already be loaded')
            self.app = _typed(_member(addin, 'GetCWApp'), 'ICWApp4', self.tlb)
            require(self.identity() == self.initial, 'Identity changed during bootstrap')
            self.session = CamMessageSession(self.app, self.tlb)
            self.stack.enter_context(self.session)
            self.boundary()
        except BaseException:
            self.stack.close()
            raise

    def read(self, obj, name, *args):
        self.check()
        self.report['phase'] = name
        self.report['native_read_count'] += 1
        require(self.report['native_read_count'] <= 8192, 'Bounded export reader budget exceeded')
        value = _member(obj, name, *args)
        self.check()
        return value

    def typed(self, raw, name):
        self.check()
        result = _typed(raw, name, self.tlb)
        require(result is not None, 'Missing declared interface: ' + name)
        self.check()
        return result

    def capture(self, label):
        state = {}
        self.report[label] = state
        self.report['phase'] = label
        self.persist()
        self.boundary()
        try:
            self.native = current._capture(self.app, self.tlb, self.read, self.typed,
                state, reader_values(self.v), self.boundary)
            state['document'] = deepcopy(self.initial)
            self.boundary()
            return state
        finally:
            self.persist()

    def guard(self):
        self.boundary()
        return ScopedCamDispatchGuard(self.sw, self.tlb, process_id=self.v['process_id'],
            expected_document=self.initial, source_sha256=self.v['expected_source_sha256'],
            evidence_pins=self.loaded['pins'], verify_evidence=self.verify_files,
            verify_owned_process=self.boundary, check_events=self.check)

    def close(self):
        self.stack.close()
        if self.session is not None:
            self.report['messages'] = self.session.summary()
            clean_events(self.report)
        if self.initial is not None:
            require(self.identity() == self.initial, 'Document changed after event cleanup')


def revoke_runtime(report, error):
    report.update(status='uncertain' if report.get('dispatch_claimed') else 'error',
        phase='finished', runtime_unchanged=False, readback_verified=False,
        export_verified=False, runtime_error=_error(error))
    _write_receipt(Path(report['receipt_path']), report)
    return report


def run_export(sw, clsid, tlb, *, runtime_check, _context_factory=CurrentExportContext,
        _validate=validate, _preflight=preflight, **v):
    loaded = _validate(v)
    runtime_check()
    abi = _preflight(tlb)
    r = dict(scope=SCOPE, status='running', phase='preflight', request=deepcopy(v),
        receipt_path=str(loaded['receipt']), marker_path=str(loaded['marker']),
        source_before_sha256=v['expected_source_sha256'], provenance_pins=deepcopy(v['provenance_pins']),
        provenance_is_history_only=True, native_interface_audit=abi, native_read_count=0,
        dispatch_claimed=False, native_call_attempted=False, native_call_returned=False,
        native_dispatch_pending=False, mutation_attempted=False, model_saved=False,
        GTP_attempted=False, GOP_attempted=False, AFR_attempted=False,
        import_attempted=False, rebuild_attempted=False, TechDB_setter_attempted=False,
        automatic_replay=False, export_verified=False, readback_verified=False,
        runtime_unchanged=False, source_unchanged=False, stock_included=False,
        archive_contents_verified=False, archive_restore_verified=False,
        CAM_migration_verified=False, cl_coordinates_compared=False,
        full_hidden_geometry_preservation_verified=False, production_qualified=False)
    def persist():
        _write_receipt(loaded['receipt'], r)
    _write_receipt(loaded['receipt'], r, create=True)
    c = None
    guard = None
    try:
        c = _context_factory(sw, clsid, tlb, v, loaded, r, persist, runtime_check)
        c.start()
        before = c.capture('before')
        require(before.get('capture_complete') is True, 'Complete pre-export capture required')
        output = loaded['output']
        canonical = str(output.resolve())
        with c.guard() as guard:
            target = guard.typed(c.app, 'ICWApp4')
            output.parent.mkdir()
            require(not output.parent.is_symlink() and str(output.resolve()) == canonical
                and not output.exists(), 'Exclusive process archive path changed')
            r['output_directory_created'] = True
            persist()
            def pending():
                r.update(dispatch_claimed=True, native_dispatch_pending=True, phase='ExportCAMData_pending')
                marker = dict(scope=SCOPE, source_sha256=v['expected_source_sha256'],
                    receipt_path=str(loaded['receipt']), output_path=str(output), automatic_replay=False)
                _write_receipt(loaded['marker'], marker, create=True)
                persist()
            def invoke():
                r.update(native_call_attempted=True, phase='ExportCAMData')
                persist()
                value = _member(target, 'ExportCAMData', str(output))
                r.update(native_call_returned=True, native_dispatch_pending=False,
                    native_return_type=type(value).__name__,
                    native_return_value=value if value is None or type(value) in (bool,int,float,str) else None,
                    phase='ExportCAMData_returned')
                persist()
                return value
            result = guard.dispatch_once(invoke, persist_pending=pending)
        r['dispatch_guard'] = guard.summary()
        require(type(result) is int and result == 0, 'Exact ExportCAMData HRESULT int0 required')
        after = c.capture('after')
        require(after.get('capture_complete') is True and before == after,
            'Full captured current CAM state changed during process export')
        c.boundary()
        require(output.is_file() and not output.is_symlink() and not output.parent.is_symlink()
            and str(output.resolve()) == canonical and 0 < output.stat().st_size <= MAX_BYTES
            and sorted(p.name for p in output.parent.iterdir()) == [output.name],
            'One bounded nonempty process archive required')
        raw = output.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        require(_file_hash(output) == digest, 'Process archive changed during final read')
        r['output'] = dict(path=str(output), sha256=digest, bytes=len(raw))
        c.close()
        runtime_check()
        require(output.stat().st_size == len(raw) and _file_hash(output) == digest,
            'Process archive changed during cleanup')
        require(_file_hash(v['expected_document_path']) == v['expected_source_sha256'], 'Source changed after export cleanup')
        r.update(status='review_required', phase='finished', export_verified=True,
            readback_verified=True, runtime_unchanged=True, source_unchanged=True,
            source_after_sha256=v['expected_source_sha256'],
            reason='NATIVE_ARCHIVE_OUTPUT_ONLY_NO_IMPORT_REBUILD_OR_MIGRATION_QUALIFICATION')
    except Exception as error:
        if guard is not None:
            r['dispatch_guard'] = guard.summary()
        r.update(status='uncertain' if r['dispatch_claimed'] else 'error', failed_phase=r['phase'],
            phase='finished', issue=_error(error), export_verified=False, readback_verified=False)
        try:
            if c is not None:
                c.close()
        except Exception as cleanup:
            r['cleanup_error'] = _error(cleanup)
    persist()
    return r
