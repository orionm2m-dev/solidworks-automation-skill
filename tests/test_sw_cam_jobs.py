"""独立 CAM worker 的验证、互斥与持久状态测试；不启动真实进程或 CAD。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_jobs as jobs

REAL_ATTACH = jobs._attach
REAL_EXECUTE = jobs._execute


@pytest.fixture
def environment(tmp_path, monkeypatch):
    """所有外部进程、COM 和 CAM 入口均为模拟对象。"""
    part = tmp_path / "calibration.sldprt"
    typelib = tmp_path / "camworks.tlb"
    part.write_bytes(b"test only")
    typelib.write_bytes(b"test only")
    config = {
        "process_id": 612,
        "process_create_time": 1000.5,
        "expected_document_path": str(part),
        "addin_clsid": "{00000000-0000-0000-0000-000000000001}",
        "typelib_path": str(typelib),
        "expected_feature_count": 2,
        "expected_operation_count": 1,
        "expected_operation_setup_count": 1,
        "setup_index": 0,
        "operation_index": 0,
        "expected_operation_type": 3,
        "qualification_only": True,
        "message_policy": "vendor_default",
        "attention_seconds": 60,
    }
    fingerprint = Mock(return_value=("a" * 64, 17))

    def identity(pid):
        created = 1000.5 if pid == 612 else (2000.5 if pid == 991 else 3000.5)
        return {"pid": pid, "alive": True, "create_time": created, "status": "alive"}

    identities = Mock(side_effect=identity)
    popen = Mock(return_value=SimpleNamespace(pid=991))
    com = SimpleNamespace(CoUninitialize=Mock())
    initialize = Mock(return_value=com)
    sw = object()
    attach = Mock(return_value=sw)
    execute = Mock(return_value={"status": "completed", "toolpath_verified": True})
    registration = Mock()
    events = []
    held = {"value": False}

    @contextmanager
    def lock(*args, **kwargs):
        events.append(("lock_enter", args, kwargs))
        held["value"] = True
        try:
            yield
        finally:
            events.append(("lock_exit", args, kwargs))
            held["value"] = False

    monkeypatch.setattr(jobs, "source_fingerprint", fingerprint)
    monkeypatch.setattr(jobs, "process_identity", identities)
    monkeypatch.setattr(jobs.subprocess, "Popen", popen)
    monkeypatch.setattr(jobs, "_initialize_com", initialize)
    monkeypatch.setattr(jobs, "_attach", attach)
    monkeypatch.setattr(jobs, "_execute", execute)
    monkeypatch.setattr(jobs, "_validate_registration", registration)
    monkeypatch.setattr(jobs, "solidworks_operation_lock", lock)
    return SimpleNamespace(
        config=config, directory=tmp_path / "job", fingerprint=fingerprint,
        identities=identities, popen=popen, initialize=initialize, com=com,
        attach=attach, execute=execute, registration=registration, sw=sw,
        events=events, held=held,
    )


def read_json(path):
    """读取测试中的持久任务状态。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    """写入测试夹具，不触及生产任务。"""
    Path(path).write_text(json.dumps(value), encoding="utf-8")


