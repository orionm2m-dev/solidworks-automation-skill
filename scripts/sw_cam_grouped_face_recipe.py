"""One bounded FACE recipe, selected generation and native save.

The workflow is deliberately non-atomic. A persistent attempt blocks replay.
Runtime binding and native observations remain separate from machining acceptance.
"""
from copy import deepcopy
from pathlib import Path
import math
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_ud14_save import run_one_existing_save

SCOPE = 'GROUPED_EXISTING_FACE_RECIPE_V1'
OPERATION_ID = 267
FEATURE_ID = 265
TOOL_ID = 249
ORDER = [143, 144, 195, 196, 267, 247, 248]
CHANGES = (
    ('ShapeExtent', 'property', 'ShapeExtent', 1, 0),
    ('AutoAngle', 'property', 'AutoAngle', True, False),
    ('CutOrder', 'property', 'CutOrder', 0, 1),
    ('SetMaxStepOver', 'pair', 'GetMaxStepOver', [70.0, True], [3.2, False]),
    ('SetMinSideOffset', 'pair', 'GetMinSideOffset', [10.0, True], [0.5, False]),
    ('SetMaxSideOffset', 'pair', 'GetMaxSideOffset', [25.0, True], [1.0, False]),
    ('SetFirstCutAmount', 'pair', 'GetFirstCutAmount', [1.0, False], [0.5, False]),
    ('SetMaxCutAmount', 'pair', 'GetMaxCutAmount', [1.0, False], [0.5, False]),
    ('SetLeadInClearance', 'feature_pair', 'GetLeadInClearance', [55.0, True], [2.0, False]),
    ('SetLeadOutClearance', 'feature_pair', 'GetLeadOutClearance', [55.0, True], [2.0, False]),
    ('SetPassClearance', 'feature_pair', 'GetPassClearance', [5.0, True], [2.0, False]),
    ('SetLinkTypeAlongCutAboveThreshold', 'feature_int', 'GetLinkTypeAlongCutAboveThreshold', 1, 0),
    ('SetLinkTypeBetweenCutsAboveThreshold', 'feature_int', 'GetLinkTypeBetweenCutsAboveThreshold', 1, 0),
)
PROTECTED_FACE = dict(CutMethod=1, NumberOfCuts=1, EqualizeToolLoading=False,
    MachiningExtent=0, IslandXYAllowance=0.5, IslandCleanupPass=False, CutAngle=0.0,
    MillingType=0, ZigZagType=True, GetBottomAllowance=0.0, GetFinalCutAmount=0.0,
    GetAvoidAllowance=0.002, GetContainAllowance=0.002, GetContainType=0,
    GetLinkThresholdAlongCut=[100.0, True], GetLinkThresholdBetweenCuts=[70.0, True],
    GetLinkTypeAlongCutUptoThreshold=0, GetLinkTypeBetweenCutsUptoThreshold=0,
    GetMachiningDepth=2.0, GetOverrideMachiningDepth=False)
NC_EXPECTED = dict(GetSpndlSpeed=1000.0, GetTlpComp=1, GetCNCComp=0,
    GetRetractType=0, GetClrPlaneUseSetupStatus=False, GetRpdPlaneUseSetupStatus=False,
    XYFeed=500.0)


def exact(a, b):
    """Native bool/int distinctions and list shape are part of the contract."""
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return math.isfinite(a) and math.isfinite(b) and a == b
    if type(a) is list:
        return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b))
    if type(a) is dict:
        return set(a) == set(b) and all(exact(a[k], b[k]) for k in a)
    return a == b


def expected_settings(configured=False):
    face = deepcopy(PROTECTED_FACE)
    face.update({getter: deepcopy(target if configured else old)
                 for _, _, getter, old, target in CHANGES})
    return dict(face=face, nc=deepcopy(NC_EXPECTED))


def settings_from_observation(raw):
    """Use the existing decoder; do not silently coerce observed scalar types."""
    from scripts import sw_cam_raw_mill_face_observation_v2 as reader
    face = raw.get('face_parameters', {})
    nc = raw.get('nc_parameters', {})
    require(set(face) == set(expected_settings()['face']) and nc.get('available') is True
        and set(nc.get('fields', {})) == set(NC_EXPECTED), 'Complete33FACE and7NC required')
    result = dict(face={}, nc={})
    for group, fields in [('face', face), ('nc', nc['fields'])]:
        for name, row in fields.items():
            require(row.get('read_complete') is True and 'raw' in row, 'Incomplete parameter read')
            value = row['raw']
            if name in reader.PAIRS or name in reader.FEATURE_PAIRS:
                reader.decode(value, 'pair')
            else:
                wanted = expected_settings()[group][name]
                reader.decode(value, 'bool' if type(wanted) is bool else 'int' if type(wanted) is int else 'float')
            result[group][name] = deepcopy(value)
    return result


def verify_settings(actual, *, configured=False, declared_coupling=False, generated_count=None):
    expected = expected_settings(configured)
    if generated_count is not None:
        require(configured and type(generated_count) is int and 1 <= generated_count <= 2147483647, 'Strict positive automatic LONG count required')
        expected['face']['NumberOfCuts'] = generated_count
    require(type(actual) is dict and set(actual) == {'face', 'nc'}, 'Exact settings schema required')
    require(type(actual['face']) is dict and set(actual['face']) == set(expected['face']), 'Exact33FACE fields required')
    require(exact(actual['nc'], expected['nc']), 'Protected NC values changed')
    changed = {g: (o, t) for _, _, g, o, t in CHANGES}
    for name, target in expected['face'].items():
        value = actual['face'][name]
        if declared_coupling and name in changed:
            old, requested = changed[name]
            require(exact(value, old) or exact(value, requested), 'Unexpected coupled FACE field: ' + name)
        else:
            require(exact(value, target), 'Unexpected FACE field: ' + name)
    return deepcopy(actual)


