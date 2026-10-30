"""Continue from a verified native tool-configuration save without replay."""
from copy import deepcopy
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events, same_saved_context, SCOPE as PLAN_SCOPE
from scripts.sw_cam_mill_stock_export_evidence import _require
from scripts.sw_cam_mill_inventory import _same_inventory
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_shared_cutter_evidence import SCOPE, load_cutter_evidence
from scripts.sw_cam_shared_cutter_geometry import verify_full_delta
from scripts.sw_cam_shared_holder_geometry import read_holder_recipe, check_holder_pins
from scripts.sw_operation_guard import check_document_target

TRUE_FLAGS = ('mutation_attempted', 'native_call_attempted', 'native_call_returned',
    'readback_verified', 'cutter_profile_readback_verified', 'save_after_verified',
    'save_attempted', 'save_call_returned', 'save_readback_verified', 'model_saved')
FALSE_FLAGS = ('native_dispatch_pending', 'AFR_attempted', 'GOP_attempted', 'GTP_attempted',
    'simulation_attempted', 'stock_edit_attempted', 'material_edit_attempted',
    'tool_assignment_attempted', 'TechDB_write_attempted', 'post_cleanup_CAM_getters',
    'production_qualified', 'automatic_replay', 'automatic_rollback')


class ConfiguredPlanEvidence:
    """Keep the saved configuration receipt distinct from the original plan."""
    def __init__(self, data, pin, previous, holder):
        self.data = deepcopy(data)
        self.state = deepcopy(data['saved'])
        self.selected = deepcopy(data['selected'])
        self.operation_ids = list(previous.base.operation_ids)
        self.tool_id = previous.base.tool_id
        self.previous = previous
        self.receipt_pin = deepcopy(pin)
        self.holder = deepcopy(holder)
        self.pins = deepcopy(previous.pins) + [deepcopy(pin)]
        if holder is not None:
            self.pins += deepcopy(holder['pins'])
        self.baseline_tool_details = deepcopy(data['saved_tool_details'])

    def check_files(self):
        self.previous.check_files()
        _, actual = read_pin(self.receipt_pin['path'], self.receipt_pin['sha256'])
        _require(actual == self.receipt_pin, 'Saved configuration receipt changed')
        if self.holder is not None:
            check_holder_pins(self.holder)

    def check_runtime_identity(self):
        self.previous.check_runtime_identity()

    def read_stock(self, *args):
        return self.previous.read_stock(*args)

    def verify(self, state):
        _require(_same_inventory(self.state, state), 'Saved configured CAM context changed')
        return True

    def summary(self):
        return dict(scope='MILL_CONFIGURED_PLAN_CONTINUATION_V1',
            saved_configuration_receipt=deepcopy(self.receipt_pin),
            saved_source_sha256=self.data['saved_file_sha256'],
            process_id=self.data['process_id'], selected=deepcopy(self.selected),
            operation_native_ids=self.operation_ids, tool_native_id=self.tool_id,
            previous_configuration_anchor=deepcopy(self.data['anchor']),
            original_receipts_modified=False, full_inventory_verified=False,
            world_geometry_verified=False, production_qualified=False)


