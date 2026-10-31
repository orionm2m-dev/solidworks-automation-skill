"""Read-only CL export of a saved generated eight-operation MILL route.

Reuses the guarded machine-wide CL core and established bounded readers. Native
profiles and prior rough/finish parameters are reused from the saved checkpoint;
headers, scalar catalogue, FACE settings and selected Contour settings are fresh.
No CAD edit, tool edit, assignment, generation or model save is performed.
"""
from copy import deepcopy
from pathlib import Path
import importlib
import json
import re
from scripts import sw_cam_checkpoint_exports as common
from scripts import sw_cam_chamfer_insert_defaults as prior
from scripts import sw_cam_chamfer_defaults as defaults
from scripts import sw_cam_taper_tool_candidate as tool_reader
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_cl_inventory import verify_export_operation_inventory

group = prior.group
SCOPE = 'SAVED_CONTOUR_ROUTE_CL_EXPORT_V1'
PREFIX = [143, 144, 195, 196, 267, 247, 248]
UNGENERATED = [143, 144, 195, 196]
REUSED_SCOPE = ['rough_finish_parameters', 'all_tool_profiles', 'holder_profiles',
                'full_CAD_BRep', 'saved_sketch_contours']
FRESH_SCOPE = ['document_identity', 'machine_stock_headers', 'CAD_body_fingerprints',
               'feature_headers', 'operation_headers', 'scalar_tool_catalogue',
               'FACE_settings', 'units', 'selected_Contour_settings', 'selected_feature_taper']


def operation_contract(loaded):
    state, target = loaded['state'], loaded['configured_contour']
    oid, fid, tid = target['native_id'], target['feature_native_id'], target['tool_native_id']
    require(type(oid) is int and oid not in PREFIX and type(fid) is int and type(tid) is int,
            'Unique actual selected Contour identity required')
    require(len(state['features']) == 21 and state['operation_count'] == 8
        and [v['native_id'] for v in state['operations']] == PREFIX + [oid]
        and state['document']['needs_save'] is False, 'Exact saved clean eight-operation route required')
    require(target['generated'] is True and target['operation_type'] == 1,
            'Saved generated Contour required')
    row = state['operations'][-1]
    require(row['linked_feature_ids'] == [fid] and row['mill_operation_type'] == 1
        and row['setup_native_id'] == 93 and row['setup_index'] == 0 and row['operation_index'] == 7
        and row['assigned_tool']['native_id'] == tid == loaded['local_tool_candidate']['native_id']
        and row['assigned_tool']['tool_type_raw'] == 8, 'Saved Contour/tool/setup binding differs')
    counts = deepcopy(target['record_counts'])
    contract = [dict(operation_native_id=267, toolpath_record_counts=[760]),
        dict(operation_native_id=247, toolpath_record_counts=[191]),
        dict(operation_native_id=248, toolpath_record_counts=[74]),
        dict(operation_native_id=oid, toolpath_record_counts=counts)]
    verify_export_operation_inventory(state['operations'], oid, counts, UNGENERATED, contract)
    return contract


def validate_catalogue_authority(loaded):
    current = loaded['operation_checkpoint']['final_observation']['tools']
    # The earlier rough-tool payload contains pre-replacement metadata for
    # unassigned tools. The completed taper-tool checkpoint is the qualified
    # before/after authority for the current entire catalogue.
    historical = loaded['tool_checkpoint']['initial_observation']['tools']
    qualified = loaded['tool_checkpoint']['final_observation']['tools']
    inserted = loaded['insertion_checkpoint']['final_observation']['tools']
    tid = loaded['configured_contour']['tool_native_id']
    require(len(historical) == 17 and len(current) == 18
        and len({v['native_id'] for v in current}) == 18
        and group.exact(current, qualified) and group.exact(current, inserted)
        and group.exact([v for v in current if v['native_id'] != tid], historical),
        'Exact saved eighteen-tool catalogue with protected seventeen required')
    selected = [v for v in current if v['native_id'] == tid]
    candidate = loaded['local_tool_candidate']
    require(len(selected) == 1 and selected[0]['tool_type_raw'] == candidate['tool_type_raw'] == 8
        and all(group.exact(selected[0][k], candidate['parameters'][k])
                for k in ('CutDiameter', 'Protrusion', 'StnNo')),
        'Current selected scalar tool metadata differs from qualified profile authority')
    return deepcopy(current)