def test_start_persists_request_and_launch_without_attaching(environment):
    f = environment
    jobs.start_job(f.config, f.directory)
    request = read_json(f.directory / "request.json")
    state = read_json(f.directory / "state.json")
    launch = read_json(f.directory / "launch.json")
    assert request["config"] == f.config
    assert request["runtime_root"] == str(jobs.ROOT)
    assert request["source_sha256"] == "a" * 64
    assert state["finished"] is False
    assert state["status"] == "pending"
    assert launch
    f.popen.assert_called_once()
    command = f.popen.call_args.args[0]
    options = f.popen.call_args.kwargs
    assert command[:3] == [sys.executable, "-m", "scripts.sw_cam_jobs"]
    assert command[3:] == ["--job-directory", str(f.directory)]
    assert options["cwd"] == str(jobs.ROOT)
    assert options["stdin"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.STDOUT
    assert Path(options["stdout"].name) == f.directory / "worker.log"
    assert options["shell"] is False
    assert options["close_fds"] is True
    if sys.platform == "win32":
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert options["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB
    f.attach.assert_not_called()
    f.initialize.assert_not_called()
    f.execute.assert_not_called()


@pytest.mark.parametrize("field", [
    "process_id", "expected_feature_count", "expected_operation_count",
    "expected_operation_setup_count", "setup_index", "operation_index",
    "expected_operation_type", "attention_seconds",
])
@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_integer_configuration_rejects_coercions_before_launch(environment, field, value):
    f = environment
    f.config[field] = value
    with pytest.raises((ValueError, TypeError)):
        jobs.start_job(f.config, f.directory)
    f.popen.assert_not_called()
    f.attach.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("process_id", 0), ("process_create_time", 0.0),
    ("process_create_time", float("inf")), ("process_create_time", float("nan")),
    ("process_create_time", True), ("process_create_time", "1000.5"),
    ("expected_feature_count", 0), ("expected_feature_count", 262145),
    ("expected_operation_count", 0), ("expected_operation_count", 513),
    ("expected_operation_setup_count", 0), ("expected_operation_setup_count", 513),
    ("setup_index", -1), ("operation_index", 512),
    ("expected_operation_type", 0), ("expected_operation_type", 17),
    ("attention_seconds", 4), ("attention_seconds", 3601), ("qualification_only", 1),
    ("qualification_only", False), ("message_policy", "accept_all"),
    ("addin_clsid", "unregistered.progid"),
    ("expected_document_path", "relative.sldprt"),
    ("typelib_path", "relative.tlb"),
])
def test_invalid_configuration_stops_before_process_creation(environment, field, value):
    f = environment
    f.config[field] = value
    with pytest.raises((ValueError, TypeError)):
        jobs.start_job(f.config, f.directory)
    f.popen.assert_not_called()
    f.attach.assert_not_called()


def test_new_job_directory_is_required_and_existing_files_are_preserved(environment):
    f = environment
    f.directory.mkdir()
    marker = f.directory / "request.json"
    marker.write_text("existing evidence", encoding="utf-8")
    with pytest.raises((ValueError, FileExistsError)):
        jobs.start_job(f.config, f.directory)
    assert marker.read_text(encoding="utf-8") == "existing evidence"
    f.popen.assert_not_called()


def test_start_never_overwrites_state_already_written_by_spawned_worker(environment):
    f = environment
    worker_state = {"status": "in_native_call", "finished": False,
                    "worker_pid": 991, "worker_create_time": 2000.5}

    def spawn(*args, **kwargs):
        assert (f.directory / "request.json").is_file()
        write_json(f.directory / "state.json", worker_state)
        return SimpleNamespace(pid=991)

    f.popen.side_effect = spawn
    jobs.start_job(f.config, f.directory)
    assert read_json(f.directory / "state.json") == worker_state
    assert (f.directory / "launch.json").is_file()


def test_failed_quiet_spawn_has_no_visible_fallback(environment):
    f = environment
    f.popen.side_effect = OSError("process creation failed")
    try:
        jobs.start_job(f.config, f.directory)
    except OSError:
        pass
    assert f.popen.call_count == 1
    f.attach.assert_not_called()
    f.initialize.assert_not_called()


def test_worker_claim_and_whole_native_execution_are_inside_pid_lock(environment):
    f = environment
    jobs.start_job(f.config, f.directory)
    observed = []

    def attach(config):
        assert f.held["value"] is True
        assert (f.directory / "worker.claim.json").is_file()
        assert config == f.config
        observed.append("attach")
        return f.sw

    def execute(sw, config, publish):
        assert f.held["value"] is True
        assert sw is f.sw
        observed.append("execute")
        publish({"status": "in_native_call", "stage": "generate_toolpath"})
        for invalid in ({"finished": True}, {"worker_pid": -1}, {"worker_create_time": -1}):
            with pytest.raises(ValueError):
                publish(invalid)
        during = read_json(f.directory / "state.json")
        assert during["finished"] is False
        assert during["worker_pid"] == os.getpid()
        assert during["worker_create_time"] == 3000.5
        assert "completed_at" not in during
        return {"status": "completed", "toolpath_verified": True}

    f.attach.side_effect = attach
    f.execute.side_effect = execute
    assert jobs._worker(f.directory) == 0
    state = read_json(f.directory / "state.json")
    assert observed == ["attach", "execute"]
    assert state["finished"] is True
    assert state["status"] == "completed"
    assert state["completed_at"]
    assert state["result"]["toolpath_verified"] is True
    assert f.events[0][0] == "lock_enter"
    assert f.events[0][2]["process_id"] == 612
    assert f.events[-1][0] == "lock_exit"
    f.com.CoUninitialize.assert_called_once_with()


