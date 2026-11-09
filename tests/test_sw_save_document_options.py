"""@brief 文档保存选项：静默保存与"同时保存引用文档"位掩码（假对象，不连接 SolidWorks）。"""

import pytest

sw_connect = pytest.importorskip("scripts.sw_connect", reason="需要 pywin32 才能导入 COM 连接模块")


class RecordingExtension:
    """@brief 记录 SaveAs 的路径与选项。"""

    def __init__(self):
        self.calls = []

    def SaveAs(self, path, version, options, export_data, errors, warnings):
        self.calls.append((path, version, options))
        return True


class RecordingModel:
    """@brief 记录 Save3 选项的假模型。"""

    def __init__(self):
        self.save3_options = []
        self.Extension = RecordingExtension()

    def Save3(self, options, errors, warnings):
        self.save3_options.append(options)
        return True

    def GetPathName(self):
        return "C:/models/top.SLDASM"


def test_save_in_place_is_silent_by_default() -> None:
    model = RecordingModel()

    assert sw_connect.save_document(model) is True
    assert model.save3_options == [1]


def test_save_in_place_can_include_referenced_documents() -> None:
    model = RecordingModel()

    assert sw_connect.save_document(model, save_referenced=True) is True
    assert model.save3_options == [1 | 4]


def test_save_as_passes_the_same_options(tmp_path) -> None:
    model = RecordingModel()
    target = str(tmp_path / "copy.SLDASM")

    assert sw_connect.save_document(model, target, save_referenced=True) is True
    assert model.save3_options == []
    assert model.Extension.calls == [(target, 0, 5)]
