"""Accept a completed single holder-shape change without reopening its dispatch gate."""
from copy import deepcopy
from pathlib import Path

from scripts.sw_cam_holder_shape_cas import SCOPE as CAS_SCOPE, DESIRED_INPUT, shape_marker
from scripts.sw_cam_holder_mode_query import SCOPE as QUERY_SCOPE, HOLDER_FIELDS, _finite_scalar
from scripts.sw_cam_holder_observation import complete_holder_profile, observe_holder_nominal
from scripts.sw_cam_mill_tool_geometry import _integer, _text
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_sandvik_phase1 import FIELDS, field_equal
from scripts.sw_cam_thread import _file_hash
from scripts.sw_operation_guard import check_document_target


def same_path(value, expected):
    check_document_target(value, None, expected_path=str(expected), required=True)


def _raw_holder(value):
    if set(value) != set(HOLDER_FIELDS):
        raise ValueError("Complete exact holder scalar snapshot required")
    for name in HOLDER_FIELDS:
        item = value[name]
        if name in ("GetHolderShape", "GetHolderNumber", "GetName"):
            _text(item, name)
        elif name == "GetHolderId":
            _integer(item, name)
        else:
            _finite_scalar(item, name)


def load_completed_holder_cas(prior, cut_evidence, *, holder_shape_receipt_path,
        holder_shape_receipt_sha256, **args):
    """File-only extension of validated candidate and cutting-stop evidence.

    Inputs come from load_existing_candidate_evidence and load_cutting_export_stop.
    This function does not rerun their fresh-output gates, write any marker, or
    authorize Save/GTP. The caller still verifies current native state and all
    protected operations before accepting a completed observation.
    """
    data, pin = read_pin(holder_shape_receipt_path, holder_shape_receipt_sha256)
    if (data.get("scope") != CAS_SCOPE or data.get("status") != "review_required"
        or data.get("phase") != "finished"):
        raise ValueError("Completed holder-shape CAS required")
    for flag in ("mutation_attempted", "setter_attempted", "native_call_returned",
                 "readback_verified", "holder_profile_verified", "mode_changed",
                 "mode_and_profile_verified", "hresult_succeeded"):
        if data.get(flag) is not True:
            raise ValueError("Incomplete holder-shape proof: " + flag)
    for flag in ("native_dispatch_pending", "assignment_attempted", "GTP_attempted",
                 "save_attempted", "export_attempted", "file_reference_setter_attempted",
                 "tool_creation_attempted", "TechDB_write_attempted", "automatic_replay",
                 "automatic_rollback", "full_context_rechecked", "protected_context_unchanged",
                 "production_qualified", "physical_holder_qualified", "may_continue",
                 "holder_metadata_changes_qualified"):
        if data.get(flag) is not False:
            raise ValueError("Unexpected holder-shape flag: " + flag)
    if any(k in data for k in ("issue", "receipt_write_error")):
        raise ValueError("Failed or unpublished holder-shape result")
    result = data.get("setter_return_value")
    if data.get("setter_return_type") != "int" or type(result) is not int or not 0 <= result < 2**31:
        raise ValueError("Completed successful signed32 HRESULT required")
    clean_events(data)
    guards = data.get("guard_diagnostics")
    if (type(guards) is not list or not guards
        or any(g.get("invalid") is not False for g in guards)):
        raise ValueError("Completed valid native guards required")
    dispatches = [g for g in guards if g.get("native_call_attempted") is True]
    if (len(dispatches) != 1 or dispatches[0].get("native_call_returned") is not True
        or dispatches[0].get("claimed") is not True
        or any(type(g.get("native_call_attempted")) is not bool for g in guards)):
        raise ValueError("Exactly one completed holder dispatch required")
    tool_id = args["expected_candidate_tool_native_id"]
    if (type(tool_id) is not int or type(data.get("tool_native_id")) is not int
        or data["tool_native_id"] != tool_id or prior["data"]["new_tool_native_id"] != tool_id
        or cut_evidence["tool_native_id"] != tool_id
        or type(data.get("process_id")) is not int or data["process_id"] != args["process_id"]
        or data["source_sha256"] != args["expected_source_sha256"]
        or cut_evidence["process_id"] != args["process_id"]
        or cut_evidence["expected_source_sha256"] != args["expected_source_sha256"]):
        raise ValueError("Holder-shape candidate/process/source differs")
    same_path(data["expected_document_path"], args["expected_document_path"])
    if (data.get("original_observation_pin") != cut_evidence["prior_receipt_pin"]
        or data.get("desired_input") != DESIRED_INPUT):
        raise ValueError("Holder-shape observation or documented input differs")
    query, query_pin = read_pin(data["query_pin"]["path"], data["query_pin"]["sha256"])
    if (query_pin != data["query_pin"] or query.get("scope") != QUERY_SCOPE
        or query.get("status") != "observed" or query.get("phase") != "finished"
        or query.get("readback_verified") is not True or query.get("raw_dimensions") is not True
        or query.get("tool_native_id") != tool_id or type(query.get("tool_native_id")) is not int
        or query.get("process_id") != args["process_id"] or type(query.get("process_id")) is not int
        or query.get("source_sha256") != args["expected_source_sha256"]
        or query.get("observation_pin") != cut_evidence["prior_receipt_pin"]):
        raise ValueError("Completed originating holder query differs")
    for flag in ("mutation_attempted", "export_attempted", "save_attempted", "assignment_attempted",
                 "GTP_attempted", "profile_read_attempted", "manufacturing_qualified", "may_mutate",
                 "full_context_rechecked", "units_verified"):
        if query.get(flag) is not False:
            raise ValueError("Unexpected originating query flag: " + flag)
    if any(k in query for k in ("issue", "receipt_write_error")):
        raise ValueError("Originating query failed")
    clean_events(query)
    if (query.get("guard_diagnostic", {}).get("invalid") is not False
        or query["guard_diagnostic"].get("native_call_attempted") is not False):
        raise ValueError("Originating query guard differs")
    same_path(query["expected_document_path"], args["expected_document_path"])
    before, after = data["before"], data["after"]
    if (query["before_document"] != prior["data"]["before_document"]
        or query["after_document"] != query["before_document"]
        or data["before_document"] != query["after_document"]
        or query["holder"] != query["after_holder"] or before["holder"] != query["after_holder"]
        or data["expected_holder_shape_raw"] != before["holder"]["GetHolderShape"]
        or query["before_tool_parameters"] != prior["data"]["tool"]["parameters"]
        or query["after_tool_parameters"] != query["before_tool_parameters"]):
        raise ValueError("Exact pre-change query snapshot differs")
    for state in (before, after):
        _raw_holder(state["holder"])
        if (set(state["tool_parameters"]) != {k for k, _ in FIELDS}
            or any(not field_equal(k, state["tool_parameters"][k], v) for k, v in FIELDS)):
            raise ValueError("All nine tool fields must be preserved")
        same_path(state["mt_path_raw"], prior["data"]["tool"]["mt_path_raw"])
        same_path(state["holder"]["GetName"], prior["holder"]["file_path"])
    mode = after["holder"]["GetHolderShape"]
    if (not mode or mode == before["holder"]["GetHolderShape"]
        or before["tool_parameters"] != after["tool_parameters"]
        or before["mt_path_raw"] != after["mt_path_raw"]
        or before["holder"]["GetName"] != after["holder"]["GetName"]
        or before["holder"]["GetProtrusion"] != 25 or after["holder"]["GetProtrusion"] != 25):
        raise ValueError("Holder-mode or required tool/path/protrusion invariant differs")
    recipe = prior["holder"]
    if (data.get("holder_recipe") != recipe or len(recipe["records"]) != 17
        or type(data.get("expected_nominal_curve_count")) is not int
        or data["expected_nominal_curve_count"] != 17):
        raise ValueError("Exact pinned seventeen-segment holder recipe required")
    profile = after["holder_profile"]
    complete_holder_profile(profile)
    diagnostic = after["holder_diagnostic"]
    if (diagnostic.get("capture_complete") is not True or diagnostic.get("stage") != "complete"
        or diagnostic.get("state") != profile):
        raise ValueError("Complete retained raw holder diagnostic required")
    verification = observe_holder_nominal(profile, recipe, 25)
    if (verification.get("native_holder_shape_verified") is not True
        or verification.get("nominal_match") is not True
        or after.get("nominal_verification") != verification):
        raise ValueError("Observed holder does not match the pinned recipe")
    bd, ad = data["before_document"], data["after_document"]
    if (type(ad.get("needs_save")) is not bool or type(bd.get("needs_save")) is not bool
        or dict(ad, needs_save=bd["needs_save"]) != bd):
        raise ValueError("Document identity changed during shape selection")
    marker_path = shape_marker(args["expected_document_path"], prior["pin"]["sha256"], tool_id)
    same_path(data["marker_path"], marker_path)
    marker, marker_pin = read_pin(str(marker_path), _file_hash(marker_path))
    expected_marker = dict(scope=CAS_SCOPE, receipt_path=holder_shape_receipt_path,
        tool_native_id=tool_id, query_pin=query_pin, status="review_required", phase="finished",
        native_dispatch_pending=False, native_call_returned=True, automatic_replay=False)
    same_path(marker.get("receipt_path"), holder_shape_receipt_path)
    expected_marker["receipt_path"] = marker["receipt_path"]
    if marker != expected_marker:
        raise ValueError("Original completed CAS marker differs")
    pins = {}
    for item in prior["pins"] + cut_evidence["immutable_pins"] + [pin, query_pin, marker_pin]:
        key = str(Path(item["path"]).resolve()).casefold()
        if key in pins and pins[key]["sha256"] != item["sha256"]:
            raise ValueError("Conflicting holder continuation evidence")
        if _file_hash(item["path"]) != item["sha256"]:
            raise ValueError("Holder continuation evidence changed")
        pins[key] = item
    if _file_hash(args["expected_document_path"]) != args["expected_source_sha256"]:
        raise ValueError("Saved source changed")
    return dict(data=data, pin=pin, marker_pin=marker_pin, query_pin=query_pin,
        pins=list(pins.values()), after_document=deepcopy(ad), holder_snapshot=deepcopy(after["holder"]),
        holder_profile=deepcopy(profile), holder_verification=verification)
