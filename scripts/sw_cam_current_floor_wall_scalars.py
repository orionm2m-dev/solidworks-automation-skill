"""Bounded lengths/feed-plane read at the exact current saved partial terminal.

No complete CAD/stock/CL capture. The other saved operations are historical pins,
never represented as freshly observed. Requires the shared strict partial binder.
"""
from copy import deepcopy
from pathlib import Path
import math
import hashlib
import json

SCOPE = 'CURRENT_SAVED_PARTIAL_TERMINAL_FLOOR_WALL_SCALARS_V1'
AUTHORITY_KEYS = frozenset({'process_id', 'expected_process_create_time',
    'expected_document_path', 'expected_source_sha256', 'generation_receipt_path',
    'generation_receipt_sha256', 'qualification_only', 'message_policy'})
KEYS = AUTHORITY_KEYS | {'receipt_path', 'floor_operation_native_id', 'wall_operation_native_id'}
LENGTHS = (('feed_length_native', 'ToolpathFeedLength', 7),
           ('rapid_length_native', 'ToolpathRapidLength', 9),
           ('total_length_native', 'ToolpathTotalLength', 11))
PLANES = (('ICWNCParam3', 'FeedPlaneType', 'long', 24, True),
          ('ICWNCParam3', 'FeedPlaneDistance', 'double', 25, True),
          ('ICWNCParam4', 'GetUseCurrentMachiningDepthForFeedPlane', 'bool', 41, False))
EXTRA_IIDS = {'ICWNCParam3': '{32880B43-2E9A-4143-9C71-8053A1336CA5}',
              'ICWNCParam4': '{3DC6FB05-9C9F-42A4-8532-F1B7892CF3AA}'}
INTERFACES = {'ICWDoc3', 'ICWPartDoc', 'ICWMachine', 'ICWOperation',
    'ICWMillOperation', 'ICWFeature', 'ICWTool', 'ICWToolpath',
    'ICWBaseOpSetup', 'ICWDispatchCollection'} | set(EXTRA_IIDS)
GETTERS = {'IGetActiveDoc', 'GetDocType', 'IGetMachine', 'MachType',
    'IGetEnumOpSetups', 'IGetEnumOperations', 'GetCWObjectFromID', 'GetCWObjectID',
    'Count', 'Item', 'IGetAllFeatures', 'OpernType', 'Suppressed',
    'GetIsToolpathGenerated', 'IGetEnumToolpaths', 'RecordCount', 'IGetTool',
    'IsMillTool', 'IGetNCParam'} | {x[1] for x in LENGTHS} | {x[1] for x in PLANES}
MAX_READS = 512


def require(value, message):
    if not value: raise ValueError(message)


def exact(a, b):
    if type(a) is not type(b): return False
    if type(a) is dict: return a.keys() == b.keys() and all(exact(a[k], b[k]) for k in a)
    if type(a) in (tuple, list): return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b))
    return a == b


def target_projection(row):
    return dict(native_id=row['native_id'], setup_native_id=row['setup_native_id'],
        linked_feature_ids=deepcopy(row['linked_feature_ids']),
        mill_operation_type=row['mill_operation_type'], base_operation_type=row['base_operation_type'],
        suppressed=row['suppressed'], toolpath_generated=row['toolpath_generated'],
        toolpath_record_counts=deepcopy(row['toolpath_record_counts']),
        tool_native_id=row['assigned_tool']['native_id'])


