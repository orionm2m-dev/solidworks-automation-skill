"""独立试件刀路计算与显式停止观察；不保存、不输出 NC、不取消原生计算。"""
from __future__ import annotations

import math
import time

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _collection, _context, _inventory, _typed
from scripts.sw_operation_guard import check_document_target


def _selected_operation(machine, typelib_path, setup_index, operation_index):
    setups = _collection(_member(machine, "IGetEnumOpSetups"), typelib_path)
    setup = _typed(setups[setup_index], "ICWBaseOpSetup", typelib_path)
    operations = _collection(_member(setup, "IGetEnumOperations"), typelib_path)
    return operations[operation_index]


def _same_document(before, after):
    return all(before[key] == after[key] for key in ("path", "title", "type"))


def _message_problem(summary):
    return bool(summary.get("event_count") or summary.get("callback_errors") or
                summary.get("overflow") or summary.get("disconnect_errors") or
                summary.get("subscription_error"))


def _pump_wait(seconds):
    """仅处理本线程 COM 消息，不操作应用窗口。"""
    import pythoncom
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pythoncom.PumpWaitingMessages()
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def _process_gone(config):
    from scripts.sw_cam_jobs import process_identity
    current = process_identity(config["process_id"])
    if current.get("alive") is False:
        return True
    return (current.get("alive") is True and current.get("create_time") is not None and
            current.get("create_time") != config["process_create_time"])


def _wait_completion(app, messages, config, report, publish, *, started, operation, stop_observation=None):
    """原生调用返回后观察结果；超时不取消，显式停止只释放观察上下文。"""
    last_publish = -1.0
    while True:
        if stop_observation is not None:
            try:
                stop_requested = stop_observation() is True
            except Exception as exc:
                # 无法读到停止命令不等于收到命令，继续持有上下文。
                stop_requested = False
                report["stop_observation_error"] = _error(exc)
                report["stop_observation_error_count"] = report.get("stop_observation_error_count", 0) + 1
            if stop_requested:
                report.update(status="uncertain", observation_stopped=True,
                              native_cancelled=False, completion_observed=False,
                              result_verified=False, may_continue=False,
                              reason="OBSERVATION_STOPPED_NATIVE_OUTCOME_UNKNOWN")
                return False
        try:
            gone = _process_gone(config)
        except Exception as exc:
            gone = False
            report["process_query_error"] = _error(exc)
        if gone:
            report.update(status="error", reason="CAM_PROCESS_EXITED", completion_observed=False)
            return False
        try:
            # 文档明确此标志表示该操作成功生成；调用前已验证为 False。
            complete = bool(_member(operation, "GetIsToolpathGenerated"))
            report["completion_query_error"] = None
        except Exception as exc:
            complete = False
            report["completion_query_error"] = _error(exc)
            report["completion_query_error_count"] = report.get("completion_query_error_count", 0) + 1
        try:
            # 全局 Process Manager 属于复杂铣削；False 并不能证明车削仍在运行。
            report["background_completion_flag"] = bool(_member(app, "IsBackgroundProcessForGTPOver"))
        except Exception as exc:
            report["background_flag_error"] = _error(exc)
        elapsed = time.monotonic() - started
        report.update(elapsed_seconds=round(elapsed, 3),
                      attention_required=elapsed >= config["attention_seconds"])
        try:
            report["messages"] = messages.summary()
        except Exception as exc:
            report["message_summary_error"] = _error(exc)
        if complete:
            report["completion_observed"] = True
            report["completion_source"] = "selected_operation_generated_false_to_true_after_native_return"
            return True
        report.update(status="pending", phase="waiting_native_completion", may_continue=False)
        if elapsed - last_publish >= 1.0:
            # 回执写入失败也不能中断已启动的 CAM；下一次更新继续尝试。
            try:
                publish(dict(report))
            except Exception as exc:
                report["receipt_write_error"] = _error(exc)
            last_publish = elapsed
        try:
            _pump_wait(0.25)
        except Exception as exc:
            report["message_pump_error"] = _error(exc)
            time.sleep(0.25)


