"""Saved continuation for a verified feature-local strategy and plan replacement."""
from copy import deepcopy
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_appended_plan_evidence import AppendedPlanEvidence
from scripts.sw_cam_mill_stock_export_evidence import _require
from scripts.sw_cam_compound_plan_evidence import (
    SCOPE, load_primary_route, check_primary_route, validate_replacement_baseline, verify_protected_details)
from scripts.sw_cam_compound_plan_delta import (
    same_observed_context, verify_replaced_plan, verify_strategy_details, target_tool_metadata_verified)
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

class ReplacedPlanEvidence(AppendedPlanEvidence):
    def __init__(self,data,pin,previous,route):
        super().__init__(data,pin,previous,previous.profile)
        self.route=deepcopy(route)
        self.pins += [deepcopy(route["pin"])] + deepcopy(route["sources"])
    def check_files(self):
        super().check_files()
        check_primary_route(self.route)
    def summary(self):
        return dict(scope="MILL_REPLACED_PLAN_CONTINUATION_V1",
            saved_replacement_receipt=deepcopy(self.receipt_pin),
            saved_source_sha256=self.data["saved_file_sha256"],process_id=self.data["process_id"],
            selected=deepcopy(self.selected),operation_native_ids=list(self.operation_ids),
            tool_native_id=self.tool_id,replacement_operation_native_ids=[
                r["native_id"] for r in self.data["replacement_operations"]],
            target_strategy=deepcopy(self.data["immediate_strategy"]),
            previous_anchor=deepcopy(self.data["anchor"]),original_receipts_modified=False,
            full_inventory_verified=False,world_geometry_verified=False,production_qualified=False)

def validate_saved_replacement(data,previous,profile,route,*,process_id,document_path,source_sha):
    _require(data.get("scope")==SCOPE and data.get("status")=="review_required"
        and data.get("phase")=="finished","Completed replacement save required")
    for key in ("mutation_attempted","lookup_call_attempted","lookup_call_returned",
        "strategy_assignment_attempted","attribute_call_returned","immediate_strategy_readback_verified",
        "strategy_stage_verified","GOP_attempted","gop_call_returned","operation_delta_verified",
        "save_attempted","save_call_returned","readback_verified","save_readback_verified","model_saved"):
        _require(data.get(key) is True,"Verified replacement flag required: "+key)
    for key in ("native_dispatch_pending","attribute_hresult_observable","AFR_attempted",
        "GTP_attempted","simulation_attempted","explicit_delete_attempted","global_GOP_attempted",
        "TechDB_write_attempted","stock_edit_attempted","geometry_edit_attempted","material_edit_attempted",
        "tool_assignment_attempted","automatic_replay","automatic_rollback","post_cleanup_CAM_getters",
        "production_qualified"):
        _require(data.get(key) is False,"Unexpected replacement field: "+key)
    _require(not any(k in data for k in ("issue","failed_phase","receipt_write_error")),
             "Failed replacement cannot anchor continuation")
    for key in ("gop_hresult","save_hresult"):
        _require(type(data.get(key)) is int and data[key]==0,"Strict successful native result required")
    _require(type(data.get("lookup_id")) is int and 0<data["lookup_id"]<2**31,
             "Positive resolved strategy ID required")
    _require(type(data.get("process_id")) is int and data["process_id"]==process_id,
             "Replacement belongs to another owned session")
    clean_events(data)
    attempts=data.get("attempts")
    _require(type(attempts) is list and [r.get("stage") for r in attempts]==["attribute","regenerate","save"]
        and all(r.get("status")=="returned" and r.get("native_call_attempted") is True
                and r.get("native_call_returned") is True for r in attempts),
        "Exactly the two changes and checked save must have returned")
    _require(data["anchor"]==previous.summary() and data["target_profile"]==profile
        and data["primary_route"]==route,"Replacement evidence lineage differs")
    args=data["request"]
    _require(args["requested_strategy_name"]=="Rough-Finish" and args["save_after_verified"] is True,
             "Explicit primary-reviewed strategy and checked save required")
    _require(data["immediate_strategy"]==dict(attribute_id=data["lookup_id"],
        attribute_name=args["requested_strategy_name"],active_attribute_name=args["requested_strategy_name"]),
        "Immediate exact strategy readback differs")
    previous.verify(data["before"])
    _require(data["before_details"]==profile["details"],"Saved baseline details differ")
    _require(same_observed_context(data["before"],data["after_attribute"],allow_dirty=True),
             "Strategy assignment changed operations or context")
    verify_strategy_details(data["before_details"],data["after_attribute_details"],
                            data["lookup_id"],args["requested_strategy_name"])
    replacement=verify_replaced_plan(data["after_attribute"],data["after"],
        args["target_feature_native_id"],args["target_operation_setup_native_id"])
    _require(replacement==data["replacement_operations"],"Replacement-operation proof differs")
    _require(data["after_attribute_details"]==data["after_details"]==data["saved_details"],
             "Strategy/profile/protected tool changed after assignment")
    verify_protected_details(previous,data["saved"],data["saved_details"])
    observed_tools=target_tool_metadata_verified(data.get("target_tool_observations",{}),replacement)
    _require(type(data.get("target_tool_metadata_readback_verified")) is bool
        and data["target_tool_metadata_readback_verified"] == observed_tools
        and data.get("target_tool_physical_geometry_qualified") is False,
        "Optional target tool metadata proof differs or exceeds its qualification")
    saved=data["saved"]
    _require(same_observed_context(data["after"],saved,allow_dirty=True,allow_saved_source=True),
             "Save changed captured replacement context")
    _require(data["source_before_sha256"]==args["expected_source_sha256"]==previous.state["saved_file_sha256"]
        and data["saved_file_sha256"]==data["source_after_sha256"]==saved["saved_file_sha256"]==source_sha,
        "Replacement source lineage differs")
    _require(data["continuation_state"]==saved and data["state_sha256"]==_digest(saved),
             "Replacement continuation digest differs")
    _require(type(saved["document"]["type"]) is int and saved["document"]["type"]==1
        and saved["document"]["needs_save"] is False,"Clean saved part required")
    check_document_target(saved["document"]["path"],saved["document"]["title"],
                          expected_path=document_path,required=True)
    return True

