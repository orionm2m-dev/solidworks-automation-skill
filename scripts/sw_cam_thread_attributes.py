"""精确 THREAD/关联特征的有界属性读取；不推断深度、单位或条件含义。"""
from __future__ import annotations
from pathlib import Path
import re
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_cam_thread_feature_attributes import read_feature_attributes
from scripts.sw_operation_guard import absolute_document_path, check_document_target, solidworks_operation_lock


def _capture(sw, clsid, typelib_path, config, read, check, identity, result):
    """仅使用已支持的身份、关联与库存 getter；不读取刀具或 CL 内容。"""
    result["capture_complete"]=False
    check(); result["document"]=identity()
    _,doc,_,machine,_=_context(sw,clsid,typelib_path,read)
    result["inventory"]=_inventory(machine,typelib_path,read)
    setups=_items(read(machine,"IGetEnumOpSetups"),typelib_path,read)
    si=config["setup_index"]; oi=config["operation_index"]
    if si>=len(setups):raise ValueError("Selected operation setup absent")
    operations=_items(read(_typed(setups[si],"ICWBaseOpSetup",typelib_path),"IGetEnumOperations"),typelib_path,read)
    if oi>=len(operations):raise ValueError("Selected operation absent")
    operation=_typed(operations[oi],"ICWOperation",typelib_path)
    operation_id=_object_id(doc,operation,read)
    if operation_id!=config["expected_operation_native_id"]:raise ValueError("Exact operation ID mismatch")
    kind=read(_typed(operation,"ICWTurnOperation",typelib_path),"OpernType")
    if type(kind) is not int or kind!=12:raise ValueError("Selected operation must be native THREAD type12")
    suppressed=read(operation,"Suppressed")
    if type(suppressed) is not bool:raise ValueError("Suppression state must be Boolean")
    linked=_items(read(operation,"IGetAllFeatures"),typelib_path,read,limit=64)
    ids=[_object_id(doc,item,read) for item in linked]
    result["selected_operation"]=dict(setup_index=si,operation_index=oi,native_id=operation_id,
        turn_operation_type=kind,suppressed=suppressed,linked_feature_ids=ids)
    if ids!=[config["expected_feature_native_id"]]:raise ValueError("Exact sole linked feature ID mismatch")
    feature=_typed(linked[0],"ICWFeature",typelib_path)
    turn=_typed(linked[0],"ICWTurnFeature",typelib_path)
    metadata={"native_id":ids[0]};result["feature"]=metadata
    for field,obj,name,expected_type in (("name",feature,"FeatureName",str),
            ("feature_type_raw",feature,"FeatType",int),("turn_feature_type_raw",turn,"GetTurnFeatureType",int),
            ("attribute_id_raw",turn,"Attribute",int),("attribute_name",turn,"GetAttributeName",str)):
        value=read(obj,name)
        if type(value) is not expected_type or (expected_type is str and len(value)>1000):
            raise ValueError("Unexpected bounded feature metadata: "+name)
        metadata[field]=value
    check()
    if identity()!=result["document"]:raise ValueError("Document changed during identity capture")
    result["capture_complete"]=True
    return feature