def selected_authority(state, floor_id, wall_id):
    require(type(state) is dict and type(state.get('operations')) is list
            and 2 <= len(state['operations']) <= 128, 'Bounded saved operation authority required')
    require(type(floor_id) is int and floor_id > 0 and type(wall_id) is int
            and wall_id > 0 and floor_id != wall_id, 'Two distinct strict operation IDs required')
    pair = state['selected_pair_observations']['targets']
    require(sum(x.get('operation_native_id') == floor_id for x in pair) == 1,
            'Floor must belong to the saved selected pair')
    selected = {}
    for ident, kind in ((floor_id, 0), (wall_id, 1)):
        rows = [r for r in state['operations'] if type(r.get('native_id')) is int and r['native_id'] == ident]
        require(len(rows) == 1, 'One exact saved target required')
        row = target_projection(rows[0])
        require(type(row['mill_operation_type']) is int and row['mill_operation_type'] == kind
                and type(row['base_operation_type']) is int and row['base_operation_type'] == 0
                and row['suppressed'] is False and row['toolpath_generated'] is True
                and type(row['setup_native_id']) is int and row['setup_native_id'] > 0
                and type(row['tool_native_id']) is int and row['tool_native_id'] > 0
                and type(row['linked_feature_ids']) is list and len(row['linked_feature_ids']) == 1
                and type(row['linked_feature_ids'][0]) is int and row['linked_feature_ids'][0] > 0
                and type(row['toolpath_record_counts']) is list and len(row['toolpath_record_counts']) == 1
                and type(row['toolpath_record_counts'][0]) is int and 0 < row['toolpath_record_counts'][0] <= 100000,
                'Exact positive saved Rough/Finish role required')
        selected[ident] = row
    return selected


def validate(v):
    from scripts import sw_cam_current_saved_finish_read_authority as authority
    from scripts.sw_cam_thread import _file_hash
    require(type(v) is dict and set(v) == KEYS, 'Exact grouped scalar request required')
    data = authority.load_saved_boundary({k: deepcopy(v[k]) for k in AUTHORITY_KEYS})
    require(data['authority_scope'] == 'CURRENT_SAVED_PARTIAL_TERMINAL_READ_AUTHORITY_V1', 'Exact saved partial binder required')
    state = data['recovery_saved_state']
    require(type(v['wall_operation_native_id']) is int and v['wall_operation_native_id'] == data['saved_boundary_proof']['operation_id'], 'Wall must be the verified saved boundary operation')
    selected = selected_authority(state, v['floor_operation_native_id'], v['wall_operation_native_id'])
    receipt = Path(v['receipt_path'])
    require(receipt.is_absolute() and receipt.suffix.lower() == '.json' and receipt.parent.is_dir()
            and not receipt.exists() and not receipt.is_symlink(), 'Fresh absolute read receipt required')
    pins = deepcopy(data['pins'])
    pins += [dict(path=str(Path(x).resolve()), sha256=_file_hash(x)) for x in (__file__, authority.__file__)]
    unique = {}
    for pin in pins:
        key = str(Path(pin['path']).resolve()).casefold()
        require(key not in unique or unique[key]['sha256'] == pin['sha256'], 'Conflicting immutable pin')
        unique[key] = pin
    require(str(receipt.resolve()).casefold() not in unique, 'Receipt aliases evidence')
    require(data['generation_receipt']['status'] == 'uncertain', 'Original terminal status must remain uncertain')
    membership = {sid: [row['native_id'] for row in state['operations'] if row['setup_native_id'] == sid]
        for sid in {row['setup_native_id'] for row in selected.values()}}
    return dict(data=data, state=state, selected=selected, membership=membership, pins=list(unique.values()), receipt=receipt)


_ISSUER = object()
class _Prepared:
    def __init__(self, v, loaded):
        self.issuer = _ISSUER; self.v = deepcopy(v); self.loaded = deepcopy(loaded)
        self.used = False; self.digest = self.fingerprint()
    def fingerprint(self):
        raw = json.dumps(dict(v=self.v, loaded=self.loaded), sort_keys=True, allow_nan=False, default=str)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def _prepare_invocation(v, *, runtime_check):
    runtime_check(); loaded = validate(v); runtime_check()
    return _Prepared(v, loaded)

def _consume(prepared, v, runtime_check):
    from scripts.sw_cam_thread import _file_hash
    require(type(prepared) is _Prepared and prepared.issuer is _ISSUER and prepared.used is False,
            'Private unused prepared read bundle required')
    prepared.used = True
    require(exact(prepared.v, v) and prepared.fingerprint() == prepared.digest,
            'Prepared current authority changed')
    runtime_check()
    for pin in prepared.loaded['pins']:
        require(_file_hash(pin['path']) == pin['sha256'], 'Prepared immutable evidence changed')
    receipt = prepared.loaded['receipt']
    require(receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),
            'Fresh read receipt changed before admission')
    runtime_check(); return prepared.loaded


