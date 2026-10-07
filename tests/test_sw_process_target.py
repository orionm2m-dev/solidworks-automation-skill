"""显式进程连接的回归测试；全部使用假 ROT，不调用真实 COM。"""
from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pywintypes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import sw_connect as connection


class FakeMoniker:
    def __init__(self, name):
        self.name = name

    def GetDisplayName(self, _context, _left):
        if isinstance(self.name, Exception):
            raise self.name
        return self.name


class FakeEnumerator:
    def __init__(self, monikers):
        self.monikers = iter(monikers)

    def Next(self, _count):
        value = next(self.monikers, None)
        return (value,) if value is not None else ()


class FakeUnknown:
    """模拟没有 GetTypeInfo 的 PyIUnknown，只通过 QueryInterface 暴露代理。"""
    def __init__(self, dispatch):
        self.dispatch = dispatch
        self.queried = []

    def QueryInterface(self, iid):
        assert iid == "IID_IDispatch"
        self.queried.append(iid)
        return self.dispatch


class FakeRot:
    def __init__(self, entries):
        self.entries = [(FakeMoniker(name), app) for name, app in entries]
        self.bound = []
        self.unknowns = []

    def EnumRunning(self):
        return FakeEnumerator(moniker for moniker, _app in self.entries)

    def GetObject(self, moniker):
        self.bound.append(moniker.name)
        app = next(app for candidate, app in self.entries if candidate is moniker)
        if isinstance(app, Exception):
            raise app
        unknown = FakeUnknown(app)
        self.unknowns.append(unknown)
        return unknown


def app(pid, revision="34.4.1", model=None):
    return SimpleNamespace(GetProcessID=lambda: pid, RevisionNumber=revision, ActiveDoc=model)


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.delenv("SOLIDWORKS_MCP_PROCESS_ID", raising=False)
    monkeypatch.setattr(connection.pywintypes, "IID", Mock(side_effect=pywintypes.com_error(
        -2147221005, "Invalid class string", None, None)))
    ensure = Mock()
    monkeypatch.setattr(connection, "ensure_solidworks_installed", ensure)
    legacy = Mock(side_effect=AssertionError("不得附着默认实例"))
    dispatch = Mock(side_effect=lambda obj: obj if not isinstance(obj, str) else pytest.fail("不得激活类工厂"))
    monkeypatch.setattr(connection, "win32com_client", SimpleNamespace(GetActiveObject=legacy, Dispatch=dispatch))
    monkeypatch.setattr(connection, "_LaunchGuard", lambda: nullcontext())

    def install(entries):
        rot = FakeRot(entries)
        monkeypatch.setattr(connection, "pythoncom", SimpleNamespace(
            GetRunningObjectTable=lambda: rot, CreateBindCtx=lambda _reserved: object(),
            IID_IDispatch="IID_IDispatch",
        ))
        return rot

    return SimpleNamespace(install=install, ensure=ensure, legacy=legacy, dispatch=dispatch)


@pytest.mark.parametrize("pid", [0, -1, True, False, "123", 1.5, object()])
def test_invalid_pid_fails_before_installation_or_com(harness, pid):
    with pytest.raises(ValueError, match="positive integer"):
        connection.connect_solidworks(process_id=pid)
    harness.ensure.assert_not_called()
    harness.legacy.assert_not_called()
    harness.dispatch.assert_not_called()


@pytest.mark.parametrize("value", ["", "0", "-1", "123.0", " 123", "123 ", "+123", "abc"])
def test_invalid_environment_pid_does_not_fall_back(harness, monkeypatch, value):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", value)
    with pytest.raises(ValueError, match="positive decimal"):
        connection.connect_solidworks()
    harness.ensure.assert_not_called()
    harness.legacy.assert_not_called()
    harness.dispatch.assert_not_called()


@pytest.mark.parametrize("name", ["SolidWorks_PID_123", "!SolidWorks_PID_123", "SldWorks_PID_123"])
def test_matches_exact_pid_without_touching_other_documents(harness, name):
    wanted, other = app(123), app(456)
    rot = harness.install([
        ("!SolidWorks_PID_456", other),
        ("C:/work/part.SLDPRT", object()),
        (name, wanted),
    ])
    sw, model, metadata = connection.connect_solidworks(process_id=123, return_metadata=True)
    assert sw is wanted and model is None
    assert rot.bound == [name]
    assert metadata["process_id"] == metadata["requested_process_id"] == 123
    assert metadata["started_by_cad_studio"] is False
    assert not hasattr(wanted, "Visible")
    harness.legacy.assert_not_called()


