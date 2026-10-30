"""Bounded machine-scope generic CL export for an exact generated MILL inventory.

Reuses guarded MILL captures and the qualified TURN SaveCLFile contract.
No generation, model save, controller assignment or CL record access.
An exported file does not qualify physical units, coordinates or geometry.
"""
from __future__ import annotations

from scripts.sw_cam_cl_inventory import generated_operation_contract, verify_export_operation_inventory
from pathlib import Path
import re

from scripts.sw_cam_mill_feature_context import (load_selected_mill_context,
    capture_selected_mill_context, selected_context_identity)
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_feature_process import capture_mill_feature_state
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_toolpath import _selected
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_thread_postprocess import _controller, _digest
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def validate_mill_cl_request(*, process_id, expected_document_path,
        expected_source_sha256, expected_feature_native_id,
        expected_operation_native_id, expected_mill_operation_type,
        expected_toolpath_record_counts, expected_ungenerated_operation_ids,
        action, qualification_only, acknowledge_disposable_copy,
        acknowledge_machine_scope, message_policy="vendor_default",
        output_path=None, expected_state_sha256=None, receipt_path=None,
        expected_generated_operations=None):
    """Pure input/file preflight; no COM calls or filesystem writes."""
    for name, value, lower in (
        ("process_id", process_id, 1),
        ("expected_feature_native_id", expected_feature_native_id, 1),
        ("expected_operation_native_id", expected_operation_native_id, 1),
        ("expected_mill_operation_type", expected_mill_operation_type, 0),
    ):
        if type(value) is not int or not lower <= value <= 0xFFFFFFFF:
            raise ValueError("Strict bounded integer required: " + name)
    generated_operation_contract(expected_operation_native_id, expected_toolpath_record_counts,
        expected_ungenerated_operation_ids, expected_generated_operations)
    counts = expected_toolpath_record_counts
    if (type(counts) is not list or not 1 <= len(counts) <= 32
            or any(type(v) is not int or not 0 <= v <= 100000 for v in counts)
            or not 1 <= sum(counts) <= 100000):
        raise ValueError("Exact generated path record counts required")
    siblings = expected_ungenerated_operation_ids
    if (type(siblings) is not list or len(siblings) > 31
            or any(type(v) is not int or not 1 <= v <= 0xFFFFFFFF for v in siblings)
            or len(set(siblings)) != len(siblings)
            or expected_operation_native_id in siblings):
        raise ValueError("Exact unique ungenerated sibling operation IDs required")
    if (type(expected_document_path) is not str
            or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold() != ".sldprt"):
        raise ValueError("Exact absolute saved part required")
    if (type(expected_source_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256)):
        raise ValueError("Explicit saved source SHA required")
    if (qualification_only is not True or acknowledge_disposable_copy is not True
            or acknowledge_machine_scope is not True):
        raise ValueError("Explicit disposable qualification and machine-scope acknowledgements required")
    if message_policy != "vendor_default" or action not in {"inspect", "prepare", "apply"}:
        raise ValueError("Explicit qualification action and vendor_default required")
    if action == "inspect":
        if any(v is not None for v in (output_path, expected_state_sha256, receipt_path)):
            raise ValueError("Inspect rejects output/mutation inputs")
        return
    output = Path(output_path) if type(output_path) is str else None
    if (output is None or not output.is_absolute() or output.suffix.casefold() != ".cl"
            or len(output.name) > 80 or any(c in output.name for c in '<>:"/\\|?*\x00')
            or not output.drive or output.drive.startswith("\\")
            or ".." in output.parts or output.parent.exists() or output.parent.is_symlink()
            or not output.parent.parent.is_dir()):
        raise ValueError("New local-drive .cl in an exclusive new directory required")
    if Path(output.resolve()).drive.startswith("\\"):
        raise ValueError("Output must resolve to a local drive")
    if action == "prepare":
        if expected_state_sha256 is not None or receipt_path is not None:
            raise ValueError("Prepare rejects mutation receipt/hash")
    else:
        if (type(expected_state_sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", expected_state_sha256)):
            raise ValueError("Prepared state SHA required")
        receipt = Path(receipt_path) if type(receipt_path) is str else None
        if (receipt is None or not receipt.is_absolute()
                or receipt.suffix.casefold() != ".json" or not receipt.parent.is_dir()
                or receipt.exists() or receipt.is_symlink()):
            raise ValueError("New absolute unused JSON receipt required")


def export_mill_generic_cl(sw, clsid, typelib_path, *, process_id,
        expected_document_path, expected_source_sha256, expected_feature_native_id,
        expected_operation_native_id, expected_mill_operation_type,
        expected_toolpath_record_counts, expected_ungenerated_operation_ids,
        action, qualification_only, acknowledge_disposable_copy,
        acknowledge_machine_scope, message_policy="vendor_default",
        output_path=None, expected_state_sha256=None, receipt_path=None,
        feature_kind='open_pocket', circle_creation_receipt_path=None, circle_creation_receipt_sha256=None, _context_adapter=None, expected_generated_operations=None):
    """The MCP wrapper holds the exact selected-process lock."""
    from scripts.sw_cam_events import CamMessageSession
    selected_context=None

    report = dict(
        status="error", phase="preflight", action=action, process_id=process_id,
        may_continue=False, apply_eligible=False,
        mutation_attempted=False, native_call_attempted=False, native_call_returned=False,
        native_dispatch_pending=False, automatic_retry_permitted=False,
        native_hresult=None, no_retval_method=True,
        export_scope="whole_current_mill_machine", selected_operation_scope=False,
        bounded_scope="One feature, one generated operation and exact ungenerated siblings",
        snapshot_scope="Captured MILL machine settings, feature, operations and controller; not whole RAM BRep or all SOLIDWORKS configurations",
        productionNC=False, production_qualified=False, model_saved=False,
        controller_changed=False, cnc_send_attempted=False,
        toolpath_generation_attempted=False, GTP_attempted=False, GOP_attempted=False,
        AFR_attempted=False, simulation_attempted=False,
        stock_edit_attempted=False, tool_edit_attempted=False,
        readback_verified=False, output_verified=False,
        geometry_verified=False, units_verified=False, physical_depth_verified=False,
        coordinate_frame_verified=False, cut_coordinates_verified=False,
        radius_vs_diameter_verified=False, tool_reference_verified=False,
        raw_output_interpreted=False, raw_CL_record_getters_used=False, tool_readers_used=False,
        bootstrap_scope="GetAddInObject/GetCWApp only before message subscription",
        full_cam_snapshot_scope="before_event_disconnect",
        post_cleanup_cam_read_performed=False, snapshot_diagnostics=[],
    )
    session = receipt = output = None
    created = False

    def persist():
        if created:
            _write_receipt(receipt, report)
            if _context_adapter is not None:
                _context_adapter.persist(report)

    def identity():
        if _context_adapter is not None:
            return _context_adapter.identity(sw)
        if selected_context is not None:
            strict_selected_document=selected_context_identity(sw,selected_context)['document']
        pid = _member(sw, "GetProcessID")
        if type(pid) is not int or pid != process_id:
            raise ValueError("Exact PID mismatch")
        model = _member(sw, "ActiveDoc")
        if model is None:
            raise ValueError("Active saved part required")
        doc = dict(path=_member(model, "GetPathName"), title=_member(model, "GetTitle"),
                   type=_member(model, "GetType"), needs_save=_member(model, "GetSaveFlag"))
        if (type(doc["type"]) is not int or doc["type"] != 1
                or type(doc["needs_save"]) is not bool or doc["needs_save"]):
            raise ValueError("Clean saved part with strict native type and dirty flag required")
        check_document_target(doc.get("path"), doc.get("title"),
                              expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError("Saved source SHA mismatch")
        if selected_context is not None and doc!=strict_selected_document:
            raise ValueError('Selected context document changed during identity check')
        return doc

    def check(*, active=True):
        state = session.summary()
        report["messages"] = state
        if (state.get("subscribed") is not True
                or (active and state.get("active") is not True)
                or (not active and (state.get("active") is not False
                                    or state.get("disconnected") is not True))
                or any(state.get(k) for k in (
                    "event_count", "overflow", "callback_errors", "callback_error_count",
                    "subscription_error", "disconnect_errors"))):
            raise ValueError("CAM event/transport requires stop; no retry")

    def capture(phase):
        report["phase"] = phase
        persist()
        check()
        if identity() != initial_doc:
            raise ValueError("Document changed")
        diagnostic = dict(phase=phase)
        report["snapshot_diagnostics"].append(diagnostic)
        if _context_adapter is None:
            state, native = capture_selected_mill_context(
                sw, clsid, typelib_path, expected_document_path,
                expected_feature_native_id=expected_feature_native_id,
                check=check, diagnostic=diagnostic,
                context=selected_context,legacy_capture=capture_mill_feature_state)
        else:
            state, native = _context_adapter.capture(sw, clsid, typelib_path, app, check, diagnostic)
        check()
        if (state["document"] != initial_doc
                or state["saved_file_sha256"] != expected_source_sha256):
            raise ValueError("MILL snapshot document/source mismatch")
        selector = _selected if _context_adapter is None else _context_adapter.selected
        selected = selector(state, expected_feature_native_id,
                            expected_operation_native_id, expected_mill_operation_type)
        if (selected["toolpath_generated"] is not True
                or selected["toolpath_record_counts"] != expected_toolpath_record_counts):
            raise ValueError("Exact previously generated record counts required")
        verify_export_operation_inventory(state["operations"], expected_operation_native_id,
            expected_toolpath_record_counts, expected_ungenerated_operation_ids, expected_generated_operations)
        check()
        diagnostic["stage"] = "QueryInterface(ICWMachine5)"
        persist()
        target = _typed(native["machine"], "ICWMachine5", typelib_path)
        check()
        diagnostic["stage"] = "GetController2"
        persist()
        controller = _controller(_member(target, "GetController2"))
        check()
        if identity() != initial_doc:
            raise ValueError("Document changed during capture")
        check()
        snapshot = dict(
            process_id=process_id, mill_state=state, controller=controller,
            selected_feature_native_id=expected_feature_native_id,
            selected_operation_native_id=expected_operation_native_id,
            selected_mill_operation_type=expected_mill_operation_type,
            expected_toolpath_record_counts=expected_toolpath_record_counts,
            expected_ungenerated_operation_ids=expected_ungenerated_operation_ids,
            output_native_path=str(output) if output else None,
            output_canonical_path=output_canonical if output else None,
        )
        if expected_generated_operations is not None:
            snapshot["expected_generated_operations"] = generated_operation_contract(
                expected_operation_native_id, expected_toolpath_record_counts,
                expected_ungenerated_operation_ids, expected_generated_operations)
            snapshot["CL_block_order_native_qualified"] = False
        diagnostic.update(stage="complete", capture_complete=True)
        return snapshot, target

    try:
        generated_operation_contract(expected_operation_native_id, expected_toolpath_record_counts,
            expected_ungenerated_operation_ids, expected_generated_operations)
        if expected_generated_operations is not None:
            report["bounded_scope"] = "Explicit ordered generated operations and exact remaining ungenerated inventory"
            report["CL_block_order_native_qualified"] = False
        if _context_adapter is None:
            selected_context=load_selected_mill_context(process_id=process_id,
                expected_document_path=expected_document_path,expected_feature_native_id=expected_feature_native_id,
                expected_source_sha256=expected_source_sha256,feature_kind=feature_kind,
                circle_creation_receipt_path=circle_creation_receipt_path,
                circle_creation_receipt_sha256=circle_creation_receipt_sha256)
        else:
            report.update(_context_adapter.report_fields())
        validator = validate_mill_cl_request if _context_adapter is None else _context_adapter.validate
        validation_extra = dict(expected_generated_operations=expected_generated_operations) if _context_adapter is None else {}
        validator(
            process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256,
            expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_id=expected_operation_native_id,
            expected_mill_operation_type=expected_mill_operation_type,
            expected_toolpath_record_counts=expected_toolpath_record_counts,
            expected_ungenerated_operation_ids=expected_ungenerated_operation_ids,
            action=action, qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy,
            acknowledge_machine_scope=acknowledge_machine_scope, message_policy=message_policy,
            output_path=output_path, expected_state_sha256=expected_state_sha256,
            receipt_path=receipt_path, **validation_extra)
        output = Path(output_path) if output_path is not None else None
        output_canonical = str(output.resolve()) if output is not None else None
        receipt = Path(receipt_path) if receipt_path is not None else None
        initial_doc = identity()
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        session = CamMessageSession(app, typelib_path)
        with session:
            before, target = capture("capture_before")
            report.update(before=before, state_sha256=_digest(before),
                          controller=before["controller"], apply_eligible=action != "inspect")
            if action == "apply":
                if _context_adapter is None:
                    if report["state_sha256"] != expected_state_sha256:
                        raise ValueError("Prepared process/source/controller/inventory/output state changed")
                else:
                    _context_adapter.verify_before(before)
                current, target = capture("capture_immediately_before_export")
                if current != before:
                    raise ValueError("State changed before generic CL export")
                _write_receipt(receipt, report, create=True)
                created = True
                output.parent.mkdir()
                if output.parent.is_symlink() or str(output.resolve()) != output_canonical:
                    raise ValueError("Output directory identity changed")
                report.update(phase="SaveCLFile", native_dispatch_pending=True,
                              output_native_path=str(output), output_canonical_path=output_canonical)
                # Durable pending intent consumes this operation even across a crash.
                persist()
                check()
                if identity() != initial_doc:
                    raise ValueError("Document changed immediately before SaveCLFile")
                check()
                if _context_adapter is not None:
                    _context_adapter.claim(report)
                report.update(mutation_attempted=True, native_call_attempted=True)
                returned = _member(target, "SaveCLFile", str(output))
                report.update(native_call_returned=True, native_dispatch_pending=False,
                              phase="SaveCLFile_returned", native_hresult=returned)
                persist()
                if type(returned) is not int or returned != 0:
                    raise ValueError("SaveCLFile has no retval; exact integer S_OK required")
                check()
                after, _ = capture("capture_after_export")
                report["after"] = after
                if after != before:
                    raise ValueError("Source, feature, controller or operation inventory changed after output")
                if output.parent.is_symlink() or str(output.resolve()) != output_canonical:
                    raise ValueError("Output path identity changed")
                if not output.is_file() or output.is_symlink() or not 0 < output.stat().st_size <= 64*1024*1024:
                    raise ValueError("Native output absent, empty, linked or exceeds qualification bound")
                report["output"] = dict(path=str(output), bytes=output.stat().st_size,
                                        sha256=_file_hash(output))
                report["directory_entries"] = sorted(p.name for p in output.parent.iterdir())
                if report["directory_entries"] != [output.name]:
                    raise ValueError("Unexpected native additional outputs; no replay")
                report.update(output_verified=True, readback_verified=True)
            check()
        check(active=False)
        if identity() != initial_doc:
            raise ValueError("Document changed after event cleanup")
        if action == "apply":
            if (output.is_symlink() or output.parent.is_symlink()
                    or str(output.resolve()) != output_canonical
                    or _file_hash(output) != report["output"]["sha256"]
                    or sorted(p.name for p in output.parent.iterdir()) != [output.name]):
                raise ValueError("Output/directory changed after cleanup")
        report.update(status="review_required" if action == "apply" else "ok", phase="finished",
                      reason="GENERIC_CL_REQUIRES_OFFLINE_FORMAT_UNITS_FRAME_AND_GEOMETRY_REVIEW" if action == "apply" else None,
                      post_cleanup_document_file_verified=True)
    except Exception as exc:
        report.update(status="uncertain" if report["native_call_attempted"] else "error",
                      failed_phase=report["phase"], phase="finished", issue=_error(exc),
                      readback_verified=False, output_verified=False)
    finally:
        if session is not None:
            report["messages"] = session.summary()
        if created:
            try:
                persist()
            except Exception as exc:
                report.update(status="uncertain", receipt_write_error=_error(exc),
                              readback_verified=False, output_verified=False)
    return report
