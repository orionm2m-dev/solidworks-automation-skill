"""Read raw levels of one ungenerated rough operation from a saved additive plan."""
from copy import deepcopy
from pathlib import Path
import time
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request, _same_inventory
from scripts.sw_cam_mill_route_context import integer
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_compound_plan_evidence import verify_protected_details
from scripts.sw_cam_mill_levels import read_mill_level_values, _nonnull, MAX_NEW_READS
from scripts.sw_operation_guard import check_document_target
from scripts.sw_cam_turn_tool import _digest

SCOPE = "MILL_DEFINED_ROUGH_LEVELS_V1"
BINDING_KEYS = ("process_id","expected_document_path","expected_source_sha256",
    "expected_feature_native_id","expected_operation_native_ids",
    "expected_operation_setup_native_id","expected_tool_native_id")
FALSE_FLAGS = ("mutation_attempted","AFR_attempted","GOP_attempted","GTP_attempted",
    "save_attempted","model_saved","simulation_attempted","export_attempted","stock_edit_attempted",
    "tool_edit_attempted","record_access_attempted","post_cleanup_CAM_getters",
    "units_verified","physical_depth_verified","coordinate_frame_verified","production_qualified",
    "incoming_stock_verified","entry_strategy_read_complete","ramp_helix_parameters_read")

def validate_defined_rough(anchor, feature_id, operation_id, setup_id):
    for value,label in ((feature_id,"target feature"),(operation_id,"target operation"),(setup_id,"target setup")):
        integer(value,label,1)
    if anchor.data.get("scope") != "MILL_ADDED_CIRCULAR_POCKET_PLAN_V1" or len(anchor.state["features"]) != 19:
        raise ValueError("Verified saved nineteen-feature additive pocket plan required")
    if type(anchor.data.get("new_feature_native_id")) is not int or anchor.data["new_feature_native_id"] != feature_id:
        raise ValueError("Exact newly added circular feature required")
    if setup_id != anchor.data["request"]["operation_setup_native_id"]:
        raise ValueError("Target operation setup differs from saved request")
    rows=[r for r in anchor.state["operations"] if r["native_id"]==operation_id]
    if len(rows)!=1 or operation_id not in [r["native_id"] for r in anchor.data["new_operations"]]:
        raise ValueError("Exact newly added operation required")
    op=rows[0]
    if (type(op["mill_operation_type"]) is not int or op["mill_operation_type"] != 0
        or op["linked_feature_ids"] != [feature_id] or op["setup_native_id"] != setup_id
        or op["suppressed"] is not False or op["toolpath_generated"] is not False
        or op["toolpath_record_counts"] != []):
        raise ValueError("One unsuppressed rough definition with zero paths required")
    features=[r for r in anchor.state["features"] if r["geometry"]["native_id"]==feature_id]
    if (len(features)!=1 or features[0]["setup_native_id"]!=anchor.data["request"]["owner_setup_native_id"]
        or features[0]["geometry"]["suppressed"] is not False or features[0]["geometry"]["volume_type"]!=2):
        raise ValueError("Exact saved circular feature and owner required")
    return deepcopy(op)

