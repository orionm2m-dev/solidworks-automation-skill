"""验证预览与装配辅助连接不能越过 PID 绑定；不访问真实 COM。"""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import sw_assembly, sw_review


class FakeModel:
    """模拟同名、同路径但可能属于不同应用的文档。"""
    def __init__(self, path=r"C:\selected\part.sldprt", title="part.sldprt"):
        self.path = path
        self.title = title

    def GetTitle(self):
        return self.title

    def GetPathName(self):
        return self.path


def bound_preview(monkeypatch, documents, active):
    """建立严格进程目标并禁止使用默认 COM 活动对象。"""
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "1234")
    app = SimpleNamespace(GetDocuments=lambda: documents, ActiveDoc=active)
    app.ActivateDoc3 = Mock(return_value=active)
    app.ActivateDoc2 = Mock()
    connect = Mock(return_value=(app, active))
    global_connect = Mock(side_effect=AssertionError("不能连接默认实例"))
    monkeypatch.setattr(sw_review, "connect_solidworks", connect)
    monkeypatch.setattr(sw_review._win32com, "GetActiveObject", global_connect)
    return app, connect, global_connect


def test_bound_preview_activates_full_path_in_selected_process(monkeypatch):
    model = FakeModel()
    app, connect, default = bound_preview(monkeypatch, [model], model)
    assert sw_review.activate_model_for_preview(model) is True
    assert app.ActivateDoc3.call_args.args[0] == model.path
    connect.assert_called_once_with(visible=False)
    default.assert_not_called()


@pytest.mark.parametrize("foreign_path", [r"C:\other\part.sldprt", r"C:\selected\part.sldprt", ""])
def test_bound_preview_rejects_foreign_document_before_activation(monkeypatch, foreign_path):
    local = FakeModel()
    foreign = FakeModel(foreign_path)
    app, _, default = bound_preview(monkeypatch, [local], local)
    with pytest.raises(RuntimeError, match="不属于"):
        sw_review.activate_model_for_preview(foreign)
    app.ActivateDoc3.assert_not_called()
    app.ActivateDoc2.assert_not_called()
    default.assert_not_called()


def test_bound_preview_accepts_second_wrapper_of_same_com_identity(monkeypatch):
    model, local = FakeModel(), FakeModel()
    canonical = object()
    model._oleobj_ = SimpleNamespace(QueryInterface=Mock(return_value=canonical))
    local._oleobj_ = SimpleNamespace(QueryInterface=Mock(return_value=canonical))
    app, _, _ = bound_preview(monkeypatch, [local], local)
    assert sw_review.activate_model_for_preview(model) is True
    app.ActivateDoc3.assert_called_once()


def test_bound_preview_handles_unsaved_document_by_confirmed_identity(monkeypatch):
    model = FakeModel("", "Part1")
    app, _, _ = bound_preview(monkeypatch, [model], model)
    assert sw_review.activate_model_for_preview(model) is True
    assert app.ActivateDoc3.call_args.args[0] == "Part1"


def test_bound_preview_checks_activation_result(monkeypatch):
    model, other = FakeModel(), FakeModel(r"C:\other\part.sldprt")
    app, _, _ = bound_preview(monkeypatch, [model], other)
    with pytest.raises(RuntimeError, match="激活结果"):
        sw_review.activate_model_for_preview(model)
    app.ActivateDoc3.assert_called_once()


def test_bound_preview_fallback_stays_in_same_application(monkeypatch):
    model = FakeModel()
    app, _, default = bound_preview(monkeypatch, [model], model)
    app.ActivateDoc3.side_effect = RuntimeError("旧版激活接口")
    assert sw_review.activate_model_for_preview(model) is True
    assert app.ActivateDoc2.call_args.args[0] == model.path
    default.assert_not_called()


def test_bound_preview_connection_failure_never_uses_default(monkeypatch):
    model = FakeModel()
    app, connect, default = bound_preview(monkeypatch, [model], model)
    connect.side_effect = RuntimeError("所选实例已退出")
    with pytest.raises(RuntimeError, match="实例已退出"):
        sw_review.activate_model_for_preview(model)
    app.ActivateDoc3.assert_not_called()
    default.assert_not_called()


def test_unbound_preview_preserves_legacy_title_activation(monkeypatch):
    monkeypatch.delenv("SOLIDWORKS_MCP_PROCESS_ID", raising=False)
    model = FakeModel()
    app = SimpleNamespace(ActivateDoc3=Mock(return_value=model))
    default = Mock(return_value=app)
    bound = Mock(side_effect=AssertionError("不应使用绑定接口"))
    monkeypatch.setattr(sw_review._win32com, "GetActiveObject", default)
    monkeypatch.setattr(sw_review, "connect_solidworks", bound)
    assert sw_review.activate_model_for_preview(model) is True
    assert app.ActivateDoc3.call_args.args[0] == model.title
    default.assert_called_once_with("SldWorks.Application")
    bound.assert_not_called()


def test_assembly_fallback_uses_bound_connector(monkeypatch):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "1234")
    app = object()
    bound = Mock(return_value=(app, None))
    default = Mock(side_effect=AssertionError("不能连接默认实例"))
    monkeypatch.setattr(sw_assembly, "connect_solidworks", bound)
    monkeypatch.setattr(sw_assembly._win32com, "GetActiveObject", default)
    assert sw_assembly._active_solidworks_app() is app
    bound.assert_called_once_with(visible=False)
    default.assert_not_called()


def test_assembly_missing_bound_instance_does_not_fallback(monkeypatch):
    monkeypatch.setenv("SOLIDWORKS_MCP_PROCESS_ID", "1234")
    monkeypatch.setattr(sw_assembly, "connect_solidworks", Mock(side_effect=RuntimeError("所选实例已退出")))
    default = Mock()
    monkeypatch.setattr(sw_assembly._win32com, "GetActiveObject", default)
    with pytest.raises(RuntimeError, match="实例已退出"):
        sw_assembly._active_solidworks_app()
    default.assert_not_called()


def test_assembly_unbound_legacy_missing_app_returns_none(monkeypatch):
    monkeypatch.delenv("SOLIDWORKS_MCP_PROCESS_ID", raising=False)
    default = Mock(side_effect=RuntimeError("没有活动实例"))
    bound = Mock()
    monkeypatch.setattr(sw_assembly._win32com, "GetActiveObject", default)
    monkeypatch.setattr(sw_assembly, "connect_solidworks", bound)
    assert sw_assembly._active_solidworks_app() is None
    default.assert_called_once_with("SldWorks.Application")
    bound.assert_not_called()
