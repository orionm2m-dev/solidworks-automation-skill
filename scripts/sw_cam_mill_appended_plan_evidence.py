"""Continue from a verified additive-plan save; no generation or implicit rebind."""
from copy import deepcopy
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events, same_saved_context
from scripts.sw_cam_mill_inventory import _same_inventory
from scripts.sw_cam_mill_stock_export_evidence import _require
from scripts.sw_cam_mill_append_evidence import SCOPE, load_target_profile, require_protected_tools
from scripts.sw_cam_mill_append_delta import verify_added_plan
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

class AppendedPlanEvidence:
    def __init__(self, data, pin, previous, profile):
        self.data = deepcopy(data)
        self.state = deepcopy(data["saved"])
        self.selected = deepcopy(previous.selected)
        self.operation_ids = list(previous.operation_ids)
        self.tool_id = previous.tool_id
        self.previous = previous
        self.receipt_pin = deepcopy(pin)
        self.profile = deepcopy(profile)
        self.pins = deepcopy(previous.pins) + [deepcopy(profile["pin"]), deepcopy(pin)]
        self.baseline_tool_details = deepcopy(data["saved_details"]["selected_tool_details"])
    def check_files(self):
        self.previous.check_files()
        for pin in (self.profile["pin"], self.receipt_pin):
            _require(read_pin(pin["path"], pin["sha256"])[1] == pin, "Appended evidence changed")
    def check_runtime_identity(self):
        self.previous.check_runtime_identity()
    def read_stock(self, *args):
        return self.previous.read_stock(*args)
    def verify(self, state):
        _require(_same_inventory(self.state, state), "Saved appended CAM context changed")
        return True
    def summary(self):
        return dict(scope="MILL_APPENDED_PLAN_CONTINUATION_V1",
            saved_append_receipt=deepcopy(self.receipt_pin),
            saved_source_sha256=self.data["saved_file_sha256"],
            process_id=self.data["process_id"], selected=deepcopy(self.selected),
            operation_native_ids=list(self.operation_ids), tool_native_id=self.tool_id,
            added_operation_native_ids=[r["native_id"] for r in self.data["new_operations"]],
            previous_anchor=deepcopy(self.data["anchor"]), original_receipts_modified=False,
            full_inventory_verified=False, world_geometry_verified=False, production_qualified=False)

def validate_saved_append(data, previous, profile, *, process_id, document_path, source_sha):
    _require(data.get("scope") == SCOPE and data.get("status") == "review_required"
        and data.get("phase") == "finished", "Completed additive-plan save required")
    for key in ("mutation_attempted", "native_call_attempted", "native_call_returned",
        "GOP_attempted", "save_after_verified", "save_attempted", "save_call_returned",
        "readback_verified", "operation_delta_verified", "save_readback_verified", "model_saved"):
        _require(data.get(key) is True, "Verified additive save flag required: " + key)
    for key in ("native_dispatch_pending", "GTP_attempted", "AFR_attempted", "simulation_attempted",
        "stock_edit_attempted", "geometry_edit_attempted", "material_edit_attempted",
        "strategy_assignment_attempted", "tool_assignment_attempted", "TechDB_write_attempted",
        "automatic_replay", "automatic_rollback", "post_cleanup_CAM_getters", "production_qualified"):
        _require(data.get(key) is False, "Unexpected additive save field: " + key)
    _require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error")),
             "Failed or uncertain append cannot anchor continuation")
    for key in ("native_hresult", "save_hresult"):
        _require(type(data.get(key)) is int and data[key] == 0, "Strict zero HRESULT required")
    _require(type(data.get("process_id")) is int and data["process_id"] == process_id,
             "Appended plan belongs to another process; explicit rebind required")
    clean_events(data)
    _require(data["anchor"] == previous.summary() and data["target_profile"] == profile,
             "Append lineage differs")
    args = data["request"]
    previous.verify(data["before"])
    added = verify_added_plan(data["before"], data["after"], args["target_feature_native_id"],
                              args["target_operation_setup_native_id"])
    _require(added == data["new_operations"], "Added-operation proof differs")
    _require(data["before_details"] == data["after_details"] == data["saved_details"],
             "Saved full tools or target metadata differ")
    details = data["saved_details"]
    require_protected_tools(previous, data["saved"], details["selected_tool_details"])
    _require(details["three_step_profile"]["compound_strategy"] == profile["details"],
             "Saved target profile differs")
    strategy = details["strategy"]["compound_strategy"]
    _require(strategy.get("metadata_read_complete") is True
        and strategy.get("attribute_id") == args["expected_strategy_id"]
        and strategy.get("attribute_name") == args["expected_strategy_name"],
        "Saved target strategy precondition differs")
    saved = data["saved"]
    _require(same_saved_context(data["after"], saved), "Save changed appended context")
    _require(data["source_before_sha256"] == previous.state["saved_file_sha256"]
        and data["saved_file_sha256"] == data["source_after_sha256"] == saved["saved_file_sha256"] == source_sha,
        "Appended source lineage differs")
    _require(data["continuation_state"] == saved and data["state_sha256"] == _digest(saved),
             "Appended continuation digest differs")
    _require(type(saved["document"].get("type")) is int and saved["document"]["type"] == 1
        and saved["document"].get("needs_save") is False, "Clean saved part required")
    check_document_target(saved["document"]["path"], saved["document"]["title"],
                          expected_path=document_path, required=True)
    return True

def load_appended_plan_evidence(path, sha, *, process_id, expected_document_path,
        expected_source_sha256, expected_feature_native_id, expected_operation_native_ids,
        expected_operation_setup_native_id, expected_tool_native_id):
    from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
    data, pin = read_pin(path, sha)
    _require(data.get("scope") == SCOPE, "Additive plan receipt required")
    request = data["request"]
    expected = dict(process_id=process_id, expected_document_path=expected_document_path,
        expected_feature_native_id=expected_feature_native_id,
        expected_operation_native_ids=expected_operation_native_ids,
        expected_operation_setup_native_id=expected_operation_setup_native_id,
        expected_tool_native_id=expected_tool_native_id)
    for key, value in expected.items():
        _require(type(request.get(key)) is type(value) and request[key] == value,
                 "Append request continuation mismatch: " + key)
    prior_data, _ = read_pin(request["saved_plan_receipt_path"], request["saved_plan_receipt_sha256"])
    _require(prior_data.get("scope") == "MILL_SAVED_SHARED_CUTTER_CONFIG_V1",
             "This bounded capability requires an original configured-plan anchor; no recursive append")
    previous = load_saved_plan_tools_evidence(request["saved_plan_receipt_path"],
        request["saved_plan_receipt_sha256"], expected_source_sha256=data["source_before_sha256"], **expected)
    profile = load_target_profile(request["target_profile_receipt_path"],
        request["target_profile_receipt_sha256"], previous, process_id=process_id,
        source_sha=data["source_before_sha256"], feature_id=request["target_feature_native_id"],
        owner_id=request["target_owner_setup_native_id"])
    validate_saved_append(data, previous, profile, process_id=process_id,
        document_path=expected_document_path, source_sha=expected_source_sha256)
    result = AppendedPlanEvidence(data, pin, previous, profile)
    result.check_files(); result.check_runtime_identity()
    return result
