"""One guarded feature-dependent rough tool-diameter-percent mutation.

Prepare and apply are separate. This module never generates, deletes paths,
saves, simulates, exports, or interprets air-edge geometry.
"""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import re
import time

from scripts.sw_cam_mill_feature_context import (load_selected_mill_context,
    capture_selected_mill_context, selected_context_identity)
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_feature_process import capture_mill_feature_state, _integer
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_toolpath import _selected
from scripts.sw_cam_thread import _file_hash
from scripts.sw_operation_guard import absolute_document_path, check_document_target

from scripts.sw_cam_mill_rough_boundary import _number, _long, _stepover, _nonnull, _dispatch_feature
from scripts.sw_cam_turn_tool import _digest

MAX_NEW_READS = 24


def _percent(value):
    value = _number(value)
    if not 0 <= value <= 150:
        raise ValueError("Bounded tool-diameter percent 0..150 required")
    return value


def _verify_delta(before, after, operation_id, new_percent):
    expected = deepcopy(before)
    expected["boundary_parameters"]["tool_diameter_percent_native"] = float(new_percent)
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    old = next(row for row in before["operations"] if row["native_id"] == operation_id)
    actual = next(row for row in after["operations"] if row["native_id"] == operation_id)
    counts = actual["toolpath_record_counts"]
    if type(actual["toolpath_generated"]) is not bool or type(counts) is not list:
        raise ValueError("Strict selected generated flag/count list required")
    if len(counts) > 32 or any(type(n) is not int or not 0 <= n <= 100000 for n in counts):
        raise ValueError("Strict bounded selected counts required")
    if actual["toolpath_generated"] is True and counts == old["toolpath_record_counts"]:
        state = "generated_flag_and_counts_retained"
        gtp_eligible = False
    elif actual["toolpath_generated"] is False and all(n == 0 for n in counts):
        state = "generation_invalidated_no_calculated_records"
        gtp_eligible = True
    else:
        raise ValueError("Unknown selected toolpath delta; no generation or deletion allowed")
    target = next(row for row in expected["operations"] if row["native_id"] == operation_id)
    target["toolpath_generated"] = actual["toolpath_generated"]
    target["toolpath_record_counts"] = deepcopy(counts)
    if expected != after:
        raise ValueError("Unexpected parameter, feature, sibling or captured state delta")
    return dict(state=state, generated=actual["toolpath_generated"], record_counts=deepcopy(counts),
                no_record_GTP_precondition_met=gtp_eligible,
                GTP_authorized=False, old_path_geometry_verified=False)


