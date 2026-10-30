"""Continue only the unattempted noncutting export after a pinned S_FALSE stop.

This file has no CAD discovery or native connection. The caller supplies the
existing guarded dispatch and current-tool validator. Historical cutting bytes
remain an observation of their original holder context, not a qualified tool.
"""
from copy import deepcopy
from pathlib import Path

from scripts.sw_cam_existing_sandvik import (
    SCOPE as OBSERVER_SCOPE, BINDING_KEYS, FIELDS, field_equal, read_pin,
    clean_events, check_document_target, raw_export_pin, analyze_export,
    export_marker, fresh_output, _file_hash)
from scripts.sw_cam_generation import _write_receipt

SCOPE = "EXISTING_NONCUTTING_EXPORT_CONTINUATION_V1"
LABEL = "CreateSTLOfNonCuttingPortion"


def hresult_observation(value):
    """HRESULT is signed 32-bit. SUCCEEDED describes severity, not CAM geometry."""
    if type(value) is not int or not -(2**31) <= value < 2**31:
        raise ValueError("Strict signed 32-bit HRESULT required")
    return dict(raw_hresult=value, hresult_hex=f"0x{value & 0xffffffff:08X}",
                success_severity=value >= 0, s_false=value == 1,
                application_semantics_verified=False)


def noncutting_marker(original):
    """Output names cannot create a second native attempt identity."""
    p = Path(original)
    return p.with_name(p.stem + ".noncutting.json")


def _same_path(actual, expected):
    check_document_target(actual, None, expected_path=str(expected), required=True)


