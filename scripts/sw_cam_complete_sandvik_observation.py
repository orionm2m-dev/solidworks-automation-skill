"""Finish one missing noncutting export after a verified existing-holder CAS.

The original cutting artifact and marker are retained. One full protected after
snapshot follows the missing export; no fresh full-before or wrapper-identity
comparison is performed. No Save, assignment, GTP or geometry setter exists.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from time import monotonic
import math
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _object_id,_file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_inventory import validate_inventory_request,_items
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_compound_plan_evidence import verify_protected_details
from scripts.sw_cam_compound_plan_delta import same_observed_context
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_ud14_qualification import read_ud14_tool,capture_local_tools
from scripts.sw_cam_ud14_probe_core import verify_one_new_tool
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains
from scripts.sw_cam_shared_holder_geometry import read_holder_recipe,verify_holder_profile
import scripts.sw_cam_shared_holder_geometry as holder_geometry
from scripts.sw_cam_holder_observation import observe_holder_nominal
from scripts.sw_cam_sandvik_mt import load_candidate_contract,_curves,_same_edge,POINTS
from scripts.sw_cam_sandvik_phase1 import (
    SCOPE as PRIOR_SCOPE,BINDING_KEYS,FIELDS,field_equal,attempt_marker,
    holder_objects,reject_holder_alias,com_identity,numeric_mesh_observation,fresh_output)
from scripts.sw_cam_stock_mesh_compare import _read_pinned,_decode
from scripts.sw_cam_rough_firstcut import load_firstcut_receipt,read_firstcut_settings
from scripts.sw_operation_guard import check_document_target

from scripts.sw_cam_existing_sandvik import resolve_existing_context, profile_observation
from scripts.sw_cam_existing_sandvik_evidence import load_existing_candidate_evidence
from scripts.sw_cam_noncutting_continuation import load_cutting_export_stop, export_noncutting_once
from scripts.sw_cam_completed_holder_cas import load_completed_holder_cas
from scripts.sw_cam_holder_mode_query import HOLDER_FIELDS

SCOPE="EXISTING_SANDVIK_COMPLETED_OBSERVATION_V1"
READ_MODE="STRONG_PER_GETTER_MISSING_NONCUT_ONLY_V1"
MAX_READS=6000


def load_completion_request(*,completed_receipt_path,completed_receipt_sha256,
        expected_cutting_sha256,holder_shape_receipt_path,holder_shape_receipt_sha256,
        noncutting_stl_path,**args):
    loaded=load_existing_candidate_evidence(**args)
    cutting=load_cutting_export_stop(loaded,completed_receipt_path=completed_receipt_path,
        completed_receipt_sha256=completed_receipt_sha256,expected_cutting_sha256=expected_cutting_sha256,**args)
    shape=load_completed_holder_cas(loaded,cutting,holder_shape_receipt_path=holder_shape_receipt_path,
        holder_shape_receipt_sha256=holder_shape_receipt_sha256,**args)
    pins={}
    for pin in cutting["immutable_pins"]+shape["pins"]:
        key=str(Path(pin["path"]).resolve()).casefold()
        if key in pins and pins[key]["sha256"]!=pin["sha256"]:raise ValueError("Conflicting immutable continuation pin")
        pins[key]=pin
    blocked={Path(p["path"]).resolve() for p in list(pins.values())+loaded["anchor"].pins}
    blocked|={Path(args["expected_document_path"]).resolve(),Path(cutting["noncutting_marker_path"]).resolve()}
    receipt=fresh_output(args["receipt_path"],".json",blocked)
    fresh_output(noncutting_stl_path,".stl",blocked|{receipt.resolve()})
    historical,_=read_pin(cutting["prior_receipt_pin"]["path"],cutting["prior_receipt_pin"]["sha256"])
    loaded.update(cutting=cutting,shape=shape,pins=list(pins.values()),
        historical_candidate=historical["before_candidate"])
    return loaded


def complete_sandvik_observation(sw,clsid,typelib_path,*,completed_receipt_path,
        completed_receipt_sha256,expected_cutting_sha256,holder_shape_receipt_path,
        holder_shape_receipt_sha256,noncutting_stl_path,**args):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,read_mode=READ_MODE,status="error",phase="preflight",process_id=args.get("process_id"),
        native_dispatch_pending=False,export_attempted=False,cutting_export_attempted=False,mutation_attempted=False,
        tool_creation_attempted=False,MT_load_attempted=False,field_setter_attempted=False,
        holder_setter_attempted=False,operation_assignment_attempted=False,GTP_attempted=False,
        GOP_attempted=False,AFR_attempted=False,simulation_attempted=False,model_saved=False,
        save_attempted=False,TechDB_write_attempted=False,automatic_replay=False,automatic_rollback=False,
        units_verified=False,physical_tool_qualified=False,cutting_partition_verified=False,
        numeric_profile_verified=False,production_qualified=False,may_continue=False,draft_save_eligible=False,
        exports_verified=False,raw_exports_pinned=False,holder_profile_verified=False,holder_profile_observed=False,
        holder_readback_stable=False,protected_context_unchanged=False,post_cleanup_CAM_getters=False,
        readback_verified=False,native_read_count=0,dispatches=[],exports={},snapshot_diagnostics=[],guard_diagnostics=[])
    expected_candidate_tool_native_id=args["expected_candidate_tool_native_id"]
    session=anchor=receipt=None;created=False;baseline=None;active_guard=None
    started=monotonic()
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:_write_receipt(receipt,report)
    def events(active=True):
        value=session.summary();report["messages"]=value
        if (value.get("subscribed") is not True or value.get("active") is not active
            or (not active and value.get("disconnected") is not True)
            or any(value.get(k) for k in ("event_count","overflow","callback_errors","callback_error_count",
                                         "subscription_error","disconnect_errors"))):
            raise ValueError("CAM event or transport requires stop")
    def identity():
        pid=_member(sw,"GetProcessID")
        if type(pid) is not int or pid!=args["process_id"]:raise ValueError("Exact process changed")
        anchor.check_runtime_identity();doc=raw_part_identity(sw)
        check_document_target(doc["path"],doc["title"],expected_path=args["expected_document_path"],required=True)
        if _file_hash(args["expected_document_path"])!=args["expected_source_sha256"]:
            raise ValueError("Saved source changed")
        if baseline is not None and doc!=baseline:raise ValueError("Active document/dirty state changed")
        return doc
    def verify_files():
        anchor.check_files()
        for p in pins:
            if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Prior immutable evidence changed")
    @contextmanager
    def guard():
        g=ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],
            expected_document=identity(),source_sha256=args["expected_source_sha256"],
            evidence_pins=anchor.pins+pins,verify_evidence=verify_files,
            verify_owned_process=anchor.check_runtime_identity,check_events=events)
        try:
            with g:yield g
        finally:report["guard_diagnostics"].append(g.summary())
    @contextmanager
    def reads(*,strong=False):
        nonlocal active_guard
        if active_guard is not None:raise ValueError("Nested read scope")
        with guard() as g:
            active_guard=g
            try:yield
            finally:active_guard=None
    def read(obj,name,*values):
        if active_guard is None:raise ValueError("Getter outside bounded scope")
        report["native_read_count"]+=1
        if report["native_read_count"]>MAX_READS:raise ValueError("Read budget exceeded")
        return active_guard.read(obj,name,*values)
    def typed(obj,name):
        if active_guard is None:raise ValueError("Interface query outside bounded scope")
        report["native_read_count"]+=1
        if report["native_read_count"]>MAX_READS:raise ValueError("Read budget exceeded")
        return active_guard.typed(obj,name)
    def details(state,native,read,typed,diag,boundary):
        read_selected_operation_tool_details(state,native,read,typed,diag,
            feature_native_id=args["expected_feature_native_id"],boundary=boundary)
        source=anchor.data["request"]
        for mode in ("three_step_profile","strategy"):
            read_compound_strategy(state,native,read,typed,diag.setdefault(mode,{}),
                feature_id=source["reference_feature_native_id"],owner_id=source["owner_setup_native_id"],
                step_count=3,expected_header=anchor.profile["header"],boundary=boundary,observation=mode)
        verify_protected_details(anchor,state,diag)
        for key in ("three_step_profile","strategy"):
            if diag[key]!=anchor.data["saved_details"][key]:raise ValueError("Protected compound changed")
    def capture(phase,full=False):
        report["phase"]=phase;diag=dict(phase=phase);report["snapshot_diagnostics"].append(diag);persist()
        state,native=capture_selected_plan(sw,clsid,typelib_path,args["expected_document_path"],
            process_id=args["process_id"],expected_source_sha256=args["expected_source_sha256"],
            evidence=anchor,check=events,diagnostic=diag,progress=persist,
            operation_details_reader=details if full else None)
        expected=deepcopy(state);expected["document"]["needs_save"]=anchor.state["document"]["needs_save"]
        anchor.verify(expected);report[phase]=state;persist()
        return state,native

    def candidate_snapshot(native,phase,*,full):
        with reads(strong=True):
            model=read(sw,"ActiveDoc")
            metric=read_document_cam_unit_scope(model,app,sw_read=lambda o,n:read(o,n),cam_read=read)
            if metric!=prior["metric_scope"]:raise ValueError("Metric document scope changed")
        with reads():
            firstcut=read_firstcut_settings(native["operations"][loaded["rough_id"]],read,typed)
            if firstcut!=loaded["firstcut"]:raise ValueError("Firstcut checkpoint changed")
            crib=typed(read(native["machine"],"IGetToolcrib"),"ICWToolcrib4")
            if full:
                rows=capture_local_tools(crib,native["doc"],read,typed)
                verify_one_new_tool(prior["before_tools"],rows,expected_candidate_tool_native_id)
            else:
                rows=deepcopy(loaded["historical_candidate"]["local_tools"])
            matches=[]
            for raw in _items(read(crib,"GetAllTools"),typed,read,128):
                t=typed(raw,"ICWTool")
                if _object_id(native["doc"],t,read)==expected_candidate_tool_native_id:matches.append(t)
            if len(matches)!=1:raise ValueError("Exact existing tool not unique")
            tool=matches[0]
            if read(tool,"IsMillTool") is not True:raise ValueError("Existing candidate is not MILL")
            if full:
                observed=read_ud14_tool(tool,doc=native["doc"],read=read,typed=typed,
                    diagnostic=report.setdefault(phase+"_tool_diagnostic",{}))
            else:
                kind=read(tool,"ToolType")
                if type(kind) is not int or kind!=14:raise ValueError("Exact UD14 type required")
                ud=typed(tool,"ICWMillUDTool")
                values={key:read(tool if key in ("CutDiameter","Protrusion") else ud,key) for key,_ in FIELDS}
                if any(not field_equal(key,values[key],value) for key,value in FIELDS):
                    raise ValueError("Current candidate scalar differs from R83")
                mt=read(ud,"GetToolName")
                check_document_target(mt,None,expected_path=prior["tool"]["mt_path_raw"],required=True)
                observed=deepcopy(prior["tool"])
                observed["parameters"]=values
                observed["mt_path_raw"]=mt
            if observed!=prior["tool"]:raise ValueError("Existing candidate fields or exact tool/shank profile changed")
            observation=profile_observation(loaded["candidate"],observed["profiles"])
            if observation!=loaded["profile_observation"]:raise ValueError("Frozen contour observation changed")
            holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
            expected_holder=loaded["shape"]["holder_snapshot"]
            if full:
                all_holders=holder_objects(crib,native["doc"],read,typed)
                reject_holder_alias(holder,{k:v for k,v in all_holders.items() if k!=expected_candidate_tool_native_id},
                    identity=lambda obj:com_identity(obj,read))
                holder_fields={name:read(holder,name) for name in HOLDER_FIELDS}
                hp={};hd=dict(state=hp,capture_complete=False);report[phase+"_holder_diagnostic"]=hd
                read_segment_chains(holder,"GetHolderProfile",read=read,typed=typed,
                    diagnostic=hd,budget=dict(curves=0,chains=0,islands=0))
                if hp!=loaded["shape"]["holder_profile"]:raise ValueError("Holder profile differs from verified CAS readback")
                hv=observe_holder_nominal(hp,loaded["holder"],25)
                if hv!=loaded["shape"]["holder_verification"] or hv.get("native_holder_shape_verified") is not True:
                    raise ValueError("Current seventeen-segment holder recipe no longer matches")
            else:
                holder_fields=deepcopy(expected_holder)
                for name in ("GetHolderShape","GetName","GetProtrusion"):
                    holder_fields[name]=read(holder,name)
                hp=deepcopy(loaded["shape"]["holder_profile"])
                hv=deepcopy(loaded["shape"]["holder_verification"])
            if any(type(holder_fields[n]) is not type(expected_holder[n]) or holder_fields[n]!=expected_holder[n] for n in HOLDER_FIELDS):
                raise ValueError("Current holder mode/fields differ from completed CAS")
            check_document_target(holder_fields["GetName"],None,expected_path=loaded["holder"]["file_path"],required=True)
        report[phase+"_candidate_provenance"]=dict(
            fresh_tool_profile=full,fresh_shank_profile=full,fresh_holder_profile=full,
            fresh_local_tool_inventory=full,fresh_all_nine_scalars=True,fresh_MT_reference=True,
            fresh_holder_mode_path_protrusion=True,fresh_firstcut=True,
            tool_profile_source=None if full else dict(pin=loaded["pin"],field="tool.profiles"),
            holder_profile_source=None if full else dict(pin=loaded["shape"]["pin"],field="after.holder_profile"),
            other_holder_fields_source=None if full else dict(pin=loaded["shape"]["pin"],field="after.holder"),
            local_tool_inventory_source=None if full else dict(pin=loaded["cutting"]["prior_receipt_pin"],field="before_candidate.local_tools"))
        snap=dict(tool=observed,profile_observation=observation,holder_profile=hp,
            holder_verification=hv,holder_fields=holder_fields,firstcut=firstcut,metric_scope=metric,local_tools=rows)
        report[phase+"_candidate"]=snap;persist()
        return tool,holder,snap

    def validate_current():
        if active_guard is not None:raise ValueError("Export cannot overlap read scope")
        if report.get("before_candidate") is None:raise ValueError("Current candidate/holder snapshot required")
        identity();verify_files();events()

    def noncut_dispatch(label,path,pending):
        if label!="CreateSTLOfNonCuttingPortion":raise ValueError("Only missing noncutting export allowed")
        with guard() as g:
            report["native_read_count"]+=13
            if report["native_read_count"]>MAX_READS:raise ValueError("Read budget exceeded")
            # Recheck scalar/mode/path bindings immediately before one dispatch.
            ud=g.typed(tool,"ICWMillUDTool")
            for key,value in FIELDS:
                if not field_equal(key,g.read(tool if key in ("CutDiameter","Protrusion") else ud,key),value):
                    raise ValueError("Candidate scalar changed before export")
            check_document_target(g.read(ud,"GetToolName"),None,expected_path=prior["tool"]["mt_path_raw"],required=True)
            if (g.read(holder,"GetHolderShape")!=before_candidate["holder_fields"]["GetHolderShape"]
                or g.read(holder,"GetName")!=before_candidate["holder_fields"]["GetName"]):
                raise ValueError("Holder mode/path changed before export")
            def persist_pending():
                pending()
                report.update(phase=label,native_dispatch_pending=True,export_attempted=True)
                persist()
            value=g.dispatch_once(lambda:_member(tool,label,path),persist_pending=persist_pending)
        report["native_dispatch_pending"]=False
        report["dispatches"]=[dict(label=label,path=path,attempted=True,returned=True,pending=False,
            return_type=type(value).__name__,return_value=value if type(value) in (int,bool,float,str,type(None)) else None)]
        persist()
        return value

    try:
        loaded=load_completion_request(completed_receipt_path=completed_receipt_path,
            completed_receipt_sha256=completed_receipt_sha256,expected_cutting_sha256=expected_cutting_sha256,
            holder_shape_receipt_path=holder_shape_receipt_path,holder_shape_receipt_sha256=holder_shape_receipt_sha256,
            noncutting_stl_path=noncutting_stl_path,**args)
        prior=loaded["data"];anchor=loaded["anchor"];pins=loaded["pins"]
        receipt=Path(args["receipt_path"]);_write_receipt(receipt,report,create=True);created=True
        baseline=loaded["shape"]["after_document"]
        if identity()!=baseline:raise ValueError("Current document differs from completed CAS")
        report.update(before_document=deepcopy(baseline),source_before_sha256=args["expected_source_sha256"],
            expected_document_path=args["expected_document_path"],expected_source_sha256=args["expected_source_sha256"],
            prior_receipt_pin=loaded["pin"],prior_creation_marker_pin=loaded["creation_pin"],
            holder_shape_pin=loaded["shape"]["pin"],holder_shape_marker_pin=loaded["shape"]["marker_pin"],
            completed_cutting_receipt_pin=loaded["cutting"]["prior_receipt_pin"],
            original_export_marker_pin=loaded["cutting"]["original_marker_pin"],
            tool_native_id=expected_candidate_tool_native_id,anchor=anchor.summary(),evidence_pins=pins,
            candidate_contract=loaded["candidate"],holder_recipe=loaded["holder"],
            request_binding={k:deepcopy(args[k]) for k in BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")},
            dispatch_marker_path=loaded["cutting"]["noncutting_marker_path"],profile_observation=loaded["profile_observation"])
        report["exports"]["cutting"]=dict(pin=loaded["cutting"]["cutting_pin"],reused=True,
            source_receipt_pin=loaded["cutting"]["prior_receipt_pin"],hresult=loaded["cutting"]["cutting_hresult"],
            source_holder_context="R84c before holder mode CAS",applicability_to_current_holder_verified=False,
            classification_pending=True,physical_tool_qualified=False,units_verified=False)
        verify_files();app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"])
        if identity()!=baseline:raise ValueError("Document changed acquiring CAM host")
        session=CamMessageSession(app,typelib_path)
        with session:
            before=deepcopy(prior["before"])
            report["before_reference"]=dict(pin=loaded["pin"],field="before",fresh_full_snapshot=False,
                subsequent_holder_shape_pin=loaded["shape"]["pin"])
            with reads(strong=True):native=resolve_existing_context(app,read,typed,prior)
            tool,holder,before_candidate=candidate_snapshot(native,"before",full=False)
            report["holder_profile_observed"]=True;report["holder_profile_verified"]=True
            report["noncutting_continuation"]=export_noncutting_once(loaded["cutting"],noncutting_stl_path,
                dispatch_once=noncut_dispatch,validate_current=validate_current)
            report["exports"]["noncutting"]=report["noncutting_continuation"]["analysis"]
            report["raw_exports_pinned"]=True
            after,after_native=capture("after",full=True)
            if (after["document"]!=baseline or not same_observed_context(before,after,allow_dirty=True)):
                raise ValueError("Protected plan changed outside the verified holder CAS")
            _,_,after_candidate=candidate_snapshot(after_native,"after",full=True)
            if before_candidate!=after_candidate:raise ValueError("Candidate or holder readback changed during export")
            report["protected_context_unchanged"]=True;report["holder_readback_stable"]=True
        events(active=False);report["after_document"]=identity();verify_files()
        report.update(status="review_required",phase="finished",readback_verified=True,draft_save_eligible=True,
            classification_pending=True,reason="CURRENT_CANDIDATE_HOLDER_AND_FULL_PROTECTED_CONTEXT_OBSERVED_RAW_PORTIONS_PENDING_PHYSICAL_CLASSIFICATION")
    except Exception as exc:
        report.update(status="uncertain" if report["export_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False,draft_save_eligible=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(receipt_write_error=_error(exc),status="uncertain",readback_verified=False,draft_save_eligible=False)
    return report
