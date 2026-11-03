"""Read-only reconciliation of a completed feature GOP whose new block was appended.

Original mutation evidence and its once marker remain immutable. This qualifies
RAM definitions only; the appended machining order is not accepted.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from scripts import sw_cam_turn_feature_regenerate as core
from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_operation_guard import absolute_document_path

SCOPE = "TURN_RECIPE_APPENDED_DEFINITIONS_RECONCILIATION_V1"
CONFIG_KEYS = {"process_id", "expected_process_create_time", "expected_document_path", "expected_source_sha256",
    "feature_setup_index", "expected_feature_native_id", "expected_turn_feature_type", "attribute_name", "max_features", "max_operations"}


def pinned_json(path, digest):
    core.require(type(path) is str and absolute_document_path(path) and core.sha(digest), "Exact absolute evidence pin required")
    target = Path(path)
    core.require(target.is_file() and not target.is_symlink() and target.stat().st_size <= 32*1024*1024, "Bounded regular evidence file required")
    raw = target.read_bytes(); core.require(hashlib.sha256(raw).hexdigest() == digest, "Evidence bytes changed")
    return json.loads(raw.decode("utf-8-sig"))


def validate_parent(parent, *, parent_path, expected_after_state_sha256, expected_operation_order):
    core.require(parent.get("scope") == core.SCOPE and parent.get("status") == "uncertain"
        and parent.get("phase") == "finished" and parent.get("failed_phase") == "GenerateOpPlan_returned",
        "Completed uncertain GOP result required")
    core.require(parent.get("actions") == {name:dict(attempted=True,returned=True) for name in ("Attribute", "GenerateOpPlan")},
        "Both exact native mutations must have returned")
    for flag in ("native_dispatch_pending", "readback_verified", "native_recipe_ram_verified", "model_saved", "GTP_attempted", "tool_assignment_attempted"):
        core.require(parent.get(flag) is False, "Unexpected parent outcome: " + flag)
    core.require(parent.get("mutation_attempted") is True and not parent.get("receipt_write_error"), "Durable original mutation receipt required")
    messages = parent.get("messages", {})
    core.require(messages.get("subscribed") is True and messages.get("disconnected") is True and messages.get("active") is False
        and not any(messages.get(x) for x in core.EVENT_ERRORS), "Original event cleanup was not quiet")
    request = parent["request"]; config = {k:request[k] for k in CONFIG_KEYS}; policy = request["policy"]
    core.validate(config, policy)
    core.require(request["action"] == "apply" and core.key(request["receipt_path"]) == core.key(parent_path), "Original apply receipt binding differs")
    before, after_attribute, after = parent["before"], parent["after_attribute"], parent["after"]
    core.preflight(before, config, policy)
    prepared = core._digest(dict(config=config, policy=policy, state=before))
    core.require(prepared == parent["prepared_state_sha256"] == request["expected_state_sha256"], "Original prepared state binding differs")
    core.attribute_expected(before, after_attribute, config, policy)
    try:
        core.verify_delta(after_attribute, after, config, policy)
    except ValueError as exc:
        core.require(str(exc) == "Protected operation order or insertion position changed", "Original failure is not the exact replacement-position check")
    else:
        raise ValueError("This reconciliation is only for an appended replacement block")
    core.require(core.sha(expected_after_state_sha256) and core._digest(after) == expected_after_state_sha256, "Exact reviewed after-state digest required")
    core.ids(expected_operation_order)
    core.require([x["native_id"] for x in after["operations"]] == expected_operation_order, "Exact reviewed appended operation order required")
    delta = core.verify_delta(after_attribute, after, config, policy, new_position="append_definitions_only")
    identity = before["copy_file_identity"]
    core.require(after["copy_file_identity"] == identity, "Copy file identity changed during GOP")
    marker = core.marker_path(config, identity)
    core.require(core.key(marker) == core.key(parent["marker_path"]), "Original once marker location differs")
    marker_sha = _file_hash(marker)
    claim = pinned_json(str(marker), marker_sha)
    expected = dict(scope=core.SCOPE,status="claimed_no_replay",copy_file_identity=identity,
        feature_native_id=config["expected_feature_native_id"],source_sha256=config["expected_source_sha256"],
        receipt_path=request["receipt_path"],prepared_state_sha256=prepared)
    core.require(type(claim) is dict and set(claim) == set(expected)
        and type(claim["receipt_path"]) is str and core.key(claim["receipt_path"]) == core.key(expected["receipt_path"]),
        "Original once marker receipt binding differs")
    comparable = dict(claim, receipt_path=expected["receipt_path"])
    core.require(comparable == expected, "Original once marker content differs")
    return config, policy, after, delta, dict(path=str(marker),sha256=marker_sha)


def reconcile_turn_feature_recipe(sw, clsid, typelib_path, *, process_id, expected_process_create_time,
        expected_document_path, expected_source_sha256, parent_receipt_path, parent_receipt_sha256,
        expected_after_state_sha256, expected_operation_order, receipt_path, acknowledge_append_definitions_only):
    report = dict(scope=SCOPE,status="error",phase="preflight",read_only=True,mutation_attempted=False,
        readback_verified=False,native_recipe_ram_verified=False,route_order_qualified=False,
        model_saved=False,GTP_attempted=False,tool_assignment_attempted=False,toolpath_coordinates_verified=False,
        protected_CL_bytes_compared=False,all_nc_parameters_verified=False,persistence_verified=False,
        production_qualified=False,full_model_geometry_verified=False,
        nc_parameter_scope=["ICWTurnNCParam.GetSpndlSpeed", "ICWTurnNCParam.GetFeedRateIPM"],
        tool_geometry_scope="existing_profile_and_diamond_crib_getters_only",
        document_verification_scope="path_title_type_expected_dirty_flag_and_saved_file_hash",
        snapshots=[],guarded_member_reads=0)
    session = None; output = None; created = False
    try:
        core.require(acknowledge_append_definitions_only is True, "Explicit definitions-only append review required")
        parent = pinned_json(parent_receipt_path, parent_receipt_sha256)
        config, policy, expected, delta, marker_pin = validate_parent(parent, parent_path=parent_receipt_path,
            expected_after_state_sha256=expected_after_state_sha256, expected_operation_order=expected_operation_order)
        core.require(type(process_id) is int and process_id == config["process_id"]
            and type(expected_process_create_time) in (int,float) and expected_process_create_time == config["expected_process_create_time"]
            and core.key(expected_document_path) == core.key(config["expected_document_path"])
            and expected_source_sha256 == config["expected_source_sha256"], "Exact original process/copy binding required")
        core.require(type(receipt_path) is str and absolute_document_path(receipt_path), "Absolute fresh reconciliation receipt required")
        output = Path(receipt_path)
        core.require(output.suffix.lower() == ".json" and output.parent.is_dir() and not output.exists() and not output.is_symlink(), "Fresh reconciliation receipt required")
        report.update(parent_receipt_pin=dict(path=parent_receipt_path,sha256=parent_receipt_sha256),
            marker_pin=marker_pin,request=dict(config,policy=deepcopy(policy)),expected_after_state_sha256=expected_after_state_sha256,
            expected_operation_order=expected_operation_order,delta=delta,position_policy="append_definitions_only")
        _write_receipt(output,report,create=True);created=True
        core.require(core.files(config,policy) == expected["copy_file_identity"], "Original saved copy identity changed")
        core.isolated(sw,config,lambda:None)
        _,_,_,_,app = core.recipe._context(sw,clsid,typelib_path,_member)
        session = CamMessageSession(app,typelib_path)
        def check():
            messages = session.summary();report["messages"] = messages
            core.require(messages.get("active") is True and messages.get("subscribed") is True
                and not any(messages.get(x) for x in core.EVENT_ERRORS), "CAM event requires stop")
        with session:
            for phase in ("before", "after"):
                report["phase"] = phase
                state,_ = core.capture(sw,clsid,typelib_path,config,policy,report,clean=False,check=check)
                report[phase] = state;_write_receipt(output,report)
                core.require(state == expected, "Current RAM definitions differ from the completed GOP snapshot")
            check()
        messages = session.summary();report["messages"] = messages
        core.require(messages.get("subscribed") is True and messages.get("disconnected") is True and messages.get("active") is False
            and not any(messages.get(x) for x in core.EVENT_ERRORS), "Reconciliation event cleanup uncertain")
        core.require(document_snapshot(sw) == expected["document"] and core.files(config,policy) == expected["copy_file_identity"], "Post-cleanup copy changed")
        core.isolated(sw,config,lambda:None)
        pinned_json(parent_receipt_path,parent_receipt_sha256);pinned_json(marker_pin["path"],marker_pin["sha256"])
        report.update(status="review_required",phase="finished",readback_verified=True,native_recipe_ram_verified=True,
            final_state=expected,final_state_sha256=expected_after_state_sha256,original_receipt_unchanged=True,
            reason="APPENDED_DEFINITIONS_ONLY_MACHINING_ORDER_NOT_QUALIFIED")
    except Exception as exc:
        report.update(status="error",failed_phase=report["phase"],phase="finished",readback_verified=False,native_recipe_ram_verified=False,issue=_error(exc))
    finally:
        if session is not None:report["messages"] = session.summary()
        if created:
            try:_write_receipt(output,report)
            except Exception as exc:report.update(status="error",readback_verified=False,native_recipe_ram_verified=False,receipt_write_error=_error(exc))
    return report
