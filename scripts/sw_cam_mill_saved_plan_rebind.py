"""Explicit read-only rebind of an unchanged saved MILL plan to one owned session."""
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from pathlib import Path
import math

from scripts.sw_cam import _member, _error
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request, _same_inventory
from scripts.sw_cam_mill_route_context import integer
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_stock_export_evidence import _require
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target
from scripts.sw_executable_launch import _process_identity, _same_path

SCOPE = 'MILL_SAVED_PLAN_SESSION_REBIND_V1'
APPENDED_SCOPE = 'MILL_APPEND_OPERATIONS_V1'
_historical_pid = ContextVar('saved_mill_historical_pid', default=None)


@contextmanager
def _historical_validation(process_id):
    """Validate recorded history without requiring its retired process to exist."""
    token = _historical_pid.set(integer(process_id, 'historical process ID', 1))
    try:
        yield
    finally:
        _historical_pid.reset(token)


def _is_appended(evidence):
    return evidence.data.get('scope') == APPENDED_SCOPE


def _saved_receipt_from_summary(summary):
    if summary.get('scope') == 'MILL_APPENDED_PLAN_CONTINUATION_V1':
        return summary.get('saved_append_receipt', {})
    return summary.get('saved_plan_receipt', {})


def _verify_compound_details(details, evidence):
    if _is_appended(evidence):
        expected = evidence.data['saved_details']
        for key in ('three_step_profile', 'strategy'):
            _require(details.get(key) == expected[key],
                     'Rebound compound profile differs: ' + key)


def _read_session_details(evidence, state, native, read, typed, diagnostic, boundary):
    read_selected_operation_tool_details(state, native, read, typed, diagnostic,
        feature_native_id=evidence.selected['feature_native_id'], boundary=boundary)
    if _is_appended(evidence):
        from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
        args = evidence.data['request']
        for mode in ('three_step_profile', 'strategy'):
            read_compound_strategy(state, native, read, typed, diagnostic.setdefault(mode, {}),
                feature_id=args['target_feature_native_id'],
                owner_id=args['target_owner_setup_native_id'], step_count=3,
                expected_header=evidence.profile['header'], boundary=boundary, observation=mode)

FALSE_FLAGS = (
    'mutation_attempted', 'AFR_attempted', 'GOP_attempted', 'GTP_attempted',
    'model_saved', 'save_attempted', 'stock_edit_attempted', 'material_edit_attempted',
    'tool_assignment_attempted', 'TechDB_write_attempted', 'post_cleanup_CAM_getters',
    'full_inventory_verified', 'world_geometry_verified', 'units_verified',
    'physical_tool_identity_verified', 'holder_clearance_verified',
    'actual_incoming_WIP_verified', 'production_qualified',
)
TRUE_FLAGS = ('read_only', 'readback_verified', 'tools_readback_verified',
              'tool_geometry_read_complete', 'tool_profile_complete')


def _successful_read(data, scope):
    _require(data.get('scope') == scope and data.get('status') == 'review_required'
             and data.get('phase') == 'finished', 'Completed read-only evidence required')
    for key in TRUE_FLAGS:
        _require(data.get(key) is True, 'Complete read flag required: ' + key)
    for key in FALSE_FLAGS:
        _require(data.get(key) is False, 'Unexpected evidence flag: ' + key)
    _require(not any(key in data for key in ('issue', 'failed_phase', 'receipt_write_error')),
             'Failure evidence cannot anchor a rebind')
    clean_events(data)


def _full_details(details, evidence):
    _require(type(details) is dict
             and details.get('metadata_read_complete') is True
             and details.get('profile_complete') is True
             and details.get('generic_operation_context_unchanged') is True
             and details.get('canonical_state_changed') is False,
             'Complete full tool profiles with unchanged operation context required')
    items = details.get('items')
    _require(type(items) is list and len(items) == len(evidence.operation_ids),
             'Complete ordered shared-tool users required')
    _require([integer(row.get('operation_native_id'), 'operation ID', 1) for row in items]
             == evidence.operation_ids, 'Full-tool operation membership differs')
    fulls = []
    for row in items:
        full = row.get('full_tool')
        _require(type(full) is dict and full.get('geometry_read_complete') is True
                 and full.get('profile_complete') is True
                 and integer(full.get('tool_native_id'), 'tool ID', 1) == evidence.tool_id,
                 'Complete exact assigned tool required')
        fulls.append(full)
    _require(all(value == fulls[0] for value in fulls), 'Shared full-tool observations differ')
    return details


