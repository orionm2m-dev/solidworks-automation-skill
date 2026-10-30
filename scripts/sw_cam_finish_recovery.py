"""Fixed native recovery, CL and Save actions after a completed uncertain finish GTP.

No generation, setters, document switching, process launch or replay is exposed.
The failed operation stays immutable; recovery is a separate fresh observation.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import json,re
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_finish_continuation_evidence import (load_finish_continuation,verify_gtp_delta,
    verify_save_delta,selected,marker_state,continuation_marker,make_checkpoint,IDS,checked_lineage_pins)
from scripts.sw_cam_finish_continuation import FinishContinuationContext,_events,_finished
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_finish_read_batch import capture_finish_recipe_batch
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_generated_plan_cl import validate_project_output
from scripts.sw_operation_guard import check_document_target

SCOPES={"recover_readonly":"FINISH_GTP_READBACK_RECOVERY_V1","export_cl":"RECOVERED_FINISH_CL_V1","save":"RECOVERED_FINISH_SAVE_V1"}
DELTAS={"GetPreviousAllowance":(0.5,0.25),"SideCutAmt":(5.0,3.2)}


def verify_recovery_delta(before_state,before_payload,after_state,after_payload,args):
    verify_gtp_delta(before_state,after_state,args)
    require(selected(after_state,args,generated=True)["toolpath_record_counts"]==[74],"Exact observed finish 74-record container required")
    expected=deepcopy(before_payload)
    changes=[]
    for name,(old,new) in DELTAS.items():
        value=expected["finish"]["details"]["finish"][name]["raw"]
        require(type(value) is float and value==old,"Exact prior derived field required: "+name)
        expected["finish"]["details"]["finish"][name]["raw"]=new
        changes.append(dict(field="finish.details.finish."+name+".raw",before=old,after=new))
    require(after_payload==expected,"Unexpected post-GTP recipe delta")
    return dict(scope="two_exact_observed_GTP_derived_scalars",changes=changes,
        finish_record_counts=[74],rough_record_counts=[191],engineering_qualification=False)


def _self_pin():return dict(path=str(Path(__file__).resolve()),sha256=_file_hash(__file__))
def _key(pin):return str(Path(pin["path"]).resolve()).casefold()
def _same_pin(a,b):return _key(a)==_key(b) and a["sha256"]==b["sha256"]
def _payload(loaded):return dict(rough=deepcopy(loaded["payload"]),finish=deepcopy(loaded["finish_payload"]))
def _capture_payload(result):return dict(rough=result["rough_payload"],finish=result["finish_payload"])
def _all_pins(pins):
    for pin in pins:require(_file_hash(pin["path"])==pin["sha256"],"Recovery evidence changed")
def _history(*groups):
    value=canonical_evidence_pins(*groups);checked_lineage_pins(value);return value


def load_failed_gtp(path,sha256,*,check_current_source=True,**args):
    data,pin=read_pin(path,sha256)
    require(data.get("scope")=="SAVED_ROUTE_FINISH_GTP_V1" and data.get("action")=="gtp"
        and data.get("status")=="uncertain" and data.get("phase")=="finished"
        and data.get("failed_phase")=="after_capture" and "receipt_write_error" not in data,"Exact terminal post-GTP mismatch required")
    require(data.get("parent_action")=="save","Saved verified parent required")
    parent=data["parent_checkpoint_pin"]
    saved=load_finish_continuation(parent["path"],parent["sha256"],action="save",
        check_current_source=check_current_source,**args)
    require(saved.get("checkpoint_action")=="save" and _same_pin(saved["pin"],parent),"Validated parent differs")
    require(type(data.get("process_id")) is int and data["process_id"]==args["process_id"],"Process binding differs")
    check_document_target(data["expected_document_path"],None,expected_path=args["expected_document_path"],required=True)
    for name in IDS:require(type(data.get(name)) is int and data[name]==args[name],"Recovery native ID differs")
    for name in ("native_call_attempted","native_call_returned","mutation_attempted","GTP_attempted","GTP_returned"):
        require(data.get(name) is True,"Missing completed native action: "+name)
    for name in ("native_dispatch_pending","save_attempted","save_pending","model_saved","readback_verified",
            "GOP_attempted","AFR_attempted","assignment_attempted","tool_edit_attempted","simulation_attempted",
            "NC_export_attempted","automatic_retry","automatic_replay","automatic_rollback","production_qualified"):
        require(data.get(name) is False,"Unexpected failed-GTP flag: "+name)
    require(type(data.get("GTP_call_count")) is int and data["GTP_call_count"]==1
        and data.get("native_return_type")=="int" and type(data.get("native_return_value")) is int
        and data["native_return_value"]==0,"One strict successful native GTP return required")
    guard=data["dispatch_guard"]
    require(guard.get("claimed") is True and guard.get("native_call_attempted") is True
        and guard.get("native_call_returned") is True and guard.get("invalid") is False,"Completed valid dispatch guard required")
    clean_events(data)
    diagnostics=data["snapshot_diagnostics"]
    require(len(diagnostics)==2 and all(d.get("capture_complete") is True for d in diagnostics)
        and diagnostics[0].get("finish_current_checkpoint_match_verified") is True
        and diagnostics[1].get("finish_current_checkpoint_match_verified") is False,"Exact completed mismatch capture required")
    require(data["before_context"]==saved["state"] and data["before_payload"]==_payload(saved),"Failed GTP parent snapshot differs")
    require(data["source_before_sha256"]==data["source_after_sha256"]==saved["source_sha256"]==args["expected_source_sha256"],"Source binding differs")
    require(data["evidence_pins"]==saved["pins"] and data.get("lineage_pins",[])==saved.get("lineage_pins",[]),"Failed GTP evidence closure differs")
    expected_marker=continuation_marker(args["expected_document_path"],"gtp",parent,args["finish_operation_native_id"])
    require(Path(data["marker_path"]).resolve()==expected_marker,"Failed GTP marker identity differs")
    marker,marker_pin=read_pin(str(expected_marker),_file_hash(expected_marker))
    require(marker==marker_state(data),"Failed GTP marker differs")
    # Only fully validated completed configuration98 and Save99 move to history.
    cfg=saved["config_receipt"];cfg_pin=saved["parent_pin"]
    cfg_marker=dict(path=cfg["marker_path"],sha256=_file_hash(cfg["marker_path"]))
    completed=canonical_evidence_pins(saved["active_continuation_pins"],[cfg_pin,cfg_marker])
    keys={_key(p) for p in completed}
    require(len(keys)==4 and keys<={_key(p) for p in saved["pins"]},"Exact completed98/99 quartet required")
    fixed=[p for p in saved["pins"] if _key(p) not in keys]
    history=_history(saved.get("lineage_pins",[]),completed)
    runtime=_self_pin();live=canonical_evidence_pins(fixed,[pin,marker_pin,runtime])
    _all_pins(live+history)
    result=dict(saved)
    result.update(pins=live,lineage_pins=history,failed_receipt=data,failed_pin=pin,failed_marker_pin=marker_pin,
        recovery_module_pin=runtime,fixed_pins=canonical_evidence_pins(fixed,[runtime]),original_saved_parent_pin=parent,
        pin=pin,historical_only=not check_current_source,active_own_pins=[],active_continuation_pins=[])
    return result


def _marker(action,original_failed_pin,args):
    digest=_digest(dict(scope=SCOPES[action],source=str(Path(args["expected_document_path"]).resolve()).casefold(),
        original_failed_gtp_sha256=original_failed_pin["sha256"],source_before_sha256=args["expected_source_sha256"],
        operation_id=args["finish_operation_native_id"]))
    return Path(args["expected_document_path"]).resolve().parent/("finish_recovered_"+action+"_"+digest+".json")


def _report(action,loaded,parent_action,args):
    return dict(schema_version=1,scope=SCOPES[action],action=action,status="error",phase="preflight",
        process_id=args["process_id"],expected_document_path=args["expected_document_path"],**{k:args[k] for k in IDS},
        source_before_sha256=args["expected_source_sha256"],source_after_sha256=args["expected_source_sha256"],
        receipt_path=args["receipt_path"],parent_checkpoint_pin=deepcopy(loaded["pin"]),parent_action=parent_action,
        evidence_pins=deepcopy(loaded["pins"]),lineage_pins=deepcopy(loaded["lineage_pins"]),
        recovery_module_pin=deepcopy(loaded["recovery_module_pin"]),failed_gtp_pin=deepcopy(loaded["failed_pin"]),
        failed_gtp_marker_pin=deepcopy(loaded["failed_marker_pin"]),read_only=action=="recover_readonly",
        native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,mutation_attempted=False,
        GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,assignment_attempted=False,tool_edit_attempted=False,
        simulation_attempted=False,NC_export_attempted=False,GTP_call_count=0,GTP_returned=False,
        save_attempted=False,save_pending=False,model_saved=False,readback_verified=False,save_readback_verified=False,
        full_geometry_rechecked=False,automatic_retry=False,automatic_replay=False,automatic_rollback=False,
        reopen_persistence_verified=False,production_qualified=False,may_continue=False,snapshot_diagnostics=[],
        before_context=deepcopy(loaded["state"]),before_payload=_payload(loaded),
        marker_path=str(_marker(action,loaded["failed_pin"],args)) if action!="recover_readonly" else None)


def _preflight(report,loaded,args):
    require(args.get("qualification_only") is True and args.get("acknowledge_disposable_copy") is True
        and args.get("software_only_experiment") is True and args.get("message_policy")=="vendor_default","Explicit disposable software qualification required")
    output=Path(args["receipt_path"])
    require(output.is_absolute() and output.suffix.lower()==".json" and output.parent.is_dir()
        and not output.exists() and not output.is_symlink(),"Fresh absolute JSON receipt required")
    paths=[args["expected_document_path"],str(output)]
    if report["marker_path"]:
        marker=Path(report["marker_path"]);require(not marker.exists() and not marker.is_symlink(),"Prior native attempt exists; no replay")
        paths.append(str(marker))
    keys={str(Path(p).resolve()).casefold() for p in paths}
    require(len(keys)==len(paths) and not keys.intersection(_key(p) for p in loaded["pins"]+loaded["lineage_pins"]),"Source/output/evidence overlap")


def recover_readonly(sw,clsid,typelib_path,*,failed_receipt_path,failed_receipt_sha256,**args):
    from scripts.sw_cam_events import CamMessageSession
    loaded=load_failed_gtp(failed_receipt_path,failed_receipt_sha256,**args)
    report=_report("recover_readonly",loaded,"failed_gtp",args);_preflight(report,loaded,args)
    created=False;session=None;start=monotonic()
    def persist():
        report["elapsed_seconds"]=monotonic()-start
        if created:_write_receipt(args["receipt_path"],report)
    try:
        _write_receipt(args["receipt_path"],report,create=True);created=True
        ctx=FinishContinuationContext(loaded,dict(args),sw,typelib_path,None,lambda:_events(session,report))
        ctx.allow_dirty_transition=True;ctx.identity()
        ctx.app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"])
        session=CamMessageSession(ctx.app,typelib_path)
        with session:
            report["phase"]="fresh_readback";diag=dict(phase="fresh_readback");report["snapshot_diagnostics"].append(diag);persist()
            observed=capture_finish_recipe_batch(ctx,loaded["state"],holder_recipe=loaded["holder_recipe"],diagnostic=diag)
            state,payload=observed["state"],_capture_payload(observed)
            report.update(observed_context=deepcopy(state),observed_payload=deepcopy(payload),phase="validate_observation");persist()
            report["permitted_delta"]=verify_recovery_delta(loaded["state"],_payload(loaded),state,payload,args)
            ctx.files();require(ctx.identity()==state["document"],"Recovery identity changed")
        _events(session,report,False);ctx.files();report["after_cleanup_document"]=ctx.identity()
        require(report["after_cleanup_document"]==state["document"],"Recovery cleanup identity changed")
        report.update(after_context=deepcopy(state),after_payload=deepcopy(payload),failed_gtp_resolved_by_fresh_readback=True)
        _finished(report,state,payload)
    except Exception as exc:
        report.update(status="error",failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        persist()
    return report


def load_completed_recovery(path,sha256,*,action,check_current_source=True,_depth=0,**args):
    require(action in SCOPES and type(_depth) is int and 0<=_depth<=2,"Bounded recovery lineage required")
    data,pin=read_pin(path,sha256)
    require(data.get("scope")==SCOPES[action] and data.get("action")==action and data.get("phase")=="finished"
        and data.get("status")=="review_required" and data.get("readback_verified") is True
        and not any(k in data for k in ("issue","failed_phase","receipt_write_error")),"Completed verified recovery action required")
    require(type(data.get("process_id")) is int and data["process_id"]==args["process_id"],"Recovery process differs")
    check_document_target(data["expected_document_path"],None,expected_path=args["expected_document_path"],required=True)
    for name in IDS:require(type(data.get(name)) is int and data[name]==args[name],"Recovery IDs differ")
    require(_same_pin(data["recovery_module_pin"],_self_pin()),"Recovery module changed")
    clean_events(data)
    for name in ("GTP_attempted","GOP_attempted","AFR_attempted","assignment_attempted","tool_edit_attempted",
        "simulation_attempted","NC_export_attempted","automatic_retry","automatic_replay","automatic_rollback","production_qualified"):
        require(data.get(name) is False,"Unexpected recovery action flag")
    require(type(data.get("GTP_call_count")) is int and data["GTP_call_count"]==0,"Recovery must never generate")
    parent=data["parent_checkpoint_pin"]
    old_args=dict(args,expected_source_sha256=data["source_before_sha256"])
    if action=="recover_readonly":
        require(data.get("parent_action")=="failed_gtp" and data.get("read_only") is True
            and data.get("mutation_attempted") is False and data.get("native_call_attempted") is False
            and data.get("native_call_returned") is False and data.get("native_dispatch_pending") is False
            and data.get("model_saved") is False and data.get("save_attempted") is False
            and data.get("failed_gtp_resolved_by_fresh_readback") is True,"Exact read-only recovery required")
        previous=load_failed_gtp(parent["path"],parent["sha256"],check_current_source=False,**old_args)
        require(len(data["snapshot_diagnostics"])==1 and data["snapshot_diagnostics"][0].get("capture_complete") is True,"Complete fresh capture required")
        permitted=verify_recovery_delta(previous["state"],_payload(previous),data["observed_context"],data["observed_payload"],old_args)
        require(data["permitted_delta"]==permitted and data["after_context"]==data["observed_context"]
            and data["after_payload"]==data["observed_payload"],"Recovery observed checkpoint differs")
        history=_history(previous["lineage_pins"],[previous["failed_pin"]])
        fixed=canonical_evidence_pins(previous["fixed_pins"],[previous["failed_marker_pin"]])
        own=[pin]
    else:
        expected_parent="recover_readonly" if action=="export_cl" else "export_cl"
        require(data.get("parent_action")==expected_parent and _depth<2,"Exact recovery action order required")
        previous=load_completed_recovery(parent["path"],parent["sha256"],action=expected_parent,check_current_source=False,_depth=_depth+1,**old_args)
        require(data["after_payload"]==_payload(previous),"Protected recovered recipe changed")
        diagnostics=data["snapshot_diagnostics"]
        require(len(diagnostics)==(3 if action=="export_cl" else 2)
            and all(d.get("capture_complete") is True for d in diagnostics),"Complete continued captures required")
        if action=="export_cl":
            require(data["after_context"]==previous["state"] and data.get("output_verified") is True
                and type(data.get("native_hresult")) is int and data["native_hresult"]==0
                and data.get("model_saved") is False and data.get("save_attempted") is False,"Verified CL-only export required")
            require(_file_hash(data["output"]["path"])==data["output"]["sha256"],"CL output changed")
            for diagnostic in diagnostics:
                require(diagnostic.get("observed_context")==previous["state"] and diagnostic.get("observed_payload")==_payload(previous),"CL full observations differ")
        else:
            require(data.get("save_attempted") is True and data.get("save_readback_verified") is True
                and data.get("model_saved") is True and data.get("save_pending") is False
                and data.get("native_return_type")=="int" and type(data.get("native_return_value")) is int
                and data["native_return_value"]==0,"One strict completed Save required")
            verify_save_delta(previous["state"],data["after_context"],old_args,data["saved_file_sha256"])
        require(data.get("native_call_attempted") is True and data.get("native_call_returned") is True
            and data.get("native_dispatch_pending") is False,"Completed native continuation required")
        expected_marker=_marker(action,previous["failed_pin"],old_args)
        require(Path(data["marker_path"]).resolve()==expected_marker,"Recovery marker identity differs")
        marker,mpin=read_pin(str(expected_marker),_file_hash(expected_marker));require(marker==marker_state(data),"Recovery marker differs")
        history=_history(previous["lineage_pins"],previous["active_own_pins"])
        fixed=previous["fixed_pins"]
        own=canonical_evidence_pins([pin,mpin],[data["output"]] if action=="export_cl" else [])
    require(data["before_context"]==previous["state"] and data["before_payload"]==_payload(previous),"Recovery parent snapshot differs")
    require(data["evidence_pins"]==previous["pins"] and data["lineage_pins"]==previous["lineage_pins"],"Recovery evidence closure differs")
    state,payload=data["after_context"],data["after_payload"]
    require(data["after_cleanup_document"]==state["document"],"Recovery cleanup differs")
    checkpoint=make_checkpoint(state,payload)
    require(data["checkpoint"]==checkpoint and data["checkpoint_sha256"]==_digest(checkpoint),"Recovery checkpoint digest differs")
    require(data["source_before_sha256"]==previous["source_sha256"] and data["source_after_sha256"]==state["saved_file_sha256"]==args["expected_source_sha256"],"Recovery saved source differs")
    if check_current_source:require(_file_hash(args["expected_document_path"])==args["expected_source_sha256"],"Current saved source changed")
    live=canonical_evidence_pins(fixed,own);_all_pins(live+history)
    result=dict(previous);result.update(state=deepcopy(state),payload=deepcopy(payload["rough"]),finish_payload=deepcopy(payload["finish"]),
        pin=pin,pins=live,lineage_pins=history,fixed_pins=fixed,active_own_pins=own,active_continuation_pins=own,
        checkpoint_action=action,source_sha256=state["saved_file_sha256"],historical_only=not check_current_source,
        resolved_failed_receipt_pin=previous["failed_pin"])
    return result


class RecoveryCLContext:
    """Existing machine export core with a separate recovered checkpoint authority."""
    def __init__(self,loaded,args,project_root,sw,typelib_path):
        self.loaded,self.args,self.project_root=loaded,args,project_root
        self.report=_report("export_cl",loaded,"recover_readonly",args);self.claimed=False
        self.ctx=FinishContinuationContext(loaded,dict(args),sw,typelib_path,None,lambda:None)
        self.observation_path=Path(args["receipt_path"]).with_suffix(".observations.json")
        self.observations=[]
    def report_fields(self):return deepcopy(self.report)
    def identity(self,sw):return self.ctx.identity()
    def validate(self,**request):
        _preflight(self.report,self.loaded,self.args)
        require(request["action"]=="apply" and request["acknowledge_machine_scope"] is True,"Explicit machine export required")
        require(not self.observation_path.exists() and not self.observation_path.is_symlink(),"Fresh observation diagnostics required")
        validate_project_output(request["output_path"],self.project_root,request["receipt_path"],self.args["expected_document_path"],self.loaded["pins"])
    def selected(self,state,*ignored):return selected(state,self.args,generated=True)
    def verify_before(self,snapshot):require(snapshot["mill_state"]==self.loaded["state"],"Recovered state changed")
    def capture(self,sw,clsid,typelib_path,app,check,diagnostic):
        self.ctx.app,self.ctx.events=app,check
        result=capture_finish_recipe_batch(self.ctx,self.loaded["state"],holder_recipe=self.loaded["holder_recipe"],diagnostic=diagnostic)
        state,payload=result["state"],_capture_payload(result)
        diagnostic.update(observed_context=deepcopy(state),observed_payload=deepcopy(payload))
        # The unchanged export core creates its main receipt only after two reads.
        # This duplicate diagnostic survives an assertion/process failure; loaders
        # use only the completed main receipt, never this auxiliary file.
        self.observations.append(deepcopy(diagnostic))
        _write_receipt(self.observation_path,dict(authoritative_checkpoint=False,observations=self.observations),create=len(self.observations)==1)
        require(state==self.loaded["state"] and payload==_payload(self.loaded),"Recovered CL profile/settings changed")
        diagnostic["finish_current_checkpoint_match_verified"]=True
        return state,result["native"]
    def claim(self,report):
        self.ctx.files();_write_receipt(self.report["marker_path"],marker_state(report),create=True);self.claimed=True
    def persist(self,report):
        if self.claimed:_write_receipt(self.report["marker_path"],marker_state(report))


def export_cl(sw,clsid,typelib_path,*,checkpoint_receipt_path,checkpoint_receipt_sha256,project_root,output_path,acknowledge_machine_scope,**args):
    from scripts.sw_cam_mill_generic_cl import export_mill_generic_cl
    loaded=load_completed_recovery(checkpoint_receipt_path,checkpoint_receipt_sha256,action="recover_readonly",**args)
    context=RecoveryCLContext(loaded,args,project_root,sw,typelib_path)
    report=export_mill_generic_cl(sw,clsid,typelib_path,
        **{k:args[k] for k in ("process_id","expected_document_path","expected_source_sha256","qualification_only","acknowledge_disposable_copy","message_policy","receipt_path")},
        expected_feature_native_id=args["target_feature_native_id"],expected_operation_native_id=args["finish_operation_native_id"],
        expected_mill_operation_type=1,expected_toolpath_record_counts=[74],expected_ungenerated_operation_ids=[143,144,195,196],
        expected_generated_operations=[dict(operation_native_id=args["target_operation_native_id"],toolpath_record_counts=[191]),
            dict(operation_native_id=args["finish_operation_native_id"],toolpath_record_counts=[74])],
        action="apply",acknowledge_machine_scope=acknowledge_machine_scope,output_path=output_path,_context_adapter=context)
    if report.get("phase")=="finished" and report.get("readback_verified") is True and report.get("output_verified") is True:
        try:
            context.ctx.files();report["after_cleanup_document"]=context.ctx.identity()
            require(report["after_cleanup_document"]==loaded["state"]["document"],"CL cleanup changed")
            _finished(report,loaded["state"],_payload(loaded))
        except Exception as exc:
            report.update(status="uncertain",failed_phase="recovery_export_finalize",issue=_error(exc),readback_verified=False)
        # Only this successful core invocation owns the existing main receipt.
        require(context.claimed,"Completed core must own its durable attempt marker")
        context.persist(report)
        _write_receipt(args["receipt_path"],report)
    return report


def save(sw,clsid,typelib_path,*,checkpoint_receipt_path,checkpoint_receipt_sha256,**args):
    from scripts.sw_cam_events import CamMessageSession
    from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
    loaded=load_completed_recovery(checkpoint_receipt_path,checkpoint_receipt_sha256,action="export_cl",**args)
    report=_report("save",loaded,"export_cl",args);_preflight(report,loaded,args)
    created=claimed=False;session=ctx=save_app=None;state_after=payload_after=None;start=monotonic()
    def persist():
        report["elapsed_seconds"]=monotonic()-start
        if created:
            if claimed:_write_receipt(report["marker_path"],marker_state(report))
            _write_receipt(args["receipt_path"],report)
    def claim():
        nonlocal claimed
        _write_receipt(report["marker_path"],marker_state(report),create=True);claimed=True
    def events():_events(session,report)
    def boundary():ctx.files();events();ctx.identity()
    def capture(label):
        nonlocal state_after,payload_after,save_app
        boundary();report["phase"]=label+"_capture";diag=dict(phase=label);report["snapshot_diagnostics"].append(diag);persist()
        result=capture_finish_recipe_batch(ctx,loaded["state"],holder_recipe=loaded["holder_recipe"],diagnostic=diag)
        state,payload=result["state"],_capture_payload(result)
        report[label+"_context"]=deepcopy(state);report[label+"_payload"]=deepcopy(payload)
        diag.update(observed_context=deepcopy(state),observed_payload=deepcopy(payload));persist()
        require(payload==_payload(loaded),"Protected recovered Save payload changed")
        if label=="before":require(state==loaded["state"],"Recovered Save state changed")
        else:verify_save_delta(loaded["state"],state,args,report["saved_file_sha256"])
        state_after,payload_after=state,payload
        with ctx.guard() as guard:save_app=guard.typed(ctx.app,"ICWApp")
        normalized=deepcopy(state);normalized["document"]["needs_save"]=loaded["state"]["document"]["needs_save"]
        normalized["saved_file_sha256"]=loaded["state"]["saved_file_sha256"]
        return dict(context=normalized,**deepcopy(payload))
    def saved_hash():
        require(report.get("native_call_returned") is True and report.get("save_pending") is False
            and report.get("native_return_type")=="int" and type(report.get("native_return_value")) is int and report["native_return_value"]==0,"No source transition before strict Save return")
        events();ctx.files();ctx.owned();doc=raw_part_identity(sw)
        expected=deepcopy(ctx.expected_document);expected["needs_save"]=False
        require(doc==expected,"Save must leave exact clean document")
        sha=_file_hash(args["expected_document_path"]);ctx.args=dict(ctx.args,expected_source_sha256=sha)
        ctx.expected_document=deepcopy(doc);ctx.allow_dirty_transition=False
        report["source_transition"]=dict(source_before_sha256=args["expected_source_sha256"],source_after_sha256=sha,strict_native_save_return=0,clean_document=doc)
        ctx.identity();return sha
    try:
        _write_receipt(args["receipt_path"],report,create=True);created=True
        ctx=FinishContinuationContext(loaded,dict(args),sw,typelib_path,None,events);ctx.identity()
        ctx.app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"]);ctx.identity()
        session=CamMessageSession(ctx.app,typelib_path)
        with session:
            expected=dict(context=deepcopy(loaded["state"]),**_payload(loaded))
            def verify(value):require(value==expected,"Recovered Save normalized snapshot changed")
            def native_save():boundary();return _member(save_app,"SaveActiveDocument")
            run_one_existing_save(report,capture=capture,verify=verify,guard=boundary,claim=claim,persist=persist,save=native_save,saved_hash=saved_hash)
        _events(session,report,False);ctx.files();report["after_cleanup_document"]=ctx.identity()
        require(report["after_cleanup_document"]==state_after["document"],"Save cleanup changed")
        report["model_saved"]=True;_finished(report,state_after,payload_after)
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False,model_saved=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        persist()
    return report


COMMON={"process_id","expected_document_path","expected_source_sha256",*IDS,"qualification_only",
    "acknowledge_disposable_copy","software_only_experiment","message_policy","receipt_path","addin_clsid","module_sha256"}
EXTRA={"recover_readonly":{"failed_receipt_path","failed_receipt_sha256"},
    "export_cl":{"checkpoint_receipt_path","checkpoint_receipt_sha256","project_root","output_path","acknowledge_machine_scope"},
    "save":{"checkpoint_receipt_path","checkpoint_receipt_sha256"}}


def validate_request(request):
    require(type(request) is dict and set(request)=={"action","params"},"Exact action/params request required")
    action=request["action"];params=request["params"]
    require(type(action) is str and action in SCOPES,"Only recover_readonly, export_cl and save actions supported")
    require(type(params) is dict and set(params)==COMMON|EXTRA[action],"Exact fixed action parameters required")
    require(type(params["process_id"]) is int and params["process_id"]>0,"Explicit existing PID required")
    for name in IDS:require(type(params[name]) is int and 0<params[name]<2**32,"Strict native IDs required")
    for name,value in params.items():
        if name.endswith("sha256"):require(type(value) is str and re.fullmatch("[0-9a-f]{64}",value),"Exact SHA256 required")
        if name.endswith("path") or name=="project_root":require(type(value) is str and Path(value).is_absolute(),"Absolute input/output paths required")
    require(params["module_sha256"]==_self_pin()["sha256"],"Native recovery module hash differs")
    require(params["qualification_only"] is True and params["acknowledge_disposable_copy"] is True
        and params["software_only_experiment"] is True and params["message_policy"]=="vendor_default","Explicit qualification acknowledgements required")
    require(type(params["addin_clsid"]) is str and re.fullmatch(r"\{[0-9A-Fa-f-]{36}\}",params["addin_clsid"]),"Exact add-in CLSID required")
    if action=="export_cl":require(params["acknowledge_machine_scope"] is True,"Machine scope acknowledgement required")
    return action,dict(params)


def dispatch_request(request):
    """Fixed native dispatcher: exact existing PID, shared operation lock, no start."""
    action,params=validate_request(request)
    # Validate all receipt/runtime/ownership evidence before connecting to any app.
    args={k:v for k,v in params.items() if k not in {"addin_clsid","module_sha256"}|EXTRA[action]}
    if action=="recover_readonly":load_failed_gtp(params["failed_receipt_path"],params["failed_receipt_sha256"],**args)
    else:load_completed_recovery(params["checkpoint_receipt_path"],params["checkpoint_receipt_sha256"],action="recover_readonly" if action=="export_cl" else "export_cl",**args)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=params["process_id"]):
        inventory=discover_cam_installations();require(not inventory["errors"],"CAM installation discovery errors")
        registration=select_registration(inventory,params.pop("addin_clsid"));params.pop("module_sha256")
        sw,_=connect_solidworks(process_id=params["process_id"],launch_new_instance=False,wait_seconds=1)
        require(type(_member(sw,"GetProcessID")) is int and _member(sw,"GetProcessID")==params["process_id"],"Connected process mismatch")
        return {"recover_readonly":recover_readonly,"export_cl":export_cl,"save":save}[action](sw,registration["clsid"],
            typelib_path=str(Path(registration["addin_path"]).parent/"camworks.tlb"),**params)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description="Fixed finish recovery native actions")
    parser.add_argument("--request",required=True);parser.add_argument("--result",required=True)
    values=parser.parse_args(argv);request_path,result_path=Path(values.request),Path(values.result)
    require(request_path.is_absolute() and request_path.is_file() and request_path.stat().st_size<=65536,"Bounded absolute JSON request required")
    require(result_path.is_absolute() and result_path.suffix.lower()==".json" and result_path.parent.is_dir()
        and not result_path.exists() and not result_path.is_symlink(),"Fresh absolute result JSON required")
    try:
        request=json.loads(request_path.read_text(encoding="utf-8"));action,params=validate_request(request)
        require(str(result_path.resolve()).casefold() not in {str(Path(v).resolve()).casefold() for k,v in params.items() if k.endswith("path")},"Result/input/output overlap")
        result=dispatch_request(request)
    except Exception as exc:result=dict(status="error",issue=_error(exc),native_action_replayed=False)
    _write_receipt(result_path,result,create=True)
    print(json.dumps(dict(status=result.get("status"),phase=result.get("phase"),readback_verified=result.get("readback_verified"),result_path=str(result_path)),ensure_ascii=False))
    return 0 if result.get("readback_verified") is True else 2


if __name__=="__main__":raise SystemExit(main())