def test_missing_pid_never_opens_any_other_instance(harness):
    rot = harness.install([("SolidWorks_PID_456", app(456)), ("not-solidworks", object())])
    with pytest.raises(connection.SolidWorksConnectionError) as error:
        connection.connect_solidworks(process_id=123)
    assert error.value.code == "SW_PROCESS_NOT_FOUND"
    assert rot.bound == []
    harness.legacy.assert_not_called()
    harness.dispatch.assert_not_called()


def test_rot_pid_disagreement_is_rejected(harness):
    harness.install([("SolidWorks_PID_123", app(456))])
    with pytest.raises(connection.SolidWorksConnectionError) as error:
        connection.connect_solidworks(process_id=123)
    assert error.value.code == "SW_PROCESS_MISMATCH"
    harness.legacy.assert_not_called()


def test_unreadable_target_does_not_create_replacement(harness):
    harness.install([("SolidWorks_PID_123", RuntimeError("disconnected"))])
    with pytest.raises(connection.SolidWorksConnectionError) as error:
        connection.connect_solidworks(process_id=123)
    assert error.value.code == "SW_PROCESS_NOT_FOUND"
    harness.legacy.assert_not_called()
    harness.dispatch.assert_not_called()


def test_application_alias_requires_matching_process_readback(harness):
    wanted = app(123)
    rot = harness.install([("SldWorks.Application", app(456)), ("SldWorks.Application.34", wanted)])
    sw, _model = connection.connect_solidworks(process_id=123, version=2026)
    assert sw is wanted
    assert rot.bound == ["SldWorks.Application", "SldWorks.Application.34"]
    harness.legacy.assert_not_called()


def test_dead_exact_moniker_can_use_verified_application_alias(harness):
    wanted = app(123)
    harness.install([("SolidWorks_PID_123", RuntimeError("stale")), ("SldWorks.Application", wanted)])
    assert connection.connect_solidworks(process_id=123)[0] is wanted
    harness.legacy.assert_not_called()


def test_version_mismatch_does_not_fall_back(harness):
    harness.install([("SolidWorks_PID_123", app(123, "32.5.0"))])
    with pytest.raises(connection.SolidWorksConnectionError) as error:
        connection.connect_solidworks(process_id=123, version=2026)
    assert error.value.code == "SW_VERSION_MISMATCH"
    harness.legacy.assert_not_called()


def test_environment_binding_is_inherited_by_nested_connect_calls(harness, monkeypatch):
    wanted = app(123)
    harness.install([("SolidWorks_PID_123", wanted), ("SolidWorks_PID_456", app(456))])
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "123")
    assert connection.connect_solidworks()[0] is wanted
    assert connection.connect_solidworks(return_metadata=True)[2]["requested_process_id"] == 123
    harness.legacy.assert_not_called()


def test_explicit_pid_overrides_environment_for_direct_api(harness, monkeypatch):
    wanted = app(123)
    harness.install([("SolidWorks_PID_123", wanted)])
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "456")
    assert connection.connect_solidworks(process_id=123)[0] is wanted


def test_legacy_default_still_attaches_without_rot(harness):
    wanted = app(123)
    harness.legacy.side_effect = None
    harness.legacy.return_value = wanted
    sw, _model, metadata = connection.connect_solidworks(version=2026, return_metadata=True)
    assert sw is wanted
    harness.legacy.assert_called_once_with("SldWorks.Application.34")
    harness.dispatch.assert_not_called()
    assert metadata["started_by_cad_studio"] is False
    assert metadata["process_id"] == 123
    assert metadata["requested_process_id"] is None


def test_legacy_default_still_launches_if_no_active_instance(harness):
    wanted = app(123)
    harness.legacy.side_effect = RuntimeError("no active object")
    harness.dispatch.side_effect = None
    harness.dispatch.return_value = wanted
    sw, _model, metadata = connection.connect_solidworks(visible=False, return_metadata=True)
    assert sw is wanted and wanted.Visible is False
    assert metadata["started_by_cad_studio"] is True
    harness.dispatch.assert_called_once_with("SldWorks.Application")


def test_instances_list_is_read_only_deduplicated_and_filters_documents(harness):
    model = SimpleNamespace(GetPathName="C:/work/part.SLDPRT", GetTitle="part", GetType=1)
    wanted = app(123, model=model)
    other = app(456)
    rot = harness.install([
        ("SolidWorks_PID_456", other), ("SolidWorks_PID_123", wanted),
        ("SldWorks.Application", wanted), ("C:/work/part.SLDPRT", object()),
        ("SolidWorks_PID_789", app(987)), ("SolidWorks_PID_234", RuntimeError("closed")),
    ])
    result = connection.list_solidworks_instances()
    assert [item["process_id"] for item in result] == [123, 456]
    assert result[0]["active_document"]["path"] == "C:/work/part.SLDPRT"
    assert result[1]["active_document"] is None
    assert "C:/work/part.SLDPRT" not in rot.bound
    assert not hasattr(wanted, "Visible") and not hasattr(other, "Visible")
    harness.legacy.assert_not_called()


