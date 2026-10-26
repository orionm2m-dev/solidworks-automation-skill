"""通过已安装的主程序启动独立进程；不调用 UI、不回退已有实例、不自动重试。"""
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import subprocess
import time

from .cad_installation import discover_installations
from . import sw_connect as connection


def _image_path(handle):
    """QueryFullProcessImageNameW 的公开 ABI；仅查询已持有的进程句柄。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                      ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buffer))
    if not query(int(handle), 0, buffer, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not 0 < size.value < len(buffer):
        raise ValueError("Invalid executable image length")
    return buffer.value


def _process_identity(pid):
    """同一句柄读取创建时间、映像与退出状态；任何未知结果均阻止后续写入。"""
    import win32api
    import win32process

    handle = win32api.OpenProcess(0x1000, False, pid)
    try:
        created = float(win32process.GetProcessTimes(handle)["CreationTime"].timestamp())
        image = _image_path(handle)
        alive = win32process.GetExitCodeProcess(handle) == 259
        if not math.isfinite(created) or created <= 0:
            raise ValueError("Invalid process creation timestamp")
        return {"process_id": pid, "create_time": created, "executable": image, "alive": alive}
    finally:
        handle.Close()


def _same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def _installed_executable(version):
    candidates = discover_installations("solidworks")
    if version is not None:
        candidates = [item for item in candidates if str(item.get("version")) == str(version)]
    if not candidates:
        raise ValueError("No matching installed SOLIDWORKS executable")
    selected = candidates[0]
    path = Path(selected["executable"])
    if not path.is_absolute() or path.name.casefold() != "sldworks.exe" or not path.is_file():
        raise ValueError("Installation locator did not return an existing absolute SLDWORKS.exe")
    return path.resolve(), selected


def validate_receipt_path(value):
    """日志必须是新绝对 JSON 文件；不会覆盖旧的未知启动结果。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("startup_receipt_path is required for executable launch")
    path = Path(value)
    if not path.is_absolute() or path.suffix.lower() != ".json" or not path.parent.is_dir():
        raise ValueError("startup_receipt_path must be an absolute JSON path with an existing parent")
    if path.exists() or path.with_name(path.name + ".tmp").exists():
        raise FileExistsError("Startup receipt already exists; inspect it, do not replay launch")
    return path


def _write_receipt(path, value, *, initial=False):
    destination = path if initial else path.with_name(path.name + ".tmp")
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if not initial:
        os.replace(destination, path)


def launch_executable(version, wait_seconds, startup_receipt_path):
    """启动一次主程序并绑定其新 PID；返回代理、moniker、PID 与启动证据。"""
    receipt_path = validate_receipt_path(startup_receipt_path)
    executable, installation = _installed_executable(version)
    report = {
        "status": "pending", "phase": "launch_intent", "launch_mode": "executable",
        "launch_attempted": True, "process_id": None, "new_process_verified": False,
        "user_control_verified": False, "visible_verified": False,
        "executable": str(executable), "installation_source": installation.get("source"),
        "installation_version": installation.get("version"), "requested_version": version,
        "startup_receipt_path": str(receipt_path), "automatic_retry": False,
        "termination_attempted": False,
    }
    with connection._LaunchGuard():
        known_pids = connection._snapshot_process_ids()
        report["known_process_ids_before"] = sorted(known_pids)
        report["launch_intent_time"] = time.time()
        # 必须在 CreateProcess 之前落盘；意图不等同于已成功启动。
        _write_receipt(receipt_path, report, initial=True)
        try:
            process = subprocess.Popen(
                [str(executable)], cwd=str(executable.parent), shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            pid = process.pid
            report.update(process_id=pid, phase="process_created")
            _write_receipt(receipt_path, report)
            if type(pid) is not int or pid <= 0 or pid in known_pids:
                raise ValueError("Created PID is not proven new")
            first = _process_identity(pid)
            report["process_identity"] = first
            if (first["alive"] is not True or not _same_path(first["executable"], executable)
                    or first["create_time"] < report["launch_intent_time"] - 1
                    or first["create_time"] > time.time() + 1):
                raise ValueError("New process creation time, image path or liveness was not verified")
            report.update(new_process_verified=True, phase="waiting_for_exact_pid_rot")
            _write_receipt(receipt_path, report)

            def verify():
                current = _process_identity(pid)
                if (current["alive"] is not True or current["create_time"] != first["create_time"]
                        or not _same_path(current["executable"], executable)):
                    raise ValueError("Spawned process identity changed or process exited")

            deadline = time.monotonic() + float(wait_seconds)
            while True:
                verify()
                try:
                    # 允许标准应用别名，但 resolver 必须读取实际 PID；从不返回其它进程。
                    sw, moniker = connection._connect_process(pid, version)
                    break
                except connection.SolidWorksConnectionError as error:
                    if error.code != "SW_PROCESS_NOT_FOUND" or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)
            connection._wait_until_ready(sw, max(0.1, deadline - time.monotonic()))

            def verify_proxy():
                verify()
                if connection._read_process_id(sw) != pid:
                    raise ValueError("COM proxy does not match the spawned PID")
                if version is not None and connection.get_sw_version(sw)["year"] != int(version):
                    raise ValueError("COM version does not match the requested installation")

            verify_proxy()
            report.update(moniker=moniker, phase="user_control_intent")
            _write_receipt(receipt_path, report)
            sw.UserControl = True
            verify_proxy()
            if connection.get_com_member(sw, "UserControl") is not True:
                raise ValueError("UserControl=true was not verified")
            report.update(user_control_verified=True, phase="visible_intent")
            _write_receipt(receipt_path, report)
            sw.Visible = True
            verify_proxy()
            if connection.get_com_member(sw, "Visible") is not True:
                raise ValueError("Visible=true was not verified")
            report.update(status="ok", phase="connected", visible_verified=True)
            _write_receipt(receipt_path, report)
            return sw, moniker, pid, report
        except Exception as error:
            report.update(status="uncertain", error={"type": type(error).__name__, "message": str(error)})
            try:
                _write_receipt(receipt_path, report)
            except Exception as receipt_error:
                detail = f"; receipt update failed: {receipt_error}"
            else:
                detail = ""
            raise connection.SolidWorksConnectionError(
                "SW_EXECUTABLE_LAUNCH_UNCERTAIN", report["phase"],
                f"{error}; receipt={receipt_path}; PID={report['process_id']}{detail}; "
                "no process was closed or terminated; do not replay launch",
            ) from error
