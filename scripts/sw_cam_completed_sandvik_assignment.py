"""Assign one existing qualified-draft cutter to the added rough operation once."""
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_existing_sandvik import resolve_existing_context
from scripts.sw_cam_mill_route_context import read_route_operations
from scripts.sw_cam_compound_plan_delta import same_observed_context
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_mill_levels import read_mill_level_values
from scripts.sw_cam_rough_firstcut import read_firstcut_settings, require
from scripts.sw_cam_completed_sandvik_saved import load_saved_sandvik, TARGET_KEYS
from scripts.sw_cam_sandvik_phase1 import FIELDS, field_equal
from scripts.sw_cam_holder_mode_query import HOLDER_FIELDS
from scripts.sw_cam_rough_entry_parameters import read_rough_entry_parameters
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_operation_guard import check_document_target

from scripts.sw_cam_route_batch_qualified_capture import (
    load_route_batch_qualification, qualified_route_capture, canonical_evidence_pins)

SCOPE = "MILL_SANDVIK_ROUGH_ASSIGNMENT_V1"


def assignment_marker(document_path, source_sha256, operation_id, candidate_id, mt_sha256):
    source = Path(document_path).resolve()
    key = _digest(dict(scope=SCOPE, document=str(source).casefold(), source_sha256=source_sha256,
        operation=operation_id, candidate=candidate_id, candidate_mt_sha256=mt_sha256))
    return source.parent / ("sandvik_assignment_" + key + ".json")


def load_assignment_contract(path, sha):
    data, pin = read_pin(path, sha)
    rows = [r for r in data["route"] if r.get("member") == "SetTool" or r.get("step") == 5]
    require(len(rows) == 1 and rows[0]["interface"] == "ICWMillOperation"
        and rows[0]["dispid"] == 8
        and rows[0]["signature"] == "HRESULT SetTool([in] IDispatch *pDispTool);",
        "Exact reviewed SetTool binding required")
    source = data["source"]
    require(source["sha256"] == "359e2d39a970d2362fa1b44750963b9a64e1fa819d2d046e38174affa37eb3c4"
            and _file_hash(source["path"]) == source["sha256"], "Reviewed typed source changed")
    return [pin, dict(path=source["path"], sha256=source["sha256"])]


def verify_assignment_delta(before, after, operation_id, candidate):
    """Only the selected assigned-tool summary and strict dirty flag may change."""
    expected = deepcopy(before)
    old = [r for r in expected["operations"] if r["native_id"] == operation_id]
    new = [r for r in after["operations"] if r["native_id"] == operation_id]
    require(len(old) == len(new) == 1, "Exact unique selected operation required")
    summary = new[0]["assigned_tool"]
    require(type(summary["native_id"]) is int and summary["native_id"] == candidate["native_id"]
            and summary["tool_type_raw"] == 14 and summary["is_mill_tool"] is True
            and summary["cut_diameter_native"] == candidate["parameters"]["CutDiameter"]
            and summary["protrusion_native"] == candidate["parameters"]["Protrusion"],
            "Assigned tool differs from the pinned candidate")
    require(old[0]["assigned_tool"]["native_id"] != candidate["native_id"], "Already assigned; no replay")
    old[0]["assigned_tool"] = deepcopy(summary)
    require(same_observed_context(expected, after, allow_dirty=True),
            "Assignment changed a sibling operation, path, geometry, stock or protected context")
    require(len(after["features"]) == 19 and len(after["operations"]) == 6
            and all(r["toolpath_generated"] is False and r["toolpath_record_counts"] == []
                    for r in after["operations"]), "Nineteen features and six zero-path definitions required")


