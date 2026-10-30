"""Immutable prior-candidate checks reused from the reviewed observer preflight.

Fresh export-output and dispatch-marker gates remain with the observer; this
loader neither creates output nor authorizes creation or replay.
"""
from copy import deepcopy
from scripts.sw_cam_existing_sandvik import (
    validate_inventory_request, PHASE1_SHA, WRITER_SHA, PRIOR_SCOPE, BINDING_KEYS,
    _file_hash, read_pin, clean_events, check_document_target,
    load_saved_plan_tools_evidence, load_firstcut_receipt, load_candidate_contract,
    read_holder_recipe, field_equal, FIELDS, profile_observation, attempt_marker, export_marker, SCOPE)

READ_MODE="STRONG_PER_GETTER_AFTER_READONLY_BINDING_STOP"

def load_existing_candidate_evidence(*,phase1_receipt_path,phase1_receipt_sha256,
        expected_candidate_tool_native_id,phase1_backend_path,phase1_backend_sha256,
        profile_validator_path,profile_validator_sha256,**args):
    validate_inventory_request(**{k:args[k] for k in ("process_id","expected_document_path",
        "expected_source_sha256","qualification_only","acknowledge_disposable_copy","receipt_path","message_policy")})
    new_id=expected_candidate_tool_native_id
    if type(new_id) is not int or not 0<new_id<2**32:raise ValueError("Strict existing candidate ID required")
    implementation=[dict(path=phase1_backend_path,sha256=phase1_backend_sha256),
                    dict(path=profile_validator_path,sha256=profile_validator_sha256)]
    if [p["sha256"] for p in implementation]!=[PHASE1_SHA,WRITER_SHA]:
        raise ValueError("Exact reviewed failed implementation pins required")
    for p in implementation:
        if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Failed implementation source changed")
    data,pin=read_pin(phase1_receipt_path,phase1_receipt_sha256)
    if (data.get("scope")!=PRIOR_SCOPE or data.get("status")!="uncertain" or data.get("phase")!="finished"
        or data.get("failed_phase")!="SetFilePathForUserDefinedHolder"
        or data.get("native_dispatch_pending") is not False or data.get("readback_verified") is not False
        or type(data.get("new_tool_native_id")) is not int or data["new_tool_native_id"]!=new_id):
        raise ValueError("Only the exact completed profile-review stop is supported")
    issue=data.get("issue",{})
    if issue.get("type")!="ValueError" or issue.get("locations")!=[
        dict(file="sw_cam_sandvik_phase1.py",function="qualify_sandvik_ud14",line=450),
        dict(file="sw_cam_sandvik_mt.py",function="validate_native_profiles",line=172)]:
        raise ValueError("Different or unknown failure cannot authorize export continuation")
    for k in ("operation_assignment_attempted","GTP_attempted","GOP_attempted","AFR_attempted",
              "simulation_attempted","model_saved","save_attempted","TechDB_write_attempted",
              "automatic_replay","automatic_rollback","post_cleanup_CAM_getters",
              "units_verified","physical_tool_qualified","cutting_partition_verified","production_qualified"):
        if data.get(k) is not False:raise ValueError("Unexpected prior flag: "+k)
    if "receipt_write_error" in data or data.get("exports") or data.get("after"):
        raise ValueError("Prior exports, post-state or publication failure is outside this continuation")
    clean_events(data)
    bound=data["request_binding"]
    for key in BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256"):
        if type(bound.get(key)) is not type(args[key]) or bound[key]!=args[key]:
            raise ValueError("Prior binding differs: "+key)
    if data.get("process_id")!=args["process_id"] or data.get("source_before_sha256")!=args["expected_source_sha256"]:
        raise ValueError("Prior process/source differs")
    check_document_target(data.get("expected_document_path"),None,expected_path=args["expected_document_path"],required=True)
    anchor=load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],args["saved_plan_receipt_sha256"],
                                         **{k:args[k] for k in BINDING_KEYS})
    if (anchor.data.get("scope")!="MILL_ADDED_CIRCULAR_POCKET_PLAN_V1" or data["anchor"]!=anchor.summary()
        or len(anchor.state["features"])!=19 or len(anchor.state["operations"])!=6):
        raise ValueError("Exact nineteen-feature six-definition source required")
    if any(o["toolpath_generated"] is not False or o["toolpath_record_counts"]!=[] for o in anchor.state["operations"]):
        raise ValueError("Only zero-path plan supported")
    before=deepcopy(data["before"]);before["document"]["needs_save"]=anchor.state["document"]["needs_save"]
    anchor.verify(before)
    rough=[o for o in anchor.data["new_operations"] if o["mill_operation_type"]==0]
    if len(rough)!=1:raise ValueError("One exact added rough definition required")
    firstpin=dict(path=bound["firstcut_receipt_path"],sha256=bound["firstcut_receipt_sha256"])
    first=load_firstcut_receipt(firstpin["path"],firstpin["sha256"],process_id=args["process_id"],
        expected_document_path=args["expected_document_path"],expected_source_sha256=args["expected_source_sha256"],
        target_feature_native_id=anchor.data["new_feature_native_id"],target_operation_native_id=rough[0]["native_id"],
        target_operation_setup_native_id=rough[0]["setup_native_id"])
    if data["before_document"]!=first["after_document"]:raise ValueError("Original document differs from firstcut checkpoint")
    if data["firstcut_anchor"]!=dict(pin=firstpin,after_settings=first["after_settings"]) or data["before_firstcut"]!=first["after_settings"]:
        raise ValueError("Verified firstcut0 state differs")
    cp=data["candidate_contract"]["pins"]
    if len(cp)!=4:raise ValueError("Four candidate asset pins required")
    candidate=load_candidate_contract(*(v for p in cp for v in (p["path"],p["sha256"])))
    hp=data["holder_recipe"]["pins"]
    if len(hp)!=2:raise ValueError("Holder recipe and vendor file required")
    holder=read_holder_recipe(*(v for p in hp for v in (p["path"],p["sha256"])))
    if candidate!=data["candidate_contract"] or holder!=data["holder_recipe"]:
        raise ValueError("Pinned candidate/holder contract differs")
    tool=data["tool"]
    if (tool.get("native_id")!=new_id or tool.get("tool_type_raw")!=14 or tool.get("profile_complete") is not True
        or any(not field_equal(k,tool["parameters"][k],v) for k,v in FIELDS)):
        raise ValueError("Exact prior coherent existing tool observation required")
    check_document_target(tool["mt_path_raw"],None,expected_path=data["candidate_asset"]["path"],required=True)
    observation=profile_observation(candidate,tool["profiles"])
    dispatches=data["dispatches"];labels=[d.get("label") for d in dispatches]
    expected=["AddNewTool3","SetToolName"]+["property:"+r["property"] for r in data["field_attempts"]
              if r["setter_attempted"]]+["SetFilePathForUserDefinedHolder"]
    if labels!=expected or len(data["field_attempts"])!=9:
        raise ValueError("Exact completed creation/configuration history required")
    for d in dispatches:
        if d.get("attempted") is not True or d.get("returned") is not True or d.get("pending") is not False:
            raise ValueError("Unknown native dispatch outcome blocks continuation")
        if d["label"] in ("SetToolName","SetFilePathForUserDefinedHolder") and (
            d.get("return_type")!="int" or type(d.get("return_value")) is not int or d["return_value"]!=0):
            raise ValueError("Prior loader/holder HRESULT was not strict zero")
    if ([r["property"] for r in data["field_attempts"]]!=[k for k,v in FIELDS]
        or any(r.get("readback_verified") is not True for r in data["field_attempts"])):
        raise ValueError("All nine field readbacks required")
    creation=attempt_marker(args["expected_document_path"],args["expected_source_sha256"],data["candidate_asset"]["sha256"])
    check_document_target(data["dispatch_marker_path"],None,expected_path=str(creation),required=True)
    marker_data,creation_pin=read_pin(str(creation),_file_hash(creation))
    if (marker_data.get("scope")!=PRIOR_SCOPE or marker_data.get("status")!="uncertain"
        or marker_data.get("phase")!="finished" or marker_data.get("native_dispatch_pending") is not False
        or marker_data.get("new_tool_native_id")!=new_id or marker_data.get("dispatches")!=dispatches
        or marker_data.get("candidate_sha256")!=data["candidate_asset"]["sha256"]
        or marker_data.get("source_sha256")!=args["expected_source_sha256"]
        or marker_data.get("automatic_replay") is not False):
        raise ValueError("Original completed partial-result marker differs")
    check_document_target(marker_data["document"],None,expected_path=args["expected_document_path"],required=True)
    check_document_target(marker_data["receipt_path"],None,expected_path=phase1_receipt_path,required=True)
    pins=[pin,creation_pin,firstpin]+implementation+candidate["pins"]+holder["pins"]+[data["candidate_asset"]]
    for p in pins:
        if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Immutable prior asset changed")
    return dict(data=data,pin=pin,pins=pins,anchor=anchor,candidate=candidate,holder=holder,
        firstcut=first["after_settings"],rough_id=rough[0]["native_id"],creation_pin=creation_pin,
        profile_observation=observation,
        marker=export_marker(args["expected_document_path"],phase1_receipt_sha256,new_id))


