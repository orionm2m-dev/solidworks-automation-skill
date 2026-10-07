"""进程绑定下的交付兜底隔离测试；不调用真实 CAD。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scripts import sw_delivery


@pytest.mark.parametrize("target", ["1234", "", "invalid"])
def test_comtypes_attach_is_blocked_before_any_client_call(monkeypatch, target):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", target)
    client = SimpleNamespace(GetActiveObject=Mock(), CreateObject=Mock())
    with pytest.raises(RuntimeError, match="SW_PROCESS_TARGET_FALLBACK_UNSUPPORTED"):
        sw_delivery._connect_comtypes_solidworks(client, ["SldWorks.Application"])
    client.GetActiveObject.assert_not_called()
    client.CreateObject.assert_not_called()


def test_comtypes_pack_is_blocked_before_typelib_or_instance_lookup(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "1234")
    module = Mock()
    major = Mock()
    connect = Mock()
    monkeypatch.setattr(sw_delivery, "_comtypes_module", module)
    monkeypatch.setattr(sw_delivery, "_active_solidworks_major", major)
    monkeypatch.setattr(sw_delivery, "_connect_comtypes_solidworks", connect)
    with pytest.raises(RuntimeError, match="SW_PROCESS_TARGET_FALLBACK_UNSUPPORTED"):
        sw_delivery._comtypes_pack_and_go(
            "unopened.SLDASM", tmp_path, {}, include_drawings=True,
            include_simulation_results=False, include_toolbox_components=False,
            include_suppressed=False, flatten=False,
        )
    module.assert_not_called()
    major.assert_not_called()
    connect.assert_not_called()


def test_bound_typelib_version_uses_selected_application(monkeypatch):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "1234")
    selected = SimpleNamespace(RevisionNumber="34.4.1")
    connect = Mock(return_value=(selected, None))
    default = Mock(side_effect=AssertionError("不得读取默认实例"))
    monkeypatch.setattr(sw_delivery, "connect_solidworks", connect)
    monkeypatch.setattr(sw_delivery, "win32com_client", SimpleNamespace(GetActiveObject=default))
    assert sw_delivery._active_solidworks_major() == 34
    connect.assert_called_once_with(wait_seconds=0)
    default.assert_not_called()


def test_missing_bound_instance_does_not_choose_another_typelib(monkeypatch):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "1234")
    connect = Mock(side_effect=RuntimeError("target missing"))
    default = Mock()
    monkeypatch.setattr(sw_delivery, "connect_solidworks", connect)
    monkeypatch.setattr(sw_delivery, "win32com_client", SimpleNamespace(GetActiveObject=default))
    with pytest.raises(RuntimeError, match="target missing"):
        sw_delivery._active_solidworks_major()
    default.assert_not_called()


def test_unbound_comtypes_attach_keeps_legacy_behavior(monkeypatch):
    monkeypatch.delenv("SOLIDWORKS_MCP_PROCESS_ID", raising=False)
    selected = object()
    client = SimpleNamespace(GetActiveObject=Mock(return_value=selected), CreateObject=Mock())
    assert sw_delivery._connect_comtypes_solidworks(client, ["SldWorks.Application"]) == (selected, False, None)
    client.CreateObject.assert_not_called()


def test_unbound_comtypes_creation_keeps_legacy_behavior(monkeypatch):
    monkeypatch.delenv("SOLIDWORKS_MCP_PROCESS_ID", raising=False)
    selected = object()
    error = RuntimeError("not active")
    client = SimpleNamespace(GetActiveObject=Mock(side_effect=error), CreateObject=Mock(return_value=selected))
    assert sw_delivery._connect_comtypes_solidworks(client, ["SldWorks.Application"]) == (selected, True, error)


def test_unbound_typelib_version_keeps_legacy_behavior(monkeypatch):
    monkeypatch.delenv("SOLIDWORKS_MCP_PROCESS_ID", raising=False)
    default = Mock(return_value=SimpleNamespace(RevisionNumber="32.5.0"))
    monkeypatch.setattr(sw_delivery, "win32com_client", SimpleNamespace(GetActiveObject=default))
    assert sw_delivery._active_solidworks_major() == 32
    default.assert_called_once_with("SldWorks.Application")