def validate_plan(plan):
    require(type(plan) is dict and plan.get('scope') == SCOPE, 'Exact approved FACE plan required')
    identity = plan['identity']
    require(identity['operation_native_id'] == OPERATION_ID and identity['feature_native_id'] == FEATURE_ID
        and identity['setup_native_id'] == 93 and identity['required_confirmed_operation_order'] == ORDER,
        'Approved FACE target/order differs')
    rows = plan['face_changes']
    require(len(rows) == len(CHANGES), 'Exactly thirteen declared FACE changes required')
    for index, (row, spec) in enumerate(zip(rows, CHANGES), 1):
        member, kind, getter, old, target = spec
        args = ([target] if kind == 'property' else list(target) if kind == 'pair' else
                ['exact_feature265_IDispatch', *target] if kind == 'feature_pair' else
                ['exact_feature265_IDispatch', target])
        require(row['index'] == index and row['interface'] == 'ICWFaceMillOp'
            and row['member'] == member and row['kind'] == kind and row['readback'] == getter
            and exact(row['expected_old'], old) and exact(row['requested'], target)
            and exact(row['args'], args), 'FACE plan write differs: ' + member)
    require(exact(plan['face_already_at_target_or_protected'], PROTECTED_FACE)
        and exact(plan['nc_expected_unchanged'], NC_EXPECTED), 'Protected plan fields differ')
    tool = plan['tool_assignment']
    require(tool['expected_old_id'] == 252 and tool['target_existing_id'] == TOOL_ID
        and tool['interface'] == 'ICWMillOperation' and tool['member'] == 'SetTool', 'Existing tool assignment differs')
    require(plan['feeds']['no_feed_or_spindle_setters'] is True and plan['feeds']['plunging_allowed'] is False,
        'Only geometric qualification without feed/spindle edits is allowed')
    return dict(operation_id=OPERATION_ID, feature_id=FEATURE_ID, tool_id=TOOL_ID,
                changes=deepcopy(CHANGES), number_of_cuts_policy='EXACT1_BASELINE_CONFIG_POSITIVE_LONG_AFTER_GTP_FREEZE_THROUGH_SAVE')


def group_marker(source, source_sha, operation_id=OPERATION_ID):
    require(type(operation_id) is int and operation_id == OPERATION_ID, 'Exact FACE operation required')
    source = Path(source).resolve()
    key = _digest(dict(document=str(source).casefold(), source_sha256=source_sha,
                       operation_native_id=operation_id, scope=SCOPE))
    return Path(source).parent / ('face_group_' + key + '.json')


def return_observation(value):
    row = dict(python_type=type(value).__name__, value_recorded=False, value=None)
    if value is None or type(value) is bool:
        row.update(value_recorded=True, value=value)
    elif type(value) is int:
        if -(2**63) <= value < 2**63: row.update(value_recorded=True,value=value)
        else: row['limit_reason']='integer_outside_signed64'
    elif type(value) is float:
        if math.isfinite(value): row.update(value_recorded=True, value=value)
        else: row['nonfinite_repr'] = repr(value)
    elif type(value) is str:
        if len(value) <= 4096: row.update(value_recorded=True, value=value)
        else: row['limit_reason'] = 'string_over4096'
    else:
        row['limit_reason'] = 'nonprimitive_native_return'
    return row


class GroupJournal:
    """One durable marker for the entire group, independent of recipe/output names."""
    def __init__(self, report, receipt, marker):
        self.report, self.receipt, self.marker = report, Path(receipt), Path(marker)
        self.created = self.claimed = False
        self.marker_digest = None

    def create(self):
        require(not self.marker.exists() and not self.marker.is_symlink(), 'Prior FACE group attempt; no replay')
        _write_receipt(self.receipt, self.report, create=True)
        self.created = True

    def _marker_state(self):
        r = self.report
        return dict(scope=SCOPE, status=r['status'], phase=r['phase'], source_path=r['source_path'],
            source_sha256=r['source_sha256'], operation_native_id=OPERATION_ID,
            recipe_sha256=r['recipe_sha256'], receipt_path=str(self.receipt),
            current_action=r.get('current_action'), actions=deepcopy(r['actions']),
            native_dispatch_pending=r.get('native_dispatch_pending', False), automatic_replay=False)

    def persist(self):
        if not self.created: return
        if self.claimed:
            require(_file_hash(self.marker) == self.marker_digest, 'Current group marker changed externally')
            _write_receipt(self.marker, self._marker_state())
            self.marker_digest = _file_hash(self.marker)
        _write_receipt(self.receipt, self.report)

    def entry(self, name):
        require(name not in self.report['actions'], 'Stage already attempted; no replay')
        row = dict(status='prepared', attempted=False, returned=False, readback_verified=False)
        self.report['actions'][name] = row
        self.report['current_action'] = name
        self.report['phase'] = name
        self.persist()
        return row

    def pending(self, name):
        row = self.report['actions'][name]
        require(row['attempted'] is False, 'Repeated native action forbidden')
        row.update(status='pending', attempted=True, native_dispatch_pending=True)
        self.report.update(mutation_attempted=True, native_call_attempted=True, native_dispatch_pending=True)
        if not self.claimed:
            _write_receipt(self.marker, self._marker_state(), create=True)
            self.claimed = True
            self.marker_digest = _file_hash(self.marker)
        self.persist()

    def execute(self, name, invoke, *, property_assignment=False):
        row = self.entry(name)
        value = invoke(lambda: self.pending(name))
        require(row['attempted'] is True, 'Native callback bypassed durable pending')
        row.update(status='returned', returned=True, native_dispatch_pending=False,
                   native_return=return_observation(value))
        self.report.update(native_call_returned=True, native_dispatch_pending=False)
        self.persist()
        if property_assignment:
            require(value is None, 'Unexpected Python property assignment result')
            row['return_contract'] = 'PROPERTY_ASSIGNMENT_NO_OBSERVABLE_HRESULT'
        else:
            require(type(value) is int and value == 0, 'Strict native HRESULT S_OK0 required: ' + name)
        self.persist()
        return row

    def verified(self, name, observed):
        row = self.report['actions'][name]
        row.update(observed=deepcopy(observed), readback_verified=True, status='verified')
        self.persist()


def apply_face_fields(backend, journal):
    """Fixed writer list; one affected getter after each actual assignment."""
    for member, kind, getter, old, target in CHANGES:
        backend.boundary()
        actual = backend.read_field(getter)
        journal.report.setdefault('field_observations', {})[member] = dict(before=deepcopy(actual))
        journal.persist()
        require(exact(actual, old) or exact(actual, target), 'FACE field changed before write: ' + member)
        if exact(actual, target):
            row = journal.entry(member)
            row.update(status='already_observed_at_target', readback_verified=True, observed=deepcopy(actual))
            journal.persist()
            continue
        journal.execute(member, lambda pending: backend.write_field(member, kind, deepcopy(target), pending),
                        property_assignment=kind == 'property')
        backend.refresh_dirty()
        value = backend.read_field(getter)
        journal.report['field_observations'][member]['after'] = deepcopy(value)
        journal.persist()
        require(exact(value, target), 'FACE immediate readback differs: ' + member)
        journal.verified(member, value)