def test_rot_failure_has_distinct_error_and_never_launches(harness, monkeypatch):
    monkeypatch.setattr(connection, "pythoncom", SimpleNamespace(
        GetRunningObjectTable=Mock(side_effect=RuntimeError("unavailable")),
    ))
    with pytest.raises(connection.SolidWorksConnectionError) as error:
        connection.connect_solidworks(process_id=123)
    assert error.value.code == "SW_ROT_UNAVAILABLE"
    harness.legacy.assert_not_called()
    harness.dispatch.assert_not_called()


def test_registered_class_moniker_is_verified_by_process_id(harness, monkeypatch):
    wanted = app(123)
    fake_clsid = "{11111111-2222-3333-4444-555555555555}"
    rot = harness.install([("!" + fake_clsid, wanted), ("!{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}", object())])
    monkeypatch.setattr(connection.pywintypes, "IID", lambda _name: fake_clsid, raising=False)
    assert connection.connect_solidworks(process_id=123)[0] is wanted
    assert rot.bound == ["!" + fake_clsid]
    harness.legacy.assert_not_called()


def test_registered_class_wrong_pid_never_falls_back(harness, monkeypatch):
    fake_clsid = "{11111111-2222-3333-4444-555555555555}"
    harness.install([("!" + fake_clsid, app(456))])
    monkeypatch.setattr(connection.pywintypes, "IID", lambda _name: fake_clsid, raising=False)
    with pytest.raises(connection.SolidWorksConnectionError) as error:
        connection.connect_solidworks(process_id=123)
    assert error.value.code == "SW_PROCESS_NOT_FOUND"
    harness.legacy.assert_not_called()


def test_target_version_registered_class_is_included(harness, monkeypatch):
    wanted = app(123)
    generic_clsid = "{11111111-2222-3333-4444-555555555555}"
    version_clsid = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
    harness.install([("!" + version_clsid, wanted)])
    monkeypatch.setattr(connection.pywintypes, "IID", lambda name:
                        version_clsid if name == "SldWorks.Application.34" else generic_clsid, raising=False)
    assert connection.connect_solidworks(process_id=123, version=2026)[0] is wanted


def test_rot_iunknown_is_queried_before_dispatch_wrapping(harness):
    wanted = app(123)
    rot = harness.install([("SolidWorks_PID_123", wanted)])
    assert connection.connect_solidworks(process_id=123)[0] is wanted
    assert len(rot.unknowns) == 1
    assert not hasattr(rot.unknowns[0], "GetTypeInfo")
    assert rot.unknowns[0].queried == ["IID_IDispatch"]
    harness.dispatch.assert_called_once_with(wanted)


def test_rot_query_interface_failure_never_uses_default_instance(harness, monkeypatch):
    rot = harness.install([("SolidWorks_PID_123", app(123))])
    monkeypatch.setattr(rot, "GetObject", lambda _moniker: SimpleNamespace(
        QueryInterface=Mock(side_effect=RuntimeError("E_NOINTERFACE"))))
    with pytest.raises(connection.SolidWorksConnectionError) as error:
        connection.connect_solidworks(process_id=123)
    assert error.value.code == "SW_PROCESS_NOT_FOUND"
    harness.dispatch.assert_not_called()
    harness.legacy.assert_not_called()


def test_real_pywintypes_exposes_iid_constructor_without_com_activation():
    """直接检查真实 pywin32 接口；解析字面 GUID 不连接任何应用。"""
    value = "{11111111-2222-3333-4444-555555555555}"
    assert str(pywintypes.IID(value)).casefold() == value.casefold()


def test_class_resolution_programming_error_is_not_silently_ignored(harness, monkeypatch):
    monkeypatch.setattr(connection.pywintypes, "IID", Mock(side_effect=AttributeError("unavailable API")))
    harness.install([])
    with pytest.raises(connection.SolidWorksConnectionError) as error:
        connection.connect_solidworks(process_id=123)
    assert error.value.code == "SW_ROT_UNAVAILABLE"
    assert "unavailable API" in str(error.value)
    harness.legacy.assert_not_called()