def test_worker_replay_does_not_attach_or_overwrite_completed_state(environment):
    f = environment
    jobs.start_job(f.config, f.directory)
    assert jobs._worker(f.directory) == 0
    original = (f.directory / "state.json").read_bytes()
    f.attach.reset_mock()
    f.execute.reset_mock()
    f.initialize.reset_mock()
    assert jobs._worker(f.directory) != 0
    assert (f.directory / "state.json").read_bytes() == original
    f.attach.assert_not_called()
    f.execute.assert_not_called()
    f.initialize.assert_not_called()


@pytest.mark.parametrize("failure", ["source", "target_identity", "registration"])
def test_worker_guards_fail_before_com_initialization(environment, failure):
    f = environment
    jobs.start_job(f.config, f.directory)
    if failure == "source":
        f.fingerprint.return_value = ("b" * 64, 17)
    elif failure == "target_identity":
        f.identities.side_effect = lambda pid: {
            "pid": pid, "alive": True, "create_time": 9999.5, "status": "alive",
        }
    else:
        f.registration.side_effect = ValueError("registration changed")
    assert jobs._worker(f.directory) != 0
    state = read_json(f.directory / "state.json")
    assert state["finished"] is True
    assert state["status"] == "error"
    f.initialize.assert_not_called()
    f.attach.assert_not_called()
    f.execute.assert_not_called()


def test_source_is_rechecked_after_acquiring_operation_lock(environment):
    f = environment
    jobs.start_job(f.config, f.directory)
    f.fingerprint.side_effect = [("a" * 64, 17), ("b" * 64, 17)]
    assert jobs._worker(f.directory) != 0
    f.initialize.assert_called_once()
    f.attach.assert_not_called()
    f.execute.assert_not_called()
    f.com.CoUninitialize.assert_called_once()


def test_worker_execution_exception_finishes_error_and_releases_lock(environment):
    f = environment
    jobs.start_job(f.config, f.directory)
    f.execute.side_effect = RuntimeError("native execution failed")
    assert jobs._worker(f.directory) != 0
    state = read_json(f.directory / "state.json")
    assert state["finished"] is True
    assert state["status"] == "error"
    assert f.held["value"] is False
    f.com.CoUninitialize.assert_called_once_with()


def test_unexpected_exception_after_mutation_stays_uncertain(environment):
    f = environment
    jobs.start_job(f.config, f.directory)

    def execute(sw, config, publish):
        publish({"status": "in_native_call", "mutation_attempted": True})
        raise RuntimeError("completion is unknown")

    f.execute.side_effect = execute
    assert jobs._worker(f.directory) != 0
    state = read_json(f.directory / "state.json")
    assert state["status"] == "uncertain"
    assert state["finished"] is False
    assert state["may_continue"] is False
    assert "completed_at" not in state
    f.com.CoUninitialize.assert_called_once_with()


@pytest.mark.parametrize("state,created", [
    ("dead", None), ("alive", 9999.5), ("unknown", None),
])
def test_inspect_missing_reused_or_unverifiable_worker_is_uncertain(environment, state, created):
    f = environment
    jobs.start_job(f.config, f.directory)
    files = {p.name: p.read_bytes() for p in f.directory.iterdir() if p.is_file()}
    alive = {"alive": True, "dead": False, "unknown": None}[state]
    f.identities.side_effect = lambda pid: {
        "pid": pid, "alive": alive, "create_time": created, "status": state,
    }
    result = jobs.inspect_job(f.directory)
    assert result["observation_status"] == "uncertain"
    assert result["finished"] is False
    assert result["may_continue"] is False
    assert result["worker_identity_matches"] is False
    assert {p.name: p.read_bytes() for p in f.directory.iterdir() if p.is_file()} == files
    assert f.popen.call_count == 1
    f.attach.assert_not_called()
    f.execute.assert_not_called()


