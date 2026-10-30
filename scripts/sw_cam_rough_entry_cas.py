"""One guarded compare-and-set of selected rough entry mode; no path generation."""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import re
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_completed_gtp_wip import load_completed_route_save, same_path, wip_marker, SCOPE as WIP_SCOPE
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_route_checkpoint import RouteCheckpointContext, capture_route_checkpoint, snapshot_payload, checkpoint_from_snapshot
from scripts.sw_cam_rough_firstcut import require

SCOPE = "MILL_ROUGH_ENTRY_CAS_V1"
CHECKPOINT_SCOPE = "MILL_VERIFIED_ROUTE_CHECKPOINT_V1"
TARGET_KEYS = ("target_feature_native_id", "target_operation_native_id", "target_operation_setup_native_id")

def load_entry_contract(path, sha, expected_old, new_value):
    data, pin = read_pin(path, sha)
    require(data.get("scope") == "OFFLINE_ROUGH_ENTRY_RECIPE_REVIEW_V1"
        and data.get("status") == "PROPOSAL_REQUIRES_ONE_NATIVE_QUALIFICATION_AND_CL_READBACK", "Reviewed experimental recipe required")
    contract = data["native_interface_contract"]
    methods = {r["name"]:r for r in contract["methods"]}
    require(contract["interface"] == "ICWRghMillOp" and methods["GetEntryExitType"]["dispid"] == 58
        and methods["SetEntryExitType"]["dispid"] == 88
        and methods["SetEntryExitType"]["in"] == ["IDispatch feature", "LONG type"]
        and methods["SetEntryExitType"]["return"] == "HRESULT only; no retval", "Exact installed setter ABI required")
    source = dict(path=contract["tlb_path"], sha256=contract["tlb_sha256"])
    require(_file_hash(source["path"]) == source["sha256"], "Reviewed generated TLB source changed")
    text = Path(source["path"]).read_text(encoding="utf-8-sig")
    values = dict(PLUNGE=0, ENTRYDRILL=1, RAMP=2, ENTRY_HOLE=3, HELICAL=4, RAMP_ON_LEADIN=5)
    require(data["primary_documentation"]["enum_constants"] == values
        and data["primary_documentation"]["named_enum_binding_in_method_signature"] is False, "Raw enum evidence changed")
    for name, value in values.items():
        require(re.search(r"(?m)^CW_ENTRY_EXIT_" + name + r"\s*=\s*" + str(value) + r"\s*$", text) is not None,
            "Installed enum constant differs")
    require(type(expected_old) is int and type(new_value) is int and expected_old in values.values()
        and new_value in values.values() and expected_old != new_value, "Distinct explicit documented raw enum values required")
    return dict(pin=pin, source_pin=source, enum_constants=values,
        method_enum_binding_verified=False, resulting_entry_geometry_verified=False,
        exact_scope=contract["exact_scope"])

def load_wip_witness(path, sha, loaded):
    data, pin = read_pin(path, sha)
    require(data.get("scope") == WIP_SCOPE and data.get("status") == "review_required" and data.get("phase") == "finished",
        "Completed exact WIP observation required")
    for key in ("mutation_attempted", "native_call_attempted", "native_call_returned", "readback_verified", "export_files_verified"):
        require(data.get(key) is True, "Incomplete WIP flag: " + key)
    for key in ("native_dispatch_pending", "GTP_attempted", "simulation_attempted", "model_saved", "NC_export_attempted",
                "automatic_retry", "automatic_replay", "post_cleanup_CAM_getters", "production_qualified", "may_continue"):
        require(data.get(key) is False, "Unexpected WIP flag: " + key)
    require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error"))
        and type(data.get("native_call_count")) is int and data["native_call_count"] == 1
        and data.get("native_return_type") == "bool" and data.get("native_return_value") is True, "Completed single WIP export required")
    clean_events(data)
    require(data["saved_gtp_pin"] == loaded["pin"] and data["before"] == data["after"] == loaded["state"]
        and data["source_sha256"] == loaded["state"]["saved_file_sha256"], "WIP saved route differs")
    for file in data["files"]:
        require(type(file["bytes"]) is int and file["bytes"] > 0 and Path(file["path"]).stat().st_size == file["bytes"]
            and _file_hash(file["path"]) == file["sha256"], "WIP file evidence changed")
    require(data["files"], "Actual WIP output witness required")
    marker = wip_marker(data["expected_document_path"], data["source_sha256"], data["target_operation_native_id"], data["candidate_id"])
    same_path(data["marker_path"], marker)
    marker_data, marker_pin = read_pin(str(marker), _file_hash(marker))
    require(marker_data["scope"] == WIP_SCOPE and marker_data["status"] == "review_required"
        and marker_data["phase"] == "finished" and marker_data["native_call_returned"] is True
        and marker_data["native_dispatch_pending"] is False and marker_data["readback_verified"] is True
        and marker_data["saved_gtp_pin"] == loaded["pin"], "Completed WIP marker required")
    same_path(marker_data["receipt_path"], path)
    return data, pin, [pin, marker_pin] + data["files"]

