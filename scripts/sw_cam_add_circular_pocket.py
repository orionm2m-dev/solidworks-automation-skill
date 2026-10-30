"""Add one circle pocket and its definitions while retaining the saved MILL plan."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence,validate_selected_ids
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_mill_append_evidence import attempt_marker
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_compound_plan_evidence import verify_protected_details
from scripts.sw_cam_compound_plan_delta import same_observed_context
from scripts.sw_cam_profile_sketch import (
    _snapshot as sketch_snapshot,_select_plane,_create as create_sketch,_read_sketch,_same_bodies,call)
from scripts.sw_cam_mill_units_qualification import _circle_feature,_circle_sketch,_nonnull
from scripts.sw_cam_added_pocket_delta import (
    SCOPE,SKETCH_SCOPE,profile_for_action,verify_sketch_delta,verify_pocket_delta,verify_pocket_operations,
    verify_circle_observation)
from scripts.sw_cam_added_pocket_evidence import load_circle_route,check_circle_route
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

BASE_KEYS=("process_id","expected_document_path","expected_source_sha256","qualification_only",
    "acknowledge_disposable_copy","receipt_path","message_policy")
REBIND_KEYS=("session_rebind_receipt_path","session_rebind_receipt_sha256")
BINDING_KEYS=("process_id","expected_document_path","expected_source_sha256","expected_feature_native_id",
    "expected_operation_native_ids","expected_operation_setup_native_id","expected_tool_native_id")

def validate_add_pocket_request(**args):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    from scripts.sw_cam_profile_sketch import _input
    validate_inventory_request(**{k:args[k] for k in BASE_KEYS})
    validate_selected_ids(args["expected_feature_native_id"],args["expected_operation_native_ids"],
        args["expected_operation_setup_native_id"],args["expected_tool_native_id"])
    for key in ("reference_feature_native_id","owner_setup_native_id","operation_setup_native_id"):
        if type(args[key]) is not int or not 0<args[key]<2**32:
            raise ValueError("Exact positive native ID required: "+key)
    if args["action"] not in ("create_sketch","create_pocket_plan"):
        raise ValueError("Explicit create_sketch or create_pocket_plan action required")
    spec=_input(args["sketch_spec"])
    if spec["profile"]["kind"]!="circle" or spec["plane_axis"]!="Z":
        raise ValueError("One XY circle specification required")
    if args["save_after_verified"] is not True or args["reverse_direction"] is not False:
        raise ValueError("Verified save and previously qualified direction required")
    if type(args["cylinder_step_index"]) is not int or args["cylinder_step_index"]!=1:
        raise ValueError("Only the middle cylindrical step is supported")
    pins=[read_pin(args[p],args[h])[1] for p,h in (
        ("saved_plan_receipt_path","saved_plan_receipt_sha256"),
        ("route_receipt_path","route_receipt_sha256"))]
    pair={k:args.get(k) for k in REBIND_KEYS}
    if any(v is not None for v in pair.values()):
        if args['action'] != 'create_sketch' or not all(type(v) is str and v for v in pair.values()):
            raise ValueError('Explicit complete rebind is supported only for create_sketch')
        pins.append(read_pin(pair[REBIND_KEYS[0]],pair[REBIND_KEYS[1]])[1])
    canonical=[p["canonical_path"].casefold() for p in pins]
    if len(set(canonical))!=len(canonical) or str(Path(args["receipt_path"]).resolve()).casefold() in canonical:
        raise ValueError("Distinct immutable inputs and new output required")
    marker=attempt_marker(args["attempt_registry_path"],args["expected_document_path"],
        args["expected_source_sha256"],args["reference_feature_native_id"])
    marker=marker.with_name(marker.name.replace("mill_append_","circle_"+args["action"]+"_",1))
    if marker.exists() or marker.is_symlink():
        raise ValueError("Prior pocket attempt exists; inspect outcome, never replay")
    if marker.resolve()==Path(args["receipt_path"]).resolve():
        raise ValueError("Attempt journal and result must differ")
    return marker

def add_circular_pocket_plan(sw,clsid,typelib_path,**args):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SKETCH_SCOPE if args.get("action")=="create_sketch" else SCOPE,status="error",phase="preflight",request=deepcopy(args),
        process_id=args.get("process_id"),mutation_attempted=False,native_dispatch_pending=False,
        sketch_readback_verified=False,sketch_save_readback_verified=False,
        feature_delta_verified=False,circle_readback_verified=False,operation_delta_verified=False,
        readback_verified=False,save_readback_verified=False,model_saved=False,
        GTP_attempted=False,AFR_attempted=False,simulation_attempted=False,
        explicit_delete_attempted=False,global_GOP_attempted=False,TechDB_write_attempted=False,
        stock_edit_attempted=False,geometry_edit_attempted=False,material_edit_attempted=False,
        strategy_assignment_attempted=False,tool_assignment_attempted=False,
        automatic_replay=False,automatic_rollback=False,post_cleanup_CAM_getters=False,
        production_qualified=False,physical_depth_verified=False,cones_completed=False,
        reopen_persistence_verified=False,full_inventory_verified=False,world_geometry_verified=False,
        production_GTP_ready=False,retained_drill_operations_pending_review=True,may_continue=False,attempts=[],snapshot_diagnostics=[],dispatch_guards=[],circle_observations={},sketch_observations={})
    anchor=profile=route=session=receipt=marker=None
    created=marker_created=False
    source=args.get("expected_source_sha256")
    def persist():
        if created:_write_receipt(receipt,report)
    def files():
        anchor.check_files();check_circle_route(route)
    def identity(*,owned=True):
        pid=_member(sw,"GetProcessID")
        if type(pid) is not int or pid!=args["process_id"]:raise ValueError("Owned process changed")
        if owned:anchor.check_runtime_identity()
        doc=raw_part_identity(sw)
        check_document_target(doc["path"],doc["title"],expected_path=args["expected_document_path"],required=True)
        if _file_hash(args["expected_document_path"])!=source:raise ValueError("Saved source changed")
        return doc
    def events(active=True):
        s=session.summary();report["messages"]=s
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
                feature_id=args["reference_feature_native_id"],owner_id=args["owner_setup_native_id"],
                step_count=3,expected_header=profile["header"],boundary=boundary,observation=mode)
        measured=None
        if report["phase"]!="before" or args["action"]=="create_pocket_plan":
            boundary()
            feature=read(sw.ActiveDoc,"FeatureByName",profile["sketch_spec"]["sketch_name"])
            sketch=read(feature,"GetSpecificFeature2")
            measured=_read_sketch(sw,sketch,profile["sketch_spec"])
            _circle_sketch(measured,profile["sketch_spec"])
            boundary()
            diag["new_sketch"]=measured
        if report.get("new_feature_native_id") is not None:
            ident=report["new_feature_native_id"]
            raw=read(native["doc"],"GetCWObjectFromID",1,ident)
            if not isinstance(raw,(tuple,list)) or len(raw)!=2 or raw[1] is not True:
                raise ValueError("Exact new pocket lookup failed")
            base=typed(raw[0],"ICWFeature")
            if _object_id(native["doc"],read(base,"GetOwner"),read)!=args["owner_setup_native_id"]:
                raise ValueError("New pocket owner changed")
            observed=_circle_feature(raw[0],native["doc"],typelib_path,read,typed)
            diag["new_circle"]=dict(feature=observed,
                sketch_circle_m=_circle_sketch(measured,profile["sketch_spec"]))
    def capture(phase,count):
        events();files();identity()
        report["phase"]=phase
        diag=dict(phase=phase);report["snapshot_diagnostics"].append(diag);persist()
        state,native=capture_selected_plan(sw,clsid,typelib_path,args["expected_document_path"],
            process_id=args["process_id"],expected_source_sha256=source,evidence=anchor,
            check=events,diagnostic=diag,progress=persist,operation_details_reader=details_reader,
            expected_feature_count=count)
        details={k:deepcopy(diag["operation_details"][k])
            for k in ("selected_tool_details","three_step_profile","strategy")}
        verify_protected_details(anchor,state,details)
        if details!=profile["details"]:raise ValueError("Original compound strategy/profile or protected tool changed")
        report[phase]=state;report[phase+"_details"]=details
        if "new_sketch" in diag["operation_details"]:
            report["sketch_observations"][phase]=deepcopy(diag["operation_details"]["new_sketch"])
            first=report["sketch_observations"].get("after_sketch" if args["action"]=="create_sketch" else "before")
            if first is not None and first!=report["sketch_observations"][phase]:
                raise ValueError("Created circle sketch changed")
        if "new_circle" in diag["operation_details"]:
            observation=deepcopy(diag["operation_details"]["new_circle"])
            verify_circle_observation(observation,profile["sketch_spec"],profile["depth_native"],
                report["new_feature_native_id"])
            report["circle_observations"][phase]=observation
        events();persist();return state,native
    def guard(doc):
        return ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],
            expected_document=doc,source_sha256=source,
            evidence_pins=anchor.pins+[route["pin"]]+route["sources"],
            verify_evidence=files,verify_owned_process=anchor.check_runtime_identity,check_events=events)
    def pending(stage):
        nonlocal marker_created
        if any(r["stage"]==stage for r in report["attempts"]):raise ValueError("Stage already attempted")
        report["attempts"].append(dict(stage=stage,status="dispatch_pending",
            native_call_attempted=True,native_call_returned=False))
        report.update(phase=stage,mutation_attempted=True,native_dispatch_pending=True)
        _write_receipt(marker,dict(scope=report["scope"],status="dispatch_pending",stage=stage,
            receipt_path=str(receipt),request=deepcopy(args),automatic_replay=False),create=not marker_created)
        marker_created=True;persist()
    def returned(stage):
        report["attempts"][-1].update(status="returned",native_call_returned=True)
        report["native_dispatch_pending"]=False;persist()
    def save(stage,state,native,count,phase):
        nonlocal source
        # All dispatch/read scopes are closed before a save can replace the file.
        events();files()
        app=_typed(native["app"],"ICWApp",typelib_path)
        if identity()!=state["document"]:raise ValueError("Identity changed before save")
        pending(stage);events();files()
        if identity()!=state["document"]:raise ValueError("Identity changed publishing save pending")
        result=_member(app,"SaveActiveDocument")
        key="sketch_save_hresult" if stage=="save_sketch" else "save_hresult"
        report[key]=result if type(result) is int else None
        returned(stage);events()
        if type(result) is not int or result!=0:raise ValueError("Unexpected save HRESULT; no replay")
        source=_file_hash(args["expected_document_path"])
        saved,native=capture(phase,count)
        if (not same_observed_context(state,saved,allow_dirty=True,allow_saved_source=True)
            or saved["document"]["needs_save"] is not False):
            raise ValueError("Save changed captured context or left a dirty document")
        return saved,native
    try:
        marker=validate_add_pocket_request(**args)
        anchor=load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],args["saved_plan_receipt_sha256"],
            **{k:args[k] for k in BINDING_KEYS},**{k:args.get(k) for k in REBIND_KEYS})
        profile=profile_for_action(anchor,args)
        route=load_circle_route(args["route_receipt_path"],args["route_receipt_sha256"],
            anchor if args["action"]=="create_sketch" else anchor.previous)
        receipt=Path(args["receipt_path"])
        report.update(anchor=anchor.summary(),profile=deepcopy(profile),route=deepcopy(route),
            source_before_sha256=source,dispatch_marker_path=str(marker))
        _write_receipt(receipt,report,create=True);created=True
        initial=identity()
        if initial["needs_save"] is not False:raise ValueError("Clean saved part required")
        app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"])
        if identity()!=initial:raise ValueError("Identity changed acquiring event host")
        session=CamMessageSession(app,typelib_path)
        with session:
            before,native=capture("before",18);anchor.verify(before)
            report["retained_reference_operations"]=[dict(native_id=r["native_id"],
                mill_operation_type=r["mill_operation_type"]) for r in before["operations"]
                if r["linked_feature_ids"]==[args["reference_feature_native_id"]]]
            report["production_limit"]="Retained reference drill definitions require explicit disable/removal review before production or GTP release."
            persist()
            if args["action"]=="create_sketch":
                sketch_state,model,refs=sketch_snapshot(sw,args["process_id"],args["expected_document_path"],profile["sketch_spec"])
                if (sketch_state["features"]!=before["sw_reference"]["feature_tree"]
                    or not _same_bodies(sketch_state["solids"],before["sw_reference"]["solids"])
                    or sketch_state["needs_save"] is not False):
                    raise ValueError("SW snapshot changed before circle creation")
                _select_plane(sketch_state)
                report["sketch_creation"]={}
                def sketch_check():
                    events();identity(owned=False)
                with guard(before["document"]) as g:
                    names=g.dispatch_once(lambda:create_sketch(sw,model,sketch_state,refs,sketch_check,
                        report["sketch_creation"]),persist_pending=lambda:pending("sketch"))
                    returned("sketch")
                report["dispatch_guards"].append(g.summary())
                report["created_features"]=[dict(name=n,type="ProfileFeature"
                    if n==profile["sketch_spec"]["sketch_name"] else "RefPlane") for n in names]
                after_sketch,native=capture("after_sketch",18)
                verify_sketch_delta(before,after_sketch,report["created_features"],profile["sketch_spec"])
                report["sketch_readback_verified"]=True;persist()
                saved_sketch,native=save("save_sketch",after_sketch,native,18,"saved_sketch")
                report.update(sketch_save_readback_verified=True,sketch_source_sha256=source);persist()
                saved=saved_sketch
                report["saved"]=deepcopy(saved)
                report["saved_details"]=deepcopy(report["saved_sketch_details"])
            else:
                saved_sketch=before
                with guard(saved_sketch["document"]) as g:
                    indices=[i for i,s in enumerate(saved_sketch["feature_setups"])
                        if s["native_id"]==args["owner_setup_native_id"]]
                    if len(indices)!=1:raise ValueError("Exact owner setup missing")
                    setup=g.typed(native["setups"][indices[0]],"ICWSetup")
                    if _object_id(native["doc"],setup,g.read)!=args["owner_setup_native_id"]:
                        raise ValueError("Owner setup ID mismatch")
                    value=g.dispatch_once(lambda:_member(setup,"CreateMillFeature2",0,
                        profile["sketch_spec"]["sketch_name"],False,profile["depth_native"],False,
                        False,False,False,0.,-1,False,0,0),persist_pending=lambda:pending("feature"))
                    returned("feature")
                report["dispatch_guards"].append(g.summary())
                _nonnull(value,"CreateMillFeature2 return")
                with guard(identity()) as g:
                    new_id=_object_id(native["doc"],value,g.read)
                report["new_feature_native_id"]=new_id;persist()
                after_feature,native=capture("after_feature",19)
                report["new_feature"]=verify_pocket_delta(saved_sketch,after_feature,new_id,
                    args["owner_setup_native_id"],profile["sketch_spec"],profile["depth_native"])
                report.update(feature_delta_verified=True,circle_readback_verified=True);persist()
                with guard(after_feature["document"]) as g:
                    raw=g.read(native["doc"],"GetCWObjectFromID",1,new_id)
                    if not isinstance(raw,(tuple,list)) or len(raw)!=2 or raw[1] is not True:
                        raise ValueError("New pocket exact dispatch lookup failed")
                    feature=g.typed(raw[0],"ICWFeature")
                    if (_object_id(native["doc"],feature,g.read)!=new_id
                        or _object_id(native["doc"],g.read(feature,"GetOwner"),g.read)!=args["owner_setup_native_id"]
                        or g.read(feature,"Suppressed") is not False):
                        raise ValueError("New pocket dispatch scope differs")
                    result=g.dispatch_once(lambda:_member(feature,"GenerateOpPlan",1),
                        persist_pending=lambda:pending("gop"))
                    report["gop_hresult"]=result if type(result) is int else None
                    returned("gop")
                report["dispatch_guards"].append(g.summary())
                if type(result) is not int or result!=0:raise ValueError("Unexpected RETAIN HRESULT; no replay")
                after,native=capture("after",19)
                report["new_operations"]=verify_pocket_operations(after_feature,after,new_id,args["operation_setup_native_id"])
                if report["circle_observations"]["after"]!=report["circle_observations"]["after_feature"]:
                    raise ValueError("GOP changed circular pocket geometry")
                report["operation_delta_verified"]=True;persist()
                saved,native=save("save",after,native,19,"saved")
                if report["circle_observations"]["saved"]!=report["circle_observations"]["after"]:
                    raise ValueError("Save changed circular pocket metadata")
        events(active=False);files()
        if identity()!=saved["document"]:raise ValueError("Identity changed during cleanup")
        report.update(status="review_required",phase="finished",readback_verified=True,
            save_readback_verified=True,model_saved=True,source_after_sha256=source,
            saved_file_sha256=source,state_sha256=_digest(saved),continuation_state=deepcopy(saved),
            reason=("SAVED_CIRCLE_ONLY_CONTINUE_WITH_CREATE_POCKET_PLAN" if args["action"]=="create_sketch"
                else "CYLINDRICAL_POCKET_DEFINITIONS_ONLY_NO_PATHS_CONES_OR_PHYSICAL_DEPTH_QUALIFICATION"))
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False,
            save_readback_verified=False,model_saved=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:
            persist()
            if marker_created:_write_receipt(marker,dict(scope=report["scope"],status=report["status"],
                receipt_path=str(receipt),receipt_sha256=_file_hash(receipt),automatic_replay=False))
        except Exception as exc:
            report.update(status="uncertain" if report["mutation_attempted"] else "error",
                receipt_write_error=_error(exc),readback_verified=False,save_readback_verified=False,model_saved=False)
            try:persist()
            except Exception:pass
    return report
