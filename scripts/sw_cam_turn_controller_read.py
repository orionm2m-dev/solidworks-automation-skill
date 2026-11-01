"""Read a TURN controller name through its documented legacy interface."""
from __future__ import annotations
import re

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _context, _inventory, _typed
from scripts.sw_cam_thread import _file_hash
from scripts.sw_operation_guard import check_document_target


def _bounded_output(value):
    """Use the shared bounded, JSON-safe COM conversion diagnostics."""
    from scripts.sw_cam_qualification_context import _converted_shape
    return _converted_shape(value)


def inspect_turn_controller(sw, clsid, typelib_path, *, process_id,
                            expected_document_path, expected_source_sha256,
                            include_parameters=False, expected_controller_name=None):
    """Read a name and optionally its exact non-APT parameters, without selecting it."""
    report = dict(status="error", may_continue=False, mutation_attempted=False,
                  model_saved=False, generation_attempted=False,
                  controller_parameters_read=False, preset_values_verified=False,
                  production_process_qualified=False, getter_call_count=0)
    stage = "validate_inputs"
    try:
        if type(process_id) is not int or not 0 < process_id <= 4294967295:
            raise ValueError("A positive exact process ID is required")
        if not isinstance(expected_document_path, str) or not expected_document_path:
            raise ValueError("An exact document path is required")
        if not isinstance(expected_source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256):
            raise ValueError("A saved source SHA-256 is required")
        if type(include_parameters) is not bool:
            raise ValueError("include_parameters must be a strict Boolean")
        if include_parameters:
            if (not isinstance(expected_controller_name, str) or not expected_controller_name.strip()
                    or len(expected_controller_name) > 1024 or any(ord(c) < 32 for c in expected_controller_name)
                    or not expected_controller_name.lower().endswith(".ctl")):
                raise ValueError("An observed exact non-APT .ctl name is required")
        elif expected_controller_name is not None:
            raise ValueError("A name expectation is only used for requested parameter lookup")
        def identity():
            if _member(sw, "GetProcessID") != process_id:
                raise ValueError("Selected process changed")
            doc = document_snapshot(sw)
            if not isinstance(doc, dict) or doc.get("type") != 1 or doc.get("needs_save") is not False:
                raise ValueError("A clean saved part is required")
            check_document_target(doc["path"], doc["title"], expected_path=expected_document_path, required=True)
            if _file_hash(doc["path"]) != expected_source_sha256:
                raise ValueError("Saved source changed")
            return doc
        stage = "identity_before"
        before = identity()
        report["document_before"] = before
        report["source_sha256"] = expected_source_sha256
        stage = "context"
        context_doc, _doc, _part, machine, _app = _context(sw, clsid, typelib_path)
        if context_doc != before:
            raise ValueError("Document changed during context binding")
        stage = "inventory_before"
        inventory = _inventory(machine, typelib_path)
        report["inventory_before"] = inventory
        if inventory.get("machine_type") != 3:
            raise ValueError("Only a confirmed TURN machine is supported")
        if identity() != before:
            raise ValueError("Document changed before controller read")
        stage = "ICWTurnMachine"
        target = _typed(machine, "ICWTurnMachine", typelib_path)
        stage = "GetController"
        report["getter_call_count"] = 1
        name = _member(target, "GetController")
        report["getter_returned"] = True
        if not isinstance(name, str) or len(name) > 1024 or any(ord(c) < 32 for c in name):
            raise ValueError("GetController must return a bounded BSTR without control characters")
        report["controller_name_raw"] = name
        report["controller_name_available"] = bool(name.strip())
        if include_parameters:
            if name != expected_controller_name:
                raise ValueError("Current TURN controller differs from the observed exact name")
            if identity() != before:
                raise ValueError("Document changed before parameter lookup")
            stage = "ICWMachine5"
            parameter_target = _typed(machine, "ICWMachine5", typelib_path)
            stage = "GetControllerParameters"
            report["parameter_lookup_attempted"] = True
            report["parameter_lookup_arguments"] = dict(is_apt=False, name=name)
            raw = _member(parameter_target, "GetControllerParameters", False, name)
            report["parameter_lookup_returned"] = True
            report["parameter_output_shape"] = _bounded_output(raw)
            from scripts.sw_cam_apt_controller import _parameters
            try:
                report["controller_parameters"] = _parameters(raw)
                report["controller_parameters_read"] = report["controller_parameters"]["success"]
            except ValueError as exc:
                report["parameter_shape_issue"] = str(exc)
                report["controller_parameters"] = dict(success=False,entries=[],reason="unsupported_native_output_shape")
        stage = "inventory_after"
        after_inventory = _inventory(machine, typelib_path)
        report["inventory_after"] = after_inventory
        stage = "identity_after"
        after = identity()
        report["document_after"] = after
        report["inventory_unchanged"] = inventory == after_inventory
        report["active_document_unchanged"] = before == after
        if inventory != after_inventory or before != after:
            raise ValueError("Document or CAM inventory changed during read")
        report["status"] = "ok" if name.strip() else "review_required"
        report["reason"] = "TURN_CONTROLLER_NAME_READ" if name.strip() else "TURN_CONTROLLER_NAME_EMPTY"
        if include_parameters:
            report["status"] = "ok" if report["controller_parameters_read"] else "review_required"
            report["reason"] = "TURN_CONTROLLER_PARAMETERS_READ" if report["controller_parameters_read"] else "TURN_CONTROLLER_PARAMETERS_UNAVAILABLE"
        report["scope"] = "Raw name/optional parameters only; no controller selection, generation, save, or preset qualification"
    except Exception as exc:
        report.update(status="error", reason="TURN_CONTROLLER_READ_FAILED", failed_stage=stage, issue=_error(exc))
    return report
