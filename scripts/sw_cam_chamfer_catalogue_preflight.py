"""Read missing finish-operation defaults for one saved circular MILL feature.

The saved checkpoint supplies verified contours. Only feature/anchor identity
and the missing catalogue are read. No creation, generation, save or selection.
"""
from copy import deepcopy
from pathlib import Path
import json
import re
from scripts import sw_cam_checkpoint_reconfigure as checkpoint
from scripts import sw_cam_grouped_face_recipe as group
from scripts import sw_cam_checkpoint_exports as exports
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_turn_tool import _digest

SCOPE = 'SAVED_MILL_CHAMFER_CATALOGUE_READ_V1'
OPERATION_TYPE = 1  # CWOPER_FINISH_MILL, not CW_OP_CONTOUR_MILL=9.
MAX_NAMES, MAX_READS = 32, 256
READ_MEMBERS = frozenset({
    'IGetActiveDoc', 'GetDocType', 'IGetMachine', 'MachType',
    'GetCWObjectFromID', 'GetCWObjectID', 'GetOwner',
    'IGetEnumOpSetups', 'IGetEnumOperations', 'Count', 'Item',
    'VolumeType', 'SubType', 'Shape', 'Suppressed', 'FeatureName', 'Axis',
    'Depth', 'GetBoundParams', 'GetStartPosition', 'Taper', 'IGetTaperAngle',
    'OpernType', 'IGetAllFeatures', 'IGetTool', 'IsMillTool', 'ToolType',
    'CutDiameter', 'Protrusion', 'GetIsToolpathGenerated', 'IGetEnumToolpaths',
    'RecordCount', 'IGetAllDefaultOperations', 'GetTdbIdForDefaultOperation',
})
INTERFACES = frozenset({
    'ICWDoc3', 'ICWPartDoc', 'ICWMachine', 'ICWFeature', 'ICWMillFeature',
    'ICWOperation', 'ICWMillOperation', 'ICWBaseOpSetup',
    'ICWDispatchCollection', 'ICWTool', 'ICWToolpath',
})
PARAMS = frozenset({
    'process_id', 'expected_document_path', 'expected_source_sha256',
    'checkpoint_receipt_path', 'checkpoint_receipt_sha256', 'module_sha256',
    'addin_clsid', 'feature_native_id', 'anchor_operation_native_id', 'receipt_path',
})