def run_grouped_backend(backend, journal):
    """The backend supplies finite native captures; this engine never retries."""
    r = journal.report
    r.update(status='error', phase='preflight', actions={}, mutation_attempted=False,
        native_call_attempted=False, native_call_returned=False, native_dispatch_pending=False,
        model_saved=False, readback_verified=False, full_capture_count=0,
        automatic_retry=False, automatic_replay=False, automatic_rollback=False,
        physical_geometry_verified=False, cutting_conditions_qualified=False, production_qualified=False)
    try:
        journal.create()
        backend.start()
        r['phase'] = 'baseline'; journal.persist()
        baseline = backend.capture_full('baseline'); r['full_capture_count'] += 1
        r['baseline'] = deepcopy(baseline); journal.persist()
        backend.verify_baseline(baseline)
        verify_settings(baseline['settings'])
        journal.execute('SetTool', backend.assign_tool)
        backend.refresh_dirty()
        assigned = backend.read_settings('after_assignment')
        r['after_assignment'] = deepcopy(assigned); journal.persist()
        backend.verify_assignment(assigned)
        verify_settings(assigned['settings'], declared_coupling=True)
        journal.verified('SetTool', assigned)
        apply_face_fields(backend, journal)
        configured = backend.read_narrow('configured')
        r['configured'] = deepcopy(configured); journal.persist()
        verify_settings(configured['settings'], configured=True)
        backend.verify_configured(configured)
        journal.execute('GenerateToolpath', backend.generate)
        backend.refresh_dirty()
        generated = backend.read_narrow('generated')
        r['generated'] = deepcopy(generated); journal.persist()
        generated_count = generated['settings']['face']['NumberOfCuts']
        r['automatic_count_observation'] = dict(before=1, after=generated_count, physical_pass_count_verified=False)
        journal.persist()
        verify_settings(generated['settings'], configured=True, generated_count=generated_count)
        backend.verify_generated(generated)
        journal.verified('GenerateToolpath', generated)
        expected = backend.save_projection(generated)
        save_report = dict(phase='prepared', native_call_returned=False, save_pending=False)
        r['save_stage'] = save_report
        journal.entry('SaveActiveDocument')
        def save_persist():
            entry = r['actions']['SaveActiveDocument']
            if save_report.get('native_call_returned') is True:
                entry.update(returned=True, native_dispatch_pending=False, status='returned',
                    native_return=return_observation(save_report['native_return_value']))
                if not entry['native_return']['value_recorded']:
                    save_report['unserializable_native_return'] = deepcopy(entry['native_return'])
                    save_report['native_return_value'] = None
                r.update(native_dispatch_pending=False)
            journal.persist()
        def capture(label):
            if label == 'before':
                observed = backend.read_narrow('before_save')
                r['before_save'] = deepcopy(observed); journal.persist()
                backend.verify_generated(observed)
                verify_settings(observed['settings'], configured=True, generated_count=generated_count)
                return backend.save_projection(observed)
            observed = backend.capture_full('final'); r['full_capture_count'] += 1
            r['final'] = deepcopy(observed); journal.persist()
            backend.verify_final(observed)
            verify_settings(observed['settings'], configured=True, generated_count=generated_count)
            return backend.save_projection(observed)
        run_one_existing_save(save_report, capture=capture,
            verify=lambda value: require(exact(value, expected), 'Save protected projection changed'),
            guard=backend.boundary, claim=lambda: journal.pending('SaveActiveDocument'),
            persist=save_persist, save=backend.save,
            saved_hash=lambda: backend.saved_hash(save_report))
        journal.verified('SaveActiveDocument', dict(source_sha256=save_report['saved_file_sha256']))
        backend.finish()
        require(r['full_capture_count'] == 2, 'Exactly one full baseline and final capture required')
        r.update(status='review_required', phase='finished', model_saved=True, readback_verified=True,
            compact_checkpoint=backend.checkpoint(r['final']),
            reason='GROUPED_FACE_RECIPE_GTP_SAVE_READBACK_ONLY_CL_WIP_PENDING')
        journal.persist()
    except Exception as exc:
        from scripts.sw_cam import _error
        r.update(status='uncertain' if r['mutation_attempted'] else 'error', failed_phase=r['phase'],
            phase='finished', issue=_error(exc), readback_verified=False)
        try: journal.persist()
        except Exception as write_exc: r['receipt_write_error'] = _error(write_exc)
    finally:
        try: backend.close()
        except Exception as exc:
            from scripts.sw_cam import _error
            r.update(status='uncertain' if r['mutation_attempted'] else 'error', readback_verified=False, cleanup_issue=_error(exc))
            try: journal.persist()
            except Exception as write_exc: r['receipt_write_error'] = _error(write_exc)
    return r


CURRENT_KEYS = ('state','payload','finish_payload','ownership','ids','observation_pin','holder_recipe',
    'cone_observation','face_observation','cone_sketch_spec','face_sketch_spec','cone_feature_native_id',
    'face_feature_native_id','source_sha256','qualification','read_mode','base_saved_pin')


def current_projection(loaded):
    return {k: deepcopy(loaded[k]) for k in CURRENT_KEYS}


def _key(path):
    return str(Path(path).resolve()).casefold()


def verify_route_delta(reference, observed, expected_tool, *, generated=False, saved_sha=None):
    """Only the selected assignment/path and explicit Save transition can change."""
    from scripts import sw_cam_raw_mill_face_operation as capture
    require(type(generated) is bool and type(observed['document'].get('needs_save')) is bool,
            'Strict generated/dirty flags required')
    require(len(reference['features']) == len(observed['features']) == 21
        and reference['operation_count'] == observed['operation_count'] == 7
        and [r['native_id'] for r in reference['operations']] == ORDER
        and [r['native_id'] for r in observed['operations']] == ORDER, 'Exact current21/7 order required')
    expected = deepcopy(reference)
    expected['document']['needs_save'] = observed['document']['needs_save']
    if saved_sha is not None:
        require(type(saved_sha) is str and len(saved_sha) == 64
            and observed['document']['needs_save'] is False, 'Explicit clean saved source required')
        expected['saved_file_sha256'] = saved_sha
    for old, actual, wanted in zip(reference['operations'], observed['operations'], expected['operations']):
        if old['native_id'] != OPERATION_ID:
            require(exact(old, actual), 'Protected operation changed: ' + str(old['native_id']))
            continue
        require(old['linked_feature_ids'] == [FEATURE_ID] and old['setup_native_id'] == 93
            and old['mill_operation_type'] == 20 and old['suppressed'] is False, 'Exact FACE binding required')
        wanted['assigned_tool'] = deepcopy(expected_tool)
        wanted['toolpath_generated'] = generated
        if generated:
            counts = actual['toolpath_record_counts']
            require(type(counts) is list and len(counts) == 1 and type(counts[0]) is int
                and 0 < counts[0] <= capture.MAX_RECORDS, 'One bounded positive FACE toolpath required')
            wanted['toolpath_record_counts'] = deepcopy(counts)
        else:
            wanted['toolpath_record_counts'] = []
        require(exact(wanted, actual), 'FACE delta exceeded assignment/path scope')
    capture.cone.require_state_equivalent(expected, observed)
    return deepcopy(observed)


