"""CAM 保存提示的严格 UI 目标门禁；全部窗口与消息均为模拟，不操作桌面。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.sw_cam_save_prompt import handle_cam_save_prompt

TITLE = "Предупреждение SOLIDWORKS CAM"
BASENAME = "CALIBRATION.SLDPRT"
TEXT = f"Сохранить изменения в {BASENAME} ?"


@pytest.fixture
def prompt():
    windows = {}
    for root, pid in ((10, 100), (20, 200)):
        windows[root] = dict(text=TITLE, cls="#32770", pid=pid, parent=0, ident=0, visible=True, enabled=True, exists=True)
        for offset, text, cls, ident in ((1, TEXT, "Static", -1), (2, "&Да", "Button", 6), (3, "&Нет", "Button", 7)):
            windows[root + offset] = dict(text=text, cls=cls, pid=pid, parent=root, ident=ident,
                                         visible=True, enabled=True, exists=True)
    state = {"enumerations": 0, "before_enumerate": None, "on_post": None, "dismiss": True}

    def enumerate_windows(visit, argument):
        state["enumerations"] += 1
        if state["before_enumerate"]:
            state["before_enumerate"](state["enumerations"])
        for handle, data in list(windows.items()):
            if data["parent"] == 0 and data["exists"]:
                visit(handle, argument)

    def enumerate_children(parent, visit, argument):
        for handle, data in list(windows.items()):
            if data["parent"] == parent and data["exists"]:
                visit(handle, argument)

    def post(*args):
        if state["on_post"]:
            state["on_post"]()
        elif state["dismiss"]:
            windows[args[0]]["exists"] = False

    gui = SimpleNamespace(
        EnumWindows=enumerate_windows, EnumChildWindows=enumerate_children,
        GetWindowText=lambda h: windows[h]["text"], GetClassName=lambda h: windows[h]["cls"],
        GetDlgCtrlID=lambda h: windows[h]["ident"], GetParent=lambda h: windows[h]["parent"],
        IsWindowVisible=lambda h: windows[h]["visible"], IsWindowEnabled=lambda h: windows[h]["enabled"],
        IsWindow=lambda h: h in windows and windows[h]["exists"],
        GetDlgItem=lambda h, ident: next((key for key, d in windows.items() if d["parent"] == h and d["ident"] == ident), 0),
        PostMessage=Mock(side_effect=post),
    )
    processes = SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, windows[h]["pid"]))
    sleeper = Mock()

    def run(**changes):
        values = dict(process_id=100, expected_document_basename=BASENAME, action="discard", acknowledge_discard=True,
                      gui=gui, processes=processes, sleep=sleeper)
        values.update(changes)
        return handle_cam_save_prompt(**values)

    return SimpleNamespace(windows=windows, state=state, gui=gui, processes=processes, sleep=sleeper, run=run)


def test_inspection_is_readonly_and_returns_exact_evidence(prompt):
    result = prompt.run(action="inspect", acknowledge_discard=False)
    assert result["status"] == "inspected" and result["matching_prompt_count"] == 1
    assert result["expected_title"] == TITLE and result["expected_text"] == TEXT
    assert result["button_invocation_count"] == 0 and result["can_discard"] is True
    assert result["native_cam_api_used"] is False and result["com_probe_performed"] is False
    prompt.gui.PostMessage.assert_not_called()
    prompt.sleep.assert_not_called()


@pytest.mark.parametrize("label", ["&Нет", "Нет", "&No", "No"])
def test_explicit_discard_invokes_actual_no_button_once_and_verifies_disappearance(prompt, label):
    prompt.windows[13]["text"] = label
    result = prompt.run()
    prompt.gui.PostMessage.assert_called_once_with(10, 0x111, 7, 13)
    assert result["status"] == "dismissed" and result["dismissal_confirmed"] is True
    assert result["button_invocation_count"] == 1
    assert prompt.windows[20]["exists"] is True
    assert result["document_save_state"] == "not_verified"


@pytest.mark.parametrize("pid", [None, True, 0, -1, "100", 100.0, 2**32])
def test_process_id_cannot_be_inferred_or_coerced(prompt, pid):
    with pytest.raises(ValueError):
        prompt.run(process_id=pid)
    prompt.gui.PostMessage.assert_not_called()
    assert prompt.state["enumerations"] == 0


@pytest.mark.parametrize("name", [None, "", "../a.SLDPRT", r"C:\a.SLDPRT", r"folder\a.SLDPRT", "a/b.SLDPRT",
                                  "a:part.SLDPRT", "a?.SLDPRT", "a.SLDASM", " a.SLDPRT", "a.SLDPRT ",
                                  "a\n.SLDPRT", "x" * 256 + ".SLDPRT"])
def test_document_must_be_an_exact_part_basename(prompt, name):
    with pytest.raises(ValueError):
        prompt.run(expected_document_basename=name)
    prompt.gui.PostMessage.assert_not_called()
    assert prompt.state["enumerations"] == 0


@pytest.mark.parametrize("acknowledgement", [False, None, 0, 1, 1.0, "true"])
def test_discard_requires_strict_explicit_acknowledgement(prompt, acknowledgement):
    with pytest.raises(ValueError):
        prompt.run(acknowledge_discard=acknowledgement)
    prompt.gui.PostMessage.assert_not_called()
    assert prompt.state["enumerations"] == 0


@pytest.mark.parametrize("handle,field,value", [
    (10, "pid", 300), (10, "cls", "UnknownDialog"), (10, "text", "SOLIDWORKS"),
    (10, "visible", False), (10, "enabled", False),
    (11, "text", "Сохранить изменения в PRODUCTION.SLDPRT ?"),
    (11, "text", TEXT + " extra"), (11, "pid", 200),
    (13, "text", "&Да"), (13, "text", "Cancel"), (13, "cls", "Static"),
    (13, "pid", 200), (13, "enabled", False), (13, "visible", False), (13, "ident", 0),
])
def test_unknown_prompt_or_button_is_never_invoked(prompt, handle, field, value):
    prompt.windows[handle][field] = value
    result = prompt.run()
    assert result["status"] == "blocked" and result["button_invocation_count"] == 0
    prompt.gui.PostMessage.assert_not_called()


def test_ambiguous_matching_prompts_are_not_discarded(prompt):
    for handle in (20, 21, 22, 23):
        prompt.windows[handle]["pid"] = 100
    result = prompt.run()
    assert result["matching_prompt_count"] == 2 and result["status"] == "blocked"
    prompt.gui.PostMessage.assert_not_called()


def test_duplicate_no_buttons_are_rejected(prompt):
    prompt.windows[14] = {**prompt.windows[13], "ident": 8}
    assert prompt.run()["status"] == "blocked"
    prompt.gui.PostMessage.assert_not_called()


@pytest.mark.parametrize("handle,field,value", [(10, "pid", 200), (10, "cls", "Other"),
                                                (10, "text", "Other"), (11, "text", "Other document"),
                                                (13, "text", "&Да"), (13, "enabled", False), (13, "ident", 8)])
def test_target_is_revalidated_before_the_single_action(prompt, handle, field, value):
    def change(count):
        if count == 2:
            prompt.windows[handle][field] = value
    prompt.state["before_enumerate"] = change
    result = prompt.run()
    assert result["status"] == "blocked" and result["reason"] == "CAM_SAVE_PROMPT_CHANGED_BEFORE_ACTION"
    prompt.gui.PostMessage.assert_not_called()


def test_actual_button_handle_is_revalidated_by_control_id(prompt):
    prompt.gui.GetDlgItem = lambda *_: 999
    assert prompt.run()["status"] == "blocked"
    prompt.gui.PostMessage.assert_not_called()


def test_no_disappearance_is_uncertain_and_never_retried(prompt):
    prompt.state["dismiss"] = False
    result = prompt.run()
    assert result["status"] == "uncertain" and result["dismissal_confirmed"] is False
    assert result["reason"] == "DIALOG_DISAPPEARANCE_NOT_CONFIRMED"
    prompt.gui.PostMessage.assert_called_once()
    assert prompt.sleep.call_count == 20


def test_post_failure_is_uncertain_and_never_retried(prompt):
    prompt.gui.PostMessage.side_effect = OSError("notification failed")
    result = prompt.run()
    assert result["status"] == "uncertain" and result["dismissal_confirmed"] is False
    assert result["button_invocation_count"] == 1
    prompt.gui.PostMessage.assert_called_once()


def test_changed_window_identity_after_post_is_not_claimed_as_success(prompt):
    prompt.state["on_post"] = lambda: prompt.windows[10].update(pid=999)
    result = prompt.run()
    assert result["status"] == "uncertain" and result["dismissal_confirmed"] is False
    assert result["reason"] == "DIALOG_IDENTITY_CHANGED_AFTER_ACTION"
    prompt.gui.PostMessage.assert_called_once()


def test_hidden_original_dialog_confirms_disappearance_without_further_input(prompt):
    prompt.state["on_post"] = lambda: prompt.windows[10].update(visible=False)
    result = prompt.run()
    assert result["status"] == "dismissed" and result["dismissal_confirmed"] is True
    prompt.gui.PostMessage.assert_called_once()


def test_recreated_matching_dialog_is_not_treated_as_disappearance(prompt):
    def replacement():
        prompt.windows[10]["exists"] = False
        for handle in (20, 21, 22, 23):
            prompt.windows[handle]["pid"] = 100
    prompt.state["on_post"] = replacement
    result = prompt.run()
    assert result["status"] == "uncertain" and result["dismissal_confirmed"] is False
    assert result["matching_prompt_count_after"] == 1
    assert result["reason"] == "MATCHING_PROMPT_REMAINS_AFTER_ACTION"
    prompt.gui.PostMessage.assert_called_once_with(10, 0x111, 7, 13)
