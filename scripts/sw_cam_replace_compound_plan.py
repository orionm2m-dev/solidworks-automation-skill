"""Qualify one compound strategy assignment and feature-local REGENERATE plan."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence, validate_selected_ids
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_mill_append_operations import exact_target
from scripts.sw_cam_mill_append_evidence import attempt_marker
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_compound_plan_evidence import (
    SCOPE, load_primary_route, check_primary_route, verify_protected_details, validate_replacement_baseline)
from scripts.sw_cam_compound_plan_delta import (same_observed_context, verify_replaced_plan,
    verify_strategy_details, target_tool_metadata_verified)
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

TARGET_KEYS = ("target_feature_native_id", "target_owner_setup_native_id", "target_operation_setup_native_id",
    "expected_target_operation_native_ids", "expected_target_operation_types", "expected_target_tool_native_ids",
    "expected_strategy_id", "expected_strategy_name")
BASE_KEYS = ("process_id", "expected_document_path", "expected_source_sha256", "qualification_only",
             "acknowledge_disposable_copy", "receipt_path", "message_policy")
BINDING_KEYS = ("process_id", "expected_document_path", "expected_source_sha256",
    "expected_feature_native_id", "expected_operation_native_ids", "expected_operation_setup_native_id",
    "expected_tool_native_id")

def validate_replace_request(**args):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    validate_inventory_request(**{k:args[k] for k in BASE_KEYS})
    validate_selected_ids(args["expected_feature_native_id"], args["expected_operation_native_ids"],
        args["expected_operation_setup_native_id"], args["expected_tool_native_id"])
    for key in TARGET_KEYS[:3]:
        if type(args[key]) is not int or not 0 < args[key] < 2**32:
            raise ValueError("Strict target identity required: " + key)
    lists = [args[key] for key in TARGET_KEYS[3:6]]
    if any(type(v) is not list or not 1 <= len(v) <= 32
           or any(type(x) is not int or not 0 <= x < 2**32 for x in v) for v in lists):
        raise ValueError("Strict bounded ordered target operations/types/tools required")
    if len({len(v) for v in lists}) != 1 or len(set(lists[0])) != len(lists[0]):
        raise ValueError("Exact unique target membership and corresponding types/tools required")
    if any(x == 0 for x in lists[0] + lists[2]):
        raise ValueError("Positive target operation/tool identities required")
    if args["requested_strategy_name"] != "Rough-Finish":
        raise ValueError("Only the primary-reviewed exact Rough-Finish route is supported")
    if type(args["expected_strategy_id"]) is not int or not 0 < args["expected_strategy_id"] < 2**31:
        raise ValueError("Strict current strategy ID required")
    if type(args["expected_strategy_name"]) is not str or not 1 <= len(args["expected_strategy_name"]) <= 4096:
        raise ValueError("Exact bounded current strategy name required")
    if args["save_after_verified"] is not True:
        raise ValueError("Explicit verified save is required for this complete replacement lifecycle")
    pins = [read_pin(args[p],args[h])[1] for p,h in (
        ("saved_plan_receipt_path","saved_plan_receipt_sha256"),
        ("primary_route_receipt_path","primary_route_receipt_sha256"))]
    canonical = [p["canonical_path"].casefold() for p in pins]
    if len(set(canonical)) != len(canonical) or str(Path(args["receipt_path"]).resolve()).casefold() in canonical:
        raise ValueError("Distinct input evidence and output required")
    marker = attempt_marker(args["attempt_registry_path"], args["expected_document_path"],
                            args["expected_source_sha256"], args["target_feature_native_id"])
    marker = marker.with_name(marker.name.replace("mill_append_", "compound_replace_", 1))
    if marker.exists() or marker.is_symlink() or marker.resolve() == Path(args["receipt_path"]).resolve():
        raise ValueError("A prior replacement attempt exists; inspect outcome, never replay")
    return marker

def read_strategy(obj, read, expected_id, expected_name):
    attribute = read(obj, "Attribute")
    pair = read(obj, "GetAttribute")
    active = read(obj, "IGetActiveAttribute")
    if (type(attribute) is not int or attribute != expected_id
        or not isinstance(pair,(tuple,list)) or len(pair) != 2
        or type(pair[1]) is not int or pair[1] != expected_id
        or pair[0] != expected_name or active != expected_name):
        raise ValueError("Exact Attribute/GetAttribute/active strategy readback differs")
    return dict(attribute_id=attribute, attribute_name=pair[0], active_attribute_name=active)

def replace_compound_strategy_plan(sw, clsid, typelib_path, **args):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(scope=SCOPE, status="error", phase="preflight", request=deepcopy(args),
        process_id=args.get("process_id"), mutation_attempted=False, native_dispatch_pending=False,
        lookup_call_attempted=False, lookup_call_returned=False, lookup_id=None,
        strategy_assignment_attempted=False, attribute_call_returned=False,
        attribute_hresult_observable=False, immediate_strategy_readback_verified=False,
        strategy_stage_verified=False, GOP_attempted=False, gop_call_returned=False, gop_hresult=None,
        operation_delta_verified=False, save_attempted=False, save_call_returned=False, save_hresult=None,
        readback_verified=False, save_readback_verified=False, model_saved=False,
        AFR_attempted=False, GTP_attempted=False, simulation_attempted=False,
        explicit_delete_attempted=False, global_GOP_attempted=False, TechDB_write_attempted=False,
        stock_edit_attempted=False, geometry_edit_attempted=False, material_edit_attempted=False,
        tool_assignment_attempted=False, automatic_replay=False, automatic_rollback=False,
        full_inventory_verified=False, world_geometry_verified=False, production_qualified=False,
        post_cleanup_CAM_getters=False, reopen_persistence_verified=False, may_continue=False,
        attempts=[], snapshot_diagnostics=[], dispatch_guards=[], target_tool_observations={},
        target_tool_metadata_readback_verified=False, target_tool_physical_geometry_qualified=False)
    anchor = route = profile = session = receipt = marker = None
    created = marker_created = False
    source = args.get("expected_source_sha256")
    def persist():
        if created: _write_receipt(receipt, report)
    def files():
        anchor.check_files(); check_primary_route(route)
    def identity():
        pid = _member(sw,"GetProcessID")
        if type(pid) is not int or pid != args["process_id"]: raise ValueError("Owned process changed")
        anchor.check_runtime_identity()
        doc = raw_part_identity(sw)
        check_document_target(doc["path"],doc["title"],expected_path=args["expected_document_path"],required=True)
        if _file_hash(args["expected_document_path"]) != source: raise ValueError("Saved source changed")
        return doc
    def events(active=True):
        s = session.summary(); report["messages"] = s
        if (s.get("subscribed") is not True or (active and s.get("active") is not True)
            or (not active and (s.get("active") is not False or s.get("disconnected") is not True))
            or any(s.get(k) for k in ("event_count","overflow","callback_errors","callback_error_count",
                                      "subscription_error","disconnect_errors"))):
            raise ValueError("CAM event/transport requires stop")
    def details_reader(state,native,read,typed,diag,*,boundary):
        read_selected_operation_tool_details(state,native,read,typed,diag,
            feature_native_id=args["expected_feature_native_id"],boundary=boundary)
        for mode in ("three_step_profile","strategy"):
            read_compound_strategy(state,native,read,typed,diag.setdefault(mode,{}),
                feature_id=args["target_feature_native_id"],owner_id=args["target_owner_setup_native_id"],
                step_count=3,expected_header=profile["header"],boundary=boundary,observation=mode)
        if report["phase"] in ("after","saved"):
            target_rows=[r for r in state["operations"] if r["linked_feature_ids"]==[args["target_feature_native_id"]]]
            observation=diag.setdefault("target_tool_observation",{})
            if target_rows and all(r["assigned_tool"].get("tool_type_raw")==1 for r in target_rows):
                read_selected_operation_tool_details(state,native,read,typed,observation,
                    feature_native_id=args["target_feature_native_id"],boundary=boundary)
            else:
                observation.update(status="not_read",reason="TARGET_GENERIC_TOOL_TYPE_NOT_SUPPORTED_FOR_FULL_READER")
    def capture(phase):
        events(); files(); identity()
        report["phase"] = phase
        diag = dict(phase=phase); report["snapshot_diagnostics"].append(diag); persist()
        state,native = capture_selected_plan(sw,clsid,typelib_path,args["expected_document_path"],
            process_id=args["process_id"],expected_source_sha256=source,evidence=anchor,
            check=events,diagnostic=diag,progress=persist,operation_details_reader=details_reader)
        details = {key:deepcopy(diag["operation_details"][key])
                   for key in ("selected_tool_details","three_step_profile","strategy")}
        verify_protected_details(anchor,state,details)
        if "target_tool_observation" in diag["operation_details"]:
            report["target_tool_observations"][phase]=deepcopy(diag["operation_details"]["target_tool_observation"])
        report[phase] = state; report[phase+"_details"] = details
        events(); check_primary_route(route); persist()
        return state,native,details
    def guard(doc):
        return ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],
            expected_document=doc,source_sha256=source,
            evidence_pins=anchor.pins+[route["pin"]]+route["sources"],verify_evidence=files,
            verify_owned_process=anchor.check_runtime_identity,check_events=events)
    def pending(stage):
        nonlocal marker_created
        entry = dict(stage=stage,status="dispatch_pending",native_call_attempted=True,native_call_returned=False)
        if any(r["stage"] == stage for r in report["attempts"]): raise ValueError("Stage already attempted")
        report["attempts"].append(entry)
        report.update(phase=stage,mutation_attempted=True,native_dispatch_pending=True)
        report[{"attribute":"strategy_assignment_attempted","regenerate":"GOP_attempted","save":"save_attempted"}[stage]] = True
        _write_receipt(marker,dict(scope=SCOPE,status="dispatch_pending",stage=stage,
            receipt_path=str(receipt),request=deepcopy(args),automatic_replay=False),create=not marker_created)
        marker_created = True
        persist()
    def returned(stage):
        report["attempts"][-1].update(status="returned",native_call_returned=True)
        report["native_dispatch_pending"] = False
        report[{"attribute":"attribute_call_returned","regenerate":"gop_call_returned","save":"save_call_returned"}[stage]] = True
        persist()
    try:
        marker = validate_replace_request(**args)
        anchor = load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],
            args["saved_plan_receipt_sha256"],**{k:args[k] for k in BINDING_KEYS})
        profile = validate_replacement_baseline(anchor,**{k:args[k] for k in TARGET_KEYS})
        route = load_primary_route(args["primary_route_receipt_path"],args["primary_route_receipt_sha256"],anchor)
        receipt = Path(args["receipt_path"])
        report.update(anchor=anchor.summary(),primary_route=deepcopy(route),target_profile=deepcopy(profile),
                      source_before_sha256=source,dispatch_marker_path=str(marker))
        _write_receipt(receipt,report,create=True); created=True
        baseline = identity()
        if baseline["needs_save"] is not False: raise ValueError("Clean saved qualification part required")
        app = _bootstrap(sw,clsid,typelib_path,args["expected_document_path"])
        if identity() != baseline: raise ValueError("Identity changed acquiring event host")
        session = CamMessageSession(app,typelib_path)
        with session:
            before,native,before_details = capture("before")
            anchor.verify(before)
            if before_details != profile["details"]: raise ValueError("Current target/protected details differ from saved anchor")
            with guard(before["document"]) as g:
                target = exact_target(native,profile,args["target_feature_native_id"],
                                      args["target_owner_setup_native_id"],g.read,g.typed)
                compound = g.typed(target,"ICWMultiStepFeature")
                read_strategy(compound,g.read,args["expected_strategy_id"],args["expected_strategy_name"])
                report["lookup_call_attempted"] = True; persist()
                resolved = g.read(compound,"GetTdbIdForAttribute",args["requested_strategy_name"])
                report.update(lookup_call_returned=True,lookup_id=resolved if type(resolved) is int else None)
                persist()
                if type(resolved) is not int or not 0 < resolved < 2**31:
                    raise ValueError("Exact strategy lookup did not return a positive TechDB ID")
                g.dispatch_once(lambda:setattr(compound,"Attribute",resolved),
                                persist_pending=lambda:pending("attribute"))
                returned("attribute")
            report["dispatch_guards"].append(g.summary())
            immediate_doc = identity()
            expected_doc = deepcopy(before["document"]); expected_doc["needs_save"] = immediate_doc["needs_save"]
            if immediate_doc != expected_doc: raise ValueError("Document changed during strategy assignment")
            with guard(immediate_doc) as g:
                report["immediate_strategy"] = read_strategy(compound,g.read,resolved,args["requested_strategy_name"])
            report["immediate_strategy_readback_verified"] = True; persist()
            assigned,native,assigned_details = capture("after_attribute")
            if not same_observed_context(before,assigned,allow_dirty=True):
                raise ValueError("Strategy setter changed operations or protected context")
            verify_strategy_details(before_details,assigned_details,resolved,args["requested_strategy_name"])
            report["strategy_stage_verified"] = True; persist()
            with guard(assigned["document"]) as g:
                target = exact_target(native,profile,args["target_feature_native_id"],
                                      args["target_owner_setup_native_id"],g.read,g.typed)
                compound = g.typed(target,"ICWMultiStepFeature")
                read_strategy(compound,g.read,resolved,args["requested_strategy_name"])
                result = g.dispatch_once(lambda:_member(target,"GenerateOpPlan",2),
                                         persist_pending=lambda:pending("regenerate"))
                report["gop_hresult"] = result if type(result) is int else None
                returned("regenerate")
            report["dispatch_guards"].append(g.summary())
            if type(result) is not int or result != 0: raise ValueError("Unexpected REGENERATE HRESULT; no replay")
            after,native,after_details = capture("after")
            target_rows = verify_replaced_plan(assigned,after,args["target_feature_native_id"],
                                               args["target_operation_setup_native_id"])
            if after_details != assigned_details: raise ValueError("Regeneration changed strategy/profile/protected full tools")
            report.update(operation_delta_verified=True,replacement_operations=target_rows); persist()
            events(); files()
            save_app = _typed(native["app"],"ICWApp",typelib_path)
            if identity() != after["document"]: raise ValueError("Identity changed before verified save")
            pending("save")
            events(); files()
            if identity() != after["document"]: raise ValueError("Identity changed publishing save pending")
            result = _member(save_app,"SaveActiveDocument")
            report["save_hresult"] = result if type(result) is int else None
            returned("save"); events()
            if type(result) is not int or result != 0: raise ValueError("Unexpected save HRESULT; no replay")
            source = _file_hash(args["expected_document_path"]); report["source_after_sha256"] = source
            saved,_,saved_details = capture("saved")
            if (not same_observed_context(after,saved,allow_dirty=True,allow_saved_source=True)
                or saved["document"]["needs_save"] is not False or saved_details != after_details):
                raise ValueError("Save changed protected context or left the document dirty")
        events(active=False); files()
        if identity() != saved["document"]: raise ValueError("Identity changed during event cleanup")
        report["target_tool_metadata_readback_verified"]=target_tool_metadata_verified(
            report["target_tool_observations"],report["replacement_operations"])
        report.update(status="review_required",phase="finished",readback_verified=True,
            save_readback_verified=True,model_saved=True,state_sha256=_digest(saved),
            continuation_state=deepcopy(saved),saved_file_sha256=source,
            reason="FEATURE_LOCAL_REGENERATE_DEFINITIONS_ONLY_NO_PATHS_OR_MANUFACTURING_QUALIFICATION")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False,
            save_readback_verified=False,model_saved=False)
    finally:
        if session is not None: report["messages"] = session.summary()
        try:
            persist()
            if marker_created:
                _write_receipt(marker,dict(scope=SCOPE,status=report["status"],receipt_path=str(receipt),
                    receipt_sha256=_file_hash(receipt),automatic_replay=False))
        except Exception as exc:
            report.update(status="uncertain" if report["mutation_attempted"] else "error",
                receipt_write_error=_error(exc),readback_verified=False,save_readback_verified=False,model_saved=False)
            try: persist()
            except Exception: pass
    return report
