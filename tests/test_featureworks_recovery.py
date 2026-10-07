"""FeatureWorks 恢复只取消选定进程的已知识别提示。"""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts.sw_dialogs import cancel_featureworks_prompt


def gui_fixture(title="FeatureWorks", button="&No", text="Do you want to proceed with feature recognition?"):
    """两个进程显示相似窗口，用于证明不会操作邻近会话。"""
    gui = SimpleNamespace(
        EnumWindows=lambda visit, arg: [visit(h, arg) for h in (10, 20)],
        EnumChildWindows=lambda h, visit, arg: [visit(h+i, arg) for i in (1, 2)],
        GetWindowText=lambda h: {10: title, 20: title, 11: text, 21: text, 12: button, 22: button}[h],
        GetClassName=lambda h: "#32770" if h in (10, 20) else ("Button" if h in (12, 22) else "Static"),
        IsWindowVisible=lambda h: True, IsWindowEnabled=lambda h: True,
        GetDlgCtrlID=lambda h: 2 if h in (12, 22) else -1,
        GetDlgItem=lambda h, command: h+2,
        PostMessage=Mock(),
    )
    processes = SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 100 if h < 20 else 200))
    return gui, processes


def test_only_explicit_process_is_cancelled():
    gui, processes = gui_fixture()
    result = cancel_featureworks_prompt(100, gui=gui, processes=processes)
    gui.PostMessage.assert_called_once_with(10, 0x111, 2, 12)
    assert result["status"] == "posted" and not result["com_probe_performed"]


@pytest.mark.parametrize("kwargs", [{"title": "SOLIDWORKS"}, {"button": "Yes"}, {"text": "Save changes?"}])
def test_unrelated_or_unrecognized_prompt_is_untouched(kwargs):
    gui, processes = gui_fixture(**kwargs)
    result = cancel_featureworks_prompt(100, gui=gui, processes=processes)
    gui.PostMessage.assert_not_called()
    assert result["status"] == "no_matching_prompt"


@pytest.mark.parametrize("pid", [None, 0, -1, True, "100"])
def test_unbound_process_is_rejected(pid):
    with pytest.raises(ValueError):
        cancel_featureworks_prompt(pid)


def test_russian_prompt_uses_actual_cancel_command():
    gui, processes = gui_fixture(button="&Нет", text="Вы хотите продолжить распознавание элементов?")
    cancel_featureworks_prompt(100, gui=gui, processes=processes)
    gui.PostMessage.assert_called_once_with(10, 0x111, 2, 12)
