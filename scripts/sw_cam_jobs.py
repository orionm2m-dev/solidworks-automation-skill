"""CAM 长任务的持久启动与状态协议；不实现加工算法，也不按超时结束进程。"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from scripts.sw_operation_guard import solidworks_operation_lock
from scripts.sw_runtime_identity import source_fingerprint

ROOT = Path(__file__).resolve().parents[1]
_CONFIG_FIELDS = {
    "process_id", "process_create_time", "expected_document_path", "addin_clsid", "typelib_path",
    "expected_feature_count", "expected_operation_count", "expected_operation_setup_count",
    "setup_index", "operation_index", "expected_operation_type", "qualification_only",
    "message_policy", "attention_seconds",
}
_METADATA_FIELDS = {
    "schema_version", "job_id", "created_at", "runtime_root", "source_sha256", "source_file_count",
    "job_directory", "process_id", "process_create_time", "expected_document_path", "attention_seconds",
    "worker_pid", "worker_create_time",
}


def process_identity(pid) -> dict:
    """只读原生进程创建时间和存活状态；访问拒绝返回 unknown，不猜测进程已死。"""
    if type(pid) is not int or pid <= 0:
        raise ValueError("pid must be a positive integer")
    report = {"pid": pid, "alive": None, "create_time": None, "status": "unknown"}
    handle = None
    stage = "open"
    try:
        import win32api
        import win32process

        handle = win32api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        stage = "query"
        created = win32process.GetProcessTimes(handle)["CreationTime"].timestamp()
        alive = win32process.GetExitCodeProcess(handle) == 259  # STILL_ACTIVE
        report.update(alive=alive, create_time=float(created), status="alive" if alive else "dead")
    except Exception as error:
        code = getattr(error, "winerror", None)
        if stage == "open" and code in {87, 1168}:  # 无效 PID / 对象不存在。
            report.update(alive=False, status="dead")
        report["error"] = {"type": type(error).__name__, "winerror": code, "stage": stage}
    finally:
        if handle is not None:
            handle.Close()
    return report


def _validate_config(config):
    if not isinstance(config, dict) or set(config) != _CONFIG_FIELDS:
        raise ValueError("Job config must contain exactly the documented fields")
    result = dict(config)
    bounds = {
        "process_id": (1, 2**32 - 1), "expected_feature_count": (1, 262144),
        "expected_operation_count": (1, 512), "expected_operation_setup_count": (1, 512),
        "setup_index": (0, 511), "operation_index": (0, 511),
        "expected_operation_type": (1, 16), "attention_seconds": (5, 3600),
    }
    for key, (lower, upper) in bounds.items():
        if type(result[key]) is not int or not lower <= result[key] <= upper:
            raise ValueError(f"{key} must be an integer in [{lower}, {upper}]")
    created = result["process_create_time"]
    if type(created) not in (int, float) or not math.isfinite(created) or created <= 0:
        raise ValueError("process_create_time must be a finite positive timestamp")
    result["process_create_time"] = float(created)
    if result["qualification_only"] is not True or result["message_policy"] != "vendor_default":
        raise ValueError("Explicit qualification_only=true and vendor_default policy are required")
    for key, suffix in (("expected_document_path", ".sldprt"), ("typelib_path", ".tlb")):
        if not isinstance(result[key], str) or not Path(result[key]).is_absolute() or Path(result[key]).suffix.lower() != suffix:
            raise ValueError(f"{key} must be an absolute {suffix} path")
    if not isinstance(result["addin_clsid"], str) or not re.fullmatch(
        r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}", result["addin_clsid"]
    ):
        raise ValueError("addin_clsid must be a GUID in braces")
    return result


def _directory(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("job_directory must be absolute")
    return path.resolve()


def _write_json(path, value, *, create=False):
    temporary = path if create else path.with_name(path.name + ".tmp")
    created = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if not create:
            os.replace(temporary, path)
    finally:
        if not create and created and temporary.exists():
            temporary.unlink()


def _read_json(path):
    with path.open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return value


def _require_process(pid, expected_create_time):
    identity = process_identity(pid)
    if identity["alive"] is not True or identity["create_time"] != expected_create_time:
        raise RuntimeError("Process identity is unavailable, terminated or reused")
    return identity


def _prepare_job(config, job_directory):
    config = _validate_config(config)
    directory = _directory(job_directory)
    if not directory.parent.is_dir():
        raise ValueError("The job parent directory must already exist")
    _require_process(config["process_id"], config["process_create_time"])
    digest, count = source_fingerprint(ROOT)
    request = {
        "schema_version": 1, "job_id": uuid.uuid4().hex, "created_at": time.time(),
        "runtime_root": str(ROOT), "source_sha256": digest, "source_file_count": count, "config": config,
    }
    state = {key: value for key, value in request.items() if key != "config"}
    state.update({key: config[key] for key in (
        "process_id", "process_create_time", "expected_document_path", "attention_seconds"
    )})
    state.update(job_directory=str(directory), worker_pid=None, worker_create_time=None,
                 status="pending", phase="prepared", finished=False, may_continue=False,
                 updated_at=time.time())
    directory.mkdir()  # 目录本身也必须是新的；不恢复或复用旧任务。
    _write_json(directory / "request.json", request, create=True)
    _write_json(directory / "state.json", state, create=True)
    return directory, request, state


def start_job(config: dict, job_directory: str) -> dict:
    """创建新任务并启动隐藏 worker；参数为配置和新目录，返回只读状态快照。"""
    directory, _request, state = _prepare_job(config, job_directory)
    try:
        env = os.environ.copy()
        env["SOLIDWORKS_MCP_RUNTIME_ROOT"] = str(ROOT)
        env["SOLIDWORKS_MCP_PROCESS_ID"] = str(config["process_id"])
        flags = 0
        if sys.platform == "win32":
            # 不能继承临时 MCP Job 的 kill-on-close 生命周期；不允许静默降级。
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB
        with (directory / "worker.log").open("x", encoding="utf-8") as log:
            child = subprocess.Popen(
                [sys.executable, "-m", "scripts.sw_cam_jobs", "--job-directory", str(directory)],
                cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, shell=False, close_fds=True, creationflags=flags,
            )
        identity = process_identity(child.pid)
        _write_json(directory / "launch.json", {
            "pid": child.pid, "create_time": identity.get("create_time"), "launched_at": time.time()
        }, create=True)
    except Exception as error:
        # 已启动的 worker 不会被终止；无法确认启动阶段则报告不确定。
        spawned = "child" in locals()
        if not spawned:
            state.update(status="error", phase="launch_failed", finished=True, completed_at=time.time(),
                         may_continue=False, error={"type": type(error).__name__, "message": str(error)[:1000]})
            _write_json(directory / "state.json", state)
        result = inspect_job(str(directory))
        result["launch_error"] = {"type": type(error).__name__, "worker_started": spawned}
        if spawned:
            result.update(observation_status="uncertain", may_continue=False)
        return result
    return inspect_job(str(directory))


def inspect_job(job_directory) -> dict:
    """只读状态和 worker PID/创建时间；不重放、不重启、不终止后台任务。"""
    directory = _directory(job_directory)
    try:
        state = _read_json(directory / "state.json")
        identity_data = {"pid": state.get("worker_pid"), "create_time": state.get("worker_create_time")}
        if not identity_data["pid"]:
            for name in ("worker.claim.json", "launch.json"):
                if (directory / name).is_file():
                    identity_data = _read_json(directory / name)
                    break
        pid, expected = identity_data.get("pid"), identity_data.get("create_time")
        identity = process_identity(pid) if type(pid) is int and pid > 0 else {
            "pid": pid, "alive": None, "create_time": None, "status": "unknown"
        }
        matched = identity.get("alive") is True and expected is not None and identity.get("create_time") == expected
        result = dict(state)
        result.update(worker_identity=identity, worker_alive=matched if identity.get("alive") is not None else None,
                      worker_identity_matches=matched)
        elapsed = max(0.0, time.time() - float(state["created_at"]))
        finished = state.get("finished") is True
        result["attention_required"] = not finished and elapsed >= state["attention_seconds"]
        result["observation_status"] = "finished" if finished else ("running" if matched else "uncertain")
        if not finished:
            result["may_continue"] = False
        return result
    except Exception as error:
        return {"status": "unknown", "observation_status": "uncertain", "finished": False,
                "may_continue": False, "job_directory": str(directory),
                "error": {"type": type(error).__name__, "message": str(error)[:1000]}}


def _valid_stop_request(command, job_id):
    return (isinstance(command, dict) and set(command) == {"job_id", "acknowledge_native_not_cancelled"}
            and command["job_id"] == job_id and command["acknowledge_native_not_cancelled"] is True)


def request_observation_stop(job_directory, *, acknowledge_native_not_cancelled):
    """只请求停止观察并解除本方订阅；不是取消 CAM，不能中断当前 COM 调用。"""
    if acknowledge_native_not_cancelled is not True:
        raise ValueError("Explicit acknowledgement that native CAM is not cancelled is required")
    directory = _directory(job_directory)
    state = inspect_job(str(directory))
    if state.get("finished") or state.get("worker_identity_matches") is not True:
        return {"status": "blocked", "may_continue": False,
                "reason": "No verified live unfinished observer", "state": state}
    request = {"job_id": state["job_id"], "acknowledge_native_not_cancelled": True}
    path = directory / "stop_observation.json"
    if path.exists():
        if not _valid_stop_request(_read_json(path), state["job_id"]):
            raise ValueError("Existing stop request belongs to another job or policy")
    else:
        _write_json(path, request, create=True)
    return {"status": "stop_requested", "job_id": state["job_id"],
            "native_cam_cancelled": False, "cleanup_confirmed": False, "may_continue": False}


def _validate_source(request):
    if os.path.normcase(str(Path(request["runtime_root"]).resolve())) != os.path.normcase(str(ROOT)):
        raise RuntimeError("Job belongs to another runtime directory")
    digest, count = source_fingerprint(ROOT)
    if digest != request["source_sha256"] or count != request["source_file_count"]:
        raise RuntimeError("Runtime source fingerprint changed; job will not execute")


def _validate_registration(config):
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration

    inventory = discover_cam_installations()
    if inventory.get("errors"):
        raise RuntimeError("CAM registration cannot be verified")
    registered = select_registration(inventory, config["addin_clsid"])
    expected = Path(registered["addin_path"]).parent / "camworks.tlb"
    if os.path.normcase(str(expected.resolve())) != os.path.normcase(str(Path(config["typelib_path"]).resolve())):
        raise RuntimeError("CAM type library does not match the registered add-in")
    return registered


def _initialize_com():
    import pythoncom

    pythoncom.CoInitialize()
    return pythoncom


def _attach(config):
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam import _member, document_snapshot
    from scripts.sw_operation_guard import check_document_target

    registration = _validate_registration(config)
    sw, _model = connect_solidworks(process_id=config["process_id"], wait_seconds=1)
    year = int(str(_member(sw, "RevisionNumber")).split(".")[0]) + 1992
    registered_year = re.search(r"SOLIDWORKS (20\d{2})", registration["registry_key"], re.IGNORECASE)
    if registered_year and int(registered_year[1]) != year:
        raise ValueError("CAM registration belongs to another SOLIDWORKS major version")
    snapshot = document_snapshot(sw)
    if snapshot is None:
        raise RuntimeError("No active qualification document")
    check_document_target(snapshot["path"], snapshot["title"],
                          expected_path=config["expected_document_path"], required=True)
    return sw


def _execute(sw, config, publish):
    from scripts.sw_cam_toolpaths import run_toolpath_job

    return run_toolpath_job(sw, config, publish,
                            stop_observation=getattr(publish, "stop_observation_requested", None))


def _worker(job_directory):
    directory = _directory(job_directory)
    identity = process_identity(os.getpid())
    claim = {"pid": os.getpid(), "create_time": identity.get("create_time"), "claimed_at": time.time()}
    # 声明文件永远不删除。重复启动即使前 worker 已退出也不允许重放。
    try:
        _write_json(directory / "worker.claim.json", claim, create=True)
    except Exception:
        return 2
    com = None
    state = None
    try:
        request = _read_json(directory / "request.json")
        state = _read_json(directory / "state.json")
        if request.get("schema_version") != 1 or state.get("job_id") != request.get("job_id") or state.get("finished"):
            raise ValueError("Invalid or already finished job")
        config = _validate_config(request["config"])
        expected_metadata = {key: request[key] for key in (
            "schema_version", "job_id", "created_at", "runtime_root", "source_sha256", "source_file_count"
        )}
        expected_metadata.update({key: config[key] for key in (
            "process_id", "process_create_time", "expected_document_path", "attention_seconds"
        )})
        expected_metadata["job_directory"] = str(directory)
        if any(state.get(key) != value for key, value in expected_metadata.items()):
            raise ValueError("Job state metadata differs from its immutable request")
        if identity.get("alive") is not True or identity.get("create_time") is None:
            raise RuntimeError("Worker process identity could not be verified")
        state.update(worker_pid=claim["pid"], worker_create_time=claim["create_time"])
        metadata = {key: state[key] for key in _METADATA_FIELDS}

        def publish(update):
            if not isinstance(update, dict):
                raise TypeError("Job publication must be a dictionary")
            if "finished" in update or any(key in update and update[key] != value for key, value in metadata.items()):
                raise ValueError("Publication cannot replace worker lifecycle metadata")
            updated = {**state, **update, **metadata, "updated_at": time.time(), "finished": False,
                       "may_continue": False}
            _write_json(directory / "state.json", updated)
            state.clear()
            state.update(updated)

        def stop_observation_requested():
            path = directory / "stop_observation.json"
            if not path.exists():
                return False
            command = _read_json(path)
            if not _valid_stop_request(command, request["job_id"]):
                raise ValueError("Stop request identity or acknowledgement is invalid")
            return True

        publish.stop_observation_requested = stop_observation_requested

        _validate_source(request)
        _require_process(config["process_id"], config["process_create_time"])
        _validate_registration(config)
        publish({"status": "pending", "phase": "waiting_for_lock"})
        com = _initialize_com()
        with solidworks_operation_lock(process_id=config["process_id"]):
            _validate_source(request)
            _require_process(config["process_id"], config["process_create_time"])
            publish({"status": "running", "phase": "attaching"})
            sw = _attach(config)
            try:
                # 算法必须保留事件/COM 生命周期直到确认完成；attention 不是取消。
                result = _execute(sw, config, publish)
            finally:
                sw = None
            terminal_status = isinstance(result, dict) and result.get("status") in {"completed", "error", "review_required"}
            stopped = (isinstance(result, dict) and result.get("status") == "uncertain" and
                       result.get("observation_stopped") is True and stop_observation_requested())
            if not terminal_status and not stopped:
                raise RuntimeError("Toolpath algorithm returned without a terminal result")
            terminal = {**state, **result, **metadata, "result": result, "finished": True,
                        "completed_at": time.time(), "updated_at": time.time()}
            terminal["may_continue"] = result.get("status") == "completed" and result.get("may_continue") is True
            _write_json(directory / "state.json", terminal)
        return 0 if result["status"] == "completed" else 1
    except Exception as error:
        if state is not None:
            uncertain = state.get("mutation_attempted") is True
            state.update(status="uncertain" if uncertain else "error", phase="worker_error",
                         finished=not uncertain, may_continue=False,
                         error={"type": type(error).__name__, "message": str(error)[:1000]}, updated_at=time.time())
            try:
                _write_json(directory / "state.json", state)
            except Exception:
                pass  # 保留最后已持久化状态，inspect 会标记消失的 worker 为 uncertain。
        return 1
    finally:
        if com is not None:
            com.CoUninitialize()


def main(argv=None):
    """CLI：启动新配置，或执行已准备任务；foreground 不依赖后台进程脱离 Job。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-directory", required=True)
    parser.add_argument("--start-config")
    parser.add_argument("--foreground", action="store_true")
    args = parser.parse_args(argv)
    if args.foreground and not args.start_config:
        parser.error("--foreground requires --start-config")
    try:
        if args.start_config:
            config_path = Path(args.start_config)
            if not config_path.is_absolute():
                raise ValueError("--start-config must be absolute")
            config = _read_json(config_path)
            if args.foreground:
                directory, _request, _state = _prepare_job(config, args.job_directory)
                return _worker(directory)
            report = start_job(config, args.job_directory)
            print(json.dumps(report, ensure_ascii=False))
            return 1 if report.get("status") in {"error", "unknown"} else 0
        return _worker(args.job_directory)
    except Exception as error:
        print(f"CAM job refused: {type(error).__name__}: {str(error)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
