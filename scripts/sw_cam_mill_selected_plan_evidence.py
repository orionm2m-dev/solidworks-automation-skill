"""Immutable scoped evidence for selected MILL planning; not a full inventory gate."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes, _decode, _sha, _require
from scripts.sw_cam_mill_profile_indexed import load_profile_headers_anchor
from scripts.sw_cam_mill_inventory_recovery_evidence import load_mill_inventory_recovery_evidence
from scripts.sw_cam_mill_inventory import _same_inventory
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

SCOPE = 'MILL_SELECTED_PLAN_18_HEADERS_V1'
HEADER_KEYS = ('native_id','volume_type','subtype_raw','shape_raw','suppressed','name',
               'axis_native','depth_native','bounds_native','start_native')
BASE_KEYS = ('document','saved_file_sha256','current_machine','mill_catalogue','feature_setups',
             'material_raw','extend_holes_to_stock','unit_record_raw','unit_record_status',
             'recognition_options','recognition_method','stock','sw_reference',
             'visible_solid_body_count','all_solid_body_count')

def clean_events(data):
    s = data.get('messages', {})
    _require(s.get('subscribed') is True and s.get('disconnected') is True
             and s.get('active') is False, 'Completed clean event session required')
    _require(not any(s.get(k) for k in ('event_count','overflow','callback_errors',
        'callback_error_count','subscription_error','disconnect_errors')), 'Event errors present')

def read_pin(path, sha):
    _sha(sha)
    raw, pin = _receipt_bytes(path)
    _require(pin['sha256'] == sha, 'Pinned receipt SHA differs')
    return _decode(raw), pin

def observed_context(state):
    """Only captured headers and fingerprints; never claim unavailable contours."""
    out = {key:deepcopy(state[key]) for key in BASE_KEYS}
    out['features'] = [
        dict(setup_index=r['setup_index'], feature_index=r['feature_index'],
             setup_native_id=r['setup_native_id'],
             geometry={key:deepcopy(r['geometry'][key]) for key in HEADER_KEYS})
        for r in state['features']]
    return out

def same(a, b):
    return _same_inventory(a, b)

def protected_context(state, original_source):
    out = observed_context(state)
    out['document']['needs_save'] = False
    out['saved_file_sha256'] = original_source
    return out

def same_saved_context(before, after):
    expected = deepcopy(before)
    expected['document']['needs_save'] = after['document']['needs_save']
    expected['saved_file_sha256'] = after['saved_file_sha256']
    return same(expected, after)

class SelectedPlanEvidence:
    def __init__(self, pins, selected, header, context, indexed, recovery):
        self.pins = deepcopy(pins)
        self.selected = deepcopy(selected)
        self.header = deepcopy(header)
        self.context = deepcopy(context)
        self.indexed = deepcopy(indexed)
        self.recovery = recovery
        self.original_source = context['saved_file_sha256']

    def check_files(self):
        for pin in self.pins:
            _, current = _receipt_bytes(pin['path'])
            _require(current == pin, 'Pinned scoped evidence changed')
        self.recovery.check_files()

    def read_stock(self, wp, tlb, read, diagnostic):
        return self.recovery.read_stock(wp, tlb, read, diagnostic)

    def verify(self, state):
        _require(same(protected_context(state, self.original_source), self.context),
                 'Observed neighbor, selected header, setup, stock, option or SW context changed')
        _require(state['selected_profile_headers'] == self.header,
                 'Selected PROFILE headers differ from completed scoped anchor')
        return True

    def summary(self):
        return dict(scope=SCOPE, pins=deepcopy(self.pins), selected=deepcopy(self.selected),
                    original_source_sha256=self.original_source,
                    diagnostic_baseline_promoted=False, full_inventory_verified=False,
                    world_geometry_verified=False, actual_incoming_WIP_verified=False,
                    production_qualified=False)

def load_selected_plan_evidence(*, process_id, expected_document_path, expected_source_sha256,
        selected, profile_headers_receipt_path, profile_headers_receipt_sha256,
        profile_indexed_receipt_path, profile_indexed_receipt_sha256,
        diagnostic_inventory_receipt_path, diagnostic_inventory_receipt_sha256):
    indexed, ipin = read_pin(profile_indexed_receipt_path, profile_indexed_receipt_sha256)
    for key in ('read_only','readback_verified','selected_chains_read_complete',
                'selected_index_name_mapping_verified'):
        _require(indexed.get(key) is True, 'Incomplete indexed evidence: '+key)
    for key in ('mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted',
                'model_saved','TechDB_write_attempted','post_cleanup_CAM_getters',
                'full_inventory_verified','world_geometry_verified','production_qualified'):
        if key == 'world_geometry_verified' and key not in indexed:
            continue
        _require(indexed.get(key) is False, 'Unexpected indexed evidence flag: '+key)
    _require(indexed.get('status') == 'review_required' and indexed.get('phase') == 'finished',
             'Completed indexed observation required')
    _require(type(indexed.get('process_id')) is int and indexed['process_id'] == process_id,
             'Indexed observation process differs')
    _require(indexed.get('selected') == selected, 'Indexed selected identity differs')
    _require(indexed.get('saved_file_sha256') == expected_source_sha256, 'Indexed saved source differs')
    clean_events(indexed)
    ib = indexed.get('before')
    _require(type(ib) is dict and ib == indexed.get('after')
             and indexed.get('state_sha256') == _digest(ib), 'Indexed snapshots differ')
    header = load_profile_headers_anchor(profile_headers_receipt_path, profile_headers_receipt_sha256,
        process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256, selected=selected,
        index_mapping=indexed['index_mapping'])
    _require(indexed.get('header_anchor') == header['pin'], 'Indexed header provenance differs')
    _require(ib.get('headers') == header['headers'] and ib.get('read_complete') is True,
             'Indexed metadata differs from header evidence')
    chains = ib.get('indexed_chains')
    _require(type(chains) is list and len(chains) == header['headers']['sketch_count'],
             'All selected observed sketch chains required')
    _require([r.get('expected_sketch_name') for r in chains] == header['names'],
             'Selected sketch chain order differs')
    _require(all(r.get('read_complete') is True and r.get('name_matches') is True
                 and r.get('contour',{}).get('status') == 'observed' for r in chains),
             'Incomplete indexed chain observations')
    diag, dpin = read_pin(diagnostic_inventory_receipt_path, diagnostic_inventory_receipt_sha256)
    _require(diag.get('status') == 'error' and diag.get('phase') == 'finished'
             and diag.get('diagnostic_enumeration_complete') is True
             and diag.get('reason') == 'DIAGNOSTIC_CAPABILITY_ERRORS_FULL_GEOMETRY_AND_REBIND_NOT_VERIFIED',
             'Exact completed diagnostic-only baseline required')
    _require(type(diag.get('process_id')) is int and diag['process_id'] == process_id,
             'Diagnostic process differs')
    _require(diag.get('read_only') is True, 'Read-only diagnostic baseline required')
    for key in ('mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted',
                'model_saved','stock_edit_attempted','material_edit_attempted','TechDB_write_attempted',
                'post_cleanup_CAM_getters','inventory_read_complete','readback_verified'):
        _require(diag.get(key) is False, 'Unexpected diagnostic flag: '+key)
    clean_events(diag)
    before, after = diag.get('before'), diag.get('after')
    _require(type(before) is dict and type(after) is dict and same(before,after),
             'Two stable diagnostic observations required')
    _require(before.get('saved_file_sha256') == expected_source_sha256, 'Diagnostic source differs')
    check_document_target(before['document']['path'],before['document']['title'],
                          expected_path=expected_document_path,required=True)
    _require(before['document'].get('needs_save') is False and before['document'].get('type') == 1,
             'Clean saved part anchor required')
    _require(before.get('operation_count') == 0 and not any(before['operation_counts']),
             'Diagnostic baseline must precede all operations')
    _require(len(before['features']) == 18, 'Scoped pilot requires exactly 18 features')
    ids = [r['geometry']['native_id'] for r in before['features']]
    _require(all(type(v) is int and 0<v<2**32 for v in ids) and len(set(ids)) == 18,
             'Unique bounded feature identities required')
    rows = [r for r in before['features'] if r['geometry']['native_id'] == selected['feature_native_id']]
    _require(len(rows) == 1 and rows[0]['setup_native_id'] == selected['owner_setup_native_id'],
             'Selected native ID/owner absent from diagnostic baseline')
    _require(rows[0]['geometry']['volume_type'] == selected['volume_type']
             and rows[0]['geometry']['shape_raw'] == selected['shape']
             and rows[0]['geometry']['suppressed'] is False, 'Selected classification differs')
    context = observed_context(before)
    e = diag['recovery_evidence']; rp=e['recognition_receipt']; sp=e['preservation_save_receipt']
    recovery = load_mill_inventory_recovery_evidence(rp['path'],rp['sha256'],sp['path'],sp['sha256'],
        process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256, allow_saved_process_rebind=True)
    _require(recovery.summary() == e, 'Diagnostic recovery lineage differs')
    result = SelectedPlanEvidence([header['pin'],ipin,dpin],selected,header['headers'],context,ib,recovery)
    result.check_files()
    return result

def load_plan_receipt(path, sha, *, evidence, process_id, expected_operation_setup_native_id):
    data, pin = read_pin(path, sha)
    _require(data.get('scope') == SCOPE and data.get('action') == 'plan_once'
             and data.get('status') == 'review_required' and data.get('phase') == 'finished',
             'Completed selected-plan receipt required')
    for key in ('mutation_attempted','native_call_attempted','native_call_returned',
                'GOP_attempted','readback_verified','operation_delta_verified'):
        _require(data.get(key) is True, 'Missing successful plan field: '+key)
    for key in ('native_dispatch_pending','GTP_attempted','model_saved','save_attempted',
                'tool_assignment_attempted','stock_edit_attempted','geometry_edit_attempted',
                'production_qualified','post_cleanup_CAM_getters'):
        _require(data.get(key) is False, 'Unexpected selected-plan field: '+key)
    _require(type(data.get('native_hresult')) is int and data['native_hresult'] == 0,
             'Plan did not return strict S_OK')
    _require(data.get('process_id') == process_id and type(data.get('process_id')) is int,
             'Plan process differs')
    _require(data.get('anchor') == evidence.summary(), 'Plan anchor differs')
    _require(data.get('expected_operation_setup_native_id') == expected_operation_setup_native_id
             and type(data.get('expected_operation_setup_native_id')) is int, 'Plan operation setup differs')
    clean_events(data)
    _require(data.get('state_sha256') == _digest(data['after']), 'Plan after digest differs')
    evidence.verify(data['before']); evidence.verify(data['after'])
    from scripts.sw_cam_mill_selected_plan import verify_plan_delta
    verify_plan_delta(data['before'],data['after'],evidence.selected['feature_native_id'],expected_operation_setup_native_id)
    return data,pin