def run_toolpath_job(sw, config, publish, *, stop_observation=None):
    """在调用方的 PID 互斥锁和 COM apartment 内计算一条明确选择的刀路。

    超时本身不取消计算。stop_observation 回调只在 GenerateToolpath 返回后
    检查；明确返回 True 时解除消息订阅并返回 uncertain，不能宣称原生计算
    已取消或完成，也不能中断尚未返回的 COM 调用。回调异常不释放上下文。
    消息使用供应商默认响应，不代表取消；任何消息阻止自动继续。
    仅允许独立保存的试件。
    """
    if config.get("qualification_only") is not True or config.get("message_policy") != "vendor_default":
        raise ValueError("Explicit qualification-only/vendor-default policy is required")
    report = {"status": "started", "phase": "preflight", "mutation_attempted": False,
              "may_continue": False, "model_saved": False, "nc_exported": False,
              "production_process_qualified": False, "completion_observed": False,
              "observation_stopped": False, "native_cancelled": False,
              "default_response_is_not_cancellation": True}
    messages = None
    typelib = config["typelib_path"]
    try:
        before, _doc, _part, machine, app = _context(sw, config["addin_clsid"], typelib)
        report["document_before"] = before
        check_document_target(before["path"], before["title"],
                              expected_path=config["expected_document_path"], required=True)
        if before["needs_save"]:
            raise ValueError("Save the separate calibration part before starting a path")
        initial = _inventory(machine, typelib)
        report["before"] = initial
        for key in ("feature_count", "operation_count", "operation_setup_count"):
            if initial[key] != config["expected_" + key]:
                raise ValueError("CAM inventory changed: " + key)
        selected = next((op for op in initial["operations"]
                         if op["setup_index"] == config["setup_index"] and
                         op["operation_index"] == config["operation_index"]), None)
        if selected is None or selected["turn_operation_type"] != config["expected_operation_type"]:
            raise ValueError("Selected turning operation changed")
        if selected["toolpath_generated"]:
            raise ValueError("Existing generated paths are never regenerated by this tool")
        report["background_completion_flag_before"] = bool(_member(app, "IsBackgroundProcessForGTPOver"))
        raw_op = _selected_operation(machine, typelib, config["setup_index"], config["operation_index"])
        operation = _typed(raw_op, "ICWTurnOperation", typelib)
        completion_operation = _typed(raw_op, "ICWOperation", typelib)
        messages = CamMessageSession(app, typelib)
        with messages:
            if document_snapshot(sw) != before or _message_problem(messages.summary()):
                raise ValueError("Document or CAM messages changed before generation")
            if not messages.summary().get("subscribed"):
                raise ValueError("Native CAM message subscription is required")
            if _inventory(machine, typelib) != initial:
                raise ValueError("CAM plan changed during native event subscription")
            if (_message_problem(messages.summary()) or document_snapshot(sw) != before):
                raise ValueError("CAM state changed immediately before generation")
            report.update(status="running", phase="in_native_call", messages=messages.summary())
            # 必须先持久化尝试记录；此后不能因磁盘/客户端超时释放事件连接。
            report["mutation_attempted"] = True
            publish(dict(report))
            started = time.monotonic()
            native_error = None
            try:
                _member(operation, "GenerateToolpath")
            except Exception as exc:
                native_error = _error(exc)
                report["native_call_error"] = native_error
            completed = _wait_completion(app, messages, config, report, publish,
                                         started=started, operation=completion_operation,
                                         stop_observation=stop_observation)
            if completed:
                after_document = document_snapshot(sw)
                report["document_after"] = after_document
                if not _same_document(before, after_document):
                    raise ValueError("Active document changed during generation")
                _state, _doc, _part, after_machine, _app = _context(sw, config["addin_clsid"], typelib)
                after = _inventory(after_machine, typelib)
                report["after"] = after
                observed = next(op for op in after["operations"]
                                if op["setup_index"] == config["setup_index"] and
                                op["operation_index"] == config["operation_index"])
                actual_op = _typed(_selected_operation(after_machine, typelib, config["setup_index"],
                                   config["operation_index"]), "ICWOperation", typelib)
                feed = float(_member(actual_op, "ToolpathFeedLength"))
                if not math.isfinite(feed):
                    raise ValueError("CAM returned a non-finite feed length")
                report["selected_result"] = {**observed, "feed_length_native_units": feed,
                                             "length_units_verified": False}
                same_inventory = all(after[key] == initial[key] for key in
                                     ("feature_count", "operation_count", "operation_setup_count"))
                others_unchanged = [op for op in after["operations"] if op is not observed] == [
                    op for op in initial["operations"] if op is not selected]
                achieved = (same_inventory and others_unchanged and
                            observed["turn_operation_type"] == config["expected_operation_type"] and
                            observed["toolpath_generated"] and sum(observed["toolpath_record_counts"]) > 0 and
                            math.isfinite(feed) and feed > 0)
                report.update(status="completed" if achieved and native_error is None else "error",
                              result_verified=achieved, other_operations_unchanged=others_unchanged)
                if not achieved:
                    report["reason"] = "CAM_TOOLPATH_RESULT_NOT_VERIFIED"
        report["messages"] = messages.summary()
        report["document_after"] = document_snapshot(sw) if report["completion_observed"] else None
        if report["document_after"] and not _same_document(before, report["document_after"]):
            report.update(status="error", reason="CAM_DOCUMENT_CHANGED")
        if (_message_problem(report["messages"]) or not report["messages"].get("disconnected") or
                report.get("message_summary_error") or report.get("message_pump_error")):
            report["message_review_required"] = True
            if not report["observation_stopped"]:
                report.update(status="review_required", reason="CAM_MESSAGES_REQUIRE_REVIEW")
        report["may_continue"] = report["status"] == "completed"
    except Exception as exc:
        report.update(status="error", reason="CAM_TOOLPATH_JOB_FAILED", issue=_error(exc), may_continue=False)
        if messages is not None:
            report["messages"] = messages.summary()
    report["phase"] = "finished"
    return report
