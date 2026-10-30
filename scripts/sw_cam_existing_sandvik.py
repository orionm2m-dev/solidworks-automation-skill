"""Observe and export one existing candidate after an exact profile-review stop.

No tool creation, MT reload, field/holder assignment, Save, GTP or retry exists.
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

SCOPE="EXISTING_SANDVIK_PROFILE_OBSERVATION_EXPORT_V1"
READ_MODE="STRONG_PER_GETTER_AFTER_READONLY_BINDING_STOP"
PHASE1_SHA="a4e0c0dca5e4b3bc7f55766998dc2eda8f5267e56f3392986b9053cc18c0a76e"
WRITER_SHA="9c4a466d8782e3c841d9bc874d541e10e4666dde465a8bf79408a4915c1712d6"
MAX_READS=6000
COLLECTOR_MODE="RAW_HOLDER_AND_PORTIONS_BEFORE_NOMINAL_ACCEPTANCE_V1"
FAILED_HOLDER_OBSERVER_SHA="3fc1264c40162e1717b0d6a7cf89e2ecbea27bc36b3a446c2c3c2e10ce472860"
FAILED_HOLDER_READ_SHA="b682451e4324a3731ec6af8f0bf6711559c3c0483b507b9fc2a6cad3a1cdf8f6"
HOLDER_VERIFIER_SHA="882c1acf9fbdb0a1c457c8d8a593a5a8a38a29b4ba092e133ccf9c43cd86420b"


def export_marker(document,prior_sha,tool_id):
    p=Path(document).resolve()
    key=_digest(dict(scope=SCOPE,document=str(p).casefold(),prior_sha256=prior_sha,tool_native_id=tool_id))
    return p.parent/("sandvik_observe_export_"+key+".json")


def profile_observation(candidate,profiles):
    """List expected MT segments and extras without accepting native cutting shape."""
    expected=list(zip(POINTS,POINTS[1:]));matches=[];extras=[];all_rows={}
    for label in ("tool","shank"):
        all_rows[label]=[]
        for chain,index,a,b in _curves(profiles[label]):
            row=dict(chain=chain,curve=index,start_native=list(a),end_native=list(b))
            match=[i for i,(c,d) in enumerate(expected) if _same_edge(a,b,c,d)]
            row["matching_MT_segment_indexes"]=match
            all_rows[label].append(row)
            if label=="tool" and match:matches.extend(match)
            elif label=="tool":extras.append(row)
    if sorted(matches)!=list(range(5)):
        raise ValueError("Observed tool no longer contains each pinned MT outer segment once")
    return dict(scope="EXACT_NATIVE_PROFILE_OBSERVATION_NOT_SHAPE_ACCEPTANCE",
        profile_sha256=_digest(profiles),expected_MT_segment_count=5,
        expected_MT_segments_present_once=True,tool_extra_edges=extras,
        observed_edges=all_rows,source_candidate_part=candidate["part"],
        numeric_profile_verified=False,cutting_partition_verified=False,
        units_verified=False,physical_tool_qualified=False,production_qualified=False,
        reason="Frozen prior contours retained; extra radial edge and full-length cylindrical geometry remain unqualified.")


def raw_export_pin(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file():raise ValueError("Export is not a regular file")
    before=p.stat()
    if not 0<=before.st_size<=4*1024*1024:raise ValueError("Export exceeds bounded file size")
    digest=_file_hash(p);after=p.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError("Export changed during pinning")
    return dict(path=str(p),sha256=digest,bytes=after.st_size)


def analyze_export(path,portion):
    """Retain native bytes and numeric measurements even if the envelope fails."""
    pin=raw_export_pin(path)
    result=dict(pin=pin,portion=portion,classification_pending=True,mesh_health_verified=False,
        units_verified=False,cutting_partition_verified=False,physical_tool_qualified=False,
        numeric_envelope_verified=False,production_qualified=False)
    try:
        raw,stable_pin=_read_pinned(path)
        if stable_pin["sha256"]!=pin["sha256"]:raise ValueError("Export changed before decoding")
        result["stable_mesh_pin"]=stable_pin
        triangles,encoding=_decode(raw)
        points=[p for t in triangles for p in t]
        result["raw_measurement"]=dict(encoding=encoding,triangle_count=len(triangles),
            bounds_native=[min(p[i] for p in points) for i in range(3)]+[max(p[i] for p in points) for i in range(3)],
            maximum_radius_native=max(math.hypot(p[0],p[1]) for p in points),
            axial_extent_native=[min(p[2] for p in points),max(p[2] for p in points)],
            finite_bounded_decoded=True,alignment_performed=False,rescaling_performed=False)
        result["bounded_observation"]=numeric_mesh_observation(path,portion)
        result["mesh_health_verified"]=result["bounded_observation"]["mesh_health_verified"]
    except ValueError as exc:
        result["observation_issue"]=dict(type=type(exc).__name__,reason=str(exc))
        result["review_required"]=True
    if _file_hash(path)!=pin["sha256"]:raise ValueError("Export changed during offline observation")
    return result


def load_observation_request(*,phase1_receipt_path,phase1_receipt_sha256,
        expected_candidate_tool_native_id,phase1_backend_path,phase1_backend_sha256,
        profile_validator_path,profile_validator_sha256,cutting_stl_path,noncutting_stl_path,**args):
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
    blocked={Path(p["path"]).resolve() for p in anchor.pins+pins}
    blocked.add(Path(args["expected_document_path"]).resolve())
    outputs=[fresh_output(path,suffix,blocked) for path,suffix in (
        (cutting_stl_path,".stl"),(noncutting_stl_path,".stl"),(args["receipt_path"],".json"))]
    if len(set(p.resolve() for p in outputs))!=3:raise ValueError("Distinct fresh outputs required")
    marker=export_marker(args["expected_document_path"],phase1_receipt_sha256,new_id)
    if marker.exists() or marker.is_symlink() or marker.resolve() in blocked|set(p.resolve() for p in outputs):
        raise ValueError("Existing export attempt or path collision; never replay")
    return dict(data=data,pin=pin,pins=pins,anchor=anchor,candidate=candidate,holder=holder,
        firstcut=first["after_settings"],rough_id=rough[0]["native_id"],creation_pin=creation_pin,
        profile_observation=observation,marker=marker)



def load_strong_observation_request(*,failed_observation_receipt_path,failed_observation_receipt_sha256,
        failed_observer_backend_path,failed_observer_backend_sha256,
        failed_read_batch_backend_path,failed_read_batch_backend_sha256,**args):
    """Resume only the completed pre-export failure; retain the same export gate."""
    loaded=load_observation_request(**args)
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
    if loaded["marker"].exists():raise ValueError("Export attempt already exists; never replay")
    if _file_hash(args["expected_document_path"])!=args["expected_source_sha256"]:
        raise ValueError("Saved source differs after read-only failure")
    loaded["pins"]+=implementation+[pin]
    loaded["readonly_binding_stop"]=dict(receipt_pin=pin,implementation_pins=implementation,
        no_export_attempt_verified=True,read_mode=READ_MODE,
        original_export_marker=str(loaded["marker"]),new_export_identity_created=False)
    return loaded


def load_collector_request(*,failed_observation_receipt_path,failed_observation_receipt_sha256,
        failed_observer_backend_path,failed_observer_backend_sha256,
        failed_read_batch_backend_path,failed_read_batch_backend_sha256,**args):
    """Continue the exact completed nominal-holder stop without replaying exports."""
    if (failed_observation_receipt_sha256!=FAILED_HOLDER_READ_SHA
        or failed_observer_backend_sha256!=FAILED_HOLDER_OBSERVER_SHA):
        raise ValueError("Exact completed nominal-holder stop and implementation required")
    implementation=dict(path=failed_observer_backend_path,sha256=failed_observer_backend_sha256)
    if _file_hash(implementation["path"])!=implementation["sha256"]:
        raise ValueError("Failed holder observer implementation changed")
    verifier=dict(path=str(Path(holder_geometry.__file__)),sha256=HOLDER_VERIFIER_SHA)
    if _file_hash(verifier["path"])!=verifier["sha256"]:
        raise ValueError("Reviewed nominal holder verifier changed")
    failed,pin=read_pin(failed_observation_receipt_path,failed_observation_receipt_sha256)
    if (failed.get("scope")!=SCOPE or failed.get("read_mode")!=READ_MODE
        or failed.get("status")!="error" or failed.get("phase")!="finished"
        or failed.get("failed_phase")!="preflight" or type(failed.get("native_read_count")) is not int
        or failed["native_read_count"]!=525):
        raise ValueError("Only the exact completed holder-count observation stop is supported")
    for key in ("native_dispatch_pending","export_attempted","mutation_attempted","tool_creation_attempted",
        "MT_load_attempted","field_setter_attempted","holder_setter_attempted","operation_assignment_attempted",
        "GTP_attempted","GOP_attempted","AFR_attempted","simulation_attempted","model_saved","save_attempted",
        "TechDB_write_attempted","automatic_replay","automatic_rollback","readback_verified",
        "numeric_profile_verified","physical_tool_qualified","units_verified","cutting_partition_verified",
        "production_qualified","may_continue","raw_exports_pinned","exports_verified","post_cleanup_CAM_getters",
        "holder_profile_verified","protected_context_unchanged"):
        if failed.get(key) is not False:raise ValueError("Unexpected holder-stop flag: "+key)
    if (failed.get("dispatches")!=[] or failed.get("exports")!={} or failed.get("snapshot_diagnostics")!=[]
        or any(k in failed for k in ("before_candidate","after_candidate","after","receipt_write_error"))):
        raise ValueError("Prior export or uncertain holder observation blocks continuation")
    issue=failed.get("issue",{})
    if issue.get("type")!="ValueError" or issue.get("locations")!=[
        dict(file="sw_cam_existing_sandvik.py",function="observe_existing_sandvik",line=509),
        dict(file="sw_cam_existing_sandvik.py",function="candidate_snapshot",line=469),
        dict(file="sw_cam_shared_holder_geometry.py",function="verify_holder_profile",line=52)]:
        raise ValueError("Different failure cannot authorize nominal-holder collection")
    clean_events(failed)
    stop=failed["readonly_binding_stop"];old=stop["receipt_pin"];impl=stop["implementation_pins"]
    if type(impl) is not list or len(impl)!=2:raise ValueError("Original read-only stop lineage required")
    check_document_target(failed_read_batch_backend_path,None,expected_path=impl[1]["path"],required=True)
    if failed_read_batch_backend_sha256!=impl[1]["sha256"]:raise ValueError("Historical read-batch pin differs")
    loaded=load_strong_observation_request(failed_observation_receipt_path=old["path"],
        failed_observation_receipt_sha256=old["sha256"],failed_observer_backend_path=impl[0]["path"],
        failed_observer_backend_sha256=impl[0]["sha256"],failed_read_batch_backend_path=impl[1]["path"],
        failed_read_batch_backend_sha256=impl[1]["sha256"],**args)
    expected_binding={k:args[k] for k in BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")}
    if (failed["readonly_binding_stop"]!=loaded["readonly_binding_stop"]
        or failed["request_binding"]!=expected_binding or failed["prior_receipt_pin"]!=loaded["pin"]
        or failed["prior_creation_marker_pin"]!=loaded["creation_pin"]
        or failed["evidence_pins"]!=loaded["pins"] or failed["anchor"]!=loaded["anchor"].summary()
        or failed["profile_observation"]!=loaded["profile_observation"]
        or type(failed.get("tool_native_id")) is not int or failed["tool_native_id"]!=args["expected_candidate_tool_native_id"]
        or type(failed.get("process_id")) is not int or failed["process_id"]!=args["process_id"]
        or failed["before_document"]!=loaded["data"]["before_document"]
        or failed["source_before_sha256"]!=args["expected_source_sha256"]
        or failed["expected_source_sha256"]!=args["expected_source_sha256"]):
        raise ValueError("Holder-stop source, candidate or prior lineage differs")
    check_document_target(failed["expected_document_path"],None,expected_path=args["expected_document_path"],required=True)
    check_document_target(failed["dispatch_marker_path"],None,expected_path=str(loaded["marker"]),required=True)
    diagnostic=failed.get("before_tool_diagnostic",{})
    if (diagnostic.get("capture_complete") is not True or diagnostic.get("stage")!="complete"
        or diagnostic.get("state")!=loaded["data"]["tool"]):
        raise ValueError("Exact complete pre-holder candidate observation required")
    guards=failed.get("guard_diagnostics")
    if type(guards) is not list or not guards or any(g.get("invalid") is not False
        or g.get("native_call_attempted") is not False or g.get("native_call_returned") is not False for g in guards):
        raise ValueError("Prior strong-read guard failure or native dispatch blocks continuation")
    loaded["pins"] += [pin,implementation,verifier]
    loaded["holder_nominal_stop"]=dict(receipt_pin=pin,implementation_pin=implementation,
        nominal_verifier_pin=verifier,no_export_attempt_verified=True,
        original_export_marker=str(loaded["marker"]),new_export_identity_created=False,
        prior_raw_holder_profile_available=False)
    return loaded


def resolve_existing_context(app,read,typed,prior):
    """Resolve existing identities without a second full geometry snapshot."""
    active=read(app,"IGetActiveDoc")
    doc=typed(active,"ICWDoc3")
    doc_type=read(doc,"GetDocType")
    if type(doc_type) is not int or doc_type!=1:
        raise ValueError("Exact active CAM part required")
    part=typed(active,"ICWPartDoc")
    machine=typed(read(part,"IGetMachine"),"ICWMachine")
    kind=read(machine,"MachType")
    if type(kind) is not int or kind!=1:raise ValueError("MILL machine required")
    rows=[];operations={}
    for raw_setup in _items(read(machine,"IGetEnumOpSetups"),typed,read,8):
        setup=typed(raw_setup,"ICWBaseOpSetup");sid=_object_id(doc,setup,read)
        for raw in _items(read(setup,"IGetEnumOperations"),typed,read,32):
            op=typed(raw,"ICWOperation");oid=_object_id(doc,op,read)
            if type(oid) is not int or oid in operations:raise ValueError("Duplicate/invalid operation identity")
            operations[oid]=raw;rows.append((oid,sid))
    expected=[(o["native_id"],o["setup_native_id"]) for o in prior["before"]["operations"]]
    if rows!=expected:raise ValueError("Existing operation/setup identities changed")
    return dict(doc=doc,machine=machine,operations=operations)


def observe_existing_sandvik(sw,clsid,typelib_path,*,phase1_receipt_path,phase1_receipt_sha256,
        expected_candidate_tool_native_id,phase1_backend_path,phase1_backend_sha256,
        profile_validator_path,profile_validator_sha256,cutting_stl_path,noncutting_stl_path,
        failed_observation_receipt_path,failed_observation_receipt_sha256,
        failed_observer_backend_path,failed_observer_backend_sha256,
        failed_read_batch_backend_path,failed_read_batch_backend_sha256,**args):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,read_mode=READ_MODE,collector_mode=COLLECTOR_MODE,status="error",phase="preflight",process_id=args.get("process_id"),
        native_dispatch_pending=False,export_attempted=False,mutation_attempted=False,
        tool_creation_attempted=False,MT_load_attempted=False,field_setter_attempted=False,
        holder_setter_attempted=False,operation_assignment_attempted=False,GTP_attempted=False,
        GOP_attempted=False,AFR_attempted=False,simulation_attempted=False,model_saved=False,
        save_attempted=False,TechDB_write_attempted=False,automatic_replay=False,automatic_rollback=False,
        units_verified=False,physical_tool_qualified=False,cutting_partition_verified=False,
        numeric_profile_verified=False,production_qualified=False,may_continue=False,
        exports_verified=False,raw_exports_pinned=False,holder_profile_verified=False,holder_profile_observed=False,holder_readback_stable=False,
        protected_context_unchanged=False,post_cleanup_CAM_getters=False,readback_verified=False,
        native_read_count=0,dispatches=[],exports={},snapshot_diagnostics=[],guard_diagnostics=[])
    session=anchor=receipt=marker=None;created=claimed=False;baseline=None;active_guard=None
    started=monotonic()
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:
            if claimed:
                _write_receipt(marker,dict(scope=SCOPE,status=report["status"],phase=report["phase"],
                    receipt_path=str(receipt),document=args["expected_document_path"],
                    source_sha256=args["expected_source_sha256"],phase1_receipt_sha256=phase1_receipt_sha256,
                    tool_native_id=expected_candidate_tool_native_id,native_dispatch_pending=report["native_dispatch_pending"],
                    dispatches=report["dispatches"],exports=report["exports"],automatic_replay=False))
            _write_receipt(receipt,report)
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
        with ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],
                expected_document=identity(),source_sha256=args["expected_source_sha256"],
                evidence_pins=anchor.pins+pins,verify_evidence=verify_files,
                verify_owned_process=anchor.check_runtime_identity,check_events=events) as g:
            try:yield g
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
    def export(tool,label,path,portion):
        nonlocal claimed
        if active_guard is not None:raise ValueError("Export in read-only scope")
        fresh_output(path,".stl",immutable)
        entry=dict(label=label,path=path,pending=True,attempted=False,returned=False)
        report["dispatches"].append(entry)
        report.update(phase=label,native_dispatch_pending=True,export_attempted=True)
        def pending():
            nonlocal claimed
            if not claimed:
                _write_receipt(marker,dict(scope=SCOPE,status="dispatch_pending",receipt_path=str(receipt),
                    document=args["expected_document_path"],source_sha256=args["expected_source_sha256"],
                    phase1_receipt_sha256=phase1_receipt_sha256,tool_native_id=expected_candidate_tool_native_id,
                    automatic_replay=False),create=True)
                claimed=True
            entry["attempted"]=True;persist()
        with guard() as g:result=g.dispatch_once(lambda:_member(tool,label,path),persist_pending=pending)
        entry.update(returned=True,pending=False,return_type=type(result).__name__,
                     return_value=result if type(result) in (int,bool,float,str,type(None)) else None)
        report["native_dispatch_pending"]=False;persist()
        if type(result) is not int or result!=0:raise ValueError("Unexpected STL export HRESULT")
        # Pin raw bytes now; topology and envelope analysis wait for both exports.
        pin=raw_export_pin(path)
        report["exports"][portion]=dict(pin=pin,classification_pending=True);persist()
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
    def candidate_snapshot(native,phase):
        # Application-wide unit settings retain the strong per-getter guard.
        with reads(strong=True):
            model=read(sw,"ActiveDoc")
            metric=read_document_cam_unit_scope(model,app,sw_read=lambda o,n:read(o,n),cam_read=read)
            if metric!=prior["metric_scope"]:raise ValueError("Metric document scope changed")
        with reads():
            firstcut=read_firstcut_settings(native["operations"][loaded["rough_id"]],read,typed)
            if firstcut!=loaded["firstcut"]:raise ValueError("Firstcut checkpoint changed")
            crib=typed(read(native["machine"],"IGetToolcrib"),"ICWToolcrib4")
            rows=capture_local_tools(crib,native["doc"],read,typed)
            verify_one_new_tool(prior["before_tools"],rows,expected_candidate_tool_native_id)
            matches=[]
            for raw in _items(read(crib,"GetAllTools"),typed,read,128):
                t=typed(raw,"ICWTool")
                if _object_id(native["doc"],t,read)==expected_candidate_tool_native_id:matches.append(t)
            if len(matches)!=1:raise ValueError("Exact existing tool not unique")
            tool=matches[0]
            if read(tool,"IsMillTool") is not True:raise ValueError("Existing candidate is not MILL")
            observed=read_ud14_tool(tool,doc=native["doc"],read=read,typed=typed,
                diagnostic=report.setdefault(phase+"_tool_diagnostic",{}))
            if observed!=prior["tool"]:raise ValueError("Existing candidate fields or exact profile changed")
            observation=profile_observation(loaded["candidate"],observed["profiles"])
            if observation!=loaded["profile_observation"]:raise ValueError("Frozen contour observation changed")
            holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
            all_holders=holder_objects(crib,native["doc"],read,typed)
            old_holders={k:v for k,v in all_holders.items() if k!=expected_candidate_tool_native_id}
            reject_holder_alias(holder,old_holders,identity=lambda obj:com_identity(obj,read))
            check_document_target(read(holder,"GetName"),None,expected_path=loaded["holder"]["file_path"],required=True)
            hp={}
            holder_diagnostic=dict(state=hp,capture_complete=False)
            report[phase+"_holder_diagnostic"]=holder_diagnostic
            read_segment_chains(holder,"GetHolderProfile",read=read,typed=typed,
                diagnostic=holder_diagnostic,budget=dict(curves=0,chains=0,islands=0))
            report[phase+"_holder_profile"]=deepcopy(hp)
            persist()
            hv=observe_holder_nominal(hp,loaded["holder"],25)
            report[phase+"_holder_nominal_verification"]=deepcopy(hv)
            persist()
            current_identity=com_identity(holder,read)
        snap=dict(tool=observed,profile_observation=observation,holder_profile=hp,
            holder_verification=hv,firstcut=firstcut,metric_scope=metric,local_tools=rows)
        report[phase+"_candidate"]=snap;persist()
        return tool,current_identity,snap
    try:
        loaded=load_collector_request(
            failed_observation_receipt_path=failed_observation_receipt_path,
            failed_observation_receipt_sha256=failed_observation_receipt_sha256,
            failed_observer_backend_path=failed_observer_backend_path,
            failed_observer_backend_sha256=failed_observer_backend_sha256,
            failed_read_batch_backend_path=failed_read_batch_backend_path,
            failed_read_batch_backend_sha256=failed_read_batch_backend_sha256,
            phase1_receipt_path=phase1_receipt_path,phase1_receipt_sha256=phase1_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,phase1_backend_path=phase1_backend_path,
            phase1_backend_sha256=phase1_backend_sha256,profile_validator_path=profile_validator_path,
            profile_validator_sha256=profile_validator_sha256,cutting_stl_path=cutting_stl_path,
            noncutting_stl_path=noncutting_stl_path,**args)
        prior=loaded["data"];anchor=loaded["anchor"];pins=loaded["pins"];marker=loaded["marker"]
        immutable={Path(p["path"]).resolve() for p in anchor.pins+pins}
        immutable.add(Path(args["expected_document_path"]).resolve())
        receipt=Path(args["receipt_path"]);_write_receipt(receipt,report,create=True);created=True
        baseline=identity()
        if baseline!=prior["before_document"]:raise ValueError("Current document differs from original checkpoint")
        report.update(before_document=deepcopy(baseline),source_before_sha256=args["expected_source_sha256"],
            expected_document_path=args["expected_document_path"],expected_source_sha256=args["expected_source_sha256"],
            prior_receipt_pin=loaded["pin"],prior_creation_marker_pin=loaded["creation_pin"],
            tool_native_id=expected_candidate_tool_native_id,anchor=anchor.summary(),evidence_pins=pins,
            request_binding={k:deepcopy(args[k]) for k in BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")},
            dispatch_marker_path=str(marker),profile_observation=loaded["profile_observation"],
            readonly_binding_stop=loaded["readonly_binding_stop"],holder_nominal_stop=loaded["holder_nominal_stop"])
        verify_files();app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"])
        if identity()!=baseline:raise ValueError("Document changed acquiring CAM host")
        session=CamMessageSession(app,typelib_path)
        with session:
            before=deepcopy(prior["before"])
            report["before_reference"]=dict(pin=loaded["pin"],field="before",fresh_full_snapshot=False)
            with reads(strong=True):
                native=resolve_existing_context(app,read,typed,prior)
            tool,holder_identity,before_candidate=candidate_snapshot(native,"before")
            report["holder_profile_observed"]=True
            report["holder_profile_verified"]=before_candidate["holder_verification"]["native_holder_shape_verified"]
            export(tool,"CreateSTLOfCuttingPortion",cutting_stl_path,"cutting")
            export(tool,"CreateSTLOfNonCuttingPortion",noncutting_stl_path,"noncutting")
            report["raw_exports_pinned"]=True
            for portion,path in (("cutting",cutting_stl_path),("noncutting",noncutting_stl_path)):
                report["exports"][portion]=analyze_export(path,portion);persist()
            after,after_native=capture("after",full=True)
            if not same_observed_context(before,after,allow_dirty=False):raise ValueError("Protected plan changed during exports")
            _,after_holder,after_candidate=candidate_snapshot(after_native,"after")
            if before_candidate!=after_candidate or after_holder!=holder_identity:
                raise ValueError("Candidate/holder identity changed during exports")
            report["protected_context_unchanged"]=True
            report["holder_readback_stable"]=True
            report["exports_verified"]=all(row.get("mesh_health_verified") is True for row in report["exports"].values())
        events(active=False);report["after_document"]=identity();verify_files()
        report.update(status="review_required",phase="finished",readback_verified=True,
            reason="EXACT_EXISTING_CANDIDATE_AND_RAW_PORTIONS_OBSERVED_GEOMETRY_CLASSIFICATION_PENDING",
            classification_pending=True)
    except Exception as exc:
        report.update(status="uncertain" if report["export_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(receipt_write_error=_error(exc),status="uncertain",readback_verified=False)
    return report

