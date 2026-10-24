"""限定进程和文档的 CAM 保存提示 UI helper；不是原生 CAM API。"""
from __future__ import annotations

import re
import time

_TITLE = "Предупреждение SOLIDWORKS CAM"
_NO_LABELS = {"&Нет", "Нет", "&No", "No"}


def handle_cam_save_prompt(process_id, *, expected_document_basename, action="inspect",
                           acknowledge_discard=False, gui=None, processes=None, sleep=None):
    """只检查或明确拒绝一个已知 CAM 保存提示，不调用 COM、激活窗口或重试点击。

    process_id 必须已由调用方绑定；文档参数只能为精确 SLDPRT 文件名。
    discard 必须显式确认；发送一次实际“否”按钮通知后只读取窗口是否消失。
    此 helper 不获取可能正被模态提示阻塞的 CAD 操作锁。
    """
    if type(process_id) is not int or not 0 < process_id <= 2**32 - 1:
        raise ValueError("An explicit positive process_id is required")
    name = expected_document_basename
    if (not isinstance(name, str) or not 1 <= len(name) <= 255 or name != name.strip()
            or re.search(r'[\\/:*?"<>|\x00-\x1f]', name)
            or not name.casefold().endswith(".sldprt")):
        raise ValueError("expected_document_basename must be an exact SLDPRT basename")
    if action not in {"inspect", "discard"} or type(acknowledge_discard) is not bool:
        raise ValueError("Explicit supported action and JSON boolean acknowledgement are required")
    if action == "discard" and acknowledge_discard is not True:
        raise ValueError("Discarding CAM changes requires acknowledge_discard=true")
    if gui is None:
        import win32gui as gui
    if processes is None:
        import win32process as processes
    sleep = time.sleep if sleep is None else sleep
    expected_text = f"Сохранить изменения в {name} ?"
    report = {"status": "blocked", "action": action, "process_id": process_id,
              "expected_document_basename": name, "expected_title": _TITLE,
              "expected_text": expected_text, "mechanism": "win32_ui_helper",
              "native_cam_api_used": False, "com_probe_performed": False,
              "button_invocation_count": 0, "dismissal_confirmed": False,
              "document_save_state": "not_verified"}

    def snapshot(handle):
        children = []

        def child_visit(child, _):
            if len(children) >= 64:
                raise ValueError("Unexpected CAM prompt control count")
            text = gui.GetWindowText(child)
            children.append({"handle": child, "text": text[:1000], "class": gui.GetClassName(child),
                             "id": gui.GetDlgCtrlID(child), "parent": gui.GetParent(child),
                             "process_id": processes.GetWindowThreadProcessId(child)[1],
                             "visible": bool(gui.IsWindowVisible(child)),
                             "enabled": bool(gui.IsWindowEnabled(child))})
            return True

        gui.EnumChildWindows(handle, child_visit, None)
        return {"handle": handle, "title": gui.GetWindowText(handle), "class": gui.GetClassName(handle),
                "process_id": processes.GetWindowThreadProcessId(handle)[1],
                "visible": bool(gui.IsWindowVisible(handle)), "enabled": bool(gui.IsWindowEnabled(handle)),
                "controls": children}

    def button_for(prompt):
        if (prompt["process_id"] != process_id or prompt["class"] != "#32770"
                or prompt["title"] != _TITLE or not prompt["visible"] or not prompt["enabled"]):
            return None
        texts = [c["text"] for c in prompt["controls"] if c["class"].casefold() == "static" and c["text"]]
        if texts != [expected_text] or any(c["process_id"] != process_id for c in prompt["controls"]):
            return None
        buttons = [c for c in prompt["controls"] if c["class"].casefold() == "button"
                   and c["text"] in _NO_LABELS]
        if len(buttons) != 1:
            return None
        button = buttons[0]
        if (not button["visible"] or not button["enabled"] or button["parent"] != prompt["handle"]
                or not 0 < button["id"] <= 65535):
            return None
        return button

    def collect():
        prompts = []

        def visit(handle, _):
            if (processes.GetWindowThreadProcessId(handle)[1] == process_id
                    and gui.IsWindowVisible(handle) and gui.GetClassName(handle) == "#32770"
                    and gui.GetWindowText(handle) == _TITLE):
                prompts.append(snapshot(handle))
            return True

        gui.EnumWindows(visit, None)
        return prompts

    def confirm_disappearance():
        remaining = collect()
        matches = [p for p in remaining if button_for(p) is not None]
        report.update(prompts_after=remaining, matching_prompt_count_after=len(matches))
        if matches:
            report.update(status="uncertain", reason="MATCHING_PROMPT_REMAINS_AFTER_ACTION", may_continue=False)
        else:
            report.update(status="dismissed", dismissal_confirmed=True)
        return report

    try:
        prompts = collect()
        candidates = [(p, button_for(p)) for p in prompts if button_for(p) is not None]
        report.update(prompts=prompts, matching_prompt_count=len(candidates))
        if len(candidates) != 1:
            report.update(reason="CAM_SAVE_PROMPT_NOT_UNIQUE_OR_NOT_MATCHING", may_continue=False)
            return report
        prompt, button = candidates[0]
        if action == "inspect":
            report.update(status="inspected", can_discard=True)
            return report
        current_prompts = collect()
        current = [(p, button_for(p)) for p in current_prompts if button_for(p) is not None]
        if (len(current) != 1 or current[0] != (prompt, button)
                or snapshot(prompt["handle"]) != prompt
                or gui.GetDlgItem(prompt["handle"], button["id"]) != button["handle"]):
            report.update(reason="CAM_SAVE_PROMPT_CHANGED_BEFORE_ACTION", may_continue=False)
            return report
        # 与 FeatureWorks helper 相同的定向通知；BN_CLICKED=0，不能发送 WM_CLOSE。
        report["button_invocation_count"] = 1
        report["invocation"] = {"dialog": prompt["handle"], "button": button["handle"],
                                "command": button["id"], "message": "WM_COMMAND/BN_CLICKED"}
        gui.PostMessage(prompt["handle"], 0x111, button["id"], button["handle"])
        for attempt in range(21):
            if not gui.IsWindow(prompt["handle"]):
                return confirm_disappearance()
            if (processes.GetWindowThreadProcessId(prompt["handle"])[1] != process_id
                    or gui.GetClassName(prompt["handle"]) != "#32770"
                    or gui.GetWindowText(prompt["handle"]) != _TITLE):
                report.update(status="uncertain", reason="DIALOG_IDENTITY_CHANGED_AFTER_ACTION", may_continue=False)
                return report
            if not gui.IsWindowVisible(prompt["handle"]):
                return confirm_disappearance()
            if attempt < 20:
                sleep(0.1)
        report.update(status="uncertain", reason="DIALOG_DISAPPEARANCE_NOT_CONFIRMED", may_continue=False)
    except Exception as error:
        report.update(status="uncertain" if report["button_invocation_count"] else "error",
                      reason="CAM_SAVE_PROMPT_UI_HELPER_FAILED", may_continue=False,
                      issue={"type": type(error).__name__, "message": str(error)[:500]})
    return report