def preflight(tlb):
    from ctypes import HRESULT, POINTER, c_double, c_long
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _load_type_library, _interface_class
    library = _load_type_library(str(tlb)); classes = {}
    for name in INTERFACES:
        cls = getattr(library, name) if name in EXTRA_IIDS else _interface_class(name, str(tlb))
        if name in EXTRA_IIDS: require(str(cls._iid_).upper() == EXTRA_IIDS[name], 'Exact NC extension IID required')
        classes[name] = cls
    types = {'long': c_long, 'double': c_double, 'bool': VARIANT_BOOL}
    specs = [('ICWOperation', name, dispid, (POINTER(c_double),), True) for _, name, dispid in LENGTHS]
    specs += [(i, n, d, (POINTER(types[k]),), prop) for i, n, k, d, prop in PLANES]
    specs += [('ICWMillOperation', 'IGetNCParam', 7, (POINTER(POINTER(IDispatch)),), False)]
    rows = []
    for interface, name, dispid, args, prop in specs:
        methods = [m for m in classes[interface]._methods_ if m.name == ('_get_' + name if prop else name)]
        require(len(methods) == 1, 'One exact getter declaration required: ' + name)
        m = methods[0]
        require(m.restype is HRESULT and int(m.idlflags[0]) == dispid and m.argtypes == args
                and tuple(p[0] for p in m.paramflags) == (10,)
                and ('propget' in m.idlflags) is prop, 'Getter ABI differs: ' + name)
        rows.append(dict(interface=interface, member=name, dispid=dispid, property=prop))
    return classes, dict(native_calls=0, application_connections=0, getters_only=True, members=rows)


def items(raw, read, typed, limit):
    collection = typed(raw, 'ICWDispatchCollection'); count = read(collection, 'Count')
    require(type(count) is int and 0 <= count <= limit, 'Bounded strict collection count required')
    return [read(collection, 'Item', index) for index in range(count)]


def observe_targets(doc, machine, selected, membership_expected, *, read, typed):
    from scripts.sw_cam_thread import _object_id
    def oid(obj): return _object_id(doc, obj, read)
    owners = {}
    for raw in items(read(machine, 'IGetEnumOpSetups'), read, typed, 8):
        ident = oid(raw)
        if ident in membership_expected:
            require(ident not in owners, 'Duplicate selected setup ID')
            owners[ident] = typed(raw, 'ICWBaseOpSetup')
    require(set(owners) == set(membership_expected), 'Exact selected operation setups required')
    for ident, owner in owners.items():
        membership = [oid(raw) for raw in items(read(owner, 'IGetEnumOperations'), read, typed, 128)]
        require(exact(membership, membership_expected[ident]), 'Current selected setup membership differs')
    rows, handles = {}, {}
    for ident, expected in selected.items():
        found = read(doc, 'GetCWObjectFromID', 3, ident)
        require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True, 'Exact operation lookup required')
        op = typed(found[0], 'ICWOperation'); mill = typed(found[0], 'ICWMillOperation')
        tool = typed(read(op, 'IGetTool'), 'ICWTool')
        require(read(tool, 'IsMillTool') is True, 'Exact mill tool required')
        row = dict(native_id=oid(op), setup_native_id=expected['setup_native_id'],
            linked_feature_ids=[oid(x) for x in items(read(op, 'IGetAllFeatures'), read, typed, 2)],
            mill_operation_type=read(mill, 'OpernType'), base_operation_type=read(op, 'OpernType'),
            suppressed=read(op, 'Suppressed'), toolpath_generated=read(op, 'GetIsToolpathGenerated'),
            toolpath_record_counts=[read(typed(x, 'ICWToolpath'), 'RecordCount')
                for x in items(read(op, 'IGetEnumToolpaths'), read, typed, 1)], tool_native_id=oid(tool))
        require(exact(row, expected), 'Fresh selected operation binding differs')
        rows[ident] = row; handles[ident] = op
    return rows, handles