def validate_request(request):
    require(type(request) is dict and set(request) == {'action', 'params'}
            and request['action'] == 'inspect_chamfer_catalogue', 'Exact read-only action required')
    p = request['params']
    require(type(p) is dict and set(p) == PARAMS, 'Exact request fields required')
    for name in ('process_id', 'feature_native_id', 'anchor_operation_native_id'):
        require(type(p[name]) is int and 0 < p[name] < 2**31, 'Strict positive identity required')
    for name, value in p.items():
        if name.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'Full SHA256 required')
        if name.endswith('path'):
            require(type(value) is str and Path(value).is_absolute(), 'Absolute request path required')
    require(p['module_sha256'] == _file_hash(__file__), 'Preflight implementation changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(
        r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', p['addin_clsid']), 'Exact add-in CLSID required')
    return deepcopy(p)


def expected_binding(loaded, params):
    state = loaded['state']
    fid, aid = params['feature_native_id'], params['anchor_operation_native_id']
    require(type(fid) is int and type(aid) is int and fid == loaded['cone_feature_native_id'],
            'Requested feature must be the saved cone')
    features = [x for x in state['features'] if x['geometry']['native_id'] == fid]
    anchors = [x for x in state['operations'] if x['native_id'] == aid]
    require(len(features) == len(anchors) == 1, 'Unique saved feature and anchor required')
    feature, anchor = features[0], anchors[0]
    require(anchor['mill_operation_type'] == OPERATION_TYPE and anchor['suppressed'] is False
            and anchor['toolpath_generated'] is True, 'Generated finish-operation anchor required')
    siblings = [x['native_id'] for x in state['operations'] if x['setup_native_id'] == anchor['setup_native_id']]
    require(siblings and siblings[-1] == aid, 'Anchor must remain last in its setup')
    geometry = loaded['cone_observation']['feature']
    require(geometry['native_id'] == fid and geometry['taper_enabled'] is True
            and geometry['suppressed'] is False, 'Verified saved tapered contour required')
    for field, value in feature['geometry'].items():
        if field in geometry:
            require(group.exact(value, geometry[field]), 'Saved feature/contour binding differs')
    require(state['document']['needs_save'] is False, 'Clean saved document required')
    return dict(feature=deepcopy(feature), anchor=deepcopy(anchor),
        operation_setups=deepcopy(state['operation_setups']),
        order=[dict(setup_native_id=x['setup_native_id'], native_id=x['native_id']) for x in state['operations']],
        taper_enabled=geometry['taper_enabled'], taper_angle_readback=geometry['taper_angle_readback'],
        saved_contours=deepcopy(geometry), saved_contours_sha256=_digest(geometry))


def decode_catalogue(raw, lookup):
    require(type(raw) in (str, list, tuple), 'Native catalogue must be a name or bounded sequence')
    names = [raw] if type(raw) is str else list(raw)
    require(0 < len(names) <= MAX_NAMES and all(type(v) is str and 0 < len(v) <= 1000
        and '\x00' not in v for v in names), 'Bounded exact catalogue names required')
    require(len(set(names)) == len(names), 'Duplicate catalogue names are ambiguous')
    result = dict(operation_type=OPERATION_TYPE, converted_python_type=type(raw).__name__, entries=[])
    for name in names:
        value = lookup(name)
        require(type(value) is int and 0 < value < 2**31, 'Positive strict default-operation ID required')
        result['entries'].append(dict(name=name, default_operation_id=value))
    result.update(unique_default_available=len(names) == 1,
        selected_default_operation_id=None, selection_performed=False)
    return result


def prepare(params):
    identity = {k: params[k] for k in ('process_id', 'expected_document_path', 'expected_source_sha256')}
    loaded = checkpoint.load_completed(params['checkpoint_receipt_path'], params['checkpoint_receipt_sha256'], **identity)
    binding = expected_binding(loaded, params)
    # Save code cannot execute in this read-only phase. Its exact pin remains
    # checked as completed phase history; all executing code stays live.
    retired = [p for p in loaded['pins'] if Path(p['path']).name == 'sw_cam_ud14_save.py']
    require(len(retired) == 1, 'Exact completed Save implementation proof required')
    live = exports._merge([p for p in loaded['pins'] if p != retired[0]], [exports._pin(__file__)])
    require(len(live) <= 64, 'Bounded complete live closure required')
    loaded.update(pins=live, preflight_retired_pins=retired)
    loaded['offline_export_proof_pins'] = exports._merge(loaded['offline_export_proof_pins'], retired)
    exports._check(live); exports._check(loaded['offline_export_proof_pins'])
    output = Path(params['receipt_path'])
    exports._local_receipt(str(output))
    protected = [p['path'] for p in live + loaded['offline_export_proof_pins']] + [params['expected_document_path']]
    require(not output.exists() and not output.is_symlink()
            and exports._key(output) not in {exports._key(v) for v in protected}, 'Fresh nonaliased receipt required')
    report = dict(schema_version=1, scope=SCOPE, status='started', phase='prepared', read_only=True,
        native_mutation_calls=0, generation_attempted=False, model_saved=False, readback_verified=False,
        process_id=params['process_id'], source_path=params['expected_document_path'],
        source_sha256=params['expected_source_sha256'], module_pin=exports._pin(__file__),
        checkpoint_pin=deepcopy(loaded['parent_pin']), current_context_sha256=loaded['current_context_sha256'],
        expected_binding=binding, live_pins=deepcopy(live),
        offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']), native_read_calls=[])
    return loaded, binding, report


class NativeBackend(group.NativeBackend):
    def __init__(self, loaded, args, sw, clsid, typelib_path, report, persist):
        super().__init__(loaded, args, sw, clsid, typelib_path, report, persist)
        self.reads = 0

    def read(self, guard, obj, name, *args):
        require(name in READ_MEMBERS and self.reads < MAX_READS, 'Unsupported or excess read-only call')
        self.reads += 1
        self.report['native_read_calls'].append(dict(member=name, arguments=list(args) if name in
            ('GetCWObjectFromID', 'IGetAllDefaultOperations', 'GetTdbIdForDefaultOperation') else None))
        return guard.read(obj, name, *args)

    def typed(self, guard, obj, name):
        require(name in INTERFACES, 'Unsupported read-only interface')
        return guard.typed(obj, name)

    def observe(self):
        self.boundary()
        with self.ctx.guard() as g:
            read = lambda obj, name, *a: self.read(g, obj, name, *a)
            typed = lambda obj, name: self.typed(g, obj, name)
            active = read(self.ctx.app, 'IGetActiveDoc')
            doc = typed(active, 'ICWDoc3')
            kind = read(doc, 'GetDocType')
            require(type(kind) is int and kind == 1, 'CAM part required')
            machine = typed(read(typed(active, 'ICWPartDoc'), 'IGetMachine'), 'ICWMachine')
            kind = read(machine, 'MachType')
            require(type(kind) is int and kind == 1, 'MILL machine required')
            found = read(doc, 'GetCWObjectFromID', 1, self.args['feature_native_id'])
            require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True, 'Exact feature lookup required')
            expected = expected_binding(self.loaded, self.args)
            header, _ = read_header(found[0], doc, read, typed, expected['feature']['setup_native_id'])
            feature = typed(found[0], 'ICWMillFeature')
            taper, angle = read(feature, 'Taper'), read(feature, 'IGetTaperAngle')
            setups, order, anchor = [], [], None
            for index, raw_setup in enumerate(_items(read(machine, 'IGetEnumOpSetups'), typed, read, 8)):
                setup = typed(raw_setup, 'ICWBaseOpSetup')
                sid = _object_id(doc, setup, read)
                ops = _items(read(setup, 'IGetEnumOperations'), typed, read, 32)
                setups.append(dict(index=index, native_id=sid, operation_count=len(ops)))
                for oi, raw in enumerate(ops):
                    operation = typed(raw, 'ICWOperation'); oid = _object_id(doc, operation, read)
                    order.append(dict(setup_native_id=sid, native_id=oid))
                    if oid == self.args['anchor_operation_native_id']:
                        require(anchor is None, 'Duplicate anchor operation')
                        mill = typed(raw, 'ICWMillOperation')
                        links = [_object_id(doc, v, read) for v in _items(read(operation, 'IGetAllFeatures'), typed, read, 64)]
                        records = [read(typed(v, 'ICWToolpath'), 'RecordCount') for v in _items(
                            read(operation, 'IGetEnumToolpaths'), typed, read, 32)]
                        tool, _ = read_generic_tool(raw, doc, read, typed)
                        anchor = dict(setup_index=index, setup_native_id=sid, operation_index=oi,
                            native_id=oid, mill_operation_type=read(mill, 'OpernType'),
                            base_operation_type=read(operation, 'OpernType'), suppressed=read(operation, 'Suppressed'),
                            toolpath_generated=read(operation, 'GetIsToolpathGenerated'),
                            linked_feature_ids=links, toolpath_record_counts=records, assigned_tool=tool)
            self.native = dict(doc=doc, feature=feature)
            return dict(feature=dict(expected['feature'], geometry=header), anchor=anchor,
                operation_setups=setups, order=order, taper_enabled=taper, taper_angle_readback=angle)

    def catalogue(self):
        require(self.native is not None, 'Fresh bound feature required')
        with self.ctx.guard() as g:
            feature = self.native['feature']
            raw = self.read(g, feature, 'IGetAllDefaultOperations', OPERATION_TYPE)
            safe = ([raw] if type(raw) is str else list(raw) if type(raw) in (list, tuple) else [])
            self.report['catalogue_observation'] = dict(python_type=type(raw).__name__,
                names=[v[:1000] if type(v) is str else {'python_type': type(v).__name__} for v in safe[:MAX_NAMES]],
                truncated=len(safe) > MAX_NAMES, lookups=[])
            self.persist()
            def lookup(name):
                value = self.read(g, feature, 'GetTdbIdForDefaultOperation', OPERATION_TYPE, name)
                row = dict(name=name, python_type=type(value).__name__)
                if value is None or type(value) in (bool, int, str):
                    row['value'] = value if type(value) is not str else value[:1000]
                self.report['catalogue_observation']['lookups'].append(row)
                self.persist()
                return value
            return decode_catalogue(raw, lookup)


def verify_binding(expected, observed):
    wanted = {k: v for k, v in expected.items() if k not in ('saved_contours', 'saved_contours_sha256')}
    require(group.exact(wanted, observed), 'Feature, anchor or sibling order changed')


def run_backend(backend, binding, report, persist):
    try:
        backend.start()
        report['phase'] = 'binding_before'; persist()
        report['before'] = backend.observe(); verify_binding(binding, report['before']); persist()
        report['phase'] = 'catalogue'; persist()
        report['catalogue'] = backend.catalogue(); persist()
        report['phase'] = 'binding_after'
        report['after'] = backend.observe(); verify_binding(binding, report['after']); persist()
        backend.finish()
        report.update(status='observed', phase='finished', readback_verified=True,
            saved_contours_reused=True, contour_native_reads=0, full_capture_count=0,
            ready_for_mutation=False)
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], issue=_error(exc), readback_verified=False)
    finally:
        try:
            backend.close()
        except Exception as exc:
            report.update(status='uncertain', readback_verified=False, cleanup_issue=_error(exc))
        persist()
    return report