def entry_marker(document, source_sha, operation_id, feature_id, expected_old, new_value):
    source = Path(document).resolve()
    key = _digest(dict(scope=SCOPE, document=str(source).casefold(), source_sha256=source_sha,
        operation_id=operation_id, feature_id=feature_id, expected_old=expected_old, new_value=new_value))
    return source.parent / ("rough_entry_cas_" + key + ".json")

def verify_entry_delta(before, after, *, operation_id, expected_old, new_value):
    require(before["candidate"] == after["candidate"] and before["levels"] == after["levels"], "Entry edit changed cutter or levels")
    prior = before["entry"]; current = after["entry"]
    require(type(prior["entry"]["GetEntryExitType"]["raw"]) is int
        and prior["entry"]["GetEntryExitType"]["raw"] == expected_old, "Entry precondition differs")
    expected_entry = deepcopy(prior); expected_entry["entry"]["GetEntryExitType"]["raw"] = new_value
    require(type(current["entry"]["GetEntryExitType"]["raw"]) is int and current == expected_entry,
        "Setter changed another entry/depth/boundary/NC parameter or missed the requested value")
    old_state = before["context"]; state = after["context"]; expected_state = deepcopy(old_state)
    require(type(state["document"].get("needs_save")) is bool, "Strict dirty state required")
    expected_state["document"]["needs_save"] = state["document"]["needs_save"]
    old = [r for r in expected_state["operations"] if r["native_id"] == operation_id]
    new = [r for r in state["operations"] if r["native_id"] == operation_id]
    require(len(old) == len(new) == 1, "One exact target operation required")
    flag, counts = new[0]["toolpath_generated"], new[0]["toolpath_record_counts"]
    require(type(flag) is bool and type(counts) is list and len(counts) <= 32
        and all(type(n) is int and n >= 0 for n in counts), "Strict bounded raw target path flag/counts required")
    old[0]["toolpath_generated"] = flag; old[0]["toolpath_record_counts"] = deepcopy(counts)
    require(expected_state == state, "Entry edit changed a sibling, tool binding, feature, stock, source or protected route")
    return dict(toolpath_generated=flag, toolpath_record_counts=deepcopy(counts),
        path_invalidation_observed=not flag, cached_records_present=bool(counts), regeneration_required=True,
        path_valid_for_changed_entry_verified=False,
        existing_record_counts_are_not_regeneration_evidence=True)

def checkpoint_record(loaded, after):
    result = checkpoint_from_snapshot(loaded, after)
    result.update(checkpoint_scope=CHECKPOINT_SCOPE, base_saved_pin=deepcopy(loaded["base_saved_pin"]),
        physical_units_verified=False, actual_entry_geometry_verified=False, production_qualified=False)
    return result