def derive_closure(loaded):
    # These completed writers/profile evaluators are validated offline; none of
    # their functions are executed by the read-only export path below.
    retired_names = {'sw_cam_chamfer_generate.py', 'sw_cam_ud14_save.py',
        'sw_cam_taper_profile.py', 'sw_cam_ud14_qualification.py', 'sw_cam_shared_holder_geometry.py'}
    retired = [p for p in loaded['pins'] if Path(p['path']).name in retired_names]
    require({Path(p['path']).name for p in retired} == retired_names,
            'Exact inactive completed-writer/profile phase roles required')
    added = [common._pin(__file__)] + [common._pin(importlib.import_module('scripts.' + n).__file__)
        for n in ('sw_cam_mill_generic_cl', 'sw_cam_cl_inventory',
                  'sw_cam_thread_postprocess', 'sw_cam_operation_profile')]
    live = common._merge([p for p in loaded['pins'] if p not in retired], added)
    offline = common._merge(loaded['offline_export_proof_pins'], retired)
    require(len(live) <= 64, 'Read-only live dependency bound exceeded')
    common._check(live); common._check(offline)
    return live, offline, retired


def load_checkpoint(path, sha256, *, process_id, expected_document_path, expected_source_sha256):
    from scripts.sw_cam_chamfer_generate import load_completed
    loaded = load_completed(path, sha256, process_id=process_id,
        expected_document_path=expected_document_path, expected_source_sha256=expected_source_sha256)
    require(loaded['authority_kind'] == 'saved_generated_contour_geometry_review_pending',
            'Completed single-target generation authority required')
    operation_contract(loaded); validate_catalogue_authority(loaded)
    live, offline, retired = derive_closure(loaded)
    result = dict(loaded, pins=live, offline_export_proof_pins=offline,
        export_phase_retired_pins=retired, export_parent_pins=deepcopy(loaded['pins']))
    require(_digest(group.current_projection(result)) == loaded['current_context_sha256'],
            'Read-only cutover changed saved context')
    return result


def marker_path(source, source_sha256, operation_id):
    key = _digest(dict(scope=SCOPE, source=common._key(source), source_sha256=source_sha256,
                      operation_native_id=operation_id))
    return common.local_evidence_root() / ('contour_cl_' + key + '.json')


def fresh_paths(loaded, args):
    marker = marker_path(args['expected_document_path'], args['expected_source_sha256'],
                         loaded['configured_contour']['native_id'])
    receipt = Path(args['receipt_path']); observation = receipt.with_suffix('.observations.json')
    protected = {common._key(p['path']) for p in loaded['pins'] + loaded['offline_export_proof_pins']
                 + loaded['bootstrap_export_pins']}
    protected.add(common._key(args['expected_document_path']))
    paths = (receipt, observation, marker)
    for path in paths:
        require(path.is_absolute() and path.suffix.casefold() == '.json' and path.parent.is_dir()
            and not path.exists() and not path.is_symlink(), 'Fresh export evidence and once marker required')
    require(len({common._key(p) for p in paths}) == 3
        and not protected.intersection({common._key(p) for p in paths}), 'Export evidence alias')
    return marker, observation


