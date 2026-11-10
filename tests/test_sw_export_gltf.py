"""glTF/GLB 导出路由与扩展名校验测试（离线假对象，不连接 SOLIDWORKS）。"""
from pathlib import Path

import pytest

from scripts import sw_export


class _FakeExtension:
    def __init__(self):
        self.calls = []

    def SaveAs(self, path, version, options, data, errors, warnings):
        self.calls.append((path, version, options))
        return True


class _FakeModel:
    def __init__(self):
        self.Extension = _FakeExtension()
        self.cleared = 0

    def ClearSelection2(self, _all):
        self.cleared += 1


def test_normalize_format_accepts_glb_and_gltf():
    assert sw_export._normalize_format("glb") == ".glb"
    assert sw_export._normalize_format(".GLTF") == ".gltf"


def test_export_to_gltf_rejects_other_extensions(tmp_path):
    with pytest.raises(ValueError):
        sw_export.export_to_gltf(_FakeModel(), str(tmp_path / "model.stl"))


def test_export_to_gltf_calls_save_as_with_glb_path(tmp_path):
    model = _FakeModel()
    target = tmp_path / "out" / "model.glb"
    assert sw_export.export_to_gltf(model, str(target)) is True
    assert model.cleared == 1
    path, version, options = model.Extension.calls[0]
    assert Path(path) == target.resolve()
    assert (version, options) == (0, 1)
    assert target.parent.is_dir()


def test_export_for_format_routes_glb_to_gltf_exporter(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(sw_export, "export_to_gltf", lambda model, path: seen.append(path) or True)
    assert sw_export._export_for_format(object(), str(tmp_path / "a.glb"), ".glb", "fine") is True
    assert sw_export._export_for_format(object(), str(tmp_path / "a.gltf"), ".gltf", "fine") is True
    assert len(seen) == 2
