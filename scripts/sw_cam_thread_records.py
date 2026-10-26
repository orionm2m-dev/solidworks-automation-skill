"""只读 THREAD/GOTO/SPINDL 原生 CL 记录；不把 Height 猜成完整螺纹深度。"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path

from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_operation_profile import _number, _integer, _values
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_operation_guard import absolute_document_path, check_document_target

# 注册集成前只提供离线测试模块；这些 IID 来自安装版 CAMWorksLib25.0。
# 两条记录访问均发生原生错误；随后独立单位读取处观察到进程丢失。
# 原因尚未确定，禁止再向已知失败的记录访问 API 发送调用；无请求参数可解除。
CL_RECORD_ACCESS_DISABLED = True

REQUIRED_INTERFACES = {
    "ICWCLRecord": "{389E2D8D-138F-4EBC-ABC2-81F45B7EAE00}",
    "ICWThreadRecord": "{9AEDABDB-3752-46F7-A444-47B39D4C4F37}",
    "ICWGotoRecord": "{F49042DD-935A-4DC7-BA10-DBC8ED7E68A3}",
    "ICWSpindleRecord": "{31045094-825D-4EF0-B997-7A1034E2FDC1}",
    "ICWUnitRecord": "{CE3C70F4-D7B1-4201-91C8-47FCCA05A8D3}",
    "ICWFeedrateRecord": "{E2A45175-92D6-4D4F-A73B-2B3DFDC92C6E}",
}


def _decode(raw, typelib_path, read, row):
    base=_typed(raw,"ICWCLRecord",typelib_path)
    kind=_integer(read(base,"GetType"));row["type_raw"]=kind
    row["payload_decoded"]=False
    if kind==36:
        values=_values(read(_typed(raw,"ICWThreadRecord",typelib_path),"GetThreadRecordParams"),5)
        values=list(map(_number,values))
        row.update(kind="THREAD",end_native=values[:3],pitch_native=values[3],height_native=values[4],payload_decoded=True)
    elif kind==7:
        goto=_typed(raw,"ICWGotoRecord",typelib_path)
        row.update(kind="GOTO",rapid_line_raw=_integer(read(goto,"GetRapidLine")))
        point=_typed(read(goto,"GetToolpathPoint"),"ICWPosition",typelib_path)
        row.update(point_native=list(map(_number,_values(read(point,"GetCoordinates"),3))),payload_decoded=True)
    elif kind==8:
        values=_values(read(_typed(raw,"ICWSpindleRecord",typelib_path),"GetSpindleParams"),7)
        if type(values[6]) is not str or len(values[6])>1000:
            raise ValueError("Spindle unit string must be a bounded native BSTR")
        row.update(kind="SPINDL",speed_native=_number(values[0]),max_speed_native=_number(values[1]),
            range_native=_number(values[2]),speed_unit_raw=_integer(values[3]),
            spindle_direction_raw=_integer(values[4]),radius_native=_number(values[5]),
            unit_string_raw=values[6],payload_decoded=True)
    elif kind==24:
        value=read(_typed(raw,"ICWUnitRecord",typelib_path),"GetUnitParams")
        if type(value) is not str or len(value)>1000:
            raise ValueError("Unit record must return a bounded native BSTR")
        row.update(kind="UNITS",unit_string_raw=value,payload_decoded=True)
    elif kind==29:
        values=_values(read(_typed(raw,"ICWFeedrateRecord",typelib_path),"GetFeedrateParams"),2)
        row.update(kind="FEEDRATE",value_native=_number(values[0]),
            is_metric_raw=_integer(values[1]),payload_decoded=True)
    else:row.update(kind="UNDECODED",reason="record_type_not_in_readonly_whitelist")


def inspect_thread_records(sw, clsid, typelib_path, *, process_id, expected_document_path,
        setup_index, operation_index, expected_operation_native_id, max_records=10000,
        message_policy="vendor_default"):
    """读取指定已生成 THREAD 的有界 CL 序列；全部 CAM 记录读取均在事件订阅内。"""
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status="error",phase="preflight",may_continue=False,mutation_attempted=False,
        generation_attempted=False,model_saved=False,record_setters_called=False,
        coordinate_frame_verified=False,length_units_verified=False,thread_depth_verified=False,
        thread_form_verified=False,handedness_verified=False,production_process_qualified=False,
        full_cam_snapshot_scope="before_event_disconnect",post_cleanup_cam_read_performed=False,
        bootstrap_scope="GetCWApp_and_event_notifier_required_before_subscription",paths=[],read_count=0)
    if CL_RECORD_ACCESS_DISABLED:
        report.update(status="blocked",phase="finished",reason="CAM_CL_RECORD_ACCESS_DISABLED_AFTER_NATIVE_FAILURES",
            blocked_methods=["GetRecordAtIndex","GetEnumRecords"],readback_verified=False,
            limitation="Both accessors returned 0x80040201; later process loss occurred at a different getter. Causality unresolved; no retry permitted.")
        return report
    session=None
    try:
        for name,value,low,high in (("process_id",process_id,1,4294967295),
                ("setup_index",setup_index,0,511),("operation_index",operation_index,0,511),
                ("expected_operation_native_id",expected_operation_native_id,1,4294967295),
                ("max_records",max_records,1,100000)):
            if type(value) is not int or not low<=value<=high:raise ValueError("Invalid strict selector: "+name)
        if type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.casefold()!=".sldprt":
            raise ValueError("Exact absolute saved part required")
        if message_policy!="vendor_default":raise ValueError("Only vendor_default is supported")
        def sw_identity():
            if _integer(_member(sw,"GetProcessID"))!=process_id:raise ValueError("Exact SOLIDWORKS PID mismatch")
            current=document_snapshot(sw)
            if current is None or current["type"]!=1:raise ValueError("Active saved part required")
            check_document_target(current["path"],current["title"],expected_path=expected_document_path,required=True)
            return current
        before=sw_identity();initial_file_hash=_file_hash(before["path"])
        report.update(document_before=before,saved_file_sha256_before=initial_file_hash)
        addin=_member(sw,"GetAddInObject",clsid)
        if addin is None:raise ValueError("CAM add-in must already be loaded")
        app=_typed(_member(addin,"GetCWApp"),"ICWApp4",typelib_path)
        session=CamMessageSession(app,typelib_path)
        def local():
            summary=session.summary();report["messages"]=summary
            if not summary.get("active") or not summary.get("subscribed") or any(summary.get(key) for key in
                    ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
                raise ValueError("CAM event requires review; no further native reads")
        def boundary():
            local()
            if sw_identity()!=before:raise ValueError("Document state changed during record inspection")
            local()
        def read(obj,name,*args):
            report["phase"]=name;local();value=_member(obj,name,*args);local();return value
        with session:
            boundary()
            _before,doc,_part,machine,_app=_context(sw,clsid,typelib_path,read)
            initial=_inventory(machine,typelib_path,read);report["inventory_before"]=initial
            selected=next((x for x in initial["operations"] if x["setup_index"]==setup_index and x["operation_index"]==operation_index),None)
            if selected is None or selected["turn_operation_type"]!=12 or selected["toolpath_generated"] is not True:
                raise ValueError("Exact selected THREAD type12 must already have a generated toolpath")
            setups=_items(read(machine,"IGetEnumOpSetups"),typelib_path,read)
            setup=_typed(setups[setup_index],"ICWBaseOpSetup",typelib_path)
            operations=_items(read(setup,"IGetEnumOperations"),typelib_path,read)
            operation=_typed(operations[operation_index],"ICWOperation",typelib_path)
            native_id=_object_id(doc,operation,read)
            if native_id!=expected_operation_native_id:raise ValueError("Selected native operation ID mismatch")
            report["selected_operation"]=dict(selected,native_id=native_id)
            paths=_items(read(operation,"IGetEnumToolpaths"),typelib_path,read)
            typed_paths=[_typed(raw,"ICWToolpath",typelib_path) for raw in paths]
            counts=[_integer(read(path,"RecordCount")) for path in typed_paths]
            if not counts or any(count<0 for count in counts) or sum(counts)==0 or sum(counts)>max_records:
                raise ValueError("Native total record count is empty or exceeds explicit limit")
            if counts!=selected["toolpath_record_counts"]:raise ValueError("Toolpath record counts changed")
            report["record_counts_before"]=counts
            for pi,(path,count) in enumerate(zip(typed_paths,counts)):
                boundary();rows=[];report["paths"].append(dict(path_index=pi,record_count=count,records=rows))
                # 使用文档化记录集合及已有 ICWDispatchCollection 的零基 Item 契约；
                # 不再调用在资格测试中失败的 GetRecordAtIndex，也不猜测备用索引。
                collection=_typed(read(path,"GetEnumRecords"),"ICWDispatchCollection",typelib_path)
                if _integer(read(collection,"Count"))!=count:
                    raise ValueError("CL collection count does not match toolpath RecordCount")
                for index in range(count):
                    if index%64==0:boundary()
                    row=dict(record_index=index);rows.append(row)
                    raw=read(collection,"Item",index)
                    _decode(raw,typelib_path,read,row);report["read_count"]+=1
                if _integer(read(collection,"Count"))!=count or _integer(read(path,"RecordCount"))!=count:
                    raise ValueError("Record count changed during path read")
            boundary()
            if _object_id(doc,operation,read)!=expected_operation_native_id:raise ValueError("Operation ID changed")
            final_inventory=_inventory(machine,typelib_path,read);report["inventory_after"]=final_inventory
            final_document=sw_identity();final_hash=_file_hash(before["path"])
            report.update(document_after=final_document,saved_file_sha256_after=final_hash)
            if final_inventory!=initial or final_document!=before or final_hash!=initial_file_hash:
                raise ValueError("Native inventory, document or saved file changed during read")
            local()
        summary=session.summary();report["messages"]=summary
        if summary.get("disconnected") is not True or summary.get("active") or any(summary.get(key) for key in
                ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
            raise ValueError("Event cleanup was not confirmed cleanly")
        post_document=sw_identity();post_hash=_file_hash(before["path"])
        report["post_cleanup"]=dict(document=post_document,saved_file_sha256=post_hash)
        if post_document!=before or post_hash!=initial_file_hash:raise ValueError("Document or file changed during event cleanup")
        all_rows=[row for path in report["paths"] for row in path["records"]]
        counts_by_type=Counter(row["type_raw"] for row in all_rows)
        threads=[row for row in all_rows if row["type_raw"]==36]
        report.update(status="ok",phase="finished",readback_verified=True,
            record_access="GetEnumRecords/ICWDispatchCollection.Count/Item",
            unit_strings_raw=sorted({row["unit_string_raw"] for row in all_rows if row["type_raw"]==24}),
            feedrate_records=[row for row in all_rows if row["type_raw"]==29],
            record_types={str(k):v for k,v in sorted(counts_by_type.items())},
            thread_record_count=len(threads),thread_pitch_values_native=sorted({row["pitch_native"] for row in threads}),
            thread_height_values_native=sorted({row["height_native"] for row in threads}),
            thread_record_payloads_complete=bool(threads),all_record_payloads_decoded=all(row["payload_decoded"] for row in all_rows),
            sequence_sha256=hashlib.sha256(json.dumps(report["paths"],sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest(),
            interpretation="Raw native endpoints/pitch/height only; Height is not asserted to be total radial thread depth")
    except Exception as exc:
        report.update(status="error",failed_phase=report["phase"],phase="finished",reason="CAM_THREAD_RECORD_INSPECTION_FAILED",issue=_error(exc),readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
    return report
