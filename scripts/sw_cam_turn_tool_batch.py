"""限定工作副本的多字段车刀尺寸更新；不保存、生成、重试或回滚。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from scripts import sw_cam_turn_tool as single
from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_operation_profile import _number
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _values(value):
    if (not isinstance(value, dict) or not 1 <= len(value) <= len(single._FIELDS)
            or any(type(key) is not str or key not in single._FIELDS for key in value)):
        raise ValueError("One to six existing whitelisted insert dimensions are required")
    result = {}
    for field in sorted(value):
        number = _number(value[field])
        if number < 0 or (field in {"Width", "Thickness", "InscribedCircle"} and number == 0):
            raise ValueError("Radii must be nonnegative and insert sizes positive")
        result[field] = number
    return result


def _verify_changes(before, after, changes):
    expected = deepcopy(before)
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    expected["selected_tool"]["info_raw"] = after["selected_tool"]["info_raw"]
    group = before["selected_tool_group"]
    for field, value in changes.items():
        expected["tool_groups"][group]["dimensions_native"][field] = value
        expected["selected_tool"]["dimensions_native"][field] = value
    if expected != after:
        raise ValueError("Readback changed more than the explicitly requested insert dimensions")


def configure_turn_tool_dimensions(sw, clsid, typelib_path, *, process_id,
        expected_document_path, setup_index, operation_index, expected_operation_type,
        action, values_native, expected_state_sha256=None, allowed_affected_operations=None,
        receipt_path=None, qualification_only, message_policy):
    """一次准备完整状态并绑定尺寸配方；逐项记录后只做一次完整回读。

    调用方必须持有同一显式 PID 的操作锁。数值保持 native units；此功能不证明
    实物刀具适配、单位、路径、持久化或加工安全。旧单字段 API 不受影响。
    """
    if type(process_id) is not int or not 0 < process_id < 2**32:
        raise ValueError("An explicit strict PID is required")
    selected = single._reference(dict(setup_index=setup_index, operation_index=operation_index,
                                    expected_operation_type=expected_operation_type))
    values = _values(values_native)
    if action not in {"prepare", "apply"}:
        raise ValueError("Only prepare and apply are supported")
    if qualification_only is not True or message_policy != "vendor_default":
        raise ValueError("Explicit qualification-only/vendor-default policy is required")
    if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold() != ".sldprt"):
        raise ValueError("An exact absolute saved working part is required")
    receipt = None
    if action == "prepare":
        if any(item is not None for item in (expected_state_sha256, allowed_affected_operations, receipt_path)):
            raise ValueError("Prepare accepts the desired recipe but no apply guard or receipt")
    else:
        if (not isinstance(expected_state_sha256, str) or len(expected_state_sha256) != 64
                or any(char not in "0123456789abcdef" for char in expected_state_sha256)):
            raise ValueError("The exact prepared state/recipe SHA-256 is required")
        if not isinstance(allowed_affected_operations, list) or not 1 <= len(allowed_affected_operations) <= 512:
            raise ValueError("Explicit affected operation references are required")
        allowed_affected_operations = [single._reference(item) for item in allowed_affected_operations]
        keys = [(item["setup_index"], item["operation_index"]) for item in allowed_affected_operations]
        if len(set(keys)) != len(keys) or selected not in allowed_affected_operations:
            raise ValueError("Unique affected references including the selected operation are required")
        receipt = Path(receipt_path) if isinstance(receipt_path, str) else None
        if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != ".json"
                or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink()):
            raise ValueError("A new absolute JSON receipt with an existing parent is required")
    report = dict(status="started", action=action, phase="preflight", process_id=process_id,
        values_native=values, mutation_attempted=False, native_calls_returned_count=0,
        readback_verified=False, scalar_readback_verified=False, may_continue=False,
        model_saved=False, generation_attempted=False, physical_tool_qualified=False,
        native_units_verified=False, setters=[], snapshot_diagnostics=[],
        attempt_marker_meaning="durable_intent_before_property_put_not_proof_of_native_entry",
        automatic_retry=False, automatic_rollback=False)
    if receipt:
        _write_receipt(receipt, report, create=True)
    session = None

    def publish():
        if receipt:
            _write_receipt(receipt, report)

    def pid_guard():
        pid = _member(sw, "GetProcessID")
        if type(pid) is not int or pid != process_id:
            raise ValueError("Exact native process identity changed")

    def messages(active=True):
        data = session.summary()
        report["messages"] = data
        if (not data.get("subscribed") or (active and not data.get("active"))
                or data.get("event_count") or data.get("overflow") or data.get("callback_errors")
                or data.get("callback_error_count") or data.get("subscription_error")
                or data.get("disconnect_errors")):
            raise ValueError("CAM messages or event lifecycle require review; no further native calls")

    def read(obj, name, *args):
        messages()
        result = _member(obj, name, *args)
        messages()
        return result

    def document_guard(reference, file_sha, *, allow_dirty=False):
        pid_guard()
        observed = document_snapshot(sw)
        expected = deepcopy(reference)
        if observed is None:
            raise ValueError("Active document disappeared")
        check_document_target(observed["path"], observed["title"],
                              expected_path=expected_document_path, required=True)
        if allow_dirty:
            expected["needs_save"] = observed["needs_save"]
        if expected != observed or _file_hash(expected_document_path) != file_sha:
            raise ValueError("Exact document identity or saved file changed")
        return observed

    def capture(phase):
        report["phase"] = phase
        diagnostic = {"phase": phase}
        report["snapshot_diagnostics"].append(diagnostic)
        return single._snapshot(sw, clsid, typelib_path, selected, check=messages,
                                diagnostics=diagnostic, guarded_readers=True)

    try:
        pid_guard()
        entry = document_snapshot(sw)
        if entry is None or entry.get("type") != 1 or entry.get("needs_save") is not False:
            raise ValueError("A clean saved working copy is required")
        check_document_target(entry["path"], entry["title"], expected_path=expected_document_path, required=True)
        source_sha = _file_hash(expected_document_path)
        report["saved_file_sha256"] = source_sha
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        session = CamMessageSession(app, typelib_path)
        with session:
            messages()
            before, native = capture("before")
            report["before"] = before
            document_guard(entry, source_sha)
            if before["document"] != entry:
                raise ValueError("Document changed during initial snapshot")
            group = before["selected_tool_group"]
            dimensions = before["tool_groups"][group]["dimensions_native"]
            if any(field not in dimensions for field in values):
                raise ValueError("A requested dimension is not applicable to this insert")
            changes = {field: value for field, value in values.items() if dimensions[field] != value}
            report["changed_fields"] = list(changes)
            report["unchanged_fields"] = [field for field in values if field not in changes]
            report["before_values_native"] = {field: dimensions[field] for field in values}
            report["state_sha256"] = single._digest(dict(process_id=process_id, state=before,
                saved_file_sha256=source_sha, values_native=values))
            affected = before["affected_operations"]
            generated = [item for item in before["inventory"]["operations"]
                if item["toolpath_generated"] and any(item["setup_index"] == ref["setup_index"]
                    and item["operation_index"] == ref["operation_index"] for ref in affected)]
            report.update(affected_operations=affected, affected_generated_operations=generated,
                          apply_eligible=not generated, no_changes_required=not changes)
            if action == "apply":
                if report["state_sha256"] != expected_state_sha256:
                    raise ValueError("Prepared state or exact desired recipe changed; prepare again")
                if sorted(allowed_affected_operations, key=single._ref_key) != sorted(affected, key=single._ref_key):
                    raise ValueError("Allowed references must match all and only operations sharing the tool")
                if generated:
                    raise ValueError("An affected operation already has a generated toolpath")
                assignment = next(item for item in before["operation_tools"] if item["operation"] == selected)
                expected_values = {field: dimensions[field] for field in values}
                for field, value in changes.items():
                    messages()
                    document_guard(entry, source_sha, allow_dirty=bool(report["setters"]))
                    if _object_id(native["native_doc"], native["operation"], read) != assignment["operation_native_id"]:
                        raise ValueError("Selected native operation identity changed")
                    current_tool = _typed(read(native["operation"], "IGetTool"), "ICWTool", typelib_path)
                    if (_object_id(native["native_doc"], current_tool, read) != assignment["tool_native_id"]
                            or _object_id(native["native_doc"], native["tool"], read) != assignment["tool_native_id"]):
                        raise ValueError("Selected native tool identity changed")
                    for key, expected_value in expected_values.items():
                        if _number(read(native["turn_tool"], key)) != expected_value:
                            raise ValueError("Insert dimensions changed between bounded property writes")
                    step = dict(field=field, old_value_native=dimensions[field], value_native=value,
                                attempted=True, returned=False, scalar_readback_verified=False)
                    report["setters"].append(step)
                    report.update(phase="property_put", mutation_attempted=True)
                    publish()
                    document_guard(entry, source_sha, allow_dirty=report["native_calls_returned_count"] > 0)
                    messages()
                    setattr(native["turn_tool"], field, value)
                    step["returned"] = True
                    report["native_calls_returned_count"] += 1
                    report["phase"] = "property_put_returned"
                    publish()
                    messages()
                    observed = _number(read(native["turn_tool"], field))
                    step["observed_value_native"] = observed
                    if observed != value:
                        raise ValueError("Immediate scalar readback differs from requested value")
                    step["scalar_readback_verified"] = True
                    expected_values[field] = value
                    publish()
                if changes:
                    after, _ = capture("after")
                    report["after"] = after
                    _verify_changes(before, after, changes)
                    report["scalar_readback_verified"] = True
                else:
                    after = before
                    report["after"] = deepcopy(before)
                document_guard(after["document"], source_sha)
                report["readback_before_cleanup_verified"] = True
            else:
                after = before
            messages()
            report["snapshot_scope"] = "full_CAM_state_before_event_disconnect"
        messages(active=False)
        if not session.summary().get("disconnected") or session.summary().get("active"):
            raise ValueError("CAM event disconnect was not confirmed")
        report["document_after_cleanup"] = document_guard(after["document"], source_sha)
        report["saved_file_unchanged"] = True
        report.update(status="ok" if action == "prepare" else "review_required", phase="finished",
            readback_verified=action == "apply", reason=("PREPARED_RECIPE_ONLY" if action == "prepare"
                else "CAM_DEFINITION_ONLY_PHYSICAL_TOOL_AND_PERSISTENCE_REQUIRE_REVIEW"))
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
                      reason=getattr(exc, "reason", "CAM_TOOL_DIMENSION_BATCH_FAILED"),
                      issue=_error(exc), failed_phase=report["phase"], phase="finished", readback_verified=False)
    finally:
        if session is not None:
            report["messages"] = session.summary()
        if receipt:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status="uncertain", receipt_write_error=_error(exc), readback_verified=False)
    return report