def dispatch_request(request):
    params = validate_request(request)
    loaded, binding, report = prepare(params)
    persist = lambda: _write_receipt(params['receipt_path'], report)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=params['process_id']):
        exports._check(loaded['pins']); exports._check(loaded['offline_export_proof_pins'])
        registration = exports.discover_export_registration(loaded, params['addin_clsid'])
        sw, _ = connect_solidworks(process_id=params['process_id'], launch_new_instance=False, wait_seconds=1)
        backend = NativeBackend(loaded, params, sw, registration['clsid'],
            str(Path(registration['addin_path']).parent / 'camworks.tlb'), report, persist)
        run_backend(backend, binding, report, persist)
        try:
            exports._check(loaded['pins']); exports._check(loaded['offline_export_proof_pins'])
            exports._check(loaded['bootstrap_export_pins'])
            report['phase_proofs_verified_after_read'] = True
        except Exception as exc:
            report.update(status='uncertain', readback_verified=False,
                phase_proofs_verified_after_read=False, post_read_proof_error=_error(exc))
        persist()
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    options = parser.parse_args(argv)
    result = dispatch_request(json.loads(Path(options.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({k: result.get(k) for k in ('status', 'phase', 'readback_verified', 'issue')}, ensure_ascii=False))
    return 0 if result.get('readback_verified') is True and result.get('phase_proofs_verified_after_read') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
