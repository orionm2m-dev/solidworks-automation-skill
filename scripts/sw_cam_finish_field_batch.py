"""Read the fifteen direct finish fields in one retained, read-only scope.

Entry and exit keep the existing evidence, process, document and binding checks.
Each native getter still checks events. No owner or data escapes a failed scope.
This helper does not authorize a setter, generation, save or automatic replay.
"""
from math import isfinite
from pathlib import Path
import re

from scripts import sw_cam_pocket_finish_apply as finish
from scripts import sw_cam_pocket_pair_read as pocket
from scripts import sw_cam_read_progress_journal as progress
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_rough_firstcut import require

SCOPE = 'BOUNDED_FINISH_DIRECT_FIELDS_READ_V1'
MAX_CALLS = 128
INTERFACES = frozenset({'ICWOperation', 'ICWMillOperation',
    'ICWDispatchCollection', 'ICWFinishMillOp', 'ICWFinishMillOp2',
    'ICWFinishMillOp3', 'ICWLeadInOut'})
GETTERS = frozenset(spec[2] for spec in finish.FIELDS) | {
    'GetCWObjectFromID', 'GetCWObjectID', 'Suppressed', 'IGetAllFeatures',
    'OpernType', 'Count', 'Item', 'IGetLeadin', 'IGetLeadout'}


class FinishFieldReadBatch(pocket.PocketReadBatch):
    def read(self, obj, name, *args):
        self.reject(name in GETTERS, 'Getter outside direct finish field scope')
        for arg in args:
            self.reject(type(arg) is int or id(arg) in self._known_objects,
                        'Argument outside retained finish graph')
        return self.observed(obj, 'getter', name, lambda: _member(obj, name, *args))

    def typed(self, obj, name):
        try:
            self.reject(name in INTERFACES, 'Interface outside direct finish field scope')
            cls = finish.interface_class(name, self.typelib_path, self.generated_pin)
            def query():
                value = obj.QueryInterface(cls)
                require(value is not None and bool(value) and isinstance(value, cls),
                        'Exact non-null finish interface required')
                return value
            return self.observed(obj, 'qi', name, query)
        except BaseException:
            self._invalid = True
            self._completed = False
            raise

    def sw_typed(self, *args):
        self.reject(False, 'SW association query outside direct finish field scope')

    def plane(self, *args):
        self.reject(False, 'Plane query outside direct finish field scope')

    def feature_dispatch(self, *args):
        self.reject(False, 'Dispatch conversion outside direct finish field scope')


def checked_value(spec, value):
    """Preserve native scalars, flags and tuple order without unit conversion."""
    value = list(value) if type(value) is tuple else value
    mode = spec[4]
    finite = lambda v: type(v) is float and isfinite(v)
    if mode == 'depth_pair':
        valid = (type(value) is list and len(value) == 2
                 and finite(value[0]) and type(value[1]) is bool)
    elif mode == 'pair':
        valid = (type(value) is list and len(value) == 3
                 and finite(value[0]) and type(value[1]) is bool and finite(value[2]))
    elif type(spec[6]) is bool:
        valid = type(value) is bool
    else:
        valid = finite(value)
    require(valid, 'Direct finish field has an unexpected native scalar shape: ' + spec[0])
    return value


def raw_observation(value):
    row = dict(python_type=type(value).__name__, value_recorded=False)
    if value is None or type(value) is bool:
        row.update(value=value, value_recorded=True)
    elif type(value) is int and -(2**64) < value < 2**64:
        row.update(value=value, value_recorded=True)
    elif type(value) is float:
        if isfinite(value):row.update(value=value, value_recorded=True)
        else:row['nonfinite'] = 'nan' if value != value else ('positive_infinity' if value > 0 else 'negative_infinity')
    elif type(value) is str and len(value) <= 128:
        row.update(value=value, value_recorded=True)
    elif type(value) in (tuple, list) and len(value) <= 4:
        items = [raw_observation(v) if type(v) in (type(None),bool,int,float,str) else
                 dict(python_type=type(v).__name__,value_recorded=False) for v in value]
        row['items'] = items
        if all(v['value_recorded'] for v in items):
            row.update(value=[v['value'] for v in items], value_recorded=True)
    return row


