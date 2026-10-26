"""独立 EXE 启动的离线回归；所有进程创建和 COM 均为替身。"""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import sw_executable_launch as launch
from scripts import sw_connect as connection


class App:
    def __init__(self):
        self.pid = 999
        self.writes = []
        self.RevisionNumber = "34.4.1"
        self.ActiveDoc = None
        self.control = False
        self.visible = False

    def GetProcessID(self):
        return self.pid

    @property
    def UserControl(self):
        return self.control

    @UserControl.setter
    def UserControl(self, value):
        self.writes.append(("UserControl", value))
        self.control = value

    @property
    def Visible(self):
        return self.visible

    @Visible.setter
    def Visible(self, value):
        self.writes.append(("Visible", value))
        self.visible = value


@pytest.fixture
def case(tmp_path, monkeypatch):
    exe = tmp_path / "Installed application" / "SLDWORKS.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"test only")
    receipt = tmp_path / "launch.json"
    app = App()
    monkeypatch.setattr(connection, "_LaunchGuard", lambda: nullcontext())
    monkeypatch.setattr(connection, "_snapshot_process_ids", Mock(return_value={123, 456}))
    monkeypatch.setattr(connection, "ensure_solidworks_installed", Mock())
    monkeypatch.setattr(launch, "discover_installations", Mock(return_value=[
        {"executable": str(exe), "version": 2026, "source": "test"}]))
    monkeypatch.setattr(launch.time, "time", lambda: 100.0)
    identity = {"process_id": 999, "create_time": 100.0, "executable": str(exe), "alive": True}
    query = Mock(side_effect=lambda pid: dict(identity))
    monkeypatch.setattr(launch, "_process_identity", query)
    process = SimpleNamespace(pid=999, terminate=Mock(side_effect=AssertionError("no termination")),
                              kill=Mock(side_effect=AssertionError("no kill")))

    def create(*args, **kwargs):
        intent = json.loads(receipt.read_text(encoding="utf-8"))
        assert intent["phase"] == "launch_intent" and intent["launch_attempted"] is True
        assert intent["process_id"] is None
        return process

    popen = Mock(side_effect=create)
    monkeypatch.setattr(launch.subprocess, "Popen", popen)
    resolver = Mock(return_value=(app, "SolidWorks_PID_999"))
    monkeypatch.setattr(connection, "_connect_process", resolver)
    monkeypatch.setattr(connection, "_wait_until_ready", Mock())
    for name in ("Dispatch", "DispatchEx", "GetActiveObject"):
        monkeypatch.setattr(connection.win32com_client, name,
                            Mock(side_effect=AssertionError("no COM activation/default attach")))
    return SimpleNamespace(exe=exe, receipt=receipt, app=app, identity=identity,
                           query=query, popen=popen, process=process, resolver=resolver)


def call(case):
    return connection.connect_solidworks(launch_new_instance=True, launch_mode="executable",
        startup_receipt_path=str(case.receipt), wait_seconds=1, return_metadata=True)


def test_executable_launch_intent_precedes_creation_and_new_identity_precedes_writes(case):
    sw, model, metadata = call(case)
    assert sw is case.app and model is None
    case.popen.assert_called_once_with([str(case.exe)], cwd=str(case.exe.parent), shell=False,
        stdin=launch.subprocess.DEVNULL, stdout=launch.subprocess.DEVNULL,
        stderr=launch.subprocess.DEVNULL, close_fds=True, creationflags=launch.subprocess.CREATE_NO_WINDOW)
    case.resolver.assert_called_once_with(999, None)
    assert case.app.writes == [("UserControl", True), ("Visible", True)]
    assert metadata["process_id"] == 999 and metadata["launch_mode"] == "executable"
    assert metadata["connection_source"] == "verified_pid_rot_executable"
    report = json.loads(case.receipt.read_text(encoding="utf-8"))
    assert report["status"] == "ok" and report["process_identity"] == case.identity
    assert report["new_process_verified"] and report["user_control_verified"] and report["visible_verified"]
    case.process.terminate.assert_not_called()
    case.process.kill.assert_not_called()


def test_existing_receipt_refuses_replay_before_any_launch(case):
    case.receipt.write_text("previous uncertain launch", encoding="utf-8")
    with pytest.raises(FileExistsError):
        call(case)
    case.popen.assert_not_called()
    assert case.receipt.read_text() == "previous uncertain launch"


@pytest.mark.parametrize("value", [123, 0, True])
def test_pid_not_new_refuses_all_com_and_writes(case, value):
    case.process.pid = value
    with pytest.raises(connection.SolidWorksConnectionError):
        call(case)
    case.resolver.assert_not_called()
    assert case.app.writes == []


