"""Read one completed observation for a draft Save; no dispatch gate is reopened."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_sandvik_phase1 import BINDING_KEYS
from scripts.sw_cam_existing_sandvik import PHASE1_SHA,WRITER_SHA,export_marker,raw_export_pin,profile_observation
from scripts.sw_cam_existing_sandvik_evidence import load_existing_candidate_evidence
from scripts.sw_cam_completed_holder_cas import load_completed_holder_cas
from scripts.sw_cam_complete_sandvik_observation import SCOPE as OBSERVATION_SCOPE,READ_MODE
from scripts.sw_cam_noncutting_continuation import SCOPE as NONCUT_SCOPE,noncutting_marker,hresult_observation
from scripts.sw_cam_sandvik_save import save_marker,verify_context
from scripts.sw_cam_compound_plan_evidence import verify_protected_details
from scripts.sw_cam_ud14_probe_core import verify_one_new_tool
from scripts.sw_cam_holder_observation import observe_holder_nominal
from scripts.sw_operation_guard import check_document_target

TRUE_FLAGS=("readback_verified","draft_save_eligible","protected_context_unchanged","holder_profile_observed",
    "holder_profile_verified","holder_readback_stable","raw_exports_pinned","export_attempted","classification_pending")
FALSE_FLAGS=("native_dispatch_pending","cutting_export_attempted","mutation_attempted","tool_creation_attempted",
    "MT_load_attempted","field_setter_attempted","holder_setter_attempted","operation_assignment_attempted",
    "GTP_attempted","GOP_attempted","AFR_attempted","simulation_attempted","model_saved","save_attempted",
    "TechDB_write_attempted","automatic_replay","automatic_rollback","post_cleanup_CAM_getters",
    "physical_tool_qualified","units_verified","cutting_partition_verified","production_qualified",
    "numeric_profile_verified","may_continue","exports_verified")

def same_path(value,expected):
    check_document_target(value,None,expected_path=str(expected),required=True)


def completed_export_evidence(data,prior,args):
    """Consume finished cutting/noncutting markers; never call the fresh-export loader."""
    cp=data["completed_cutting_receipt_pin"]
    cut,cp_actual=read_pin(cp["path"],cp["sha256"])
    if cp_actual!=cp:raise ValueError("Original cutting receipt pin differs")
    original=export_marker(args["expected_document_path"],prior["pin"]["sha256"],args["expected_candidate_tool_native_id"])
    mp=data["original_export_marker_pin"]
    same_path(mp["path"],original)
    mark,mp_actual=read_pin(mp["path"],mp["sha256"])
    if mp_actual!=mp:raise ValueError("Original marker pin differs")
    row=cut["dispatches"]
    if len(row)!=1:raise ValueError("One original cutting call required")
    row=row[0]
    if (row.get("label")!="CreateSTLOfCuttingPortion" or row.get("attempted") is not True
        or row.get("returned") is not True or row.get("pending") is not False
        or row.get("return_type")!="int" or type(row.get("return_value")) is not int or row["return_value"]!=1):
        raise ValueError("Exact completed cutting S_FALSE observation required")
    if (cut.get("prior_receipt_pin")!=prior["pin"] or cut.get("prior_creation_marker_pin")!=prior["creation_pin"]
        or cut.get("process_id")!=args["process_id"] or cut.get("tool_native_id")!=args["expected_candidate_tool_native_id"]
        or cut.get("source_before_sha256")!=args["expected_source_sha256"]
        or cut.get("status")!="uncertain" or cut.get("phase")!="finished"
        or cut.get("native_dispatch_pending") is not False):raise ValueError("Original cutting lineage differs")
    clean_events(cut)
    same_path(mark.get("receipt_path"),cp["path"])
    same_path(mark.get("document"),args["expected_document_path"])
    if (mark.get("status")!="uncertain" or mark.get("phase")!="finished" or mark.get("native_dispatch_pending") is not False
        or mark.get("dispatches")!=[row] or mark.get("exports")!={}
        or mark.get("phase1_receipt_sha256")!=prior["pin"]["sha256"]
        or mark.get("tool_native_id")!=args["expected_candidate_tool_native_id"]
        or mark.get("source_sha256")!=args["expected_source_sha256"] or mark.get("automatic_replay") is not False):
        raise ValueError("Original completed cutting marker differs")
    cutting=raw_export_pin(row["path"])
    expected=dict(pin=cutting,reused=True,source_receipt_pin=cp,hresult=hresult_observation(1),
        source_holder_context="R84c before holder mode CAS",applicability_to_current_holder_verified=False,
        classification_pending=True,physical_tool_qualified=False,units_verified=False)
    if data["exports"]["cutting"]!=expected:raise ValueError("Historical cutting provenance differs")
    path=noncutting_marker(original);same_path(data["dispatch_marker_path"],path)
    noncut,np=read_pin(str(path),_file_hash(path))
    if noncut!=data["noncutting_continuation"]:raise ValueError("Completed noncutting marker differs")
    if (noncut.get("scope")!=NONCUT_SCOPE or noncut.get("status")!="export_observed" or noncut.get("phase")!="finished"
        or noncut.get("raw_file_observed") is not True or noncut.get("native_dispatch_pending") is not False
        or noncut.get("original_marker_pin")!=mp or noncut.get("prior_receipt_pin")!=cp or noncut.get("cutting_pin")!=cutting
        or noncut.get("tool_native_id")!=args["expected_candidate_tool_native_id"]
        or noncut.get("process_id")!=args["process_id"] or noncut.get("expected_source_sha256")!=args["expected_source_sha256"]):
        raise ValueError("Complete noncutting observation required")
    for key in ("automatic_replay","cutting_export_attempted","units_verified","physical_tool_qualified","production_qualified",
                "cutting_applicability_to_current_holder_verified","protected_context_unchanged","readback_verified","may_continue"):
        if noncut.get(key) is not False:raise ValueError("Unexpected noncutting flag: "+key)
    if "issue" in noncut:raise ValueError("Noncutting result failed")
    same_path(noncut["expected_document_path"],args["expected_document_path"])
    d=noncut["dispatch"]
    if (d.get("label")!="CreateSTLOfNonCuttingPortion" or d.get("attempted") is not True
        or d.get("returned") is not True or d.get("pending") is not False or d.get("return_type")!="int"
        or data.get("dispatches")!=[d]):raise ValueError("One completed missing noncutting call required")
    hr=hresult_observation(d["return_value"])
    if not hr["success_severity"] or noncut.get("hresult")!=hr:raise ValueError("Noncutting HRESULT differs")
    raw=raw_export_pin(d["path"])
    if (not raw["bytes"] or raw!=noncut["noncutting_pin"] or noncut["analysis"].get("pin")!=raw
        or data["exports"]["noncutting"]!=noncut["analysis"]):raise ValueError("Noncutting bytes differ")
    pins=prior["pins"]+[cp,mp,cutting,np,raw]
    return dict(prior_receipt_pin=cp,original_marker_pin=mp,tool_native_id=args["expected_candidate_tool_native_id"],
        process_id=args["process_id"],expected_source_sha256=args["expected_source_sha256"],immutable_pins=pins,
        noncutting_marker_pin=np)


def load_completed_for_save(*,observation_receipt_path,observation_receipt_sha256,expected_candidate_tool_native_id,**args):
    validate_inventory_request(**{k:args[k] for k in ("process_id","expected_document_path","expected_source_sha256",
        "qualification_only","acknowledge_disposable_copy","receipt_path","message_policy")})
    new_id=expected_candidate_tool_native_id
    if type(new_id) is not int or not 0<new_id<2**32:raise ValueError("Strict candidate ID required")
    data,pin=read_pin(observation_receipt_path,observation_receipt_sha256)
    if (data.get("scope")!=OBSERVATION_SCOPE or data.get("read_mode")!=READ_MODE or data.get("status")!="review_required"
        or data.get("phase")!="finished" or type(data.get("tool_native_id")) is not int or data["tool_native_id"]!=new_id):
        raise ValueError("Completed exact observation required")
    for key in TRUE_FLAGS:
        if data.get(key) is not True:raise ValueError("Incomplete observation: "+key)
    for key in FALSE_FLAGS:
        if data.get(key) is not False:raise ValueError("Unexpected observation flag: "+key)
    if any(k in data for k in ("issue","failed_phase","receipt_write_error")):raise ValueError("Failed observation cannot authorize Save")
    clean_events(data)
    binding={k:args[k] for k in BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")}
    if any(type(data.get("request_binding",{}).get(k)) is not type(v) or data["request_binding"][k]!=v for k,v in binding.items()):
        raise ValueError("Exact request binding differs")
    if (type(data.get("process_id")) is not int or data["process_id"]!=args["process_id"]
        or data.get("source_before_sha256")!=args["expected_source_sha256"]
        or data.get("expected_source_sha256")!=args["expected_source_sha256"]):raise ValueError("Process/source differs")
    same_path(data["expected_document_path"],args["expected_document_path"])
    def implementation(sha):
        rows=[p for p in data["evidence_pins"] if p.get("sha256")==sha]
        if len(rows)!=1:raise ValueError("Exact prior implementation pin required")
        return rows[0]
    phase=implementation(PHASE1_SHA);writer=implementation(WRITER_SHA);pp=data["prior_receipt_pin"]
    loaded=load_existing_candidate_evidence(phase1_receipt_path=pp["path"],phase1_receipt_sha256=pp["sha256"],
        expected_candidate_tool_native_id=new_id,phase1_backend_path=phase["path"],phase1_backend_sha256=phase["sha256"],
        profile_validator_path=writer["path"],profile_validator_sha256=writer["sha256"],**args)
    prior=loaded["data"];anchor=loaded["anchor"]
    all_args=dict(args,expected_candidate_tool_native_id=new_id)
    cutting=completed_export_evidence(data,loaded,all_args)
    sp=data["holder_shape_pin"]
    shape=load_completed_holder_cas(loaded,cutting,holder_shape_receipt_path=sp["path"],holder_shape_receipt_sha256=sp["sha256"],**all_args)
    if (data["prior_receipt_pin"]!=loaded["pin"] or data["prior_creation_marker_pin"]!=loaded["creation_pin"]
        or data["holder_shape_marker_pin"]!=shape["marker_pin"] or data["anchor"]!=anchor.summary()
        or data["candidate_contract"]!=loaded["candidate"] or data["holder_recipe"]!=loaded["holder"]):
        raise ValueError("Completed observation ancestry differs")
    if (data["before_reference"]!=dict(pin=loaded["pin"],field="before",fresh_full_snapshot=False,subsequent_holder_shape_pin=sp)
        or data["before_document"]!=shape["after_document"] or data["after_document"]!=data["before_document"]
        or data["after_document"]!=data["after"]["document"] or data["after"]["saved_file_sha256"]!=args["expected_source_sha256"]):
        raise ValueError("Document/reference state differs")
    verify_context(prior["before"],data["after"])
    normalized=deepcopy(data["after"]);normalized["document"]["needs_save"]=anchor.state["document"]["needs_save"]
    anchor.verify(normalized)
    diags=data["snapshot_diagnostics"]
    if type(diags) is not list or len(diags)!=1 or diags[0].get("phase")!="after" or diags[0].get("capture_complete") is not True:
        raise ValueError("One complete fresh protected after required")
    details=diags[0]["operation_details"];verify_protected_details(anchor,data["after"],details)
    if any(details[k]!=anchor.data["saved_details"][k] for k in ("three_step_profile","strategy")):raise ValueError("Protected strategy differs")
    guards=data["guard_diagnostics"]
    if not guards or any(g.get("invalid") is not False for g in guards):raise ValueError("Invalid native read guard")
    dispatched=[g for g in guards if g.get("native_call_attempted") is True]
    if len(dispatched)!=1 or dispatched[0].get("native_call_returned") is not True or dispatched[0].get("claimed") is not True:
        raise ValueError("Exactly one guarded noncutting dispatch required")
    c=data["after_candidate"]
    if (c!=data["before_candidate"] or c["tool"]!=prior["tool"] or c["firstcut"]!=loaded["firstcut"]
        or c["metric_scope"]!=prior["metric_scope"] or c["holder_fields"]!=shape["holder_snapshot"]
        or c["holder_profile"]!=shape["holder_profile"]):raise ValueError("Complete stable candidate differs")
    verify_one_new_tool(prior["before_tools"],c["local_tools"],new_id)
    if profile_observation(loaded["candidate"],c["tool"]["profiles"])!=c["profile_observation"] or c["profile_observation"]!=data["profile_observation"]:
        raise ValueError("Tool profile observation differs")
    hv=observe_holder_nominal(c["holder_profile"],loaded["holder"],25)
    if hv!=shape["holder_verification"] or hv!=c["holder_verification"]:raise ValueError("Verified holder profile differs")
    hd=data["after_holder_diagnostic"]
    if hd.get("capture_complete") is not True or hd.get("state")!=c["holder_profile"]:raise ValueError("Incomplete holder after")
    for key in ("fresh_tool_profile","fresh_shank_profile","fresh_holder_profile","fresh_local_tool_inventory",
                "fresh_all_nine_scalars","fresh_MT_reference","fresh_holder_mode_path_protrusion","fresh_firstcut"):
        if data["after_candidate_provenance"].get(key) is not True:raise ValueError("Fresh after provenance missing")
    pins=[pin]+data["evidence_pins"]+cutting["immutable_pins"]+shape["pins"]
    unique={}
    for p in pins:
        if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Immutable save evidence changed")
        key=str(Path(p["path"]).resolve()).casefold()
        if key in unique and unique[key]["sha256"]!=p["sha256"]:raise ValueError("Conflicting evidence pin")
        unique[key]=p
    pins=list(unique.values())
    marker=save_marker(args["expected_document_path"],loaded["pin"]["sha256"],new_id)
    if marker.exists() or marker.is_symlink():raise ValueError("Prior Save exists; no replay")
    outputs=[Path(x).resolve() for x in (args["expected_document_path"],args["receipt_path"],str(marker))]
    immutable={Path(p["path"]).resolve() for p in pins+anchor.pins}
    if len(set(outputs))!=3 or set(outputs)&immutable:raise ValueError("Save output/source/evidence alias")
    reference=dict(context=data["after"],document=data["after_document"],candidate=c,
        holder_recipe=loaded["holder"],candidate_contract=loaded["candidate"])
    return dict(data=data,reference=reference,pin=pin,prior_pin=loaded["pin"],anchor=anchor,prior_data=prior,
        rough_id=loaded["rough_id"],pins=pins,creation_pin=loaded["creation_pin"],
        firstcut_anchor=prior["firstcut_anchor"],marker=marker,noncutting_marker_pin=cutting["noncutting_marker_pin"])