def load_complete_tool_anchor(path, sha, evidence, historical_process_id):
    from scripts.sw_cam_mill_saved_plan_tools import SCOPE as TOOL_SCOPE
    data, pin = read_pin(path, sha)
    if _is_appended(evidence):
        _require(pin == evidence.receipt_pin and data == evidence.data,
                 'Appended full-tool anchor must be the exact validated saved receipt')
        _require(data.get('process_id') == historical_process_id,
                 'Historical appended tool PID differs')
        details = deepcopy(data['saved_details']['selected_tool_details'])
        _full_details(details, evidence)
        return details, pin
    _successful_read(data, TOOL_SCOPE)
    _require(type(data.get('process_id')) is int
             and data['process_id'] == historical_process_id, 'Historical tool PID differs')
    _require(data.get('anchor') == evidence.summary(), 'Historical tool lineage differs')
    _require(data.get('saved_file_sha256') == evidence.data['saved_file_sha256'],
             'Historical tool source differs')
    for label in ('before', 'after'):
        evidence.verify(data[label])
        _full_details(data[label + '_tool_details'], evidence)
    _require(_same_inventory(data['before'], data['after'])
             and data['before_tool_details'] == data['after_tool_details'],
             'Historical tool captures disagree')
    _require(data.get('state_sha256') == _digest(data['before'])
             and data.get('tool_details_sha256') == _digest(data['before_tool_details']),
             'Historical tool digest differs')
    return deepcopy(data['before_tool_details']), pin


def load_owned_startup(path, sha, process_id):
    data, pin = read_pin(path, sha)
    _require(data.get('status') == 'ok' and data.get('phase') == 'connected'
             and data.get('launch_mode') == 'executable', 'Verified executable startup required')
    for key in ('launch_attempted', 'new_process_verified', 'user_control_verified'):
        _require(data.get(key) is True, 'Owned startup flag required: ' + key)
    _require(data.get('automatic_retry') is False and data.get('termination_attempted') is False,
             'Unexpected startup retry or termination')
    _require(type(data.get('process_id')) is int and data['process_id'] == process_id,
             'Owned startup PID differs')
    previous = data.get('known_process_ids_before')
    _require(type(previous) is list and process_id not in previous,
             'Startup did not prove a new process')
    identity = data.get('process_identity', {})
    _require(type(identity.get('process_id')) is int and identity['process_id'] == process_id
             and identity.get('alive') is True, 'Owned process identity differs')
    created = identity.get('create_time')
    _require(type(created) in (int, float) and math.isfinite(created) and created > 0,
             'Owned process creation time required')
    _require(type(identity.get('executable')) is str
             and _same_path(identity['executable'], data.get('executable', '')),
             'Owned executable identity differs')
    return deepcopy(identity), pin


class SessionEvidence:
    """Preserve historical data; carry explicit process/session evidence separately."""
    def __init__(self, original, tool_details, tool_pin, ownership, ownership_pin, process_id):
        self.historical_evidence = original
        self.data = original.data
        self.state = original.state
        self.selected = original.selected
        self.operation_ids = original.operation_ids
        self.tool_id = original.tool_id
        self.historical_process_id = original.data['process_id']
        self.bound_process_id = process_id
        self.baseline_tool_details = deepcopy(tool_details)
        self.ownership = deepcopy(ownership)
        self.extra_pins = [deepcopy(tool_pin), deepcopy(ownership_pin)]
        self.pins = deepcopy(original.pins) + deepcopy(self.extra_pins)
        self.rebind_pin = None
        if _is_appended(original):
            self.receipt_pin = deepcopy(original.receipt_pin)
            self.profile = deepcopy(original.profile)

    def historical_summary(self):
        return self.historical_evidence.summary()

    def check_files(self):
        self.historical_evidence.check_files()
        for pin in self.extra_pins:
            _, current = read_pin(pin['path'], pin['sha256'])
            _require(current == pin, 'Pinned tool, ownership or rebind evidence changed')

    def check_runtime_identity(self):
        retired = _historical_pid.get()
        if retired is not None:
            _require(self.bound_process_id == retired,
                     'Historical validation cannot cover a different owned process')
            return
        current = _process_identity(self.bound_process_id)
        _require(type(current.get('process_id')) is int
                 and current['process_id'] == self.bound_process_id
                 and current.get('alive') is True
                 and current.get('create_time') == self.ownership['create_time']
                 and _same_path(current.get('executable', ''), self.ownership['executable']),
                 'Owned process exited or PID was reused')

    def read_stock(self, *args):
        return self.historical_evidence.read_stock(*args)

    def verify(self, state):
        return self.historical_evidence.verify(state)

    def summary(self):
        return dict(scope=SCOPE, historical_summary=self.historical_summary(),
                    historical_process_id=self.historical_process_id,
                    bound_process_id=self.bound_process_id,
                    historical_tool_receipt=deepcopy(self.extra_pins[0]),
                    owned_startup_receipt=deepcopy(self.extra_pins[1]),
                    session_rebind_receipt=deepcopy(self.rebind_pin),
                    original_receipts_modified=False, full_inventory_verified=False,
                    world_geometry_verified=False, production_qualified=False)


