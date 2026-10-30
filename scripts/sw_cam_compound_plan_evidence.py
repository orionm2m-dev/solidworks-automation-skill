"""Pinned current compound replacement scope and primary route evidence."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_mill_saved_plan_rebind import _full_details
from scripts.sw_cam_mill_stock_export_evidence import _require
from scripts.sw_cam_mill_compound_strategy import validate_compound_scope
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_compound_plan_delta import target_operations

SCOPE = "MILL_REPLACED_COMPOUND_PLAN_V1"

def load_primary_route(path, sha, anchor):
    data, pin = read_pin(path, sha)
    _require(data.get("status") == "PRIMARY_ROUTE_CONFIRMED_FEATURE_REGEN_SCOPE_REQUIRES_NATIVE_QUALIFICATION",
             "Pinned primary feature-regeneration route required")
    _require(data.get("current_r55", {}).get("saved_sha256") == anchor.state["saved_file_sha256"],
             "Primary review belongs to a different saved input")
    sources = data.get("sources")
    _require(type(sources) is list and 1 <= len(sources) <= 24, "Bounded primary source pins required")
    for source in sources:
        _require(type(source.get("path")) is str and Path(source["path"]).is_file()
            and _file_hash(source["path"]) == source["sha256"], "Primary source changed")
    _require(any(source["sha256"] == anchor.receipt_pin["sha256"] for source in sources),
             "Primary review does not pin the saved input receipt")
    return dict(pin=pin, sources=deepcopy(sources), status=data["status"])

def check_primary_route(route):
    pin = route["pin"]
    _require(read_pin(pin["path"], pin["sha256"])[1] == pin, "Primary route receipt changed")
    for source in route["sources"]:
        _require(_file_hash(source["path"]) == source["sha256"], "Primary source changed")

def verify_protected_details(anchor, state, details):
    _full_details(details["selected_tool_details"], anchor)
    _require(details["selected_tool_details"] == anchor.baseline_tool_details,
             "Protected full cutter/holder profile changed")
    _require([r["native_id"] for r in state["operations"]
              if r["native_id"] in anchor.operation_ids] == anchor.operation_ids,
             "Protected operation relative order changed")

def validate_replacement_baseline(anchor, *, target_feature_native_id,
        target_owner_setup_native_id, target_operation_setup_native_id,
        expected_target_operation_native_ids, expected_target_operation_types,
        expected_target_tool_native_ids, expected_strategy_id, expected_strategy_name):
    _require(anchor.data.get("scope") == "MILL_APPEND_OPERATIONS_V1",
             "This replacement capability starts from one verified appended save")
    header = validate_compound_scope(anchor, target_feature_native_id, target_owner_setup_native_id, 3)
    target = target_operations(anchor.state, target_feature_native_id, target_operation_setup_native_id)
    _require([r["native_id"] for r in target] == expected_target_operation_native_ids
        and [r["mill_operation_type"] for r in target] == expected_target_operation_types
        and [r["assigned_tool"]["native_id"] for r in target] == expected_target_tool_native_ids,
        "Pinned target operations/types/tools differ")
    _require([r["native_id"] for r in anchor.state["operations"] if r not in target] == anchor.operation_ids,
             "All non-target operations must be covered by protected full-tool evidence")
    details = anchor.data["saved_details"]
    _require(details["three_step_profile"]["compound_strategy"] == anchor.profile["details"],
             "Saved exact three-step profile differs")
    strategy = details["strategy"]["compound_strategy"]
    _require(type(expected_strategy_id) is int and strategy["attribute_id"] == expected_strategy_id
        and strategy["attribute_name"] == strategy["active_attribute_name"] == expected_strategy_name,
        "Expected current strategy differs")
    _require(strategy["mill_attributes"].get("names_enumeration_verified") is True
        and "Rough-Finish" in strategy["mill_attributes"]["values"],
        "Exact requested strategy absent from observed catalogue")
    verify_protected_details(anchor, anchor.state, details)
    return dict(header=header, details=deepcopy(details))