def inspect_thread_feature_attributes(sw,clsid,typelib_path,*,process_id,expected_document_path,
        setup_index,operation_index,expected_operation_native_id,expected_feature_native_id,
        expected_source_sha256,receipt_path,message_policy="vendor_default"):
    """一个尚未现场资格验证的属性 getter；调用前持久化意图，任何错误均不重试。"""
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status="error",phase="validation",may_continue=False,mutation_attempted=False,
        GOP_attempted=False,GTP_attempted=False,model_saved=False,tool_readers_used=False,
        CL_read_attempted=False,attribute_read_intent=False,readback_verified=False,
        field_semantics_verified=False,units_verified=False,total_thread_depth_verified=False,
        thread_condition_verified=False,production_ready=False,
        full_cam_snapshot_scope="before_event_disconnect",post_cleanup_cam_read_performed=False,
        inventory_evidence_scope="counts_types_generated_flags_and_record_counts_not_full_toolpath_geometry",
        bootstrap_scope="GetAddInObject/GetCWApp only; required before subscription")
    session=None;receipt_created=False
    try:
        for name,value,lo,hi in (("process_id",process_id,1,2**32-1),("setup_index",setup_index,0,511),
                ("operation_index",operation_index,0,511),("expected_operation_native_id",expected_operation_native_id,1,2**32-1),
                ("expected_feature_native_id",expected_feature_native_id,1,2**32-1)):
            if type(value) is not int or not lo<=value<=hi:raise ValueError("Invalid strict selector: "+name)
        if type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.casefold()!=".sldprt":
            raise ValueError("Exact absolute saved part required")
        if type(expected_source_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}",expected_source_sha256):
            raise ValueError("Exact saved source SHA required")
        if type(receipt_path) is not str or not Path(receipt_path).is_absolute() or Path(receipt_path).suffix.casefold()!=".json" or not Path(receipt_path).parent.is_dir():
            raise ValueError("New absolute JSON receipt in existing directory required")
        if message_policy!="vendor_default":raise ValueError("Only vendor_default policy allowed")
        config=dict(setup_index=setup_index,operation_index=operation_index,
            expected_operation_native_id=expected_operation_native_id,expected_feature_native_id=expected_feature_native_id)
        report["request"]=dict(config,process_id=process_id,expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,message_policy=message_policy)
        def identity():
            pid=_member(sw,"GetProcessID")
            if type(pid) is not int or pid!=process_id:raise ValueError("Exact PID mismatch")
            state=document_snapshot(sw)
            if state is None or state["type"]!=1 or not state["path"]:raise ValueError("Active saved part required")
            check_document_target(state["path"],state["title"],expected_path=expected_document_path,required=True)
            if _file_hash(state["path"])!=expected_source_sha256:raise ValueError("Saved source SHA changed")
            return state
        with solidworks_operation_lock(timeout_seconds=1,process_id=process_id):
            initial=identity();report["document_before"]=initial
            report["unsaved_memory_present"]=initial["needs_save"]
            _write_receipt(receipt_path,report,create=True);receipt_created=True
            addin=_member(sw,"GetAddInObject",clsid)
            if addin is None:raise ValueError("CAM add-in must already be loaded")
            app=_typed(_member(addin,"GetCWApp"),"ICWApp4",typelib_path)
            session=CamMessageSession(app,typelib_path)
            def check():
                state=session.summary();report["messages"]=state
                if not state.get("active") or not state.get("subscribed") or any(state.get(k) for k in
                        ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
                    raise ValueError("CAM event transport requires review; no further CAM calls")
            def boundary():
                check()
                if identity()!=initial:raise ValueError("Active document changed")
                check()
            def read(obj,name,*args):
                report["phase"]=name;check();value=_member(obj,name,*args);check();return value
            with session:
                boundary();report["before"]={}
                feature=_capture(sw,clsid,typelib_path,config,read,check,identity,report["before"])
                boundary()
                report.update(phase="attribute_read_intent",attribute_read_intent=True)
                _write_receipt(receipt_path,report)
                report["attribute_diagnostic"]={}
                report["attributes"]=read_feature_attributes(feature,read=read,check=boundary,diagnostic=report["attribute_diagnostic"])
                _write_receipt(receipt_path,report)
                boundary();report["after"]={}
                _capture(sw,clsid,typelib_path,config,read,check,identity,report["after"])
                if report["before"]!=report["after"]:raise ValueError("Operation, feature or inventory changed during attribute read")
                boundary()
            state=session.summary();report["messages"]=state
            if state.get("disconnected") is not True or state.get("active") or any(state.get(k) for k in
                    ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
                raise ValueError("CAM event cleanup not cleanly confirmed")
            if identity()!=initial:raise ValueError("Document changed after event cleanup")
            report.update(status="review_required",phase="finished",readback_verified=True,
                post_cleanup_document_file_verified=True,payload_read_once=True)
    except Exception as error:
        report.update(status="error",failed_phase=report["phase"],phase="finished",issue=_error(error),readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        if receipt_created:
            try:_write_receipt(receipt_path,report)
            except Exception as error:
                report.update(status="error",readback_verified=False,receipt_persist_failed=True,receipt_issue=_error(error))
    return report