@pytest.mark.parametrize("changes", [dict(alive=False), dict(create_time=5.0),
    dict(create_time=102.0), dict(executable="C:/foreign/SLDWORKS.exe")])
def test_bad_process_identity_stops_before_rot(case, changes):
    case.identity.update(changes)
    with pytest.raises(connection.SolidWorksConnectionError):
        call(case)
    case.resolver.assert_not_called()
    assert case.app.writes == []
    assert json.loads(case.receipt.read_text())["status"] == "uncertain"


def test_creation_time_change_is_not_pid_identity(case):
    case.query.side_effect = [dict(case.identity), dict(case.identity, create_time=100.1)]
    with pytest.raises(connection.SolidWorksConnectionError):
        call(case)
    case.resolver.assert_not_called()
    assert case.app.writes == []


def test_identity_query_error_never_falls_back(case):
    case.query.side_effect = PermissionError("metadata unknown")
    with pytest.raises(connection.SolidWorksConnectionError):
        call(case)
    assert case.app.writes == []
    case.popen.assert_called_once()
    case.resolver.assert_not_called()


def test_foreign_com_proxy_never_gets_property_writes(case):
    case.app.pid = 456
    with pytest.raises(connection.SolidWorksConnectionError):
        call(case)
    assert case.app.writes == []


def test_rot_timeout_keeps_receipt_and_never_relaunches_or_terminates(case, monkeypatch):
    case.resolver.side_effect = connection.SolidWorksConnectionError("SW_PROCESS_NOT_FOUND", "attach", "not ready")
    monkeypatch.setattr(launch.time, "monotonic", Mock(side_effect=[0, 2]))
    with pytest.raises(connection.SolidWorksConnectionError):
        call(case)
    case.popen.assert_called_once()
    case.process.terminate.assert_not_called()
    case.process.kill.assert_not_called()
    assert case.app.writes == []
    assert json.loads(case.receipt.read_text())["process_id"] == 999


def test_matching_pid_on_application_alias_is_valid_without_default_activation(case):
    case.resolver.return_value = case.app, "SldWorks.Application"
    result = call(case)
    assert result[2]["startup"]["moniker"] == "SldWorks.Application"
    assert result[2]["process_id"] == 999


def test_intent_write_failure_prevents_process_creation(case, monkeypatch):
    monkeypatch.setattr(launch, "_write_receipt", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        call(case)
    case.popen.assert_not_called()


def test_receipt_failure_after_create_stops_before_com(case, monkeypatch):
    original = launch._write_receipt
    def fail(path, report, *, initial=False):
        if not initial:
            raise OSError("cannot record created PID")
        return original(path, report, initial=True)
    monkeypatch.setattr(launch, "_write_receipt", fail)
    with pytest.raises(connection.SolidWorksConnectionError, match="receipt update failed"):
        call(case)
    case.popen.assert_called_once()
    case.resolver.assert_not_called()
    assert case.app.writes == []


def test_user_control_false_readback_prevents_visible_write(case, monkeypatch):
    original = connection.get_com_member
    monkeypatch.setattr(connection, "get_com_member", lambda obj, name, *args:
        False if name == "UserControl" else original(obj, name, *args))
    with pytest.raises(connection.SolidWorksConnectionError):
        call(case)
    assert case.app.writes == [("UserControl", True)]


@pytest.mark.parametrize("options", [dict(launch_mode="exe"),
    dict(launch_mode="executable"), dict(startup_receipt_path="test.json"),
    dict(launch_new_instance=True, launch_mode="executable", startup_receipt_path="relative.json")])
def test_invalid_backend_options_do_not_launch(case, options):
    with pytest.raises((ValueError, FileNotFoundError)):
        connection.connect_solidworks(**options)
    case.popen.assert_not_called()


def test_requested_installation_version_is_not_silently_changed(case):
    with pytest.raises(ValueError, match="No matching"):
        connection.connect_solidworks(version=2025, launch_new_instance=True, launch_mode="executable",
            startup_receipt_path=str(case.receipt))
    case.popen.assert_not_called()


def test_process_identity_closes_native_handle_when_image_query_fails(monkeypatch):
    handle = Mock()
    api = SimpleNamespace(OpenProcess=Mock(return_value=handle))
    process = SimpleNamespace(GetProcessTimes=Mock(return_value={"CreationTime": SimpleNamespace(timestamp=lambda: 100)}),
                              GetExitCodeProcess=Mock(return_value=259))
    monkeypatch.setitem(sys.modules, "win32api", api)
    monkeypatch.setitem(sys.modules, "win32process", process)
    monkeypatch.setattr(launch, "_image_path", Mock(side_effect=OSError("unknown image")))
    with pytest.raises(OSError):
        launch._process_identity(999)
    api.OpenProcess.assert_called_once_with(0x1000, False, 999)
    handle.Close.assert_called_once()