def scalar(kind, value):
    require((type(value) is int and -(2**31) <= value < 2**31) if kind == 'long' else
            (type(value) is float and math.isfinite(value)) if kind == 'double' else
            type(value) is bool, 'Strict finite feed-plane scalar required')
    return value


def observe_values(handles, *, read, typed, progress):
    """Exactly twelve length and six feed-plane getters; no implicit retry."""
    result = dict(first={}, feed_planes={}, second={}, complete=False)
    for passname in ('first', 'second'):
        for oid in handles:
            lengths = {}; result[passname][oid] = lengths
            for key, member, _ in LENGTHS:
                value = read(handles[oid], member)
                require(type(value) is float and math.isfinite(value) and value >= 0, 'Finite nonnegative native DOUBLE length required')
                lengths[key] = value; progress(deepcopy(result))
        if passname == 'first':
            for oid in handles:
                raw = read(typed(handles[oid], 'ICWMillOperation'), 'IGetNCParam')
                require(raw is not None and bool(raw), 'Operation-owned NC object required')
                values = {}; owners = {}; result['feed_planes'][oid] = values
                for interface, member, kind, _, _ in PLANES:
                    if interface not in owners: owners[interface] = typed(raw, interface)
                    values[member] = scalar(kind, read(owners[interface], member)); progress(deepcopy(result))
    require(exact(result['first'], result['second']), 'Repeated native length triples differ')
    result['complete'] = True; progress(deepcopy(result)); return result


def finalize_runtime_failure(result, error):
    from scripts.sw_cam import _error
    from scripts.sw_cam_generation import _write_receipt
    result.update(status='error', phase='finished', runtime_error=_error(error),
        runtime_unchanged=False, readback_verified=False, source_unchanged=False)
    _write_receipt(Path(result['receipt_path']), result); return result


