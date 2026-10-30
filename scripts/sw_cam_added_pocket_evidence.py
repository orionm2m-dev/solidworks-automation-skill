"""Saved continuation for an additive circular pocket and its MILL definitions."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_appended_plan_evidence import AppendedPlanEvidence
from scripts.sw_cam_mill_stock_export_evidence import _require
from scripts.sw_cam_compound_plan_evidence import verify_protected_details
from scripts.sw_cam_compound_plan_delta import same_observed_context
from scripts.sw_cam_added_pocket_delta import (
    SCOPE,SKETCH_SCOPE,profile_for_action,verify_sketch_delta,verify_pocket_delta,verify_pocket_operations,
    verify_circle_observation)
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

def load_circle_route(path,sha,anchor):
    data,pin=read_pin(path,sha)
    _require(data.get("status")=="PRIMARY_CIRCULAR_POCKET_REUSE_ROUTE_V1",
        "Pinned native circle route review required")
    _require(data.get("saved_plan_sha256")==anchor.receipt_pin["sha256"],
        "Route belongs to another saved baseline")
    sources=data.get("sources")
    _require(type(sources) is list and 3<=len(sources)<=20,"Bounded primary/reuse sources required")
    route=dict(pin=pin,sources=deepcopy(sources))
    check_circle_route(route)
    return route

def check_circle_route(route):
    pin=route["pin"]
    _require(read_pin(pin["path"],pin["sha256"])[1]==pin,"Circle route pin changed")
    for pin in route["sources"]:
        _require(type(pin.get("path")) is str and Path(pin["path"]).is_file()
            and _file_hash(pin["path"])==pin["sha256"],"Circle source changed")

def validate_saved_pocket(data,previous,profile,route,*,process_id,document_path,source_sha):
    action=data["request"]["action"]
    sketch_only=action=="create_sketch"
    expected_scope=SKETCH_SCOPE if sketch_only else SCOPE
    _require(data.get("scope")==expected_scope and data.get("status")=="review_required"
        and data.get("phase")=="finished","Completed saved circle/pocket action required")
    required=("mutation_attempted","readback_verified","save_readback_verified","model_saved")
    required+=("sketch_readback_verified","sketch_save_readback_verified") if sketch_only else (
        "feature_delta_verified","circle_readback_verified","operation_delta_verified")
    for key in required:_require(data.get(key) is True,"Verified flag required: "+key)
    for key in ("native_dispatch_pending","GTP_attempted","AFR_attempted","simulation_attempted",
        "explicit_delete_attempted","global_GOP_attempted","TechDB_write_attempted",
        "stock_edit_attempted","geometry_edit_attempted","material_edit_attempted",
        "strategy_assignment_attempted","tool_assignment_attempted","automatic_replay",
        "automatic_rollback","post_cleanup_CAM_getters","production_qualified",
        "physical_depth_verified","cones_completed","production_GTP_ready"):
        _require(data.get(key) is False,"Unexpected capability flag: "+key)
    _require(not any(k in data for k in ("issue","failed_phase","receipt_write_error")),
        "Failed or uncertain action cannot anchor continuation")
    _require(type(data.get("process_id")) is int and data["process_id"]==process_id,
        "Action belongs to another owned process")
    clean_events(data)
    stages=["sketch","save_sketch"] if sketch_only else ["feature","gop","save"]
    attempts=data.get("attempts")
    _require(type(attempts) is list and [r.get("stage") for r in attempts]==stages
        and all(r.get("status")=="returned" and r.get("native_call_attempted") is True
                and r.get("native_call_returned") is True for r in attempts),"Every unique stage must have returned")
    for key in (("sketch_save_hresult",) if sketch_only else ("gop_hresult","save_hresult")):
        _require(type(data.get(key)) is int and data[key]==0,"Strict successful HRESULT required")
    _require(data["anchor"]==previous.summary() and data["profile"]==profile and data["route"]==route,
        "Saved evidence lineage differs")
    args=data["request"];spec=profile["sketch_spec"];depth=profile["depth_native"]
    previous.verify(data["before"])
    if sketch_only:
        verify_sketch_delta(data["before"],data["after_sketch"],data["created_features"],spec)
        _require(same_observed_context(data["after_sketch"],data["saved_sketch"],
            allow_dirty=True,allow_saved_source=True)
            and data["saved_sketch"]["document"]["needs_save"] is False,"Sketch save changed CAM or geometry")
        _require(data["sketch_source_sha256"]==data["saved_sketch"]["saved_file_sha256"],
            "Saved sketch source differs")
        _require(data["saved"]==data["saved_sketch"] and data["saved_details"]==data["saved_sketch_details"],
            "Sketch continuation state differs")
        phases=("before","after_sketch","saved_sketch")
        sketch_phases=("after_sketch","saved_sketch")
    else:
        new_id=data["new_feature_native_id"]
        added=verify_pocket_delta(data["before"],data["after_feature"],new_id,
            args["owner_setup_native_id"],spec,depth)
        _require(added==data["new_feature"],"Saved new feature delta differs")
        ops=verify_pocket_operations(data["after_feature"],data["after"],new_id,args["operation_setup_native_id"])
        _require(ops==data["new_operations"],"Saved new operation delta differs")
        for phase in ("after_feature","after","saved"):
            verify_circle_observation(data["circle_observations"][phase],spec,depth,new_id)
        _require(data["circle_observations"]["after_feature"]==data["circle_observations"]["after"]
            ==data["circle_observations"]["saved"],"Pocket circle metadata changed")
        _require(same_observed_context(data["after"],data["saved"],allow_dirty=True,allow_saved_source=True),
            "Final save changed captured pocket context")
        phases=("before","after_feature","after","saved")
        sketch_phases=phases
    for phase in phases:
        _require(data[phase+"_details"]==profile["details"],"Existing compound/tool details changed")
        verify_protected_details(previous,data[phase],data[phase+"_details"])
    from scripts.sw_cam_mill_units_qualification import _circle_sketch
    for phase in sketch_phases:
        _circle_sketch(data["sketch_observations"][phase],spec)
        _require(data["sketch_observations"][phase]==data["sketch_observations"][sketch_phases[0]],
            "Saved sketch observations differ")
    retained=[dict(native_id=r["native_id"],mill_operation_type=r["mill_operation_type"])
        for r in data["before"]["operations"] if r["linked_feature_ids"]==[args["reference_feature_native_id"]]]
    _require(data["retained_reference_operations"]==retained
        and data["retained_drill_operations_pending_review"] is True,"Retained drill operation restriction missing")
    current=data["saved"]
    _require(current["document"]["needs_save"] is False,"Final saved document must be clean")
    _require(data["source_before_sha256"]==args["expected_source_sha256"]
        ==previous.state["saved_file_sha256"],"Original saved source differs")
    _require(data["source_after_sha256"]==data["saved_file_sha256"]
        ==current["saved_file_sha256"]==source_sha,"Final saved source differs")
    _require(data["continuation_state"]==current and data["state_sha256"]==_digest(current),
        "Continuation digest differs")
    check_document_target(current["document"]["path"],current["document"]["title"],
        expected_path=document_path,required=True)
    return True

class AddedPocketEvidence(AppendedPlanEvidence):
    def __init__(self,data,pin,previous,route):
        super().__init__(data,pin,previous,previous.profile)
        self.route=deepcopy(route)
        self.pins += [deepcopy(route["pin"])]+deepcopy(route["sources"])
    def check_files(self):
        super().check_files();check_circle_route(self.route)
    def summary(self):
        return dict(scope="MILL_ADDED_CIRCLE_SKETCH_CONTINUATION_V1"
                if self.data["scope"]==SKETCH_SCOPE else "MILL_ADDED_POCKET_CONTINUATION_V1",
            saved_pocket_receipt=deepcopy(self.receipt_pin),
            saved_source_sha256=self.data["saved_file_sha256"],process_id=self.data["process_id"],
            selected=deepcopy(self.selected),operation_native_ids=list(self.operation_ids),
            tool_native_id=self.tool_id,added_feature_native_id=self.data.get("new_feature_native_id"),
            added_operation_native_ids=[r["native_id"] for r in self.data.get("new_operations",[])],
            previous_anchor=deepcopy(self.data["anchor"]),full_inventory_verified=False,
            world_geometry_verified=False,production_qualified=False,cones_completed=False)

def load_added_pocket_evidence(path,sha,*,process_id,expected_document_path,
        expected_source_sha256,expected_feature_native_id,expected_operation_native_ids,
        expected_operation_setup_native_id,expected_tool_native_id):
    from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
    data,pin=read_pin(path,sha)
    _require(data.get("scope") in (SCOPE,SKETCH_SCOPE),"Saved additive circle/pocket receipt required")
    args=data["request"]
    binding=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_feature_native_id=expected_feature_native_id,
        expected_operation_native_ids=expected_operation_native_ids,
        expected_operation_setup_native_id=expected_operation_setup_native_id,
        expected_tool_native_id=expected_tool_native_id)
    for key,value in binding.items():
        _require(type(args.get(key)) is type(value) and args[key]==value,"Protected scope differs: "+key)
    prior,_=read_pin(args["saved_plan_receipt_path"],args["saved_plan_receipt_sha256"])
    expected_prior="MILL_APPEND_OPERATIONS_V1" if data["scope"]==SKETCH_SCOPE else SKETCH_SCOPE
    _require(prior.get("scope")==expected_prior,"Exact prior circle-plan scope required; no recursive creation")
    previous=load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],args["saved_plan_receipt_sha256"],
        expected_source_sha256=data["source_before_sha256"],**binding,
        **{k:args.get(k) for k in ('session_rebind_receipt_path','session_rebind_receipt_sha256')})
    profile=profile_for_action(previous,args)
    route_anchor=previous if data["scope"]==SKETCH_SCOPE else previous.previous
    route=load_circle_route(args["route_receipt_path"],args["route_receipt_sha256"],route_anchor)
    validate_saved_pocket(data,previous,profile,route,process_id=process_id,
        document_path=expected_document_path,source_sha=expected_source_sha256)
    result=AddedPocketEvidence(data,pin,previous,route)
    result.check_files();result.check_runtime_identity()
    return result
