"""Validate a saved completed-observation draft without reopening old dispatch gates."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
from scripts.sw_cam_sandvik_save import save_marker, verify_context
from scripts.sw_cam_completed_sandvik_save import SCOPE as SAVE_SCOPE, stable_payload
from scripts.sw_cam_complete_sandvik_observation import SCOPE as OBS_SCOPE, READ_MODE
from scripts.sw_cam_completed_sandvik_evidence import TRUE_FLAGS, FALSE_FLAGS
from scripts.sw_cam_sandvik_phase1 import BINDING_KEYS
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target

TARGET_KEYS = ("target_feature_native_id", "target_operation_native_id", "target_operation_setup_native_id")


def load_saved_sandvik(*, saved_draft_receipt_path, saved_draft_receipt_sha256,
        expected_candidate_tool_native_id, **args):
    validate_inventory_request(**{k:args[k] for k in ("process_id", "expected_document_path",
        "expected_source_sha256", "qualification_only", "acknowledge_disposable_copy", "receipt_path", "message_policy")})
    new_id = expected_candidate_tool_native_id
    require(type(new_id) is int and 0 < new_id < 2**32, "Strict existing candidate ID required")
    data, pin = read_pin(saved_draft_receipt_path, saved_draft_receipt_sha256)
    require(data.get("scope") == SAVE_SCOPE and data.get("status") == "review_required"
        and data.get("phase") == "finished", "Completed exact draft Save required")
    for key in ("mutation_attempted", "save_attempted", "native_call_attempted", "native_call_returned",
                "model_saved", "experimental_draft_saved", "save_readback_verified", "readback_verified",
                "holder_readback_stable", "holder_profile_verified", "classification_pending"):
        require(data.get(key) is True, "Incomplete Save flag: " + key)
    for key in ("save_pending", "reopen_persistence_verified", "close_attempted", "creator_attempted",
                "MT_load_attempted", "assignment_attempted", "GTP_attempted", "GOP_attempted", "AFR_attempted",
                "TechDB_write_attempted", "automatic_replay", "automatic_rollback", "post_cleanup_CAM_getters",
                "production_qualified", "units_verified", "cutting_partition_verified", "physical_tool_qualified",
                "may_continue", "full_geometry_rechecked", "full_context_rechecked"):
        require(data.get(key) is False, "Unexpected Save flag: " + key)
    require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error")), "Failed Save cannot authorize assignment")
    require(type(data.get("native_return_value")) is int and data["native_return_value"] == 0
        and data.get("native_return_type") == "int", "Strict successful Save HRESULT required")
    require(type(data.get("capture_count")) is int and data["capture_count"] == 2, "Two scoped Save captures required")
    require(type(data.get("process_id")) is int and data["process_id"] == args["process_id"]
        and type(data.get("tool_native_id")) is int and data["tool_native_id"] == new_id, "Saved identity differs")
    clean_events(data)
    check_document_target(data["expected_document_path"], None, expected_path=args["expected_document_path"], required=True)
    current_sha = args["expected_source_sha256"]
    require(data["saved_file_sha256"] == data["source_after_sha256"] == current_sha
        and _file_hash(args["expected_document_path"]) == current_sha, "Current saved source differs")
    obs_pin = data["observation_pin"]
    obs, actual_obs_pin = read_pin(obs_pin["path"], obs_pin["sha256"])
    require(actual_obs_pin == obs_pin and obs.get("scope") == OBS_SCOPE and obs.get("read_mode") == READ_MODE
        and obs.get("status") == "review_required" and obs.get("phase") == "finished", "Completed observation provenance differs")
    for key in TRUE_FLAGS:require(obs.get(key) is True, "Incomplete observation flag: " + key)
    for key in FALSE_FLAGS:require(obs.get(key) is False, "Unexpected observation flag: " + key)
    require(not any(k in obs for k in ("issue", "failed_phase", "receipt_write_error")), "Failed observation provenance")
    clean_events(obs)
    binding = data["request_binding"]
    require(binding == obs["request_binding"] and type(binding["process_id"]) is int
        and binding["process_id"] == args["process_id"], "Saved observation binding differs")
    check_document_target(binding["expected_document_path"], None, expected_path=args["expected_document_path"], required=True)
    require(data["source_before_sha256"] == binding["expected_source_sha256"] == obs["source_before_sha256"]
        and obs["tool_native_id"] == new_id and obs["process_id"] == args["process_id"], "Historical observation identity differs")
    phase1_pin = data["phase1_pin"]
    prior, actual_prior_pin = read_pin(phase1_pin["path"], phase1_pin["sha256"])
    require(actual_prior_pin == phase1_pin == obs["prior_receipt_pin"]
        and data["creation_pin"] == obs["prior_creation_marker_pin"]
        and data["holder_shape_pin"] == obs["holder_shape_pin"]
        and all(type(prior["request_binding"].get(k)) is type(v) and prior["request_binding"][k] == v
            for k,v in binding.items()), "Saved ancestry differs")
    anchor = load_saved_plan_tools_evidence(binding["saved_plan_receipt_path"], binding["saved_plan_receipt_sha256"],
        **{k:binding[k] for k in BINDING_KEYS})
    require(data["anchor"] == obs["anchor"] == anchor.summary(), "Protected historical anchor differs")
    reference = dict(context=obs["after"], document=obs["after_document"], candidate=obs["after_candidate"],
        holder_recipe=obs["holder_recipe"], candidate_contract=obs["candidate_contract"])
    payload = stable_payload(reference)
    require(data["before"] == data["after"] == payload, "Saved tool/holder/firstcut payload differs")
    require(data["candidate_contract"] == obs["candidate_contract"] and data["holder_recipe"] == obs["holder_recipe"]
        and data["profile_observation"] == obs["profile_observation"], "Saved profile provenance differs")
    require(data["observed_physical_flags"] == {k:False for k in ("units_verified", "cutting_partition_verified",
        "physical_tool_qualified", "production_qualified", "numeric_profile_verified")}, "Unexpected physical qualification")
    verify_context(obs["after"], data["before_context"])
    verify_context(data["before_context"], data["after_context"], after_save=True)
    current = data["after_context"]
    require(data["before_document"] == obs["after_document"] == data["before_context"]["document"]
        and data["after_document"] == data["after_cleanup_document"] == current["document"], "Document checkpoints differ")
    require(current["saved_file_sha256"] == current_sha and current["document"]["needs_save"] is False
        and data["continuation_state"] == current and data["state_sha256"] == _digest(current), "Clean saved continuation required")
    require(data["continuation_state_provenance"] == dict(reference_pin=obs_pin,
        fresh_fields=["document", "operations"], reused_fields="all remaining context geometry and metadata"),
        "Save geometry provenance differs")
    captures = data["capture_diagnostics"]
    require(type(captures) is list and len(captures) == 2, "Two Save diagnostics required")
    for label, row in zip(("before", "after"), captures):
        require(row.get("phase") == label and row.get("capture_complete") is True
            and row.get("fresh_full_snapshot") is False and row.get("reference_pin") == obs_pin
            and row.get("operations", {}).get("operation_capture_complete") is True, "Incomplete scoped Save capture")
    guards = data["guard_diagnostics"]
    require(bool(guards) and all(g.get("invalid") is False for g in guards), "Invalid Save read guard")
    firstpin = data["firstcut_anchor"]["pin"]
    firstcut, _ = read_pin(firstpin["path"], firstpin["sha256"])
    require(data["firstcut_anchor"] == prior["firstcut_anchor"]
        and payload["firstcut"] == firstcut["after_settings"] == data["firstcut_anchor"]["after_settings"], "Saved firstcut differs")
    rough = [o for o in anchor.data["new_operations"] if o["mill_operation_type"] == 0]
    require(len(rough) == 1, "One added rough required")
    target = dict(target_feature_native_id=anchor.data["new_feature_native_id"],
        target_operation_native_id=rough[0]["native_id"], target_operation_setup_native_id=rough[0]["setup_native_id"])
    for key in TARGET_KEYS:require(type(args.get(key)) is int and args[key] == target[key], "Exact added rough target required")
    require(len(current["features"]) == 19 and len(current["operations"]) == 6
        and all(o["toolpath_generated"] is False and o["toolpath_record_counts"] == []
            and o["assigned_tool"]["native_id"] != new_id for o in current["operations"]),
        "Nineteen features, six ungenerated definitions and unassigned candidate required")
    marker = save_marker(args["expected_document_path"], phase1_pin["sha256"], new_id)
    check_document_target(data["save_marker_path"], None, expected_path=str(marker), required=True)
    marker_data, marker_pin = read_pin(str(marker), _file_hash(marker))
    expected_marker = dict(scope=SAVE_SCOPE, phase="finished", status="review_required", document=args["expected_document_path"],
        source_before_sha256=data["source_before_sha256"], phase1_receipt_sha256=phase1_pin["sha256"],
        observation_receipt_sha256=obs_pin["sha256"], tool_native_id=new_id, receipt_path=saved_draft_receipt_path,
        save_pending=False, native_call_returned=True, saved_file_sha256=current_sha, automatic_replay=False)
    require(marker_data == expected_marker, "Exact completed original Save marker required")
    pins = data["observation_evidence_pins"] + [pin, marker_pin]
    required = [obs_pin, phase1_pin, data["creation_pin"], data["holder_shape_pin"], data["noncutting_marker_pin"], firstpin]
    identities = {(str(Path(p["path"]).resolve()).casefold(), p["sha256"]) for p in pins}
    require(all((str(Path(p["path"]).resolve()).casefold(), p["sha256"]) in identities for p in required),
        "Missing immutable observation lineage pin")
    for evidence in pins:require(_file_hash(evidence["path"]) == evidence["sha256"], "Pinned saved lineage changed")
    output = str(Path(args["receipt_path"]).resolve()).casefold()
    require(output not in {str(Path(p["path"]).resolve()).casefold() for p in pins}
        and output != str(Path(args["expected_document_path"]).resolve()).casefold(), "Assignment output aliases evidence")
    normalized_prior = deepcopy(prior)
    normalized_prior["after_firstcut"] = deepcopy(payload["firstcut"])
    return dict(data=data, pin=pin, phase1=normalized_prior, firstcut=firstcut, anchor=anchor, pins=pins,
        target=target, state=deepcopy(current), candidate_id=new_id, marker_pin=marker_pin,
        payload=payload, observation_pin=obs_pin)
