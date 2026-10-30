"""取消路径只模拟进程对象和 taskkill；不终止实际进程。"""
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
import pytest
from apps.desktop.cad_workbench import queue_worker as worker


def test_windows_localized_taskkill_output_is_kept_as_bytes(monkeypatch):
    process = SimpleNamespace(pid=731, poll=Mock(return_value=None), wait=Mock(), kill=Mock())
    monkeypatch.setattr(worker, 'os', SimpleNamespace(name='nt'))
    def run(command, **kwargs):
        assert command == ['taskkill', '/PID', '731', '/T', '/F']
        assert kwargs == {'capture_output': True, 'check': False}
        return subprocess.CompletedProcess(command, 0, stdout=b'\x93\x94', stderr=b'\xff')
    command = Mock(side_effect=run)
    monkeypatch.setattr(worker.subprocess, 'run', command)
    worker.terminate_process(process)
    command.assert_called_once()
    process.wait.assert_called_once_with(timeout=3)
    process.kill.assert_not_called()


def test_already_exited_process_never_dispatches_taskkill(monkeypatch):
    process = SimpleNamespace(pid=731, poll=Mock(return_value=0), wait=Mock(), kill=Mock())
    command = Mock(side_effect=AssertionError('must not terminate an exited process'))
    monkeypatch.setattr(worker.subprocess, 'run', command)
    worker.terminate_process(process)
    command.assert_not_called()
    process.wait.assert_not_called()
    process.kill.assert_not_called()
