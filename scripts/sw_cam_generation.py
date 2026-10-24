"""独立 CAM 试件的单步验证；不保存模型、不输出 NC、不处理窗口。"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from scripts.sw_cam import _error, _member, _turning_context, document_snapshot
from scripts.sw_cam_comtypes import query_cam_interface

_LIMIT = 512


def _typed(obj, name, typelib_path):
    return query_cam_interface(obj, name, typelib_path)


def _collection(obj, typelib_path):
    col = _typed(obj, "ICWDispatchCollection", typelib_path)
    count = int(_member(col, "Count"))
    if not 0 <= count <= _LIMIT:
        raise ValueError("CAM collection exceeds qualification limit")
    return [_member(col, "Item", index) for index in range(count)]


def _context(sw, clsid, typelib_path):
    before, doc, part, machine, _candidates, _count = _turning_context(sw, clsid, typelib_path)
    if int(_member(machine, "MachType")) != 3:
        raise ValueError("Qualification requires a turning machine")
    app = _typed(_member(sw.GetAddInObject(clsid), "GetCWApp"), "ICWApp4", typelib_path)
    return before, doc, part, machine, app


def _inventory(machine, typelib_path):
    setups = _collection(_member(machine, "IGetEnumSetups"), typelib_path)
    feature_counts = []
    for item in setups:
        setup = _typed(item, "ICWBaseSetup", typelib_path)
        feature_counts.append(len(_collection(_member(setup, "IGetEnumFeatures"), typelib_path)))
    op_setups = _collection(_member(machine, "IGetEnumOpSetups"), typelib_path)
    operations = []
    for setup_index, item in enumerate(op_setups):
        setup = _typed(item, "ICWBaseOpSetup", typelib_path)
        for operation_index, value in enumerate(_collection(_member(setup, "IGetEnumOperations"), typelib_path)):
            if len(operations) >= _LIMIT:
                raise ValueError("Too many CAM operations for qualification")
            operation = _typed(value, "ICWOperation", typelib_path)
            turn_operation = _typed(value, "ICWTurnOperation", typelib_path)
            generated = bool(_member(operation, "GetIsToolpathGenerated"))
            records = []
            if generated:
                for toolpath in _collection(_member(operation, "IGetEnumToolpaths"), typelib_path):
                    path = _typed(toolpath, "ICWToolpath", typelib_path)
                    count = int(_member(path, "RecordCount"))
                    if count < 0:
                        raise ValueError("Negative CAM toolpath record count")
                    records.append(count)
            operations.append({"setup_index": setup_index, "operation_index": operation_index,
                               "turn_operation_type": int(_member(turn_operation, "OpernType")),
                               "toolpath_generated": generated, "toolpath_record_counts": records})
    stock = _typed(_member(machine, "IGetWorkpiece"), "ICWTurnWorkpiece", typelib_path)
    stock_type = int(_member(stock, "GetTurnWorkpieceType"))
    # 只读原生参数；不猜测单位，不改变自动生成的毛坯。
    stock_data = {"type": stock_type, "parameters_modified": False,
                  "length_units": "native_API_units_not_assumed"}
    return {"machine_type": 3, "feature_setup_count": len(setups),
            "feature_counts_by_setup": feature_counts, "feature_count": sum(feature_counts),
            "operation_setup_count": len(op_setups), "operation_count": len(operations),
            "operations": operations, "stock": stock_data}


def inspect_machining(sw, clsid, typelib_path):
    """读取试件特征、操作和已生成刀路；不生成、不保存。"""
    try:
        before, _doc, _part, machine, _app = _context(sw, clsid, typelib_path)
        data = _inventory(machine, typelib_path)
        after = document_snapshot(sw)
        return {"status": "ok" if before == after else "error", "inventory": data,
                "document_before": before, "document_after": after,
                "active_document_unchanged": before == after, "model_saved": False}
    except Exception as exc:
        return {"status": "error", "reason": "CAM_MACHINING_INSPECTION_FAILED", "issue": _error(exc)}


def inspect_operation(sw, clsid, typelib_path, *, setup_index, operation_index):
    """只读指定车削操作的诊断值；不把成功标志误认为后台执行状态。

    参数为已绑定的 SOLIDWORKS 会话、已验证的插件/类型库及零基操作索引。
    返回文档与清单前后快照、原生诊断值及可选 getter 的失败信息；不生成或保存。
    """
    report = {"status": "error", "mutation_attempted": False, "generation_attempted": False,
              "model_saved": False, "native_execution_state": "unknown", "diagnostics": []}

    def optional(field, read):
        try:
            return read(), True
        except Exception as exc:
            report["diagnostics"].append({"field": field, "issue": _error(exc)})
            return None, False

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("CAM diagnostic number is not finite")
        return number

    try:
        for name, value in (("setup_index", setup_index), ("operation_index", operation_index)):
            if type(value) is not int or not 0 <= value < _LIMIT:
                raise ValueError(f"{name} must be an integer in [0, {_LIMIT - 1}]")
        before, _doc, _part, machine, _app = _context(sw, clsid, typelib_path)
        report["document_before"] = before
        initial = _inventory(machine, typelib_path)
        report["inventory"] = initial
        selected = next((item for item in initial["operations"]
                         if item["setup_index"] == setup_index and
                         item["operation_index"] == operation_index), None)
        if selected is None:
            raise ValueError("Selected CAM operation is outside the inspected inventory")
        setups = _collection(_member(machine, "IGetEnumOpSetups"), typelib_path)
        setup = _typed(setups[setup_index], "ICWBaseOpSetup", typelib_path)
        operations = _collection(_member(setup, "IGetEnumOperations"), typelib_path)
        raw_operation = operations[operation_index]
        operation = _typed(raw_operation, "ICWOperation", typelib_path)
        turning = _typed(raw_operation, "ICWTurnOperation", typelib_path)
        details = {**selected, "turn_operation_type": int(_member(turning, "OpernType")),
                   "toolpath_generated": bool(_member(operation, "GetIsToolpathGenerated")),
                   "feed_length_native_units": None, "feed_length_available": False,
                   "length_units_verified": False}
        report["selected_operation"] = details
        report["selected_operation_unchanged"] = all(details[key] == selected[key] for key in
                                                      ("turn_operation_type", "toolpath_generated"))

        # 只报告原生值；缺失工具、未知枚举和读取失败不能自动视为可加工。
        def read_boolean(value):
            if type(value) is not bool:
                raise ValueError("CAM diagnostic value is not a Boolean")
            return value

        def read_integer(value):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("CAM diagnostic value is not an integer")
            return int(value)

        value, available = optional("ICWOperation.Suppressed", lambda: read_boolean(
            _member(operation, "Suppressed")))
        details.update(suppressed=value, suppressed_available=available)

        def read_feature_count():
            collection = _typed(_member(operation, "IGetAllFeatures"), "ICWDispatchCollection", typelib_path)
            count = read_integer(_member(collection, "Count"))
            if not 0 <= count <= _LIMIT:
                raise ValueError("CAM linked feature count exceeds qualification limit")
            return count

        value, available = optional("ICWOperation.IGetAllFeatures.Count", read_feature_count)
        details.update(linked_feature_count=value, linked_feature_count_available=available)
        tool = {"available": False, "present": None, "tool_type_raw": None,
                "tool_type_available": False, "turn_tool_type_raw": None,
                "turn_tool_type_available": False, "info_raw": None,
                "info_available": False, "info_truncated": False,
                "type_names_resolved": False}
        details["tool"] = tool

        def read_tool():
            raw = _member(operation, "IGetTool")
            return raw if raw is not None and bool(raw) else None

        raw_tool, available = optional("ICWOperation.IGetTool", read_tool)
        tool.update(available=available, present=(raw_tool is not None) if available else None)
        if available and raw_tool is not None:
            native_tool, typed_available = optional("ICWTool", lambda: _typed(raw_tool, "ICWTool", typelib_path))
            if typed_available:
                value, field_available = optional("ICWTool.ToolType", lambda: read_integer(
                    _member(native_tool, "ToolType")))
                tool.update(tool_type_raw=value, tool_type_available=field_available)

                def read_tool_info():
                    value = _member(native_tool, "GetToolInfoString")
                    if not isinstance(value, str):
                        raise ValueError("GetToolInfoString did not return a BSTR string")
                    return value

                value, field_available = optional("ICWTool.GetToolInfoString", read_tool_info)
                tool.update(info_raw=value[:1000] if field_available else None,
                            info_available=field_available,
                            info_truncated=field_available and len(value) > 1000)
            value, field_available = optional("ICWTurnTool.ToolType", lambda: read_integer(_member(
                _typed(raw_tool, "ICWTurnTool", typelib_path), "ToolType")))
            tool.update(turn_tool_type_raw=value, turn_tool_type_available=field_available)

        def read_time():
            value = _member(operation, "TimeTakenForGTP")
            if not isinstance(value, str):
                raise ValueError("TimeTakenForGTP did not return a BSTR string")
            return value

        value, available = optional("TimeTakenForGTP", read_time)
        details.update(time_taken_for_gtp_raw=value[:1000] if available else None,
                       time_taken_for_gtp_available=available,
                       time_taken_for_gtp_truncated=available and len(value) > 1000)
        licensed, available = optional("ICWObject.GetIsLicensed", lambda: bool(_member(
            _typed(raw_operation, "ICWObject", typelib_path), "GetIsLicensed")))
        details["object_license"] = {"available": available, "is_licensed": licensed,
                                     "scope": "unknown", "source": "ICWObject.GetIsLicensed"}
        # 没有生成结果时不读取依赖刀路的长度；不推断长度单位。
        if details["toolpath_generated"]:
            value, available = optional("ToolpathFeedLength", lambda: finite(
                _member(operation, "ToolpathFeedLength")))
            details.update(feed_length_native_units=value, feed_length_available=available)
        stock = {**initial["stock"], "bar_parameters_available": False, "bar_parameters": None}
        report["stock"] = stock
        if stock["type"] == 3:  # CW_TURN_WP_BARSTOCK；其他类型不调用棒料专用 getter。
            def read_bar_parameters():
                workpiece = _typed(_member(machine, "IGetWorkpiece"), "ICWTurnWorkpiece", typelib_path)
                values = _member(workpiece, "GetBarStockParameters")
                if not isinstance(values, (tuple, list)) or len(values) != 5:
                    raise ValueError("Unexpected GetBarStockParameters output shape")
                result = dict(zip(("startZ", "length", "odOff", "idOff"), map(finite, values[:4])))
                result["eCWTurnWpAttribute"] = int(values[4])
                return result

            value, available = optional("GetBarStockParameters", read_bar_parameters)
            stock.update(bar_parameters=value, bar_parameters_available=available)
        else:
            stock["bar_parameters_reason"] = "stock_type_is_not_barstock"
        after_inventory = _inventory(machine, typelib_path)
        after = document_snapshot(sw)
        report.update(inventory_after=after_inventory, document_after=after,
                      inventory_unchanged=initial == after_inventory,
                      active_document_unchanged=before == after,
                      diagnostics_complete=not report["diagnostics"])
        unchanged = (report["inventory_unchanged"] and report["active_document_unchanged"] and
                     report["selected_operation_unchanged"])
        report["status"] = "ok" if unchanged else "review_required"
        if not unchanged:
            report.update(reason="CAM_STATE_CHANGED_DURING_INSPECTION", may_continue=False)
    except Exception as exc:
        report.update(status="error", reason="CAM_OPERATION_INSPECTION_FAILED", issue=_error(exc),
                      may_continue=False)
    return report


def _write_receipt(path, report, *, create=False):
    path = Path(path)
    if create:
        with path.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
    else:
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)


def run_qualification_step(sw, clsid, typelib_path, *, step, expected_feature_count,
                           expected_operation_count, receipt_path, qualification_only,
                           message_policy, expected_operation_setup_count=0):
    """一次只验证一个阶段；原生默认消息响应仅适用于明确指定的独立试件。"""
    from scripts.sw_cam_events import CamMessageSession

    if qualification_only is not True or message_policy != "vendor_default":
        raise ValueError("Explicit qualification-only/vendor-default policy is required")
    if step not in {"subscribe", "extract_features", "generate_operations"}:
        raise ValueError("Unsupported CAM qualification step")
    path = Path(receipt_path)
    if not path.is_absolute() or path.suffix.lower() != ".json" or not path.parent.is_dir():
        raise ValueError("An existing absolute directory and new JSON receipt are required")
    report = {"status": "started", "step": step, "mutation_attempted": False,
              "model_saved": False, "message_policy": "vendor_default",
              "default_response_is_not_cancellation": True,
              "production_process_qualified": False}
    # Exclusive receipt creation prevents a timed-out request from replaying.
    _write_receipt(path, report, create=True)
    messages = None
    try:
        before, doc, _part, machine, app = _context(sw, clsid, typelib_path)
        report["document_before"] = before
        if before["needs_save"]:
            raise ValueError("Save the calibration part before qualification")
        initial = _inventory(machine, typelib_path)
        report["before"] = initial
        if (initial["feature_count"] != expected_feature_count or
                initial["operation_count"] != expected_operation_count or
                initial["operation_setup_count"] != expected_operation_setup_count):
            raise ValueError("CAM inventory changed; inspect before starting a step")
        if step == "extract_features" and (expected_feature_count or expected_operation_count or
                                           initial["feature_setup_count"] or initial["operation_setup_count"]):
            raise ValueError("Extraction only qualifies an empty CAM plan")
        if step == "generate_operations" and (expected_feature_count <= 0 or expected_operation_count):
            raise ValueError("Operation generation needs recognized features and no existing operations")
        messages = CamMessageSession(app, typelib_path)
        with messages:
            if document_snapshot(sw) != before:
                raise ValueError("Active document changed before CAM operation")
            entry_events = messages.summary()
            if (entry_events.get("event_count") or entry_events.get("callback_errors") or
                    entry_events.get("overflow") or not entry_events.get("subscribed")):
                raise ValueError("CAM subscription reported messages; mutation was not started")
            if step != "subscribe":
                report["mutation_attempted"] = True
                report["status"] = "in_native_call"
                _write_receipt(path, report)
                if step == "extract_features":
                    report["native_return"] = _member(doc, "ExtractMachinableFeatures")
                else:
                    # CW_GOP_REGENERATE=2; accepted only when no operations exist.
                    _member(app, "ActiveDocGOP", 2)
            after_context, _doc, _part, after_machine, _app = _context(sw, clsid, typelib_path)
            report["after"] = _inventory(after_machine, typelib_path)
            report["document_after"] = after_context
        report["messages"] = messages.summary()
        after = document_snapshot(sw)
        report["document_after"] = after
        same = all(before[key] == after[key] for key in ("path", "title", "type"))
        if step == "subscribe":
            same = before == after and initial == report["after"]
        report["same_document"] = same
        result = report["after"]
        achieved = (step == "subscribe" or
                    (step == "extract_features" and result["feature_count"] > 0) or
                    (step == "generate_operations" and result["operation_count"] > 0))
        event_report = report["messages"]
        clean_events = (event_report.get("subscribed") and event_report.get("disconnected") and
                        not event_report.get("event_count") and not event_report.get("overflow") and
                        not event_report.get("callback_errors") and not event_report.get("disconnect_errors"))
        report["stage_result_present"] = achieved
        report["status"] = "ok" if same and achieved and clean_events else "review_required"
        report["may_continue"] = report["status"] == "ok"
        if not clean_events:
            report["reason"] = "CAM_MESSAGES_REQUIRE_REVIEW"
        elif not achieved:
            report["reason"] = "CAM_STAGE_HAS_NO_RESULT"
        elif not same:
            report["reason"] = "CAM_DOCUMENT_CHANGED"
    except Exception as exc:
        report.update(status="error", reason="CAM_QUALIFICATION_FAILED", issue=_error(exc), may_continue=False)
        if messages is not None:
            report["messages"] = messages.summary()
    _write_receipt(path, report)
    return report
