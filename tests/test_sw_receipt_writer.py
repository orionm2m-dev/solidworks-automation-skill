"""Receipt publication failures must not overwrite evidence or replay native work."""
import errno
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_generation as generation
from test_sw_native_transfer import graph  # Reuse offline native-operation fixture.


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=0.0, waits=[])
    def sleep(delay):
        state.waits.append(delay)
        state.now += delay
    monkeypatch.setattr(generation.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(generation.time, "sleep", sleep)
    return state


def pending(path):
    return list(path.parent.glob(path.name + ".*.tmp"))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_create_remains_exclusive(tmp_path):
    path = tmp_path / "receipt.json"
    generation._write_receipt(path, {"phase": "entered"}, create=True)
    with pytest.raises(FileExistsError):
        generation._write_receipt(path, {"phase": "other"}, create=True)
    assert read(path) == {"phase": "entered"}
    assert not pending(path)


def test_transient_replace_retries_same_durable_file(tmp_path, monkeypatch, clock):
    path = tmp_path / "receipt.json"
    generation._write_receipt(path, {"phase": "before"}, create=True)
    legacy = path.with_name(path.name + ".tmp")
    legacy.write_bytes(b"prior failure evidence")
    original = generation.os.replace
    calls = []
    fsync = Mock(wraps=generation.os.fsync)
    monkeypatch.setattr(generation.os, "fsync", fsync)
    def replace(source, target):
        calls.append(Path(source))
        assert Path(source).parent == path.parent
        assert read(source) == {"phase": "returned", "note": "Сохранено"}
        if len(calls) < 3:
            assert read(target) == {"phase": "before"}
            raise PermissionError(errno.EACCES, "sharing denied")
        return original(source, target)
    monkeypatch.setattr(generation.os, "replace", replace)
    generation._write_receipt(path, {"phase": "returned", "note": "Сохранено"})
    assert len(calls) == 3 and len(set(calls)) == 1
    assert read(path)["phase"] == "returned"
    assert fsync.call_count == 1
    assert clock.waits == [0.025, 0.05]
    assert legacy.read_bytes() == b"prior failure evidence"
    assert not pending(path)


def test_permanent_permission_error_keeps_old_and_unique_pending(tmp_path, monkeypatch, clock):
    path = tmp_path / "receipt.json"
    generation._write_receipt(path, {"phase": "before"}, create=True)
    original = generation.os.replace
    failure = PermissionError(errno.EACCES, "sharing denied")
    replace = Mock(side_effect=failure)
    monkeypatch.setattr(generation.os, "replace", replace)
    with pytest.raises(PermissionError) as raised:
        generation._write_receipt(path, {"phase": "native_returned"})
    assert raised.value is failure
    assert 1 < replace.call_count <= 8
    assert sum(clock.waits) <= 1.5
    assert read(path) == {"phase": "before"}
    saved = pending(path)
    assert len(saved) == 1 and read(saved[0]) == {"phase": "native_returned"}
    monkeypatch.setattr(generation.os, "replace", original)
    generation._write_receipt(path, {"phase": "uncertain"})
    assert read(path) == {"phase": "uncertain"}
    assert pending(path) == saved
    assert read(saved[0]) == {"phase": "native_returned"}


def test_other_os_error_is_not_retried(tmp_path, monkeypatch, clock):
    path = tmp_path / "receipt.json"
    generation._write_receipt(path, {"phase": "before"}, create=True)
    failure = OSError(errno.EIO, "disk I/O failed")
    replace = Mock(side_effect=failure)
    monkeypatch.setattr(generation.os, "replace", replace)
    with pytest.raises(OSError) as raised:
        generation._write_receipt(path, {"phase": "native_returned"})
    assert raised.value is failure
    assert replace.call_count == 1 and not clock.waits
    assert read(path) == {"phase": "before"}
    assert len(pending(path)) == 1


def test_invalid_report_does_not_publish_or_create_pending(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    generation._write_receipt(path, {"phase": "before"}, create=True)
    replace = Mock()
    monkeypatch.setattr(generation.os, "replace", replace)
    with pytest.raises(ValueError):
        generation._write_receipt(path, {"value": float("nan")})
    assert read(path) == {"phase": "before"}
    assert not pending(path) and not replace.called


def test_transient_receipt_failure_after_save_never_repeats_save(graph, monkeypatch, clock):
    original = generation.os.replace
    refused = []
    def replace(source, target):
        if read(source).get("phase") == "Save3_returned" and len(refused) < 2:
            refused.append(str(source))
            raise PermissionError(errno.EACCES, "sharing denied after Save3")
        return original(source, target)
    monkeypatch.setattr(generation.os, "replace", replace)
    result = graph.apply()
    assert result["body_transfer_verified"] and result["reopened_verified"], result
    assert graph.state["calls"] == ["insert", "delete", "save", "export"]
    assert len(refused) == 2 and len(set(refused)) == 1
    assert not pending(graph.receipt)


def test_persistent_receipt_failure_stops_native_sequence_and_retains_returned_state(
        graph, monkeypatch, clock):
    original = generation.os.replace
    failed = {"started": False}
    def replace(source, target):
        if read(source).get("phase") == "Save3_returned":
            failed["started"] = True
        if failed["started"]:
            raise PermissionError(errno.EACCES, "persistent sharing denial")
        return original(source, target)
    monkeypatch.setattr(generation.os, "replace", replace)
    result = graph.apply()
    assert result["status"] == "uncertain" and not result["may_continue"]
    assert graph.state["calls"] == ["insert", "delete", "save"]
    assert result["issue"]["type"] == "PermissionError"
    assert result["receipt_write_error"]["type"] == "PermissionError"
    evidence = [read(path) for path in pending(graph.receipt)]
    assert len(evidence) == 2
    assert {entry["phase"] for entry in evidence} == {"Save3_returned", "finished"}
    assert all(next(call for call in entry["native_calls"]
                    if call["name"] == "Save3")["returned"] for entry in evidence)
    calls_before = list(graph.state["calls"])
    rerun = graph.run(action="apply", expected_state_sha256="0" * 64,
                      receipt_path=str(graph.receipt))
    assert not rerun["mutation_attempted"]
    assert graph.state["calls"] == calls_before