def validate_saved_configuration(data, previous, holder, *, process_id,
                                 expected_document_path, expected_source_sha256):
    _require(data.get('scope') == SCOPE and data.get('status') == 'review_required'
             and data.get('phase') == 'finished', 'Completed configured-tool save required')
    for key in TRUE_FLAGS:
        _require(data.get(key) is True, 'Missing verified save field: ' + key)
    for key in FALSE_FLAGS:
        _require(data.get(key) is False, 'Unexpected configured save field: ' + key)
    _require(not any(k in data for k in ('issue', 'failed_phase', 'receipt_write_error')),
             'Failed configuration cannot anchor continuation')
    _require(type(data.get('save_hresult')) is int and data['save_hresult'] == 0,
             'Strict native save HRESULT required')
    _require(type(data.get('process_id')) is int and data['process_id'] == process_id,
             'Configuration belongs to another process; explicit rebind required')
    clean_events(data)
    _require(data.get('anchor') == previous.summary(), 'Configuration lineage differs')
    _require(data.get('selected') == previous.selected, 'Selected feature scope differs')
    previous.verify_before(data['before'], data['before_tool_details'])
    previous.verify_after_context(data['after'])
    saved = data['saved']
    _require(data.get('source_before_sha256') == previous.base.state['saved_file_sha256'],
             'Previous source differs')
    _require(data.get('saved_file_sha256') == data.get('source_after_sha256')
             == saved.get('saved_file_sha256') == expected_source_sha256,
             'Saved source differs')
    _require(data.get('continuation_state') == saved and data.get('state_sha256') == _digest(saved),
             'Saved continuation digest differs')
    _require(same_saved_context(data['after'], saved), 'Save changed observed CAM context')
    doc = saved['document']
    _require(type(doc.get('type')) is int and doc['type'] == 1
             and doc.get('needs_save') is False, 'Clean saved part required')
    check_document_target(doc['path'], doc['title'], expected_path=expected_document_path, required=True)
    details = data['saved_tool_details']
    _require(details == data['after_tool_details']
             and data.get('tool_details_sha256') == _digest(details), 'Saved tool details differ')
    from scripts.sw_cam_mill_saved_plan_rebind import _full_details
    _full_details(details, previous.base)
    original = data['before_tool_details']['items'][0]['full_tool']
    current = details['items'][0]['full_tool']
    comparison = verify_full_delta(original, current, previous.target, holder)
    _require(comparison == data.get('profile_comparison'), 'Native profile proof differs')
    if holder is not None:
        _require(data.get('holder_profile_readback_verified') is True
                 and data.get('holder_assignment_performed') is True,
                 'Holder assignment proof missing')
        ref = data['holder_reference']
        _require(ref.get('readback_verified') is True and ref.get('setter_attempted') is True
                 and ref.get('native_call_returned') is True and type(ref.get('hresult')) is int
                 and ref['hresult'] == 0 and ref.get('after') == holder['file_path']
                 and ref.get('requested') == holder['file_path'], 'Holder reference differs')
    else:
        _require(data.get('holder_profile_readback_verified') is False
                 and data.get('holder_assignment_performed') is False,
                 'Holder proof has no pinned asset')
    return True


def load_configured_plan_evidence(path, sha, *, process_id, expected_document_path,
        expected_source_sha256, expected_feature_native_id, expected_operation_native_ids,
        expected_operation_setup_native_id, expected_tool_native_id):
    data, pin = read_pin(path, sha)
    _require(data.get('scope') == SCOPE, 'Configured save receipt required')
    anchor = data['anchor']
    saved_plan = anchor['saved_plan']
    rebound = saved_plan.get('scope') == 'MILL_SAVED_PLAN_SESSION_REBIND_V1'
    original = saved_plan['historical_summary'] if rebound else saved_plan
    old_pin = original['saved_plan_receipt']
    old_data, _ = read_pin(old_pin['path'], old_pin['sha256'])
    # Do not accept recursive configuration history as an original plan.
    _require(old_data.get('scope') == PLAN_SCOPE,
             'Original selected plan lineage required')
    inspection = anchor['tool_inspection']
    nominal = anchor['nominal_geometry']
    extra = {}
    if rebound:
        ref = saved_plan['session_rebind_receipt']
        extra = dict(session_rebind_receipt_path=ref['path'],
                     session_rebind_receipt_sha256=ref['sha256'])
    previous = load_cutter_evidence(
        saved_plan_receipt_path=old_pin['path'], saved_plan_receipt_sha256=old_pin['sha256'],
        tools_receipt_path=inspection['path'], tools_receipt_sha256=inspection['sha256'],
        nominal_geometry_receipt_path=nominal['path'], nominal_geometry_receipt_sha256=nominal['sha256'],
        target_geometry=anchor['target_geometry'], process_id=process_id,
        expected_document_path=expected_document_path,
        expected_source_sha256=data['source_before_sha256'],
        expected_feature_native_id=expected_feature_native_id,
        expected_operation_native_ids=expected_operation_native_ids,
        expected_operation_setup_native_id=expected_operation_setup_native_id,
        expected_tool_native_id=expected_tool_native_id, **extra)
    binding = data.get('holder_asset_binding')
    holder = None
    if binding is not None:
        pins = binding['pins']
        _require(type(pins) is list and len(pins) == 2, 'Exact holder asset pair required')
        holder = read_holder_recipe(pins[0]['path'], pins[0]['sha256'],
                                    pins[1]['path'], pins[1]['sha256'])
        _require(holder == binding, 'Holder recipe binding differs')
    validate_saved_configuration(data, previous, holder, process_id=process_id,
        expected_document_path=expected_document_path, expected_source_sha256=expected_source_sha256)
    result = ConfiguredPlanEvidence(data, pin, previous, holder)
    result.check_files()
    result.check_runtime_identity()
    return result
