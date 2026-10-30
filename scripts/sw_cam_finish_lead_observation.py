"""Bounded read-only lead-in/out supplement to a completed finish observation."""
from copy import deepcopy
from math import isfinite
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_existing_sandvik import resolve_existing_context
from scripts.sw_cam_route_entry_evidence import load_continuation_checkpoint
from scripts.sw_cam_route_checkpoint import RouteCheckpointContext
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_rough_entry_parameters import bounded_raw_observation
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_route_entry_continuation import _events
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_finish_observation import (
    SCOPE as OBSERVATION_SCOPE, FINISH_BASE_FIELDS, FINISH_V3_FIELDS,
    finish_row, _capture_operations,
)
from scripts.sw_operation_guard import check_document_target

SCOPE = "SAVED_ROUTE_FINISH_LEAD_OBSERVATION_V1"
LEAD_IID = "{6DA10A61-7C7F-11D6-A9EF-00062999E55F}"
LEAD_FIELDS = {
    "LeadType": "int", "LeadAngle": "number", "ArcAngle": "number",
    "SidePassType": "int", "CutDepthType": "int", "StartAngle": "number",
    "GetArcRadius2": "number_bool_number", "GetLeadOverlap2": "number_bool_number",
    "GetLeadAmt2": "number_bool_number", "GetIsSameLeadinout": "bool",
    "GetFeedRate": "number_bool",
}
NO_ACTION_FLAGS = (
    "mutation_attempted", "GTP_attempted", "GOP_attempted", "AFR_attempted",
    "save_attempted", "model_saved", "export_attempted", "simulation_attempted",
    "setter_attempted", "native_dispatch_pending", "automatic_retry",
)


def load_completed_finish_observation(path, sha256, **args):
    """Only this exact completed observation over the current completed Save."""
    data, pin = read_pin(path, sha256)
    require(data.get("scope") == OBSERVATION_SCOPE and data.get("status") == "observed"
        and data.get("phase") == "finished" and data.get("readback_verified") is True
        and data.get("detail_observation_complete") is True and data.get("read_only") is True,
        "Completed finish observation required")
    require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error")), "Observation error present")
    require(all(data.get(k) is False for k in NO_ACTION_FLAGS), "Observation contained unexpected action")
    for k in ("process_id", "finish_operation_native_id", "finish_tool_native_id", "target_feature_native_id"):
        require(type(data.get(k)) is int and data[k] == args[k], "Observation target differs: " + k)
    require(data["expected_source_sha256"] == args["expected_source_sha256"], "Observation source differs")
    check_document_target(data["expected_document_path"], None, expected_path=args["expected_document_path"], required=True)
    clean_events(data)
    parent = data["checkpoint_pin"]
    loaded = load_continuation_checkpoint(parent["path"], parent["sha256"], action="save", check_current_source=True, **args)
    state = loaded["state"]
    require(loaded.get("historical_only") is False and state["document"]["needs_save"] is False,
        "Current clean saved checkpoint required")
    require(data["before_context"] == data["after_context"] == state
        and data["after_cleanup_document"] == state["document"], "Observation route changed")
    require(data["units_before"] == data["units_after"], "Observation units changed")
    selected = finish_row(state, args)
    require(data["tool_summary"] == selected["assigned_tool"], "Observed finish assignment differs")
    fields = data["details"]["finish"]
    require(set(fields) == set(FINISH_BASE_FIELDS + FINISH_V3_FIELDS + ("GetPreviousAllowance",))
        and all(v.get("recorded") is True for v in fields.values()), "Exact 24 observed finish settings required")
    require(len(data["snapshot_diagnostics"]) == 2
        and all(d.get("capture_complete") is True for d in data["snapshot_diagnostics"]), "Completed operation snapshots required")
    loaded["pins"] = canonical_evidence_pins(loaded["pins"], data["evidence_pins"], [pin])
    loaded["pin"] = pin
    loaded["finish_observation"] = data
    return loaded