def configure_mill_rough_boundary(
    sw, clsid, typelib_path, *, process_id, expected_document_path,
    expected_source_sha256, expected_feature_native_id,
    expected_operation_native_id, expected_mill_operation_type,
    expected_toolpath_record_counts, expected_ungenerated_operation_ids, qualification_only,
    acknowledge_disposable_copy, receipt_path, action,
    expected_tool_diameter_percent, new_tool_diameter_percent,
    message_policy="vendor_default", expected_state_sha256=None,
    prepare_receipt_path=None, prepare_receipt_sha256=None,
        feature_kind='open_pocket', circle_creation_receipt_path=None, circle_creation_receipt_sha256=None):
    from scripts.sw_cam_events import CamMessageSession
    selected_context=None

    report = dict(
        status="error", phase="preflight", process_id=process_id, action=action,
        read_only=action == "prepare", may_continue=False, mutation_attempted=False,
        native_dispatch_pending=False, native_read_attempted=False,
        readback_verified=False, boundary_parameters_read_complete=False,
        native_setter_attempted=False, native_setter_returned=False,
        parameter_readback_verified=False, apply_eligible=False, automatic_path_deletion=False,
        model_saved=False, AFR_attempted=False, GOP_attempted=False,
        GTP_attempted=False, simulation_attempted=False, export_attempted=False,
        stock_edit_attempted=False, tool_edit_attempted=False,
        record_access_attempted=False, units_verified=False,
        physical_depth_verified=False, coordinate_frame_verified=False, air_segment_semantics_verified=False,
        boundary_geometry_verified=False,
        production_qualified=False, post_cleanup_CAM_getters=False,
        native_reads_scope="New CAM interface queries and rough-boundary getters only; excludes existing snapshot and SOLIDWORKS identity calls",
        snapshot_scope="One feature and bounded operation inventory, document and saved source; not whole RAM BRep",
        native_reads=[], snapshot_diagnostics=[],
    )
    receipt = session = None
    created = False
    before = None
    final = None
    prep = marker = None

    def persist():
        if created:
            _write_receipt(receipt, report)

    def identity():
        if selected_context is not None:
            strict_selected_document=selected_context_identity(sw,selected_context)['document']
        pid = _member(sw, "GetProcessID")
        if type(pid) is not int or pid != process_id:
            raise ValueError("Exact SOLIDWORKS process changed")
        model = _member(sw, "ActiveDoc")
        if model is None:
            raise ValueError("Active saved part required")
        doc = dict(path=_member(model, "GetPathName"), title=_member(model, "GetTitle"),
                   type=_member(model, "GetType"), needs_save=_member(model, "GetSaveFlag"))
        if (type(doc["type"]) is not int or doc["type"] != 1
                or type(doc["needs_save"]) is not bool):
            raise ValueError("Saved part with strict native type and dirty flag required")
        check_document_target(doc.get("path"), doc.get("title"),
                              expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError("Saved source file hash changed")
        if selected_context is not None and doc!=strict_selected_document:
            raise ValueError('Selected context document changed during identity check')
        return doc

    def check(*, active=True):
        summary = session.summary()
        report["messages"] = summary
        if (summary.get("subscribed") is not True
            or (active and summary.get("active") is not True)
            or (not active and (summary.get("active") is not False
                                or summary.get("disconnected") is not True))
            or any(summary.get(k) for k in (
                "event_count", "overflow", "callback_errors", "callback_error_count",
                "subscription_error", "disconnect_errors"))):
            raise ValueError("CAM event/transport requires stop; no retry")

    def boundary():
        check()
        if before is not None:
            current = identity()
            expected = deepcopy(before["document"])
            if report["mutation_attempted"]:
                expected["needs_save"] = current["needs_save"]
            if current != expected:
                raise ValueError("Document/source changed during rough-boundary operation")
        check()

    def capture(phase):
        report["phase"] = phase
        persist()
        check()
        begin = identity()
        check()
        diagnostic = dict(phase=phase)
        report["snapshot_diagnostics"].append(diagnostic)
        state, native = capture_selected_mill_context(
            sw, clsid, typelib_path, expected_document_path,
            expected_feature_native_id=expected_feature_native_id,
            check=check, diagnostic=diagnostic,
            context=selected_context,legacy_capture=capture_mill_feature_state)
        check()
        if (state["document"] != begin or identity() != begin
            or state["saved_file_sha256"] != expected_source_sha256):
            raise ValueError("Document/source changed during capture")
        selected = _selected(state, expected_feature_native_id,
                             expected_operation_native_id, expected_mill_operation_type)
        selected_counts = selected["toolpath_record_counts"]
        if (type(selected["toolpath_generated"]) is not bool or type(selected_counts) is not list
            or len(selected_counts) > 32
            or any(type(n) is not int or not 0 <= n <= 100000 for n in selected_counts)):
            raise ValueError("Strict native generated flag and record counts required")
        if not report["mutation_attempted"] and (
            selected["toolpath_generated"] is not True
            or selected["toolpath_record_counts"] != expected_toolpath_record_counts):
            raise ValueError("Exact previously generated record counts required")
        expected_ids = {expected_operation_native_id, *expected_ungenerated_operation_ids}
        actual_ids = [row["native_id"] for row in state["operations"]]
        if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
            raise ValueError("Exact expected MILL operation inventory required")
        for row in state["operations"]:
            if row["native_id"] in expected_ungenerated_operation_ids:
                if row["toolpath_generated"] is not False or row["toolpath_record_counts"] != []:
                    raise ValueError("Expected untouched MILL operation is generated or has records")
        check()
        state["boundary_parameters"], target, dispatch = parameters(native)
        if identity() != begin:
            raise ValueError("Document changed while reading rough parameters")
        persist()
        return state, target, dispatch

    def native_read(label, call, decoder=None, *, interface=False, validator=None):
        if len(report["native_reads"]) >= MAX_NEW_READS:
            raise ValueError("Bounded native read budget exceeded")
        boundary()
        row = dict(index=len(report["native_reads"]), name=label,
                   started_unix=time.time(), attempted=False,
                   returned=False, validated=False)
        report["native_reads"].append(row)
        report.update(phase=label, native_dispatch_pending=True)
        persist()
        boundary()
        row["attempted"] = True
        report["native_read_attempted"] = True
        persist()  # Failure here prevents dispatch.
        start = time.monotonic()
        try:
            result = call()
        except Exception as exc:
            row.update(raised=True, issue=_error(exc),
                       elapsed_seconds=time.monotonic() - start)
            # A raised native call is not treated as successful or safe to retry.
            report["native_dispatch_pending"] = False
            persist()
            raise
        row.update(returned=True, return_type=type(result).__name__,
                   elapsed_seconds=time.monotonic() - start)
        if type(result) in (tuple, list):
            row["tuple_length"] = len(result)
        report["native_dispatch_pending"] = False
        persist()  # Record return before validation or any later native call.
        boundary()
        if interface:
            _nonnull(result)
            row["non_null_interface"] = True
        if validator is not None:
            validator(result)
        if decoder is not None:
            result = decoder(result)
            row["value"] = deepcopy(result)
        row["validated"] = True
        persist()
        return result

    def typed(raw, name):
        return native_read("QueryInterface." + name,
                           lambda: _typed(raw, name, typelib_path), interface=True)

    def getter(raw, interface_name, name, *args, decoder=None, interface=False, validator=None):
        return native_read(interface_name + "." + name,
                           lambda: _member(raw, name, *args), decoder=decoder,
                           interface=interface, validator=validator)

    def parameters(native):
        feature = native_read("QueryInterface.IDispatch.feature",
            lambda: _dispatch_feature(native["selected_feature"]), interface=True)
        target = typed(native["operations"][expected_operation_native_id], "ICWRghMillOp")
        values = dict(
            tool_diameter_percent_native=getter(target, "ICWRghMillOp", "GetToolDiameterPercent", feature, decoder=_number),
            side_allowance_native=getter(target, "ICWRghMillOp", "SideAllow", decoder=_number),
            stepover=getter(target, "ICWRghMillOp", "GetStepOver", decoder=_stepover),
            pocket_method_raw=getter(target, "ICWRghMillOp", "PocketMethod", decoder=_long),
            contain_type_raw=getter(target, "ICWRghMillOp", "GetContainType", decoder=_long),
            contain_allowance_native=getter(target, "ICWRghMillOp", "GetContainAllowance", decoder=_number),
        )
        return values, target, feature

    try:
        selected_context=load_selected_mill_context(process_id=process_id,
            expected_document_path=expected_document_path,expected_feature_native_id=expected_feature_native_id,
            expected_source_sha256=expected_source_sha256,feature_kind=feature_kind,
            circle_creation_receipt_path=circle_creation_receipt_path,
            circle_creation_receipt_sha256=circle_creation_receipt_sha256)
        _percent(expected_tool_diameter_percent)
        _percent(new_tool_diameter_percent)
        if expected_tool_diameter_percent == new_tool_diameter_percent:
            raise ValueError("Different explicit old and new percentages required")
        if action not in ("prepare", "apply"):
            raise ValueError("Only prepare/apply supported")
        credentials = (expected_state_sha256, prepare_receipt_path, prepare_receipt_sha256)
        if action == "prepare":
            if any(value is not None for value in credentials):
                raise ValueError("Prepare rejects apply credentials")
        else:
            for value in (expected_state_sha256, prepare_receipt_sha256):
                if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
                    raise ValueError("Exact prepared state and receipt hashes required")
            prep = Path(prepare_receipt_path) if type(prepare_receipt_path) is str else None
            if (prep is None or not prep.is_absolute() or prep.suffix.casefold() != ".json"
                or not prep.is_file() or prep.is_symlink() or prep.stat().st_size > 4*1024*1024):
                raise ValueError("Exact existing bounded prepare receipt required")
            if _file_hash(prep) != prepare_receipt_sha256:
                raise ValueError("Prepare receipt hash changed")
            prepared = json.loads(prep.read_text(encoding="utf-8"))
            if (prepared.get("status") != "ok" or prepared.get("action") != "prepare"
                or prepared.get("phase") != "finished" or prepared.get("apply_eligible") is not True
                or prepared.get("mutation_attempted") is not False
                or prepared.get("state_sha256") != expected_state_sha256
                or _digest(prepared.get("prepared_state")) != expected_state_sha256):
                raise ValueError("A complete immutable prepare receipt is required")
            marker = Path(str(prep) + ".apply_attempt.json")
            if marker.exists() or marker.is_symlink():
                raise ValueError("Prepare already consumed; no replay")
        for value in (process_id, expected_feature_native_id, expected_operation_native_id):
            _integer(value, positive=True)
        if (type(expected_mill_operation_type) is not int
            or expected_mill_operation_type != 0):
            raise ValueError("Exact ROUGH MILL operation type 0 required")
        if (type(expected_toolpath_record_counts) is not list
            or not 1 <= len(expected_toolpath_record_counts) <= 32
            or any(type(n) is not int or not 0 <= n <= 100000
                   for n in expected_toolpath_record_counts)
            or not 1 <= sum(expected_toolpath_record_counts) <= 100000):
            raise ValueError("Exact bounded nonempty native record counts required")
        if (type(expected_ungenerated_operation_ids) is not list
            or len(expected_ungenerated_operation_ids) > 31):
            raise ValueError("Bounded exact ungenerated operation IDs required")
        for value in expected_ungenerated_operation_ids:
            _integer(value, positive=True)
        if (len(set(expected_ungenerated_operation_ids)) != len(expected_ungenerated_operation_ids)
            or expected_operation_native_id in expected_ungenerated_operation_ids):
            raise ValueError("Unique ungenerated operation IDs excluding selected operation required")
        if (type(expected_document_path) is not str
            or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold() != ".sldprt"):
            raise ValueError("Exact absolute saved qualification part required")
        if (type(expected_source_sha256) is not str
            or re.fullmatch("[0-9a-f]{64}", expected_source_sha256) is None):
            raise ValueError("Exact saved source SHA required")
        if (qualification_only is not True or acknowledge_disposable_copy is not True
            or message_policy != "vendor_default"):
            raise ValueError("Explicit disposable qualification with vendor_default required")
        receipt = Path(receipt_path) if type(receipt_path) is str else None
        if (receipt is None or not receipt.is_absolute()
            or receipt.suffix.casefold() != ".json" or not receipt.parent.is_dir()
            or receipt.exists() or receipt.is_symlink()):
            raise ValueError("Unique absolute JSON receipt required")
        _write_receipt(receipt, report, create=True)
        created = True
        baseline = identity()
        if baseline["needs_save"] is not False:
            raise ValueError("Clean saved qualification document required")
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline:
            raise ValueError("Document changed acquiring event host")
        session = CamMessageSession(app, typelib_path)
        with session:
            before, target, feature = capture("initial_capture")
            report["before"] = before
            if before["document"]["needs_save"] is not False:
                raise ValueError("Prepare/apply requires initially clean saved state")
            if before["boundary_parameters"]["tool_diameter_percent_native"] != expected_tool_diameter_percent:
                raise ValueError("Expected tool-diameter percent is stale")
            state_key = dict(snapshot=before, process_id=process_id,
                feature_id=expected_feature_native_id, operation_id=expected_operation_native_id,
                old_percent=expected_tool_diameter_percent, new_percent=new_tool_diameter_percent,
                scope="MILL_ROUGH_FEATURE_TOOL_DIAMETER_PERCENT_ONLY")
            report.update(prepared_state=state_key, state_sha256=_digest(state_key), apply_eligible=True)
            persist()
            if action == "apply" and report["state_sha256"] != expected_state_sha256:
                raise ValueError("Prepared state, request or parameter changed")
            current, target, feature = capture("before_mutation_capture" if action == "apply" else "prepare_readback")
            if current != before:
                raise ValueError("State changed before setter or prepare completion")
            final = current
            if action == "apply":
                if _file_hash(prep) != prepare_receipt_sha256:
                    raise ValueError("Prepared receipt changed before dispatch")
                boundary()
                if identity() != before["document"]:
                    raise ValueError("Document became dirty before setter")
                _write_receipt(marker, dict(status="consumed", process_id=process_id,
                    state_sha256=expected_state_sha256, apply_receipt_path=str(receipt),
                    automatic_replay_allowed=False), create=True)
                report.update(phase="SetToolDiameterPercent", mutation_attempted=True,
                    native_setter_attempted=True, native_dispatch_pending=True)
                persist()  # Durable setter intent; failure prevents the native call.
                boundary()
                if identity() != before["document"]:
                    raise ValueError("Document changed immediately before setter")
                result = _member(target, "SetToolDiameterPercent", feature, float(new_tool_diameter_percent))
                report.update(native_setter_returned=True, native_dispatch_pending=False,
                    setter_return_type=type(result).__name__, phase="setter_returned")
                if type(result) in (int, float, bool, str) or result is None:
                    report["native_hresult"] = result
                persist()
                boundary()
                if type(result) is not int or result != 0:
                    raise ValueError("Exact integer S_OK required from no-OUT native setter")
                after, _, _ = capture("after_mutation_capture")
                report["after"] = after
                persist()
                report["selected_toolpath_after"] = _verify_delta(
                    before, after, expected_operation_native_id, new_tool_diameter_percent)
                report["parameter_readback_verified"] = True
                final = after
            else:
                report["after"] = current
            report["boundary_parameters_read_complete"] = True
            check()
        report["phase"] = "after_cleanup"
        check(active=False)
        final_document = identity()
        report["after_cleanup_SW_file"] = dict(document=final_document,
            saved_file_sha256=expected_source_sha256)
        if final_document != final["document"]:
            raise ValueError("Document changed during event cleanup")
        check(active=False)
        report.update(status="review_required" if action == "apply" else "ok",
            phase="finished", readback_verified=True,
            reason="RAW_PERCENT_CHANGE_ONLY_GTP_SAVE_AIR_GEOMETRY_AND_PRODUCTION_UNQUALIFIED")
    except Exception as exc:
        report.update(
            status="uncertain" if report["mutation_attempted"] else "error", failed_phase=report["phase"], phase="finished",
            issue=_error(exc), readback_verified=False, parameter_readback_verified=False, apply_eligible=False,
            reason="MILL_ROUGH_PERCENT_STOPPED_NO_RETRY_OR_AUTOMATIC_GTP",
        )
    finally:
        if session is not None:
            report["messages"] = session.summary()
        if created:
            try:
                persist()
            except Exception as exc:
                report.update(status="uncertain" if report["mutation_attempted"] else "error", receipt_write_error=_error(exc),
                              readback_verified=False, parameter_readback_verified=False)
    return report
