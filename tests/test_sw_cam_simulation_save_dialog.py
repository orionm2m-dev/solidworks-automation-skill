"""Save STL UI helper 的窗口目标、持久回执和单次通知测试；不操作桌面。"""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_simulation_save_dialog as helper


@pytest.fixture
def probe(tmp_path):
    part = tmp_path / "CALIBRATION.SLDPRT"
    part.write_bytes(b"fixture")
    receipt = tmp_path / "receipt.json"
    windows = {
        1: dict(title="CALIBRATION.SLDPRT - SOLIDWORKS", cls="SldWorks", pid=100, parent=0, ident=0, top=True),
        2: dict(title="Симуляция траектории", cls="#32770", pid=100, parent=1, ident=0, top=False),
        3: dict(title="СохрSTLфайл", cls="Button", pid=100, parent=2, ident=6182, top=False),
    }
    for window in windows.values():
        window.update(visible=True, enabled=True)
    state = dict(on_post=None, on_enumerate=None, enumerations=0, create_dialog=True)
    def enum_windows(visit, value):
        state["enumerations"] += 1
        if state["on_enumerate"]:
            state["on_enumerate"](state["enumerations"])
        for handle, window in list(windows.items()):
            if window["top"]:
                visit(handle, value)
    def enum_children(parent, visit, value):
        for handle, window in list(windows.items()):
            if window["top"]:
                continue
            ancestor = window["parent"]
            while ancestor:
                if ancestor == parent:
                    visit(handle, value)
                    break
                ancestor = windows[ancestor]["parent"]
    def post(*args):
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        assert saved["button_invocation_attempted"] and saved["phase"] == "before_button_notification"
        if state["on_post"]:
            state["on_post"]()
        if state["create_dialog"]:
            windows[4] = dict(title="Сохранение", cls="#32770", pid=100, parent=1, ident=0, top=True,
                              visible=True, enabled=True)
            windows[5] = dict(title="", cls="Edit", pid=100, parent=4, ident=1148, top=False,
                              visible=True, enabled=True)
    gui = SimpleNamespace(EnumWindows=enum_windows, EnumChildWindows=enum_children,
        GetWindowText=lambda h: windows[h]["title"], GetClassName=lambda h: windows[h]["cls"],
        GetDlgCtrlID=lambda h: windows[h]["ident"], GetParent=lambda h: windows[h]["parent"],
        IsWindowVisible=lambda h: windows[h]["visible"], IsWindowEnabled=lambda h: windows[h]["enabled"],
        GetDlgItem=lambda h, ident: next((key for key, value in windows.items()
                                         if value["parent"] == h and value["ident"] == ident), 0),
        PostMessage=Mock(side_effect=post))
    processes = SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, windows[h]["pid"]))
    document = dict(path=str(part), title=part.name, type=1, needs_save=False)
    def run(**changes):
        return helper.handle_simulation_save_dialog(**dict(process_id=100, expected_document_path=str(part),
            verified_document_snapshot=document, action="open_save", acknowledge_open_save=True,
            receipt_path=str(receipt), gui=gui, processes=processes, sleep=Mock()) | changes)
    return SimpleNamespace(run=run, gui=gui, windows=windows, state=state, receipt=receipt, document=document)


def test_inspect_is_readonly_and_persists_metadata(probe):
    report = probe.run(action="inspect", acknowledge_open_save=False)
    assert report["status"] == "inspected" and report["can_open_save"]
    assert report["save_button"]["id"] == 6182 and not report["native_cam_api_used"]
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == report
    probe.gui.PostMessage.assert_not_called()


def test_open_once_collects_actual_new_controls_without_filename_or_save(probe):
    report = probe.run()
    probe.gui.PostMessage.assert_called_once_with(2, 0x111, 6182, 3)
    assert report["status"] == "dialog_observed" and report["button_invocation_count"] == 1
    assert report["dialogs_after"][0]["controls"][0]["id"] == 1148
    assert not report["file_name_entered"] and not report["save_confirmed"] and not report["may_continue"]
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == report


@pytest.mark.parametrize("handle,key,value", [(1,"title","OTHER.SLDPRT - SOLIDWORKS"), (1,"pid",200),
    (2,"title","Other"), (2,"cls","Other"), (3,"pid",200), (3,"cls","Static"),
    (3,"title","Save"), (3,"ident",6183), (3,"enabled",False), (3,"visible",False), (3,"parent",1)])
def test_mismatch_blocks_button(probe, handle, key, value):
    probe.windows[handle][key] = value
    assert probe.run()["status"] == "blocked"
    probe.gui.PostMessage.assert_not_called()


def test_target_rechecked_before_notification(probe):
    def change(count):
        if count == 2:
            probe.windows[3]["enabled"] = False
    probe.state["on_enumerate"] = change
    assert probe.run()["status"] == "blocked"
    probe.gui.PostMessage.assert_not_called()


def test_missing_new_dialog_never_retries_notification(probe):
    probe.state["create_dialog"] = False
    assert probe.run()["status"] == "uncertain"
    probe.gui.PostMessage.assert_called_once()


@pytest.mark.parametrize("changes", [{"process_id":True}, {"acknowledge_open_save":False},
    {"acknowledge_open_save":1}, {"expected_document_path":"relative.SLDPRT"},
    {"verified_document_snapshot":{"type":1,"needs_save":True}}, {"action":"save"}])
def test_invalid_arguments_never_touch_ui(probe, changes):
    with pytest.raises(ValueError):
        probe.run(**changes)
    probe.gui.PostMessage.assert_not_called()
    assert probe.state["enumerations"] == 0


def test_receipt_must_be_new(probe):
    probe.receipt.write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError):
        probe.run()
    assert probe.receipt.read_text() == "old"
    probe.gui.PostMessage.assert_not_called()


def test_receipt_failure_before_notification_prevents_click(probe, monkeypatch):
    original = helper._write_receipt
    def write(path, report, **kwargs):
        if report["button_invocation_attempted"]:
            raise OSError("receipt unavailable")
        return original(path, report, **kwargs)
    monkeypatch.setattr(helper,"_write_receipt",write)
    assert probe.run()["status"] == "uncertain"
    probe.gui.PostMessage.assert_not_called()


def test_existing_top_level_modal_blocks_action_and_returns_metadata(probe):
    probe.windows[4] = dict(title="Existing", cls="#32770", pid=100, parent=1, ident=0, top=True,
                           visible=True, enabled=True)
    report = probe.run()
    assert report["reason"] == "EXISTING_TOP_LEVEL_DIALOG_REQUIRES_REVIEW"
    probe.gui.PostMessage.assert_not_called()
