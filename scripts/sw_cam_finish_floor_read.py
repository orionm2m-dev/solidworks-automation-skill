"""Read eighteen floor settings from one retained finish operation.

This reader observes existing state only. The no-direction StepOver pointer
getter uses caller-owned typed storage and strict metadata/HRESULT validation.
No setter, generation, save or automatic retry belongs to this module.
"""
from copy import deepcopy
from ctypes import byref, c_double, c_long, c_short, POINTER, HRESULT
from ctypes.wintypes import VARIANT_BOOL
from math import isfinite
from pathlib import Path
import re

from scripts import sw_cam_pocket_finish_apply as finish
from scripts import sw_cam_pocket_pair_read as pocket
from scripts import sw_cam_read_progress_journal as progress
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events

SCOPE = 'BOUNDED_FINISH_FLOOR_FIELDS_READ_V1'
MAX_CALLS = 128
BOOL_SENTINEL = 32767
INTERFACES = frozenset({'ICWOperation', 'ICWMillOperation', 'ICWDispatchCollection',
                        'ICWFinishMillOp', 'ICWFinishMillOp3'})
# key, exact interface, member, shape, DISPID; enum values stay raw.
FIELDS = (
    ('bottom_finish', 'ICWFinishMillOp', 'BottomFinOpt', 'bool', 22),
    ('bottom_method', 'ICWFinishMillOp', 'BottomFinMethod', 'long', 24),
    ('perimeter_pass_type', 'ICWFinishMillOp', 'PerimeterPassType', 'long', 23),
    ('stepover', 'ICWFinishMillOp', 'GetStepOver', 'owned_bool_double', 25),
    ('side_allowance', 'ICWFinishMillOp3', 'GetBottomFinishSideAllowance', 'double_bool', 33),
    ('feed_rate', 'ICWFinishMillOp3', 'GetBottomFinishFeedRate', 'double_bool', 35),
    ('bottom_first', 'ICWFinishMillOp3', 'BottomFirst', 'bool', 37),
    ('cut_angle', 'ICWFinishMillOp3', 'CutAngle', 'double', 32),
    ('entry_move', 'ICWFinishMillOp3', 'EntryMove', 'bool', 38),
    ('entry_length', 'ICWFinishMillOp3', 'GetEntryMoveLength', 'double_bool', 39),
    ('entry_angle', 'ICWFinishMillOp3', 'EntryAngle', 'double', 41),
    ('entry_ramp_height', 'ICWFinishMillOp3', 'EntryRampHeight', 'double', 42),
    ('entry_ramp_angle', 'ICWFinishMillOp3', 'GetBottomFinEntryRampAngle', 'double', 106),
    ('cnc_compensation', 'ICWFinishMillOp3', 'BottomFinishCNCCompensation', 'bool', 43),
    ('retract_move', 'ICWFinishMillOp3', 'RetractMove', 'bool', 44),
    ('retract_length', 'ICWFinishMillOp3', 'GetRetractLength', 'double_bool', 45),
    ('retract_angle', 'ICWFinishMillOp3', 'RetractAngle', 'double', 47),
    ('retract_ramp_height', 'ICWFinishMillOp3', 'RetractRampHeight', 'double', 48),
)
GETTERS = frozenset(v[2] for v in FIELDS if v[3] != 'owned_bool_double') | {
    'GetCWObjectFromID', 'GetCWObjectID', 'Suppressed', 'IGetAllFeatures',
    'OpernType', 'Count', 'Item'}
RAW_STEPOVER = '_ICWFinishMillOp__com_GetStepOver'