def load_replaced_plan_evidence(path,sha,*,process_id,expected_document_path,
        expected_source_sha256,expected_feature_native_id,expected_operation_native_ids,
        expected_operation_setup_native_id,expected_tool_native_id):
    from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
    from scripts.sw_cam_replace_compound_plan import TARGET_KEYS
    data,pin=read_pin(path,sha)
    _require(data.get("scope")==SCOPE,"Replacement save receipt required")
    args=data["request"]
    binding=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_feature_native_id=expected_feature_native_id,
        expected_operation_native_ids=expected_operation_native_ids,
        expected_operation_setup_native_id=expected_operation_setup_native_id,
        expected_tool_native_id=expected_tool_native_id)
    for key,value in binding.items():
        _require(type(args.get(key)) is type(value) and args[key]==value,
                 "Protected continuation scope differs: "+key)
    prior,_=read_pin(args["saved_plan_receipt_path"],args["saved_plan_receipt_sha256"])
    _require(prior.get("scope")=="MILL_APPEND_OPERATIONS_V1",
             "This replacement requires original appended save, no implicit recursion")
    previous=load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],
        args["saved_plan_receipt_sha256"],expected_source_sha256=data["source_before_sha256"],**binding)
    profile=validate_replacement_baseline(previous,**{k:args[k] for k in TARGET_KEYS})
    route=load_primary_route(args["primary_route_receipt_path"],args["primary_route_receipt_sha256"],previous)
    validate_saved_replacement(data,previous,profile,route,process_id=process_id,
        document_path=expected_document_path,source_sha=expected_source_sha256)
    result=ReplacedPlanEvidence(data,pin,previous,route)
    result.check_files(); result.check_runtime_identity()
    return result
