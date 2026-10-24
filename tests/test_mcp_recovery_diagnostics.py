"""Read-only, PID-scoped recovery diagnostics; all Win32 and COM calls are fake."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "mcp-server") not in sys.path:
    sys.path.insert(0, str(ROOT / "mcp-server"))
import server  # noqa: E402


@pytest.fixture
def windows(monkeypatch):
    rows = {
        1: {"pid": 731, "visible": True, "title": "VYBRO - SOLIDWORKS", "class": "SolidWorks_SldWorks"},
        2: {"pid": 731, "visible": True, "title": "SOLIDWORKS Design 2026", "class": "#32770"},
        3: {"pid": 999, "visible": True, "title": "SOLIDWORKS foreign session", "class": "#32770"},
        4: {"pid": 731, "visible": False, "title": "SOLIDWORKS hidden", "class": "#32770"},
        20: {"title": "Save changes to TURNING_GENERATION_PROBE.SLDPRT?", "class": "Static"},
        21: {"title": "No", "class": "Button"},
        22: {"title": "Yes", "class": "Button"},
    }
    children = {2: [20, 21, 22], 3: [], 4: []}
    def enum_windows(callback, param):
        for handle in [1, 2, 3, 4]:
            if callback(handle, param) is False:
                break
    def enum_children(handle, callback, param):
        for child in children[handle]:
            if callback(child, param) is False:
                break
    gui = SimpleNamespace(
        EnumWindows=Mock(side_effect=enum_windows), EnumChildWindows=Mock(side_effect=enum_children),
        IsWindowVisible=Mock(side_effect=lambda handle: rows[handle]["visible"]),
        GetWindowText=Mock(side_effect=lambda handle: rows[handle]["title"]),
        GetClassName=Mock(side_effect=lambda handle: rows[handle]["class"]),
        PostMessage=Mock(side_effect=AssertionError("No window control permitted")),
        SendMessage=Mock(side_effect=AssertionError("No window control permitted")),
        SetForegroundWindow=Mock(side_effect=AssertionError("No focus control permitted")),
    )
    process = SimpleNamespace(GetWindowThreadProcessId=Mock(side_effect=lambda handle: (10, rows[handle]["pid"])))
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32process", process)
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(WM_CLOSE=16))
    return SimpleNamespace(rows=rows, children=children, gui=gui, process=process)


def assert_readonly(windows):
    windows.gui.PostMessage.assert_not_called()
    windows.gui.SendMessage.assert_not_called()
    windows.gui.SetForegroundWindow.assert_not_called()


def test_enumeration_reads_only_visible_selected_pid_dialog_text(windows):
    main, dialogs, error = server._enumerate_solidworks_windows(731)
    assert error is None and main["handle"] == 1
    assert [item["handle"] for item in dialogs] == [2]
    assert dialogs[0]["texts"] == [
        {"class": "Static", "text": "Save changes to TURNING_GENERATION_PROBE.SLDPRT?"},
        {"class": "Button", "text": "No"}, {"class": "Button", "text": "Yes"},
    ]
    assert [call.args[0] for call in windows.gui.EnumChildWindows.call_args_list] == [2]
    text_handles = [call.args[0] for call in windows.gui.GetWindowText.call_args_list]
    assert 3 not in text_handles and 4 not in text_handles
    assert_readonly(windows)


def test_child_text_collection_is_bounded_without_control_messages(windows):
    windows.children[2] = list(range(100, 150))
    for handle in windows.children[2]:
        windows.rows[handle] = {"title": "x" * 2500, "class": "Static"}
    _main, dialogs, error = server._enumerate_solidworks_windows(731)
    assert error is None
    assert len(dialogs[0]["texts"]) == 40
    assert all(len(item["text"]) == 2000 for item in dialogs[0]["texts"])
    assert_readonly(windows)


def test_child_read_error_preserves_blocking_dialog_evidence(windows):
    windows.gui.EnumChildWindows.side_effect = RuntimeError("child text inaccessible")
    _main, dialogs, error = server._enumerate_solidworks_windows(731)
    assert error is None
    assert dialogs[0]["handle"] == 2 and dialogs[0]["text_error"] == "RuntimeError"
    assert dialogs[0]["texts"] == []
    assert_readonly(windows)


@pytest.fixture
def recovery(monkeypatch, windows):
    runners = []
    def locked(operation, response_format, **kwargs):
        runners.append(kwargs)
        try:
            return server._result(operation(), response_format)
        except Exception as error:
            return server._tool_error(error, response_format)
    lock = SimpleNamespace(acquire=Mock(return_value=True), release=Mock())
    sw = SimpleNamespace(RevisionNumber="34.4.0")
    connect = Mock(return_value=(sw, None))
    monkeypatch.setattr(server, "_run_locked", locked)
    monkeypatch.setattr(server, "_selected_process_id", 731)
    monkeypatch.setattr(server, "_lock_state", {"acquired_at": None, "thread": None})
    monkeypatch.setattr(server, "_sw_lock", lock)
    monkeypatch.setattr(server, "missing_com_dependencies", Mock(return_value=[]))
    monkeypatch.setattr(server, "_load_automation_modules", Mock())
    monkeypatch.setattr(server, "_coinitialize", Mock())
    monkeypatch.setattr(server, "connect_solidworks", connect)
    monkeypatch.setattr(server, "get_com_member", lambda obj, name: getattr(obj, name), raising=False)
    monkeypatch.delenv("SOLIDWORKS_MCP_PROCESS_ID", raising=False)
    return SimpleNamespace(windows=windows, runners=runners, lock=lock, connect=connect)


def test_default_recovery_reports_modal_blocked_even_when_com_is_responsive(recovery):
    assert server.SolidWorksRecoverInput().dismiss_dialogs is False
    result = json.loads(server.solidworks_recover())
    assert result["status"] == "blocked" and result["may_continue"] is False
    assert result["probe"]["com_status"] == "responsive"
    assert result["probe"]["blocking_dialogs"][0]["texts"][0]["text"].startswith("Save changes")
    assert result["probe"]["dismissed_dialogs"] == []
    recovery.lock.release.assert_called_once_with()
    assert recovery.runners[0]["load_automation"] is False
    assert_readonly(recovery.windows)


def test_readonly_recovery_uses_bound_pid_over_environment(recovery, monkeypatch):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "999")
    result = json.loads(server.solidworks_recover())
    assert [d["handle"] for d in result["probe"]["blocking_dialogs"]] == [2]
    assert_readonly(recovery.windows)


def test_readonly_recovery_uses_explicit_environment_pid_if_unbound(recovery, monkeypatch):
    monkeypatch.setattr(server, "_selected_process_id", None)
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "999")
    result = json.loads(server.solidworks_recover())
    assert [d["handle"] for d in result["probe"]["blocking_dialogs"]] == [3]
    assert result["status"] == "blocked" and not result["may_continue"]
    assert_readonly(recovery.windows)


@pytest.mark.parametrize("com_result", ["locked", "error"])
def test_modal_is_blocking_when_com_probe_is_locked_or_errors(recovery, com_result):
    if com_result == "locked":
        recovery.lock.acquire.return_value = False
    else:
        recovery.connect.side_effect = RuntimeError("COM unavailable")
    result = json.loads(server.solidworks_recover())
    assert result["status"] == "blocked" and not result["may_continue"]
    assert result["probe"]["com_status"] == com_result
    assert result["probe"]["dismissed_dialogs"] == []
    assert_readonly(recovery.windows)


def test_responsive_session_only_allows_continuation_without_selected_pid_dialog(recovery):
    recovery.windows.rows[2]["visible"] = False
    result = json.loads(server.solidworks_recover())
    assert result["status"] == "responsive" and result["may_continue"]
    assert result["probe"]["blocking_dialogs"] == []
    assert_readonly(recovery.windows)
