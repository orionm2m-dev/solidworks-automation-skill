"""Graceful exit of an empty SOLIDWORKS process bound to this MCP server.

One ExitApp only when the bound process has no open documents; the exit is confirmed by waiting on an OS
process handle opened before the call. No retry, no forced termination.
"""
from __future__ import annotations

import ctypes
import time

SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WAIT_OBJECT_0 = 0


def _open_handle(pid):
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        raise OSError(f'OpenProcess failed for PID {pid}: {ctypes.get_last_error()}')
    return k32, handle


def open_documents(sw):
    from scripts.sw_connect import get_com_member as get
    rows = []
    for doc in list(get(sw, 'GetDocuments') or []):
        rows.append({'title': str(get(doc, 'GetTitle') or ''), 'path': str(get(doc, 'GetPathName') or '')})
    return rows


def exit_empty_session(sw, process_id, wait_seconds=60):
    from scripts.sw_connect import get_com_member as get
    actual = int(get(sw, 'GetProcessID'))
    if actual != int(process_id):
        raise RuntimeError(f'connected PID {actual} differs from requested {process_id}')
    docs = open_documents(sw)
    if docs or get(sw, 'ActiveDoc') is not None:
        return {'status': 'refused', 'process_id': actual, 'reason': 'open documents', 'open_documents': docs,
                'exit_attempted': False}
    k32, handle = _open_handle(actual)
    try:
        started = time.time()
        returned = None
        try:
            returned = sw.ExitApp()
        except Exception as exc:  # noqa: BLE001 - the process may drop the COM link while exiting
            returned = f'exception: {exc}'
        rc = k32.WaitForSingleObject(ctypes.c_void_p(handle), int(wait_seconds * 1000))
        exited = rc == WAIT_OBJECT_0
        return {'status': 'exited' if exited else 'exit_not_observed', 'process_id': actual, 'exit_attempted': True,
                'exit_call_count': 1, 'exit_returned': str(returned), 'process_exit_verified': exited,
                'seconds': round(time.time() - started, 1),
                'note': None if exited else 'ExitApp was called once; not retried, not terminated.'}
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))
