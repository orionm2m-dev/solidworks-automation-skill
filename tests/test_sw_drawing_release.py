"""出图检查：PDF 页面尺寸逐页对照图纸尺寸（无 COM）。"""
import pytest

pymupdf = pytest.importorskip("pymupdf")

from scripts.sw_drawing_2d import _safe_file_part, check_pdf_pages

K = 72 / 25.4


def _pdf(tmp_path, sizes_mm):
    doc = pymupdf.open()
    for w, h in sizes_mm:
        doc.new_page(width=w * K, height=h * K)
    path = tmp_path / "out.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _sheets(*sizes):
    return [{"name": f"Лист{i + 1}", "size_mm": list(s)} for i, s in enumerate(sizes)]


def test_pages_match_sheet_sizes(tmp_path):
    path = _pdf(tmp_path, [(210, 297), (420, 297)])
    report = check_pdf_pages(path, _sheets((210, 297), (420, 297)))
    assert report["all_ok"] is True
    assert [row["ok"] for row in report["pages"]] == [True, True]


def test_scaled_page_is_reported(tmp_path):
    path = _pdf(tmp_path, [(210, 297), (297, 210)])
    report = check_pdf_pages(path, _sheets((210, 297), (420, 297)))
    assert report["all_ok"] is False
    assert report["pages"][1]["problem"] == "size"


def test_rotated_page_is_reported(tmp_path):
    path = _pdf(tmp_path, [(297, 210)])
    report = check_pdf_pages(path, _sheets((210, 297)))
    assert report["pages"][0]["problem"] == "rotated"
    assert report["all_ok"] is False


def test_missing_and_extra_pages_fail(tmp_path):
    short = check_pdf_pages(_pdf(tmp_path, [(210, 297)]), _sheets((210, 297), (210, 297)))
    assert short["all_ok"] is False and short["pages"][1]["problem"] == "missing_page"
    (tmp_path / "out.pdf").unlink()
    extra = check_pdf_pages(_pdf(tmp_path, [(210, 297), (210, 297)]), _sheets((210, 297)))
    assert extra["all_ok"] is False and extra["extra_pages"] == 1


def test_safe_file_part_strips_forbidden_characters():
    assert _safe_file_part('Лист 1: "схема"/A?') == "Лист 1_ _схема__A_"
    assert _safe_file_part("..") == "sheet"
