"""CAM 消息订阅与真实内存 IDispatch ABI 回归；不连接 CAD、不注册 COM。"""
from __future__ import annotations

import gc
import weakref
from ctypes import HRESULT, POINTER, byref, c_int, c_uint, pointer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_events as events


@pytest.fixture
def lifecycle(monkeypatch):
    """所有应用、类型库与订阅入口均使用模拟对象。"""
    raw = object()
    app = SimpleNamespace(IGetEventNotifier=Mock(return_value=raw))
    notifier = SimpleNamespace(SetResponse=Mock(side_effect=AssertionError("SetResponse is forbidden")))
    connection = SimpleNamespace(disconnect=Mock())
    interface = object()
    module = SimpleNamespace(_IDialogEvents=interface)
    query = Mock(return_value=notifier)
    loader = Mock(return_value=module)
    subscribe = Mock(return_value=connection)
    monkeypatch.setattr(events, "query_cam_interface", query)
    monkeypatch.setattr(events, "_load_type_library", loader)
    monkeypatch.setattr(events, "_get_events", subscribe)
    session = events.CamMessageSession(app, "verified-installation/camworks.tlb")
    return SimpleNamespace(
        app=app, raw=raw, notifier=notifier, connection=connection, interface=interface,
        query=query, loader=loader, subscribe=subscribe, session=session,
    )


def test_subscription_targets_existing_notifier_and_disconnects(lifecycle):
    f = lifecycle
    assert f.session.summary()["active"] is False
    with f.session as active:
        assert active is f.session
        f.app.IGetEventNotifier.assert_called_once_with()
        f.query.assert_called_once_with(f.raw, "ICWEventGenerator", "verified-installation/camworks.tlb")
        f.loader.assert_called_once_with("verified-installation/camworks.tlb")
        f.subscribe.assert_called_once_with(f.notifier, f.session._sink, interface=f.interface)
        report = f.session.summary()
        assert report["policy"] == "vendor_default"
        assert report["subscribed"] is True
        assert report["active"] is True
        assert report["disconnected"] is False
    report = f.session.summary()
    assert report["active"] is False
    assert report["disconnected"] is True
    assert report["event_count"] == 0
    assert report["events"] == []
    f.connection.disconnect.assert_called_once_with()
    f.notifier.SetResponse.assert_not_called()


def test_body_exception_still_disconnects_and_propagates(lifecycle):
    with pytest.raises(RuntimeError, match="operation failed"):
        with lifecycle.session:
            raise RuntimeError("operation failed")
    lifecycle.connection.disconnect.assert_called_once_with()
    assert lifecycle.session.summary()["active"] is False


def test_subscription_failure_raises_and_records_without_entering_body(lifecycle):
    lifecycle.subscribe.side_effect = RuntimeError("subscription failed")
    with pytest.raises(RuntimeError, match="subscription failed"):
        with lifecycle.session:
            pytest.fail("Body must not run after failed subscription")
    report = lifecycle.session.summary()
    assert report["active"] is False
    assert report["subscription_error"]
    lifecycle.connection.disconnect.assert_not_called()
    lifecycle.notifier.SetResponse.assert_not_called()


@pytest.mark.parametrize("stage", ["notifier", "interface", "library"])
def test_pre_subscription_failure_does_not_subscribe(lifecycle, stage):
    target = {
        "notifier": lifecycle.app.IGetEventNotifier,
        "interface": lifecycle.query,
        "library": lifecycle.loader,
    }[stage]
    target.side_effect = RuntimeError("preflight failed")
    with pytest.raises(RuntimeError, match="preflight failed"):
        with lifecycle.session:
            pytest.fail("Body must not run after failed initialization")
    assert lifecycle.session.summary()["subscription_error"]
    assert lifecycle.session.summary()["active"] is False
    lifecycle.subscribe.assert_not_called()
    lifecycle.notifier.SetResponse.assert_not_called()


def test_disconnect_failure_is_recorded_without_hiding_body_result(lifecycle):
    lifecycle.connection.disconnect.side_effect = RuntimeError("unadvise failed")
    with lifecycle.session:
        pass
    report = lifecycle.session.summary()
    assert report["active"] is True
    assert report["disconnected"] is False
    assert report["disconnect_errors"]
    lifecycle.notifier.SetResponse.assert_not_called()


def test_disconnect_failure_does_not_replace_body_exception(lifecycle):
    lifecycle.connection.disconnect.side_effect = RuntimeError("unadvise failed")
    with pytest.raises(ValueError, match="original body error"):
        with lifecycle.session:
            raise ValueError("original body error")
    assert lifecycle.session.summary()["disconnect_errors"]


