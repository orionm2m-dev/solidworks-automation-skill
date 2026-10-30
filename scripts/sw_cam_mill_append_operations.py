"""Append one compound feature's operation definitions, preserving prior work.

Native qualification is still required. No strategy edits, paths or simulation.
"""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_route_context import integer, MAX_OPERATIONS
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan, read_header
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, same_saved_context
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence, validate_selected_ids
from scripts.sw_cam_mill_append_delta import verify_added_plan
from scripts.sw_cam_mill_append_evidence import (
    SCOPE, load_target_profile, require_protected_tools, attempt_marker)
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

def validate_append_request(*, saved_plan_receipt_path, saved_plan_receipt_sha256,
        target_profile_receipt_path, target_profile_receipt_sha256,
        expected_feature_native_id, expected_operation_native_ids,
        expected_operation_setup_native_id, expected_tool_native_id,
        target_feature_native_id, target_owner_setup_native_id, target_operation_setup_native_id,
        expected_strategy_id, expected_strategy_name, save_after_verified,
        attempt_registry_path, **base):
    validate_inventory_request(**base)
    validate_selected_ids(expected_feature_native_id, expected_operation_native_ids,
                          expected_operation_setup_native_id, expected_tool_native_id)
    for label, value in (("target feature", target_feature_native_id),
                        ("target owner", target_owner_setup_native_id),
                        ("target operation setup", target_operation_setup_native_id)):
        integer(value, label, 1)
    if target_feature_native_id == expected_feature_native_id:
        raise ValueError("Target must differ from the already planned protected feature")
    if type(expected_strategy_id) is not int or not -(2**31) <= expected_strategy_id < 2**31:
        raise ValueError("Explicit strict compound strategy ID required")
    if type(expected_strategy_name) is not str or not 1 <= len(expected_strategy_name) <= 4096:
        raise ValueError("Explicit nonempty bounded compound strategy name required")
    if type(save_after_verified) is not bool:
        raise ValueError("Explicit strict save_after_verified choice required")
    pins = [read_pin(saved_plan_receipt_path, saved_plan_receipt_sha256)[1],
            read_pin(target_profile_receipt_path, target_profile_receipt_sha256)[1]]
    paths = [p["canonical_path"].casefold() for p in pins]
    if len(set(paths)) != len(paths) or str(Path(base["receipt_path"]).resolve()).casefold() in paths:
        raise ValueError("Distinct immutable input receipts and output required")
    marker = attempt_marker(attempt_registry_path, base["expected_document_path"],
                            base["expected_source_sha256"], target_feature_native_id)
    if marker.exists() or marker.is_symlink():
        raise ValueError("A prior dispatch marker exists; inspect its outcome, never replay")
    if marker.resolve() == Path(base["receipt_path"]).resolve():
        raise ValueError("Dispatch marker and report must be separate")
    return marker

def exact_target(native, profile, feature_id, owner_id, read, typed):
    raw = read(native["doc"], "GetCWObjectFromID", 1, feature_id)
    if not isinstance(raw, (tuple, list)) or len(raw) != 2 or raw[1] is not True or raw[0] is None:
        raise ValueError("Exact target lookup failed")
    header, base = read_header(raw[0], native["doc"], read, typed, owner_id)
    if header != profile["header"] or _object_id(native["doc"], base, read) != feature_id:
        raise ValueError("Exact target ID/owner/header changed before dispatch")
    return base