from scripts.sw_cam_upper_cone_feature import UpperConeContext

class GroupContext(UpperConeContext):
    def files(self):
        require(_digest(current_projection(self.loaded)) == self.loaded['current_context_sha256'],
                'Immutable current parent changed')
        for pin in self.loaded['pins']:
            require(_file_hash(pin['path']) == pin['sha256'], 'Group native dependency changed')


class NativeBackend:
    """Reuse current inventory, parameter-reader and typed native implementations."""
    def __init__(self, loaded, args, sw, clsid, typelib_path, report, persist):
        from scripts import sw_cam_raw_mill_face_operation as capture
        self.capture = capture
        self.loaded, self.args, self.sw = loaded, dict(args), sw
        self.clsid, self.typelib_path = clsid, typelib_path
        self.report, self.persist = report, persist
        self.session = None
        self.session_active = False
        self.native = None
        self.current_state = deepcopy(loaded['state'])
        self.expected_tool = deepcopy(next(r['assigned_tool'] for r in loaded['state']['operations']
                                         if r['native_id'] == 248))
        require(self.expected_tool['native_id'] == TOOL_ID, 'Existing protected finish tool249 required')
        self.ctx = GroupContext(loaded, dict(args, **loaded['ids']), sw, typelib_path, None,
                                self.events, loaded['state'])
        self.save_app = None

    def events(self, active=True):
        require(self.session is not None, 'CAM message session required')
        value = self.session.summary()
        self.report['messages'] = value
        require(value.get('subscribed') is True and value.get('active') is active
            and (active or value.get('disconnected') is True)
            and not any(value.get(k) for k in ('event_count','overflow','callback_errors',
                'callback_error_count','subscription_error','disconnect_errors')), 'CAM event requires stop')

    def start(self):
        from scripts.sw_cam_events import CamMessageSession
        self.ctx.files(); self.ctx.identity()
        self.ctx.app = self.capture.cone._bootstrap(self.sw, self.clsid, self.typelib_path,
                                                   self.args['expected_document_path'])
        self.ctx.identity()
        self.session = CamMessageSession(self.ctx.app, self.typelib_path)
        self.session.__enter__(); self.session_active = True
        self.boundary()

    def boundary(self):
        self.ctx.files(); self.events(); self.ctx.identity()

    def refresh_dirty(self):
        from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
        self.ctx.files(); self.ctx.owned(); self.events()
        actual = raw_part_identity(self.sw)
        require(type(actual.get('needs_save')) is bool, 'Actual raw SW dirty flag must be bool')
        expected = deepcopy(self.ctx.expected_document); expected['needs_save'] = actual['needs_save']
        require(actual == expected and _file_hash(self.args['expected_document_path']) == self.ctx.args['expected_source_sha256'],
                'Mutation changed document identity or saved source')
        self.ctx.expected_document = deepcopy(actual)
        self.ctx.identity()
        self.report['current_document'] = deepcopy(actual); self.persist()

    def _resolve(self, g):
        from scripts.sw_cam_thread import _object_id
        require(self.native is not None, 'Fresh baseline native graph required')
        doc = self.native['doc']
        found = g.read(doc, 'GetCWObjectFromID', 3, OPERATION_ID)
        require(type(found) in (tuple,list) and len(found) == 2 and found[1] is True, 'Exact current operation lookup failed')
        op = g.typed(found[0], 'ICWOperation')
        require(_object_id(doc, op, g.read) == OPERATION_ID, 'Current operation identity differs')
        found = g.read(doc, 'GetCWObjectFromID', 1, FEATURE_ID)
        require(type(found) in (tuple,list) and len(found) == 2 and found[1] is True, 'Exact current FACE lookup failed')
        feature = g.typed(found[0], 'ICWFeature')
        require(_object_id(doc, feature, g.read) == FEATURE_ID, 'Current FACE identity differs')
        links = [_object_id(doc, f, g.read) for f in self.capture._items(g.read(op,'IGetAllFeatures'),g.typed,g.read,2)]
        require(links == [FEATURE_ID] and g.read(op,'Suppressed') is False, 'Current FACE linkage/suppression changed')
        self.native['operations'][OPERATION_ID] = op
        return op, feature

    def _face(self, g, op):
        from scripts.sw_cam_face_interfaces import query_face_interface
        g._fast()
        result = query_face_interface(op, 'ICWFaceMillOp', self.typelib_path,
                                      generated_pin=self.loaded['generated_pin'])
        g._fast()
        return result

    def _feature_dispatch(self, g, feature):
        from comtypes.automation import IDispatch
        from scripts.sw_cam_thread import _object_id
        result = g.read(feature, 'QueryInterface', IDispatch)
        require(_object_id(self.native['doc'], result, g.read) == FEATURE_ID, 'Feature dispatch identity changed')
        return result

    def _units(self):
        from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
        with self.ctx.guard() as g:
            value = read_document_cam_unit_scope(g.read(self.sw,'ActiveDoc'),self.ctx.app,
                                                 sw_read=g.read,cam_read=g.read)
        require(value == self.loaded['finish_payload']['unit_record']
            and value['metric_document_scope_observed'] is True, 'Metric document scope changed')
        return value

    def read_settings(self, label):
        from scripts import sw_cam_raw_mill_face_observation_v2 as reader
        from scripts.sw_cam_mill_route_context import read_generic_tool
        self.boundary()
        raw = dict(label=label)
        self.report.setdefault('parameter_observations', []).append(raw); self.persist()
        try:
            units = self._units()
            with self.ctx.guard() as g:
                op, feature = self._resolve(g)
                generic, _ = read_generic_tool(op,self.native['doc'],g.read,g.typed)
            binding = dict(doc=self.native['doc'],machine=self.native['machine'],operations={OPERATION_ID:op})
            row = deepcopy(next(r for r in self.current_state['operations'] if r['native_id'] == OPERATION_ID))
            batch = reader.FaceReadBatch(self.sw,self.typelib_path,native_context=binding,
                reference_state={'operations':[row]},process_id=self.args['process_id'],
                expected_document=self.ctx.identity(),source_sha256=self.ctx.args['expected_source_sha256'],
                evidence_pins=self.loaded['pins'],verify_evidence=self.ctx.files,
                verify_owned_process=self.ctx.owned,check_events=self.events,max_native_calls=150)
            batch.generated_pin = self.loaded['generated_pin']
            try:
                with batch:
                    from scripts.sw_cam_thread import _object_id
                    found = batch.read(self.native['doc'],'GetCWObjectFromID',1,FEATURE_ID)
                    require(type(found) in (tuple,list) and len(found)==2 and found[1] is True, 'Retained FACE lookup failed')
                    feature = batch.typed(found[0],'ICWFeature')
                    require(_object_id(self.native['doc'],feature,batch.read)==FEATURE_ID, 'Retained FACE ID differs')
                    reader.read_parameters(op,feature,read=batch.read,typed=batch.typed,
                        feature_dispatch=batch.feature_dispatch,report=raw,persist=self.persist)
                batch.require_complete()
            finally: raw['batch'] = batch.summary(); self.persist()
            require(self._units() == units, 'Units changed during selected parameter read')
            result = dict(settings=settings_from_observation(raw),binding=generic,units=units)
            raw['observed'] = deepcopy(result); self.persist()
            return result
        finally: self.persist()

    def read_field(self, getter):
        from scripts import sw_cam_raw_mill_face_observation_v2 as reader
        specs = [s for s in CHANGES if s[2] == getter]
        require(len(specs) == 1, 'Affected getter outside fixed FACE fields')
        _, kind, _, old, _ = specs[0]
        with self.ctx.guard() as g:
            op, feature = self._resolve(g); face = self._face(g,op)
            args = [self._feature_dispatch(g,feature)] if kind.startswith('feature_') else []
            value = g.read(face,getter,*args)
        value = list(value) if type(value) is tuple else value
        raw = dict(member=getter,value=deepcopy(value))
        self.report.setdefault('affected_getters', []).append(raw); self.persist()
        reader.decode(value,'pair' if type(old) is list else 'bool' if type(old) is bool else 'int')
        return value

    def assign_tool(self, pending):
        from scripts.sw_cam import _member
        from scripts.sw_cam_thread import _object_id
        from scripts.sw_cam_mill_route_context import read_generic_tool
        with self.ctx.guard() as g:
            op, feature = self._resolve(g)
            old, _ = read_generic_tool(op,self.native['doc'],g.read,g.typed)
            require(exact(old,next(r['assigned_tool'] for r in self.loaded['state']['operations']
                                  if r['native_id'] == OPERATION_ID)), 'Initial FACE assignment changed')
            crib = g.typed(g.read(self.native['machine'],'IGetToolcrib'),'ICWToolcrib4')
            candidates = [v for v in self.capture._items(g.read(crib,'GetAllTools'),g.typed,g.read,128)
                          if _object_id(self.native['doc'],v,g.read) == TOOL_ID]
            require(len(candidates) == 1, 'Existing crib tool249 must be unique')
            mill = g.typed(op,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'SetTool',candidates[0]),persist_pending=pending)

    def write_field(self, member, kind, target, pending):
        from scripts.sw_cam import _member
        matches = [s for s in CHANGES if s[0] == member and s[1] == kind and exact(s[4],target)]
        require(len(matches) == 1, 'Write outside approved FACE targets')
        with self.ctx.guard() as g:
            op, feature = self._resolve(g); face = self._face(g,op)
            if kind == 'property':
                invoke = lambda:setattr(face,member,target)
            else:
                args = list(target) if type(target) is list else [target]
                if kind.startswith('feature_'): args.insert(0,self._feature_dispatch(g,feature))
                invoke = lambda:_member(face,member,*args)
            return g.dispatch_once(invoke,persist_pending=pending)

    def generate(self, pending):
        from scripts.sw_cam import _member
        from scripts.sw_cam_mill_route_context import read_generic_tool
        with self.ctx.guard() as g:
            op, _ = self._resolve(g)
            require(g.read(op,'GetIsToolpathGenerated') is False, 'FACE267 already generated; no replay')
            tool,_ = read_generic_tool(op,self.native['doc'],g.read,g.typed)
            require(exact(tool,self.expected_tool), 'FACE target tool changed before GTP')
            mill = g.typed(op,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)

    def capture_full(self, label):
        self.boundary(); diagnostic = dict(phase=label)
        self.report.setdefault('full_diagnostics', []).append(diagnostic); self.persist()
        try:
            state,native = self.capture._capture_headers(self.ctx,self.clsid,self.loaded['state'],21,diagnostic)
            diagnostic['state'] = deepcopy(state); self.persist()
            self.native = native; self.current_state = deepcopy(state)
            payload = self.capture._capture_payload(self.ctx,state,native,diagnostic)
            diagnostic['payload'] = deepcopy(payload); self.persist()
            co = self.capture.cone._read_sketch_and_cone(self.ctx,native,self.loaded['cone_sketch_spec'],self.loaded['cone_feature_native_id'])
            diagnostic['cone'] = deepcopy(co); self.persist()
            fo = self.capture.face._read_face(self.ctx,native,self.loaded['face_sketch_spec'],FEATURE_ID,
                         diagnostic=diagnostic.setdefault('face_raw',{}),persist=self.persist)
            diagnostic['face'] = deepcopy(fo); self.persist()
            selected = self.read_settings(label)
            return dict(state=state,payload=payload,cone_observation=co,face_observation=fo,**selected)
        finally: self.persist()

    def read_narrow(self, label):
        self.boundary();state=deepcopy(self.current_state)
        state['document']=self.ctx.identity();state['saved_file_sha256']=self.ctx.args['expected_source_sha256']
        diagnostic=dict(phase=label);self.report.setdefault('route_header_observations',[]).append(diagnostic)
        self.persist()
        batch=self.capture.cone.ScopedUpperHeaderReadBatch(self.sw,self.typelib_path,native_context=self.native,
            reference_state=state,process_id=self.args['process_id'],expected_document=self.ctx.identity(),
            source_sha256=self.ctx.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events)
        try:
            with batch:self.capture.read_route_operations(state,self.native,batch.read,batch.typed,diagnostic=diagnostic)
            batch.require_complete()
        finally:
            diagnostic.update(state=deepcopy(state),batch=batch.summary());self.persist()
        self.current_state=deepcopy(state)
        selected=self.read_settings(label)
        with self.ctx.guard() as g:self.save_app=g.typed(self.ctx.app,'ICWApp')
        return dict(state=state,**selected)

    def verify_baseline(self, observed):
        self.capture.cone.require_state_equivalent(self.loaded['state'],observed['state'])
        require(observed['payload']==dict(rough=self.loaded['payload'],finish=self.loaded['finish_payload'])
            and observed['cone_observation']==self.loaded['cone_observation']
            and observed['face_observation']==self.loaded['face_observation'], 'Protected baseline differs')
        tool=observed['payload']['finish']['full_tool']
        require(tool['tool_native_id']==TOOL_ID and tool['cut_diameter_native']==8.0
            and tool['tool_protrusion_native']==25.0 and tool['mill_tool']['effective_cutting_length_native']==21.0
            and tool['mill_tool']['overall_length_native']==64.0 and tool['mill_tool']['end_radius_native']==0.0
            and tool['mill_tool']['flute_count_raw']==4,'Protected existing cutter nominal differs')
        require(tool['profiles']['holder']['declared_chain_count']==1
            and tool['profiles']['holder']['chains'][0]['declared_curve_count']==19,'Expected19segment holder reference required')

    def verify_assignment(self, observed):
        require(exact(observed['binding'],self.expected_tool),'Assigned current tool249 differs')

    def verify_configured(self, observed):
        self.verify_assignment(observed)
        verify_route_delta(self.loaded['state'],observed['state'],self.expected_tool,generated=False)

    def verify_generated(self, observed):
        self.verify_assignment(observed)
        verify_route_delta(self.loaded['state'],observed['state'],self.expected_tool,generated=True)

    def verify_final(self, observed):
        self.verify_assignment(observed)
        verify_route_delta(self.loaded['state'],observed['state'],self.expected_tool,generated=True,
                           saved_sha=self.ctx.args['expected_source_sha256'])
        require(observed['payload']==dict(rough=self.loaded['payload'],finish=self.loaded['finish_payload'])
            and observed['cone_observation']==self.loaded['cone_observation']
            and observed['face_observation']==self.loaded['face_observation'], 'Protected final payload/geometry differs')

    def save_projection(self, observed):
        state=observed['state']
        return dict(operations=deepcopy(state['operations']),operation_counts=deepcopy(state['operation_counts']),
            operation_setups=deepcopy(state['operation_setups']),settings=deepcopy(observed['settings']),
            units=deepcopy(observed['units']),assigned_tool=deepcopy(observed['binding']))

    def save(self):
        from scripts.sw_cam import _member
        self.boundary();require(self.save_app is not None,'Prepared typed Save interface required')
        return _member(self.save_app,'SaveActiveDocument')

    def saved_hash(self, save_report):
        from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
        require(save_report.get('native_call_returned') is True and save_report.get('save_pending') is False
            and save_report.get('native_return_type')=='int' and type(save_report.get('native_return_value')) is int
            and save_report['native_return_value']==0,'No source transition before strict Save0')
        self.events();self.ctx.files();self.ctx.owned()
        actual=raw_part_identity(self.sw);expected=deepcopy(self.ctx.expected_document);expected['needs_save']=False
        require(actual==expected and type(actual['needs_save']) is bool,'NativeSave must leave exact clean document')
        digest=_file_hash(self.args['expected_document_path'])
        self.report['source_transition']=dict(source_before_sha256=self.args['expected_source_sha256'],
            source_after_sha256=digest,strict_save_return=0,document=deepcopy(actual))
        self.persist()
        self.ctx.args=dict(self.ctx.args,expected_source_sha256=digest);self.ctx.expected_document=deepcopy(actual)
        self.ctx.identity()
        return digest

    def finish(self):
        require(self.session_active,'Active CAM session required')
        self.session.__exit__(None,None,None);self.session_active=False
        self.events(False);self.ctx.files();self.ctx.identity()

    def close(self):
        if self.session_active:
            try:self.session.__exit__(None,None,None)
            finally:self.session_active=False

    def checkpoint(self, final):
        current=current_projection(self.loaded)
        current.update(state=deepcopy(final['state']),source_sha256=self.ctx.args['expected_source_sha256'])
        row=next(r for r in final['state']['operations'] if r['native_id']==OPERATION_ID)
        return dict(current=current,settings=deepcopy(final['settings']),generated_face_operation_id=OPERATION_ID,
                    toolpath_record_counts=deepcopy(row['toolpath_record_counts']))


