"""Pure evidence and result-delta checks for one existing rough GTP.

No CAD discovery, dispatch, Save, output write or marker reset occurs here.
The caller supplies the independently validated completed-Save evidence.
"""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_compound_plan_delta import same_observed_context
from scripts.sw_cam_mill_toolpath import _record_counts
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target

SCOPE = "MILL_ASSIGNED_SANDVIK_INITIAL_GTP_V1"
ASSIGNMENT_SCOPE = "MILL_SANDVIK_ROUGH_ASSIGNMENT_V1"


def _path(actual, expected):
    check_document_target(actual, None, expected_path=str(expected), required=True)


def _target(state, *, operation_id, feature_id, setup_id, candidate_id):
    require(len(state["features"]) == 19 and len(state["operations"]) == 6
            and state["operation_count"] == 6, "Exact nineteen-feature/six-operation context required")
    rows = state["operations"]
    require(all(type(r["native_id"]) is int for r in rows)
            and len({r["native_id"] for r in rows}) == 6, "Unique strict operation IDs required")
    selected = [r for r in rows if r["native_id"] == operation_id]
    require(len(selected) == 1, "Exact selected rough operation required")
    row = selected[0]
    require(row["linked_feature_ids"] == [feature_id] and row["setup_native_id"] == setup_id
            and type(row["mill_operation_type"]) is int and row["mill_operation_type"] == 0
            and row["suppressed"] is False, "Exact unsuppressed added rough definition required")
    tool = row["assigned_tool"]
    require(type(tool["native_id"]) is int and tool["native_id"] == candidate_id
            and type(tool["tool_type_raw"]) is int and tool["tool_type_raw"] == 14
            and tool["is_mill_tool"] is True and tool["native_read_complete"] is True,
            "Exact complete UD14 assignment required")
    return row


def verify_initial_gtp_delta(before, after, *, operation_id, feature_id, setup_id, candidate_id):
    """Accept only target path records and a Boolean dirty flag; no regeneration."""
    original = _target(before, operation_id=operation_id, feature_id=feature_id,
                       setup_id=setup_id, candidate_id=candidate_id)
    current = _target(after, operation_id=operation_id, feature_id=feature_id,
                      setup_id=setup_id, candidate_id=candidate_id)
    require(all(r["toolpath_generated"] is False and r["toolpath_record_counts"] == []
                for r in before["operations"]), "All six paths must be absent; never regenerate")
    counts = _record_counts(current["toolpath_record_counts"])
    require(current["toolpath_generated"] is True, "Positive generated target records required")
    expected = deepcopy(before)
    target = next(r for r in expected["operations"] if r["native_id"] == operation_id)
    target["toolpath_generated"] = True
    target["toolpath_record_counts"] = deepcopy(counts)
    require(same_observed_context(expected, after, allow_dirty=True),
            "GTP changed a sibling, target definition/tool, feature, stock or saved source")
    return deepcopy(current)


def initial_gtp_marker(document_path, source_sha256, operation_id, candidate_id, mt_sha256):
    """Output/receipt names cannot create another initial-generation identity."""
    source = Path(document_path).resolve()
    key = _digest(dict(scope=SCOPE, document=str(source).casefold(),
        source_sha256=source_sha256, operation=operation_id,
        candidate=candidate_id, candidate_mt_sha256=mt_sha256))
    return source.parent / ("sandvik_initial_gtp_" + key + ".json")


