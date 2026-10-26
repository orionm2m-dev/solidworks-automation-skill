"""精确单线 Thread 特征的单次保留式 GOP；不保存、不生成刀路。"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import re

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_feature_attribute import _snapshot, _state_digest, _states_equal, _target_profile
from scripts.sw_operation_guard import absolute_document_path


def _verify_delta(before, after):
    old_ids = {row["native_id"] for row in before["operations"]}
    added = [row for row in after["operations"] if row["native_id"] not in old_ids]
    if len(added) != 1 or len(after["operations"]) != len(before["operations"]) + 1:
        raise ValueError("Exactly one new operation is required; never replay GOP")
    new = added[0]
    if type(new["native_id"]) is not int or new["native_id"] <= 0 or new["linked_feature_ids"] != [before["selected_feature_id"]]:
        raise ValueError("New operation must have a positive identity linked only to the selected feature")
    position = (new["setup_index"], new["operation_index"])
    entries = [row for row in after["inventory"]["operations"]
        if (row["setup_index"], row["operation_index"]) == position]
    if len(entries) != 1 or entries[0]["turn_operation_type"] != 12 or entries[0]["toolpath_generated"] or entries[0]["toolpath_record_counts"]:
        raise ValueError("New operation must be THREAD 12 without generated toolpaths")
    expected = deepcopy(after)
    expected["operations"].remove(next(row for row in expected["operations"] if row["native_id"] == new["native_id"]))
    expected["inventory"]["operations"].remove(next(row for row in expected["inventory"]["operations"]
        if (row["setup_index"], row["operation_index"]) == position))
    expected["inventory"]["operation_count"] -= 1
    for rows in (expected["operations"], expected["inventory"]["operations"]):
        for row in rows:
            if row["setup_index"] == position[0] and row["operation_index"] > position[1]:
                row["operation_index"] -= 1
    expected["document"]["needs_save"] = before["document"]["needs_save"]
    if not _states_equal(before, expected):
        raise ValueError("GOP changed existing profiles, model, file, operation links/order or toolpath record counts")
    return deepcopy(new) | deepcopy(entries[0])


def qualify_feature_operation_plan(sw, clsid, typelib_path, *, expected_document_path,
        feature_setup_index, expected_feature_native_id, expected_turn_feature_type,
        expected_feature_count, expected_operation_count, expected_operation_setup_count,
        action, qualification_only, message_policy, attribute_name,
        expected_state_sha256=None, receipt_path=None):
    """inspect/prepare 只读；apply 只调用一次 ICWFeature.GenerateOpPlan(RETAIN=1)。"""
    from scripts.sw_cam_events import CamMessageSession
    report = dict(status="error", phase="preflight", action=action, may_continue=False,
        mutation_attempted=False, native_call_returned=False, readback_verified=False,
        model_saved=False, toolpath_generation_attempted=False, persistence_verified=False,
        thread_condition_verified=False, thread_depth_verified=False, thread_pitch_verified=False,
        units_verified=False, production_process_qualified=False, snapshot_diagnostics=[],
        gop_preference=1, full_cam_snapshot_scope="before_event_disconnect",
        post_cleanup_cam_read_performed=False, toolpath_coordinates_verified=False,
        verification_scope="profiles_model_file_operation_ids_links_order_and_toolpath_record_counts",
        mass_comparison=dict(hash_significant_digits=11, relative_tolerance=1e-10,
            absolute_tolerance=0.0, raw_values_retained=True, other_state_fields="exact"))
    session = receipt = None
    created = False
    try:
        for key,value,low,high in (("feature_setup_index",feature_setup_index,0,511),
                ("expected_feature_native_id",expected_feature_native_id,1,4294967295),
                ("expected_turn_feature_type",expected_turn_feature_type,0,2147483647),
                ("expected_feature_count",expected_feature_count,1,64),
                ("expected_operation_count",expected_operation_count,0,511),
                ("expected_operation_setup_count",expected_operation_setup_count,1,512)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Invalid strict selector: " + key)
        if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold() != ".sldprt"):
            raise ValueError("An exact absolute saved part path is required")
        if qualification_only is not True or message_policy != "vendor_default" or action not in {"inspect","prepare","apply"}:
            raise ValueError("Explicit qualification action and vendor_default are required")
        if type(attribute_name) is not str or attribute_name != "Thread":
            raise ValueError("Only the observed exact Thread strategy is qualified for this action")
        if action != "apply":
            if expected_state_sha256 is not None or receipt_path is not None:
                raise ValueError("Read-only actions cannot accept mutation inputs")
        else:
            if type(expected_state_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}",expected_state_sha256):
                raise ValueError("Exact prepared state SHA is required")
            receipt = Path(receipt_path) if type(receipt_path) is str else None
            if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != ".json"
                    or not receipt.parent.is_dir()):
                raise ValueError("New absolute JSON receipt with an existing parent is required")
            _write_receipt(receipt,report,create=True); created=True
        config = dict(expected_document_path=expected_document_path,feature_setup_index=feature_setup_index,
            expected_feature_native_id=expected_feature_native_id,expected_turn_feature_type=expected_turn_feature_type,
            attribute_name=attribute_name)
        def capture(phase,boundary=lambda:None,local=lambda:None):
            report["phase"]=phase
            diagnostic={"phase":phase}; report["snapshot_diagnostics"].append(diagnostic)
            boundary()
            result=_snapshot(sw,clsid,typelib_path,config,check=local,diagnostic=diagnostic)
            boundary()
            return result
        before,native=capture("initial")
        report.update(before=before,state_sha256=_state_digest(before),selected_profile=_target_profile(before))
        for key,expected in (("feature_count",expected_feature_count),("operation_count",expected_operation_count),
                ("operation_setup_count",expected_operation_setup_count)):
            if before["inventory"][key] != expected:
                raise ValueError("Exact CAM count mismatch: " + key)
        linked=[row for row in before["operations"] if expected_feature_native_id in row["linked_feature_ids"]]
        report["linked_operations"]=linked
        if action == "inspect":
            report.update(status="ok",phase="inspected",apply_eligible=False)
            return report
        profile,catalog=_target_profile(before),before["catalog"]
        if (not catalog["names_resolved"] or type(catalog["requested_id"]) is not int
                or not 0 < catalog["requested_id"] <= 2147483647
                or profile["attribute_id_raw"] != catalog["requested_id"]
                or profile["attribute_name"] != attribute_name):
            raise ValueError("Selected feature must already have the exact current catalog strategy")
        if linked or before["document"]["needs_save"]:
            raise ValueError("GOP requires a clean saved part and no operations linked to the selected feature")
        if action == "prepare":
            report.update(status="ok",phase="prepared",apply_eligible=True)
            return report
        if report["state_sha256"] != expected_state_sha256:
            raise ValueError("Prepared feature/file/model state changed")
        session=CamMessageSession(native["app"],typelib_path)
        def local():
            summary=session.summary();report["messages"]=summary
            if not summary.get("active") or not summary.get("subscribed") or any(summary.get(key) for key in
                    ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
                raise ValueError("CAM event requires review; no further native calls")
        def boundary():
            local();current=document_snapshot(sw)
            if current is None or any(current[key] != before["document"][key] for key in ("path","title","type")):
                raise ValueError("Active document identity changed")
            local()
        with session:
            current,native=capture("before_generation",boundary,local)
            if not _states_equal(before,current):
                raise ValueError("State changed before feature GOP")
            feature=_typed(native["turn_feature"],"ICWFeature",typelib_path)
            boundary()
            if document_snapshot(sw) != before["document"]:
                raise ValueError("Document changed immediately before feature GOP")
            # 先持久记录调用意图；HRESULT 方法无 OUT，None 不是失败也不是成功证明。
            report.update(phase="GenerateOpPlan",mutation_attempted=True)
            _write_receipt(receipt,report)
            local()
            _member(feature,"GenerateOpPlan",1)
            report.update(native_call_returned=True,phase="GenerateOpPlan_returned")
            _write_receipt(receipt,report)
            local()
            after,_=capture("after_generation",boundary,local)
            report["after"]=after
            report["new_operation"]=_verify_delta(before,after)
            report["insertion_delta_verified"]=True
        summary=session.summary();report["messages"]=summary
        if summary.get("disconnected") is not True or summary.get("active") or any(summary.get(key) for key in
                ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
            raise ValueError("CAM event cleanup was not confirmed cleanly")
        report["phase"]="post_cleanup_document_and_file"
        final_document=document_snapshot(sw);final_hash=_file_hash(before["document"]["path"])
        report["post_cleanup"]=dict(document=final_document,saved_file_sha256=final_hash)
        if final_document != after["document"] or final_hash != after["saved_file_sha256"]:
            raise ValueError("Document or saved file changed during cleanup")
        report.update(status="review_required",phase="finished",readback_verified=True,final_state=after,
            state_sha256=_state_digest(after),post_cleanup_document_and_file_verified=True,
            reason="FEATURE_PLAN_ONLY_THREAD_CONDITION_TOOL_DEPTH_AND_PERSISTENCE_UNVERIFIED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",reason="CAM_FEATURE_OPERATION_PLAN_FAILED",issue=_error(exc))
    finally:
        if session is not None:report["messages"]=session.summary()
        if created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False)
    return report