def decode_lead_value(name, value):
    """Validate the installed TLB output order without assigning physical units."""
    kind = LEAD_FIELDS[name]
    def number(v): return type(v) in (int, float) and isfinite(v)
    if kind == "int": valid = type(value) is int
    elif kind == "bool": valid = type(value) is bool
    elif kind == "number": valid = number(value)
    else:
        count = 3 if kind == "number_bool_number" else 2
        valid = type(value) in (tuple, list) and len(value) == count
        valid = valid and number(value[0]) and type(value[1]) is bool
        if valid and count == 3: valid = number(value[2])
    require(valid, "Unexpected ICWLeadInOut shape: " + name)
    result = bounded_raw_observation(value)
    if kind.startswith("number_bool"):
        result["decoded"] = dict(value_raw=value[0], percent=value[1])
        if len(value) == 3: result["decoded"]["incremental_raw"] = value[2]
    return result


def query_lead_interface(raw, typelib_path):
    """One exact generated vtable interface; leave the pinned registry unchanged."""
    from scripts.sw_cam_comtypes import _load_type_library, _is_comtypes_pointer
    require(_is_comtypes_pointer(raw) and bool(raw), "Non-null typed getter result required")
    interface = getattr(_load_type_library(str(typelib_path)), "ICWLeadInOut")
    require(str(interface._iid_).upper() == LEAD_IID, "Unexpected lead interface IID")
    result = raw.QueryInterface(interface)
    require(result is not None and bool(result), "Null lead interface")
    return result


def read_lead_details(raw_operation, feature_dispatch, *, read, typed, lead_typed):
    finish = typed(raw_operation, "ICWFinishMillOp")
    result = {}
    for side, getter in (("lead_in", "IGetLeadin"), ("lead_out", "IGetLeadout")):
        raw = read(finish, getter, feature_dispatch)
        require(raw is not None and bool(raw), "Null " + getter + " result")
        lead = lead_typed(raw)
        result[side] = {name: decode_lead_value(name, read(lead, name)) for name in LEAD_FIELDS}
    return result