def test_connection_and_sink_remain_alive_until_context_exit(lifecycle):
    references = []

    class Connection:
        def __init__(self, sink):
            self.sink = sink
            self.disconnect = Mock()

    def subscribe(_notifier, sink, interface):
        connection = Connection(sink)
        references.append(weakref.ref(connection))
        return connection

    lifecycle.subscribe.side_effect = subscribe
    with lifecycle.session:
        gc.collect()
        assert references[0]() is not None
        assert references[0]().sink is lifecycle.session._sink
        assert lifecycle.session.summary()["active"] is True


def test_event_records_default_policy_without_response_and_bounds_storage(lifecycle):
    with lifecycle.session:
        for index in range(110):
            hr = lifecycle.session._sink._IDialogEvents_CWMsg(None, 4, index, "x" * 1200)
            assert hr == 0
    report = lifecycle.session.summary()
    assert report["event_count"] == 110
    assert len(report["events"]) == 100
    assert report["overflow"] == 10
    first = report["events"][0]
    assert first["message_type"] == 4
    assert first["message_id"] == 0
    assert first["message"] == "x" * 1000
    assert first["message_truncated"] is True
    assert first["response"] == "default_unknown"
    assert report["callback_errors"] == []
    lifecycle.notifier.SetResponse.assert_not_called()


def test_short_event_message_is_not_marked_truncated(lifecycle):
    with lifecycle.session:
        assert lifecycle.session._sink._IDialogEvents_CWMsg(None, 1, 42, "message") == 0
    item = lifecycle.session.summary()["events"][0]
    assert item["message"] == "message"
    assert item["message_truncated"] is False
    lifecycle.notifier.SetResponse.assert_not_called()


def test_callback_conversion_errors_never_escape_and_are_bounded(lifecycle):
    class BadInteger:
        def __int__(self):
            raise ValueError("invalid message number")

    with lifecycle.session:
        for _ in range(500):
            assert lifecycle.session._sink._IDialogEvents_CWMsg(None, BadInteger(), 2, "message") == 0
    errors = lifecycle.session.summary()["callback_errors"]
    assert 0 < len(errors) < 500
    lifecycle.notifier.SetResponse.assert_not_called()


@pytest.mark.parametrize("with_result", [False, True])
def test_actual_comtypes_dispatch_accepts_null_and_nonnull_result(lifecycle, with_result):
    """真实标准 IDispatch::Invoke 仅调用内存 sink，覆盖供应商事件的 HRESULT ABI。"""
    from comtypes import BSTR, DISPMETHOD, GUID, dispid
    from comtypes.automation import DISPATCH_METHOD, DISPPARAMS, EXCEPINFO, IDispatch, VARIANT
    from comtypes.client._events import CreateEventReceiver

    class _IDialogEvents(IDispatch):
        _iid_ = GUID("{7532C711-3BC4-11D6-A9AF-00062999E55F}")
        _idlflags_ = []
        _methods_ = []
        _disp_methods_ = [
            DISPMETHOD([dispid(1)], HRESULT, "CWMsg",
                       (["in"], c_int, "nMsgboxType"),
                       (["in"], c_int, "nID"),
                       (["in"], BSTR, "strMsg")),
        ]

    with lifecycle.session:
        receiver = CreateEventReceiver(_IDialogEvents, lifecycle.session._sink)
        dispatch = receiver.QueryInterface(IDispatch)
        arguments = (VARIANT * 3)()
        # IDispatch 的位置参数采用倒序。
        arguments[0].value = "in-memory event"
        arguments[1].value = 42
        arguments[2].value = 4
        parameters = DISPPARAMS()
        parameters.rgvarg = arguments
        parameters.cArgs = 3
        parameters.cNamedArgs = 0
        result = VARIANT("unchanged")
        exception = EXCEPINFO()
        argument_error = c_uint()
        hr = dispatch._IDispatch__com_Invoke(
            1, byref(GUID()), 0, DISPATCH_METHOD, byref(parameters),
            pointer(result) if with_result else POINTER(VARIANT)(),
            byref(exception), byref(argument_error),
        )
        assert hr == 0
        assert result.value == (0 if with_result else "unchanged")
    report = lifecycle.session.summary()
    assert report["event_count"] == 1
    assert report["callback_errors"] == []
    assert report["events"][0] == {
        "message_type": 4, "message_id": 42, "message": "in-memory event",
        "response": "default_unknown", "message_truncated": False,
    }
    lifecycle.notifier.SetResponse.assert_not_called()
