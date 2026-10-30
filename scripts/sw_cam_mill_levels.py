"""Read raw levels and setup direction from one generated MILL operation.

The reader never generates, saves, exports, edits, or accesses CL records.
Each new interface query/getter has a durable intent/result entry. A failed
call stops the sequence; no alternate interface or replay is attempted.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re
import time

from scripts.sw_cam_mill_feature_context import (load_selected_mill_context,
    capture_selected_mill_context, selected_context_identity)
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_feature_process import capture_mill_feature_state, _integer
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_toolpath import _selected
from scripts.sw_cam_thread import _file_hash
from scripts.sw_operation_guard import absolute_document_path, check_document_target

MAX_NEW_READS = 32


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("A finite native numeric value is required")
    return value


def _boolean(value):
    if type(value) is not bool:
        raise ValueError("A strict native Boolean is required")
    return value


def _tuple(value, length):
    if type(value) not in (tuple, list) or len(value) != length:
        raise ValueError("Unexpected native output tuple arity")
    return value


def _coordinates(value):
    return [_number(v) for v in _tuple(value, 3)]


def _toolpath_parameters(value):
    value = _tuple(value, 7)
    if type(value[3]) is not int or not -2147483648 <= value[3] <= 2147483647:
        raise ValueError("A strict native LONG enumeration is required")
    return dict(
        use_setup_definition_for_top_Z=_boolean(value[0]),
        use_minimum_Z=_boolean(value[1]),
        adjust_feature_height=_boolean(value[2]),
        first_cut_Z_type_raw=value[3],
        use_setup_definition_for_bottom_Z=_boolean(value[4]),
        minimum_Z_native=_number(value[5]),
        start_Z_native=_number(value[6]),
    )


def _nonnull(value):
    if value is None or not bool(value):
        raise ValueError("A non-null native interface is required")
    return value


def _setup_interfaces(value):
    for item in _tuple(value, 3):
        _nonnull(item)


def _dispatch_feature(feature):
    # Standard COM QI, not an interface-pointer cast or late-bound invocation.
    from comtypes.automation import IDispatch
    return feature.QueryInterface(IDispatch)


def read_mill_level_values(feature_raw, operation_raw, *, native_read, typed, getter, report):
    """Shared exact getter sequence; the caller supplies guards and durable read logging."""
    feature = native_read(
        "QueryInterface.IDispatch.feature",
        lambda: _dispatch_feature(feature_raw), interface=True,
    )
    operation = typed(operation_raw, "ICWMillOperation")
    levels = report["levels"] = {}
    levels["machining_depth_native"] = getter(
        operation, "ICWMillOperation", "GetMachiningDepth", feature, decoder=_number)
    operation3 = typed(operation_raw, "ICWMillOperation3")
    levels["override_machining_depth"] = getter(
        operation3, "ICWMillOperation3", "GetOverrideMachiningDepth", feature, decoder=_boolean)
    parameters_raw = getter(operation3, "ICWMillOperation3", "GetToolpathParam", interface=True)
    parameters = typed(parameters_raw, "ICWToolpathParam")
    levels["toolpath_parameters"] = getter(
        parameters, "ICWToolpathParam", "GetToolpathParameters", decoder=_toolpath_parameters)
    setup_raw = getter(operation3, "ICWMillOperation3", "GetSetupParameters", validator=_setup_interfaces)
    transform_raw, origin_raw, vector_raw = setup_raw
    report["setup"] = dict(transform_present=True, transform_matrix_decoded=False)
    origin = typed(origin_raw, "ICWPosition")
    report["setup"]["origin_native"] = getter(
        origin, "ICWPosition", "GetCoordinates", decoder=_coordinates)
    vector = typed(vector_raw, "ICWUnitVector")
    coordinates = getter(vector, "ICWUnitVector", "GetCoordinates", decoder=_coordinates)
    magnitude = math.hypot(*coordinates)
    if not math.isfinite(magnitude) or magnitude <= 0:
        raise ValueError("Finite nonzero setup direction required")
    report["setup"].update(
        axis_native=coordinates, axis_magnitude=magnitude,
        axis_normalized_for_report_only=[v / magnitude for v in coordinates],
        native_axis_modified=False,
    )


def inspect_mill_operation_levels(
    sw, clsid, typelib_path, *, process_id, expected_document_path,
    expected_source_sha256, expected_feature_native_id,
    expected_operation_native_id, expected_mill_operation_type,
    expected_toolpath_record_counts, expected_ungenerated_operation_ids, qualification_only,
    acknowledge_disposable_copy, receipt_path, message_policy="vendor_default",
        feature_kind='open_pocket', circle_creation_receipt_path=None, circle_creation_receipt_sha256=None):
    from scripts.sw_cam_events import CamMessageSession
    selected_context=None

    report = dict(
        status="error", phase="preflight", process_id=process_id,
        read_only=True, may_continue=False, mutation_attempted=False,
        native_dispatch_pending=False, native_read_attempted=False,
        readback_verified=False, levels_read_complete=False,
        model_saved=False, AFR_attempted=False, GOP_attempted=False,
        GTP_attempted=False, simulation_attempted=False, export_attempted=False,
        stock_edit_attempted=False, tool_edit_attempted=False,
        record_access_attempted=False, units_verified=False,
        physical_depth_verified=False, coordinate_frame_verified=False,
        production_qualified=False, post_cleanup_CAM_getters=False,
        native_reads_scope="New CAM interface queries and level/setup getters only; excludes existing snapshot and SOLIDWORKS identity calls",
        snapshot_scope="One feature and bounded operation inventory, document and saved source; not whole RAM BRep",
        native_reads=[], snapshot_diagnostics=[],
    )
    receipt = session = None
    created = False
    before = None

    def persist():
        if created:
            _write_receipt(receipt, report)

    def identity():
        if selected_context is not None:
            strict_selected_document=selected_context_identity(sw,selected_context)['document']
        pid = _member(sw, "GetProcessID")
        if type(pid) is not int or pid != process_id:
            raise ValueError("Exact SOLIDWORKS process changed")
        doc = document_snapshot(sw)
        if doc is None or doc.get("type") != 1 or type(doc.get("needs_save")) is not bool:
            raise ValueError("Active saved part with strict dirty flag required")
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
        if before is not None and identity() != before["document"]:
            raise ValueError("Document/source changed during level inspection")
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
        if (selected["toolpath_generated"] is not True
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
        persist()
        return state, native

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

    try:
        selected_context=load_selected_mill_context(process_id=process_id,
            expected_document_path=expected_document_path,expected_feature_native_id=expected_feature_native_id,
            expected_source_sha256=expected_source_sha256,feature_kind=feature_kind,
            circle_creation_receipt_path=circle_creation_receipt_path,
            circle_creation_receipt_sha256=circle_creation_receipt_sha256)
        for value in (process_id, expected_feature_native_id, expected_operation_native_id):
            _integer(value, positive=True)
        if (type(expected_mill_operation_type) is not int
            or not 0 <= expected_mill_operation_type <= 2147483647):
            raise ValueError("Strict nonnegative expected MILL operation type required")
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
            before, native = capture("initial_capture")
            report["before"] = before
            persist()
            if before["document"]["needs_save"] is not False:
                raise ValueError("Document became dirty before level reads")
            read_mill_level_values(native["selected_feature"],
                native["operations"][expected_operation_native_id], native_read=native_read,
                typed=typed, getter=getter, report=report)
            report["levels_read_complete"] = True
            persist()
            after, _ = capture("final_capture")
            report["after"] = after
            persist()
            if after != before:
                raise ValueError("MILL state changed during read-only level inspection")
            check()
        report["phase"] = "after_cleanup"
        check(active=False)
        final_document = identity()
        report["after_cleanup_SW_file"] = dict(
            document=final_document, saved_file_sha256=expected_source_sha256)
        if final_document != before["document"]:
            raise ValueError("Document changed during event cleanup")
        check(active=False)
        report.update(
            status="ok", phase="finished", readback_verified=True,
            reason="RAW_LEVELS_AND_SETUP_DIRECTION_ONLY_UNITS_FRAME_PATH_GEOMETRY_AND_PRODUCTION_UNQUALIFIED",
        )
    except Exception as exc:
        report.update(
            status="error", failed_phase=report["phase"], phase="finished",
            issue=_error(exc), readback_verified=False,
            reason="MILL_LEVEL_INSPECTION_STOPPED_NO_RETRY",
        )
    finally:
        if session is not None:
            report["messages"] = session.summary()
        if created:
            try:
                persist()
            except Exception as exc:
                report.update(status="error", receipt_write_error=_error(exc),
                              readback_verified=False)
    return report