def read_cached_fields(batch, operation, feature, *, diagnostic):
    """Acquire each exact owner once within the already active read scope."""
    owners = {name: batch.typed(operation, name) for name in
              ('ICWFinishMillOp', 'ICWFinishMillOp2', 'ICWFinishMillOp3')}
    for side, getter in (('lead_in', 'IGetLeadin'), ('lead_out', 'IGetLeadout')):
        raw = batch.read(owners['ICWFinishMillOp'], getter, feature)
        require(raw is not None and bool(raw), 'Non-null feature-specific lead required')
        owners[side] = batch.typed(raw, 'ICWLeadInOut')
    result = {}
    for spec in finish.FIELDS:
        args = [feature] if spec[4] == 'feature' else []
        value = batch.read(owners[spec[1]], spec[2], *args)
        # Record the actual result before shape/recipe validation can reject it.
        diagnostic.setdefault('raw_fields', {})[spec[0]] = raw_observation(value)
        result[spec[0]] = checked_value(spec, value)
    require(len(result) == 15, 'Exact fifteen-field finish contract required')
    return result


def read_fields(backend, label):
    """Use an existing owned NativeBackend; return only after both boundaries.

    Caller must pin this module in its live dependency closure before use.
    Existing mutation guards and action journals remain separate and unchanged.
    """
    require(type(label) is str and re.fullmatch('[A-Za-z0-9_]{1,48}', label),
            'Bounded field-read phase label required')
    own = finish.common._key(__file__)
    require(any(finish.common._key(pin['path']) == own
                and pin['sha256'] == finish._file_hash(__file__)
                for pin in backend.loaded['pins']), 'Field reader must be a pinned live dependency')
    with backend.ctx.guard() as guard:
        operation, feature = backend.target(guard, 144)
    doc = backend.native['doc']
    state = dict(member='', returned=False, read_index=0)
    diagnostic = dict(scope=SCOPE, label=label, complete=False,
                      operation_native_id=144, feature_native_id=79)
    backend.report.setdefault('direct_field_batches', []).append(diagnostic)
    path = Path(backend.args['progress_path'])
    path = path.with_name(path.stem + '.' + label + '_direct_fields.json')
    protected = [backend.args['expected_document_path'], backend.args['receipt_path']]
    protected += [pin['path'] for pin in backend.loaded['pins']]
    batch = None
    def binding():
        # Reuse the operation type, suppression and feature-link checks of
        # ordinary per-field reads. Also verify the original retained handles.
        backend.target(batch, 144)
        require(_object_id(doc, operation, batch.read) == 144
                and _object_id(doc, feature, batch.read) == 79,
                'Retained finish operation or feature binding changed')
    try:
        with progress.ReadProgressJournal(full_persist=backend.persist,
                progress_path=path, describe=lambda: dict(state, phase=label),
                max_updates=MAX_CALLS * 2 + 4, protected_paths=protected) as journal:
            batch = FinishFieldReadBatch(backend.sw, backend.typelib_path,
                generated_pin=backend.loaded['generated_pin'],
                process_id=backend.args['process_id'],
                expected_document=backend.ctx.identity(),
                source_sha256=backend.ctx.args['expected_source_sha256'],
                evidence_pins=backend.loaded['pins'], verify_evidence=backend.ctx.files,
                verify_owned_process=backend.ctx.owned, check_events=backend.events,
                retained_objects=(doc, operation, feature), verify_retained_binding=binding,
                max_native_calls=MAX_CALLS, progress=journal.read, progress_state=state)
            with batch:
                values = read_cached_fields(batch, operation, feature, diagnostic=diagnostic)
            batch.require_complete()
            journal.complete()
        diagnostic.update(complete=True, field_count=len(values))
        return values
    finally:
        if batch is not None:
            diagnostic['batch'] = batch.summary()
        backend.persist()