def load_cutting_export_stop(prior, *, completed_receipt_path,
        completed_receipt_sha256, expected_cutting_sha256, **args):
    """Extend the existing pure R83 evidence loader; do not repeat its framework.

    `prior` must come from load_existing_candidate_evidence. This checks only
    the completed R84c cutting-return stop and its immutable original marker.
    No output is created, no holder is accepted, and no dispatch is authorized
    without the caller's subsequent current-tool/source/holder validation.
    """
    data, pin = read_pin(completed_receipt_path, completed_receipt_sha256)
    if (data.get("scope") != OBSERVER_SCOPE or data.get("status") != "uncertain"
        or data.get("phase") != "finished"
        or data.get("failed_phase") != "CreateSTLOfCuttingPortion"
        or data.get("export_attempted") is not True):
        raise ValueError("Only the completed cutting HRESULT stop is supported")
    for key in ("native_dispatch_pending", "mutation_attempted", "tool_creation_attempted",
                "MT_load_attempted", "field_setter_attempted", "holder_setter_attempted",
                "operation_assignment_attempted", "GTP_attempted", "GOP_attempted",
                "AFR_attempted", "simulation_attempted", "model_saved", "save_attempted",
                "TechDB_write_attempted", "automatic_replay", "automatic_rollback",
                "units_verified", "physical_tool_qualified", "cutting_partition_verified",
                "numeric_profile_verified", "production_qualified", "may_continue",
                "exports_verified", "raw_exports_pinned", "readback_verified",
                "protected_context_unchanged", "post_cleanup_CAM_getters"):
        if data.get(key) is not False:
            raise ValueError("Unexpected prior flag: " + key)
    if (data.get("exports") != {} or any(k in data for k in
            ("after", "after_candidate", "receipt_write_error"))):
        raise ValueError("Completed export or post-state is outside this continuation")
    issue = data.get("issue", {})
    if issue.get("type") != "ValueError" or issue.get("locations") != [
        dict(file="sw_cam_existing_sandvik.py", function="observe_existing_sandvik", line=600),
        dict(file="sw_cam_existing_sandvik.py", function="export", line=495)]:
        raise ValueError("Different export failure cannot authorize continuation")
    clean_events(data)
    bound = {k: args[k] for k in BINDING_KEYS + ("saved_plan_receipt_path", "saved_plan_receipt_sha256")}
    if data.get("request_binding") != bound:
        raise ValueError("Completed observation binding differs")
    tool_id = args["expected_candidate_tool_native_id"]
    if (type(tool_id) is not int or type(data.get("tool_native_id")) is not int
        or data["tool_native_id"] != tool_id or type(data.get("process_id")) is not int
        or data["process_id"] != args["process_id"]
        or data.get("source_before_sha256") != args["expected_source_sha256"]
        or data.get("expected_source_sha256") != args["expected_source_sha256"]
        or data.get("prior_receipt_pin") != prior["pin"]
        or data.get("prior_creation_marker_pin") != prior["creation_pin"]
        or data.get("anchor") != prior["anchor"].summary()
        or data.get("profile_observation") != prior["profile_observation"]):
        raise ValueError("Completed observation lineage differs")
    _same_path(data["expected_document_path"], args["expected_document_path"])
    before = data["before_candidate"]
    tool = before["tool"]
    if (type(tool.get("native_id")) is not int or tool["native_id"] != tool_id
        or tool.get("tool_type_raw") != 14 or tool.get("profile_complete") is not True
        or tool.get("profiles") != prior["data"]["tool"]["profiles"]
        or any(not field_equal(k, tool["parameters"][k], v) for k, v in FIELDS)
        or before.get("profile_observation") != prior["profile_observation"]
        or before.get("firstcut") != prior["firstcut"]):
        raise ValueError("Frozen cutting tool/firstcut observation differs")
    _same_path(tool["mt_path_raw"], prior["data"]["candidate_asset"]["path"])
    rows = data.get("dispatches")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Exactly one completed cutting dispatch required")
    row = rows[0]
    if (row.get("label") != "CreateSTLOfCuttingPortion"
        or row.get("pending") is not False or row.get("attempted") is not True
        or row.get("returned") is not True or row.get("return_type") != "int"
        or type(row.get("return_value")) is not int or row["return_value"] != 1):
        raise ValueError("Cutting must have returned strict int S_FALSE once")
    cutting = raw_export_pin(row["path"])
    if cutting["sha256"] != expected_cutting_sha256 or cutting["bytes"] <= 0:
        raise ValueError("Completed cutting artifact differs or is empty")
    original = export_marker(args["expected_document_path"], prior["pin"]["sha256"], tool_id)
    _same_path(original, prior["marker"])
    _same_path(data["dispatch_marker_path"], original)
    marker, marker_pin = read_pin(str(original), _file_hash(original))
    expected_marker = dict(scope=OBSERVER_SCOPE, status="uncertain", phase="finished",
        receipt_path=completed_receipt_path, document=args["expected_document_path"],
        source_sha256=args["expected_source_sha256"], phase1_receipt_sha256=prior["pin"]["sha256"],
        tool_native_id=tool_id, native_dispatch_pending=False, dispatches=rows,
        exports={}, automatic_replay=False)
    # Paths may have an equivalent Windows/UNC spelling; all other fields exact.
    for key in ("receipt_path", "document"):
        _same_path(marker.get(key), expected_marker[key])
        expected_marker[key] = marker[key]
    if marker != expected_marker:
        raise ValueError("Original finished export marker differs")
    if _file_hash(args["expected_document_path"]) != args["expected_source_sha256"]:
        raise ValueError("Saved source differs")
    sibling = noncutting_marker(original)
    if sibling.exists() or sibling.is_symlink():
        raise ValueError("Noncutting attempt already exists; no replay")
    immutable = prior["pins"] + [pin, marker_pin, cutting]
    return dict(scope=SCOPE, prior_receipt_pin=pin, original_marker_pin=marker_pin,
        noncutting_marker_path=str(sibling), cutting_pin=cutting,
        cutting_hresult=hresult_observation(1), tool_native_id=tool_id,
        process_id=args["process_id"], expected_document_path=args["expected_document_path"],
        expected_source_sha256=args["expected_source_sha256"], immutable_pins=immutable,
        original_holder_observation=deepcopy(before["holder_profile"]),
        cutting_applicability_to_current_holder_verified=False,
        full_prior_post_state_verified=False, units_verified=False,
        physical_tool_qualified=False, cutting_partition_verified=False,
        production_qualified=False)