def audit_interfaces(typelib, generated_pin):
    """Resolve the installed generated classes; never connect to the app."""
    classes = {name:finish.interface_class(name, typelib, generated_pin)
               for name in sorted(INTERFACES)}
    rows = []
    for key, owner, name, kind, dispid in FIELDS:
        prop = not name.startswith('Get')
        declared = '_get_' + name if prop else name
        members = [m for m in classes[owner]._methods_ if m.name == declared]
        require(len(members) == 1, 'One exact floor getter declaration required: ' + name)
        spec = members[0]
        if kind == 'owned_bool_double':
            args, flags = (POINTER(VARIANT_BOOL), POINTER(c_double)), (0, 0)
        elif kind == 'double_bool':
            args, flags = (POINTER(c_double), POINTER(VARIANT_BOOL)), (2, 2)
        else:
            scalar = {'bool':VARIANT_BOOL, 'long':c_long, 'double':c_double}[kind]
            args, flags = (POINTER(scalar),), (10,)
        require(spec.restype is HRESULT and spec.argtypes == args
                and tuple(v[0] for v in spec.paramflags) == flags
                and int(spec.idlflags[0]) == dispid
                and ('propget' in spec.idlflags) is prop,
                'Exact floor getter ABI differs: ' + name)
        if kind == 'owned_bool_double':
            require(callable(getattr(classes[owner], RAW_STEPOVER, None)),
                    'Exact generated StepOver HRESULT wrapper required')
        rows.append(dict(key=key, interface=owner, member=declared, iid=str(classes[owner]._iid_),
                         dispid=dispid, argtypes=[v.__name__ for v in args], paramflags=list(flags)))
    return dict(all_resolved=True, native_calls=0, runtime_pointer_read_qualified=False, members=rows)


def raw_observation(value):
    row = dict(python_type=type(value).__name__, value_recorded=False)
    if value is None or type(value) is bool:
        row.update(value=value, value_recorded=True)
    elif type(value) is int and -(2**64) < value < 2**64:
        row.update(value=value, value_recorded=True)
    elif type(value) is float:
        if isfinite(value): row.update(value=value, value_recorded=True)
        else: row['nonfinite'] = 'nan' if value != value else ('positive_infinity' if value > 0 else 'negative_infinity')
    elif type(value) in (tuple, list) and len(value) <= 4:
        items = [raw_observation(v) if type(v) in (type(None), bool, int, float) else
                 dict(python_type=type(v).__name__, value_recorded=False) for v in value]
        row['items'] = items
        if all(v['value_recorded'] for v in items):
            row.update(value=[v['value'] for v in items], value_recorded=True)
    return row


def step_over_value(owner, diagnostic):
    """One exact raw getter; initialized typed buffers remain alive until return."""
    require(type(diagnostic) is dict and not diagnostic, 'Fresh StepOver diagnostic required')
    percent = VARIANT_BOOL()
    c_short.from_buffer(percent).value = BOOL_SENTINEL
    amount = c_double(float('nan'))
    diagnostic.update(member='GetStepOver', attempted=True, returned=False,
                      caller_owned=True, automatic_retry=False, outputs_validated=False,
                      initial_boolean_short=BOOL_SENTINEL, initial_double='nan')
    try:
        status = getattr(owner, RAW_STEPOVER)(byref(percent), byref(amount))
    except Exception as exc:
        diagnostic.update(exception_type=type(exc).__name__)
        for name in ('hresult', 'winerror'):
            code = getattr(exc, name, None)
            if type(code) is int: diagnostic['exception_' + name] = code
        raise
    else:
        diagnostic.update(returned=True, hresult=raw_observation(status))
    finally:
        # A raw HRESULT wrapper can raise before returning a Python status.
        # Preserve caller-owned outputs even then; never invent an HRESULT.
        diagnostic.update(boolean_short=c_short.from_buffer(percent).value,
                          double=raw_observation(amount.value))
    raw_short = diagnostic['boolean_short']
    require(type(status) is int and status == 0, 'Strict StepOver S_OK required')
    require(raw_short in (0, -1), 'StepOver Boolean output untouched or noncanonical')
    require(isfinite(amount.value), 'StepOver double output untouched or nonfinite')
    value = [raw_short == -1, amount.value]
    diagnostic.update(outputs_validated=True, value=deepcopy(value),
                      output_order=['percent', 'amount_native'], unit_conversion_performed=False)
    return value