def inspect_defined_rough_levels(sw,clsid,typelib_path,*,target_feature_native_id,
        target_operation_native_id,target_operation_setup_native_id,**args):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status="error",phase="preflight",read_only=True,may_continue=False,
        process_id=args.get("process_id"),readback_verified=False,levels_read_complete=False,
        native_read_attempted=False,native_dispatch_pending=False,native_reads=[],snapshot_diagnostics=[],
        target_feature_native_id=target_feature_native_id,target_operation_native_id=target_operation_native_id,
        target_operation_setup_native_id=target_operation_setup_native_id,
        entry_scope="Start/first-cut/setup levels only; ramp, helix, plunge and clearance parameters are not read.")
    report.update({key:False for key in FALSE_FLAGS})
    receipt=session=anchor=baseline=None;created=False
    def persist():
        if created:_write_receipt(receipt,report)
    def events(active=True):
        s=session.summary();report["messages"]=s
        if (s.get("subscribed") is not True or s.get("active") is not active
            or (not active and s.get("disconnected") is not True)
            or any(s.get(k) for k in ("event_count","overflow","callback_errors","callback_error_count",
                "subscription_error","disconnect_errors"))):
            raise ValueError("CAM event or transport requires stop")
    def identity():
        pid=_member(sw,"GetProcessID")
        if type(pid) is not int or pid!=args["process_id"]:raise ValueError("Exact owned process changed")
        anchor.check_runtime_identity()
        doc=raw_part_identity(sw)
        check_document_target(doc["path"],doc["title"],expected_path=args["expected_document_path"],required=True)
        if doc["needs_save"] is not False or _file_hash(args["expected_document_path"])!=args["expected_source_sha256"]:
            raise ValueError("Clean saved source changed")
        anchor.check_files()
        return doc
    def details_reader(state,native,read,typed,diag,boundary):
        read_selected_operation_tool_details(state,native,read,typed,diag,
            feature_native_id=args["expected_feature_native_id"],boundary=boundary)
        source=anchor.data["request"]
        for mode in ("three_step_profile","strategy"):
            read_compound_strategy(state,native,read,typed,diag.setdefault(mode,{}),
                feature_id=source["reference_feature_native_id"],owner_id=source["owner_setup_native_id"],
                step_count=3,expected_header=anchor.profile["header"],boundary=boundary,observation=mode)
        verify_protected_details(anchor,state,diag)
        for key in ("three_step_profile","strategy"):
            if diag[key]!=anchor.data["saved_details"][key]:
                raise ValueError("Preserved compound profile changed: "+key)
        matches=[r for r in state["operations"] if r["native_id"]==target_operation_native_id]
        if len(matches)!=1 or matches[0]!=report["selected_definition"]:
            raise ValueError("Target definition changed before level getters")
        raw=read(native["doc"],"GetCWObjectFromID",1,target_feature_native_id)
        if not isinstance(raw,(tuple,list)) or len(raw)!=2 or raw[1] is not True:
            raise ValueError("Exact target feature lookup failed")
        feature=typed(raw[0],"ICWFeature")
        if _object_id(native["doc"],feature,read)!=target_feature_native_id:
            raise ValueError("Target feature pointer identity differs")
        if _object_id(native["doc"],read(feature,"GetOwner"),read)!=source["owner_setup_native_id"]:
            raise ValueError("Target feature owner changed")
        operation=native["operations"][target_operation_native_id]
        if _object_id(native["doc"],operation,read)!=target_operation_native_id:
            raise ValueError("Target operation pointer identity differs")
        local=diag["levels_observation"]={}
        def native_read(label,invoke,decoder=None,*,interface=False,validator=None):
            if len(local.get("reads",[]))>=MAX_NEW_READS:raise ValueError("Bounded level getter budget exceeded")
            boundary()
            row=dict(name=label,phase=report["phase"],attempted=False,returned=False,validated=False)
            report["native_reads"].append(row);local.setdefault("reads",[]).append(row)
            report["native_dispatch_pending"]=True;persist()
            boundary();row["attempted"]=True;report["native_read_attempted"]=True;persist()
            started=time.monotonic()
            try:value=invoke()
            except Exception as exc:
                row.update(raised=True,issue=_error(exc),elapsed_seconds=time.monotonic()-started)
                report["native_dispatch_pending"]=False;persist();raise
            row.update(returned=True,elapsed_seconds=time.monotonic()-started,return_type=type(value).__name__)
            report["native_dispatch_pending"]=False;persist();boundary()
            if interface:_nonnull(value)
            if validator is not None:validator(value)
            if decoder is not None:
                value=decoder(value);row["value"]=deepcopy(value)
            row["validated"]=True;persist();return value
        def query(raw,name):
            return native_read("QueryInterface."+name,lambda:typed(raw,name),interface=True)
        def getter(raw,interface_name,name,*params,decoder=None,interface=False,validator=None):
            return native_read(interface_name+"."+name,lambda:read(raw,name,*params),
                decoder=decoder,interface=interface,validator=validator)
        read_mill_level_values(feature,operation,native_read=native_read,typed=query,getter=getter,report=local)
        local.pop("reads")
    try:
        validate_inventory_request(**{key:args[key] for key in ("process_id","expected_document_path",
            "expected_source_sha256","qualification_only","acknowledge_disposable_copy","receipt_path","message_policy")})
        anchor=load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],args["saved_plan_receipt_sha256"],
            **{key:args[key] for key in BINDING_KEYS})
        report["selected_definition"]=validate_defined_rough(anchor,target_feature_native_id,
            target_operation_native_id,target_operation_setup_native_id)
        if any(Path(args["receipt_path"]).resolve()==Path(p["path"]).resolve() for p in anchor.pins):
            raise ValueError("Output cannot overwrite evidence")
        receipt=Path(args["receipt_path"]);_write_receipt(receipt,report,create=True);created=True
        report["anchor"]=anchor.summary();baseline=identity()
        app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"])
        if identity()!=baseline:raise ValueError("Identity changed acquiring event host")
        session=CamMessageSession(app,typelib_path)
        with session:
            for phase in ("before","after"):
                events()
                if identity()!=baseline:raise ValueError("Identity changed before capture")
                report["phase"]=phase;diag=dict(phase=phase);report["snapshot_diagnostics"].append(diag);persist()
                state,_=capture_selected_plan(sw,clsid,typelib_path,args["expected_document_path"],
                    process_id=args["process_id"],expected_source_sha256=args["expected_source_sha256"],
                    evidence=anchor,check=events,diagnostic=diag,progress=persist,
                    operation_details_reader=details_reader)
                if state["document"]!=baseline:raise ValueError("Document changed during capture")
                anchor.verify(state)
                report[phase]=state;report[phase+"_details"]=deepcopy(diag["operation_details"])
                persist();events()
            if (not _same_inventory(report["before"],report["after"])
                or report["before_details"]!=report["after_details"]):
                raise ValueError("Read-only context or level observation changed")
        events(active=False)
        if identity()!=baseline:raise ValueError("Identity changed during event cleanup")
        report.update(status="review_required",phase="finished",readback_verified=True,levels_read_complete=True,
            levels=deepcopy(report["before_details"]["levels_observation"]["levels"]),
            setup=deepcopy(report["before_details"]["levels_observation"]["setup"]),
            saved_file_sha256=args["expected_source_sha256"],state_sha256=_digest(report["before"]),
            reason="STABLE_DEFINITION_LEVELS_NO_GTP_NO_ENTRY_OR_INCOMING_STOCK_QUALIFICATION")
    except Exception as exc:
        report.update(status="error",failed_phase=report["phase"],phase="finished",issue=_error(exc),
            readback_verified=False,levels_read_complete=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:
            report.update(status="error",receipt_write_error=_error(exc),readback_verified=False,levels_read_complete=False)
    return report