def export_noncutting_once(evidence, path, *, dispatch_once, validate_current):
    """One guarded noncutting call, with a durable deterministic pending claim.

    `validate_current()` must raise unless the caller has validated its owned
    process/document/source, tool263 fields/profile, firstcut and CURRENT holder
    context (including any separately qualified mode change). It is called both
    before dispatch and from persist_pending. No equality to the historical
    holder is imposed here. `dispatch_once(label,path,persist_pending)` must use
    ScopedCamDispatchGuard.dispatch_once and invoke the callback before calling
    exactly the named native method. No native call is made by this helper.

    The caller must still perform its full protected after-check. This result
    records file observation only and cannot authorize Save/assignment/GTP.
    """
    if evidence.get("scope") != SCOPE:
        raise ValueError("Validated continuation evidence required")
    original = evidence["original_marker_pin"]
    marker = noncutting_marker(original["path"])
    _same_path(evidence["noncutting_marker_path"], marker)
    blocked = {Path(p["path"]).resolve() for p in evidence["immutable_pins"]}
    blocked |= {Path(evidence["expected_document_path"]).resolve(), marker.resolve()}
    output = fresh_output(path, ".stl", blocked)
    row = dict(label=LABEL, path=str(output), pending=True, attempted=False, returned=False)
    result = dict(scope=SCOPE, phase="pending", status="uncertain", automatic_replay=False,
        original_marker_pin=deepcopy(original), prior_receipt_pin=deepcopy(evidence["prior_receipt_pin"]),
        cutting_pin=deepcopy(evidence["cutting_pin"]), tool_native_id=evidence["tool_native_id"],
        process_id=evidence["process_id"], expected_document_path=evidence["expected_document_path"],
        expected_source_sha256=evidence["expected_source_sha256"],
        dispatch=row, native_dispatch_pending=True, cutting_export_attempted=False,
        raw_file_observed=False, classification_pending=True, units_verified=False,
        physical_tool_qualified=False, production_qualified=False,
        cutting_applicability_to_current_holder_verified=False,
        protected_context_unchanged=False, readback_verified=False, may_continue=False)
    claimed = False

    def verify_immutable():
        for pin in evidence["immutable_pins"]:
            if _file_hash(pin["path"]) != pin["sha256"]:
                raise ValueError("Immutable continuation evidence changed")
        if _file_hash(evidence["expected_document_path"]) != evidence["expected_source_sha256"]:
            raise ValueError("Saved source changed")

    def pending():
        nonlocal claimed
        if claimed:
            raise ValueError("Pending callback cannot be replayed")
        verify_immutable()
        validate_current()
        fresh_output(path, ".stl", blocked)
        row["attempted"] = True
        _write_receipt(marker, result, create=True)
        claimed = True

    if marker.exists() or marker.is_symlink():
        raise ValueError("Noncutting attempt already exists; no replay")
    verify_immutable()
    validate_current()
    try:
        value = dispatch_once(LABEL, str(output), pending)
        if not claimed:
            raise ValueError("Dispatch did not persist its required pending claim")
        row.update(returned=True, pending=False, return_type=type(value).__name__,
                   return_value=value if type(value) in (int, bool, float, str, type(None)) else None)
        result["native_dispatch_pending"] = False
        _write_receipt(marker, result)
        # Preserve completed output evidence even when the HRESULT is an error.
        if output.is_file() or output.is_symlink():
            result["noncutting_pin"] = raw_export_pin(output)
            _write_receipt(marker, result)
        result["hresult"] = hresult_observation(value)
        _write_receipt(marker, result)
        if not result["hresult"]["success_severity"]:
            raise ValueError("Noncutting export returned a failure HRESULT")
        if not result.get("noncutting_pin", {}).get("bytes"):
            raise ValueError("Successful COM severity has no nonempty fresh output")
        result["raw_file_observed"] = True
        result["analysis"] = analyze_export(output, "noncutting")
        if (result["analysis"].get("pin") != result["noncutting_pin"]
            or raw_export_pin(output) != result["noncutting_pin"]):
            raise ValueError("Export changed during observation")
        verify_immutable()
        result.update(phase="finished", status="export_observed")
        _write_receipt(marker, result)
        return result
    except Exception as exc:
        if claimed:
            result.update(phase="finished", status="uncertain", issue=dict(type=type(exc).__name__, reason=str(exc)))
            _write_receipt(marker, result)
        raise
