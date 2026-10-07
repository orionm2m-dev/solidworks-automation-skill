"""桌面会话的跨进程互斥锁与活动文档校验。"""
from __future__ import annotations

import ctypes
import ntpath
import os
from contextlib import contextmanager
from pathlib import Path

OPERATION_MUTEX_NAME = r"Local\SolidWorksAutomation.Operation.v1"


def solidworks_operation_mutex_name(process_id=None):
    """返回指定 SolidWorks 进程的互斥锁名称；未绑定时使用兼容全局锁。"""
    if process_id is None:
        value = os.environ.get("SOLIDWORKS_MCP_PROCESS_ID")
        if value is None:
            return OPERATION_MUTEX_NAME
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            raise ValueError("SOLIDWORKS_MCP_PROCESS_ID must be a positive decimal PID")
        process_id = int(value)
    if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
        raise ValueError("process_id must be a positive integer")
    return rf"Local\SolidWorksAutomation.Operation.v1.PID.{process_id}"


class SolidWorksDocumentMismatch(RuntimeError):
    """请求目标与当前文档不符，必须在修改前停止。"""

    def __init__(self, message, *, expected_path=None, expected_title=None, actual_path="", actual_title=""):
        super().__init__(message)
        self.details = {
            "error_code": "SW_DOCUMENT_MISMATCH",
            "stage": "before_operation",
            "expected_document_path": expected_path,
            "expected_document_title": expected_title,
            "actual_document_path": actual_path,
            "actual_document_title": actual_title,
        }


def absolute_document_path(value):
    """只接受完整绝对路径，拒绝仅有盘符或根目录的 Windows 相对路径。"""
    value = os.path.expandvars(os.path.expanduser(str(value)))
    drive, tail = ntpath.splitdrive(value)
    if drive:
        return tail.startswith(("\\", "/"))
    return os.name != "nt" and Path(value).is_absolute()


def _path_identity(value):
    """Windows 下解析盘符映射及符号链接，并忽略路径大小写。"""
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    if os.name == "nt":
        return os.path.normcase(os.path.realpath(expanded))
    if ntpath.splitdrive(expanded)[0]:
        return ntpath.normcase(ntpath.normpath(expanded))
    return os.path.realpath(expanded)


def check_document_target(actual_path, actual_title, *, expected_path=None, expected_title=None, required=False):
    """校验已保存文档的路径，或尚未保存文档的精确标题；不会自动激活窗口。"""
    actual_path, actual_title = str(actual_path or ""), str(actual_title or "")
    reason = None
    if expected_path is not None:
        if not absolute_document_path(expected_path):
            raise ValueError("expected_document_path must be an absolute path")
        if not actual_path or _path_identity(expected_path) != _path_identity(actual_path):
            reason = "Active document path differs from the requested target. No operation was performed."
    if expected_title is not None:
        if actual_path or actual_title != expected_title:
            reason = "Title guards apply only to the exact unsaved document. Use its full path after saving."
    if required and expected_path is None and expected_title is None:
        reason = "A document guard is required. Supply expected_document_path, or expected_document_title for an unsaved document."
    if reason:
        raise SolidWorksDocumentMismatch(reason, expected_path=expected_path, expected_title=expected_title,
                                         actual_path=actual_path, actual_title=actual_title)


@contextmanager
def solidworks_operation_lock(timeout_seconds=300.0, *, name=None, process_id=None):
    """串行化目标 SolidWorks PID 的协作客户端；非 Windows 下不触及 COM。

    未显式传入名称时按 process_id 或 SOLIDWORKS_MCP_PROCESS_ID 生成锁名；未绑定时
    使用兼容全局锁。CLI 和其他进程必须使用相同 PID/名称才能参与互斥。锁不阻止人工
    操作或旧版客户端。超时只约束等待锁的时间，不能取消已经执行的 COM 调用。
    """
    if name is None:
        name = solidworks_operation_mutex_name(process_id)
    if os.name != "nt":
        yield
        return
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        result = kernel.WaitForSingleObject(handle, max(0, min(int(timeout_seconds * 1000), 0xFFFFFFFE)))
        acquired = result in (0, 0x80)
        if result == 0x102:
            raise TimeoutError("Another client owns the SOLIDWORKS operation lock. Retry after it finishes.")
        if result == 0x80:
            raise RuntimeError("The previous SOLIDWORKS lock owner exited unexpectedly. Inspect the desktop before retrying.")
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)