def inspect_saved_finish_leads(sw, clsid, typelib_path, *, checkpoint_receipt_path,
        checkpoint_receipt_sha256, **args):
    from scripts.sw_cam_events import CamMessageSession
    validate_inventory_request(**{k: args[k] for k in ("process_id", "expected_document_path",
        "expected_source_sha256", "qualification_only", "acknowledge_disposable_copy", "receipt_path", "message_policy")})
    require(args.get("software_only_experiment") is True, "Explicit software-only observation required")
    loaded = load_completed_finish_observation(checkpoint_receipt_path, checkpoint_receipt_sha256, **args)
    implementation_pin = dict(path=str(Path(__file__).resolve()), sha256=_file_hash(__file__))
    loaded["pins"] = canonical_evidence_pins(loaded["pins"], [implementation_pin])
    require(len(loaded["pins"]) <= 64, "Unchanged evidence limit exceeded")
    receipt = Path(args["receipt_path"])
    require(receipt.is_absolute() and receipt.parent.is_dir() and receipt.suffix.lower() == ".json"
        and not receipt.exists() and not receipt.is_symlink(), "Fresh absolute receipt required")
    protected = {str(Path(p["path"]).resolve()).casefold() for p in loaded["pins"]}
    protected.add(str(Path(args["expected_document_path"]).resolve()).casefold())
    require(str(receipt.resolve()).casefold() not in protected, "Receipt aliases protected evidence")
    observed = loaded["finish_observation"]
    report = dict(schema_version=1, scope=SCOPE, status="error", phase="preflight", read_only=True,
        process_id=args["process_id"], expected_document_path=args["expected_document_path"],
        expected_source_sha256=args["expected_source_sha256"], finish_operation_native_id=args["finish_operation_native_id"],
        finish_tool_native_id=args["finish_tool_native_id"], target_feature_native_id=args["target_feature_native_id"],
        observation_pin=loaded["pin"], evidence_pins=deepcopy(loaded["pins"]), implementation_pin=implementation_pin,
        reused_finish_details=deepcopy(observed["details"]), reused_finish_levels=deepcopy(observed["levels"]),
        reused_unit_record=deepcopy(observed["units_after"]), readback_verified=False,
        full_geometry_rechecked=False, finish_settings_reread=False, units_reread=False,
        production_qualified=False, physical_units_verified=False, enum_binding_verified=False,
        generated_entry_geometry_verified=False, may_continue=False, native_reads=[], snapshot_diagnostics=[])
    report.update({k: False for k in NO_ACTION_FLAGS})
    started = monotonic(); created = False; session = None
    def persist():
        report["elapsed_seconds"] = monotonic() - started
        if created: _write_receipt(receipt, report)
    def events(): _events(session, report)
    try:
        _write_receipt(receipt, report, create=True); created = True
        ctx = RouteCheckpointContext(loaded, dict(args), sw, typelib_path, None, events)
        ctx.files(); ctx.identity()
        ctx.app = _bootstrap(sw, clsid, typelib_path, args["expected_document_path"])
        ctx.identity(); session = CamMessageSession(ctx.app, typelib_path)
        with session:
            with ctx.guard() as guard:
                native = resolve_existing_context(ctx.app, guard.read, guard.typed, {"before": loaded["state"]})
            report["phase"] = "before_operations"; persist()
            diag = dict(phase="before"); report["snapshot_diagnostics"].append(diag)
            report["before_context"] = _capture_operations(ctx, native, loaded["state"], diag)
            finish_row(report["before_context"], args)
            report["phase"] = "lead_fields"; persist()
            with ctx.guard() as guard:
                def note(name, invoke, interface=False):
                    require(len(report["native_reads"]) < 32, "Lead observation count exceeded")
                    row = dict(name=name, stage="attempted"); report["native_reads"].append(row); persist()
                    value = invoke()
                    if interface:
                        require(value is not None and bool(value), "Non-null interface required")
                        row.update(stage="returned", interface_present=True)
                    else: row.update(stage="returned", observation=bounded_raw_observation(value))
                    persist(); return value
                def read(obj, name, *params):
                    return note(name, lambda: guard.read(obj, name, *params), interface=name in ("IGetLeadin", "IGetLeadout"))
                def typed(obj, name): return note(name, lambda: guard.typed(obj, name), interface=True)
                def lead_typed(obj):
                    return note("ICWLeadInOut", lambda: guard._observe(lambda: query_lead_interface(obj, typelib_path)), interface=True)
                raw = native["operations"][args["finish_operation_native_id"]]
                require(_object_id(native["doc"], raw, guard.read) == args["finish_operation_native_id"], "Finish identity changed")
                found = guard.read(native["doc"], "GetCWObjectFromID", 1, args["target_feature_native_id"])
                require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True, "Feature lookup failed")
                feature = guard.typed(found[0], "ICWFeature")
                require(_object_id(native["doc"], feature, guard.read) == args["target_feature_native_id"], "Feature identity changed")
                report["leads"] = read_lead_details(raw, found[0], read=read, typed=typed, lead_typed=lead_typed)
            report["lead_strong_guard"] = guard.summary()
            report["phase"] = "after_operations"; persist()
            diag = dict(phase="after"); report["snapshot_diagnostics"].append(diag)
            report["after_context"] = _capture_operations(ctx, native, loaded["state"], diag)
            require(report["before_context"] == report["after_context"], "Read changed route")
            finish_row(report["after_context"], args)
        _events(session, report, False); ctx.files()
        report["after_cleanup_document"] = ctx.identity()
        report.update(status="observed", phase="finished", readback_verified=True,
            lead_observation_complete=True, atomic_snapshot_claimed=False,
            fresh_observation_scope="lead-in/out definitions and six operation summaries/counts",
            reused_scope="24 finish settings, levels, tool/holder scalars, unit record, 19 feature geometries and saved lineage")
    except Exception as exc:
        report.update(status="error", failed_phase=report["phase"], phase="finished", issue=_error(exc), readback_verified=False)
    finally:
        if session is not None: report["messages"] = session.summary()
        try: persist()
        except Exception as exc: report.update(receipt_write_error=_error(exc), readback_verified=False)
    return report