def _load_baseline(*, process_id, previous_process_id, tool_receipt_path, tool_receipt_sha256,
                   owned_startup_receipt_path, owned_startup_receipt_sha256,
                   saved_plan_receipt_path, saved_plan_receipt_sha256, **scope):
    from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
    integer(process_id, 'new process ID', 1)
    integer(previous_process_id, 'historical process ID', 1)
    _require(process_id != previous_process_id, 'Explicit distinct new session required')
    with _historical_validation(previous_process_id):
        original = load_saved_plan_tools_evidence(
            saved_plan_receipt_path, saved_plan_receipt_sha256,
            process_id=previous_process_id, **scope)
    details, tool_pin = load_complete_tool_anchor(
        tool_receipt_path, tool_receipt_sha256, original, previous_process_id)
    ownership, ownership_pin = load_owned_startup(
        owned_startup_receipt_path, owned_startup_receipt_sha256, process_id)
    return SessionEvidence(original, details, tool_pin, ownership, ownership_pin, process_id)


def load_rebound_saved_plan_tools_evidence(path, sha, *, saved_plan_receipt_path,
                                          saved_plan_receipt_sha256, process_id, **scope):
    data, pin = read_pin(path, sha)
    _successful_read(data, SCOPE)
    _require(data.get('session_rebind_verified') is True
             and data.get('original_receipts_modified') is False,
             'Verified separate session rebind required')
    _require(type(data.get('process_id')) is int and data['process_id'] == process_id,
             'Rebind is for another current process')
    anchor = data.get('anchor', {})
    old = anchor.get('historical_summary', {})
    saved_pin = _saved_receipt_from_summary(old)
    supplied, actual_pin = read_pin(saved_plan_receipt_path, saved_plan_receipt_sha256)
    _require(saved_pin == actual_pin, 'Rebind original saved receipt differs')
    tool_pin = anchor.get('historical_tool_receipt', {})
    ownership_pin = anchor.get('owned_startup_receipt', {})
    evidence = _load_baseline(
        process_id=process_id, previous_process_id=data.get('previous_process_id'),
        saved_plan_receipt_path=saved_plan_receipt_path,
        saved_plan_receipt_sha256=saved_plan_receipt_sha256,
        tool_receipt_path=tool_pin['path'], tool_receipt_sha256=tool_pin['sha256'],
        owned_startup_receipt_path=ownership_pin['path'],
        owned_startup_receipt_sha256=ownership_pin['sha256'], **scope)
    _require(anchor == evidence.summary(), 'Rebind lineage changed')
    for label in ('before', 'after'):
        evidence.verify(data[label])
        _full_details(data[label + '_tool_details'], evidence)
        _require(data[label + '_tool_details'] == evidence.baseline_tool_details,
                 'Rebind tool profile differs from historical evidence')
        _verify_compound_details(data.get(label + '_compound_details', {}), evidence)
    _require(_same_inventory(data['before'], data['after'])
             and data.get('state_sha256') == _digest(data['before'])
             and data.get('tool_details_sha256') == _digest(data['before_tool_details'])
             and data.get('saved_file_sha256') == scope['expected_source_sha256'],
             'Rebind snapshots, source or digests differ')
    evidence.rebind_pin = deepcopy(pin)
    evidence.extra_pins.append(deepcopy(pin))
    evidence.pins.append(deepcopy(pin))
    evidence.check_files()
    return evidence


