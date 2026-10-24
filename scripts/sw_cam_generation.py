"""独立 CAM 试件的单步验证；不保存模型、不输出 NC、不处理窗口。"""
from __future__ import annotations

import json
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
