"""solidworks_close_documents(paths=...)：закрыть ровно перечисленные документы (поддельный COM)."""
import pytest

from scripts import sw_connect


class FakeDoc:
    def __init__(self, path, dirty=False):
        self.path, self.dirty = path, dirty

    def GetPathName(self):
        return self.path

    def GetTitle(self):
        return self.path.rsplit("\\", 1)[-1]

    def GetSaveFlag(self):
        return self.dirty


class FakeSw:
    def __init__(self, docs, sticky=()):
        self.docs, self.sticky, self.closed = list(docs), set(sticky), []

    def GetDocuments(self):
        return list(self.docs)

    def CloseDoc(self, title):
        self.closed.append(title)
        self.docs = [d for d in self.docs if d.GetTitle() != title or d.GetTitle() in self.sticky]


ROOT = "C:\\work\\"


def docs(*names, dirty=()):
    return [FakeDoc(ROOT + n, n in dirty) for n in names]


def test_closes_only_listed_documents_drawings_first():
    sw = FakeSw(docs("a.SLDPRT", "a.SLDDRW", "b.SLDASM", "other.SLDPRT"))
    r = sw_connect.close_documents_by_paths(sw, [ROOT + "a.SLDPRT", ROOT + "a.SLDDRW", ROOT + "b.SLDASM"])
    assert r["status"] == "ok" and r["untouched_count"] == 1 and r["still_open"] == []
    assert sw.closed == ["a.SLDDRW", "b.SLDASM", "a.SLDPRT"]
    assert [d.GetTitle() for d in sw.docs] == ["other.SLDPRT"]


def test_not_open_document_refuses_before_closing_anything():
    sw = FakeSw(docs("a.SLDPRT"))
    with pytest.raises(ValueError, match="not open"):
        sw_connect.close_documents_by_paths(sw, [ROOT + "a.SLDPRT", ROOT + "missing.SLDPRT"])
    assert sw.closed == []


def test_unsaved_changes_need_explicit_discard():
    sw = FakeSw(docs("a.SLDPRT", dirty={"a.SLDPRT"}))
    with pytest.raises(ValueError, match="unsaved"):
        sw_connect.close_documents_by_paths(sw, [ROOT + "a.SLDPRT"])
    assert sw.closed == []
    r = sw_connect.close_documents_by_paths(sw, [ROOT + "a.SLDPRT"], discard_unsaved_changes=True)
    assert r["status"] == "ok" and r["discarded_paths"] == [ROOT + "a.SLDPRT"]


def test_document_still_loaded_after_close_is_reported():
    sw = FakeSw(docs("part.SLDPRT", "asm.SLDASM"), sticky={"part.SLDPRT"})
    r = sw_connect.close_documents_by_paths(sw, [ROOT + "part.SLDPRT"])
    assert r["status"] == "incomplete" and r["still_open"] == [ROOT + "part.SLDPRT"]


@pytest.mark.parametrize("paths", [[], ["relative.SLDPRT"], [ROOT + "a.SLDPRT", ROOT + "A.sldprt"]])
def test_bad_lists_are_refused(paths):
    sw = FakeSw(docs("a.SLDPRT"))
    with pytest.raises(ValueError):
        sw_connect.close_documents_by_paths(sw, paths)
    assert sw.closed == []
