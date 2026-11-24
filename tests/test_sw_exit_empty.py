"""solidworks_exit_empty_session：квитанция запуска и пустота процесса на поддельных COM-объектах."""
import json

import pytest

from scripts import sw_exit_empty as m

EXE = r"C:\SOLIDWORKS\SLDWORKS.exe"


class FakeSw:
    def __init__(self, pid=123, docs=(), count=0, active=None, count_error=None):
        self.pid, self.docs, self.count, self.active, self.count_error = pid, list(docs), count, active, count_error
        self.exit_calls = 0

    def GetProcessID(self):
        return self.pid

    def GetDocuments(self):
        return self.docs

    def GetDocumentCount(self):
        if self.count_error:
            raise self.count_error
        return self.count

    @property
    def ActiveDoc(self):
        return self.active

    def ExitApp(self):
        self.exit_calls += 1


class FakeKernel:
    def __init__(self, rc=0):
        self.rc, self.closed = rc, False

    def WaitForSingleObject(self, _handle, _ms):
        return self.rc

    def CloseHandle(self, _handle):
        self.closed = True


@pytest.fixture
def kernel(monkeypatch):
    k = FakeKernel()
    monkeypatch.setattr(m, "_open_handle", lambda pid: (k, 1))
    return k


def receipt(tmp_path, **change):
    data = dict(status="ok", launch_mode="executable", new_process_verified=True, process_id=123,
                process_identity=dict(process_id=123, create_time=1700000000.0, executable=EXE, alive=True))
    data.update(change)
    path = tmp_path / "launch.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def identity(create_time=1700000000.0, executable=EXE, alive=True):
    return lambda pid: dict(process_id=pid, create_time=create_time, executable=executable, alive=alive)


def test_exits_once_when_receipt_matches_and_process_is_empty(tmp_path, kernel):
    sw = FakeSw()
    r = m.exit_empty_session(sw, 123, wait_seconds=5, startup_receipt_path=receipt(tmp_path), identity=identity())
    assert r["status"] == "exited" and r["process_exit_verified"] is True
    assert r["receipt_verified"] is True and r["exit_call_count"] == 1 and sw.exit_calls == 1
    assert kernel.closed is True


def test_exit_without_receipt_is_reported_as_unverified(kernel):
    r = m.exit_empty_session(FakeSw(), 123, wait_seconds=5)
    assert r["status"] == "exited" and r["receipt_verified"] is False


@pytest.mark.parametrize("change, message", [
    (dict(process_id=124), "differs"),
    (dict(launch_mode="com"), "not a verified executable launch"),
    (dict(new_process_verified=False), "not a verified executable launch"),
    (dict(status="error"), "not a verified executable launch"),
])
def test_receipt_contents_are_checked(tmp_path, kernel, change, message):
    sw = FakeSw()
    with pytest.raises(RuntimeError, match=message):
        m.exit_empty_session(sw, 123, startup_receipt_path=receipt(tmp_path, **change), identity=identity())
    assert sw.exit_calls == 0


@pytest.mark.parametrize("live, message", [
    (identity(create_time=1700000500.0), "PID reused"),
    (identity(executable=r"C:\Other\SLDWORKS.exe"), "differs from the receipt"),
    (identity(alive=False), "not alive"),
])
def test_live_process_must_match_receipt(tmp_path, kernel, live, message):
    sw = FakeSw()
    with pytest.raises(RuntimeError, match=message):
        m.exit_empty_session(sw, 123, startup_receipt_path=receipt(tmp_path), identity=live)
    assert sw.exit_calls == 0


def test_hidden_documents_counted_by_document_count_refuse_exit(kernel):
    sw = FakeSw(count=1)
    r = m.exit_empty_session(sw, 123)
    assert r["status"] == "refused" and r["document_count"] == 1 and sw.exit_calls == 0


def test_unknown_document_count_refuses_exit(kernel):
    sw = FakeSw(count_error=RuntimeError("COM down"))
    r = m.exit_empty_session(sw, 123)
    assert r["status"] == "refused" and "unavailable" in r["reason"] and sw.exit_calls == 0


def test_connected_pid_must_match_request(kernel):
    with pytest.raises(RuntimeError, match="differs from requested"):
        m.exit_empty_session(FakeSw(pid=999), 123)


def test_exit_not_observed_is_not_retried(monkeypatch):
    k = FakeKernel(rc=258)  # WAIT_TIMEOUT
    monkeypatch.setattr(m, "_open_handle", lambda pid: (k, 1))
    sw = FakeSw()
    r = m.exit_empty_session(sw, 123, wait_seconds=5)
    assert r["status"] == "exit_not_observed" and sw.exit_calls == 1 and r["process_exit_verified"] is False
