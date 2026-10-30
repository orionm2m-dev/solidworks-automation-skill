"""Validated lineage for finish recipe Save, one finish GTP and machine CL."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target
from scripts.sw_cam_finish_recipe import selected_finish, load_completed_finish_recipe

SCOPES = {"gtp":"SAVED_ROUTE_FINISH_GTP_V1", "save":"SAVED_ROUTE_FINISH_SAVE_V1", "cl":"SAVED_ROUTE_FINISH_CL_V1"}
IDS = ("target_feature_native_id", "target_operation_native_id", "target_operation_setup_native_id",
    "expected_candidate_tool_native_id", "finish_operation_native_id", "finish_tool_native_id")
IMPLEMENTATION = ("sw_cam_finish_continuation_evidence.py", "sw_cam_finish_continuation.py",
    "sw_cam_mill_generic_cl.py", "sw_cam_cl_inventory.py", "sw_cam_ud14_save.py",
    "sw_cam_finish_read_batch.py")
PARENTS = {"gtp":{"save"}, "save":{"recipe","gtp","cl"}, "cl":{"gtp"}}


def implementation_paths():
    return {str(Path(__file__).resolve().with_name(name)).casefold() for name in IMPLEMENTATION}


def checked_lineage_pins(pins):
    require(type(pins) is list and len(pins) <= 16, "Bounded completed lineage required")
    canonical = canonical_evidence_pins(pins) if pins else []
    require(canonical == pins, "Canonical unique completed lineage required")
    return canonical


def advance_pin_sets(previous, implementation, own_pins):
    """Only fully validated earlier continuation outputs leave the live guard list."""
    older = previous.get("active_continuation_pins", [])
    require(type(older) is list and len(older) <= 3, "Bounded previous own outputs required")
    old_keys = {(str(Path(p["path"]).resolve()).casefold(),p["sha256"]) for p in older}
    live_keys = {(str(Path(p["path"]).resolve()).casefold(),p["sha256"]) for p in previous["pins"]}
    require(old_keys <= live_keys, "Previous completed outputs must be currently pinned")
    fixed = [p for p in previous["pins"] if (str(Path(p["path"]).resolve()).casefold(),p["sha256"]) not in old_keys]
    old_lineage = checked_lineage_pins(previous.get("lineage_pins", []))
    lineage = canonical_evidence_pins(old_lineage,older) if old_lineage or older else []
    checked_lineage_pins(lineage)
    live = canonical_evidence_pins(fixed,implementation,own_pins)
    require(not {str(Path(p["path"]).resolve()).casefold() for p in live}.intersection(
        str(Path(p["path"]).resolve()).casefold() for p in lineage), "Live/history pin overlap")
    return live,lineage


def selected(state,args,*,generated=None):
    row=selected_finish(state,args)
    counts=row["toolpath_record_counts"]
    require(type(counts) is list and len(counts)<=1 and all(type(n) is int and 0<n<=100000 for n in counts),
        "At most one positive finish path container supported")
    require(row["toolpath_generated"] is bool(counts), "Path flag/count inconsistency")
    if generated is not None: require(row["toolpath_generated"] is generated,"Unexpected finish generation state")
    ids=[r["native_id"] for r in state["operations"]]
    require(all(type(n) is int and n>0 for n in ids) and len(set(ids))==6,"Unique operation IDs required")
    rough=[r for r in state["operations"] if r["native_id"]==args["target_operation_native_id"]]
    require(len(rough)==1 and rough[0]["toolpath_generated"] is True and rough[0]["toolpath_record_counts"]==[191]
        and rough[0]["suppressed"] is False and rough[0]["assigned_tool"]["native_id"]==args["expected_candidate_tool_native_id"],
        "Protected completed 191-record rough route required")
    for sibling in state["operations"]:
        if sibling["native_id"] not in (row["native_id"],rough[0]["native_id"]):
            require(sibling["suppressed"] is False and sibling["toolpath_generated"] is False
                and sibling["toolpath_record_counts"]==[],"Four other operations must remain ungenerated")
    return row


def verify_gtp_delta(before,after,args):
    selected(before,args,generated=False); target=selected(after,args,generated=True)
    require(before["document"]["needs_save"] is False,"Explicit clean recipe save required before GTP")
    expected=deepcopy(before);row=selected(expected,args,generated=False)
    row["toolpath_generated"]=True;row["toolpath_record_counts"]=deepcopy(target["toolpath_record_counts"])
    require(type(after["document"].get("needs_save")) is bool,"Strict dirty flag required")
    expected["document"]["needs_save"]=after["document"]["needs_save"]
    require(after==expected,"Finish GTP changed protected rough, other operations, tools or source")


def verify_save_delta(before,after,args,new_sha):
    selected(before,args);selected(after,args)
    expected=deepcopy(before);expected["document"]["needs_save"]=False;expected["saved_file_sha256"]=new_sha
    require(after==expected,"Save changed more than source hash and clean flag")


def continuation_marker(document_path,action,parent_pin,operation_id):
    require(action in SCOPES,"Known finish action required")
    source=Path(document_path).resolve()
    key=_digest(dict(scope=SCOPES[action],source=str(source).casefold(),parent_sha256=parent_pin["sha256"],operation_id=operation_id))
    return source.parent/("finish_"+action+"_"+key+".json")


def marker_state(report):
    keys=("scope","action","status","phase","process_id","expected_document_path","source_before_sha256","source_after_sha256",
        "parent_checkpoint_pin","finish_operation_native_id","finish_tool_native_id","marker_path","receipt_path","readback_verified",
        "native_dispatch_pending","native_call_attempted","native_call_returned","native_return_type","native_return_value","native_hresult",
        "save_pending","save_readback_verified","saved_file_sha256","output_verified","output","GTP_call_count","GTP_returned","checkpoint_sha256")
    return {k:deepcopy(report[k]) for k in keys if k in report}


def make_checkpoint(state,payload):
    require(set(payload)=={"rough","finish"},"Exact rough/finish checkpoint payload required")
    return dict(state=deepcopy(state),payload=deepcopy(payload),source_sha256=state["saved_file_sha256"])


def load_finish_continuation(path,sha256,*,action,check_current_source=True,_depth=0,**args):
    require(type(check_current_source) is bool and type(_depth) is int and 0<=_depth<=5,"Bounded explicit checkpoint lineage required")
    if action=="recipe":
        loaded=load_completed_finish_recipe(path,sha256,check_current_source=check_current_source,**args)
        selected(loaded["state"],args,generated=False)
        require(not loaded.get("lineage_pins") and not loaded.get("active_continuation_pins"), "Recipe base may not inject continuation history")
        require(loaded["source_sha256"]==args["expected_source_sha256"],"Recipe source binding differs")
        return loaded
    require(action in SCOPES and _depth<5,"Known bounded finish continuation required")
    data,pin=read_pin(path,sha256)
    require(data.get("scope")==SCOPES[action] and data.get("action")==action
        and data.get("phase")=="finished" and data.get("status")=="review_required","Completed finish continuation required")
    require(data.get("readback_verified") is True and not any(k in data for k in ("issue","failed_phase","receipt_write_error")),"Unverified finish continuation")
    require(type(data.get("process_id")) is int and data["process_id"]==args["process_id"],"Process binding differs")
    check_document_target(data["expected_document_path"],None,expected_path=args["expected_document_path"],required=True)
    for key in IDS: require(type(data.get(key)) is int and data[key]==args[key],"Finish binding differs: "+key)
    for flag in ("automatic_retry","automatic_replay","automatic_rollback","GOP_attempted","AFR_attempted",
        "assignment_attempted","tool_edit_attempted","simulation_attempted","NC_export_attempted","production_qualified"):
        require(data.get(flag) is False,"Unexpected continuation flag: "+flag)
    require(data.get("native_call_attempted") is True and data.get("native_call_returned") is True
        and data.get("native_dispatch_pending") is False,"Completed one native action required")
    clean_events(data)
    diagnostics=data.get("snapshot_diagnostics",[])
    require(len(diagnostics)==(3 if action=="cl" else 2) and all(d.get("capture_complete") is True for d in diagnostics),"Complete bounded captures required")
    parent=data["parent_checkpoint_pin"];parent_action=data["parent_action"]
    require(parent_action in PARENTS[action],"Invalid finish action lineage")
    previous=load_finish_continuation(parent["path"],parent["sha256"],action=parent_action,check_current_source=False,
        _depth=_depth+1,**dict(args,expected_source_sha256=data["source_before_sha256"]))
    before,after=data["before_context"],data["after_context"]
    payload=dict(rough=previous["payload"],finish=previous["finish_payload"])
    require(before==previous["state"] and data["before_payload"]==payload and data["after_payload"]==payload,"Protected recipe payload changed")
    require(data["after_cleanup_document"]==after["document"],"Cleanup document differs")
    checkpoint=make_checkpoint(after,payload)
    require(data["checkpoint"]==checkpoint and data["checkpoint_sha256"]==_digest(checkpoint),"Checkpoint digest/content differs")
    require(data["source_before_sha256"]==before["saved_file_sha256"] and data["source_after_sha256"]==after["saved_file_sha256"],"Source transition differs")
    if action=="gtp":
        guard=data.get("dispatch_guard",{})
        require(guard.get("claimed") is True and guard.get("native_call_attempted") is True
            and guard.get("native_call_returned") is True and guard.get("invalid") is False,"Completed GTP dispatch guard required")
        require(type(data.get("GTP_call_count")) is int and data["GTP_call_count"]==1 and data.get("GTP_returned") is True
            and data.get("GTP_attempted") is True and data.get("save_attempted") is False and data.get("model_saved") is False,"Only one finish GTP permitted")
        verify_gtp_delta(before,after,args)
    elif action=="save":
        require(data.get("save_readback_verified") is True and data.get("model_saved") is True and data.get("save_pending") is False
            and data.get("save_attempted") is True and data.get("GTP_attempted") is False and data.get("GTP_call_count")==0,"Completed save-only action required")
        verify_save_delta(before,after,args,data["saved_file_sha256"])
    else:
        selected(after,args,generated=True)
        require(before==after and data.get("output_verified") is True and type(data.get("native_hresult")) is int and data["native_hresult"]==0
            and data.get("GTP_attempted") is False and data.get("model_saved") is False,"Unchanged CL-only export required")
        require(_file_hash(data["output"]["path"])==data["output"]["sha256"],"Exported CL changed")
    if action!="cl":
        require(data.get("native_return_type")=="int" and type(data.get("native_return_value")) is int and data["native_return_value"]==0,"Strict successful native return required")
    expected_marker=continuation_marker(args["expected_document_path"],action,parent,args["finish_operation_native_id"])
    require(Path(data["marker_path"]).resolve()==expected_marker.resolve(),"Finish marker identity differs")
    marker,mpin=read_pin(str(expected_marker),_file_hash(expected_marker))
    require(marker==marker_state(data),"Completed finish marker differs")
    implementation=data["implementation_pins"]
    require(type(implementation) is list and len(implementation)==len(IMPLEMENTATION)
        and {Path(p["path"]).name for p in implementation}==set(IMPLEMENTATION),"Exact implementation pins required")
    require({str(Path(p["path"]).resolve()).casefold() for p in implementation} == implementation_paths(), "Continuation implementation paths differ from installed modules")
    for p in implementation: require(_file_hash(p["path"])==p["sha256"],"Continuation implementation changed")
    require(data["evidence_pins"]==canonical_evidence_pins(previous["pins"],implementation),"Continuation evidence closure differs")
    require(data.get("lineage_pins",[])==checked_lineage_pins(previous.get("lineage_pins",[])),"Completed history closure differs")
    require(after["saved_file_sha256"]==args["expected_source_sha256"],"Expected saved source differs")
    if check_current_source: require(_file_hash(args["expected_document_path"])==args["expected_source_sha256"],"Current source differs")
    own_pins=canonical_evidence_pins([pin,mpin],[data["output"]] if action=="cl" else [])
    live,lineage=advance_pin_sets(previous,implementation,own_pins)
    for p in lineage: require(_file_hash(p["path"])==p["sha256"],"Completed lineage file changed")
    result=dict(previous)
    result.update(historical_only=not check_current_source,state=deepcopy(after),payload=deepcopy(payload["rough"]),
        finish_payload=deepcopy(payload["finish"]),pin=pin,checkpoint_action=action,source_sha256=after["saved_file_sha256"],
        pins=live,lineage_pins=lineage,active_continuation_pins=own_pins)
    return result
