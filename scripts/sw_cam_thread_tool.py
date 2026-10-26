"""精确 THREAD 操作的只读轮廓/刀具/夹持器包装；所有数据读取都在事件订阅内。"""
from __future__ import annotations
from pathlib import Path
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_operation_profile import _integer, _read_profile, _read_tool
from scripts.sw_cam_qualification_context import _holder_profile
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def inspect_thread_tool(sw, clsid, typelib_path, *, process_id, expected_document_path,
        setup_index, operation_index, expected_operation_native_id, expected_feature_native_id,
        holder_profile="operation", message_policy="vendor_default"):
    """只读现有 type12 的精确关联、刀具尺寸及可选原生夹持器曲线；首个错误立即停止。"""
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status="error",phase="preflight",may_continue=False,mutation_attempted=False,
        generation_attempted=False,model_saved=False,coordinate_frame_verified=False,units_verified=False,
        holder_fit_verified=False,thread_form_verified=False,production_process_qualified=False,
        full_cam_snapshot_scope="before_event_disconnect",post_cleanup_cam_read_performed=False,
        bootstrap_scope="GetCWApp_and_event_notifier_required_before_subscription",linked_features=[],tool={},
        holder_profile=dict(requested=holder_profile))
    session=None
    try:
        for name,value,low,high in (("process_id",process_id,1,4294967295),("setup_index",setup_index,0,511),
                ("operation_index",operation_index,0,511),("expected_operation_native_id",expected_operation_native_id,1,4294967295),
                ("expected_feature_native_id",expected_feature_native_id,1,4294967295)):
            if type(value) is not int or not low<=value<=high:raise ValueError("Invalid strict selector: "+name)
        if type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.casefold()!=".sldprt":
            raise ValueError("Exact saved part path required")
        if holder_profile not in {"none","operation"} or message_policy!="vendor_default":raise ValueError("Unsupported inspection policy")
        def identity():
            if _integer(_member(sw,"GetProcessID"))!=process_id:raise ValueError("Exact SOLIDWORKS PID mismatch")
            value=document_snapshot(sw)
            if value is None or value["type"]!=1:raise ValueError("Active saved part required")
            check_document_target(value["path"],value["title"],expected_path=expected_document_path,required=True)
            return value
        before=identity();file_before=_file_hash(before["path"])
        report.update(document_before=before,saved_file_sha256_before=file_before)
        addin=_member(sw,"GetAddInObject",clsid)
        if addin is None:raise ValueError("CAM add-in must already be loaded")
        app=_typed(_member(addin,"GetCWApp"),"ICWApp4",typelib_path)
        session=CamMessageSession(app,typelib_path)
        def local():
            summary=session.summary();report["messages"]=summary
            if not summary.get("active") or not summary.get("subscribed") or any(summary.get(key) for key in
                    ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
                raise ValueError("CAM event requires review; no further native calls")
        def boundary():
            local()
            if identity()!=before:raise ValueError("Document state changed during inspection")
            local()
        def read(obj,name,*args):
            report["phase"]=name;local();value=_member(obj,name,*args);local();return value
        with session:
            boundary();_before,doc,_part,machine,_app=_context(sw,clsid,typelib_path,read)
            initial=_inventory(machine,typelib_path,read);report["inventory_before"]=initial
            selected=next((x for x in initial["operations"] if x["setup_index"]==setup_index and x["operation_index"]==operation_index),None)
            if selected is None or selected["turn_operation_type"]!=12:raise ValueError("Selected operation must be native THREAD12")
            setups=_items(read(machine,"IGetEnumOpSetups"),typelib_path,read)
            setup=_typed(setups[setup_index],"ICWBaseOpSetup",typelib_path)
            operations=_items(read(setup,"IGetEnumOperations"),typelib_path,read)
            operation=_typed(operations[operation_index],"ICWOperation",typelib_path)
            native_id=_object_id(doc,operation,read)
            if native_id!=expected_operation_native_id:raise ValueError("Exact operation ID mismatch")
            report["selected_operation"]=dict(selected,native_id=native_id)
            features=_items(read(operation,"IGetAllFeatures"),typelib_path,read,limit=64)
            feature_ids=[_object_id(doc,item,read) for item in features]
            report["linked_feature_ids"]=feature_ids
            if feature_ids!=[expected_feature_native_id]:raise ValueError("Exact sole linked feature ID mismatch")
            budget=[0]
            for raw in features:
                row={};report["linked_features"].append(row)
                _read_profile(raw,typelib_path,read,budget,row,
                    collection_reader=lambda value,limit:_items(value,typelib_path,read,limit=limit))
            boundary()
            raw_tool=read(operation,"IGetTool")
            if raw_tool is not None and bool(raw_tool):
                tool=_typed(raw_tool,"ICWTool",typelib_path)
                kind=_integer(read(tool,"ToolType"))
                report["tool"].update(native_id=_object_id(doc,tool,read),tool_type_raw=kind)
                if kind!=15:raise ValueError("Selected THREAD tool is not a native turning tool")
            _read_tool(raw_tool,operation,typelib_path,read,report["tool"])
            if (report["tool"].get("present") and report["tool"].get("parameters_status") != "unavailable"
                    and holder_profile=="operation"):
                turn=_typed(raw_tool,"ICWTurnTool",typelib_path)
                raw_holder=read(turn,"IGetTurnToolHolder")
                if raw_holder is None or not bool(raw_holder):
                    report["holder_profile"].update(available=False,reason="native_holder_is_null")
                else:
                    _holder_profile(_typed(raw_holder,"ICWTurnToolHolder",typelib_path),operation,typelib_path,
                        "operation",read,report["holder_profile"])
            boundary()
            if _object_id(doc,operation,read)!=expected_operation_native_id:raise ValueError("Operation ID changed during read")
            final_inventory=_inventory(machine,typelib_path,read)
            final_document=identity();final_hash=_file_hash(before["path"])
            report.update(inventory_after=final_inventory,document_after=final_document,saved_file_sha256_after=final_hash)
            if final_inventory!=initial or final_document!=before or final_hash!=file_before:
                raise ValueError("Inventory, document or saved file changed during inspection")
            local()
        summary=session.summary();report["messages"]=summary
        if summary.get("disconnected") is not True or summary.get("active") or any(summary.get(key) for key in
                ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
            raise ValueError("CAM event cleanup was not confirmed cleanly")
        post_document=identity();post_hash=_file_hash(before["path"])
        report["post_cleanup"]=dict(document=post_document,saved_file_sha256=post_hash)
        if post_document!=before or post_hash!=file_before:raise ValueError("Document or file changed during cleanup")
        report.update(status="ok" if report["tool"].get("present") and report["tool"].get("parameters_status") != "unavailable" else "review_required",phase="finished",
            readback_verified=True,tool_presence_verified=True)
    except Exception as exc:
        report.update(status="error",failed_phase=report["phase"],phase="finished",
            reason="CAM_THREAD_TOOL_INSPECTION_FAILED",issue=_error(exc),readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
    return report
