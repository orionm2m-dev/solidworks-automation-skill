"""独立 CAM 工作副本的单字段车削刀片定义；标准 COM identity 校验共享引用。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _collection, _context, _inventory, _typed, _write_receipt
from scripts.sw_cam_operation_profile import _integer, _number, _read_profile, _read_tool
from scripts.sw_operation_guard import absolute_document_path, check_document_target

_FIELDS = {"NoseRadius", "Width", "Radius1", "Radius2", "Thickness", "InscribedCircle"}


class CamToolStateError(ValueError):
    """携带稳定原因代码的原生工具状态门禁错误。"""
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _identity(obj):
    # IUnknown 是 COM 的规范对象身份；不用 vendor 内部指针或内存读取。
    from comtypes import IUnknown
    return obj.QueryInterface(IUnknown)


def _applicable(insert_type):
    result = set()
    if insert_type in {1, 3, 4, 5, 6, 7, 16}:
        result.add("NoseRadius")
    if insert_type in {1, 2, 3, 4, 5, 6, 7, 8, 15, 16}:
        result.add("Thickness")
    if insert_type == 1:
        result.add("InscribedCircle")
    if insert_type in {2, 3}:
        result.add("Width")
    if insert_type == 2:
        result.update(("Radius1", "Radius2"))
    return result


def _reference(value):
    if not isinstance(value, dict) or set(value) != {"setup_index", "operation_index", "expected_operation_type"}:
        raise ValueError("Exact operation references are required")
    for name in ("setup_index", "operation_index"):
        if type(value[name]) is not int or not 0 <= value[name] <= 511:
            raise ValueError("Operation indices must be strict integers in [0, 511]")
    if type(value["expected_operation_type"]) is not int or not 1 <= value["expected_operation_type"] <= 16:
        raise ValueError("Operation type must be a strict integer in [1, 16]")
    return dict(value)


def _ref_key(value):
    return value["setup_index"], value["operation_index"], value["expected_operation_type"]


def _snapshot(sw, clsid, typelib_path, selected, *, check=lambda: None, diagnostics=None,
              guarded_readers=False):
    diagnostics = {} if diagnostics is None else diagnostics
    def read(obj, name, *args):
        diagnostics["stage"] = name
        check()
        value = _member(obj, name, *args)
        check()
        return value

    def context():
        if not guarded_readers:
            return _context(sw, clsid, typelib_path)
        from scripts.sw_cam_turn_feature_attribute import _context as guarded_context
        return guarded_context(sw, clsid, typelib_path, read)

    def inventory_of(machine):
        if not guarded_readers:
            return _inventory(machine, typelib_path)
        from scripts.sw_cam_turn_feature_attribute import _inventory as guarded_inventory
        return guarded_inventory(machine, typelib_path, read)

    def items(raw, limit=512):
        if not guarded_readers:
            return _collection(raw, typelib_path)
        from scripts.sw_cam_turn_feature_attribute import _items
        return _items(raw, typelib_path, read, limit=limit)

    diagnostics["stage"] = "context"
    check()
    before, _doc, _part, machine, app = context()
    diagnostics["document"] = before
    check()
    diagnostics["stage"] = "ICWDoc3"
    native_doc = _typed(_doc, "ICWDoc3", typelib_path)
    diagnostics["native_id_reads"] = []
    diagnostics["stage"] = "inventory_before"
    inventory = inventory_of(machine)
    diagnostics["inventory"] = inventory
    check()

    def object_id(obj, label):
        entry = {"label": label, "returned": False}
        diagnostics["native_id_reads"].append(entry)
        values = read(native_doc, "GetCWObjectID", obj)
        entry["returned"] = True
        if not isinstance(values, (tuple, list)) or len(values) != 2:
            raise CamToolStateError("CAM_OBJECT_ID_INVALID_SHAPE", "GetCWObjectID must return (ULONG, BOOL)")
        value, status = values
        entry["object_id"] = value if type(value) is int else {"unexpected_type": type(value).__name__}
        entry["status"] = status if type(status) is bool else {"unexpected_type": type(status).__name__}
        if type(status) is not bool or not status or type(value) is not int or not 0 < value <= 4294967295:
            raise CamToolStateError("CAM_OBJECT_ID_NOT_CONFIRMED", "A successful positive native ULONG object ID is required")
        return value

    operation_ids, tool_ids, groups, assignments, handles = [], [], [], [], []
    diagnostics["operation_tools"] = assignments
    diagnostics["tool_groups"] = groups
    setups = items(read(machine, "IGetEnumOpSetups"))
    for si, raw_setup in enumerate(setups):
        setup = _typed(raw_setup, "ICWBaseOpSetup", typelib_path)
        for oi, raw in enumerate(items(read(setup, "IGetEnumOperations"), 512-len(assignments))):
            if len(assignments) >= 512:
                raise ValueError("Too many operations for tool qualification")
            operation = _typed(raw, "ICWOperation", typelib_path)
            turning = _typed(raw, "ICWTurnOperation", typelib_path)
            ref = {"setup_index": si, "operation_index": oi,
                   "expected_operation_type": _integer(read(turning, "OpernType"))}
            op_id = object_id(operation, f"operation[{si},{oi}]")
            if op_id in operation_ids:
                raise CamToolStateError("CAM_OPERATION_ID_DUPLICATE", "Document operations must have distinct native IDs")
            operation_ids.append(op_id)
            raw_tool = read(operation, "IGetTool")
            group_index = None
            tool = turn_tool = None
            if raw_tool is not None and bool(raw_tool):
                tool = _typed(raw_tool, "ICWTool", typelib_path)
                identity = object_id(tool, f"tool_for_operation[{si},{oi}]")
                group_index = next((i for i, item in enumerate(tool_ids) if item == identity), None)
                generic_type = _integer(read(tool, "ToolType"))
                # 车床清单也可包含钻削工具，不能向非车刀请求 ICWTurnTool。
                if generic_type == 15:
                    turn_tool = _typed(raw_tool, "ICWTurnTool", typelib_path)
                turn_kind = None
                if turn_tool is not None:
                    turn_kind = _integer(read(turn_tool, "ToolType"))
                    if turn_kind != 1:
                        turn_tool = None
                kind = _integer(read(turn_tool, "InsertType")) if turn_tool is not None else None
                dimensions = ({field: _number(read(turn_tool, field)) for field in sorted(_applicable(kind))}
                              if turn_tool is not None else {})
                if group_index is None:
                    group_index = len(tool_ids)
                    tool_ids.append(identity)
                    groups.append({"cam_object_id": identity, "tool_type_raw": generic_type, "insert_type_raw": kind,
                                   "dimensions_native": dimensions,
                                   "parameter_scope": ("turning_whitelist" if turn_tool is not None
                                                       else "non_turn_dimensions_not_read")})
                    groups[group_index]["turn_tool_type_raw"] = turn_kind
                elif (groups[group_index]["tool_type_raw"] != generic_type or
                      groups[group_index]["insert_type_raw"] != kind or
                      groups[group_index]["dimensions_native"] != dimensions or
                      groups[group_index]["turn_tool_type_raw"] != turn_kind):
                    diagnostics["inconsistent_alias"] = {"operation": ref, "cam_object_id": identity,
                        "tool_type_raw": generic_type, "insert_type_raw": kind, "dimensions_native": dimensions}
                    raise CamToolStateError("CAM_TOOL_ID_ALIASES_DIFFER",
                                            "Wrappers with the same CAM tool ID returned inconsistent dimensions/type")
            assignments.append({"operation": ref, "operation_native_id": op_id,
                                "tool_group": group_index,
                                "tool_native_id": tool_ids[group_index] if group_index is not None else None})
            handles.append((raw, operation, tool, turn_tool))
    target = next((i for i, item in enumerate(assignments) if item["operation"] == selected), None)
    if target is None:
        raise ValueError("Selected operation identity/type is absent")
    selected_group = assignments[target]["tool_group"]
    if selected_group is None:
        raise ValueError("Selected operation has no tool")
    _raw, operation, tool, turn_tool = handles[target]
    if groups[selected_group]["tool_type_raw"] != 15 or turn_tool is None:
        raise ValueError("The selected tool must be a verified native turning tool (ToolType=15)")
    station = _typed(read(tool, "GetToolStation"), "ICWToolStation", typelib_path)
    station_id = read(station, "GetStationId")
    diagnostics["station_id_raw"] = (station_id if station_id is None or isinstance(station_id, (str, int, bool))
                                      else {"unexpected_type": type(station_id).__name__})
    if not isinstance(station_id, str):
        raise CamToolStateError("CAM_TOOL_STATION_ID_TYPE_INVALID",
                                "Tool station ID must return its declared BSTR type")
    # 空 BSTR 是有效的已观察值；身份仍由 IUnknown 与全部使用关系验证。
    station_tool = _typed(read(station, "GetTool"), "ICWTool", typelib_path)
    diagnostics["station_wrapper_equals_selected"] = _identity(station_tool) == _identity(tool)
    station_tool_id = object_id(station_tool, "station.GetTool")
    diagnostics["station_tool_native_id"] = station_tool_id
    if station_tool_id != tool_ids[selected_group]:
        raise CamToolStateError("CAM_TOOL_STATION_IDENTITY_MISMATCH", "Station CAM tool ID does not match the selected CAM tool ID")
    roundtrip = {"object_type": 5, "requested_id": tool_ids[selected_group]}
    diagnostics["tool_roundtrip"] = roundtrip
    values = read(native_doc, "GetCWObjectFromID", 5, tool_ids[selected_group])
    if not isinstance(values, (tuple, list)) or len(values) != 2:
        raise CamToolStateError("CAM_TOOL_ID_ROUNDTRIP_INVALID", "GetCWObjectFromID must return (IDispatch, BOOL)")
    raw_again, status = values
    roundtrip["status"] = status if type(status) is bool else {"unexpected_type": type(status).__name__}
    if type(status) is not bool:
        raise CamToolStateError("CAM_TOOL_ID_ROUNDTRIP_INVALID", "Native tool ID roundtrip status must be a Boolean")
    if not status:
        # 逆向查询是额外诊断；false 时不使用未确认的 OUT 对象，也不声称成功。
        roundtrip.update(available=False, reason="native_returned_false", identity_proof_required=False)
    else:
        if raw_again is None or not bool(raw_again):
            raise CamToolStateError("CAM_TOOL_ID_ROUNDTRIP_INVALID", "Successful native ID roundtrip returned no object")
        again = _typed(raw_again, "ICWTool", typelib_path)
        roundtrip["returned_id"] = object_id(again, "tool_roundtrip")
        roundtrip["tool_type_raw"] = _integer(read(again, "ToolType"))
        if roundtrip["returned_id"] != tool_ids[selected_group] or roundtrip["tool_type_raw"] != 15:
            raise CamToolStateError("CAM_TOOL_ID_ROUNDTRIP_MISMATCH", "Native ID roundtrip returned a different tool/type")
    # 此成员由 TLB 定义为 propget；返回的 COM 集合可调用，但不是 getter 方法。
    diagnostics["stage"] = "OperationsUsingThisTool"
    check()
    usage_raw = getattr(station, "OperationsUsingThisTool")
    check()
    usage = items(usage_raw)
    usage_indices = []
    usage_ids = []
    diagnostics["station_usage_operation_ids"] = usage_ids
    for index, raw_used in enumerate(usage):
        used = object_id(_typed(raw_used, "ICWOperation", typelib_path), f"station_usage[{index}]")
        usage_ids.append(used)
        matches = [i for i, identity in enumerate(operation_ids) if identity == used]
        if len(matches) != 1 or matches[0] in usage_indices:
            raise CamToolStateError("CAM_TOOL_USAGE_REFERENCES_INVALID", "Station usage contains unknown or duplicate operations")
        usage_indices.append(matches[0])
    affected_indices = [i for i, item in enumerate(assignments) if item["tool_group"] == selected_group]
    if sorted(usage_indices) != affected_indices:
        raise CamToolStateError("CAM_TOOL_SHARED_USAGE_MISMATCH", "Station usage does not match complete native CAM tool-ID scan")
    linked = items(read(operation, "IGetAllFeatures"), 64)
    if not 1 <= len(linked) <= 64:
        raise ValueError("Selected operation must have 1 to 64 linked features")
    budget = [0]
    profiles = []
    diagnostics["linked_features"] = profiles
    for raw_feature in linked:
        profile = {}
        profiles.append(profile)
        if guarded_readers:
            _read_profile(raw_feature, typelib_path, read, budget, profile, collection_reader=items)
        else:
            _read_profile(raw_feature, typelib_path, read, budget, profile)
    selected_tool = {}
    diagnostics["selected_tool"] = selected_tool
    _read_tool(read(operation, "IGetTool"), operation, typelib_path, read, selected_tool)
    diagnostics["stage"] = "inventory_after"
    after_inventory = inventory_of(machine)
    check()
    diagnostics["stage"] = "document_after"
    after = document_snapshot(sw)
    check()
    if inventory != after_inventory or before != after:
        raise ValueError("Document or operation inventory changed during tool inspection")
    state = {"document": before, "inventory": inventory, "selected_operation": selected,
             "selected_tool_group": selected_group, "station_id": station_id,
             "native_id_scope": "current_CAM_document_snapshot_not_persistent_across_reopen",
             "station_tool_native_id": station_tool_id, "tool_roundtrip": roundtrip,
             "station_usage_operation_ids": usage_ids,
             "affected_operations": [assignments[i]["operation"] for i in affected_indices],
             "operation_tools": assignments, "tool_groups": groups,
             "linked_features": profiles, "selected_tool": selected_tool}
    diagnostics["stage"] = "complete"
    return state, {"app": app, "turn_tool": turn_tool,
                   "native_doc": native_doc, "operation": operation, "tool": tool}


def _verify_change(before, after, field, value):
    expected = deepcopy(before)
    # 文档 dirty 标志及尺寸派生显示字符串可能改变；其他完整读取必须相同。
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    expected["selected_tool"]["info_raw"] = after["selected_tool"]["info_raw"]
    group = before["selected_tool_group"]
    expected["tool_groups"][group]["dimensions_native"][field] = value
    expected["selected_tool"]["dimensions_native"][field] = value
    if expected != after:
        raise ValueError("Readback changed more than the explicitly requested tool dimension")


def configure_turn_tool(sw, clsid, typelib_path, *, expected_document_path, setup_index,
                        operation_index, expected_operation_type, action, field,
                        value_native=None, expected_state_sha256=None,
                        allowed_affected_operations=None, receipt_path=None,
                        qualification_only, message_policy):
    """准备或修改一个已选刀片尺寸；申请值为 native units，仅验证 CAM 定义。

    prepare 只读并返回完整共享引用及旧状态摘要。apply 需要精确摘要、明确允许的
    全部操作和新的持久回执；不生成、保存、克隆工具或修改数据库。
    """
    from scripts.sw_cam_events import CamMessageSession
    selected = _reference({"setup_index": setup_index, "operation_index": operation_index,
                           "expected_operation_type": expected_operation_type})
    if action not in {"prepare", "apply"} or field not in _FIELDS:
        raise ValueError("Unsupported tool action or dimension")
    if qualification_only is not True or message_policy != "vendor_default":
        raise ValueError("Explicit qualification-only/vendor-default policy is required")
    if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold() != ".sldprt"):
        raise ValueError("An exact absolute saved working part is required")
    if action == "prepare":
        if any(value is not None for value in (value_native, expected_state_sha256,
                                               allowed_affected_operations, receipt_path)):
            raise ValueError("Prepare does not accept mutation inputs or a receipt")
        receipt = None
    else:
        value_native = _number(value_native)
        if value_native < 0 or (field in {"Width", "Thickness", "InscribedCircle"} and value_native == 0):
            raise ValueError("Radii must be nonnegative; Width, Thickness and InscribedCircle must be positive")
        if (not isinstance(expected_state_sha256, str) or len(expected_state_sha256) != 64 or
                any(char not in "0123456789abcdef" for char in expected_state_sha256)):
            raise ValueError("The exact prepare SHA-256 is required")
        if not isinstance(allowed_affected_operations, list) or not 1 <= len(allowed_affected_operations) <= 512:
            raise ValueError("Explicit affected operation references are required")
        allowed_affected_operations = [_reference(item) for item in allowed_affected_operations]
        if len({(item["setup_index"], item["operation_index"]) for item in allowed_affected_operations}) != len(allowed_affected_operations):
            raise ValueError("Affected operation references must be unique")
        if selected not in allowed_affected_operations:
            raise ValueError("Selected operation must be explicitly allowed")
        receipt = Path(receipt_path) if isinstance(receipt_path, str) else None
        if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != ".json"
                or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink()):
            raise ValueError("A new absolute JSON receipt with an existing parent is required")
    report = {"status": "started", "action": action, "field": field, "value_native": value_native,
              "mutation_attempted": False, "native_call_returned": False, "readback_verified": False,
              "model_saved": False, "generation_attempted": False, "physical_tool_qualified": False,
              "native_units_verified": False, "may_continue": False, "phase": "preflight",
              "snapshot_diagnostics": [],
              "attempt_marker_meaning": "durable_intent_before_property_put_not_proof_of_entry"}
    if receipt:
        _write_receipt(receipt, report, create=True)
    session = None

    def capture(phase, check=lambda: None):
        diagnostic = {"phase": phase}
        report["snapshot_diagnostics"].append(diagnostic)
        return _snapshot(sw, clsid, typelib_path, selected, check=check, diagnostics=diagnostic)

    try:
        initial, native = capture("initial")
        report["before"] = initial
        check_document_target(initial["document"]["path"], initial["document"]["title"],
                              expected_path=expected_document_path, required=True)
        if initial["document"]["needs_save"]:
            raise ValueError("Tool changes require a clean saved working copy")
        group = initial["selected_tool_group"]
        if field not in initial["tool_groups"][group]["dimensions_native"]:
            raise ValueError("The requested dimension is not applicable to this insert")
        report["state_sha256"] = _digest(initial)
        report["profile_sha256"] = _digest(initial["linked_features"])
        report["tool_sha256"] = _digest(initial["selected_tool"])
        generated = [item for item in initial["inventory"]["operations"] if item["toolpath_generated"] and
            any(item["setup_index"] == ref["setup_index"] and item["operation_index"] == ref["operation_index"]
                for ref in initial["affected_operations"])]
        report["affected_generated_operations"] = generated
        report["apply_eligible"] = not generated
        if action == "prepare":
            report.update(status="ok", phase="prepared")
            return report
        if generated:
            raise ValueError("An affected operation already has a generated toolpath")
        if report["state_sha256"] != expected_state_sha256:
            raise ValueError("Expected profile/tool/operation state has changed; prepare again")
        if sorted(allowed_affected_operations, key=_ref_key) != initial["affected_operations"]:
            raise ValueError("Allowed references do not exactly match all operations sharing this tool")
        old_value = initial["tool_groups"][group]["dimensions_native"][field]
        if old_value == value_native:
            raise ValueError("Requested value is already present; no mutation is required")
        session = CamMessageSession(native["app"], typelib_path)

        def check_messages():
            summary = session.summary()
            report["messages"] = summary
            if (not summary.get("subscribed") or summary.get("event_count") or summary.get("overflow")
                    or summary.get("callback_errors") or summary.get("callback_error_count")
                    or summary.get("subscription_error") or summary.get("disconnect_errors")):
                raise ValueError("CAM messages require review; no further native calls")

        with session:
            check_messages()
            current, native = capture("pre_write", check_messages)
            if current != initial:
                raise ValueError("Native precondition changed immediately before property put")
            report.update(phase="property_put", mutation_attempted=True)
            _write_receipt(receipt, report)
            if document_snapshot(sw) != initial["document"]:
                raise ValueError("Document changed before property put")
            check_messages()
            setattr(native["turn_tool"], field, value_native)
            report.update(native_call_returned=True, phase="property_put_returned")
            _write_receipt(receipt, report)
            check_messages()
            after, _native = capture("after_write", check_messages)
            report["after"] = after
            _verify_change(initial, after, field, value_native)
            report["readback_before_cleanup_verified"] = True
            _write_receipt(receipt, report)
        check_messages()
        if not session.summary().get("disconnected"):
            raise ValueError("CAM event cleanup was not confirmed")
        report["phase"] = "post_cleanup_readback"
        after, _native = capture("after_cleanup", check_messages)
        report["after_cleanup"] = after
        _verify_change(initial, after, field, value_native)
        report.update(status="review_required", phase="finished", readback_verified=True,
                      reason="CAM_DEFINITION_ONLY_PHYSICAL_TOOL_AND_PERSISTENCE_REQUIRE_REVIEW",
                      verification_scope="all_operation_references_after_event_cleanup")
    except Exception as exc:
        diagnostic = report["snapshot_diagnostics"][-1] if report["snapshot_diagnostics"] else {}
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
                      reason=getattr(exc, "reason", "CAM_TOOL_CONFIGURATION_FAILED"),
                      issue=_error(exc), failed_phase=report["phase"],
                      failed_stage=(report["phase"] if report["phase"] == "property_put"
                                    else diagnostic.get("stage", report["phase"])), phase="finished")
    finally:
        if session is not None:
            report["messages"] = session.summary()
        if receipt:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status="uncertain", receipt_write_error=_error(exc), readback_verified=False)
    return report
