"""Export one exact generated TURN1/2 operation using the current APT controller.

Reuses the qualified THREAD postprocess contract without changing that tool.
Output remains unparsed qualification evidence, not production NC or geometry proof.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_operation_profile import _integer, _values
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _controller(raw):
    is_apt,name,success=_values(raw,3)
    if type(is_apt) is not bool or type(success) is not bool or type(name) is not str or len(name)>4096 or "\x00" in name:
        raise ValueError("Controller getter requires BOOL/BSTR/BOOL OUT values")
    return dict(is_apt=is_apt,name=name,success=success)


def qualify_turn_apt_postprocess(sw,clsid,typelib_path,*,process_id,expected_document_path,
        setup_index,operation_index,expected_operation_native_id,expected_operation_type,
        expected_linked_feature_ids,expected_controller_name,expected_record_count,
        expected_source_sha256,action,qualification_only,message_policy="vendor_default",
        output_path=None,expected_state_sha256=None,receipt_path=None):
    """Read-only inspect/prepare; one output-only native PostProcess(BSTR) on apply.

    The MCP wrapper owns the PID-scoped operation lock. All CAM getters after
    GetAddInObject/GetCWApp bootstrap run inside the native message session.
    """
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status="error",phase="preflight",action=action,may_continue=False,
        mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        productionNC=False,controller_changed=False,cnc_send_attempted=False,model_saved=False,
        toolpath_generation_attempted=False,readback_verified=False,output_verified=False,
        geometry_verified=False,units_verified=False,cut_coordinates_verified=False,
        radius_vs_diameter_verified=False,tool_reference_verified=False,
        raw_output_interpreted=False,CL_read_attempted=False,tool_readers_used=False,
        native_dispatch_pending=False,automatic_retry_permitted=False,native_hresult=None,
        bootstrap_scope="GetAddInObject/GetCWApp only before message subscription",
        full_cam_snapshot_scope="before_event_disconnect",post_cleanup_cam_read_performed=False)
    session=receipt=output=None;created=False
    try:
        for name,value,lo,hi in (("process_id",process_id,1,4294967295),("setup_index",setup_index,0,511),
                ("operation_index",operation_index,0,511),("expected_operation_native_id",expected_operation_native_id,1,4294967295),
                ("expected_record_count",expected_record_count,1,100000)):
            if type(value) is not int or not lo<=value<=hi:raise ValueError("Invalid strict selector: "+name)
        if type(expected_operation_type) is not int or expected_operation_type not in {1,2}:
            raise ValueError("Only exact TURN ROUGH type1 or FINISH type2 is allowed")
        if (type(expected_linked_feature_ids) is not list or not 1<=len(expected_linked_feature_ids)<=64
                or any(type(v) is not int or not 1<=v<=4294967295 for v in expected_linked_feature_ids)
                or len(set(expected_linked_feature_ids))!=len(expected_linked_feature_ids)):
            raise ValueError("Unique exact linked feature IDs are required")
        expected_linked_feature_ids=sorted(expected_linked_feature_ids)
        if (type(expected_controller_name) is not str or not 1<=len(expected_controller_name)<=4096
                or expected_controller_name!=expected_controller_name.strip() or "\x00" in expected_controller_name):
            raise ValueError("Exact nonempty current APT controller name required")
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
            if (output is None or not output.is_absolute() or output.suffix.casefold()!=".apt"
                    or len(output.name)>80 or any(c in output.name for c in '<>:"/\\|?*\x00')
                    or ".." in output.parts or output.parent.exists() or output.parent.is_symlink()
                    or not output.parent.parent.is_dir()):
                raise ValueError("Output must be a new .apt file inside a new dedicated directory whose parent exists")
            output_canonical=str(output.resolve())
            if action=="prepare" and (expected_state_sha256 is not None or receipt_path is not None):raise ValueError("Prepare cannot accept mutation receipt/hash")
        if action=="apply":
            if type(expected_state_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}",expected_state_sha256):raise ValueError("Prepared state SHA required")
            receipt=Path(receipt_path) if type(receipt_path) is str else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.casefold()!=".json" or not receipt.parent.is_dir():raise ValueError("New absolute JSON receipt required")
            _write_receipt(receipt,report,create=True);created=True
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
        def capture():
            local()
            if identity()!=initial_doc:raise ValueError("Document changed")
            _,doc,_,machine,_=_context(sw,clsid,typelib_path,read)
            inventory=_inventory(machine,typelib_path,read)
            row=next((r for r in inventory["operations"] if r["setup_index"]==setup_index and r["operation_index"]==operation_index),None)
            if row is None or row["turn_operation_type"]!=expected_operation_type or row["toolpath_generated"] is not True or sum(row["toolpath_record_counts"])!=expected_record_count:
                raise ValueError("Exact generated TURN operation type and record count required")
            setups=_items(read(machine,"IGetEnumOpSetups"),typelib_path,read)
            ops=_items(read(_typed(setups[setup_index],"ICWBaseOpSetup",typelib_path),"IGetEnumOperations"),typelib_path,read)
            raw=ops[operation_index];operation=_typed(raw,"ICWOperation",typelib_path)
            oid=_object_id(doc,operation,read)
            if oid!=expected_operation_native_id:raise ValueError("Native operation ID mismatch")
            suppressed=read(operation,"Suppressed")
            if type(suppressed) is not bool or suppressed:
                raise ValueError("Selected operation must be explicitly unsuppressed")
            linked=_items(read(operation,"IGetAllFeatures"),typelib_path,read,limit=64)
            linked_ids=[_object_id(doc,value,read) for value in linked]
            if len(set(linked_ids))!=len(linked_ids) or sorted(linked_ids)!=expected_linked_feature_ids:
                raise ValueError("Exact linked feature IDs changed")
            controller=_controller(read(_typed(machine,"ICWMachine5",typelib_path),"GetController2"))
            if identity()!=initial_doc:raise ValueError("Document changed during capture")
            local()
            return dict(document=initial_doc,saved_file_sha256=expected_source_sha256,inventory=inventory,
                selected_operation=dict(row,native_id=oid,suppressed=suppressed,linked_feature_ids=sorted(linked_ids)),
                controller=controller,expected_controller_name=expected_controller_name,
                output_native_path=str(output) if output else None,
                output_canonical_path=output_canonical if output else None),raw
        with session:
            before,raw=capture();report.update(before=before,state_sha256=_digest(before),controller=before["controller"])
            eligible=(before["controller"]["success"] is True and before["controller"]["is_apt"] is True
                and before["controller"]["name"]==expected_controller_name)
            report["apply_eligible"]=eligible and action!="inspect"
            if action!="inspect" and not eligible:raise ValueError("Current controller must be APT with the exact expected name")
            if action=="apply":
                if report["state_sha256"]!=expected_state_sha256:raise ValueError("Prepared source/controller/inventory state changed")
                current,raw=capture()
                if current!=before:raise ValueError("State changed before post-processing")
                # 调用前独占创建输出目录；不覆盖输出，也不复用失败调用目录。
                output.parent.mkdir()
                if str(output.resolve())!=output_canonical or output.parent.is_symlink():
                    raise ValueError("Output directory identity changed")
                report.update(output_native_path=str(output),output_canonical_path=output_canonical,
                    phase="PostProcess",native_dispatch_pending=True)
                # A consumed receipt with pending dispatch is never replayable, including
                # a process crash before a final result. Persist intent before any output call.
                _write_receipt(receipt,report)
                local()
                if identity()!=initial_doc:raise ValueError("Document changed immediately before PostProcess")
                local()
                turn=_typed(raw,"ICWTurnOperation",typelib_path)
                local()
                report.update(mutation_attempted=True,native_call_attempted=True)
                returned=_member(turn,"PostProcess",str(output))
                report.update(native_call_returned=True,native_dispatch_pending=False,phase="PostProcess_returned",native_hresult=returned)
                if type(returned) is not int or returned!=0:
                    raise ValueError("PostProcess has no retval; typed HRESULT must be exact S_OK integer zero")
                _write_receipt(receipt,report)
                local()
                after,_=capture();report["after"]=after
                if after!=before:raise ValueError("Controller, source or operation inventory changed after output")
                if output.parent.is_symlink() or str(output.resolve())!=output_canonical:
                    raise ValueError("Output path identity changed after PostProcess")
                if not output.is_file() or output.is_symlink() or output.stat().st_size<=0:raise ValueError("Native output file is absent or empty")
                if output.stat().st_size>64*1024*1024:raise ValueError("Native output exceeds qualification bound")
                report["output"]=dict(path=str(output),bytes=output.stat().st_size,sha256=_file_hash(output))
                report["directory_entries"]=sorted(p.name for p in output.parent.iterdir())
                if report["directory_entries"]!=[output.name]:raise ValueError("Postprocessor created unexpected additional outputs; review directory without replay")
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
            reason="QUALIFICATION_APT_REQUIRES_OFFLINE_UNITS_FRAME_AND_TOOL_REFERENCE_PROOF" if action=="apply" else None,
            post_cleanup_document_file_verified=True)
    except Exception as exc:
        report.update(status="uncertain" if report["native_call_attempted"] else "error",failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False,output_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        if created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False,output_verified=False)
    return report