def load_completed_entry_checkpoint(path, sha256, *, check_current_source=True, **args):
    """Validate immutable CAS continuation; historical mode never authorizes native dispatch."""
    require(type(check_current_source) is bool, "Explicit historical/current validation mode required")
    data, pin = read_pin(path, sha256)
    require(data.get("scope") == SCOPE and data.get("phase") == "finished" and data.get("status") == "review_required",
        "Completed exact entry CAS required")
    for key in ("mutation_attempted", "setter_attempted", "setter_returned", "readback_verified", "protected_operations_verified"):
        require(data.get(key) is True, "Incomplete entry CAS: " + key)
    for key in ("native_dispatch_pending", "GTP_attempted", "model_saved", "save_attempted", "simulation_attempted",
                "automatic_replay", "automatic_retry", "production_qualified", "entry_geometry_verified", "may_continue"):
        require(data.get(key) is False, "Unexpected entry CAS flag: " + key)
    require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error"))
        and data.get("native_return_type") == "int" and type(data.get("native_return_value")) is int
        and data["native_return_value"] == 0 and type(data.get("setter_call_count")) is int and data["setter_call_count"] == 1,
        "One strict-zero entry CAS required")
    clean_events(data)
    guard = data.get("dispatch_guard", {})
    require(guard.get("claimed") is True and guard.get("native_call_attempted") is True
        and guard.get("native_call_returned") is True and guard.get("invalid") is False,
        "Completed unchanged strong setter guard required")
    require(len(data.get("capture_diagnostics", [])) == 2
        and all(r.get("capture_complete") is True for r in data["capture_diagnostics"]), "Two completed route snapshots required")
    base, base_pin = read_pin(data["saved_gtp_pin"]["path"], data["saved_gtp_pin"]["sha256"])
    require(base_pin == data["saved_gtp_pin"] and base.get("model_saved") is True and base.get("readback_verified") is True
        and base.get("phase") == "finished" and base["after_context"] == data["before"]["context"]
        and base["saved_file_sha256"] == data["source_sha256"]
        and all(base["after"][k] == data["before"][k] for k in ("candidate", "levels", "entry")),
        "Original saved route ancestry differs")
    require(type(data.get("process_id")) is int and data["process_id"] == args["process_id"]
        and type(data.get("candidate_id")) is int and data["candidate_id"] == args["expected_candidate_tool_native_id"]
        and all(type(data.get(k)) is int and data[k] == args[k] for k in TARGET_KEYS), "Checkpoint process/target differs")
    same_path(data["expected_document_path"], args["expected_document_path"])
    observed = verify_entry_delta(data["before"], data["after"], operation_id=args["target_operation_native_id"],
        expected_old=data["expected_old"], new_value=data["new_value"])
    require(observed == data["target_path_after"], "Recorded target path state differs")
    checkpoint = data["checkpoint"]
    require(checkpoint["checkpoint_scope"] == CHECKPOINT_SCOPE and checkpoint["state"] == data["after"]["context"]
        and checkpoint["payload"] == {k:data["after"][k] for k in ("candidate", "levels", "entry")}
        and checkpoint["source_sha256"] == data["source_sha256"] == checkpoint["state"]["saved_file_sha256"]
        and data["state_sha256"] == _digest(checkpoint["state"])
        and data["after_cleanup_document"] == checkpoint["state"]["document"], "Exact post-edit checkpoint required")
    if check_current_source:
        require(args["expected_source_sha256"] == data["source_sha256"]
            == _file_hash(args["expected_document_path"]), "Current checkpoint source differs")
    marker = entry_marker(data["expected_document_path"], data["source_sha256"], data["target_operation_native_id"],
        data["target_feature_native_id"], data["expected_old"], data["new_value"])
    same_path(data["marker_path"], marker)
    md, mp = read_pin(str(marker), _file_hash(marker))
    expected_marker = entry_marker_state(data, path)
    same_path(md["receipt_path"], path); expected_marker["receipt_path"] = md["receipt_path"]
    require(md == expected_marker, "Exact completed entry marker differs")
    require(checkpoint["pins"] == data["evidence_pins"] and checkpoint["base_saved_pin"] == data["saved_gtp_pin"],
        "Checkpoint ancestry differs")
    pins = canonical_evidence_pins(checkpoint["pins"], [pin, mp])
    for evidence in pins: require(_file_hash(evidence["path"]) == evidence["sha256"], "Checkpoint evidence changed")
    loaded = deepcopy(checkpoint); loaded.update(pin=pin, entry_edit_pin=pin, pins=pins, historical_only=not check_current_source)
    return loaded

def entry_marker_state(report, receipt_path):
    return dict(scope=SCOPE, status=report["status"], phase=report["phase"], source_sha256=report["source_sha256"],
        saved_gtp_pin=report["saved_gtp_pin"], wip_witness_pin=report["wip_witness_pin"],
        operation_id=report["target_operation_native_id"], feature_id=report["target_feature_native_id"],
        expected_old=report["expected_old"], new_value=report["new_value"], receipt_path=receipt_path,
        setter_attempted=report["setter_attempted"], setter_returned=report["setter_returned"],
        native_dispatch_pending=report["native_dispatch_pending"], readback_verified=report["readback_verified"], automatic_replay=False)

