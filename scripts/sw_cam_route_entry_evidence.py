"""Completed bounded continuation evidence after one rough-entry edit."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target

GTP_SCOPE = "MILL_ENTRY_EDIT_GTP_V1"
CL_SCOPE = "MILL_ENTRY_EDIT_GENERIC_CL_V1"
SAVE_SCOPE = "MILL_ENTRY_EDIT_WORKING_SAVE_V1"
SCOPES = {"gtp": GTP_SCOPE, "cl": CL_SCOPE, "save": SAVE_SCOPE}
IDS = ("target_feature_native_id", "target_operation_native_id", "target_operation_setup_native_id", "expected_candidate_tool_native_id")


def selected(state, args, *, generated=None):
    require(len(state["features"]) == 19 and len(state["feature_setups"]) == 3
            and len(state["operation_setups"]) == 3 and len(state["operations"]) == 6
            and state["operation_count"] == 6, "Exact 19/3/6 route required")
    ids = [r["native_id"] for r in state["operations"]]
    require(all(type(n) is int and n > 0 for n in ids) and len(set(ids)) == 6, "Unique operation IDs required")
    rows = [r for r in state["operations"] if r["native_id"] == args["target_operation_native_id"]]
    require(len(rows) == 1, "Exact target operation required")
    row = rows[0]
    require(row["linked_feature_ids"] == [args["target_feature_native_id"]]
            and row["setup_native_id"] == args["target_operation_setup_native_id"]
            and type(row["mill_operation_type"]) is int and row["mill_operation_type"] == 0
            and row["suppressed"] is False, "Exact unsuppressed target rough required")
    tool = row["assigned_tool"]
    require(type(tool["native_id"]) is int and tool["native_id"] == args["expected_candidate_tool_native_id"]
            and tool["tool_type_raw"] == 14 and tool["is_mill_tool"] is True
            and tool["native_read_complete"] is True, "Exact UD14 assignment required")
    require(type(row["toolpath_generated"]) is bool, "Strict path flag required")
    counts = row["toolpath_record_counts"]
    require(type(counts) is list and len(counts) <= 32 and all(type(n) is int and 0 <= n <= 100000 for n in counts), "Bounded record counts required")
    if generated is True:
        require(row["toolpath_generated"] is True and 0 < sum(counts) <= 100000, "Fresh positive target path required")
    if generated is False:
        require(row["toolpath_generated"] is False and counts == [], "Absent target path required")
    require(all(r["toolpath_generated"] is False and r["toolpath_record_counts"] == [] and r["suppressed"] is False
                for r in state["operations"] if r is not row), "Five protected siblings must remain ungenerated")
    return row


def verify_gtp_delta(before, after, args):
    """Regeneration is explicit; only target counts and Boolean dirty may change."""
    selected(before, args)
    target = selected(after, args, generated=True)
    expected = deepcopy(before)
    row = selected(expected, args)
    row["toolpath_generated"] = target["toolpath_generated"]
    row["toolpath_record_counts"] = deepcopy(target["toolpath_record_counts"])
    require(type(after["document"].get("needs_save")) is bool, "Strict dirty required")
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    require(after == expected, "GTP changed protected route, sibling, tool or source")


def verify_save_delta(before, after, args, new_sha):
    selected(before, args, generated=True)
    selected(after, args, generated=True)
    expected = deepcopy(before)
    expected["document"]["needs_save"] = False
    expected["saved_file_sha256"] = new_sha
    require(after == expected, "Save changed state beyond clean flag and saved SHA")


def continuation_marker(document_path, action, parent_pin, operation_id):
    require(action in SCOPES, "Known action required")
    source = Path(document_path).resolve()
    key = _digest(dict(scope=SCOPES[action], source=str(source).casefold(), parent_sha256=parent_pin["sha256"], operation_id=operation_id))
    return source.parent / ("route_entry_" + action + "_" + key + ".json")


def marker_state(report):
    keys = ("scope", "action", "status", "phase", "process_id", "expected_document_path", "source_before_sha256", "source_after_sha256", "parent_checkpoint_pin", "target_operation_native_id", "marker_path", "receipt_path", "readback_verified", "native_dispatch_pending", "native_call_attempted", "native_call_returned", "native_return_type", "native_return_value", "native_hresult", "save_pending", "save_readback_verified", "saved_file_sha256", "output_verified", "output", "GTP_call_count", "GTP_returned", "checkpoint_sha256")
    return {k: deepcopy(report[k]) for k in keys if k in report}


def make_checkpoint(state, payload):
    return dict(state=deepcopy(state), payload=deepcopy(payload), source_sha256=state["saved_file_sha256"])


def load_continuation_checkpoint(path, sha256, *, action, check_current_source=True, **args):
    """Only known finished actions; bounded CAS -> GTP -> CL -> Save lineage."""
    from scripts.sw_cam_route_checkpoint import load_completed_entry_checkpoint
    require(type(check_current_source) is bool, "Explicit historical/current mode required")
    data, pin = read_pin(path, sha256)
    require(action in SCOPES and data.get("scope") == SCOPES[action] and data.get("action") == action
            and data.get("phase") == "finished" and data.get("status") == "review_required", "Exact completed continuation required")
    require(data.get("readback_verified") is True and not any(k in data for k in ("issue", "failed_phase", "receipt_write_error")), "Unverified continuation")
    require(data.get("native_call_attempted") is True and data.get("native_call_returned") is True
            and data.get("native_dispatch_pending", False) is False and data.get("automatic_replay", False) is False, "Completed single native action required")
    require(type(data.get("process_id")) is int and data["process_id"] == args["process_id"], "Process differs")
    check_document_target(data["expected_document_path"], None, expected_path=args["expected_document_path"], required=True)
    for key in IDS:
        require(type(data.get(key)) is int and data[key] == args[key], "Continuation target differs: " + key)
    for flag in ("automatic_retry", "automatic_replay", "automatic_rollback", "GOP_attempted", "AFR_attempted", "assignment_attempted", "tool_edit_attempted", "simulation_attempted", "NC_export_attempted"):
        require(data.get(flag) is False, "Unexpected continuation action: " + flag)
    clean_events(data)
    diagnostics = data.get("snapshot_diagnostics", [])
    require(len(diagnostics) == (3 if action == "cl" else 2) and all(d.get("capture_complete") is True for d in diagnostics), "Completed bounded snapshots required")
    parent = data["parent_checkpoint_pin"]
    history_args = dict(args, expected_source_sha256=data["source_before_sha256"])
    parent_action = data["parent_action"]
    if action == "gtp":
        require(parent_action == "entry", "GTP must follow entry CAS")
        loaded = load_completed_entry_checkpoint(parent["path"], parent["sha256"], check_current_source=False, **history_args)
    else:
        require(parent_action in ({"gtp"} if action == "cl" else {"gtp", "cl"}), "Unexpected lineage")
        loaded = load_continuation_checkpoint(parent["path"], parent["sha256"], action=parent_action, check_current_source=False, **history_args)
    before, after, checkpoint = data["before_context"], data["after_context"], data["checkpoint"]
    require(before == loaded["state"] and data["before_payload"] == loaded["payload"] and data["after_payload"] == loaded["payload"], "Protected payload changed")
    require(data["after_cleanup_document"] == after["document"], "Cleanup document differs")
    require(checkpoint == make_checkpoint(after, loaded["payload"]) and data["checkpoint_sha256"] == _digest(checkpoint), "Checkpoint digest/content differs")
    require(data["source_before_sha256"] == before["saved_file_sha256"] and data["source_after_sha256"] == after["saved_file_sha256"], "Source transition differs")
    if action == "gtp":
        guard = data.get("dispatch_guard", {})
        require(guard.get("claimed") is True and guard.get("native_call_attempted") is True and guard.get("native_call_returned") is True and guard.get("invalid") is False, "Completed GTP dispatch guard required")
        require(type(data.get("GTP_call_count")) is int and data["GTP_call_count"] == 1 and data.get("GTP_returned") is True, "One GTP required")
        require(data.get("GTP_attempted") is True and data.get("save_attempted") is False and data.get("model_saved") is False, "GTP may not save")
        verify_gtp_delta(before, after, args)
    elif action == "cl":
        require(before == after and data.get("output_verified") is True and type(data.get("native_hresult")) is int and data["native_hresult"] == 0, "Unchanged strict CL export required")
        selected(after, args, generated=True)
        require(_file_hash(data["output"]["path"]) == data["output"]["sha256"], "CL output changed")
        require(data.get("GTP_attempted") is False and data.get("model_saved") is False, "CL may not generate/save")
    else:
        require(data.get("save_readback_verified") is True and data.get("model_saved") is True and data.get("save_pending") is False, "Completed Save required")
        require(data.get("GTP_attempted") is False and data.get("GTP_call_count") == 0, "Save may not generate")
        verify_save_delta(before, after, args, data["saved_file_sha256"])
    if action != "cl":
        require(data.get("native_return_type") == "int" and type(data.get("native_return_value")) is int and data["native_return_value"] == 0, "Strict successful HRESULT required")
    expected_marker = continuation_marker(args["expected_document_path"], action, parent, args["target_operation_native_id"])
    require(Path(data["marker_path"]).resolve() == expected_marker.resolve(), "Marker identity differs")
    marker, mpin = read_pin(str(expected_marker), _file_hash(expected_marker))
    require(marker == marker_state(data), "Completed marker differs")
    require(after["saved_file_sha256"] == args["expected_source_sha256"], "Expected source differs")
    if check_current_source:
        require(_file_hash(args["expected_document_path"]) == args["expected_source_sha256"], "Current source differs")
    implementation = data["implementation_pins"]
    require(type(implementation) is list and len(implementation) == 2
        and {Path(p["path"]).name for p in implementation} == {"sw_cam_route_entry_evidence.py", "sw_cam_route_entry_continuation.py"}, "Exact continuation implementation pins required")
    for evidence in implementation:
        require(_file_hash(evidence["path"]) == evidence["sha256"], "Continuation implementation changed")
    output_pins = [data["output"]] if action == "cl" else []
    result = dict(loaded)
    result["historical_only"] = not check_current_source
    result.update(state=deepcopy(after), payload=deepcopy(checkpoint["payload"]), pin=pin, checkpoint_action=action,
                  source_sha256=after["saved_file_sha256"], pins=canonical_evidence_pins(loaded["pins"], implementation, [pin, mpin], output_pins))
    return result
