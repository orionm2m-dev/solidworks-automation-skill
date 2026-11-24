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


def _current_identity(pid):
    from scripts.sw_executable_launch import _process_identity
    return _process_identity(int(pid))


def _same_executable(left, right):
    import os
    from pathlib import Path
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def verify_launch_receipt(receipt_path, process_id, identity=_current_identity):
    """Check that process_id is still the process started by the executable launch in this receipt.

    The receipt is the JSON written by solidworks_connect(launch_mode="executable"). The live process must match its
    PID, creation time (a reused PID has another one) and executable image.
    """
    import json
    from pathlib import Path
    path = Path(receipt_path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f'launch receipt not found: {receipt_path}')
    data = json.loads(path.read_text(encoding='utf-8'))
    recorded = data.get('process_identity') or {}
    problems = []
    if data.get('status') != 'ok' or data.get('launch_mode') != 'executable' or data.get('new_process_verified') is not True:
        problems.append('receipt is not a verified executable launch')
    pid = int(process_id)
    if type(data.get('process_id')) is not int or data.get('process_id') != pid or recorded.get('process_id') != pid:
        problems.append(f'receipt PID {data.get("process_id")} differs from {pid}')
    if problems:
        raise RuntimeError('; '.join(problems))
    current = identity(pid)
    if current.get('alive') is not True:
        raise RuntimeError(f'process {pid} is not alive')
    if abs(float(current['create_time']) - float(recorded['create_time'])) > 0.01:
        raise RuntimeError(f'process {pid} creation time differs from the receipt (PID reused)')
    if not _same_executable(current['executable'], recorded['executable']):
        raise RuntimeError(f'process {pid} image {current["executable"]} differs from the receipt')
    return {'receipt_path': str(path), 'process_id': pid, 'create_time': recorded['create_time'],
            'executable': recorded['executable']}


def document_count(sw):
    from scripts.sw_connect import get_com_member as get
    return int(get(sw, 'GetDocumentCount'))


def open_documents(sw):
    from scripts.sw_connect import get_com_member as get
    rows = []
    for doc in list(get(sw, 'GetDocuments') or []):
        rows.append({'title': str(get(doc, 'GetTitle') or ''), 'path': str(get(doc, 'GetPathName') or '')})
    return rows


def exit_empty_session(sw, process_id, wait_seconds=60, startup_receipt_path=None, identity=_current_identity):
    from scripts.sw_connect import get_com_member as get
    actual = int(get(sw, 'GetProcessID'))
    if actual != int(process_id):
        raise RuntimeError(f'connected PID {actual} differs from requested {process_id}')
    receipt = None
    if startup_receipt_path is not None:
        receipt = verify_launch_receipt(startup_receipt_path, actual, identity=identity)
    docs = open_documents(sw)
    try:
        count = document_count(sw)
    except Exception as exc:  # noqa: BLE001 - unknown count means "not proven empty"
        return {'status': 'refused', 'process_id': actual, 'reason': f'document count unavailable: {exc}',
                'open_documents': docs, 'exit_attempted': False}
    if docs or count or get(sw, 'ActiveDoc') is not None:
        return {'status': 'refused', 'process_id': actual, 'reason': 'open documents', 'open_documents': docs,
                'document_count': count, 'exit_attempted': False}
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
                'receipt_verified': receipt is not None, 'receipt': receipt, 'document_count': count,
                'exit_call_count': 1, 'exit_returned': str(returned), 'process_exit_verified': exited,
                'seconds': round(time.time() - started, 1),
                'note': None if exited else 'ExitApp was called once; not retried, not terminated.'}
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))
