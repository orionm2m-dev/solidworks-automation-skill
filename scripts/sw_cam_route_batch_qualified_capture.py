"""Pinned qualification gate and optional snapshot-only batch adapter."""
from copy import deepcopy
import importlib
import re
from pathlib import Path
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_route_read_batch import ScopedCamRouteReadBatch, capture_route_batch
from scripts.sw_operation_guard import check_document_target

SCOPE="QUALIFIED_CAM_ROUTE_CAPTURE_V1"
QUALIFIED_MODULES=("sw_cam_route_read_batch_qualification", "sw_cam_route_read_batch",
    "sw_cam_read_batch_guard", "sw_cam_dispatch_guard", "sw_cam_rough_entry_parameters")


def canonical_evidence_pins(*groups):
    """Preserve all unique dependencies before the unchanged guard's 64-pin cap."""
    merged={}
    for group in groups:
        require(type(group) in (list,tuple), "Explicit evidence pin sequence required")
        for pin in group:
            require(type(pin) is dict and type(pin.get("path")) is str
                and type(pin.get("sha256")) is str
                and re.fullmatch("[0-9a-f]{64}",pin["sha256"]) is not None,
                "Exact evidence path and SHA-256 required")
            path=Path(pin["path"])
            require(path.is_absolute(), "Absolute evidence path required")
            canonical=str(path.resolve());key=canonical.casefold()
            item=deepcopy(pin);item["path"]=canonical
            if "canonical_path" in item:
                require(type(item["canonical_path"]) is str
                    and str(Path(item["canonical_path"]).resolve()).casefold()==key,
                    "Evidence canonical path differs")
                item["canonical_path"]=canonical
            if "bytes" in item:
                require(type(item["bytes"]) is int and item["bytes"]>=0,"Strict evidence byte length required")
            if key not in merged:
                merged[key]=item
            else:
                current=merged[key]
                require(current["sha256"]==item["sha256"],"Conflicting SHA-256 for same canonical evidence path")
                for field,value in item.items():
                    if field in ("path","canonical_path"):continue
                    require(field not in current or (type(current[field]) is type(value) and current[field]==value),
                        "Conflicting metadata for same canonical evidence path: "+field)
                    current[field]=deepcopy(value)
                if "canonical_path" in item:current["canonical_path"]=canonical
    count=len(merged)
    require(1<=count<=64,"Evidence requires "+str(count)+" unique paths; unchanged guard limit is 64")
    return list(merged.values())


def _qualified_runtime_paths():
    return [Path(importlib.import_module("scripts."+name).__file__).resolve() for name in QUALIFIED_MODULES]