def checked_value(spec, value):
    value = list(value) if type(value) is tuple else value
    kind = spec[3]
    finite = lambda v:type(v) is float and isfinite(v)
    if kind == 'bool': valid = type(value) is bool
    elif kind == 'long': valid = type(value) is int and -(2**31) <= value < 2**31
    elif kind == 'double': valid = finite(value)
    elif kind == 'double_bool':
        valid = type(value) is list and len(value) == 2 and finite(value[0]) and type(value[1]) is bool
    else:
        valid = type(value) is list and len(value) == 2 and type(value[0]) is bool and finite(value[1])
    require(valid, 'Unexpected floor field native scalar shape: ' + spec[0])
    return value


class FloorReadBatch(pocket.PocketReadBatch):
    def read(self, obj, name, *args):
        self.reject(name in GETTERS, 'Getter outside floor field scope')
        for arg in args:
            self.reject(type(arg) is int or id(arg) in self._known_objects,
                        'Argument outside retained floor graph')
        return self.observed(obj, 'getter', name, lambda:_member(obj, name, *args))

    def typed(self, obj, name):
        try:
            self.reject(name in INTERFACES, 'Interface outside floor field scope')
            cls = finish.interface_class(name, self.typelib_path, self.generated_pin)
            def query():
                value = obj.QueryInterface(cls)
                require(value is not None and bool(value) and isinstance(value, cls),
                        'Exact non-null floor interface required')
                return value
            return self.observed(obj, 'qi', name, query)
        except BaseException:
            self._invalid = True; self._completed = False
            raise

    def step_over(self, obj, diagnostic):
        try:
            cls = finish.interface_class('ICWFinishMillOp', self.typelib_path, self.generated_pin)
            self.reject(isinstance(obj, cls), 'Exact StepOver owner required')
            return self.observed(obj, 'getter', 'GetStepOver', lambda:step_over_value(obj, diagnostic))
        except BaseException:
            self._invalid = True; self._completed = False
            raise

    def sw_typed(self, *args): self.reject(False, 'SW query outside floor scope')
    def plane(self, *args): self.reject(False, 'Plane query outside floor scope')
    def feature_dispatch(self, *args): self.reject(False, 'Dispatch conversion outside floor scope')


def read_fields(backend, label):
    require(type(label) is str and re.fullmatch('[A-Za-z0-9_]{1,48}', label), 'Bounded read label required')
    own = finish.common._key(__file__)
    require(any(finish.common._key(p['path']) == own and p['sha256'] == finish._file_hash(__file__)
                for p in backend.loaded['pins']), 'Floor reader must be pinned live')
    audit = audit_interfaces(backend.typelib_path, backend.loaded['generated_pin'])
    with backend.ctx.guard() as guard:
        operation, feature = backend.target(guard, 144)
    doc = backend.native['doc']
    diagnostic = dict(scope=SCOPE, label=label, complete=False, operation_native_id=144,
                      feature_native_id=79, interface_audit=audit, raw_fields={}, pointer_fields={})
    backend.report.setdefault('floor_field_batches', []).append(diagnostic)
    state = dict(member='', returned=False, read_index=0)
    path = Path(backend.args['progress_path'])
    path = path.with_name(path.stem + '.' + label + '_floor_fields.json')
    protected = [backend.args['expected_document_path'], backend.args['receipt_path']]
    protected += [p['path'] for p in backend.loaded['pins']]
    batch = None
    def binding():
        backend.target(batch, 144)
        require(_object_id(doc, operation, batch.read) == 144
                and _object_id(doc, feature, batch.read) == 79, 'Retained floor binding changed')
    try:
        with progress.ReadProgressJournal(full_persist=backend.persist, progress_path=path,
                describe=lambda:dict(state, phase=label), max_updates=MAX_CALLS*2+4,
                protected_paths=protected) as journal:
            batch = FloorReadBatch(backend.sw, backend.typelib_path,
                generated_pin=backend.loaded['generated_pin'], process_id=backend.args['process_id'],
                expected_document=backend.ctx.identity(), source_sha256=backend.ctx.args['expected_source_sha256'],
                evidence_pins=backend.loaded['pins'], verify_evidence=backend.ctx.files,
                verify_owned_process=backend.ctx.owned, check_events=backend.events,
                retained_objects=(doc, operation, feature), verify_retained_binding=binding,
                max_native_calls=MAX_CALLS, progress=journal.read, progress_state=state)
            with batch:
                owners = {n:batch.typed(operation, n) for n in ('ICWFinishMillOp', 'ICWFinishMillOp3')}
                values = {}
                for spec in FIELDS:
                    if spec[3] == 'owned_bool_double':
                        pointer = diagnostic['pointer_fields'].setdefault(spec[0], {})
                        value = batch.step_over(owners[spec[1]], pointer)
                    else:
                        value = batch.read(owners[spec[1]], spec[2])
                    diagnostic['raw_fields'][spec[0]] = raw_observation(value)
                    values[spec[0]] = checked_value(spec, value)
                require(len(values) == 18, 'Exact eighteen floor fields required')
            batch.require_complete(); journal.complete()
        diagnostic.update(complete=True, field_count=len(values))
        return values
    finally:
        if batch is not None: diagnostic['batch'] = batch.summary()
        backend.persist()