def capture_assignment_snapshot(app, *, read, typed, reference_state, current_document,
        source_sha256, target_feature_native_id, target_operation_native_id, boundary, diagnostic,
        native_context=None, feature_dispatch_reader=None):
    """Refresh operation state and target settings, reusing pinned model geometry."""
    require(callable(boundary), "Caller identity/evidence/event boundary required")
    boundary()
    native = (resolve_existing_context(app, read, typed, {"before":reference_state})
              if native_context is None else native_context)
    state = deepcopy(reference_state)
    read_route_operations(state, native, read, typed, diagnostic=diagnostic.setdefault("operations", {}))
    state["document"] = deepcopy(current_document)
    state["saved_file_sha256"] = source_sha256
    found = read(native["doc"], "GetCWObjectFromID", 1, target_feature_native_id)
    require(isinstance(found, (tuple, list)) and len(found) == 2 and found[1] is True,
            "Exact target feature lookup failed")
    feature = typed(found[0], "ICWFeature")
    require(_object_id(native["doc"], feature, read) == target_feature_native_id, "Target feature differs")
    selected = [o for o in state["operations"] if o["native_id"] == target_operation_native_id]
    require(len(selected) == 1 and selected[0]["linked_feature_ids"] == [target_feature_native_id]
        and selected[0]["mill_operation_type"] == 0 and selected[0]["suppressed"] is False,
        "Exact unsuppressed rough operation and feature link required")
    raw_op = native["operations"][target_operation_native_id]
    def native_read(label, invoke, decoder=None, interface=False, validator=None):
        boundary()
        value = (feature_dispatch_reader(feature)
            if label == "QueryInterface.IDispatch.feature" and feature_dispatch_reader is not None
            else invoke())
        boundary()
        if interface:require(value is not None and bool(value), "Non-null interface required")
        if validator:validator(value)
        return decoder(value) if decoder else value
    def getter(raw, interface_name, name, *params, **kw):
        return native_read(interface_name + "." + name, lambda:read(raw, name, *params), **kw)
    levels = {}
    read_mill_level_values(feature, raw_op, native_read=native_read, typed=typed, getter=getter, report=levels)
    firstcut = read_firstcut_settings(raw_op, read, typed)
    entry = read_rough_entry_parameters(raw_op, found[0], read=read, typed=typed,
        diagnostic=diagnostic.setdefault("entry_parameter_diagnostic", {}))
    diagnostic.update(capture_complete=True, fresh_full_snapshot=False,
        fresh_fields=["document", "operations", "target_levels", "firstcut", "entry_parameters"],
        reused_fields=["feature_geometry", "stock_geometry", "legacy_tool_profiles"])
    boundary()
    return state, native, levels, firstcut, entry


def read_assignment_candidate(native, app, sw, *, read, typed,
        expected_candidate_tool_native_id, reference, observation_pin, firstcut, diagnostic,
        metric_scope=None):
    """Read current bindings; geometry is the pinned completed-observation reference."""
    crib = typed(read(native["machine"], "IGetToolcrib"), "ICWToolcrib4")
    items = _items(read(crib, "GetAllTools"), typed, read, 128)
    indexed = [(_object_id(native["doc"], raw, read), raw) for raw in items]
    require([oid for oid, raw in indexed] == [row["native_id"] for row in reference["tools"]],
            "Local tool IDs/order changed")
    matches = [raw for oid, raw in indexed if oid == expected_candidate_tool_native_id]
    require(len(matches) == 1, "Exact existing candidate required")
    tool = typed(matches[0], "ICWTool")
    require(read(tool, "IsMillTool") is True, "Exact candidate must be MILL")
    kind = read(tool, "ToolType")
    require(type(kind) is int and kind == 14, "Exact UD14 type required")
    ud = typed(tool, "ICWMillUDTool")
    values = {key:read(tool if key in ("CutDiameter", "Protrusion") else ud, key) for key,_ in FIELDS}
    require(all(field_equal(key, values[key], value) for key,value in FIELDS),
            "Candidate scalar differs from the completed observation")
    mt = read(ud, "GetToolName")
    check_document_target(mt, None, expected_path=reference["tool"]["mt_path_raw"], required=True)
    holder = typed(read(tool, "IGetMillToolHolder"), "ICWMillToolHolder")
    fields = {name:read(holder, name) for name in HOLDER_FIELDS}
    require(all(type(fields[name]) is type(reference["holder_fields"][name])
        and fields[name] == reference["holder_fields"][name] for name in HOLDER_FIELDS),
        "Holder mode/path/scalars changed")
    units = (read_document_cam_unit_scope(read(sw, "ActiveDoc"), app,
        sw_read=lambda obj,name:read(obj,name), cam_read=read)
        if metric_scope is None else deepcopy(metric_scope))
    result = deepcopy(reference)
    result["tool"]["parameters"] = values
    result["tool"]["mt_path_raw"] = mt
    result.update(holder_fields=fields, firstcut=deepcopy(firstcut), metric_scope=units)
    diagnostic.update(reference_pin=deepcopy(observation_pin), fresh_profiles=False,
        fresh_fields=["tool_ID", "tool_scalars", "MT_path", "holder_fields", "firstcut", "metric_scope", "crib_IDs"],
        reused_fields=["tool_profile", "shank_profile", "holder_profile", "unassigned_crib_scalar_metadata"],
        readback_complete=True)
    return result