def verify_saved_plan_session(sw, clsid, typelib_path, *, process_id, previous_process_id,
        expected_document_path, expected_source_sha256,
        saved_plan_receipt_path, saved_plan_receipt_sha256,
        tool_receipt_path, tool_receipt_sha256,
        owned_startup_receipt_path, owned_startup_receipt_sha256,
        expected_feature_native_id, expected_operation_native_ids,
        expected_operation_setup_native_id, expected_tool_native_id,
        qualification_only, acknowledge_disposable_copy, receipt_path,
        message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(scope=SCOPE, status='error', phase='preflight', process_id=process_id,
                  previous_process_id=previous_process_id, read_only=True, may_continue=False,
                  session_rebind_verified=False, original_receipts_modified=False,
                  readback_verified=False, tools_readback_verified=False,
                  tool_geometry_read_complete=False, tool_profile_complete=False,
                  snapshot_diagnostics=[])
    report.update({key: False for key in FALSE_FLAGS})
    receipt = None
    created = False
    session = None
    anchor = None
    baseline = None

    def persist():
        if created:
            _write_receipt(receipt, report)

    def identity():
        pid = _member(sw, 'GetProcessID')
        _require(type(pid) is int and pid == process_id, 'Exact new process changed')
        anchor.check_runtime_identity()
        doc = raw_part_identity(sw)
        check_document_target(doc['path'], doc['title'],
                              expected_path=expected_document_path, required=True)
        _require(type(doc.get('type')) is int and doc['type'] == 1
                 and doc.get('needs_save') is False
                 and _file_hash(expected_document_path) == expected_source_sha256,
                 'Clean exact saved source changed')
        anchor.check_files()
        return doc

    def check(active=True):
        value = session.summary()
        report['messages'] = value
        if (value.get('subscribed') is not True
                or (active and value.get('active') is not True)
                or (not active and (value.get('active') is not False
                                    or value.get('disconnected') is not True))
                or any(value.get(k) for k in ('event_count', 'overflow', 'callback_errors',
                        'callback_error_count', 'subscription_error', 'disconnect_errors'))):
            raise ValueError('CAM event or transport requires stop')

    try:
        validate_inventory_request(process_id=process_id,
            expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,
            qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy,
            receipt_path=receipt_path, message_policy=message_policy)
        anchor = _load_baseline(
            process_id=process_id, previous_process_id=previous_process_id,
            expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,
            saved_plan_receipt_path=saved_plan_receipt_path,
            saved_plan_receipt_sha256=saved_plan_receipt_sha256,
            tool_receipt_path=tool_receipt_path, tool_receipt_sha256=tool_receipt_sha256,
            owned_startup_receipt_path=owned_startup_receipt_path,
            owned_startup_receipt_sha256=owned_startup_receipt_sha256,
            expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id)
        _require(all(Path(receipt_path).resolve() != Path(p['path']).resolve()
                     for p in anchor.pins), 'Output cannot overwrite historical evidence')
        receipt = Path(receipt_path)
        _write_receipt(receipt, report, create=True)
        created = True
        report['anchor'] = anchor.summary()
        baseline = identity()
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        _require(identity() == baseline, 'Identity changed acquiring event host')
        session = CamMessageSession(app, typelib_path)
        with session:
            for phase in ('before', 'after'):
                check()
                _require(identity() == baseline, 'Identity changed before capture')
                report['phase'] = phase
                diag = dict(phase=phase)
                report['snapshot_diagnostics'].append(diag)
                persist()
                state, _ = capture_selected_plan(
                    sw, clsid, typelib_path, expected_document_path, process_id=process_id,
                    expected_source_sha256=expected_source_sha256, evidence=anchor,
                    check=check, diagnostic=diag, progress=persist,
                    operation_details_reader=partial(_read_session_details, anchor))
                _require(state['document'] == baseline, 'Document changed during capture')
                anchor.verify(state)
                details = deepcopy(diag['operation_details']['selected_tool_details'])
                _full_details(details, anchor)
                _require(details == anchor.baseline_tool_details,
                         'Current full tool differs from historical saved readback')
                report[phase] = state
                report[phase + '_tool_details'] = details
                if _is_appended(anchor):
                    compound = {key: deepcopy(diag['operation_details'][key])
                                for key in ('three_step_profile', 'strategy')}
                    _verify_compound_details(compound, anchor)
                    report[phase + '_compound_details'] = compound
                persist()
                check()
            _require(_same_inventory(report['before'], report['after'])
                     and report['before_tool_details'] == report['after_tool_details'],
                     'New-session captures disagree')
        check(active=False)
        _require(identity() == baseline, 'Identity changed during event cleanup')
        report.update(status='review_required', phase='finished',
            session_rebind_verified=True, readback_verified=True, tools_readback_verified=True,
            tool_geometry_read_complete=True, tool_profile_complete=True,
            state_sha256=_digest(report['before']),
            tool_details_sha256=_digest(report['before_tool_details']),
            saved_file_sha256=expected_source_sha256,
            reason='UNCHANGED_SAVED_PLAN_AND_FULL_TOOLS_VERIFIED_IN_EXPLICIT_OWNED_SESSION')
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], phase='finished',
                      issue=_error(exc))
        for key in ('session_rebind_verified',) + TRUE_FLAGS[1:]:
            report[key] = False
    finally:
        if session is not None:
            report['messages'] = session.summary()
        try:
            persist()
        except Exception as exc:
            report.update(status='error', receipt_write_error=_error(exc))
            for key in ('session_rebind_verified',) + TRUE_FLAGS[1:]:
                report[key] = False
    return report