OFFLINE_RUNTIME_NAMES = frozenset({'sw_cam_raw_mill_face_move.py','sw_cam_current_reconciliation.py',
    'sw_cam_route_batch_qualified_capture.py','sw_cam_stock_mesh_compare.py'})
ADDITIONAL_RUNTIME_NAMES = ('sw_cam_raw_mill_face_observation_v2.py','sw_cam_face_interfaces.py','sw_cam_ud14_save.py')


def _pin(path):
    path=Path(path).resolve()
    require(path.is_file() and not path.is_symlink(),'Regular immutable dependency required')
    return dict(path=str(path),sha256=_file_hash(path))


def _self_pin():return _pin(__file__)


def _pins(*groups):
    """Use the existing metadata-preserving merger only during offline loading."""
    from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
    return canonical_evidence_pins(*groups)


def _check(pins):
    for p in pins:require(_file_hash(p['path'])==p['sha256'],'Pinned dependency changed')


def _require_current(loaded):
    state=loaded['state']
    require(len(state['features'])==21 and state['operation_count']==7 and state['operation_counts']==[7,0,0]
        and [v['native_id'] for v in state['operations']]==ORDER,'Exact reconciled21/7 current order required')
    face=next(v for v in state['operations'] if v['native_id']==OPERATION_ID)
    require(face['linked_feature_ids']==[FEATURE_ID] and face['setup_native_id']==93 and face['operation_index']==4
        and face['mill_operation_type']==20 and face['suppressed'] is False and face['toolpath_generated'] is False
        and face['toolpath_record_counts']==[] and face['assigned_tool']['native_id']==252,'Ungenerated existing FACE267/tool252 required')
    require(next(v for v in state['operations'] if v['native_id']==247)['toolpath_record_counts']==[191]
        and next(v for v in state['operations'] if v['native_id']==248)['toolpath_record_counts']==[74], 'Protected191/74 required')
    require(type(state['document']['needs_save']) is bool and loaded['cone_feature_native_id']==264
        and loaded['face_feature_native_id']==FEATURE_ID,'Current document/geometry identity differs')


