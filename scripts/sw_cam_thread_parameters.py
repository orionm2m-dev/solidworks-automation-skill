"""已存在 THREAD 操作的单次 Pitch 写入；保留条件、深度与单位的未知状态。"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import math
import re

from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash, _DOUBLE_METHODS, _INT_METHODS
from scripts.sw_cam_operation_profile import _number, _integer
from scripts.sw_cam_turn_feature_attribute import (_snapshot, _context, _items, _inventory,
    _state_digest, _states_equal, _target_profile)
from scripts.sw_operation_guard import absolute_document_path


def _capture(sw, clsid, typelib_path, config, selected, request, check, diagnostic):
    state,native=_snapshot(sw,clsid,typelib_path,config,check=check,diagnostic=diagnostic)
    def read(obj,name,*args):
        diagnostic["stage"]=name;check();value=_member(obj,name,*args);check();return value
    _document,doc,_part,machine,_app=_context(sw,clsid,typelib_path,read)
    setups=_items(read(machine,"IGetEnumOpSetups"),typelib_path,read)
    si,oi=selected["setup_index"],selected["operation_index"]
    if si>=len(setups):raise ValueError("Operation setup index is absent")
    setup=_typed(setups[si],"ICWBaseOpSetup",typelib_path)
    operations=_items(read(setup,"IGetEnumOperations"),typelib_path,read)
    if oi>=len(operations):raise ValueError("Operation index is absent")
    raw=operations[oi]
    native_id=_object_id(doc,raw,read)
    row=next((row for row in state["operations"] if row["setup_index"]==si and row["operation_index"]==oi),None)
    item=next((row for row in state["inventory"]["operations"] if row["setup_index"]==si and row["operation_index"]==oi),None)
    if (row is None or item is None or native_id!=selected["expected_operation_native_id"]
            or row["native_id"]!=native_id or item["turn_operation_type"]!=12
            or row["linked_feature_ids"]!=[config["expected_feature_native_id"]]):
        raise ValueError("Exact existing THREAD operation and sole linked feature are required")
    thread=_typed(raw,"ICWTurnThreadOp",typelib_path)
    values={};diagnostic["thread_parameters_native"]=values
    for name in _DOUBLE_METHODS:values[name]=_number(read(thread,name))
    for name in _INT_METHODS:values[name]=_integer(read(thread,name))
    check()
    if (document_snapshot(sw)!=state["document"] or _file_hash(state["document"]["path"])!=state["saved_file_sha256"]
            or _inventory(machine,typelib_path,read)!=state["inventory"]):
        raise ValueError("Document, file or CAM inventory changed during scalar reads")
    check()
    state.update(thread_parameters_native=values,selected_operation=deepcopy(selected),pitch_request=deepcopy(request))
    native["thread"]=thread
    diagnostic["stage"]="complete"
    return state,native


def configure_thread_pitch(sw, clsid, typelib_path, *, expected_document_path, feature_setup_index,
        expected_feature_native_id, expected_turn_feature_type, expected_feature_count,
        expected_operation_count, expected_operation_setup_count, setup_index, operation_index,
        expected_operation_native_id, action, qualification_only, message_policy, attribute_name,
        expected_old_pitch=None, new_pitch=None, expected_state_sha256=None, receipt_path=None):
    """inspect/prepare 只读；apply 单次 SetPitchValue，读回既有 16 个安全标量。"""
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status="error",phase="preflight",action=action,may_continue=False,
        mutation_attempted=False,native_call_returned=False,readback_verified=False,
        model_saved=False,toolpath_generation_attempted=False,persistence_verified=False,
        thread_condition_verified=False,thread_depth_verified=False,units_verified=False,
        handedness_verified=False,tool_included_angle_verified=False,production_process_qualified=False,
        full_cam_snapshot_scope="before_event_disconnect",post_cleanup_cam_read_performed=False,
        toolpath_coordinates_verified=False,snapshot_diagnostics=[],
        readback_scope="one_pitch_setter_16_thread_scalars_profiles_model_file_ids_links_record_counts",
        mass_comparison=dict(hash_significant_digits=11,relative_tolerance=1e-10,absolute_tolerance=0.0,
            raw_values_retained=True,other_state_fields="exact"))
    session=receipt=None;created=False
    try:
        selectors=(("feature_setup_index",feature_setup_index,0,511),
            ("expected_feature_native_id",expected_feature_native_id,1,4294967295),
            ("expected_turn_feature_type",expected_turn_feature_type,0,2147483647),
            ("expected_feature_count",expected_feature_count,1,64),
            ("expected_operation_count",expected_operation_count,1,512),
            ("expected_operation_setup_count",expected_operation_setup_count,1,512),
            ("setup_index",setup_index,0,511),("operation_index",operation_index,0,511),
            ("expected_operation_native_id",expected_operation_native_id,1,4294967295))
        for name,value,low,high in selectors:
            if type(value) is not int or not low<=value<=high:raise ValueError("Invalid strict selector: "+name)
        if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold()!=".sldprt"):
            raise ValueError("An exact absolute saved part path is required")
        if qualification_only is not True or message_policy!="vendor_default" or attribute_name!="Thread" or action not in {"inspect","prepare","apply"}:
            raise ValueError("Explicit Thread qualification and vendor_default are required")
        if action=="inspect":
            if any(value is not None for value in (expected_old_pitch,new_pitch,expected_state_sha256,receipt_path)):
                raise ValueError("Inspect cannot accept mutation inputs")
        else:
            for name,value,zero in (("expected_old_pitch",expected_old_pitch,True),("new_pitch",new_pitch,False)):
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1e6 or (not zero and value==0):
                    raise ValueError("Invalid finite native pitch: "+name)
            if expected_old_pitch==new_pitch:raise ValueError("Unchanged Pitch must not be written")
        if action!="apply":
            if expected_state_sha256 is not None or receipt_path is not None:raise ValueError("Read-only actions cannot accept receipt/hash")
        else:
            if type(expected_state_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}",expected_state_sha256):
                raise ValueError("Exact prepared state SHA is required")
            receipt=Path(receipt_path) if type(receipt_path) is str else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.casefold()!=".json" or not receipt.parent.is_dir():
                raise ValueError("New absolute JSON receipt with existing parent is required")
            _write_receipt(receipt,report,create=True);created=True
        config=dict(expected_document_path=expected_document_path,feature_setup_index=feature_setup_index,
            expected_feature_native_id=expected_feature_native_id,expected_turn_feature_type=expected_turn_feature_type,attribute_name=attribute_name)
        selected=dict(setup_index=setup_index,operation_index=operation_index,expected_operation_native_id=expected_operation_native_id)
        request=dict(expected_old_pitch=expected_old_pitch,new_pitch=new_pitch)
        def capture(phase,boundary=lambda:None,local=lambda:None):
            report["phase"]=phase;diagnostic={"phase":phase};report["snapshot_diagnostics"].append(diagnostic)
            boundary();value=_capture(sw,clsid,typelib_path,config,selected,request,local,diagnostic);boundary();return value
        before,native=capture("initial")
        report.update(before=before,state_sha256=_state_digest(before))
        for key,expected in (("feature_count",expected_feature_count),("operation_count",expected_operation_count),
                ("operation_setup_count",expected_operation_setup_count)):
            if before["inventory"][key]!=expected:raise ValueError("Exact CAM count mismatch: "+key)
        if action=="inspect":
            report.update(status="ok",phase="inspected",apply_eligible=False);return report
        profile,catalog=_target_profile(before),before["catalog"]
        if (not catalog["names_resolved"] or type(catalog["requested_id"]) is not int or catalog["requested_id"]<=0
                or profile["attribute_id_raw"]!=catalog["requested_id"] or profile["attribute_name"]!="Thread"):
            raise ValueError("Selected feature must retain the exact current Thread strategy")
        item=next(row for row in before["inventory"]["operations"] if row["setup_index"]==setup_index and row["operation_index"]==operation_index)
        if before["document"]["needs_save"] or item["toolpath_generated"] or item["toolpath_record_counts"]:
            raise ValueError("Pitch qualification requires a clean part and no selected toolpath")
        if before["thread_parameters_native"]["GetPitchValue"]!=expected_old_pitch:
            raise ValueError("Expected old native Pitch differs")
        if action=="prepare":report.update(status="ok",phase="prepared",apply_eligible=True);return report
        if report["state_sha256"]!=expected_state_sha256:raise ValueError("Prepared state changed")
        session=CamMessageSession(native["app"],typelib_path)
        def local():
            summary=session.summary();report["messages"]=summary
            if not summary.get("active") or not summary.get("subscribed") or any(summary.get(key) for key in
                    ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
                raise ValueError("CAM event requires review; no further native calls")
        def boundary():
            local();current=document_snapshot(sw)
            if current is None or any(current[key]!=before["document"][key] for key in ("path","title","type")):
                raise ValueError("Active document identity changed")
            local()
        with session:
            current,native=capture("before_write",boundary,local)
            if not _states_equal(before,current):raise ValueError("State changed before Pitch setter")
            boundary()
            if document_snapshot(sw)!=before["document"]:raise ValueError("Document changed before Pitch setter")
            report.update(phase="SetPitchValue",mutation_attempted=True);_write_receipt(receipt,report)
            local();_member(native["thread"],"SetPitchValue",float(new_pitch))
            report.update(native_call_returned=True,phase="SetPitchValue_returned");_write_receipt(receipt,report);local()
            boundary();readback=_number(_member(native["thread"],"GetPitchValue"));local()
            report["pitch_readback_native"]=readback
            if readback!=new_pitch:raise ValueError("Immediate native Pitch readback mismatch")
            report["scalar_readback_verified"]=True;_write_receipt(receipt,report)
            after,_=capture("after_write",boundary,local);report["after"]=after
            expected=deepcopy(before);expected["document"]["needs_save"]=after["document"]["needs_save"]
            expected["thread_parameters_native"]["GetPitchValue"]=float(new_pitch)
            expected["thread_parameters_native"]["GetActualPitchValue"]=after["thread_parameters_native"]["GetActualPitchValue"]
            if not _states_equal(expected,after):raise ValueError("Pitch write changed unrelated state or parameters")
        summary=session.summary();report["messages"]=summary
        if summary.get("disconnected") is not True or summary.get("active") or any(summary.get(key) for key in
                ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
            raise ValueError("CAM event cleanup was not confirmed cleanly")
        report["phase"]="post_cleanup_document_and_file"
        final_document=document_snapshot(sw);final_hash=_file_hash(before["document"]["path"])
        report["post_cleanup"]=dict(document=final_document,saved_file_sha256=final_hash)
        if final_document!=after["document"] or final_hash!=after["saved_file_sha256"]:raise ValueError("Document or file changed during cleanup")
        report.update(status="review_required",phase="finished",readback_verified=True,final_state=after,
            state_sha256=_state_digest(after),actual_pitch_native=after["thread_parameters_native"]["GetActualPitchValue"],
            reason="PITCH_ONLY_THREAD_CONDITION_DEPTH_TOOL_DIRECTION_AND_PERSISTENCE_UNVERIFIED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],
            phase="finished",reason="CAM_THREAD_PITCH_FAILED",issue=_error(exc))
    finally:
        if session is not None:report["messages"]=session.summary()
        if created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False)
    return report
