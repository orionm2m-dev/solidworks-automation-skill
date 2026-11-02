"""Portable fixture and exact installed-module origin regressions."""
import json
import re
import sys
from types import SimpleNamespace
import pytest
import cam_public_test_support as support


def test_default_runtime_is_repository_containing_tests(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    monkeypatch.delenv("SOLIDWORKS_SKILL_ROOT", raising=False)
    monkeypatch.setattr(support, "TESTS", tmp_path / "tests")
    assert support.runtime_root() == tmp_path.resolve()


def test_cached_module_from_wrong_location_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    name = "cam_public_fixture_origin_probe"
    (tmp_path / "scripts" / (name + ".py")).write_text("raise AssertionError('must not execute')", encoding="utf-8")
    monkeypatch.setenv("SOLIDWORKS_SKILL_ROOT", str(tmp_path))
    monkeypatch.setitem(sys.modules, "scripts." + name, SimpleNamespace(__file__=str(tmp_path / "other.py")))
    monkeypatch.setattr(sys, "path", list(sys.path))
    with pytest.raises(RuntimeError, match="unexpected location"):
        support.required_module(name)


def test_public_packet_uses_only_synthetic_file_locations():
    value = json.loads(support.fixture_path("cam_mill_packet17_8_synthetic.json").read_text(encoding="utf-8"))
    assert value["fixture_origin"] == "public_synthetic_example"
    assert not value["native_host_packet"] and "source_pin" not in value
    def strings(v):
        if isinstance(v, dict):
            for item in v.values(): yield from strings(item)
        elif isinstance(v, list):
            for item in v: yield from strings(item)
        elif isinstance(v, str): yield v
    locations = [s for s in strings(value) if re.match(r"^[A-Za-z]:[\\/]", s) or s.startswith("\\\\")]
    assert locations
    assert set(locations) == {"C:\\fixtures\\example.sldprt", "C:\\fixtures\\holder.mh"}