def inspect_inputs(request):
    """Validate an interrupted, non-pending configuration without retrying it."""
    from copy import deepcopy
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
    from scripts.sw_cam_turn_tool import _digest
    fields = {'process_id', 'expected_document_path', 'expected_source_sha256',
        'addin_clsid', 'receipt_path', 'progress_path', 'failed_receipt_path',
        'failed_receipt_sha256', 'module_sha256'}
    require(type(request) is dict and set(request) == {'action', 'params'}
            and request['action'] == 'inspect_partial_finish_fields',
            'Explicit read-only inspection required')
    p = request['params']
    require(type(p) is dict and set(p) == fields, 'Exact field-inspection parameters required')
    require(type(p['process_id']) is int and 0 < p['process_id'] < 2**32, 'Owned PID required')
    for key, value in p.items():
        if key.endswith('path'):
            require(type(value) is str and Path(value).is_absolute(), 'Absolute path required')
        if key.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'Exact SHA required')
    require(p['module_sha256'] == finish._file_hash(__file__), 'Field reader module differs')
    require(type(p['addin_clsid']) is str and re.fullmatch(
        r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', p['addin_clsid']),
        'Exact CAM CLSID required')
    for key in ('receipt_path', 'progress_path'):
        path = Path(p[key])
        require(path.parent.is_dir() and not path.exists() and not path.is_symlink(),
                'Fresh inspection output required')
    require(finish.common._key(p['receipt_path']) != finish.common._key(p['progress_path']),
            'Inspection outputs alias')
    r, failed_pin = read_pin(p['failed_receipt_path'], p['failed_receipt_sha256'])
    require(r.get('scope') == 'PARTIAL_POCKET_FINISH_CONTINUATION_V1'
        and r.get('status') == 'uncertain' and r.get('phase') == 'finished'
        and r.get('failed_phase') == 'field:bottom_finish'
        and r.get('phase_proofs_verified') is True and r.get('model_saved') is False
        and r.get('partial_state_readback_verified') is True
        and r.get('configuration_readback_verified') is False,
        'Exact interrupted finish configuration required')
    require(set(r['actions']) == {'field:side_step', 'field:override_previous', 'field:bottom_finish'}
        and all(r[k] is False for k in finish.FORBIDDEN), 'Unexpected action or forbidden operation')
    for key, action in r['actions'].items():
        require(action.get('attempted') is True and action.get('returned') is True
            and action.get('pending') is False and action.get('native_return_type') == 'int'
            and type(action.get('native_return_value')) is int and action['native_return_value'] == 0,
            'Pending or failed native dispatch cannot be inspected as this case')
        if key != 'field:bottom_finish':
            require(action.get('readback_verified') is True, 'Confirmed prefix required')
    require(r['actions']['field:bottom_finish'].get('readback_verified') is not True
        and not any(k in r for k in ('generated', 'final', 'save_stage', 'saved_source_sha256')),
        'Unknown bottom result only; generation or Save forbids this reader')
    clean_events(r)
    require(r['process_id'] == p['process_id']
        and finish.common._key(r['source_path']) == finish.common._key(p['expected_document_path'])
        and r['initial_source_sha256'] == p['expected_source_sha256'] == finish._file_hash(p['expected_document_path']),
        'Interrupted source/process differs')
    finish.common._check(r['live_pins'])
    finish.common._check(r['offline_proof_pins'])
    finish.common._check(r['bootstrap_export_pins'])
    loaded = deepcopy(r['loaded_context_before'])
    finish.verify_route(loaded, r['reconciled']['state'], assigned=True, generated=False)
    loaded['state'] = deepcopy(r['reconciled']['state'])
    loaded['state']['document'] = deepcopy(r['current_document'])
    retired = [pin for pin in r['live_pins'] if Path(pin['path']).name == 'sw_cam_pocket_finish_continuation.py']
    require(len(retired) == 1 and retired[0]['sha256'] == r['module_pin']['sha256'],
            'One unused completed continuation writer required')
    loaded['pins'] = finish.common._merge([pin for pin in r['live_pins'] if pin not in retired],
                                         [finish.common._pin(__file__)])
    require(len(loaded['pins']) <= 64, 'Bounded field-reader live closure required')
    loaded['offline_export_proof_pins'] = finish.common._merge(
        r['offline_proof_pins'], retired, [failed_pin])
    loaded['current_context_sha256'] = _digest(finish.group.current_projection(loaded))
    return deepcopy(p), loaded, failed_pin


def run_inspection(sw, clsid, typelib, *, params, loaded, failed_pin):
    from copy import deepcopy
    from scripts.sw_cam_generation import _write_receipt
    from scripts.sw_cam import _error
    report = dict(schema_version=1, scope=SCOPE, status='reading', phase='binding',
        read_only=True, mutation_authority=False, setter_attempted=False,
        GTP_attempted=False, model_saved=False, automatic_replay=False,
        process_id=params['process_id'], source_path=params['expected_document_path'],
        source_sha256=params['expected_source_sha256'], failed_receipt_pin=failed_pin,
        module_pin=finish.common._pin(__file__), readback_verified=False,
        phase_proofs_verified=False, live_pins=deepcopy(loaded['pins']),
        offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']))
    backend = None
    def persist(): _write_receipt(params['receipt_path'], report)
    _write_receipt(params['receipt_path'], report, create=True)
    try:
        backend = finish.NativeBackend(loaded, params, sw, clsid, typelib, report, persist)
        backend.start()
        report['before_document'] = backend.ctx.identity()
        report['before_tool'] = backend.current_tool()
        require(finish.group.exact(report['before_tool'], finish.wanted_assignment(loaded)),
                'Saved neck-tool assignment changed')
        report['phase'] = 'direct_fields'; persist()
        report['fields'] = read_fields(backend, 'inspect')
        report['field_python_types'] = {key:type(value).__name__ for key,value in report['fields'].items()}
        report['matches_requested_value'] = {spec[0]:finish.group.exact(report['fields'][spec[0]], spec[6])
                                              for spec in finish.FIELDS}
        report['after_document'] = backend.ctx.identity()
        require(report['before_document'] == report['after_document'] == loaded['state']['document'],
                'Read-only inspection changed document identity')
        finish.common._check(loaded['offline_export_proof_pins'])
        finish.common._check(loaded['bootstrap_export_pins'])
        backend.boundary()
        report.update(status='observed', phase='finished', readback_verified=True, phase_proofs_verified=True)
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], phase='finished',
                      issue=_error(exc), readback_verified=False)
    finally:
        if backend is not None:
            try: backend.close()
            except Exception as exc:
                report.update(status='error', cleanup_issue=_error(exc), readback_verified=False)
        persist()
    return report


def dispatch_request(request, *, validate_only=False):
    p, loaded, failed_pin = inspect_inputs(request)
    registration = finish.common.discover_export_registration(loaded, p['addin_clsid'])
    typelib = str(Path(registration['addin_path']).parent / 'camworks.tlb')
    audit = finish.audit_recipe(typelib, loaded['generated_pin'])
    if validate_only:
        return dict(status='validated_offline', native_called=False, live_pin_count=len(loaded['pins']),
                    direct_field_count=15, interface_audit=audit, mutation_authority=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=p['process_id']):
        finish.common._check(loaded['pins'])
        finish.common._check(loaded['offline_export_proof_pins'])
        sw, _ = connect_solidworks(process_id=p['process_id'], launch_new_instance=False, wait_seconds=1)
        return run_inspection(sw, registration['clsid'], typelib,
                              params=p, loaded=loaded, failed_pin=failed_pin)


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(argv)
    result = dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),
                              validate_only=args.validate_only)
    print(json.dumps({key:result.get(key) for key in
        ('status','phase','readback_verified','fields','field_python_types','issue','native_called')},
        ensure_ascii=False))
    return 0 if result.get('status') == 'validated_offline' or result.get('readback_verified') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())