def test_inspect_live_matching_worker_can_require_attention_without_stopping(environment):
    f = environment
    jobs.start_job(f.config, f.directory)
    state = read_json(f.directory / "state.json")
    state["created_at"] = jobs.time.time() - 61
    write_json(f.directory / "state.json", state)
    before = (f.directory / "state.json").read_bytes()
    report = jobs.inspect_job(f.directory)
    assert report["observation_status"] == "running"
    assert report["worker_alive"] is True
    assert report["worker_identity_matches"] is True
    assert report["attention_required"] is True
    assert report["finished"] is False
    assert report["may_continue"] is False
    assert (f.directory / "state.json").read_bytes() == before
    assert f.popen.call_count == 1


def test_completed_receipt_remains_terminal_when_worker_exits(environment):
    f = environment
    jobs.start_job(f.config, f.directory)
    f.execute.return_value = {"status": "completed", "may_continue": True}
    assert jobs._worker(f.directory) == 0
    f.identities.side_effect = lambda pid: {"pid": pid, "alive": False, "create_time": None, "status": "dead"}
    result = jobs.inspect_job(f.directory)
    assert result["observation_status"] == "finished"
    assert result["finished"] is True
    assert result["status"] == "completed"
    assert result["may_continue"] is True
    assert result["attention_required"] is False


def test_cli_foreground_prepares_and_executes_without_child_process(environment, tmp_path):
    f = environment
    config_file = tmp_path / "config.json"
    write_json(config_file, f.config)
    assert jobs.main(["--start-config", str(config_file), "--job-directory", str(f.directory), "--foreground"]) == 0
    assert (f.directory / "request.json").is_file()
    assert (f.directory / "worker.claim.json").is_file()
    assert read_json(f.directory / "state.json")["finished"] is True
    f.popen.assert_not_called()
    f.attach.assert_called_once_with(f.config)
    f.execute.assert_called_once()


@pytest.mark.parametrize("field", ["expected_document_path", "process_id", "source_sha256", "runtime_root"])
def test_worker_rejects_state_metadata_diverging_from_request(environment, field):
    f = environment
    jobs.start_job(f.config, f.directory)
    state = read_json(f.directory / "state.json")
    state[field] = 9876 if field == "process_id" else "tampered"
    write_json(f.directory / "state.json", state)
    assert jobs._worker(f.directory) != 0
    f.initialize.assert_not_called()
    f.attach.assert_not_called()
    f.execute.assert_not_called()


@pytest.mark.parametrize("pid", [0, -1, True, "612", 612.0])
def test_process_identity_requires_strict_positive_integer(pid):
    with pytest.raises(ValueError):
        jobs.process_identity(pid)


@pytest.mark.parametrize("exit_code,expected", [(259, "alive"), (0, "dead")])
def test_process_identity_reads_creation_time_and_always_closes_handle(monkeypatch, exit_code, expected):
    handle = SimpleNamespace(Close=Mock())
    api = SimpleNamespace(OpenProcess=Mock(return_value=handle))
    native = SimpleNamespace(
        GetProcessTimes=Mock(return_value={"CreationTime": SimpleNamespace(timestamp=lambda: 1234.5)}),
        GetExitCodeProcess=Mock(return_value=exit_code),
    )
    monkeypatch.setitem(sys.modules, "win32api", api)
    monkeypatch.setitem(sys.modules, "win32process", native)
    result = jobs.process_identity(612)
    assert result == {"pid": 612, "alive": expected == "alive", "create_time": 1234.5, "status": expected}
    api.OpenProcess.assert_called_once_with(0x1000, False, 612)
    handle.Close.assert_called_once_with()