def load_prior_binding_stop(loaded,*,failed_observation_receipt_path,failed_observation_receipt_sha256,
        failed_observer_backend_path,failed_observer_backend_sha256,
        failed_read_batch_backend_path,failed_read_batch_backend_sha256,**args):
    """Immutable prior failed-read lineage only; export marker is now expected to exist."""
    implementation=[
        dict(path=failed_observer_backend_path,sha256=failed_observer_backend_sha256),
        dict(path=failed_read_batch_backend_path,sha256=failed_read_batch_backend_sha256)]
    if [p["sha256"] for p in implementation]!=[
        "9746b3f1384ce5d3b65a8a724f713a597687f68ff021a6385f501f1b76548ddb",
        "670a6c544fffdb3632d8e6cc13a147b7d2a4c6426b9604732c56d2e36ee22d6e"]:
        raise ValueError("Exact failed observer and pilot implementation required")
    for p in implementation:
        if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Failed implementation changed")
    failed,pin=read_pin(failed_observation_receipt_path,failed_observation_receipt_sha256)
    if (failed.get("scope")!=SCOPE or failed.get("status")!="error" or failed.get("phase")!="finished"
        or failed.get("failed_phase")!="preflight" or failed.get("native_read_count")!=49):
        raise ValueError("Only the exact completed read-only binding stop is supported")
    for key in ("native_dispatch_pending","export_attempted","mutation_attempted","tool_creation_attempted",
        "MT_load_attempted","field_setter_attempted","holder_setter_attempted","operation_assignment_attempted",
        "GTP_attempted","GOP_attempted","AFR_attempted","simulation_attempted","model_saved","save_attempted",
        "TechDB_write_attempted","automatic_replay","automatic_rollback","readback_verified",
        "numeric_profile_verified","physical_tool_qualified","units_verified","cutting_partition_verified",
        "production_qualified","may_continue","raw_exports_pinned","exports_verified","post_cleanup_CAM_getters"):
        if failed.get(key) is not False:raise ValueError("Unexpected failed observation flag: "+key)
    if (failed.get("dispatches")!=[] or failed.get("exports")!={}
        or any(key in failed for key in ("before_candidate","after_candidate","after","receipt_write_error"))):
        raise ValueError("Prior export, candidate result or uncertain receipt blocks continuation")
    issue=failed.get("issue",{})
    if issue.get("type")!="ValueError" or issue.get("locations")!=[
        dict(file="sw_cam_read_batch_guard.py",function="boundary",line=83),
        dict(file="sw_cam_read_batch_guard.py",function="_timed",line=70),
        dict(file="sw_cam_existing_sandvik.py",function="binding",line=319)]:
        raise ValueError("Different failure cannot authorize strong-reader fallback")
    batches=failed.get("read_batch_diagnostics")
    if not isinstance(batches,list) or len(batches)!=1:raise ValueError("Exact failed read-batch boundary required")
    batch=batches[0]
    if (batch.get("scope")!="BOUNDED_CAM_READ_BATCH_V1" or batch.get("active") is not False
        or batch.get("invalid") is not True or batch.get("claimed") is not False
        or batch.get("native_call_attempted") is not False or batch.get("native_call_returned") is not False
        or batch.get("read_scope_complete") is not False
        or type(batch.get("getter_calls")) is not int or batch["getter_calls"]!=0
        or type(batch.get("query_interface_calls")) is not int or batch["query_interface_calls"]!=0):
        raise ValueError("Candidate reads or dispatch may have started in failed batch")
    clean_events(failed)
    expected_binding={k:args[k] for k in BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")}
    if failed.get("request_binding")!=expected_binding:raise ValueError("Failed observer request binding differs")
    if (type(failed.get("process_id")) is not int or failed["process_id"]!=args["process_id"]
        or type(failed.get("tool_native_id")) is not int or failed["tool_native_id"]!=args["expected_candidate_tool_native_id"]
        or failed.get("source_before_sha256")!=args["expected_source_sha256"]
        or failed.get("expected_source_sha256")!=args["expected_source_sha256"]
        or failed.get("before_document")!=loaded["data"]["before_document"]
        or failed.get("prior_receipt_pin")!=loaded["pin"]
        or failed.get("prior_creation_marker_pin")!=loaded["creation_pin"]
        or failed.get("anchor")!=loaded["anchor"].summary()
        or failed.get("profile_observation")!=loaded["profile_observation"]):
        raise ValueError("Failed observer lineage differs from the frozen existing candidate")
    check_document_target(failed["expected_document_path"],None,expected_path=args["expected_document_path"],required=True)
    check_document_target(failed["dispatch_marker_path"],None,expected_path=str(loaded["marker"]),required=True)
    if _file_hash(args["expected_document_path"])!=args["expected_source_sha256"]:
        raise ValueError("Saved source differs after read-only failure")
    loaded["pins"]+=implementation+[pin]
    loaded["readonly_binding_stop"]=dict(receipt_pin=pin,implementation_pins=implementation,
        no_export_attempt_verified=True,read_mode=READ_MODE,
        original_export_marker=str(loaded["marker"]),new_export_identity_created=False)
    return loaded