class Evidence:
    def __init__(self, loaded, args):
        self.loaded, self.args = loaded, dict(args)
        self.marker, self.observation = fresh_paths(loaded, args)
        self.created = self.claimed = False
        self.marker_signature = None
        self.details = dict(scope=SCOPE, parent_pin=deepcopy(loaded['parent_pin']),
            generated_marker_pin=deepcopy(loaded['group_marker_pin']),
            source_sha256=args['expected_source_sha256'], live_pins=deepcopy(loaded['pins']),
            offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
            fresh_fields=FRESH_SCOPE, reused_fields=REUSED_SCOPE, observations=[])
    def persist_observations(self):
        _write_receipt(self.observation, self.details, create=not self.created)
        self.created = True
    def marker_state(self, report):
        return dict(scope=SCOPE, source=self.args['expected_document_path'],
            source_sha256=self.args['expected_source_sha256'],
            operation_native_id=self.loaded['configured_contour']['native_id'],
            parent_pin=deepcopy(self.loaded['parent_pin']), receipt_path=self.args['receipt_path'],
            observation_path=str(self.observation), status=report.get('status'), phase=report.get('phase'),
            native_call_attempted=report.get('native_call_attempted', False),
            native_call_returned=report.get('native_call_returned', False),
            native_dispatch_pending=report.get('native_dispatch_pending', False),
            readback_verified=report.get('readback_verified', False), automatic_replay=False)
    def claim(self, report):
        common._check(self.loaded['pins'])
        _write_receipt(self.marker, self.marker_state(report), create=True)
        self.claimed = True
    def persist(self, report):
        if self.claimed:
            state = self.marker_state(report)
            signature = _digest({k:v for k,v in state.items() if k != 'phase'})
            if signature != self.marker_signature:
                _write_receipt(self.marker, state); self.marker_signature = signature
    def fields(self):
        return dict(scope=SCOPE, checkpoint_export_scope=SCOPE, checkpoint_export_action='export_cl',
            saved_checkpoint_pin=deepcopy(self.loaded['parent_pin']), marker_path=str(self.marker),
            observations_path=str(self.observation), evidence_pins=deepcopy(self.loaded['pins']),
            offline_export_proof_pins=deepcopy(self.loaded['offline_export_proof_pins']),
            export_phase_retired_pins=deepcopy(self.loaded['export_phase_retired_pins']),
            bootstrap_export_pins=deepcopy(self.loaded['bootstrap_export_pins']),
            bootstrap_validation=deepcopy(self.loaded.get('bootstrap_validation')),
            fresh_fields=FRESH_SCOPE, reused_fields=REUSED_SCOPE,
            full_tool_profile_capture_count=0, GTP_attempted=False, GOP_attempted=False,
            model_saved=False, assignment_attempted=False, setter_attempted=False, automatic_replay=False)


def verify_observed(loaded, observed):
    from scripts.sw_cam_upper_cone_feature import require_state_equivalent
    diagnostic = {}
    normalized = require_state_equivalent(loaded['state'], observed['state'], diagnostic=diagnostic)
    operation_contract(dict(loaded, state=normalized))
    require(group.exact(observed['catalogue'], validate_catalogue_authority(loaded)),
            'Current scalar catalogue differs')
    require(group.exact(observed['selected_defaults'], loaded['configured_contour']['defaults']),
            'Saved selected Contour settings changed')
    defaults.validate_defaults(observed['selected_defaults'])
    require(group.exact(observed['settings'], loaded['settings'])
        and group.exact(observed['units'], loaded['finish_payload']['unit_record'])
        and group.exact(observed['binding'], next(v['assigned_tool'] for v in loaded['state']['operations']
                                               if v['native_id'] == 267)),
        'Protected FACE parameters, binding or metric scope changed')
    require(group.exact(observed['selected_feature'], loaded['cone_observation']['feature']),
            'Selected feature header or taper changed')
    return normalized, diagnostic


class ReadBackend(prior.NativeBackend):
    """Only bounded inherited readers; the CL core owns bootstrap and events."""
    def __init__(self, *args, external_events, **kwargs):
        self.external_events = external_events
        super().__init__(*args, **kwargs)
    def events(self, active=True):
        self.external_events(active)
    def capture_export(self, label):
        self.boundary()
        diagnostic = dict(phase=label)
        self.report.setdefault('header_observations', []).append(diagnostic); self.persist()
        try:
            state, native = self.capture._capture_headers(self.ctx, self.clsid, self.loaded['state'], 21, diagnostic)
            self.native, self.current_state = native, deepcopy(state)
            with self.ctx.guard() as g:
                self.crib = g.typed(g.read(native['machine'], 'IGetToolcrib'), 'ICWToolcrib4')
            selected = self.read_settings(label)
            _, feature = self.selected_feature()
            catalogue = self.catalogue()
            contour = self.operation_defaults(self.loaded['configured_contour']['native_id'], label)
            return dict(state=state, catalogue=catalogue, selected_defaults=contour,
                        selected_feature=feature, **selected)
        finally:
            self.persist()


