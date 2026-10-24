"""CAM 消息订阅：使用供应商默认响应，记录事件，不猜测响应码或操作窗口。"""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

from scripts.sw_cam_comtypes import _load_type_library, query_cam_interface

MAX_EVENTS = 100
MAX_MESSAGE_CHARS = 1000
MAX_ERROR_RECORDS = 20


def _get_events(notifier, sink, *, interface):
    """通过标准 COM connection point 注册明确的事件接口。"""
    from comtypes.client import GetEvents

    return GetEvents(notifier, sink, interface=interface)


class _CamMessageSink:
    """低层签名兼容 IDispatch::Invoke 的空或非空 pVarResult。"""

    def __init__(self, owner):
        self._owner = owner

    def _IDialogEvents_CWMsg(self, this, nMsgboxType, nID, strMsg, result=None):
        # 参数 this 使 comtypes 跳过自动返回值转换；HRESULT 不是 CAM 的用户响应。
        try:
            self._owner._record_event(nMsgboxType, nID, strMsg)
        except Exception as error:
            self._owner._record_callback_error("record", error)
        if result:
            try:
                result[0].value = 0
            except Exception as error:
                self._owner._record_callback_error("invoke_result", error)
        return 0  # S_OK；不调用 SetResponse，CAM 按其文档使用默认值。


class CamMessageSession:
    """在现有 CAM 应用上订阅消息，并在操作结束时解除订阅。

    参数:
        app: 已验证目标 SOLIDWORKS 会话返回的 CAM 应用对象。
        typelib_path: 已登记 CAM 安装目录中的类型库路径。
    返回:
        上下文管理器；summary() 提供独立的、容量受限的事件与清理结果。
    """

    def __init__(self, app, typelib_path):
        self._app = app
        self._typelib_path = str(typelib_path)
        self._notifier = None
        self._connection = None
        self._sink = _CamMessageSink(self)
        self._lock = RLock()
        self._used = False
        self._subscribed = False
        self._disconnected = False
        self._active = False
        self._event_count = 0
        self._events: list[dict[str, Any]] = []
        self._overflow = 0
        self._callback_errors: list[dict[str, str]] = []
        self._callback_error_count = 0
        self._subscription_error = None
        self._disconnect_errors: list[dict[str, str]] = []

    def __enter__(self):
        """订阅失败时抛出异常，阻止进入可能生成消息的操作。"""
        if self._used:
            raise RuntimeError("CAM message session cannot be reused")
        self._used = True
        try:
            library = _load_type_library(self._typelib_path)
            getter = getattr(self._app, "IGetEventNotifier")
            # pywin32 的对象属性可能可调用，但默认成员并不是 getter 方法。
            wrapped = {"_oleobj_", "_dispobj_"}.intersection(getattr(getter, "__dict__", {}))
            raw_notifier = getter if wrapped or not callable(getter) else getter()
            self._notifier = query_cam_interface(
                raw_notifier, "ICWEventGenerator", self._typelib_path
            )
            self._connection = _get_events(
                self._notifier, self._sink, interface=library._IDialogEvents
            )
            if self._connection is None:
                raise RuntimeError("CAM event subscription returned no connection")
            with self._lock:
                self._subscribed = True
                self._active = True
            return self
        except Exception as error:
            with self._lock:
                self._subscription_error = {"type": type(error).__name__}
            self._notifier = None
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        """无论操作成功或失败都尝试 Unadvise，清理失败保留在摘要中。"""
        if self._connection is not None:
            try:
                self._connection.disconnect()
            except Exception as error:
                # 解除订阅失败时保留连接和接收器引用，不能假称已清理。
                with self._lock:
                    self._disconnect_errors.append({"type": type(error).__name__})
            else:
                with self._lock:
                    self._disconnected = True
                    self._active = False
                self._connection = None
                self._notifier = None
                self._app = None
        return False

    def _record_event(self, message_type, message_id, message):
        with self._lock:
            self._event_count += 1
            if len(self._events) >= MAX_EVENTS:
                self._overflow += 1
                return
            rendered = str(message)
            self._events.append({
                "message_type": int(message_type),
                "message_id": int(message_id),
                "message": rendered[:MAX_MESSAGE_CHARS],
                "message_truncated": len(rendered) > MAX_MESSAGE_CHARS,
                "response": "default_unknown",
            })

    def _record_callback_error(self, stage, error):
        with self._lock:
            self._callback_error_count += 1
            if len(self._callback_errors) < MAX_ERROR_RECORDS:
                self._callback_errors.append({"stage": stage, "type": type(error).__name__})

    def summary(self) -> dict[str, Any]:
        """返回只含普通数据的副本；默认响应不是取消，也不表示加工已成功。"""
        with self._lock:
            return deepcopy({
                "policy": "vendor_default",
                "response": "default_unknown",
                "subscribed": self._subscribed,
                "disconnected": self._disconnected,
                "active": self._active,
                "event_count": self._event_count,
                "events": self._events,
                "overflow": self._overflow,
                "callback_errors": self._callback_errors,
                "callback_error_count": self._callback_error_count,
                "subscription_error": self._subscription_error,
                "disconnect_errors": self._disconnect_errors,
            })
