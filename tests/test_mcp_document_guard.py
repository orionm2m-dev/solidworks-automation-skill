"""文档目标检查与跨进程互斥的回归测试，无需启动 SOLIDWORKS。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp-server"))
import server
from scripts.sw_operation_guard import (
    SolidWorksDocumentMismatch, check_document_target, solidworks_operation_lock,
)


class DocumentTargetTests(unittest.TestCase):
    """确认错误文档在任何写入前被拒绝。"""

    def test_same_name_different_directory_is_rejected(self):
        with self.assertRaises(SolidWorksDocumentMismatch):
            check_document_target(r"C:\other\part.sldprt", "part.sldprt", expected_path=r"C:\job\part.sldprt")

    def test_windows_case_and_separator_are_normalized(self):
        check_document_target(r"C:\job\PART.SLDPRT", "PART.SLDPRT", expected_path="c:/job/part.sldprt")

    def test_unsaved_document_needs_exact_title(self):
        check_document_target("", "Part1", expected_title="Part1", required=True)
        with self.assertRaises(SolidWorksDocumentMismatch):
            check_document_target("", "Part2", expected_title="Part1")

    def test_title_does_not_authorize_a_saved_document(self):
        with self.assertRaises(SolidWorksDocumentMismatch):
            check_document_target(r"C:\other\Part1.sldprt", "Part1.sldprt", expected_title="Part1.sldprt")

    def test_strict_mode_rejects_missing_target(self):
        with self.assertRaises(SolidWorksDocumentMismatch):
            check_document_target(r"C:\job\part.sldprt", "part.sldprt", required=True)

    def test_legacy_mode_remains_compatible(self):
        check_document_target(r"C:\job\part.sldprt", "part.sldprt")

    def test_relative_and_blank_paths_are_rejected(self):
        for path in ["part.sldprt", "C:part.sldprt", "", "   "]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                server.SolidWorksSetAppearanceInput(color="#123456", expected_document_path=path)

    def test_appearance_mismatch_does_not_write_or_rebuild(self):
        model = SimpleNamespace(GetPathName=r"C:\other\part.sldprt", GetTitle="part.sldprt", ForceRebuild3=Mock())
        sw = SimpleNamespace(ActiveDoc=model)
        writer = Mock()
        with patch.object(server, "_load_automation_modules"), patch.object(server, "_coinitialize"), \
             patch.object(server, "connect_solidworks", return_value=(sw, model), create=True), \
             patch.object(server, "get_com_member", side_effect=lambda obj, name: getattr(obj, name), create=True), \
             patch.object(server, "set_document_appearance", writer, create=True):
            result = json.loads(server.solidworks_set_appearance(server.SolidWorksSetAppearanceInput(
                color="#123456", expected_document_path=r"C:\job\part.sldprt")))
        self.assertEqual(result["error_code"], "SW_DOCUMENT_MISMATCH")
        writer.assert_not_called()
        model.ForceRebuild3.assert_not_called()

    def test_strict_server_mode_blocks_unscoped_write(self):
        model = SimpleNamespace(GetPathName=r"C:\other\part.sldprt", GetTitle="part.sldprt", ForceRebuild3=Mock())
        with patch.dict(os.environ, {"SOLIDWORKS_MCP_REQUIRE_DOCUMENT_TARGET": "1"}), \
             patch.object(server, "_load_automation_modules"), patch.object(server, "_coinitialize"), \
             patch.object(server, "connect_solidworks", return_value=(SimpleNamespace(ActiveDoc=model), model), create=True), \
             patch.object(server, "get_com_member", side_effect=lambda obj, name: getattr(obj, name), create=True), \
             patch.object(server, "set_document_appearance", create=True) as writer:
            result = json.loads(server.solidworks_set_appearance(server.SolidWorksSetAppearanceInput(color="#123456")))
        self.assertEqual(result["error_code"], "SW_DOCUMENT_MISMATCH")
        writer.assert_not_called()

    def test_matching_path_writes_the_checked_document(self):
        model = SimpleNamespace(GetPathName=r"C:\job\part.sldprt", GetTitle="part.sldprt", GetType=1, ForceRebuild3=Mock())
        with patch.object(server, "_load_automation_modules"), patch.object(server, "_coinitialize"), \
             patch.object(server, "connect_solidworks", return_value=(SimpleNamespace(ActiveDoc=model), model), create=True), \
             patch.object(server, "get_com_member", side_effect=lambda obj, name: getattr(obj, name), create=True), \
             patch.object(server, "set_document_appearance", return_value=True, create=True) as writer:
            result = json.loads(server.solidworks_set_appearance(server.SolidWorksSetAppearanceInput(
                color="#123456", expected_document_path=model.GetPathName)))
        self.assertEqual(result["status"], "ok")
        writer.assert_called_once_with(model, "#123456")
        model.ForceRebuild3.assert_called_once_with(False)

    def test_active_doc_does_not_fall_back_to_stale_connection_result(self):
        with patch.object(server, "connect_solidworks", return_value=(SimpleNamespace(ActiveDoc=None), object()), create=True), \
             patch.object(server, "get_com_member", side_effect=lambda obj, name: getattr(obj, name), create=True):
            with self.assertRaisesRegex(RuntimeError, "No active"):
                server._active_model_required()

    def test_guarded_tool_schemas_expose_targets(self):
        for name in ["solidworks_set_appearance", "solidworks_export_active", "solidworks_save_document", "solidworks_fillet", "solidworks_add_concentric_mate"]:
            schema = server.mcp._tool_manager._tools[name].parameters
            definitions = json.dumps(schema)
            self.assertIn("expected_document_path", definitions, name)
            self.assertIn("expected_document_title", definitions, name)

    def test_single_target_cannot_close_all_documents(self):
        sw = SimpleNamespace(CloseAllDocuments=Mock())
        with patch.object(server, "_load_automation_modules"), patch.object(server, "_coinitialize"), \
             patch.object(server, "_active_model_required", return_value=(sw, object())):
            result = json.loads(server.solidworks_close_documents(server.SolidWorksCloseDocumentsInput(
                close_all=True, expected_document_path=r"C:\job\part.sldprt")))
        self.assertEqual(result["status"], "error")
        sw.CloseAllDocuments.assert_not_called()

    def test_explicit_native_open_activates_requested_document(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.sldprt"
            path.touch()
            sw, model = object(), object()
            with patch.object(server, "_load_automation_modules"), patch.object(server, "_coinitialize"), \
                 patch.object(server, "connect_solidworks", return_value=(sw, None), create=True), \
                 patch.object(server, "open_document", return_value=model, create=True), \
                 patch.object(server, "activate_source_document", return_value=model, create=True) as activate, \
                 patch.object(server, "_model_summary", return_value={"path": str(path)}):
                result = json.loads(server.solidworks_open_document(server.SolidWorksOpenDocumentInput(path=str(path))))
        self.assertEqual(result["status"], "ok")
        activate.assert_called_once_with(sw, model, str(path))

    def test_no_cad_operations_skip_desktop_lock(self):
        with patch.object(server, "_coinitialize"), patch.object(server, "solidworks_operation_lock") as lock:
            value = json.loads(server._run_locked(lambda: {"status": "ok"}, server.ResponseFormat.JSON, load_automation=False))
        lock.assert_not_called()
        self.assertEqual(value["status"], "ok")


@unittest.skipUnless(os.name == "nt", "Windows named mutex")
class OperationLockTests(unittest.TestCase):
    """用真实 Windows 内核对象验证进程间互斥和异常释放。"""

    def test_other_process_waits_then_can_acquire(self):
        name = r"Local\SolidWorksAutomation.Test." + uuid.uuid4().hex
        code = (
            "from scripts.sw_operation_guard import solidworks_operation_lock\n"
            "import sys\n"
            "with solidworks_operation_lock(2, name=sys.argv[1]):\n"
            " print('locked', flush=True)\n"
            " sys.stdin.readline()\n"
        )
        child = subprocess.Popen([sys.executable, "-c", code, name], cwd=ROOT,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            with self.assertRaises(TimeoutError):
                with solidworks_operation_lock(0.05, name=name):
                    self.fail("Another process already owns the mutex")
        finally:
            child.communicate("release\n", timeout=10)
        self.assertEqual(child.returncode, 0)
        with solidworks_operation_lock(0.5, name=name):
            pass

    def test_exception_releases_lock(self):
        name = r"Local\SolidWorksAutomation.Test." + uuid.uuid4().hex
        with self.assertRaises(ValueError):
            with solidworks_operation_lock(0.1, name=name):
                raise ValueError("test")
        with solidworks_operation_lock(0.1, name=name):
            pass


if __name__ == "__main__":
    unittest.main()