def inspect_inputs(request):
    from scripts import sw_cam_finish_field_batch as prior
    from scripts.sw_cam_turn_tool import _digest
    keys = {'process_id','expected_document_path','expected_source_sha256','addin_clsid',
            'receipt_path','progress_path','observation_path','observation_sha256',
            'plan_path','plan_sha256','module_sha256'}
    require(type(request) is dict and set(request) == {'action','params'}
            and request['action'] == 'inspect_finish_floor_fields', 'Explicit floor inspection required')
    p = request['params']
    require(type(p) is dict and set(p) == keys, 'Exact floor inspection parameters required')
    require(p['module_sha256'] == finish._file_hash(__file__), 'Floor reader module differs')
    for name in ('observation_path','plan_path'):
        require(type(p[name]) is str and Path(p[name]).is_absolute(), 'Absolute input path required')
    for name in ('observation_sha256','plan_sha256'):
        require(type(p[name]) is str and re.fullmatch('[0-9a-f]{64}',p[name]), 'Exact input SHA required')
    observed, observed_pin = read_pin(p['observation_path'], p['observation_sha256'])
    require(observed.get('scope') == prior.SCOPE and observed.get('status') == 'observed'
            and observed.get('phase') == 'finished' and observed.get('readback_verified') is True
            and observed.get('phase_proofs_verified') is True and observed.get('read_only') is True
            and all(observed.get(k) is False for k in ('mutation_authority','setter_attempted',
                    'GTP_attempted','model_saved','automatic_replay')), 'Completed direct observation required')
    clean_events(observed)
    require(observed['process_id'] == p['process_id']
            and finish.common._key(observed['source_path']) == finish.common._key(p['expected_document_path'])
            and observed['source_sha256'] == p['expected_source_sha256'], 'Direct observation source/process differs')
    require(set(observed['fields']) == {s[0] for s in finish.FIELDS}, 'Exact direct field inventory required')
    for spec in finish.FIELDS: prior.checked_value(spec, observed['fields'][spec[0]])
    require(observed['fields']['bottom_finish'] is False, 'Observed disabled bottom required')
    failed = observed['failed_receipt_pin']
    base = {k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256',
                            'addin_clsid','receipt_path','progress_path')}
    base.update(failed_receipt_path=failed['path'], failed_receipt_sha256=failed['sha256'],
                module_sha256=finish._file_hash(prior.__file__))
    _, loaded, _ = prior.inspect_inputs(dict(action='inspect_partial_finish_fields', params=base))
    finish.common._check(observed['live_pins']); finish.common._check(observed['offline_proof_pins'])
    require(finish.group.exact(observed['before_document'], observed['after_document'])
            and finish.group.exact(observed['after_document'], loaded['state']['document'])
            and finish.group.exact(observed['before_tool'], finish.wanted_assignment(loaded)),
            'Direct observation document or tool differs')
    old = [v for v in loaded['pins'] if finish.common._key(v['path']) == finish.common._key(prior.__file__)]
    require(len(old) == 1 and old[0]['sha256'] == observed['module_pin']['sha256'], 'Exact completed reader pin required')
    plan, plan_pin = read_pin(p['plan_path'], p['plan_sha256'])
    require([(v['interface'],v['member']) for v in plan['getters']] == [(v[1],v[2]) for v in FIELDS],
            'Exact documented eighteen-getter plan required')
    help_pins = [v['saved_help'] for v in plan['getters']] + [plan['source_archive']]
    finish.common._check(help_pins)
    loaded['pins'] = finish.common._merge([v for v in loaded['pins'] if v not in old], [finish.common._pin(__file__)])
    require(len(loaded['pins']) <= 64, 'Bounded live floor reader closure required')
    loaded['offline_export_proof_pins'] = finish.common._merge(loaded['offline_export_proof_pins'],
          old, [observed_pin,plan_pin], help_pins)
    loaded['current_context_sha256'] = _digest(finish.group.current_projection(loaded))
    return deepcopy(p), loaded, observed_pin, plan_pin


