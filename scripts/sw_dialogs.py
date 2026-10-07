"""无需 COM 的限定进程 FeatureWorks 提示取消；不确认任何保存对话框。"""
from __future__ import annotations


def cancel_featureworks_prompt(process_id, *, gui=None, processes=None):
    """只向指定 PID 的 FeatureWorks 识别提示发送“否”；返回可审计证据。

    此恢复路径故意不取得 COM 操作锁：提示可能正在阻塞持锁调用。
    不修改文档、不调用 COM、不处理其他对话框；再次核对 PID 和按钮。
    """
    if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
        raise ValueError("需要显式绑定有效进程 PID")
    if gui is None:
        import win32gui as gui
    if processes is None:
        import win32process as processes
    candidates = []
    prompts = []

    def visit(handle, _):
        if processes.GetWindowThreadProcessId(handle)[1] != process_id:
            return True
        if (gui.IsWindowVisible(handle) and gui.GetClassName(handle) == "#32770"
                and gui.GetWindowText(handle) == "FeatureWorks"):
            children = []
            def child_visit(child, _):
                children.append({"handle": child, "text": gui.GetWindowText(child),
                                 "class": gui.GetClassName(child), "id": gui.GetDlgCtrlID(child)})
                return True
            gui.EnumChildWindows(handle, child_visit, None)
            prompts.append({"handle": handle, "controls": children})
            prompt_text = " ".join(c["text"].casefold() for c in children if c["class"].lower() == "static")
            if not any(token in prompt_text for token in ("feature recognition", "распознавание элементов", "特征识别", "識別特徵")):
                return True
            no_buttons = [c for c in children if c["class"].lower() == "button"
                          and c["text"].replace("&", "").strip() in {"No", "Нет", "否", "否(N)"}]
            if len(no_buttons) == 1 and gui.IsWindowEnabled(no_buttons[0]["handle"]):
                candidates.append((handle, no_buttons[0]["handle"], no_buttons[0]["id"]))
        return True

    gui.EnumWindows(visit, None)
    dismissed = []
    for handle, button, command in candidates:
        if (processes.GetWindowThreadProcessId(handle)[1] != process_id
                or gui.GetWindowText(handle) != "FeatureWorks" or gui.GetDlgItem(handle, command) != button):
                continue
        if (not gui.IsWindowEnabled(button) or not gui.IsWindowVisible(handle)
                or gui.GetWindowText(button).replace("&", "").strip() not in {"No", "Нет", "否", "否(N)"}):
            continue
        gui.PostMessage(handle, 0x111, command, button)  # WM_COMMAND / 否
        dismissed.append({"handle": handle, "title": "FeatureWorks", "command": command})
    return {"status": "posted" if dismissed else "no_matching_prompt", "process_id": process_id,
            "dismissed": dismissed, "prompts": prompts, "com_probe_performed": False}
