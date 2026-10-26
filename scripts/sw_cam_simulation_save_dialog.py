"""限定进程和已验证零件的 CAM 保存 STL 对话框 UI helper；不是原生 CAM API。"""
from __future__ import annotations

from pathlib import Path
import re
import time

from scripts.sw_cam_generation import _write_receipt
from scripts.sw_operation_guard import absolute_document_path, check_document_target

_DIALOG_TITLE = "Симуляция траектории"
_BUTTON_TEXT = "СохрSTLфайл"
_BUTTON_ID = 6182


def handle_simulation_save_dialog(process_id, *, expected_document_path, verified_document_snapshot,
                                  action="inspect", acknowledge_open_save=False, receipt_path,
                                  gui=None, processes=None, sleep=None):
    """只检查仿真窗口或一次打开保存对话框，不填写文件名或确认保存。

    调用方须持有 PID 操作锁，先通过只读 COM 验证完整零件路径并传入快照。
    进入本 helper 后仅操作限定的窗口，按钮通知之前创建新回执；不使用 COM。
    """
    if type(process_id) is not int or not 0 < process_id <= 2**32 - 1:
        raise ValueError("An explicit positive process_id is required")
    if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold() != ".sldprt"):
        raise ValueError("An exact absolute qualification SLDPRT path is required")
    if action not in {"inspect", "open_save"} or type(acknowledge_open_save) is not bool:
        raise ValueError("Supported action and strict boolean acknowledgement are required")
    if action == "open_save" and acknowledge_open_save is not True:
        raise ValueError("open_save requires acknowledge_open_save=true")
    before = verified_document_snapshot
    if not isinstance(before, dict) or before.get("type") != 1 or before.get("needs_save") is not False:
        raise ValueError("A fresh verified clean saved-part snapshot is required")
    check_document_target(before.get("path"), before.get("title"), expected_path=expected_document_path, required=True)
    name = Path(expected_document_path).name
    receipt = Path(receipt_path)
    if not receipt.is_absolute() or receipt.suffix.casefold() != ".json" or not receipt.parent.is_dir():
        raise ValueError("A new absolute JSON receipt with an existing parent is required")
    if gui is None:
        import win32gui as gui
    if processes is None:
        import win32process as processes
    sleep = time.sleep if sleep is None else sleep
    report = {"status": "started", "phase": "inspect", "action": action, "process_id": process_id,
              "expected_document_path": expected_document_path, "document_before": before,
              "receipt_path": str(receipt), "mechanism": "win32_ui_helper", "native_cam_api_used": False,
              "com_calls_in_helper": False, "full_document_path_verified_by_caller_before_ui": True,
              "expected_dialog_title": _DIALOG_TITLE, "expected_button_text": _BUTTON_TEXT,
              "expected_button_id": _BUTTON_ID, "button_invocation_attempted": False,
              "attempt_marker_meaning": "durable_intent_before_notification_not_proof_of_delivery",
              "button_invocation_count": 0, "file_name_entered": False, "save_confirmed": False,
              "may_continue": False}
    _write_receipt(receipt, report, create=True)

    def basic(handle):
        return {"handle": handle, "title": gui.GetWindowText(handle)[:1000],
                "class": gui.GetClassName(handle), "id": gui.GetDlgCtrlID(handle),
                "parent": gui.GetParent(handle), "process_id": processes.GetWindowThreadProcessId(handle)[1],
                "visible": bool(gui.IsWindowVisible(handle)), "enabled": bool(gui.IsWindowEnabled(handle))}

    def snapshot(handle):
        result = basic(handle)
        controls = []
        def child(child_handle, _):
            if len(controls) >= 256:
                raise ValueError("Unexpected simulation/save dialog control count")
            controls.append(basic(child_handle))
            return True
        gui.EnumChildWindows(handle, child, None)
        result["controls"] = controls
        return result

    def top_windows():
        found = []
        def visit(handle, _):
            if processes.GetWindowThreadProcessId(handle)[1] == process_id and gui.IsWindowVisible(handle):
                found.append(basic(handle))
            return True
        gui.EnumWindows(visit, None)
        return found

    def candidates():
        tops = top_windows()
        pattern = r"(?<![A-Za-z0-9_.-])" + re.escape(name) + r"(?![A-Za-z0-9_.-])"
        mains = [window for window in tops if window["class"] != "#32770"
                 and "SOLIDWORKS" in window["title"].upper()
                 and re.search(pattern, window["title"], re.IGNORECASE) and window["enabled"]]
        found = []
        for main in mains:
            dialog_handles = []
            def find_dialog(handle, _):
                if gui.GetClassName(handle) == "#32770" and gui.GetWindowText(handle) == _DIALOG_TITLE:
                    dialog_handles.append(handle)
                return True
            gui.EnumChildWindows(main["handle"], find_dialog, None)
            for handle in dialog_handles:
                child = basic(handle)
                if child["process_id"] == process_id and child["visible"] and child["enabled"]:
                    dialog = snapshot(handle)
                    buttons = [control for control in dialog["controls"]
                               if control["parent"] == dialog["handle"] and control["class"] == "Button"
                               and control["id"] == _BUTTON_ID and control["title"] == _BUTTON_TEXT
                               and control["process_id"] == process_id and control["visible"] and control["enabled"]]
                    if len(buttons) == 1:
                        found.append((main, dialog, buttons[0]))
        return tops, mains, found

    try:
        tops, mains, found = candidates()
        report.update(top_windows_before=tops, matching_main_count=len(mains), matching_simulation_count=len(found))
        if len(mains) != 1 or len(found) != 1:
            report.update(status="blocked", reason="SIMULATION_SAVE_BUTTON_NOT_UNIQUE_OR_NOT_MATCHING")
            return report
        main, dialog, button = found[0]
        report.update(main_window=main, simulation_dialog=dialog, save_button=button)
        existing_dialogs = [window for window in tops if window["class"] == "#32770"]
        if existing_dialogs:
            report.update(status="blocked", reason="EXISTING_TOP_LEVEL_DIALOG_REQUIRES_REVIEW",
                          existing_dialogs=[snapshot(window["handle"]) for window in existing_dialogs])
            return report
        if action == "inspect":
            report.update(status="inspected", can_open_save=True)
            return report
        _, current_mains, current = candidates()
        if len(current_mains) != 1 or current != found or gui.GetDlgItem(dialog["handle"], _BUTTON_ID) != button["handle"]:
            report.update(status="blocked", reason="SIMULATION_SAVE_TARGET_CHANGED")
            return report
        report.update(phase="before_button_notification", button_invocation_attempted=True,
                      invocation={"dialog": dialog["handle"], "button": button["handle"],
                                  "command": _BUTTON_ID, "message": "WM_COMMAND/BN_CLICKED"})
        _write_receipt(receipt, report)
        if (basic(main["handle"]) != main or snapshot(dialog["handle"]) != dialog
                or basic(button["handle"]) != button
                or gui.GetDlgItem(dialog["handle"], _BUTTON_ID) != button["handle"]):
            report.update(status="blocked", reason="SIMULATION_SAVE_TARGET_CHANGED")
            return report
        # 只向已复核的实际父窗口发送一次按钮通知；不激活窗口、不使用全局按键。
        gui.PostMessage(dialog["handle"], 0x111, _BUTTON_ID, button["handle"])
        report.update(phase="button_notification_queued", button_invocation_count=1)
        _write_receipt(receipt, report)
        initial_handles = {window["handle"] for window in tops}
        for attempt in range(21):
            current = top_windows()
            new_dialogs = [window for window in current if window["handle"] not in initial_handles
                           and window["class"] == "#32770"]
            if new_dialogs:
                report.update(status="dialog_observed", reason="NEW_DIALOG_CONTROLS_REQUIRE_REVIEW",
                              dialogs_after=[snapshot(window["handle"]) for window in new_dialogs])
                return report
            if attempt < 20:
                sleep(0.1)
        report.update(status="uncertain", reason="NEW_SAVE_DIALOG_NOT_OBSERVED", top_windows_after=current)
    except Exception as exc:
        report.update(status="uncertain" if report["button_invocation_attempted"] else "error",
                      reason="SIMULATION_SAVE_DIALOG_HELPER_FAILED",
                      issue={"type": type(exc).__name__, "message": str(exc)[:500]})
    finally:
        report["phase_at_finish"] = report["phase"]
        report["phase"] = "finished"
        try:
            _write_receipt(receipt, report)
        except Exception as exc:
            report.update(status="uncertain", reason="UI_RECEIPT_UPDATE_FAILED",
                          receipt_write_error={"type": type(exc).__name__})
    return report
