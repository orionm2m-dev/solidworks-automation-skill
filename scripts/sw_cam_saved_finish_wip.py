"""One all-setups software WIP export from a verified saved finish checkpoint.

No generation, Save, setters, document switching or process launch is exposed.
The native stock mesh needs independent frame, resolution and removal review.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import json,re
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_finish_recovery import load_completed_recovery,_payload,_capture_payload
from scripts.sw_cam_finish_continuation import FinishContinuationContext,_events
from scripts.sw_cam_finish_continuation_evidence import IDS,selected
from scripts.sw_cam_finish_read_batch import capture_finish_recipe_batch
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_completed_gtp_wip import output_plan,collect_wip_files,run_one_wip_export
from scripts.sw_cam_mill_qualification import _bootstrap

SCOPE="SAVED_RECOVERED_FINISH_WIP_EXPORT_V1"
ACTION="export_wip"


def self_pin():return dict(path=str(Path(__file__).resolve()),sha256=_file_hash(__file__))


def route_scope(state,args):
    require(len(state["features"])==19 and len(state["feature_setups"])==3
        and len(state["operation_setups"])==3 and len(state["operations"])==6,"Exact saved route inventory required")
    selected(state,args,generated=True)
    rows=state["operations"]
    require([r["native_id"] for r in rows]==[143,144,195,196,247,248],"Exact saved operation order required")
    for row in rows:
        expected={247:[191],248:[74]}.get(row["native_id"],[])
        require(type(row["native_id"]) is int and row["suppressed"] is False
            and type(row["toolpath_generated"]) is bool and row["toolpath_generated"]==bool(expected)
            and row["toolpath_record_counts"]==expected
            and all(type(n) is int for n in row["toolpath_record_counts"]),"Saved generated inventory differs")
    require(state["document"]["needs_save"] is False,"Clean saved checkpoint required")


def load_saved_finish(path,sha256,**args):
    loaded=load_completed_recovery(path,sha256,action="save",check_current_source=True,**args)
    require(loaded["checkpoint_action"]=="save" and loaded.get("historical_only") is False,"Current saved checkpoint required")
    route_scope(loaded["state"],args)
    result=dict(loaded)
    result["pins"]=canonical_evidence_pins(loaded["pins"],[self_pin()])
    require(len(result["pins"])<=64 and len(result["lineage_pins"])<=16,"WIP pin budget exceeded")
    # The unchanged dispatch/collection engine must already be in validated runtime closure.
    core=Path(run_one_wip_export.__code__.co_filename).resolve()
    require(any(Path(p["path"]).resolve()==core and p["sha256"]==_file_hash(core) for p in result["pins"]),"Original WIP core pin missing")
    return result


def wip_marker(args):
    source=Path(args["expected_document_path"]).resolve()
    key=_digest(dict(scope=SCOPE,source=str(source).casefold(),source_sha256=args["expected_source_sha256"],
        rough_operation_id=args["target_operation_native_id"],finish_operation_id=args["finish_operation_native_id"]))
    return source.parent/("saved_finish_wip_"+key+".json")


def verify_capture(state,payload,loaded,args):
    route_scope(state,args)
    require(state==loaded["state"] and payload==_payload(loaded),"Saved route or full cutter/settings/levels/leads changed")


def read_compensation(ctx,native,args,diagnostic,persist):
    """Read existing NC objects; preserve raw enum values without interpreting them."""
    observed=[];diagnostic["raw_compensation"]=observed;diagnostic["compensation_complete"]=False;persist()
    with ctx.guard() as guard:
        for operation_id in (args["target_operation_native_id"],args["finish_operation_native_id"]):
            row=dict(operation_native_id=operation_id,status="reading",raw_values={});observed.append(row);persist()
            raw=native["operations"][operation_id]
            require(_object_id(native["doc"],raw,guard.read)==operation_id,"NC operation identity differs")
            mill=guard.typed(raw,"ICWMillOperation")
            nc=guard.typed(guard.read(mill,"IGetNCParam"),"ICWNCParam")
            for name in ("GetTlpComp","GetCNCComp"):
                value=guard.read(nc,name)
                row["raw_values"][name]=dict(raw=value if type(value) in (int,bool,float,str) or value is None else None,
                    python_type=type(value).__name__,semantics_qualified=False)
                persist()
                require(type(value) is int and -(2**31)<=value<2**31,"Strict NC compensation integer required")
            row["status"]="captured";persist()
    diagnostic["compensation_guard"]=guard.summary();diagnostic["compensation_complete"]=True;persist()
    return observed


def capture_saved_finish(ctx,loaded,args,diagnostic,persist):
    ctx.files();ctx.events();ctx.identity()
    observed=capture_finish_recipe_batch(ctx,loaded["state"],holder_recipe=loaded["holder_recipe"],diagnostic=diagnostic)
    state,payload=observed["state"],_capture_payload(observed)
    diagnostic.update(observed_context=deepcopy(state),observed_payload=deepcopy(payload),saved_checkpoint_match_verified=False)
    persist() # Preserve complete observations before acceptance assertions.
    verify_capture(state,payload,loaded,args)
    read_compensation(ctx,observed["native"],args,diagnostic,persist)
    diagnostic.update(saved_checkpoint_match_verified=True,comparison_reference_pin=deepcopy(loaded["pin"]),
        original_route_qualification_extended=False)
    ctx.files();ctx.events();require(ctx.identity()==state["document"],"Capture identity changed")
    return state,observed["native"]


def export_saved_finish_wip(sw,clsid,typelib_path,*,checkpoint_receipt_path,checkpoint_receipt_sha256,
        project_root,output_dir,acknowledge_machine_scope,**args):
    from scripts.sw_cam_events import CamMessageSession
    require(args.get("qualification_only") is True and args.get("acknowledge_disposable_copy") is True
        and args.get("software_only_experiment") is True and args.get("message_policy")=="vendor_default"
        and acknowledge_machine_scope is True,"Explicit software-only all-setups qualification required")
    loaded=load_saved_finish(checkpoint_receipt_path,checkpoint_receipt_sha256,**args)
    marker=wip_marker(args)
    directory,canonical=output_plan(output_dir,project_root,args["receipt_path"],args["expected_document_path"],
        loaded["pins"]+loaded["lineage_pins"],marker)
    report=dict(schema_version=1,scope=SCOPE,action=ACTION,status="error",phase="preflight",
        process_id=args["process_id"],expected_document_path=args["expected_document_path"],source_sha256=args["expected_source_sha256"],
        saved_checkpoint_pin=deepcopy(loaded["pin"]),evidence_pins=deepcopy(loaded["pins"]),lineage_pins=deepcopy(loaded["lineage_pins"]),
        module_pin=self_pin(),marker_path=str(marker),receipt_path=args["receipt_path"],output_dir=str(directory),canonical_output_dir=str(canonical),
        native_method="CreateSTLOfWIPs2",native_parameters=[str(directory)+"\\", "wip.stl", "", 0, 0],
        native_scope="all_wip_parts_all_setups",single_operation_scope_claimed=False,
        mutation_attempted=False,native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,native_call_count=0,
        readback_verified=False,export_files_verified=False,compensation_readback_verified=False,files=[],capture_diagnostics=[],
        GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,assignment_attempted=False,tool_edit_attempted=False,
        simulation_attempted=False,model_saved=False,NC_export_attempted=False,automatic_retry=False,automatic_replay=False,
        post_cleanup_CAM_getters=False,full_geometry_rechecked=False,production_qualified=False,
        physical_units_verified=False,frame_verified=False,material_removal_verified=False,full_circle_semantics_verified=False,
        mesh_resolution_qualified=False,manufacturing_tolerance_qualified=False,may_continue=False,
        geometry_provenance=dict(reference_pin=deepcopy(loaded["pin"]),full_geometry_rechecked=False),
        expected_generated_operations=[dict(native_id=247,record_counts=[191]),dict(native_id=248,record_counts=[74])])
    created=claimed=False;session=ctx=None;started=monotonic()
    def marker_state():
        return {k:deepcopy(report[k]) for k in ("scope","saved_checkpoint_pin","source_sha256","status","phase","receipt_path","output_dir",
            "native_call_attempted","native_call_returned","native_dispatch_pending","readback_verified","automatic_replay")}
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:
            if claimed:_write_receipt(marker,marker_state())
            _write_receipt(args["receipt_path"],report)
    def claim():
        nonlocal claimed
        require(directory.resolve(strict=True)==canonical and not any(directory.iterdir()),"WIP output changed before dispatch")
        _write_receipt(marker,marker_state(),create=True);claimed=True
    def capture(label):
        require(len(report["capture_diagnostics"])<2,"Only two complete captures permitted")
        diagnostic=dict(phase=label);report["capture_diagnostics"].append(diagnostic);persist()
        result=capture_saved_finish(ctx,loaded,args,diagnostic,persist)
        if label=="after":
            require(diagnostic["raw_compensation"]==report["capture_diagnostics"][0]["raw_compensation"],"NC compensation changed during WIP export")
            report["compensation_readback_verified"]=True;persist()
        return result
    try:
        _write_receipt(args["receipt_path"],report,create=True);created=True
        ctx=FinishContinuationContext(loaded,dict(args),sw,typelib_path,None,lambda:_events(session,report))
        ctx.files();ctx.identity();ctx.app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"]);ctx.identity()
        session=CamMessageSession(ctx.app,typelib_path)
        with session:
            _events(session,report);directory.mkdir();require(directory.resolve(strict=True)==canonical,"WIP directory identity changed")
            run_one_wip_export(report,capture=capture,guard_factory=ctx.guard,persist=persist,claim=claim,
                invoke=lambda machine:_member(machine,"CreateSTLOfWIPs2",*report["native_parameters"]),
                collect=lambda:collect_wip_files(directory,canonical))
            _events(session,report);report["after_document"]=ctx.identity()
        _events(session,report,False);ctx.files();report["after_cleanup_document"]=ctx.identity()
        require(report["after_document"]==report["after_cleanup_document"]==loaded["state"]["document"],"Cleanup changed saved document")
        require(collect_wip_files(directory,canonical)==report["files"],"WIP files changed after capture")
        report.update(status="review_required",phase="finished",reason="SOFTWARE_STOCK_EXPORT_REQUIRES_INDEPENDENT_MESH_REVIEW")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],phase="finished",
            issue=_error(exc),readback_verified=False,export_files_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False,export_files_verified=False)
    return report


PARAMS={"process_id","expected_document_path","expected_source_sha256",*IDS,"qualification_only","acknowledge_disposable_copy",
    "software_only_experiment","message_policy","receipt_path","addin_clsid","module_sha256","checkpoint_receipt_path",
    "checkpoint_receipt_sha256","project_root","output_dir","acknowledge_machine_scope"}


def validate_request(request):
    require(type(request) is dict and set(request)=={"action","params"} and request["action"]==ACTION,"Only fixed export_wip action allowed")
    params=request["params"];require(type(params) is dict and set(params)==PARAMS,"Exact WIP request fields required")
    require(type(params["process_id"]) is int and params["process_id"]>0,"Explicit owned existing PID required")
    for name in IDS:require(type(params[name]) is int and 0<params[name]<2**32,"Strict native IDs required")
    for name,value in params.items():
        if name.endswith("sha256"):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),"Exact SHA256 required")
        if name.endswith("path") or name in {"project_root","output_dir"}:require(type(value) is str and Path(value).is_absolute(),"Absolute paths required")
    require(params["module_sha256"]==self_pin()["sha256"],"WIP module hash differs")
    require(params["qualification_only"] is True and params["acknowledge_disposable_copy"] is True
        and params["software_only_experiment"] is True and params["acknowledge_machine_scope"] is True
        and params["message_policy"]=="vendor_default","Explicit disposable software all-setups acknowledgements required")
    require(type(params["addin_clsid"]) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',params["addin_clsid"]),"Exact CAM CLSID required")
    return dict(params)


def dispatch_request(request):
    params=validate_request(request)
    args={k:v for k,v in params.items() if k not in {"addin_clsid","module_sha256","checkpoint_receipt_path","checkpoint_receipt_sha256","project_root","output_dir","acknowledge_machine_scope"}}
    loaded=load_saved_finish(params["checkpoint_receipt_path"],params["checkpoint_receipt_sha256"],**args)
    output_plan(params["output_dir"],params["project_root"],args["receipt_path"],args["expected_document_path"],
        loaded["pins"]+loaded["lineage_pins"],wip_marker(args))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=params["process_id"]):
        inventory=discover_cam_installations();require(not inventory["errors"],"CAM discovery failed")
        registration=select_registration(inventory,params.pop("addin_clsid"));params.pop("module_sha256")
        sw,_=connect_solidworks(process_id=params["process_id"],launch_new_instance=False,wait_seconds=1)
        pid=_member(sw,"GetProcessID");require(type(pid) is int and pid==params["process_id"],"Connected process differs")
        return export_saved_finish_wip(sw,registration["clsid"],str(Path(registration["addin_path"]).parent/'camworks.tlb'),**params)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description="Export software WIP from a saved finish checkpoint")
    parser.add_argument('--request',required=True);parser.add_argument('--result',required=True)
    opts=parser.parse_args(argv);request_path,result_path=Path(opts.request),Path(opts.result)
    require(request_path.is_absolute() and request_path.is_file() and request_path.stat().st_size<=65536,"Bounded absolute request required")
    require(result_path.is_absolute() and result_path.suffix.lower()=='.json' and result_path.parent.is_dir()
        and not result_path.exists() and not result_path.is_symlink(),"Fresh result JSON required")
    try:
        request=json.loads(request_path.read_text(encoding='utf-8'));params=validate_request(request)
        blocked={str(Path(v).resolve()).casefold() for k,v in params.items() if k.endswith('path') or k=='output_dir'}
        require(str(result_path.resolve()).casefold() not in blocked,"Result aliases input/output")
        result=dispatch_request(request)
    except Exception as exc:result=dict(status='error',issue=_error(exc),native_action_replayed=False)
    _write_receipt(result_path,result,create=True)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','export_files_verified')}))
    return 0 if result.get('readback_verified') is True else 2


if __name__=='__main__':raise SystemExit(main())