def load_completed_assignment(saved, *, assignment_receipt_path,
        assignment_receipt_sha256,
        expected_candidate_tool_native_id, **args):
    """Extend a validated saved-state loader; do not replay assignment or fresh-output gates."""
    from scripts.sw_cam_completed_sandvik_assignment import assignment_marker, verify_assignment_delta
    expected_candidate_payload = saved["payload"]
    data, pin = read_pin(assignment_receipt_path, assignment_receipt_sha256)
    require(data.get("scope") == ASSIGNMENT_SCOPE and data.get("status") == "review_required"
            and data.get("phase") == "finished", "Completed exact assignment required")
    for flag in ("mutation_attempted", "setter_attempted", "setter_returned",
                 "readback_verified", "firstcut_preserved", "protected_operations_verified",
                 "entry_parameters_read", "entry_parameters_preserved"):
        require(data.get(flag) is True, "Missing completed assignment flag: " + flag)
    for flag in ("native_dispatch_pending", "model_saved", "save_attempted", "GTP_attempted",
                 "GOP_attempted", "AFR_attempted", "tool_edit_attempted", "creator_attempted",
                 "simulation_attempted", "TechDB_write_attempted", "automatic_replay",
                 "automatic_rollback", "post_cleanup_CAM_getters", "units_verified",
                 "cutting_partition_verified", "production_qualified", "entry_strategy_qualified",
                 "may_continue"):
        require(data.get(flag) is False, "Unexpected assignment flag: " + flag)
    require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error")),
            "Failed assignment cannot authorize a continuation")
    require(type(data.get("setter_call_count")) is int and data["setter_call_count"] == 1
            and data.get("setter_return_type") == "int"
            and type(data.get("setter_return_value")) is int and data["setter_return_value"] == 0,
            "Exactly one strict-zero completed SetTool required")
    clean_events(data)
    candidate_id = expected_candidate_tool_native_id
    require(type(candidate_id) is int and candidate_id > 0
            and type(data.get("candidate_id")) is int and data["candidate_id"] == candidate_id
            and type(data.get("process_id")) is int and data["process_id"] == args["process_id"],
            "Assignment candidate or owned process differs")
    require(data["saved_draft_pin"] == saved["pin"]
            and data["saved_file_sha256"] == args["expected_source_sha256"]
            and _file_hash(args["expected_document_path"]) == args["expected_source_sha256"],
            "Saved lineage/source differs")
    _path(data["expected_document_path"], args["expected_document_path"])
    target = {k:args[k] for k in ("target_feature_native_id", "target_operation_native_id",
                                 "target_operation_setup_native_id")}
    for key, value in target.items():
        require(type(value) is int and value > 0 and type(data.get(key)) is int
                and data[key] == value and saved["target"][key] == value, "Exact target binding required")
    require(same_observed_context(saved["state"], data["before"]), "Assignment did not start at saved state")
    require(data["before_candidate"] == data["after_candidate"] == expected_candidate_payload,
            "Candidate payload differs from validated Save reference")
    require(data["before_levels"] == data["after_levels"] == saved["firstcut"]["after_levels"],
            "Levels/setup changed during assignment")
    require(data["before_entry_parameters"] == data["after_entry_parameters"]
            and isinstance(data["after_entry_parameters"], dict) and data["after_entry_parameters"],
            "Completed stable raw entry observation required")
    entry = data["after_entry_parameters"]
    require(entry.get("scope") == "ROUGH_ENTRY_DEPTH_ALLOWANCE_RAW_READER_V1"
            and entry.get("parameter_reads_complete") is True
            and type(entry.get("native_getter_calls")) is int and entry["native_getter_calls"] == 31
            and type(entry.get("interface_queries")) is int and entry["interface_queries"] == 3,
            "Complete bounded raw entry reader result required")
    verify_assignment_delta(data["before"], data["after"], target["target_operation_native_id"],
                            expected_candidate_payload["tool"])
    _target(data["after"], operation_id=target["target_operation_native_id"],
            feature_id=target["target_feature_native_id"], setup_id=target["target_operation_setup_native_id"],
            candidate_id=candidate_id)
    require(data["continuation_state"] == data["after"]
            and data["state_sha256"] == _digest(data["after"])
            and data["after_cleanup_document"] == data["after"]["document"]
            and type(data["after"]["document"]["needs_save"]) is bool,
            "Exact current assigned continuation required")
    guard = data.get("dispatch_guard", {})
    require(guard.get("invalid") is False and guard.get("claimed") is True
            and guard.get("native_call_attempted") is True and guard.get("native_call_returned") is True,
            "One completed guarded assignment required")
    mt_pin = data["candidate_mt_pin"]
    require(mt_pin == saved["phase1"]["candidate_asset"]
            and _file_hash(mt_pin["path"]) == mt_pin["sha256"], "Candidate MT lineage changed")
    marker = assignment_marker(args["expected_document_path"], args["expected_source_sha256"],
        target["target_operation_native_id"], candidate_id, mt_pin["sha256"])
    _path(data["assignment_marker_path"], marker)
    marker_data, marker_pin = read_pin(str(marker), _file_hash(marker))
    expected_marker = dict(scope=ASSIGNMENT_SCOPE, status="review_required", phase="finished",
        document=args["expected_document_path"], source_sha256=args["expected_source_sha256"],
        saved_draft_pin=dict(path=saved["pin"]["path"], sha256=saved["pin"]["sha256"]),
        operation_id=target["target_operation_native_id"], candidate_id=candidate_id,
        receipt_path=assignment_receipt_path, setter_call_count=1, setter_returned=True,
        native_dispatch_pending=False, readback_verified=True, automatic_replay=False)
    for key in ("document", "receipt_path"):
        _path(marker_data[key], expected_marker[key])
        expected_marker[key] = marker_data[key]
    require(marker_data == expected_marker, "Completed assignment marker differs")
    pins = saved["pins"] + [pin, marker_pin, mt_pin]
    for item in pins:
        require(_file_hash(item["path"]) == item["sha256"], "Assigned continuation evidence changed")
    return dict(data=data, pin=pin, marker_pin=marker_pin, pins=pins,
        state=deepcopy(data["after"]), candidate_payload=deepcopy(expected_candidate_payload),
        levels=deepcopy(data["after_levels"]), entry=deepcopy(data["after_entry_parameters"]),
        target=target, candidate_id=candidate_id,
        saved=saved, native_called=False, production_qualified=False)