@pytest.mark.parametrize("winerror,status", [(5, "unknown"), (87, "dead"), (1168, "dead")])
def test_process_identity_distinguishes_access_denial_from_absent_pid(monkeypatch, winerror, status):
    error = OSError("native process query failure")
    error.winerror = winerror
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(OpenProcess=Mock(side_effect=error)))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace())
    result = jobs.process_identity(612)
    assert result["status"] == status
    assert result["alive"] is (False if status == "dead" else None)
    assert result["create_time"] is None


@pytest.mark.skipif(sys.platform != "win32", reason="只读 Windows 进程元数据验证")
def test_process_identity_reads_own_real_process_without_cad():
    result = jobs.process_identity(os.getpid())
    assert result["pid"] == os.getpid()
    assert result["alive"] is True
    assert result["status"] == "alive"
    assert isinstance(result["create_time"], float)
    assert result["create_time"] > 0


@pytest.mark.parametrize("field,value", [
    ("expected_feature_count", 1), ("expected_feature_count", 262144),
    ("expected_operation_count", 1), ("expected_operation_count", 512),
    ("expected_operation_setup_count", 1), ("expected_operation_setup_count", 512),
    ("expected_operation_type", 1), ("expected_operation_type", 16),
    ("attention_seconds", 5), ("attention_seconds", 3600),
])
def test_final_configuration_bounds_accept_both_endpoints(environment, field, value):
    f = environment
    f.config[field] = value
    jobs.start_job(f.config, f.directory)
    assert read_json(f.directory / "request.json")["config"][field] == value
    f.popen.assert_called_once()


@pytest.mark.parametrize("status", ["completed", "error", "review_required"])
def test_worker_accepts_only_confirmed_terminal_result_statuses(environment, status):
    f = environment
    jobs.start_job(f.config, f.directory)
    f.execute.return_value = {"status": status, "may_continue": True}
    assert jobs._worker(f.directory) == (0 if status == "completed" else 1)
    state = read_json(f.directory / "state.json")
    assert state["status"] == status
    assert state["result"]["status"] == status
    assert state["finished"] is True
    assert state["completed_at"]
    assert state["may_continue"] is (status == "completed")


def test_pending_algorithm_return_after_mutation_is_not_terminal(environment):
    f = environment
    jobs.start_job(f.config, f.directory)

    def execute(sw, config, publish):
        publish({"status": "in_native_call", "mutation_attempted": True})
        return {"status": "pending", "may_continue": True}

    f.execute.side_effect = execute
    assert jobs._worker(f.directory) == 1
    state = read_json(f.directory / "state.json")
    assert state["status"] == "uncertain"
    assert state["finished"] is False
    assert state["may_continue"] is False
    assert "completed_at" not in state


@pytest.mark.parametrize("revision,matches", [("34.4.1", True), ("33.5.0", False)])
def test_attach_rechecks_registered_cam_major_version_before_execution(environment, monkeypatch, revision, matches):
    from scripts import sw_cam, sw_connect

    f = environment
    steps = []
    registered = {"registry_key": r"SOFTWARE\SOLIDWORKS\SOLIDWORKS 2026\AddIns"}

    def registration(config):
        steps.append("registration")
        return registered

    def connect(**kwargs):
        steps.append("connect")
        return f.sw, object()

    f.registration.side_effect = registration
    connector = Mock(side_effect=connect)
    snapshot = Mock(return_value={
        "path": f.config["expected_document_path"], "title": "calibration.sldprt",
        "type": 1, "needs_save": False,
    })
    monkeypatch.setattr(sw_connect, "connect_solidworks", connector)
    monkeypatch.setattr(sw_cam, "_member", Mock(return_value=revision))
    monkeypatch.setattr(sw_cam, "document_snapshot", snapshot)
    if matches:
        assert REAL_ATTACH(f.config) is f.sw
        snapshot.assert_called_once_with(f.sw)
    else:
        with pytest.raises(ValueError, match="another SOLIDWORKS major version"):
            REAL_ATTACH(f.config)
        snapshot.assert_not_called()
    assert steps == ["registration", "connect"]
    f.registration.assert_called_once_with(f.config)
    connector.assert_called_once_with(process_id=612, wait_seconds=1)
    f.execute.assert_not_called()