def run_inspection(sw, clsid, typelib, *, params, loaded, observed_pin, plan_pin):
    report = dict(schema_version=1, scope=SCOPE, status='reading', phase='binding',
        read_only=True, mutation_authority=False, setter_attempted=False, GTP_attempted=False,
        model_saved=False, automatic_replay=False, process_id=params['process_id'],
        source_path=params['expected_document_path'], source_sha256=params['expected_source_sha256'],
        observation_pin=observed_pin, plan_pin=plan_pin, module_pin=finish.common._pin(__file__),
        live_pins=deepcopy(loaded['pins']), offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        readback_verified=False, phase_proofs_verified=False, floor_recipe_qualified=False)
    backend = None
    def persist(): _write_receipt(params['receipt_path'], report)
    _write_receipt(params['receipt_path'], report, create=True)
    try:
        backend = finish.NativeBackend(loaded, params, sw, clsid, typelib, report, persist)
        backend.start()
        report['before_document'] = backend.ctx.identity()
        report['before_tool'] = backend.current_tool()
        require(finish.group.exact(report['before_tool'], finish.wanted_assignment(loaded)), 'Floor tool assignment changed')
        report['phase'] = 'floor_fields'; persist()
        report['fields'] = read_fields(backend, 'inspect')
        require(report['fields']['bottom_finish'] is False, 'Bottom option changed since direct observation')
        report['after_document'] = backend.ctx.identity()
        require(report['before_document'] == report['after_document'] == loaded['state']['document'],
                'Read-only floor inspection changed document identity')
        finish.common._check(loaded['offline_export_proof_pins']); finish.common._check(loaded['bootstrap_export_pins'])
        backend.boundary()
        report.update(status='observed', phase='finished', readback_verified=True, phase_proofs_verified=True)
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], phase='finished', issue=_error(exc))
    finally:
        if backend is not None:
            try: backend.close()
            except Exception as exc: report.update(status='error', cleanup_issue=_error(exc), readback_verified=False)
        persist()
    return report


def dispatch_request(request, *, validate_only=False):
    p, loaded, observed_pin, plan_pin = inspect_inputs(request)
    registration = finish.common.discover_export_registration(loaded, p['addin_clsid'])
    typelib = str(Path(registration['addin_path']).parent / 'camworks.tlb')
    audit = audit_interfaces(typelib, loaded['generated_pin'])
    if validate_only:
        return dict(status='validated_offline', native_called=False, live_pin_count=len(loaded['pins']),
                    floor_field_count=18, interface_audit=audit, mutation_authority=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=p['process_id']):
        finish.common._check(loaded['pins']); finish.common._check(loaded['offline_export_proof_pins'])
        sw, _ = connect_solidworks(process_id=p['process_id'], launch_new_instance=False, wait_seconds=1)
        return run_inspection(sw, registration['clsid'], typelib, params=p, loaded=loaded,
                              observed_pin=observed_pin, plan_pin=plan_pin)


def main(argv=None):
    import argparse, json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True); parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(argv)
    result = dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')), validate_only=args.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','fields','issue','native_called')}, ensure_ascii=False))
    return 0 if result.get('status') == 'validated_offline' or result.get('readback_verified') is True else 1


if __name__ == '__main__': raise SystemExit(main())