def load_route_batch_qualification(path, sha256, *, saved, process_id,
        expected_document_path, expected_source_sha256, target_feature_native_id,
        target_operation_native_id, target_operation_setup_native_id,
        expected_candidate_tool_native_id, caller_path):
    """No native access. Qualifies the measured reader subset, never full geometry."""
    data,pin=read_pin(path,sha256)
    require(data.get("scope")=="CAM_ROUTE_READ_BATCH_QUALIFICATION_V1"
        and data.get("status")=="observed" and data.get("phase")=="finished", "Successful finished batch qualification required")
    for key in ("read_only","readback_verified","batch_qualified","snapshot_scope_qualified","raw_values_equal"):
        require(data.get(key) is True,"Incomplete batch qualification: "+key)
    for key in ("mutation_attempted","setter_attempted","save_attempted","model_saved",
            "GTP_attempted","GOP_attempted","AFR_attempted","automatic_replay","post_cleanup_CAM_getters",
            "full_route_snapshot_qualified","full_geometry_rechecked","production_qualified","may_continue",
            "atomic_snapshot","transient_active_document_excursion_excluded","reacquired_wrapper_identity_comparison"):
        require(data.get(key) is False,"Unexpected batch qualification scope: "+key)
    require(not any(k in data for k in ("issue","failed_phase","receipt_write_error")),"Failed qualification cannot authorize batch")
    clean_events(data)
    binding=dict(process_id=process_id,target_feature_native_id=target_feature_native_id,
        target_operation_native_id=target_operation_native_id,target_operation_setup_native_id=target_operation_setup_native_id)
    require(all(type(data.get(k)) is int and data[k]==v for k,v in binding.items()),"Qualification PID or target differs")
    check_document_target(data["expected_document_path"],None,expected_path=expected_document_path,required=True)
    require(data["source_sha256"]==expected_source_sha256 and data["saved_draft_pin"]==saved["pin"]
        and data["document_after"]==data["document_after_cleanup"]==saved["state"]["document"],
        "Qualification saved source or draft identity differs")
    phases=data["phases"]
    require(type(phases) is list and [p["name"] for p in phases]==["strong_before","batch","strong_after"],
        "Exactly strong/batch/strong completion required")
    counts=[p["field_native_calls"] for p in phases]
    require(counts[0]==counts[1]==counts[2]
        and all(type(v) is int and v>0 for v in counts[0].values()),"Same positive native read counts required")
    for row in phases:
        g=row["guard"]
        require(all(g.get(k) is False for k in ("active","invalid","claimed","native_call_attempted","native_call_returned")),
            "Qualification guard was active, invalid or dispatched")
    batch=phases[1]["guard"]
    require(batch.get("scope")=="BOUNDED_CAM_ROUTE_READ_BATCH_V1"
        and batch.get("read_scope_complete") is True and batch.get("dispatch_available") is False
        and batch.get("complete_boundary_checks")==2 and batch.get("retained_binding_checks")==2
        and batch.get("reacquired_wrapper_identity_comparison") is False,"Incomplete retained batch boundaries")
    obs=data["observations"]
    require(set(obs)=={"strong_before","batch","strong_after"}
        and obs["strong_before"]==obs["batch"]==obs["strong_after"],"Qualification observations differ")
    sample=obs["batch"]
    target=next(o for o in saved["state"]["operations"] if o["native_id"]==target_operation_native_id)
    require(type(sample["candidate_tool_id"]) is int and sample["candidate_tool_id"]==expected_candidate_tool_native_id
        and sample["operation_id"]==target_operation_native_id and sample["linked_feature_ids"]==[target_feature_native_id]
        and sample["assigned_tool_id"]==target["assigned_tool"]["native_id"]
        and sample["candidate_type"]==14 and sample["operation_type"]==0
        and sample["suppressed"] is False and sample["toolpath_generated"] is False,
        "Qualification candidate/target binding differs from saved draft")
    payload=saved["payload"]
    require(sample["tool_parameters"]==payload["tool"]["parameters"]
        and sample["mt_path_raw"]==payload["tool"]["mt_path_raw"]
        and sample["holder_mode_fields"]=={k:payload["holder_fields"][k]
            for k in ("GetHolderShape","GetHolderId","GetName")}
        and data["units_before"]==data["units_after"]==payload["metric_scope"],
        "Qualification tool, holder or global units differ")
    core=[]
    for runtime_path in _qualified_runtime_paths():
        rows=[p for p in data["evidence_pins"]
            if str(Path(p["path"]).resolve()).casefold()==str(runtime_path).casefold()]
        require(len(rows)==1 and _file_hash(runtime_path)==rows[0]["sha256"],
            "Qualified runtime implementation changed: "+runtime_path.name)
        core.append(rows[0])
    # New integration code is separately pinned throughout captures and dispatch;
    # it is not represented as having been exercised in the prior native sample.
    current=[]
    for p in (Path(__file__),Path(caller_path),Path(__file__).parent/"sw_cam_completed_sandvik_assignment.py"):
        resolved=p.resolve()
        row=dict(path=str(resolved),sha256=_file_hash(resolved))
        if row not in current:current.append(row)
    return dict(scope=SCOPE,pin=pin,pins=[pin]+core+current,qualified_core_pins=core,
        integration_pins=current,binding={**binding,"expected_document_path":expected_document_path,
            "expected_source_sha256":expected_source_sha256,"candidate_tool_id":expected_candidate_tool_native_id},
        qualified_snapshot_fields=deepcopy(data["qualified_snapshot_fields"]),
        full_route_snapshot_qualified=False,qualification_limit=data["qualification_limit"])


def qualified_route_capture(app, sw, typelib_path, *, qualification,
        process_id, current_document, source_sha256, evidence_pins,
        verify_evidence, verify_owned_process, check_events, strong_guard_factory,
        reference_state, target_feature_native_id, target_operation_native_id,
        expected_candidate_tool_native_id, reference_candidate, observation_pin, diagnostic):
    """Batch snapshots only; native dispatch remains owned by the existing caller."""
    require(qualification.get("scope")==SCOPE,"Pinned qualification loader required")
    binding=qualification["binding"]
    require(process_id==binding["process_id"] and source_sha256==binding["expected_source_sha256"]
        and target_feature_native_id==binding["target_feature_native_id"]
        and target_operation_native_id==binding["target_operation_native_id"]
        and expected_candidate_tool_native_id==binding["candidate_tool_id"],"Capture scope differs from qualification")
    check_document_target(current_document["path"],current_document["title"],
        expected_path=binding["expected_document_path"],required=True)
    evidence_pins=canonical_evidence_pins(evidence_pins)
    identities={(str(Path(p["path"]).resolve()).casefold(),p["sha256"]) for p in evidence_pins}
    require(all((str(Path(p["path"]).resolve()).casefold(),p["sha256"]) in identities
        for p in qualification["pins"]),"Qualification and current code pins missing from capture guard")
    def batch_factory(native, reference):
        return ScopedCamRouteReadBatch(sw,typelib_path,native_context=native,reference_state=reference,
            process_id=process_id,expected_document=current_document,source_sha256=source_sha256,
            evidence_pins=evidence_pins,verify_evidence=verify_evidence,
            verify_owned_process=verify_owned_process,check_events=check_events,max_native_calls=900)
    diagnostic.update(read_mode="qualified_batch",qualification_pin=qualification["pin"],
        qualified_snapshot_fields=qualification["qualified_snapshot_fields"],full_route_snapshot_qualified=False)
    return capture_route_batch(app,sw,strong_guard_factory=strong_guard_factory,batch_factory=batch_factory,
        reference_state=reference_state,current_document=current_document,source_sha256=source_sha256,
        target_feature_native_id=target_feature_native_id,target_operation_native_id=target_operation_native_id,
        expected_candidate_tool_native_id=expected_candidate_tool_native_id,reference_candidate=reference_candidate,
        observation_pin=observation_pin,check_events=check_events,diagnostic=diagnostic)