@pytest.mark.parametrize("acknowledgement", [False, None, 0, 1, 1.0, "true", "false"])
def test_stop_requires_actual_boolean_acknowledgement_before_reading_job(environment, monkeypatch, acknowledgement):
    f = environment
    inspection = Mock()
    monkeypatch.setattr(jobs, "inspect_job", inspection)
    with pytest.raises(ValueError):
        jobs.request_observation_stop(f.directory, acknowledge_native_not_cancelled=acknowledgement)
    inspection.assert_not_called()
    assert not f.directory.exists()
    f.attach.assert_not_called()


def test_stop_request_is_identity_bound_idempotent_and_does_not_touch_native_state(environment, monkeypatch):
    f = environment
    jobs.start_job(f.config, f.directory)
    before = {name: (f.directory / name).read_bytes() for name in ("request.json", "state.json", "launch.json")}
    request = read_json(f.directory / "request.json")
    first = jobs.request_observation_stop(f.directory, acknowledge_native_not_cancelled=True)
    command = f.directory / "stop_observation.json"
    assert read_json(command) == {"job_id": request["job_id"], "acknowledge_native_not_cancelled": True}
    assert first == {"status": "stop_requested", "job_id": request["job_id"],
                     "native_cam_cancelled": False, "cleanup_confirmed": False, "may_continue": False}
    original_command = command.read_bytes()
    writer = Mock(wraps=jobs._write_json)
    monkeypatch.setattr(jobs, "_write_json", writer)
    assert jobs.request_observation_stop(f.directory, acknowledge_native_not_cancelled=True) == first
    writer.assert_not_called()
    assert command.read_bytes() == original_command
    assert {name: (f.directory / name).read_bytes() for name in before} == before
    assert f.popen.call_count == 1
    f.initialize.assert_not_called()
    f.attach.assert_not_called()
    f.execute.assert_not_called()


@pytest.mark.parametrize("condition", ["finished", "dead", "reused", "unknown"])
def test_stop_requires_same_live_unfinished_worker(environment, condition):
    f = environment
    jobs.start_job(f.config, f.directory)
    if condition == "finished":
        state = read_json(f.directory / "state.json")
        state.update(finished=True, status="completed")
        write_json(f.directory / "state.json", state)
    else:
        f.identities.side_effect = lambda pid: {
            "pid": pid, "alive": {"dead": False, "reused": True, "unknown": None}[condition],
            "create_time": 9876.5 if condition == "reused" else None, "status": condition,
        }
    report = jobs.request_observation_stop(f.directory, acknowledge_native_not_cancelled=True)
    assert report["status"] == "blocked" and report["may_continue"] is False
    assert not (f.directory / "stop_observation.json").exists()
    f.attach.assert_not_called()
    f.execute.assert_not_called()


@pytest.mark.parametrize("change", [{"job_id": "another-job"}, {"acknowledge_native_not_cancelled": False},
                                    {"acknowledge_native_not_cancelled": 1},
                                    {"acknowledge_native_not_cancelled": 1.0}, {"extra": True}])
def test_conflicting_stop_request_is_rejected_without_replacing_evidence(environment, change):
    f = environment
    jobs.start_job(f.config, f.directory)
    command = {"job_id": read_json(f.directory / "request.json")["job_id"],
               "acknowledge_native_not_cancelled": True, **change}
    path = f.directory / "stop_observation.json"
    write_json(path, command)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        jobs.request_observation_stop(f.directory, acknowledge_native_not_cancelled=True)
    assert path.read_bytes() == original
    f.attach.assert_not_called()


@pytest.mark.parametrize("change", [{"job_id": "another-job"}, {"acknowledge_native_not_cancelled": False},
                                    {"acknowledge_native_not_cancelled": 1},
                                    {"acknowledge_native_not_cancelled": 1.0}, {"extra": True}])
