"""Export a completed initial GTP through the qualified SaveCLFile engine.

No generation, record getters or model save. Whole-machine output is bounded
to one generated operation; model and profile geometry reuse pinned evidence.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_route_batch_qualified_capture import (
    canonical_evidence_pins, load_route_batch_qualification, qualified_route_capture)
from scripts.sw_cam_completed_sandvik_saved import load_saved_sandvik
from scripts.sw_cam_completed_sandvik_save import read_feature_counts
from scripts.sw_cam_completed_sandvik_assignment import capture_assignment_snapshot, read_assignment_candidate
from scripts.sw_cam_sandvik_gtp_evidence import SCOPE as GTP_SCOPE, load_completed_assignment, verify_initial_gtp_delta, initial_gtp_marker
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_toolpath import _record_counts
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target

SCOPE = "MILL_COMPLETED_INITIAL_GTP_GENERIC_CL_V1"

def same_path(a,b):
    check_document_target(a,None,expected_path=str(b),required=True)

def load_completed_gtp(assigned,*,gtp_receipt_path,gtp_receipt_sha256,**args):
    """Extend the existing Save/assignment chain without reopening dispatch gates."""
    data,pin=read_pin(gtp_receipt_path,gtp_receipt_sha256)
    require(data.get("scope")==GTP_SCOPE and data.get("status")=="review_required"
        and data.get("phase")=="finished","Exact completed initial GTP required")
    for key in ("GTP_attempted","GTP_returned","mutation_attempted","readback_verified",
        "selected_toolpath_verified","protected_operations_verified"):
        require(data.get(key) is True,"Missing GTP flag: "+key)
    for key in ("native_dispatch_pending","save_attempted","model_saved","assignment_attempted",
        "tool_edit_attempted","GOP_attempted","AFR_attempted","simulation_attempted","NC_export_attempted",
        "CL_records_accessed","automatic_retry","automatic_replay","automatic_rollback",
        "full_geometry_rechecked","physical_units_verified","actual_poses_verified",
        "production_qualified","may_simulate","may_continue"):
        require(data.get(key) is False,"Unexpected GTP flag: "+key)
    require(not any(k in data for k in ("issue","failed_phase","receipt_write_error")),"Failed GTP cannot authorize export")
    require(type(data.get("GTP_call_count")) is int and data["GTP_call_count"]==1
        and data.get("native_return_type")=="int" and type(data.get("native_return_value")) is int
        and data["native_return_value"]==0,"One strict-zero successful GTP required")
    clean_events(data);same_path(data["expected_document_path"],args["expected_document_path"])
    require(type(data.get("process_id")) is int and data["process_id"]==args["process_id"]
        and data["source_sha256"]==args["expected_source_sha256"]
        and data["assignment_pin"]==assigned["pin"] and data["saved_draft_pin"]==assigned["saved"]["pin"],"GTP lineage differs")
    for key,value in assigned["target"].items():
        require(type(data.get(key)) is int and data[key]==value==args[key],"GTP target differs")
    require(type(data.get("candidate_id")) is int and data["candidate_id"]==assigned["candidate_id"],"Candidate differs")
    require(data["before"]==assigned["state"]
        and data["before_candidate"]==data["after_candidate"]==assigned["candidate_payload"]
        and data["before_levels"]==data["after_levels"]==assigned["levels"]
        and data["before_entry_parameters"]==data["after_entry_parameters"]==assigned["entry"],"GTP protected settings differ")
    verify_initial_gtp_delta(data["before"],data["after"],operation_id=args["target_operation_native_id"],
        feature_id=args["target_feature_native_id"],setup_id=args["target_operation_setup_native_id"],candidate_id=assigned["candidate_id"])
    require(data["continuation_state"]==data["after"] and data["state_sha256"]==_digest(data["after"])
        and data["after_cleanup_document"]==data["after"]["document"]
        and type(data["after"]["document"]["needs_save"]) is bool,"Exact post-GTP continuation required")
    guard=data["dispatch_guard"]
    require(guard.get("invalid") is False and guard.get("claimed") is True
        and guard.get("native_call_attempted") is True and guard.get("native_call_returned") is True,"Completed guarded GTP required")
    marker=initial_gtp_marker(args["expected_document_path"],args["expected_source_sha256"],
        args["target_operation_native_id"],assigned["candidate_id"],assigned["data"]["candidate_mt_pin"]["sha256"])
    same_path(data["marker_path"],marker)
    marker_data,marker_pin=read_pin(str(marker),_file_hash(marker))
    expected=dict(scope=GTP_SCOPE,status="review_required",phase="finished",document=args["expected_document_path"],
        source_sha256=args["expected_source_sha256"],assignment_pin=dict(path=assigned["pin"]["path"],sha256=assigned["pin"]["sha256"]),
        operation_id=args["target_operation_native_id"],candidate_id=assigned["candidate_id"],receipt_path=gtp_receipt_path,
        GTP_call_count=1,GTP_returned=True,native_dispatch_pending=False,readback_verified=True,automatic_replay=False)
    for key in ("document","receipt_path"):
        same_path(marker_data[key],expected[key]);expected[key]=marker_data[key]
    require(marker_data==expected,"Completed GTP marker differs")
    experiment,epin=read_pin(data["experiment_pin"]["path"],data["experiment_pin"]["sha256"])
    require(experiment.get("status")=="DECLARED_NUMERICAL_TRANSFORM_FOR_ONE_VIRTUAL_GTP_NOT_NATIVE_POSE_PROOF"
        and experiment["one_GTP_scope"]["may_generate_for_observation_with_declared_transform"] is True
        and data["declared_transform"]==experiment["candidate_transform"]
        and data["conditional_domain"]==experiment["conditional_domain"] and experiment["production_qualified"] is False
        and experiment["candidate_transform"]["verified_by_CAM_pose"] is False,"Numerical experiment lineage differs")
    pins=assigned["pins"]+[pin,marker_pin,epin]
    for item in pins:require(_file_hash(item["path"])==item["sha256"],"GTP evidence changed")
    return dict(data=data,pin=pin,pins=pins,state=deepcopy(data["after"]),assigned=assigned)

def validate_project_output(output_path,project_root,receipt_path,source_path,pins):
    """Allow raw mapped-drive paths only within the explicit canonical project root."""
    output=Path(output_path);root=Path(project_root);receipt=Path(receipt_path)
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(),"Explicit existing project root required")
    require(output.is_absolute() and bool(re.fullmatch(r"[A-Za-z]:",output.drive))
        and output.suffix.casefold()==".cl" and len(output.name)<=80
        and not any(c in output.name for c in '<>:"/\\|?*'+chr(0)) and ".." not in output.parts
        and not output.parent.exists() and not output.parent.is_symlink() and output.parent.parent.is_dir(),
        "Fresh .cl in an exclusive new drive directory required")
    canonical=output.resolve();canonical_root=root.resolve()
    require(canonical.is_relative_to(canonical_root),"CL output escapes canonical project root")
    require(receipt.is_absolute() and receipt.suffix.casefold()==".json" and receipt.parent.is_dir()
        and not receipt.exists() and not receipt.is_symlink() and receipt.resolve().is_relative_to(canonical_root),
        "Fresh project-contained receipt required")
    forbidden={str(Path(p["path"]).resolve()).casefold() for p in pins}
    forbidden.add(str(Path(source_path).resolve()).casefold())
    outputs=[str(p.resolve()).casefold() for p in (output,receipt)]
    require(len(set(outputs))==2 and not forbidden.intersection(outputs),"Output aliases source/evidence")
    return str(canonical),str(canonical_root)

class GeneratedPlanCLContext:
    """Private context of the existing exporter, not an arbitrary callback API."""
    def __init__(self,loaded,args,project_root,*,read_mode="strong",qualification=None):
        self.loaded=loaded;self.args=args;self.project_root=project_root
        self.assigned=loaded["assigned"];self.saved=self.assigned["saved"]
        self.anchor=self.saved["anchor"];self.claimed=False
        require(read_mode in ("strong","qualified_batch"),"Supported read mode required")
        require((read_mode=="qualified_batch")== (qualification is not None),"Exact optional qualification required")
        self.read_mode=read_mode;self.qualification=qualification
        self.pins=canonical_evidence_pins(self.anchor.pins,loaded["pins"],qualification["pins"] if qualification else [])
        self.marker=Path(args["expected_document_path"]).resolve().parent/(
            "generated_plan_cl_"+_digest(dict(scope=SCOPE,gtp_sha256=loaded["pin"]["sha256"]))+".json")
    def report_fields(self):
        return dict(scope=SCOPE,gtp_pin=self.loaded["pin"],evidence_pins=self.pins,
            read_mode=self.read_mode,batch_qualification_pin=self.qualification["pin"] if self.qualification else None,
            full_route_snapshot_qualified=False,
            export_marker_path=str(self.marker),full_geometry_rechecked=False,tool_readers_used=True,
            reference_state_sha256=self.loaded["data"]["state_sha256"],
            bounded_scope="Nineteen pinned features, six fresh operations, one generated rough",
            snapshot_scope="Fresh operation bindings/counts and target settings/tool/holder scalars; pinned geometry reused",
            geometry_provenance=dict(reference_pin=self.loaded["pin"],full_geometry_rechecked=False),
            authorization_scope="Completed pinned GTP and exact fresh state; no prepare or generation")
    def files(self):
        self.anchor.check_files()
        for pin in self.pins:require(_file_hash(pin["path"])==pin["sha256"],"Pinned CL evidence changed")
    def identity(self,sw):
        pid=_member(sw,"GetProcessID")
        require(type(pid) is int and pid==self.args["process_id"],"Owned process changed")
        self.anchor.check_runtime_identity();self.files();doc=raw_part_identity(sw)
        require(doc==self.loaded["state"]["document"],"Exact post-GTP RAM document required")
        require(_file_hash(self.args["expected_document_path"])==self.args["expected_source_sha256"],"Saved source changed")
        return doc
    def validate(self,**request):
        require(request["action"]=="apply" and request["expected_state_sha256"] is None,"One completed-GTP export required")
        require(request["acknowledge_machine_scope"] is True,"Explicit whole-machine scope required")
        require(not self.marker.exists() and not self.marker.is_symlink(),"Prior CL attempt exists; no replay")
        validate_project_output(request["output_path"],self.project_root,request["receipt_path"],
            self.args["expected_document_path"],self.pins)
    def selected(self,state,feature_id,operation_id,operation_type):
        require(len(state["features"])==19 and len(state["operations"])==6,"Exact protected context required")
        rows=[r for r in state["operations"] if r["native_id"]==operation_id]
        require(len(rows)==1 and rows[0]["linked_feature_ids"]==[feature_id]
            and rows[0]["mill_operation_type"]==operation_type and rows[0]["suppressed"] is False,
            "Exact unsuppressed selected operation required")
        return rows[0]
    def verify_before(self,snapshot):
        require(snapshot["mill_state"]==self.loaded["state"],"Current state differs from completed GTP")
    def capture(self,sw,clsid,typelib_path,app,check,diagnostic):
        reference=self.loaded["state"]
        def strong_guard_factory():
            return ScopedCamDispatchGuard(sw,typelib_path,process_id=self.args["process_id"],
                expected_document=self.identity(sw),source_sha256=self.args["expected_source_sha256"],
                evidence_pins=canonical_evidence_pins(self.pins),verify_evidence=self.files,
                verify_owned_process=self.anchor.check_runtime_identity,check_events=check)
        if self.read_mode=="qualified_batch":
            state,native,levels,firstcut,entry,payload=qualified_route_capture(app,sw,typelib_path,
                qualification=self.qualification,process_id=self.args["process_id"],
                current_document=self.identity(sw),source_sha256=self.args["expected_source_sha256"],
                evidence_pins=canonical_evidence_pins(self.pins),verify_evidence=self.files,
                verify_owned_process=self.anchor.check_runtime_identity,check_events=check,
                strong_guard_factory=strong_guard_factory,reference_state=reference,
                target_feature_native_id=self.args["target_feature_native_id"],
                target_operation_native_id=self.args["target_operation_native_id"],
                expected_candidate_tool_native_id=self.assigned["candidate_id"],
                reference_candidate=self.assigned["candidate_payload"],observation_pin=self.saved["observation_pin"],
                diagnostic=diagnostic)
        else:
            diagnostic["read_mode"]="strong"
            with strong_guard_factory() as guard:
                state,native,levels,firstcut,entry=capture_assignment_snapshot(app,read=guard.read,typed=guard.typed,
                    reference_state=reference,current_document=reference["document"],source_sha256=self.args["expected_source_sha256"],
                    target_feature_native_id=self.args["target_feature_native_id"],target_operation_native_id=self.args["target_operation_native_id"],
                    boundary=lambda:(self.files(),check(),self.identity(sw)),diagnostic=diagnostic)
                payload=read_assignment_candidate(native,app,sw,read=guard.read,typed=guard.typed,
                    expected_candidate_tool_native_id=self.assigned["candidate_id"],reference=self.assigned["candidate_payload"],
                    observation_pin=self.saved["observation_pin"],firstcut=firstcut,diagnostic=diagnostic.setdefault("candidate",{}))
        # Fresh counts also protect the pinned feature geometry in batch mode.
        with strong_guard_factory() as guard:
            counts=read_feature_counts(native,guard.read,guard.typed)
        expected=[dict(native_id=row["native_id"],feature_count=row["feature_count"]) for row in reference["feature_setups"]]
        require(counts==expected,"Feature/setup counts changed")
        diagnostic["fresh_feature_setup_counts"]=counts
        require(state==reference and levels==self.assigned["levels"] and entry==self.assigned["entry"]
            and payload==self.assigned["candidate_payload"],"Post-GTP operation/settings/candidate changed")
        diagnostic["geometry_reference_pin"]=self.loaded["pin"]
        return state,native
    def marker_state(self,report):
        return dict(scope=SCOPE,gtp_pin=self.loaded["pin"],status=report["status"],phase=report["phase"],
            output_path=self.args["output_path"],receipt_path=self.args["receipt_path"],
            native_dispatch_pending=report["native_dispatch_pending"],native_call_attempted=report["native_call_attempted"],
            native_call_returned=report["native_call_returned"],output_verified=report["output_verified"],automatic_replay=False)
    def claim(self,report):
        self.files();_write_receipt(self.marker,self.marker_state(report),create=True);self.claimed=True
    def persist(self,report):
        if self.claimed:_write_receipt(self.marker,self.marker_state(report))

def export_completed_gtp_cl(sw,clsid,typelib_path,*,saved_draft_receipt_path,saved_draft_receipt_sha256,
        assignment_receipt_path,assignment_receipt_sha256,gtp_receipt_path,gtp_receipt_sha256,
        expected_candidate_tool_native_id,project_root,acknowledge_machine_scope,output_path,
        read_mode="strong",batch_qualification_receipt_path=None,batch_qualification_receipt_sha256=None,**args):
    from scripts.sw_cam_mill_generic_cl import export_mill_generic_cl
    require(read_mode in ("strong","qualified_batch"),"Supported read mode required")
    require((read_mode=="qualified_batch" and type(batch_qualification_receipt_path) is str
        and type(batch_qualification_receipt_sha256) is str)
        or (read_mode=="strong" and batch_qualification_receipt_path is None and batch_qualification_receipt_sha256 is None),
        "Exact qualification pin is required only for qualified_batch")
    saved=load_saved_sandvik(saved_draft_receipt_path=saved_draft_receipt_path,saved_draft_receipt_sha256=saved_draft_receipt_sha256,
        expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
    assigned=load_completed_assignment(saved,assignment_receipt_path=assignment_receipt_path,assignment_receipt_sha256=assignment_receipt_sha256,
        expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
    loaded=load_completed_gtp(assigned,gtp_receipt_path=gtp_receipt_path,gtp_receipt_sha256=gtp_receipt_sha256,**args)
    qualification=None
    if read_mode=="qualified_batch":
        qualification=load_route_batch_qualification(batch_qualification_receipt_path,batch_qualification_receipt_sha256,
            saved=saved,process_id=args["process_id"],expected_document_path=args["expected_document_path"],
            expected_source_sha256=args["expected_source_sha256"],target_feature_native_id=args["target_feature_native_id"],
            target_operation_native_id=args["target_operation_native_id"],
            target_operation_setup_native_id=args["target_operation_setup_native_id"],
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,caller_path=__file__)
    context=GeneratedPlanCLContext(loaded,dict(args,output_path=output_path),project_root,
        read_mode=read_mode,qualification=qualification)
    row=context.selected(loaded["state"],args["target_feature_native_id"],args["target_operation_native_id"],0)
    counts=_record_counts(row["toolpath_record_counts"])
    siblings=[r["native_id"] for r in loaded["state"]["operations"] if r["native_id"]!=row["native_id"]]
    require(row["toolpath_generated"] is True and len(siblings)==5,"One completed target and five ungenerated siblings required")
    return export_mill_generic_cl(sw,clsid,typelib_path,
        **{k:args[k] for k in ("process_id","expected_document_path","expected_source_sha256",
            "qualification_only","acknowledge_disposable_copy","message_policy","receipt_path")},
        expected_feature_native_id=args["target_feature_native_id"],expected_operation_native_id=args["target_operation_native_id"],
        expected_mill_operation_type=0,expected_toolpath_record_counts=counts,expected_ungenerated_operation_ids=siblings,
        action="apply",acknowledge_machine_scope=acknowledge_machine_scope,output_path=output_path,_context_adapter=context)