def dispatch_entry_once(guard, rough, feature_dispatch, *, expected_old, new_value, report, persist, claim):
    """Immediate strict compare-and-set through the unchanged once-only guard."""
    observed = guard.read(rough, "GetEntryExitType", feature_dispatch)
    require(type(observed) is int and observed == expected_old, "Immediate compare-and-set precondition failed")
    def pending():
        report.update(phase="SetEntryExitType", native_dispatch_pending=True, mutation_attempted=True)
        claim(); persist()
    def invoke():
        report.update(setter_attempted=True, setter_call_count=1); persist()
        return _member(rough, "SetEntryExitType", feature_dispatch, new_value)
    value = guard.dispatch_once(invoke, persist_pending=pending)
    report.update(setter_returned=True, native_dispatch_pending=False, native_return_type=type(value).__name__,
        native_return_value=value if value is None or type(value) in (bool,int,float,str) else None)
    persist()
    require(type(value) is int and value == 0, "Setter requires strict HRESULT zero; no replay")
    return value

def edit_rough_entry(sw, clsid, typelib_path, *, wip_witness_receipt_path, wip_witness_receipt_sha256,
        entry_contract_path, entry_contract_sha256, expected_old, new_value, acknowledge_experimental_enum,
        saved_gtp_receipt_path, saved_gtp_receipt_sha256, owned_startup_receipt_path, owned_startup_receipt_sha256,
        read_mode="strong", batch_qualification_receipt_path=None, batch_qualification_receipt_sha256=None, **args):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(schema_version=1, scope=SCOPE, status="error", phase="preflight", process_id=args.get("process_id"),
        expected_document_path=args.get("expected_document_path"), source_sha256=args.get("expected_source_sha256"),
        candidate_id=args.get("expected_candidate_tool_native_id"), expected_old=expected_old, new_value=new_value,
        mutation_attempted=False, setter_attempted=False, setter_returned=False, setter_call_count=0, native_dispatch_pending=False,
        readback_verified=False, protected_operations_verified=False, GTP_attempted=False, model_saved=False,
        save_attempted=False, simulation_attempted=False, automatic_replay=False, automatic_retry=False,
        post_cleanup_CAM_getters=False, production_qualified=False, entry_geometry_verified=False, may_continue=False,
        full_geometry_rechecked=False, full_route_snapshot_qualified=False, capture_diagnostics=[], read_mode=read_mode)
    report.update({k:args.get(k) for k in TARGET_KEYS})
    created = claimed = False; session = loaded = marker = ctx = None; started = monotonic()
    def persist():
        report["elapsed_seconds"] = monotonic() - started
        if created:
            if claimed: _write_receipt(marker, entry_marker_state(report,args["receipt_path"]))
            _write_receipt(args["receipt_path"], report)
    def events(active=True):
        value = session.summary(); report["messages"] = value
        require(value.get("subscribed") is True and value.get("active") is active and (active or value.get("disconnected") is True)
            and not any(value.get(k) for k in ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")),
            "CAM event/transport requires stop")
    def capture(label):
        d = dict(phase=label); report["capture_diagnostics"].append(d); persist()
        require(len(report["capture_diagnostics"]) <= 2, "Only before/after entry captures allowed")
        return capture_route_checkpoint(ctx, loaded["state"], d)
    try:
        validate_inventory_request(**{k:args[k] for k in ("process_id","expected_document_path","expected_source_sha256",
            "qualification_only","acknowledge_disposable_copy","receipt_path","message_policy")})
        require(acknowledge_experimental_enum is True, "Explicit experimental raw enum acknowledgement required")
        loaded = load_completed_route_save(saved_gtp_receipt_path,saved_gtp_receipt_sha256,
            owned_startup_receipt_path=owned_startup_receipt_path,owned_startup_receipt_sha256=owned_startup_receipt_sha256,
            read_mode=read_mode,batch_qualification_receipt_path=batch_qualification_receipt_path,
            batch_qualification_receipt_sha256=batch_qualification_receipt_sha256,**args)
        loaded["base_saved_pin"] = deepcopy(loaded["pin"])
        _, witness_pin, witness_pins = load_wip_witness(wip_witness_receipt_path,wip_witness_receipt_sha256,loaded)
        contract = load_entry_contract(entry_contract_path,entry_contract_sha256,expected_old,new_value)
        exact = contract["exact_scope"]
        require(exact == dict(feature_native_id=args["target_feature_native_id"],operation_native_id=args["target_operation_native_id"],
            operation_setup_native_id=args["target_operation_setup_native_id"],tool_native_id=args["expected_candidate_tool_native_id"]),
            "Reviewed experiment target differs")
        local = [Path(__file__),Path(__file__).parent/"sw_cam_route_checkpoint.py"]
        loaded["pins"] = canonical_evidence_pins(loaded["pins"],witness_pins,[contract["pin"],contract["source_pin"]],
            [dict(path=str(p.resolve()),sha256=_file_hash(p)) for p in local])
        marker = entry_marker(args["expected_document_path"],args["expected_source_sha256"],args["target_operation_native_id"],
            args["target_feature_native_id"],expected_old,new_value)
        require(not marker.exists() and not marker.is_symlink(), "Prior entry CAS exists; no replay")
        protected = {str(Path(p["path"]).resolve()).casefold() for p in loaded["pins"]}
        outputs = [str(Path(p).resolve()).casefold() for p in (args["expected_document_path"],args["receipt_path"],marker)]
        require(len(set(outputs)) == 3 and not protected.intersection(outputs), "Output aliases protected evidence")
        report.update(saved_gtp_pin=loaded["pin"],wip_witness_pin=witness_pin,entry_contract=contract,
            evidence_pins=loaded["pins"],marker_path=str(marker))
        _write_receipt(args["receipt_path"],report,create=True); created=True
        ctx = RouteCheckpointContext(loaded,args,sw,typelib_path,None,lambda:None);ctx.files();ctx.identity()
        app = _bootstrap(sw,clsid,typelib_path,args["expected_document_path"]);ctx.identity()
        session=CamMessageSession(app,typelib_path);ctx.app,ctx.events=app,events
        with session:
            result=capture("before");before=snapshot_payload(result);native=result[1]
            require(before["context"]==loaded["state"] and {k:before[k] for k in ("candidate","levels","entry")}=={k:loaded["payload"][k] for k in ("candidate","levels","entry")},
                "Live state differs from completed Save/WIP")
            require(type(before["entry"]["entry"]["GetEntryExitType"]["raw"]) is int
                and before["entry"]["entry"]["GetEntryExitType"]["raw"]==expected_old,"Entry CAS precondition differs")
            report["before"]=before;persist()
            with ctx.guard() as guard:
                found=guard.read(native["doc"],"GetCWObjectFromID",1,args["target_feature_native_id"])
                require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,"Exact target lookup required")
                feature=guard.typed(found[0],"ICWFeature")
                require(_object_id(native["doc"],feature,guard.read)==args["target_feature_native_id"],"Feature ID changed")
                rough=guard.typed(native["operations"][args["target_operation_native_id"]],"ICWRghMillOp")
                def claim():
                    nonlocal claimed
                    _write_receipt(marker,entry_marker_state(report,args["receipt_path"]),create=True);claimed=True
                dispatch_entry_once(guard,rough,found[0],expected_old=expected_old,new_value=new_value,
                    report=report,persist=persist,claim=claim)
            report["dispatch_guard"]=guard.summary();persist()
            ctx.allow_dirty_transition=True
            after=snapshot_payload(capture("after"));report["after"]=after;persist()
            report["target_path_after"]=verify_entry_delta(before,after,operation_id=args["target_operation_native_id"],
                expected_old=expected_old,new_value=new_value)
            report["checkpoint"]=checkpoint_record(loaded,after)
            report.update(readback_verified=True,protected_operations_verified=True,state_sha256=_digest(after["context"]))
            events();report["after_document"]=ctx.identity()
        events(False);ctx.files();report["after_cleanup_document"]=ctx.identity()
        require(report["after_cleanup_document"]==report["after_document"]==report["after"]["context"]["document"],"Cleanup state differs")
        report.update(status="review_required",phase="finished",reason="ENTRY_RAW_VALUE_CHANGED_REGENERATION_AND_CL_GEOMETRY_REVIEW_REQUIRED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],
            phase="finished",issue=_error(exc),readback_verified=False,protected_operations_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False)
    return report