def test_worker_stop_callback_checks_exact_job_and_boolean_policy(environment, change):
    f = environment
    jobs.start_job(f.config, f.directory)
    job_id = read_json(f.directory / "request.json")["job_id"]

    def execute(sw, config, publish):
        assert f.held["value"] is True
        check = publish.stop_observation_requested
        assert check() is False
        path = f.directory / "stop_observation.json"
        write_json(path, {"job_id": job_id, "acknowledge_native_not_cancelled": True, **change})
        with pytest.raises(ValueError):
            check()
        write_json(path, {"job_id": job_id, "acknowledge_native_not_cancelled": True})
        assert check() is True
        return {"status": "completed", "may_continue": True}

    f.execute.side_effect = execute
    assert jobs._worker(f.directory) == 0
    f.com.CoUninitialize.assert_called_once_with()


@pytest.mark.parametrize("has_hook", [False, True])
def test_execute_routes_cooperative_stop_hook_without_invoking_it(environment, monkeypatch, has_hook):
    from scripts import sw_cam_toolpaths

    f = environment
    callback = Mock(return_value=True)
    publish = lambda update: None
    if has_hook:
        publish.stop_observation_requested = callback
    result = {"status": "uncertain", "observation_stopped": True, "may_continue": False}
    algorithm = Mock(return_value=result)
    monkeypatch.setattr(sw_cam_toolpaths, "run_toolpath_job", algorithm)
    assert REAL_EXECUTE(f.sw, f.config, publish) is result
    algorithm.assert_called_once_with(f.sw, f.config, publish,
                                      stop_observation=callback if has_hook else None)
    callback.assert_not_called()


def test_acknowledged_observer_stop_finishes_uncertain_after_algorithm_cleanup(environment):
    f = environment
    jobs.start_job(f.config, f.directory)
    cleanup = []

    def execute(sw, config, publish):
        publish({"status": "in_native_call", "mutation_attempted": True})
        assert f.held["value"] is True
        response = jobs.request_observation_stop(f.directory, acknowledge_native_not_cancelled=True)
        assert response["status"] == "stop_requested"
        assert publish.stop_observation_requested() is True
        cleanup.append("algorithm_unadvise")
        return {"status": "uncertain", "observation_stopped": True, "native_cancelled": False,
                "may_continue": True, "messages": {"disconnected": True}}

    def uninitialize():
        assert f.held["value"] is False
        assert f.events[-1][0] == "lock_exit"
        cleanup.append("apartment_uninitialize")

    f.execute.side_effect = execute
    f.com.CoUninitialize.side_effect = uninitialize
    assert jobs._worker(f.directory) == 1
    state = read_json(f.directory / "state.json")
    assert state["status"] == "uncertain" and state["finished"] is True
    assert state["observation_stopped"] is True and state["native_cancelled"] is False
    assert state["may_continue"] is False
    assert state["messages"]["disconnected"] is True
    assert state["completed_at"]
    assert cleanup == ["algorithm_unadvise", "apartment_uninitialize"]
    observed = jobs.inspect_job(f.directory)
    assert observed["observation_status"] == "finished" and observed["may_continue"] is False


@pytest.mark.parametrize("command_case", ["missing", "wrong_job", "numeric_ack", "false_ack"])
def test_uncertain_algorithm_result_without_valid_stop_is_not_terminal(environment, command_case):
    f = environment
    jobs.start_job(f.config, f.directory)
    job_id = read_json(f.directory / "request.json")["job_id"]

    def execute(sw, config, publish):
        publish({"status": "in_native_call", "mutation_attempted": True})
        if command_case != "missing":
            command = {"job_id": "another" if command_case == "wrong_job" else job_id,
                       "acknowledge_native_not_cancelled":
                       1 if command_case == "numeric_ack" else command_case != "false_ack"}
            write_json(f.directory / "stop_observation.json", command)
        return {"status": "uncertain", "observation_stopped": True, "may_continue": True}

    f.execute.side_effect = execute
    assert jobs._worker(f.directory) == 1
    state = read_json(f.directory / "state.json")
    assert state["status"] == "uncertain" and state["finished"] is False
    assert state["may_continue"] is False
    assert "completed_at" not in state
    assert f.held["value"] is False
    f.com.CoUninitialize.assert_called_once_with()