def load_group_parent(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    """Fully validate the current reconciliation once, before any native connection."""
    from scripts import sw_cam_current_reconciliation as parent
    from scripts import sw_cam
    loaded=parent.load_completed_reconciliation(path,digest,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
    _require_current(loaded)
    require(_digest(current_projection(loaded))==loaded['current_context_sha256'],'Current projection digest differs')
    _check(loaded['pins'])
    old=loaded['reconciliation_receipt']['failed_move_pin']
    retired=[];live=[]
    for pin in loaded['pins']:
        reason=None
        if Path(pin['path']).name in OFFLINE_RUNTIME_NAMES:reason='OFFLINE_PARENT_VALIDATOR_OR_UNUSED_ANALYSIS_ONLY'
        elif _key(pin['path'])==_key(old['path']):
            require(pin['sha256']==old['sha256'],'Original failed Move evidence differs')
            reason='MOVE_FAILURE_RESOLVED_BY_CURRENT_READONLY_RECONCILIATION'
        if reason:retired.append(dict(pin=deepcopy(pin),reason=reason))
        else:live.append(pin)
    require(len(retired)==5 and {Path(v['pin']['path']).name for v in retired if v['reason'].startswith('OFFLINE')}
        ==OFFLINE_RUNTIME_NAMES,'Exactly four nonexecuted dependencies and one reconciled receipt may retire')
    marker=loaded['reconciliation_receipt']['failed_move_marker_pin']
    require(any(_key(p['path'])==_key(marker['path']) and p['sha256']==marker['sha256'] for p in live),
        'Original uncertain Move marker must remain live')
    runtime=Path(sw_cam.__file__).resolve().parent
    live=_pins(live,[_self_pin()],[_pin(runtime/name) for name in ADDITIONAL_RUNTIME_NAMES])
    require(len(live)==63 and all(_key(p['path'])!=_key(expected_document_path) for p in live),
        'Exactly63 immutable dependencies; mutable source is separately guarded')
    generated=[p for p in live if Path(p['path']).name.startswith('_FE488661_')]
    require(len(generated)==1,'Exact generated native library required')
    current=current_projection(loaded)
    return dict(current,pins=live,current_context_sha256=_digest(current),parent_pin=deepcopy(loaded['parent_pin']),
        reconciliation_pin=deepcopy(loaded['reconciliation_pin']),generated_pin=generated[0],
        retired_offline=retired,parent_validation=dict(scope=parent.SCOPE,order_verified=True,
            original_failure_reconciled=True,source_verified_before_native=True),
        historical_move_marker_pin=deepcopy(marker))


def _fresh(loaded,receipt,marker):
    target=Path(receipt)
    require(target.is_absolute() and target.suffix.lower()=='.json' and target.parent.is_dir()
        and not target.exists() and not target.is_symlink(),'Fresh JSON receipt in existing directory required')
    forbidden={_key(p['path']) for p in loaded['pins']}|{_key(marker),_key(loaded['state']['document']['path'])}
    require(_key(target) not in forbidden,'Receipt overlaps protected data')
    require(not Path(marker).exists() and not Path(marker).is_symlink(),'Existing group attempt blocks replay')


def _validate_success(data):
    require(data.get('scope')==SCOPE and data.get('status')=='review_required' and data.get('phase')=='finished'
        and data.get('model_saved') is True and data.get('readback_verified') is True
        and data.get('native_dispatch_pending') is False and data.get('full_capture_count')==2,
        'Completed grouped configuration/generation/Save required')
    require(not any(k in data for k in ('issue','cleanup_issue','receipt_write_error','failed_phase'))
        and all(data.get(k) is False for k in ('automatic_retry','automatic_replay','automatic_rollback',
            'physical_geometry_verified','cutting_conditions_qualified','production_qualified')),
        'Group uncertainty or unsupported qualification')
    names=['SetTool']+[s[0] for s in CHANGES]+['GenerateToolpath','SaveActiveDocument']
    require(set(data['actions'])==set(names),'Exact fixed group stages required')
    for name in names:
        row=data['actions'][name]
        require(row.get('readback_verified') is True,'Every stage needs exact readback')
        if row.get('status')=='already_observed_at_target':
            require(name in {s[0] for s in CHANGES} and row.get('attempted') is False,'Only already-exact declared fields may skip')
            continue
        require(row.get('status')=='verified' and row.get('attempted') is True and row.get('returned') is True
            and row.get('native_dispatch_pending') is False,'Every dispatched stage must be terminal')
        ret=row['native_return'];require(ret.get('value_recorded') is True,'Durable raw native return required')
        if name in {s[0] for s in CHANGES if s[1]=='property'}:
            require(ret['python_type']=='NoneType' and ret['value'] is None,'Property assignment result differs')
        else:require(ret['python_type']=='int' and type(ret['value']) is int and ret['value']==0,'Strict nativeS_OK0 required')
    require(data['save_stage'].get('save_readback_verified') is True and data['save_stage'].get('native_call_returned') is True
        and data['save_stage'].get('save_pending') is False and data['save_stage'].get('native_return_type')=='int'
        and type(data['save_stage'].get('native_return_value')) is int and data['save_stage']['native_return_value']==0,
        'Strict native Save result and final readback required')
    n=data['automatic_count_observation']['after']
    require(data['automatic_count_observation']['before']==1 and data['automatic_count_observation']['physical_pass_count_verified'] is False,
        'Automatic count observation must remain unqualified')
    verify_settings(data['baseline']['settings'])
    verify_settings(data['configured']['settings'],configured=True)
    for key in ('generated','before_save','final'):verify_settings(data[key]['settings'],configured=True,generated_count=n)
    reference=data['baseline']['state'];final=data['final'];tool=next(v['assigned_tool'] for v in reference['operations'] if v['native_id']==248)
    verify_route_delta(reference,final['state'],tool,generated=True,saved_sha=data['save_stage']['saved_file_sha256'])
    require(final['payload']==data['baseline']['payload'] and final['cone_observation']==data['baseline']['cone_observation']
        and final['face_observation']==data['baseline']['face_observation'],'Protected payload/geometry changed')
    require(exact(NativeBackend.save_projection(None,data['generated']),NativeBackend.save_projection(None,final)),
        'Generated route/settings changed during Save')
    return final


def load_completed_group(path,digest,*,process_id,expected_document_path,expected_source_sha256,check_current_source=True):
    """Flat terminal parent: no historical creator/Move/reconciliation code replay."""
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
    data,pin=read_pin(str(path),digest);final=_validate_success(data);clean_events(data)
    require(data['module_pin']==_self_pin() and type(process_id) is int and data['process_id']==process_id
        and _key(data['source_path'])==_key(expected_document_path),'Exact group module/PID/document required')
    saved=data['save_stage']['saved_file_sha256']
    require(saved==expected_source_sha256==data['source_transition']['source_after_sha256']
        and data['source_transition']['source_before_sha256']==data['source_sha256'],'Saved source transition differs')
    cp=data['compact_checkpoint'];current=cp['current']
    require(data['compact_checkpoint_sha256']==_digest(cp) and set(current)==set(CURRENT_KEYS)
        and current['state']==final['state'] and current['source_sha256']==saved
        and cp['settings']==final['settings'] and cp['generated_face_operation_id']==OPERATION_ID,
        'Flat final checkpoint differs')
    baseline=data['current_before'];require(set(baseline)==set(CURRENT_KEYS) and _digest(baseline)==data['current_before_sha256'],
        'Initial current checkpoint differs')
    from scripts.sw_cam_upper_cone_feature import require_state_equivalent
    require_state_equivalent(baseline['state'],data['baseline']['state'])
    require(data['baseline']['payload']==dict(rough=baseline['payload'],finish=baseline['finish_payload'])
        and data['baseline']['cone_observation']==baseline['cone_observation']
        and data['baseline']['face_observation']==baseline['face_observation'],'Fresh baseline differs from current authority')
    require(cp['toolpath_record_counts']==next(v['toolpath_record_counts'] for v in final['state']['operations'] if v['native_id']==OPERATION_ID),
        'Checkpoint generated record count differs')
    expected=deepcopy(baseline);expected.update(state=deepcopy(final['state']),source_sha256=saved)
    require(current==expected,'Undeclared compact parent change')
    parent,parentpin=read_pin(data['parent_pin']['path'],data['parent_pin']['sha256'])
    require(parent['current_after']==baseline and parent['current_after_sha256']==data['current_before_sha256']
        and parent.get('order_verified') is True and parent.get('readback_verified') is True,'Original current authority differs')
    retired=data['retired_offline'];require(len(retired)==5,'Exact offline retirement proof required')
    _check([v['pin'] for v in retired]);_check(data['live_pins'])
    require(len(data['live_pins'])==63 and all(_key(p['path'])!=_key(expected_document_path) for p in data['live_pins']),
        'Exact immutable live closure required')
    marker=group_marker(data['source_path'],data['source_sha256'])
    marker_data,markerpin=read_pin(str(marker),data['group_marker_pin']['sha256'])
    require(_key(data['receipt_path'])==_key(path),'Current receipt identity differs')
    expected_marker=GroupJournal(data,data['receipt_path'],marker)._marker_state()
    require(marker_data==expected_marker and data['group_marker_pin']['path']==str(marker.resolve()),'Stable group marker differs')
    live=[p for p in data['live_pins'] if _key(p['path'])!=_key(parentpin['path'])]
    require(len(live)==62,'Only previous completed current receipt may retire')
    live=_pins(live,[pin,markerpin]);require(len(live)==64,'Terminal live closure must remain64')
    historical_marker=data['historical_move_marker_pin']
    require(any(_key(p['path'])==_key(historical_marker['path']) and p['sha256']==historical_marker['sha256'] for p in live),
        'Original uncertain Move marker must remain live')
    generated=[p for p in live if Path(p['path']).name.startswith('_FE488661_')]
    require(len(generated)==1,'Generated native library missing')
    if check_current_source:require(_file_hash(expected_document_path)==saved,'Saved source changed')
    return dict(current,pins=live,current_context_sha256=_digest(current),parent_pin=pin,group_receipt=data,
        group_marker_pin=markerpin,generated_pin=generated[0],settings=deepcopy(cp['settings']),
        generated_face_operation_id=OPERATION_ID,toolpath_record_counts=deepcopy(cp['toolpath_record_counts']),
        retired_offline=deepcopy(retired),historical_move_marker_pin=data['historical_move_marker_pin'])


PARAMS={'parent_receipt_path','parent_receipt_sha256','plan_path','plan_sha256','process_id',
    'expected_document_path','expected_source_sha256','receipt_path','addin_clsid','module_sha256'}


def validate_request(request):
    import re
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='configure_generate_save_face',
        'Only one grouped existing-FACE workflow supported')
    p=dict(request['params']);require(set(p)==PARAMS,'Exact grouped request fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Exact owned PID required')
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_self_pin()['sha256'] and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),
        'Exact module and native CLSID required')
    return p


