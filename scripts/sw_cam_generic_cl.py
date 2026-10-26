"""限定 TURN 机器范围的 generic CL 资格导出；不指定控制器，不生成或保存模型。"""
from __future__ import annotations
from pathlib import Path
import re
from scripts.sw_cam_thread_postprocess import _controller, _digest
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_operation_profile import _integer
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def export_generic_cl(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_operation_count,expected_generated_operation_count,expected_total_record_count,
        expected_source_sha256,action,qualification_only,acknowledge_machine_scope,
        message_policy="vendor_default",output_path=None,expected_state_sha256=None,receipt_path=None):
    """MCP 负责 PID 操作锁；完整读取位于单个活动 CAM 事件订阅内。"""
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status="error",phase="preflight",action=action,may_continue=False,
        mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        productionNC=False,controller_changed=False,cnc_send_attempted=False,model_saved=False,
        toolpath_generation_attempted=False,readback_verified=False,output_verified=False,
        geometry_verified=False,units_verified=False,cut_coordinates_verified=False,
        radius_vs_diameter_verified=False,tool_reference_verified=False,
        raw_output_interpreted=False,raw_CL_record_getters_used=False,tool_readers_used=False,
        export_scope="whole_current_turn_machine",selected_operation_scope=False,
        GOP_attempted=False,AFR_attempted=False,apartment_type_measured=False,
        native_hresult=None,no_retval_method=True,
        native_dispatch_pending=False,automatic_retry_permitted=False,
        bootstrap_scope="GetAddInObject/GetCWApp only before message subscription",
        full_cam_snapshot_scope="before_event_disconnect",post_cleanup_cam_read_performed=False)
    session=receipt=output=None;created=False
    try:
        for name,value,lo,hi in (("process_id",process_id,1,4294967295),
                ("expected_operation_count",expected_operation_count,1,512),
                ("expected_generated_operation_count",expected_generated_operation_count,1,512),
                ("expected_total_record_count",expected_total_record_count,1,1000000)):
            if type(value) is not int or not lo<=value<=hi:raise ValueError("Invalid strict selector: "+name)
        if expected_generated_operation_count>expected_operation_count:
            raise ValueError("Generated operation count exceeds total operations")
        if acknowledge_machine_scope is not True:raise ValueError("Explicit whole-machine scope acknowledgement required")
        if type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.casefold()!=".sldprt":
            raise ValueError("Exact absolute saved part required")
        if type(expected_source_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}",expected_source_sha256):
            raise ValueError("Explicit saved source SHA required")
        if qualification_only is not True or message_policy!="vendor_default" or action not in {"inspect","prepare","apply"}:
            raise ValueError("Explicit qualification action and vendor_default required")
        if action=="inspect":
            if any(x is not None for x in (output_path,expected_state_sha256,receipt_path)):raise ValueError("Inspect rejects output/mutation inputs")
        else:
            output=Path(output_path) if type(output_path) is str else None
            if (output is None or not output.is_absolute() or output.suffix.casefold()!=".cl"
                    or len(output.name)>80 or any(c in output.name for c in '<>:"/\\|?*\x00')
                    or not output.drive or output.drive.startswith("\\")
                    or ".." in output.parts or output.parent.exists() or output.parent.is_symlink()
                    or not output.parent.parent.is_dir()):
                raise ValueError("Output must be a new local-drive .cl file inside a new dedicated directory whose parent exists")
            output_canonical=str(output.resolve())
            if Path(output_canonical).drive.startswith("\\"):
                raise ValueError("Output must resolve to a local drive, not a network share")
            if action=="prepare" and (expected_state_sha256 is not None or receipt_path is not None):raise ValueError("Prepare cannot accept mutation receipt/hash")
        if action=="apply":
            if type(expected_state_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}",expected_state_sha256):raise ValueError("Prepared state SHA required")
            receipt=Path(receipt_path) if type(receipt_path) is str else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.casefold()!=".json" or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink():raise ValueError("New absolute unused JSON receipt required")
        def identity():
            if _integer(_member(sw,"GetProcessID"))!=process_id:raise ValueError("Exact PID mismatch")
            state=document_snapshot(sw)
            if state is None or state["type"]!=1 or state["needs_save"]:raise ValueError("Clean saved part required")
            check_document_target(state["path"],state["title"],expected_path=expected_document_path,required=True)
            if _file_hash(state["path"])!=expected_source_sha256:raise ValueError("Saved source SHA mismatch")
            return state
        initial_doc=identity()
        addin=_member(sw,"GetAddInObject",clsid)
        if addin is None:raise ValueError("CAM must already be loaded")
        app=_typed(_member(addin,"GetCWApp"),"ICWApp4",typelib_path)
        session=CamMessageSession(app,typelib_path)
        def local():
            state=session.summary();report["messages"]=state
            if not state.get("active") or not state.get("subscribed") or any(state.get(k) for k in
                    ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
                raise ValueError("CAM message/event transport requires review")
        def read(obj,name,*args):
            report["phase"]=name;local();value=_member(obj,name,*args);local();return value
        def capture(diagnostic):
            diagnostic["capture_complete"]=False
            local()
            if identity()!=initial_doc:raise ValueError("Document changed")
            _,doc,_,machine,_=_context(sw,clsid,typelib_path,read)
            inventory=_inventory(machine,typelib_path,read)
            diagnostic.update(document=initial_doc,inventory=inventory)
            operations=inventory["operations"]
            generated=sum(row["toolpath_generated"] is True for row in operations)
            records=sum(sum(row["toolpath_record_counts"]) for row in operations)
            if (len(operations)!=expected_operation_count or generated!=expected_generated_operation_count
                    or records!=expected_total_record_count):
                raise ValueError("Exact operation/generated/record counts differ")
            identities=[];diagnostic["operation_identities"]=identities
            for si,setup in enumerate(_items(read(machine,"IGetEnumOpSetups"),typelib_path,read,limit=512)):
                base=_typed(setup,"ICWBaseOpSetup",typelib_path)
                for oi,raw in enumerate(_items(read(base,"IGetEnumOperations"),typelib_path,read,limit=512-len(identities))):
                    operation=_typed(raw,"ICWOperation",typelib_path)
                    identities.append(dict(setup_index=si,operation_index=oi,native_id=_object_id(doc,operation,read)))
            if len(identities)!=len(operations) or len({row["native_id"] for row in identities})!=len(identities):
                raise ValueError("Missing or duplicate native operation IDs")
            if [(x["setup_index"],x["operation_index"]) for x in identities]!=[(x["setup_index"],x["operation_index"]) for x in operations]:
                raise ValueError("Operation identity traversal differs from inventory")
            target=_typed(machine,"ICWMachine5",typelib_path)
            controller=_controller(read(target,"GetController2"))
            if identity()!=initial_doc:raise ValueError("Document changed during capture")
            local()
            result=dict(document=initial_doc,saved_file_sha256=expected_source_sha256,inventory=inventory,
                operation_identities=identities,generated_operation_count=generated,total_record_count=records,
                controller=controller,output_native_path=str(output) if output else None,
                output_canonical_path=output_canonical if output else None)
            diagnostic.update(result,capture_complete=True)
            return result,target
        with session:
            report["before"]={}
            before,raw=capture(report["before"]);report.update(state_sha256=_digest(before),controller=before["controller"])
            report["apply_eligible"]=action!="inspect"
            if action=="apply":
                if report["state_sha256"]!=expected_state_sha256:raise ValueError("Prepared source/controller/inventory state changed")
                current,raw=capture({})
                if current!=before:raise ValueError("State changed before generic CL export")
                # 完整 QI/状态预检成功后才消费 receipt；此后的未知结果不重放。
                _write_receipt(receipt,report,create=True);created=True
                # 调用前独占创建输出目录；不覆盖输出，也不复用失败调用目录。
                output.parent.mkdir()
                if str(output.resolve())!=output_canonical or output.parent.is_symlink():
                    raise ValueError("Output directory identity changed")
                report.update(output_native_path=str(output),output_canonical_path=output_canonical,
                    phase="SaveCLFile",native_dispatch_pending=True)
                # A consumed receipt with pending dispatch is never replayable, including
                # a process crash before a final result. Persist intent before any output call.
                _write_receipt(receipt,report)
                local()
                if identity()!=initial_doc:raise ValueError("Document changed immediately before SaveCLFile")
                local()
                # ICWMachine5 继承 SaveCLFile；不额外查询已观察到 E_NOINTERFACE 的 Machine4。
                target=raw
                local()
                report.update(mutation_attempted=True,native_call_attempted=True)
                returned=_member(target,"SaveCLFile",str(output))
                report.update(native_call_returned=True,native_dispatch_pending=False,phase="SaveCLFile_returned")
                report["native_hresult"]=returned
                if type(returned) is not int or returned!=0:
                    raise ValueError("SaveCLFile has no retval; typed HRESULT must be exact S_OK integer zero")
                _write_receipt(receipt,report)
                local()
                report["after"]={}
                after,_=capture(report["after"])
                if after!=before:raise ValueError("Controller, source, operation IDs/types/generated flags/record counts changed after output")
                if output.parent.is_symlink() or str(output.resolve())!=output_canonical:
                    raise ValueError("Output path identity changed after SaveCLFile")
                if not output.is_file() or output.is_symlink() or output.stat().st_size<=0:raise ValueError("Native output file is absent or empty")
                if output.stat().st_size>64*1024*1024:raise ValueError("Native output exceeds qualification bound")
                report["output"]=dict(path=str(output),bytes=output.stat().st_size,sha256=_file_hash(output))
                report["directory_entries"]=sorted(p.name for p in output.parent.iterdir())
                if report["directory_entries"]!=[output.name]:raise ValueError("Native exporter created unexpected additional outputs; review directory without replay")
                report.update(output_verified=True,readback_verified=True)
            local()
        state=session.summary();report["messages"]=state
        if state.get("disconnected") is not True or state.get("active") or any(state.get(k) for k in
                ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
            raise ValueError("Event cleanup not confirmed cleanly")
        if identity()!=initial_doc:raise ValueError("Document changed after cleanup")
        if action=="apply":
            if (output.is_symlink() or output.parent.is_symlink() or str(output.resolve())!=output_canonical
                    or _file_hash(output)!=report["output"]["sha256"]
                    or sorted(p.name for p in output.parent.iterdir())!=[output.name]):
                raise ValueError("Output or directory changed after cleanup")
        report.update(status="review_required" if action=="apply" else "ok",phase="finished",
            reason="GENERIC_CL_REQUIRES_OFFLINE_FORMAT_UNITS_FRAME_AND_GEOMETRY_REVIEW" if action=="apply" else None,
            post_cleanup_document_file_verified=True)
    except Exception as exc:
        report.update(status="uncertain" if report["native_call_attempted"] else "error",failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False,output_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        if created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False,output_verified=False)
    return report