def append_mill_operations(sw, clsid, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, saved_plan_receipt_path, saved_plan_receipt_sha256,
        target_profile_receipt_path, target_profile_receipt_sha256,
        expected_feature_native_id, expected_operation_native_ids, expected_operation_setup_native_id,
        expected_tool_native_id, target_feature_native_id, target_owner_setup_native_id,
        target_operation_setup_native_id, expected_strategy_id, expected_strategy_name,
        save_after_verified, attempt_registry_path, qualification_only,
        acknowledge_disposable_copy, receipt_path, message_policy="vendor_default"):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(scope=SCOPE, status="error", phase="preflight", process_id=process_id,
        mutation_attempted=False, native_call_attempted=False, native_call_returned=False,
        native_dispatch_pending=False, native_hresult=None, GOP_attempted=False,
        save_attempted=False, save_call_returned=False, save_hresult=None,
        readback_verified=False, operation_delta_verified=False, save_readback_verified=False,
        model_saved=False, GTP_attempted=False, AFR_attempted=False, simulation_attempted=False,
        stock_edit_attempted=False, geometry_edit_attempted=False, material_edit_attempted=False,
        strategy_assignment_attempted=False, tool_assignment_attempted=False, TechDB_write_attempted=False,
        automatic_replay=False, automatic_rollback=False, full_inventory_verified=False,
        world_geometry_verified=False, production_qualified=False, actual_incoming_WIP_verified=False,
        holder_clearance_verified=False, strategy_suitability_verified=False,
        reopen_persistence_verified=False, post_cleanup_CAM_getters=False, may_continue=False,
        save_after_verified=save_after_verified, snapshot_diagnostics=[])
    anchor = profile = session = receipt = marker = None
    created = marker_created = False
    current_source = expected_source_sha256
    args = dict(process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256, saved_plan_receipt_path=saved_plan_receipt_path,
        saved_plan_receipt_sha256=saved_plan_receipt_sha256,
        target_profile_receipt_path=target_profile_receipt_path,
        target_profile_receipt_sha256=target_profile_receipt_sha256,
        expected_feature_native_id=expected_feature_native_id,
        expected_operation_native_ids=expected_operation_native_ids,
        expected_operation_setup_native_id=expected_operation_setup_native_id,
        expected_tool_native_id=expected_tool_native_id, target_feature_native_id=target_feature_native_id,
        target_owner_setup_native_id=target_owner_setup_native_id,
        target_operation_setup_native_id=target_operation_setup_native_id,
        expected_strategy_id=expected_strategy_id, expected_strategy_name=expected_strategy_name,
        save_after_verified=save_after_verified, attempt_registry_path=attempt_registry_path,
        qualification_only=qualification_only, acknowledge_disposable_copy=acknowledge_disposable_copy,
        receipt_path=receipt_path, message_policy=message_policy)
    def persist():
        if created:
            _write_receipt(receipt, report)
    def pins():
        anchor.check_files()
        if hasattr(anchor, "check_runtime_identity"):
            anchor.check_runtime_identity()
        if read_pin(target_profile_receipt_path, target_profile_receipt_sha256)[1] != profile["pin"]:
            raise ValueError("Pinned target profile changed")
    def identity():
        if type(_member(sw, "GetProcessID")) is not int or _member(sw, "GetProcessID") != process_id:
            raise ValueError("Exact process changed")
        doc = raw_part_identity(sw)
        check_document_target(doc["path"], doc["title"], expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != current_source:
            raise ValueError("Saved source changed")
        pins()
        return doc
    def events(active=True):
        s = session.summary()
        report["messages"] = s
        if (s.get("subscribed") is not True
            or (active and s.get("active") is not True)
            or (not active and (s.get("active") is not False or s.get("disconnected") is not True))
            or any(s.get(k) for k in ("event_count", "overflow", "callback_errors",
                "callback_error_count", "subscription_error", "disconnect_errors"))):
            raise ValueError("CAM event/transport requires stop; no replay")
    def detail_reader(state, native, read, typed, diag, *, boundary):
        read_selected_operation_tool_details(state, native, read, typed, diag,
            feature_native_id=expected_feature_native_id, boundary=boundary)
        for mode in ("three_step_profile", "strategy"):
            sub = diag.setdefault(mode, {})
            read_compound_strategy(state, native, read, typed, sub,
                feature_id=target_feature_native_id, owner_id=target_owner_setup_native_id,
                step_count=3, expected_header=profile["header"], boundary=boundary, observation=mode)
    def capture(phase):
        events(); pins()
        report["phase"] = phase
        diag = dict(phase=phase)
        report["snapshot_diagnostics"].append(diag); persist()
        state, native = capture_selected_plan(sw, clsid, typelib_path, expected_document_path,
            process_id=process_id, expected_source_sha256=current_source, evidence=anchor,
            check=events, diagnostic=diag, progress=persist, operation_details_reader=detail_reader)
        details = {key: deepcopy(diag["operation_details"][key]) for key in
            ("selected_tool_details", "three_step_profile", "strategy")}
        require_protected_tools(anchor, state, details["selected_tool_details"])
        if details["three_step_profile"]["compound_strategy"] != profile["details"]:
            raise ValueError("Target step profile changed")
        strategy = details["strategy"]["compound_strategy"]
        if (strategy.get("metadata_read_complete") is not True
            or strategy.get("attribute_id") != expected_strategy_id
            or strategy.get("attribute_name") != expected_strategy_name):
            raise ValueError("Current target strategy differs from explicit precondition")
        events(); pins()
        report[phase] = state; report[phase + "_details"] = details; persist()
        return state, native, details
    try:
        marker = validate_append_request(**args)
        anchor = load_saved_plan_tools_evidence(saved_plan_receipt_path, saved_plan_receipt_sha256,
            process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            expected_operation_setup_native_id=expected_operation_setup_native_id,
            expected_tool_native_id=expected_tool_native_id)
        if anchor.data.get("scope") != "MILL_SAVED_SHARED_CUTTER_CONFIG_V1":
            raise ValueError("This bounded append requires the configured-plan continuation anchor")
        if not hasattr(anchor, "baseline_tool_details"):
            raise ValueError("Complete pinned existing full-tool evidence required")
        profile = load_target_profile(target_profile_receipt_path, target_profile_receipt_sha256, anchor,
            process_id=process_id, source_sha=expected_source_sha256,
            feature_id=target_feature_native_id, owner_id=target_owner_setup_native_id)
        receipt = Path(receipt_path)
        report.update(request=deepcopy(args), anchor=anchor.summary(), target_profile=deepcopy(profile),
            source_before_sha256=current_source, dispatch_marker_path=str(marker),
            observation_scope="18 feature headers, exact three-step target, all prior shared-tool users, bounded operation definitions")
        _write_receipt(receipt, report, create=True); created = True
        baseline = identity()
        if baseline["needs_save"] is not False:
            raise ValueError("Clean saved qualification document required")
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline:
            raise ValueError("Identity changed acquiring event host")
        session = CamMessageSession(app, typelib_path)
        with session:
            before, native, before_details = capture("before")
            anchor.verify(before)
            if before["document"] != baseline:
                raise ValueError("Initial identity changed")
            if before["operation_count"] >= MAX_OPERATIONS:
                raise ValueError("No bounded capture capacity remains")
            if target_operation_setup_native_id not in [r["native_id"] for r in before["operation_setups"]]:
                raise ValueError("Target operation setup absent")
            if any(target_feature_native_id in r["linked_feature_ids"] for r in before["operations"]):
                raise ValueError("Target already has operation definitions; no replay")
            def read(obj, name, *values):
                events()
                if identity() != before["document"]:
                    raise ValueError("Identity changed before dispatch getter")
                result = _member(obj, name, *values)
                events()
                if identity() != before["document"]:
                    raise ValueError("Identity changed during dispatch getter")
                return result
            def typed(obj, name):
                events()
                result = _typed(obj, name, typelib_path)
                events()
                return result
            target = exact_target(native, profile, target_feature_native_id,
                                  target_owner_setup_native_id, read, typed)
            events(); pins()
            if identity() != before["document"]:
                raise ValueError("Identity changed before generation")
            pending = dict(scope=SCOPE, status="dispatch_pending", request=deepcopy(args),
                receipt_path=str(receipt), automatic_replay=False,
                target_feature_native_id=target_feature_native_id)
            _write_receipt(marker, pending, create=True); marker_created = True
            report.update(phase="GenerateOpPlan", mutation_attempted=True, native_call_attempted=True,
                          native_dispatch_pending=True, GOP_attempted=True)
            persist()
            result = _member(target, "GenerateOpPlan", 1)
            report.update(native_call_returned=True, native_dispatch_pending=False,
                native_hresult=result if type(result) is int else None, native_return_type=type(result).__name__)
            persist(); events()
            if type(result) is not int or result != 0:
                raise ValueError("Unexpected generation HRESULT; outcome unknown, no replay")
            after, native, after_details = capture("after")
            added = verify_added_plan(before, after, target_feature_native_id, target_operation_setup_native_id)
            if before_details != after_details:
                raise ValueError("Existing full tools or target strategy/profile changed")
            report.update(new_operations=added, operation_delta_verified=True); persist()
            final = after
            if save_after_verified:
                events(); pins()
                target_app = _typed(native["app"], "ICWApp", typelib_path)
                events()
                if identity() != after["document"]:
                    raise ValueError("Identity changed before verified save")
                report.update(phase="SaveActiveDocument", save_attempted=True, native_dispatch_pending=True)
                persist()
                result = _member(target_app, "SaveActiveDocument")
                report.update(save_call_returned=True, native_dispatch_pending=False,
                    save_hresult=result if type(result) is int else None,
                    save_return_type=type(result).__name__)
                persist(); events()
                if type(result) is not int or result != 0:
                    raise ValueError("Unexpected save HRESULT; outcome unknown, no replay")
                current_source = _file_hash(expected_document_path)
                report["source_after_sha256"] = current_source
                final, _, saved_details = capture("saved")
                if (not same_saved_context(after, final) or final["document"]["needs_save"] is not False
                    or saved_details != after_details):
                    raise ValueError("Save changed captured CAM context or left document dirty")
            events()
        events(active=False); pins()
        if identity() != final["document"]:
            raise ValueError("Identity changed during event cleanup")
        report.update(status="review_required", phase="finished", readback_verified=True,
            operation_delta_verified=True, save_readback_verified=save_after_verified,
            model_saved=save_after_verified, state_sha256=_digest(final),
            continuation_state=deepcopy(final), saved_file_sha256=current_source,
            reason="ADDITIVE_DEFINITIONS_ONLY_NO_PATHS_OR_MANUFACTURING_QUALIFICATION")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"], phase="finished", issue=_error(exc),
            readback_verified=False, operation_delta_verified=False,
            save_readback_verified=False, model_saved=False)
    finally:
        if session is not None:
            report["messages"] = session.summary()
        try:
            persist()
            if marker_created:
                _write_receipt(marker, dict(scope=SCOPE, status=report["status"], receipt_path=str(receipt),
                    receipt_sha256=_file_hash(receipt), automatic_replay=False,
                    target_feature_native_id=target_feature_native_id))
        except Exception as exc:
            report.update(status="uncertain" if report["mutation_attempted"] else "error",
                receipt_write_error=_error(exc), readback_verified=False,
                operation_delta_verified=False, save_readback_verified=False, model_saved=False)
    return report