def prepare_request(request):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    p=validate_request(request);plan,planpin=read_pin(p['plan_path'],p['plan_sha256']);policy=validate_plan(plan)
    loaded=load_group_parent(p['parent_receipt_path'],p['parent_receipt_sha256'],
        **{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
    marker=group_marker(p['expected_document_path'],p['expected_source_sha256']);_fresh(loaded,p['receipt_path'],marker)
    report=dict(schema_version=1,scope=SCOPE,status='prepared',phase='preflight',module_pin=_self_pin(),
        process_id=p['process_id'],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
        receipt_path=p['receipt_path'],recipe_sha256=p['plan_sha256'],recipe_pin=planpin,policy=policy,
        parent_pin=loaded['parent_pin'],current_before=current_projection(loaded),current_before_sha256=loaded['current_context_sha256'],
        live_pins=deepcopy(loaded['pins']),retired_offline=deepcopy(loaded['retired_offline']),
        historical_move_marker_pin=loaded['historical_move_marker_pin'],parent_validation=loaded['parent_validation'])
    return p,loaded,report,marker


def execute_native(sw,clsid,typelib_path,*,params,loaded,report,marker):
    journal=GroupJournal(report,params['receipt_path'],marker)
    backend=NativeBackend(loaded,params,sw,clsid,typelib_path,report,journal.persist)
    result=run_grouped_backend(backend,journal)
    if result.get('readback_verified') is True:
        result['compact_checkpoint_sha256']=_digest(result['compact_checkpoint'])
        # Marker is already terminal; pin it without modifying its stable state.
        result['group_marker_pin']=_pin(marker);journal.persist()
        require(result['group_marker_pin']['sha256']==_file_hash(marker),'Final marker pin changed')
    return result


def dispatch_request(request):
    p,loaded,report,marker=prepare_request(request)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        _check(loaded['pins']);inventory=discover_cam_installations();require(not inventory['errors'],'Installation discovery errors')
        registration=select_registration(inventory,p['addin_clsid'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute_native(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),
            params=p,loaded=loaded,report=report,marker=marker)


def main(argv=None):
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    args=parser.parse_args(argv);result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({k:result.get(k) for k in ('scope','status','phase','model_saved','readback_verified','reason','issue','receipt_path')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1
if __name__=='__main__':raise SystemExit(main())
