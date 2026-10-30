"""Observe one ungenerated finish definition on an already saved route.

Reuses pinned geometry and the existing operations reader. New finish getters
run under the unchanged strong guard; no setter, generation, save or export.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_existing_sandvik import resolve_existing_context
from scripts.sw_cam_route_entry_evidence import load_continuation_checkpoint
from scripts.sw_cam_route_checkpoint import RouteCheckpointContext
from scripts.sw_cam_route_read_batch import ScopedCamRouteReadBatch
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_mill_route_context import read_route_operations, read_generic_tool
from scripts.sw_cam_completed_sandvik_save import read_feature_counts
from scripts.sw_cam_mill_levels import read_mill_level_values
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_rough_entry_parameters import bounded_raw_observation
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_route_entry_continuation import _events
from scripts.sw_cam_mill_inventory import validate_inventory_request

SCOPE = "SAVED_ROUTE_FINISH_OBSERVATION_V1"
FINISH_BASE_FIELDS = (
    "SideAllow", "SideCutAmt", "FinalSideCutAmt", "SpringPass",
    "DepthMethod", "Ramp", "DepthAllow", "FirstDepthCut", "MaxDepthCut",
    "FinalDepthCut", "DepthAngle", "CleanUpPassOpt", "CutMethod",
    "BottomFinOpt", "PerimeterPassType", "BottomFinMethod", "OverridePrevAllow",
)
FINISH_V3_FIELDS = (
    "GetZAllowance", "GetContainType", "GetContainAllowance",
    "GetTypeOfFirstCutZ", "GetIsChamferMachining", "GetChamferLength",
)
MILL_TOOL_FIELDS = (
    "MillToolType", "MillToolSubType", "EffCutlength", "ShankDia",
    "OverallLen", "EndRadius", "NoOfFlutes", "ShoulderLength",
    "MillToolShankType", "ShoulderDia", "ShankLength",
)
HOLDER_FIELDS = (
    "GetHolderShape", "GetHolderId", "GetHolderNumber", "GetName",
    "GetHolderTopDia", "GetHolderBottomDia", "GetHolderOverallLength",
    "GetHolderBottomLength", "GetProtrusion",
)
MAX_OBSERVATIONS = 100

def finish_row(state, args):
    require(type(args["finish_operation_native_id"]) is int
        and type(args["finish_tool_native_id"]) is int, "Strict finish IDs required")
    require(len(state["features"]) == 19 and len(state["feature_setups"]) == 3
        and len(state["operations"]) == 6 and state["operation_count"] == 6,
        "Exact saved 19/3/6 context required")
    rows = [r for r in state["operations"] if r["native_id"] == args["finish_operation_native_id"]]
    require(len(rows) == 1, "Unique finish operation required")
    row = rows[0]
    require(row["native_id"] != args["target_operation_native_id"]
        and row["linked_feature_ids"] == [args["target_feature_native_id"]]
        and row["setup_native_id"] == args["target_operation_setup_native_id"]
        and type(row["mill_operation_type"]) is int and row["mill_operation_type"] == 1
        and row["suppressed"] is False and row["toolpath_generated"] is False
        and row["toolpath_record_counts"] == [], "Exact ungenerated finish definition required")
    tool = row["assigned_tool"]
    require(type(tool["native_id"]) is int and tool["native_id"] == args["finish_tool_native_id"]
        and tool["is_mill_tool"] is True and tool["native_read_complete"] is True
        and type(tool["tool_type_raw"]) is int and tool["tool_type_raw"] == 1,
        "Exact standard endmill assignment required")
    return row

def read_finish_details(raw_operation, feature_dispatch, tool, *, read, typed, diagnostic):
    """Fixed callback-only getter list. Values retain raw Python shape."""
    result = dict(finish={}, tool={}, holder={}, full_tool_profile_read=False,
        full_holder_profile_read=False, field_units_verified=False,
        enum_binding_verified=False, physical_tool_identity_verified=False,
        holder_clearance_verified=False)
    diagnostic["partial_values"] = result
    finish = typed(raw_operation, "ICWFinishMillOp")
    for name in FINISH_BASE_FIELDS:
        result["finish"][name] = bounded_raw_observation(read(finish, name))
    finish2 = typed(raw_operation, "ICWFinishMillOp2")
    result["finish"]["GetPreviousAllowance"] = bounded_raw_observation(
        read(finish2, "GetPreviousAllowance", feature_dispatch))
    finish3 = typed(raw_operation, "ICWFinishMillOp3")
    for name in FINISH_V3_FIELDS:
        result["finish"][name] = bounded_raw_observation(read(finish3, name))
    mill = typed(tool, "ICWMillTool")
    for name in MILL_TOOL_FIELDS:
        result["tool"][name] = bounded_raw_observation(read(mill, name))
    holder = typed(read(tool, "IGetMillToolHolder"), "ICWMillToolHolder")
    for name in HOLDER_FIELDS:
        result["holder"][name] = bounded_raw_observation(read(holder, name))
    diagnostic["details_complete"] = True
    return deepcopy(result)

def _capture_operations(ctx, native, reference, diagnostic):
    """Only fresh operation summaries/counts; all 19 feature geometries are reused."""
    state = deepcopy(reference)
    if ctx.loaded["read_mode"] == "qualified_batch":
        require(ctx.loaded.get("qualification") is not None, "Existing batch qualification required")
        batch = ScopedCamRouteReadBatch(ctx.sw, ctx.typelib_path, native_context=native,
            reference_state=reference, process_id=ctx.args["process_id"],
            expected_document=ctx.identity(), source_sha256=ctx.args["expected_source_sha256"],
            evidence_pins=ctx.loaded["pins"], verify_evidence=ctx.files,
            verify_owned_process=ctx.owned, check_events=ctx.events, max_native_calls=600)
        try:
            with batch:
                read_route_operations(state, native, batch.read, batch.typed, diagnostic=diagnostic)
            batch.require_complete()
        finally:
            diagnostic["operations_batch"] = deepcopy(batch.summary())
    else:
        with ctx.guard() as guard:
            read_route_operations(state, native, guard.read, guard.typed, diagnostic=diagnostic)
        diagnostic["strong_guard"] = guard.summary()
    with ctx.guard() as guard:
        counts = read_feature_counts(native, guard.read, guard.typed)
    require(counts == [dict(native_id=r["native_id"], feature_count=r["feature_count"])
        for r in reference["feature_setups"]], "Feature/setup counts changed")
    require(state == reference and ctx.identity() == reference["document"],
        "Protected saved route changed")
    diagnostic.update(capture_complete=True, fresh_feature_counts=counts,
        full_geometry_rechecked=False, geometry_reference_pin=ctx.loaded["pin"])
    return state

def inspect_saved_route_finish(sw, clsid, typelib_path, *, checkpoint_receipt_path,
        checkpoint_receipt_sha256, **args):
    from scripts.sw_cam_events import CamMessageSession
    validate_inventory_request(**{k:args[k] for k in (
        "process_id", "expected_document_path", "expected_source_sha256", "qualification_only",
        "acknowledge_disposable_copy", "receipt_path", "message_policy")})
    require(args.get("software_only_experiment") is True, "Explicit software-only observation required")
    loaded = load_continuation_checkpoint(checkpoint_receipt_path, checkpoint_receipt_sha256,
        action="save", check_current_source=True, **args)
    require(loaded.get("historical_only") is False and loaded["state"]["document"]["needs_save"] is False,
        "Finished current clean Save checkpoint required")
    selected = finish_row(loaded["state"], args)
    module_pin = dict(path=str(Path(__file__).resolve()), sha256=_file_hash(__file__))
    registry_path = Path(__file__).resolve().with_name("sw_cam_comtypes.py")
    registry_pin = dict(path=str(registry_path), sha256=_file_hash(registry_path))
    loaded["pins"] = canonical_evidence_pins(loaded["pins"], [module_pin, registry_pin])
    receipt = Path(args["receipt_path"])
    require(receipt.is_absolute() and receipt.parent.is_dir() and receipt.suffix.lower() == ".json"
        and not receipt.exists() and not receipt.is_symlink(), "Fresh absolute receipt required")
    protected = {str(Path(p["path"]).resolve()).casefold() for p in loaded["pins"]}
    protected.add(str(Path(args["expected_document_path"]).resolve()).casefold())
    require(str(receipt.resolve()).casefold() not in protected, "Receipt aliases protected evidence")
    report = dict(schema_version=1, scope=SCOPE, status="error", phase="preflight",
        read_only=True, process_id=args["process_id"], expected_document_path=args["expected_document_path"],
        expected_source_sha256=args["expected_source_sha256"], checkpoint_pin=loaded["pin"],
        finish_operation_native_id=args["finish_operation_native_id"],
        finish_tool_native_id=args["finish_tool_native_id"], target_feature_native_id=args["target_feature_native_id"],
        evidence_pins=deepcopy(loaded["pins"]), implementation_pin=module_pin, interface_registry_pin=registry_pin,
        mutation_attempted=False, GTP_attempted=False, GOP_attempted=False, AFR_attempted=False,
        save_attempted=False, model_saved=False, export_attempted=False, simulation_attempted=False,
        setter_attempted=False, native_dispatch_pending=False, automatic_retry=False,
        readback_verified=False, full_geometry_rechecked=False, production_qualified=False,
        physical_units_verified=False, may_continue=False, native_reads=[], snapshot_diagnostics=[])
    started = monotonic(); created = False; ctx = session = None
    def persist():
        report["elapsed_seconds"] = monotonic() - started
        if created: _write_receipt(receipt, report)
    def events(): _events(session, report)
    def units(guard):
        return read_document_cam_unit_scope(guard.read(sw, "ActiveDoc"), ctx.app,
            sw_read=lambda obj, name:guard.read(obj, name), cam_read=guard.read)
    try:
        _write_receipt(receipt, report, create=True); created = True
        ctx = RouteCheckpointContext(loaded, dict(args), sw, typelib_path, None, events)
        ctx.files(); ctx.identity()
        ctx.app = _bootstrap(sw, clsid, typelib_path, args["expected_document_path"])
        ctx.identity(); session = CamMessageSession(ctx.app, typelib_path)
        with session:
            with ctx.guard() as guard:
                native = resolve_existing_context(ctx.app, guard.read, guard.typed, {"before":loaded["state"]})
                report["units_before"] = units(guard)
            report["phase"] = "before_operations"; persist()
            diag = dict(phase="before"); report["snapshot_diagnostics"].append(diag)
            before = _capture_operations(ctx, native, loaded["state"], diag)
            report["before_context"] = before; finish_row(before, args); persist()
            report["phase"] = "finish_fields"; persist()
            with ctx.guard() as guard:
                def note(kind, name, invoke, interface=False):
                    require(len(report["native_reads"]) < MAX_OBSERVATIONS, "Finish observation count exceeded")
                    row = dict(kind=kind, name=name, stage="attempted")
                    report["native_reads"].append(row); persist()
                    value = invoke()
                    if interface:
                        require(value is not None and bool(value), "Non-null interface required")
                        row.update(stage="returned", interface_present=True)
                    else:
                        row.update(stage="returned", observation=bounded_raw_observation(value))
                    persist(); return value
                def read(obj, name, *params):
                    # IGetMillToolHolder returns an interface, never serialize it.
                    return note("getter", name, lambda:guard.read(obj, name, *params),
                        interface=name == "IGetMillToolHolder")
                def typed(obj, name):
                    return note("query_interface", name, lambda:guard.typed(obj, name), interface=True)
                raw = native["operations"][args["finish_operation_native_id"]]
                require(_object_id(native["doc"], raw, guard.read) == args["finish_operation_native_id"],
                    "Finish identity changed")
                generic, tool = read_generic_tool(raw, native["doc"], guard.read, guard.typed)
                require(generic == selected["assigned_tool"], "Finish tool changed")
                report["tool_summary"] = generic
                found = guard.read(native["doc"], "GetCWObjectFromID", 1, args["target_feature_native_id"])
                require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True,
                    "Feature lookup failed")
                feature = guard.typed(found[0], "ICWFeature")
                require(_object_id(native["doc"], feature, guard.read) == args["target_feature_native_id"],
                    "Selected feature changed")
                levels = {}
                def native_read(label, invoke, decoder=None, interface=False, validator=None):
                    value = (note("query_interface", "IDispatch.feature", lambda:guard._observe(invoke), interface=True)
                        if label == "QueryInterface.IDispatch.feature" else invoke())
                    if interface: require(value is not None and bool(value), "Non-null level interface required")
                    if validator: validator(value)
                    return decoder(value) if decoder else value
                def getter(obj, interface_name, name, *params, **kw):
                    # Existing level decoder owns interface tuples; durable label remains recorded.
                    row = dict(kind="level_getter", name=interface_name+"."+name, stage="attempted")
                    require(len(report["native_reads"]) < MAX_OBSERVATIONS, "Finish observation count exceeded")
                    report["native_reads"].append(row); persist()
                    raw_value = guard.read(obj, name, *params)
                    row["stage"] = "returned"; row["interface_result"] = bool(kw.get("interface") or kw.get("validator"))
                    if not row["interface_result"]: row["observation"] = bounded_raw_observation(raw_value)
                    persist(); return native_read(row["name"], lambda:raw_value, **kw)
                read_mill_level_values(feature, raw, native_read=native_read, typed=typed, getter=getter, report=levels)
                report["levels"] = levels; persist()
                report["details"] = read_finish_details(raw, found[0], tool,
                    read=read, typed=typed, diagnostic=report.setdefault("details_diagnostic", {}))
            report["finish_strong_guard"] = guard.summary()
            report["phase"] = "after_operations"; persist()
            diag = dict(phase="after"); report["snapshot_diagnostics"].append(diag)
            after = _capture_operations(ctx, native, loaded["state"], diag)
            report["after_context"] = after
            require(after == before and finish_row(after, args) == selected, "Finish read changed route")
            with ctx.guard() as guard: report["units_after"] = units(guard)
            require(report["units_before"] == report["units_after"], "Global units changed")
        _events(session, report, False); ctx.files()
        report["after_cleanup_document"] = ctx.identity()
        report.update(status="observed", phase="finished", readback_verified=True,
            detail_observation_complete=True, atomic_snapshot_claimed=False,
            fresh_observation_scope="operation summaries/counts, finish settings, levels, tool/holder scalars, unit record",
            reused_scope="all 19 feature geometries, stock geometry and existing completed checkpoint lineage")
    except Exception as exc:
        report.update(status="error", failed_phase=report["phase"], phase="finished",
            issue=_error(exc), readback_verified=False)
    finally:
        if session is not None: report["messages"] = session.summary()
        try: persist()
        except Exception as exc: report.update(receipt_write_error=_error(exc), readback_verified=False)
    return report



