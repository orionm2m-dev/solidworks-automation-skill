"""Pinned input checks for one additive compound MILL operation plan."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_saved_plan_rebind import _full_details
from scripts.sw_cam_mill_compound_strategy import validate_compound_scope
from scripts.sw_cam_mill_stock_export_evidence import _require
from scripts.sw_cam_turn_tool import _digest

SCOPE = "MILL_APPEND_OPERATIONS_V1"

def load_target_profile(path, sha, anchor, *, process_id, source_sha, feature_id, owner_id):
    data, pin = read_pin(path, sha)
    _require(data.get("scope") == "MILL_SAVED_COMPOUND_STRATEGY_READ_V1"
        and data.get("status") == "review_required" and data.get("phase") == "finished",
        "Completed compound profile receipt required")
    for key in ("read_only", "readback_verified", "step_dimensions_read",
                "index_base_verified", "complete_step_coverage"):
        _require(data.get(key) is True, "Complete profile flag required: " + key)
    for key in ("mutation_attempted", "AFR_attempted", "GOP_attempted", "GTP_attempted",
                "model_saved", "save_attempted", "geometry_edit_attempted",
                "strategy_assignment_attempted", "post_cleanup_CAM_getters"):
        _require(data.get(key) is False, "Unexpected profile flag: " + key)
    _require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error")),
             "Failed profile receipt cannot authorize dispatch")
    _require(type(data.get("process_id")) is int and data["process_id"] == process_id
        and data.get("saved_file_sha256") == source_sha
        and data.get("anchor") == anchor.summary(), "Target profile lineage differs")
    clean_events(data)
    header = validate_compound_scope(anchor, feature_id, owner_id, 3)
    scope = data.get("compound_scope", {})
    _require(scope == dict(feature_native_id=feature_id, owner_setup_native_id=owner_id,
        expected_step_count=3, expected_header=header, observation="three_step_profile"),
        "Exact observed three-step target required")
    before, after = data.get("before_compound_strategy"), data.get("after_compound_strategy")
    _require(type(before) is dict and before == after
        and before.get("metadata_read_complete") is True
        and before.get("complete_step_coverage") is True
        and before.get("index_base_verified") is True
        and before.get("feature_native_id") == feature_id
        and before.get("owner_setup_native_id") == owner_id
        and before.get("number_of_steps") == 3
        and data.get("compound_strategy_sha256") == _digest(before),
        "Stable exact profile proof required")
    _require(data.get("state_sha256") == _digest(data["before"])
        and data["before"] == data["after"], "Profile state proof differs")
    if data.get("strategy_capture_mode") == "full_plan":
        anchor.verify(data["before"])
    elif data.get("strategy_capture_mode") == "target_only":
        _require(data["before"]["document"] == anchor.state["document"]
            and data["before"]["features"] == [dict(setup_native_id=owner_id, geometry=header)],
            "Target-only document/header differs")
    else:
        raise ValueError("Unknown target profile capture scope")
    return dict(pin=pin, header=header, details=deepcopy(before))

def require_protected_tools(anchor, state, details):
    """This first append capability protects all prior operations as one shared tool."""
    _full_details(details, anchor)
    _require([r["native_id"] for r in anchor.state["operations"]] == anchor.operation_ids,
             "All prior operations must be covered by the protected full-tool evidence")
    _require(hasattr(anchor, "baseline_tool_details")
        and details == anchor.baseline_tool_details, "Existing full cutter/holder profiles changed")
    ids = anchor.operation_ids
    _require([r["native_id"] for r in state["operations"] if r["native_id"] in ids] == ids,
             "Protected operation membership/order changed")

def attempt_marker(registry_path, document_path, source_sha, feature_id):
    registry = Path(registry_path)
    _require(registry.is_absolute() and registry.is_dir() and not registry.is_symlink(),
             "Existing absolute attempt registry directory required")
    key = _digest(dict(document=str(Path(document_path).resolve()).casefold(),
                       source_sha256=source_sha, target_feature_native_id=feature_id))
    return registry / ("mill_append_" + key + ".json")