class CLContext:
    def __init__(self, loaded, args, sw, clsid, typelib_path):
        self.loaded, self.args = loaded, dict(args)
        self.evidence = Evidence(loaded, args)
        self.check = None
        reader_args = dict(args, feature_native_id=loaded['configured_contour']['feature_native_id'])
        self.backend = ReadBackend(loaded, reader_args, sw, clsid, typelib_path,
            self.evidence.details, self.evidence.persist_observations,
            external_events=lambda active: self.check(active=active))
    def identity(self, sw):
        self.backend.ctx.files()
        return self.backend.ctx.identity()
    def report_fields(self):
        return self.evidence.fields()
    def validate(self, **request):
        from scripts.sw_cam_mill_generic_cl import validate_mill_cl_request
        require(request['action'] == 'apply' and request['acknowledge_machine_scope'] is True,
                'Explicit machine-wide export required')
        prepared = dict(request, action='prepare', expected_state_sha256=None, receipt_path=None,
                        expected_generated_operations=operation_contract(self.loaded))
        validate_mill_cl_request(**prepared)
    def selected(self, state, feature_id, operation_id, operation_type):
        target = self.loaded['configured_contour']
        require((feature_id, operation_id, operation_type) ==
            (target['feature_native_id'], target['native_id'], 1), 'Selected export identity changed')
        operation_contract(dict(self.loaded, state=state))
        return next(v for v in state['operations'] if v['native_id'] == operation_id)
    def verify_before(self, snapshot):
        require(group.exact(snapshot['mill_state'], self.loaded['state']), 'Export differs from saved checkpoint')
    def capture(self, sw, clsid, typelib_path, app, check, diagnostic):
        self.check = check; self.backend.ctx.app = app
        observed = self.backend.capture_export(diagnostic['phase'])
        self.evidence.details['observations'].append(deepcopy(observed))
        self.evidence.persist_observations()
        normalized, comparison = verify_observed(self.loaded, observed)
        diagnostic.update(saved_checkpoint_match_verified=True, comparison=comparison,
                          raw_observation=deepcopy(observed))
        return normalized, self.backend.native
    def claim(self, report):
        self.backend.boundary(); self.evidence.claim(report)
    def persist(self, report):
        self.evidence.persist(report)


def export_cl(sw, clsid, typelib_path, *, loaded, args, output_path):
    from scripts.sw_cam_mill_generic_cl import export_mill_generic_cl
    context = CLContext(loaded, args, sw, clsid, typelib_path)
    target = loaded['configured_contour']
    result = export_mill_generic_cl(sw, clsid, typelib_path,
        **{k:args[k] for k in ('process_id','expected_document_path','expected_source_sha256',
            'qualification_only','acknowledge_disposable_copy','message_policy','receipt_path')},
        expected_feature_native_id=target['feature_native_id'], expected_operation_native_id=target['native_id'],
        expected_mill_operation_type=1, expected_toolpath_record_counts=target['record_counts'],
        expected_ungenerated_operation_ids=UNGENERATED, expected_generated_operations=operation_contract(loaded),
        acknowledge_machine_scope=True, action='apply', output_path=output_path, _context_adapter=context)
    if context.evidence.created:
        bounded = group.return_observation(result.get('native_hresult'))
        context.evidence.details['core_return_observation'] = bounded
        result['bounded_native_hresult'] = deepcopy(bounded)
        if not bounded['value_recorded']:
            result['native_hresult'] = None
        context.evidence.persist_observations()
    try:
        common._check(loaded['offline_export_proof_pins']); common._check(loaded['bootstrap_export_pins'])
        context.backend.ctx.files()
        result['phase_proofs_verified_after_export'] = True
        if result.get('phase') == 'finished' and result.get('readback_verified') is True and result.get('output_verified') is True:
            require(context.evidence.claimed, 'Successful export requires consumed marker')
            require(context.backend.ctx.identity() == loaded['state']['document'], 'Export cleanup changed document')
            result['checkpoint_export_readback_verified'] = True
    except Exception as exc:
        from scripts.sw_cam import _error
        result.update(status='uncertain', phase_proofs_verified_after_export=False,
            checkpoint_export_readback_verified=False, readback_verified=False, output_verified=False,
            phase_proof_error=_error(exc))
    if context.evidence.claimed:
        context.persist(result)
    if Path(args['receipt_path']).is_file():
        _write_receipt(args['receipt_path'], result)
    return result