def dispatch(sw, clsid, tlb, *, runtime_check, _prepared=None, **v):
    from ctypes import POINTER
    from scripts.sw_cam import _member, _error, document_snapshot
    from scripts.sw_cam_generation import _typed, _write_receipt
    from scripts.sw_cam_thread import _file_hash
    from scripts.sw_cam_events import CamMessageSession
    from scripts.sw_cam_mill_selected_plan_evidence import clean_events
    from scripts.sw_executable_launch import _process_identity
    from scripts.sw_operation_guard import check_document_target, solidworks_operation_lock
    from scripts.sw_cam_circular_nc_read import EVENT_ERRORS
    prepared = _prepared if _prepared is not None else _prepare_invocation(v, runtime_check=runtime_check)
    loaded = _consume(prepared, v, runtime_check); classes, abi = preflight(tlb); session = None
    require(loaded['data']['addin_clsid'].casefold() == clsid.casefold(), 'Exact registered CAM required')
    r = dict(scope=SCOPE, status='running', phase='preflight', request=deepcopy(v), receipt_path=v['receipt_path'],
        authority_scope=loaded['data']['authority_scope'], authority_terminal_status='uncertain',
        evidence_pins=loaded['pins'], saved_operation_count=len(loaded['state']['operations']), fresh_full_inventory=False,
        selected_operation_native_ids=list(loaded['selected']), abi=abi, native_read_count=0,
        native_read_limit=MAX_READS, read_only=True, mutation_attempted=False, save_attempted=False,
        GTP_attempted=False, GOP_attempted=False, parameter_setter_attempted=False, CL_export_attempted=False,
        WIP_export_attempted=False, readback_verified=False, source_unchanged=False, runtime_unchanged=False,
        units_semantics_verified=False, full_circle_semantics_verified=False, floor_coverage_verified=False,
        production_qualified=False, automatic_replay=False)
    def persist(): _write_receipt(loaded['receipt'], r)
    def files():
        runtime_check()
        for pin in loaded['pins']: require(_file_hash(pin['path']) == pin['sha256'], 'Pinned evidence/runtime changed')
    def identity():
        files(); p = _process_identity(v['process_id'])
        require(p.get('alive') is True and p.get('process_id') == v['process_id']
            and p.get('create_time') == v['expected_process_create_time']
            and Path(p.get('executable', '')).name.casefold() == 'sldworks.exe', 'Owned process lifetime changed')
        pid = _member(sw, 'GetProcessID'); require(type(pid) is int and pid == v['process_id'], 'Selected PID changed')
        d = document_snapshot(sw)
        require(type(d) is dict and type(d.get('type')) is int and d['type'] == 1 and d.get('needs_save') is False, 'Current clean saved part required')
        check_document_target(d['path'], d['title'], expected_path=v['expected_document_path'], required=True)
        require(_file_hash(v['expected_document_path']) == v['expected_source_sha256'], 'Current saved source changed')
        return d
    _write_receipt(loaded['receipt'], r, create=True)
    try:
        with solidworks_operation_lock(timeout_seconds=1, process_id=v['process_id']):
            initial = identity(); require(exact(initial, loaded['state']['document']), 'Current document differs from saved boundary')
            addin = _member(sw, 'GetAddInObject', clsid); require(addin is not None, 'CAM must already be loaded')
            app = _typed(_member(addin, 'GetCWApp'), 'ICWApp4', tlb)
            require(identity() == initial, 'Identity changed in bootstrap'); session = CamMessageSession(app, tlb)
            def check():
                summary = session.summary(); r['messages'] = summary
                require(summary.get('active') is True and summary.get('subscribed') is True
                    and not any(summary.get(k) for k in EVENT_ERRORS), 'CAM event requires stop')
            def boundary(): check(); require(identity() == initial, 'Current document changed'); check()
            def admission(name):
                check(); require(r['native_read_count'] < MAX_READS, 'Read budget exhausted')
                r['native_read_count'] += 1; r['phase'] = name; r['last_attempted_read'] = name
                r['native_dispatch_pending'] = True; persist()
            def read(owner, name, *args):
                require(name in GETTERS, 'Getter outside grouped scalar scope'); admission(name)
                try: value = _member(owner, name, *args)
                except Exception: r['failed_read'] = name; raise
                r['last_returned_read'] = name; r['native_dispatch_pending'] = False; persist(); check(); return value
            def typed(owner, name):
                require(name in classes, 'Interface outside grouped scalar scope'); admission('QI ' + name)
                value = owner.QueryInterface(classes[name])
                require(value is not None and bool(value) and isinstance(value, POINTER(classes[name])), 'Exact native pointer required')
                r['native_dispatch_pending'] = False; persist(); check(); return value
            with session:
                doc = typed(read(app, 'IGetActiveDoc'), 'ICWDoc3'); part = typed(doc, 'ICWPartDoc')
                machine = typed(read(part, 'IGetMachine'), 'ICWMachine')
                require(type(read(doc, 'GetDocType')) is int and read(doc, 'GetDocType') == 1
                    and type(read(machine, 'MachType')) is int and read(machine, 'MachType') == 1, 'Exact MILL part required')
                boundary(); r['before'], handles = observe_targets(doc, machine, loaded['selected'], loaded['membership'], read=read, typed=typed); persist()
                boundary()
                def progress(value): r['scalars'] = value; persist()
                r['scalars'] = observe_values(handles, read=read, typed=typed, progress=progress)
                boundary(); r['after'], _ = observe_targets(doc, machine, loaded['selected'], loaded['membership'], read=read, typed=typed)
                require(exact(r['before'], r['after']), 'Selected target binding changed'); boundary(); persist()
            r['messages'] = session.summary(); clean_events(r)
            require(identity() == initial, 'Identity changed after event cleanup'); runtime_check()
            r.update(status='review_required', phase='finished', readback_verified=True,
                source_unchanged=True, runtime_unchanged=True, source_sha256=v['expected_source_sha256'],
                reason='TWO_SELECTED_LENGTH_TRIPLES_REPEATED_AND_SIX_FEED_PLANE_SCALARS_OBSERVED')
    except Exception as error:
        r.update(status='error', failed_phase=r.get('phase'), phase='finished', issue=_error(error),
            readback_verified=False, source_unchanged=False, runtime_unchanged=False, native_dispatch_pending=False)
    finally:
        if session is not None: r['messages'] = session.summary()
        persist()
    return r