def assign_sandvik_to_rough(sw, clsid, typelib_path, *, saved_draft_receipt_path,
        saved_draft_receipt_sha256, expected_candidate_tool_native_id,
        assignment_contract_path, assignment_contract_sha256, read_mode="strong",
        read_batch_qualification_receipt_path=None, read_batch_qualification_receipt_sha256=None, **args):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(schema_version=1, scope=SCOPE, status="error", phase="preflight",
        process_id=args.get("process_id"), expected_document_path=args.get("expected_document_path"),
        saved_file_sha256=args.get("expected_source_sha256"), candidate_id=expected_candidate_tool_native_id,
        mutation_attempted=False, setter_attempted=False, setter_returned=False, setter_call_count=0,
        native_dispatch_pending=False, readback_verified=False, firstcut_preserved=False,
        protected_operations_verified=False, model_saved=False, save_attempted=False,
        GTP_attempted=False, GOP_attempted=False, AFR_attempted=False, tool_edit_attempted=False,
        creator_attempted=False, simulation_attempted=False, TechDB_write_attempted=False,
        automatic_replay=False, automatic_rollback=False, post_cleanup_CAM_getters=False,
        units_verified=False, cutting_partition_verified=False, production_qualified=False,
        entry_strategy_qualified=False, may_continue=False, snapshot_diagnostics=[],
        protection_scope="Fresh six operation identities/links/types/suppression/tools/path counts, target levels/setup/firstcut/entry. Feature/stock geometry and legacy tool profiles reuse pinned completed observation; not freshly rechecked.",
        full_context_rechecked=False, full_geometry_rechecked=False)
    report.update({key: args.get(key) for key in TARGET_KEYS})
    started = monotonic(); created = claimed = False; session = loaded = anchor = None
    marker = None; pins = []; before_native = None; batch_qualification = None
    source = args.get("expected_document_path"); receipt = args.get("receipt_path")
    op_id = args.get("target_operation_native_id"); feature_id = args.get("target_feature_native_id")
    def marker_state():
        return dict(scope=SCOPE, status=report["status"], phase=report["phase"],
            document=source, source_sha256=args["expected_source_sha256"],
            saved_draft_pin=dict(path=saved_draft_receipt_path, sha256=saved_draft_receipt_sha256),
            operation_id=op_id, candidate_id=expected_candidate_tool_native_id, receipt_path=receipt,
            setter_call_count=report["setter_call_count"], setter_returned=report["setter_returned"],
            native_dispatch_pending=report["native_dispatch_pending"],
            readback_verified=report["readback_verified"], automatic_replay=False)
    def persist():
        report["elapsed_seconds"] = monotonic() - started
        if created:
            if claimed: _write_receipt(marker, marker_state())
            _write_receipt(receipt, report)
    def check_files():
        anchor.check_files()
        for pin in pins:
            require(_file_hash(pin["path"]) == pin["sha256"], "Pinned assignment evidence changed")
    def identity():
        pid = _member(sw, "GetProcessID")
        require(type(pid) is int and pid == args["process_id"],
                "Exact owned process changed")
        anchor.check_runtime_identity()
        doc = raw_part_identity(sw)
        check_document_target(doc["path"], doc["title"], expected_path=source, required=True)
        require(_file_hash(source) == args["expected_source_sha256"], "Current saved source changed")
        return doc
    def events(active=True):
        value = session.summary(); report["messages"] = value
        require(value.get("subscribed") is True and value.get("active") is active
            and (active or value.get("disconnected") is True)
            and not any(value.get(k) for k in ("event_count", "overflow", "callback_errors",
                "callback_error_count", "subscription_error", "disconnect_errors")),
            "CAM event or transport requires stop")
    def guard():
        return ScopedCamDispatchGuard(sw, typelib_path, process_id=args["process_id"],
            expected_document=identity(), source_sha256=args["expected_source_sha256"],
            evidence_pins=canonical_evidence_pins(anchor.pins, pins), verify_evidence=check_files,
            verify_owned_process=anchor.check_runtime_identity, check_events=events)
    def capture(label):
        nonlocal before_native
        check_files(); events()
        diag = dict(phase=label); report["snapshot_diagnostics"].append(diag)
        if batch_qualification is not None:
            state, native, levels, firstcut, entry, payload = qualified_route_capture(app, sw, typelib_path,
                qualification=batch_qualification, process_id=args["process_id"], current_document=identity(),
                source_sha256=args["expected_source_sha256"], evidence_pins=canonical_evidence_pins(anchor.pins, pins),
                verify_evidence=check_files, verify_owned_process=anchor.check_runtime_identity,
                check_events=events, strong_guard_factory=guard, reference_state=loaded["state"],
                target_feature_native_id=feature_id, target_operation_native_id=op_id,
                expected_candidate_tool_native_id=expected_candidate_tool_native_id,
                reference_candidate=loaded["payload"], observation_pin=loaded["observation_pin"], diagnostic=diag)
        else:
            with guard() as g:
                state, native, levels, firstcut, entry = capture_assignment_snapshot(app,
                    read=g.read, typed=g.typed, reference_state=loaded["state"],
                    current_document=identity(), source_sha256=args["expected_source_sha256"],
                    target_feature_native_id=feature_id, target_operation_native_id=op_id,
                    boundary=lambda:(check_files(), events(), identity()), diagnostic=diag)
        observation = dict(levels_observation=levels, firstcut_settings=firstcut, entry_parameters=entry)
        require(observation["firstcut_settings"] == loaded["phase1"]["after_firstcut"],
                "First-cut direct/aggregate settings changed")
        require(observation["levels_observation"] == loaded["firstcut"]["after_levels"],
                "Machining depth, override, seven parameters or setup changed")
        if batch_qualification is None:
            with guard() as g:
                payload = read_assignment_candidate(native, app, sw, read=g.read, typed=g.typed,
                    expected_candidate_tool_native_id=expected_candidate_tool_native_id,
                    reference=loaded["payload"], observation_pin=loaded["observation_pin"],
                    firstcut=observation["firstcut_settings"], diagnostic=diag.setdefault("candidate", {}))
        require(payload == loaded["payload"], "Candidate, holder, crib or units changed")
        report[label] = state; report[label + "_candidate"] = payload
        report[label + "_levels"] = deepcopy(observation["levels_observation"])
        report[label + "_entry_parameters"] = deepcopy(observation["entry_parameters"])
        if label == "after":
            require(report["before_entry_parameters"] == report["after_entry_parameters"],
                    "Entry, depth pass or boundary parameters changed during assignment")
        if label == "before":
            require(same_observed_context(loaded["state"], state), "Current state differs from saved R84")
            before_native = native
        else:
            verify_assignment_delta(report["before"], state, op_id, payload["tool"])
        check_files(); events(); require(identity() == state["document"], "Capture identity changed")
        persist()
    try:
        loaded = load_saved_sandvik(saved_draft_receipt_path=saved_draft_receipt_path,
            saved_draft_receipt_sha256=saved_draft_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id, **args)
        anchor = loaded["anchor"]
        pins = loaded["pins"] + load_assignment_contract(assignment_contract_path, assignment_contract_sha256)
        require(read_mode in ("strong", "qualified_batch"), "Explicit supported snapshot read mode required")
        if read_mode == "qualified_batch":
            require(type(read_batch_qualification_receipt_path) is str
                and type(read_batch_qualification_receipt_sha256) is str, "Explicit qualification pin required")
            batch_qualification = load_route_batch_qualification(read_batch_qualification_receipt_path,
                read_batch_qualification_receipt_sha256, saved=loaded, process_id=args["process_id"],
                expected_document_path=source, expected_source_sha256=args["expected_source_sha256"],
                target_feature_native_id=feature_id, target_operation_native_id=op_id,
                target_operation_setup_native_id=args["target_operation_setup_native_id"],
                expected_candidate_tool_native_id=expected_candidate_tool_native_id, caller_path=__file__)
            pins += batch_qualification["pins"]
        else:
            require(read_batch_qualification_receipt_path is None and read_batch_qualification_receipt_sha256 is None,
                "Qualification pin is only accepted with qualified_batch read mode")
        report.update(read_mode=read_mode, batch_qualification=deepcopy(batch_qualification),
            full_route_snapshot_qualified=False)
        marker = assignment_marker(source, args["expected_source_sha256"], op_id,
            expected_candidate_tool_native_id, loaded["phase1"]["candidate_asset"]["sha256"])
        require(not marker.exists() and not marker.is_symlink(), "Prior assignment attempt exists; no replay")
        protected = {str(Path(p["path"]).resolve()).casefold() for p in pins}
        paths = [str(Path(p).resolve()).casefold() for p in (source, receipt, marker)]
        require(len(set(paths)) == 3 and not protected.intersection(paths),
                "Source, output, marker and evidence must be distinct")
        report.update(saved_draft_pin=loaded["pin"], observation_pin=loaded["observation_pin"],
            assignment_marker_path=str(marker),
            candidate_mt_pin=loaded["phase1"]["candidate_asset"])
        _write_receipt(receipt, report, create=True); created = True
        require(identity() == loaded["state"]["document"], "Exact clean saved R84 document required")
        app = _bootstrap(sw, clsid, typelib_path, source)
        require(identity() == loaded["state"]["document"], "Document changed acquiring CAM host")
        session = CamMessageSession(app, typelib_path)
        with session:
            events(); report["phase"] = "before_capture"; capture("before")
            with guard() as g:
                raw_op = before_native["operations"][op_id]
                require(_object_id(before_native["doc"], raw_op, g.read) == op_id, "Operation pointer changed")
                old = next(r for r in report["before"]["operations"] if r["native_id"] == op_id)
                summary, _ = read_generic_tool(raw_op, before_native["doc"], g.read, g.typed)
                require(summary == old["assigned_tool"], "Previous assignment changed")
                require(read_firstcut_settings(raw_op, g.read, g.typed) == loaded["phase1"]["after_firstcut"],
                        "First-cut changed before assignment")
                op = g.typed(raw_op, "ICWMillOperation")
                crib = g.typed(g.read(before_native["machine"], "IGetToolcrib"), "ICWToolcrib4")
                matches = [raw for raw in _items(g.read(crib, "GetAllTools"), g.typed, g.read, 128)
                    if _object_id(before_native["doc"], raw, g.read) == expected_candidate_tool_native_id]
                require(len(matches) == 1, "Candidate disappeared before assignment")
                # ICWDispatchCollection.Item already returns IDispatch*, per the pinned SDK.
                candidate = matches[0]
                def pending():
                    nonlocal claimed
                    report.update(phase="SetTool", setter_attempted=True, setter_call_count=1,
                                  mutation_attempted=True, native_dispatch_pending=True)
                    _write_receipt(marker, marker_state(), create=True); claimed = True; persist()
                result = g.dispatch_once(lambda:_member(op, "SetTool", candidate), persist_pending=pending)
                report.update(setter_returned=True, native_dispatch_pending=False,
                    setter_return_type=type(result).__name__,
                    setter_return_value=result if result is None or type(result) in (bool,int,float,str) else None)
                persist()
            report["dispatch_guard"] = g.summary()
            require(type(result) is int and result == 0, "Strict successful SetTool HRESULT required")
            report["phase"] = "after_capture"; capture("after")
        events(active=False)
        report["after_cleanup_document"] = identity(); check_files()
        require(report["after_cleanup_document"] == report["after"]["document"], "Cleanup changed document")
        report.update(status="review_required", phase="finished", readback_verified=True,
            firstcut_preserved=True, protected_operations_verified=True,
            continuation_state=deepcopy(report["after"]), state_sha256=_digest(report["after"]),
            continuation_state_provenance=dict(reference_pin=loaded["observation_pin"],
                fresh_fields=["document", "operations", "target_levels", "firstcut", "entry_parameters"],
                reused_fields=["feature_geometry", "stock_geometry", "legacy_tool_profiles"]),
            candidate_profile_provenance=dict(reference_pin=loaded["observation_pin"],
                fresh_profiles=False, fresh_scalars_MT_holder_fields=True, fresh_crib_IDs=True),
            entry_parameters_read=True, entry_parameters_preserved=True,
            reason="ONE_EXISTING_TOOL_ASSIGNED_TO_ADDED_ROUGH_ONLY_NO_SAVE_OR_GTP")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"], phase="finished", issue=_error(exc),
            readback_verified=False, firstcut_preserved=False, protected_operations_verified=False)
    finally:
        if session is not None: report["messages"] = session.summary()
        try: persist()
        except Exception as exc:
            report.update(status="uncertain", receipt_write_error=_error(exc), readback_verified=False)
    return report