PARAMS = common.COMMON | {'output_path'}


def validate_request(request):
    require(type(request) is dict and set(request) == {'action','params'} and request['action'] == 'export_cl',
            'Only saved-route CL export allowed')
    p = request['params']
    require(type(p) is dict and set(p) == PARAMS, 'Exact export request fields required')
    require(type(p['process_id']) is int and 0 < p['process_id'] < 2**32, 'Positive owned PID required')
    for key, value in p.items():
        if key.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'Strict SHA256 required')
        if key.endswith('path'):
            require(type(value) is str and Path(value).is_absolute(), 'Absolute path required')
    require(p['module_sha256'] == _file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['acknowledge_machine_scope'] is True
        and p['message_policy'] == 'vendor_default', 'Explicit qualified read-only export required')
    require(type(p['addin_clsid']) is str and re.fullmatch(
        r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', p['addin_clsid']), 'Exact CAM CLSID required')
    return deepcopy(p)


def dispatch_request(request, *, validate_only=False):
    params = validate_request(request)
    identity = {k:params[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    loaded = load_checkpoint(params['checkpoint_receipt_path'], params['checkpoint_receipt_sha256'], **identity)
    args = {k:params[k] for k in ('process_id','expected_document_path','expected_source_sha256',
        'receipt_path','qualification_only','acknowledge_disposable_copy','message_policy')}
    common._local_receipt(args['receipt_path']); fresh_paths(loaded, args)
    from scripts.sw_cam_mill_generic_cl import validate_mill_cl_request
    target = loaded['configured_contour']
    validate_mill_cl_request(**{k:args[k] for k in ('process_id','expected_document_path',
        'expected_source_sha256','qualification_only','acknowledge_disposable_copy','message_policy')},
        expected_feature_native_id=target['feature_native_id'], expected_operation_native_id=target['native_id'],
        expected_mill_operation_type=1, expected_toolpath_record_counts=target['record_counts'],
        expected_ungenerated_operation_ids=UNGENERATED, expected_generated_operations=operation_contract(loaded),
        action='prepare', acknowledge_machine_scope=True, output_path=params['output_path'])
    if validate_only:
        return dict(status='validated_offline', native_called=False, live_pin_count=len(loaded['pins']),
                    generated_operation_contract=operation_contract(loaded))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=args['process_id']):
        common._check(loaded['pins']); common._check(loaded['offline_export_proof_pins'])
        registration = common.discover_export_registration(loaded, params['addin_clsid'])
        sw, _ = connect_solidworks(process_id=args['process_id'], launch_new_instance=False, wait_seconds=1)
        typelib = str(Path(registration['addin_path']).parent/'camworks.tlb')
        return export_cl(sw, registration['clsid'], typelib, loaded=loaded, args=args, output_path=params['output_path'])


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True); parser.add_argument('--validate-only', action='store_true')
    options = parser.parse_args(argv)
    result = dispatch_request(json.loads(Path(options.request).read_text(encoding='utf-8-sig')),
                              validate_only=options.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','marker_path','native_called')}, ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status') == 'validated_offline' else 1


if __name__ == '__main__':
    raise SystemExit(main())
