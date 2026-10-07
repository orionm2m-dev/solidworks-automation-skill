"""验证 MCP 进程绑定、失败保留和工具路由，不访问真实 CAD。"""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))
import server
from scripts.sw_operation_guard import OPERATION_MUTEX_NAME, solidworks_operation_mutex_name


def member(obj, name, *args):
    value = getattr(obj, name)
    return value(*args) if callable(value) else value


class McpProcessTargetTests(unittest.TestCase):
    def setUp(self):
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ))
        os.environ.pop("SOLIDWORKS_MCP_PROCESS_ID", None)
        self.stack.enter_context(patch.object(server, "_selected_process_id", None))
        self.stack.enter_context(patch.object(server, "_load_automation_modules"))
        self.stack.enter_context(patch.object(server, "_coinitialize"))
        self.stack.enter_context(patch.object(server, "get_com_member", side_effect=member, create=True))

    def app(self, pid, model=None):
        return SimpleNamespace(GetProcessID=pid, RevisionNumber="34.4.1", ActiveDoc=model)

    def test_explicit_connection_pins_later_tools_and_children(self):
        sw = self.app(1234)
        with patch.object(server, "_connect_solidworks_backend", return_value=(sw, None), create=True) as backend:
            answer = json.loads(server.solidworks_connect(server.SolidWorksConnectInput(process_id=1234)))
            self.assertEqual(answer["session_target"], {"process_id": 1234, "scope": "mcp_server", "strict": True})
            self.assertEqual(os.environ["SOLIDWORKS_MCP_PROCESS_ID"], "1234")
            server.connect_solidworks(wait_seconds=1)
        self.assertEqual(backend.call_args.kwargs["process_id"], 1234)

    def test_default_connection_pins_returned_pid(self):
        with patch.object(server, "_connect_solidworks_backend", return_value=(self.app(1234), None), create=True):
            server.connect_solidworks()
        self.assertEqual(server._selected_process_id, 1234)

    def test_failed_rebind_keeps_previous_target(self):
        server._selected_process_id = 1234
        os.environ["SOLIDWORKS_MCP_PROCESS_ID"] = "1234"
        with patch.object(server, "_connect_solidworks_backend", side_effect=RuntimeError("target unavailable"), create=True):
            answer = json.loads(server.solidworks_connect(server.SolidWorksConnectInput(process_id=9999)))
        self.assertEqual(answer["status"], "error")
        self.assertEqual(server._selected_process_id, 1234)
        self.assertEqual(os.environ["SOLIDWORKS_MCP_PROCESS_ID"], "1234")

    def test_incorrect_backend_pid_is_rejected_before_binding(self):
        with patch.object(server, "_connect_solidworks_backend", return_value=(self.app(4321), None), create=True):
            answer = json.loads(server.solidworks_connect(server.SolidWorksConnectInput(process_id=1234)))
        self.assertEqual(answer["status"], "error")
        self.assertIsNone(server._selected_process_id)
        self.assertNotIn("SOLIDWORKS_MCP_PROCESS_ID", os.environ)

    def test_document_guard_runs_inside_selected_process(self):
        wrong = SimpleNamespace(GetPathName=r"C:\other\part.sldprt", GetTitle="part.sldprt", GetType=1, ForceRebuild3=Mock())
        server._selected_process_id = 1234
        with patch.object(server, "_connect_solidworks_backend", return_value=(self.app(1234, wrong), wrong), create=True) as backend, \
             patch.object(server, "set_document_appearance", create=True) as writer:
            answer = json.loads(server.solidworks_set_appearance(server.SolidWorksSetAppearanceInput(color="#123456", expected_document_path=r"C:\job\part.sldprt")))
        self.assertEqual(answer["error_code"], "SW_DOCUMENT_MISMATCH")
        self.assertEqual(backend.call_args.kwargs["process_id"], 1234)
        writer.assert_not_called()
        wrong.ForceRebuild3.assert_not_called()

    def test_other_tool_result_reports_selected_pid(self):
        server._selected_process_id = 1234
        answer = json.loads(server._run_locked(lambda: {"status": "ok"}, server.ResponseFormat.JSON))
        self.assertEqual(answer["process_id"], 1234)

    def test_native_tool_lock_is_scoped_to_selected_pid(self):
        server._selected_process_id = 1234
        with patch.object(server, "solidworks_operation_lock") as lock:
            answer = json.loads(server._run_locked(lambda: {"status": "ok"}, server.ResponseFormat.JSON))
        self.assertEqual(answer["status"], "ok")
        lock.assert_called_once_with(300.0, process_id=1234)

    def test_listing_does_not_change_binding_or_connect(self):
        server._selected_process_id = 1234
        with patch.object(server, "_list_solidworks_instances_backend", return_value=[{"process_id": 1234}, {"process_id": 5678}], create=True), \
             patch.object(server, "_connect_solidworks_backend", create=True) as connect:
            answer = json.loads(server.solidworks_list_instances())
        self.assertEqual(len(answer["instances"]), 2)
        self.assertEqual(answer["selected_process_id"], 1234)
        connect.assert_not_called()

    def test_pid_schema_rejects_coercions(self):
        for value in [0, -1, True, 12.5, "1234"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.SolidWorksConnectInput(process_id=value)

    def test_operation_mutex_is_process_scoped(self):
        self.assertEqual(solidworks_operation_mutex_name(1234), r"Local\SolidWorksAutomation.Operation.v1.PID.1234")
        self.assertEqual(solidworks_operation_mutex_name(5678), r"Local\SolidWorksAutomation.Operation.v1.PID.5678")
        self.assertEqual(solidworks_operation_mutex_name(), OPERATION_MUTEX_NAME)
        with patch.dict(os.environ, {"SOLIDWORKS_MCP_PROCESS_ID": "5678"}):
            self.assertEqual(solidworks_operation_mutex_name(), r"Local\SolidWorksAutomation.Operation.v1.PID.5678")
        for value in ["0", "-1", "12.5", " 1234", "１２３４"]:
            with self.subTest(value=value), patch.dict(os.environ, {"SOLIDWORKS_MCP_PROCESS_ID": value}):
                with self.assertRaises(ValueError):
                    solidworks_operation_mutex_name()

    def test_recovery_does_not_close_unbound_windows(self):
        with patch.object(server, "_enumerate_solidworks_windows") as windows:
            answer = json.loads(server.solidworks_recover(server.SolidWorksRecoverInput(dismiss_dialogs=True)))
        self.assertEqual(answer["status"], "error")
        windows.assert_not_called()

    def test_invalid_recovery_pid_never_enumerates_windows(self):
        for value in ["", "0", "0012", "-2", " 1234", "１２３４", "١٢٣٤"]:
            with self.subTest(value=value), patch.dict(os.environ, {"SOLIDWORKS_MCP_PROCESS_ID": value}), \
                 patch.object(server, "_enumerate_solidworks_windows") as windows:
                answer = json.loads(server.solidworks_recover(server.SolidWorksRecoverInput(dismiss_dialogs=True)))
                self.assertEqual(answer["status"], "error")
                windows.assert_not_called()

    def test_health_check_requests_desktop_lock_only_for_live_probe(self):
        for live in [False, True]:
            with self.subTest(live=live), patch.object(server, "_run_locked") as run:
                server.solidworks_health_check(server.SolidWorksHealthCheckInput(start_solidworks=live))
                self.assertEqual(run.call_args.kwargs["desktop_guard"], live)

    def test_recovery_requests_desktop_lock(self):
        with patch.object(server, "_run_locked") as run:
            server.solidworks_recover(server.SolidWorksRecoverInput())
        self.assertTrue(run.call_args.kwargs["desktop_guard"])

    def test_window_diagnostics_filter_pid(self):
        gui = SimpleNamespace(IsWindowVisible=lambda h: True, GetWindowText=lambda h: "SOLIDWORKS prompt", GetClassName=lambda h: "#32770", EnumWindows=lambda fn, arg: [fn(h, arg) for h in [1, 2]])
        process = SimpleNamespace(GetWindowThreadProcessId=lambda h: (42, 1234 if h == 1 else 5678))
        with patch.dict(sys.modules, {"win32gui": gui, "win32process": process}):
            _main, dialogs, error = server._enumerate_solidworks_windows(1234)
        self.assertIsNone(error)
        self.assertEqual([d["handle"] for d in dialogs], [1])


if __name__ == "__main__":
    unittest.main()
