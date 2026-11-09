"""@brief 范围内关闭全部文档：越界、未保存、从未存盘即拒绝，关闭后必须回读为空（假对象，不连接 SolidWorks）。"""

import pytest

sw_connect = pytest.importorskip("scripts.sw_connect", reason="需要 pywin32 才能导入 COM 连接模块")


class FakeDocument:
    """@brief 只提供路径、标题与保存标记的假文档。"""

    def __init__(self, path, title=None, needs_save=False):
        self._path = path
        self._title = title or (path.rsplit("\\", 1)[-1] if path else "Assem1")
        self._needs_save = needs_save

    def GetPathName(self):
        return self._path

    def GetTitle(self):
        return self._title

    def GetSaveFlag(self):
        return self._needs_save


class FakeSolidWorks:
    """@brief 记录 CloseAllDocuments 参数；默认关闭后文档列表为空。"""

    def __init__(self, documents, keep_open_after_close=False):
        self.documents = list(documents)
        self.close_calls = []
        self.keep_open_after_close = keep_open_after_close

    def GetDocuments(self):
        return list(self.documents) or None

    def CloseAllDocuments(self, include_unsaved):
        self.close_calls.append(include_unsaved)
        if not self.keep_open_after_close:
            self.documents = []
        return True


ROOT = r"C:\work\iso"
TEMP = r"C:\Temp\swx1"


def test_closes_every_saved_document_inside_roots() -> None:
    sw = FakeSolidWorks([
        FakeDocument(ROOT + r"\a.SLDASM"),
        FakeDocument(ROOT + r"\sub\b.SLDPRT"),
        FakeDocument(TEMP + r"\IC~~\c.step.SLDPRT"),
    ])

    result = sw_connect.close_all_documents_scoped(sw, [ROOT, TEMP])

    assert sw.close_calls == [False]
    assert result["closed_count"] == 3
    assert result["closed_paths"][1].endswith("b.SLDPRT")
    assert result["allowed_document_roots"] == [ROOT, TEMP]
    assert sw.GetDocuments() is None


def test_refuses_document_outside_roots_without_closing() -> None:
    sw = FakeSolidWorks([FakeDocument(ROOT + r"\a.SLDASM"), FakeDocument(r"C:\other\x.SLDPRT")])

    with pytest.raises(ValueError, match="outside"):
        sw_connect.close_all_documents_scoped(sw, [ROOT])
    assert sw.close_calls == []


def test_root_prefix_does_not_match_sibling_directory() -> None:
    sw = FakeSolidWorks([FakeDocument(r"C:\work\iso-other\a.SLDASM")])

    with pytest.raises(ValueError, match="outside"):
        sw_connect.close_all_documents_scoped(sw, [ROOT])
    assert sw.close_calls == []


def test_refuses_unsaved_changes() -> None:
    sw = FakeSolidWorks([FakeDocument(ROOT + r"\a.SLDASM", needs_save=True)])

    with pytest.raises(ValueError, match="unsaved"):
        sw_connect.close_all_documents_scoped(sw, [ROOT])
    assert sw.close_calls == []


def test_refuses_never_saved_document() -> None:
    sw = FakeSolidWorks([FakeDocument("", title="Assem2")])

    with pytest.raises(ValueError, match="Never-saved"):
        sw_connect.close_all_documents_scoped(sw, [ROOT])
    assert sw.close_calls == []


def test_requires_absolute_non_empty_roots() -> None:
    sw = FakeSolidWorks([FakeDocument(ROOT + r"\a.SLDASM")])

    with pytest.raises(ValueError, match="absolute"):
        sw_connect.close_all_documents_scoped(sw, ["relative\\dir"])
    with pytest.raises(ValueError, match="at least one"):
        sw_connect.close_all_documents_scoped(sw, [])
    with pytest.raises(ValueError, match="at least one"):
        sw_connect.close_all_documents_scoped(sw, ["  "])
    assert sw.close_calls == []


def test_readback_must_be_empty() -> None:
    sw = FakeSolidWorks([FakeDocument(ROOT + r"\a.SLDASM")], keep_open_after_close=True)

    with pytest.raises(RuntimeError, match="still open"):
        sw_connect.close_all_documents_scoped(sw, [ROOT])
    assert sw.close_calls == [False]
