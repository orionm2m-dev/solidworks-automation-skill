"""Focused tests for guarded custom-property reads without a CAD process."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sw_custom_properties_read.py"
SPEC = importlib.util.spec_from_file_location("staged_custom_properties_read", MODULE_PATH)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)
PATH = r"C:\project\part.SLDPRT"


class Model:
    def __init__(self):
        self.path, self.title, self.kind, self.dirty = PATH, "part.SLDPRT", 1, False
        self.configuration = SimpleNamespace(Name="Default")
        self.ConfigurationManager = SimpleNamespace(ActiveConfiguration=self.configuration)

    def GetPathName(self):
        return self.path

    def GetTitle(self):
        return self.title

    def GetType(self):
        return self.kind

    def GetSaveFlag(self):
        return self.dirty


class Session:
    def __init__(self):
        self.pid, self.ActiveDoc, self.pid_reads = 42, Model(), 0

    def GetProcessID(self):
        self.pid_reads += 1
        return self.pid


def property_row(name, scope, status=2, **updates):
    row = dict(name=name, configuration=scope, status=status, exists=status != 1,
               raw="R23" if status != 1 else "", resolved="R23" if status != 1 else "",
               was_resolved=status == 2, is_linked=False)
    row.update(updates)
    return row


@pytest.fixture
def setup(monkeypatch):
    sw, calls = Session(), []
    def read(model, name, *, configuration_name):
        calls.append((name, configuration_name))
        return property_row(name, configuration_name)
    monkeypatch.setattr(reader, "read_custom_property", read)
    return sw, calls


def run(sw, **overrides):
    params = dict(process_id=42, expected_document_path=PATH,
                  names=["Revision"], configuration_name="")
    params.update(overrides)
    return reader.read_custom_properties(sw, **params)


@pytest.mark.parametrize("scope", ["", "Default"])
def test_reads_only_requested_current_scope(setup, scope):
    sw, calls = setup
    result = run(sw, names=["Revision", "DesignStatus"], configuration_name=scope)
    assert result["status"] == "ok" and result["read_complete"]
    assert result["state_unchanged"] and result["before"] == result["after"]
    assert calls == [("Revision", scope), ("DesignStatus", scope)]
    assert not result["mutation_attempted"] and not result["model_saved"]


@pytest.mark.parametrize("params", [
    {"process_id": True}, {"process_id": 0}, {"process_id": "42"},
    {"expected_document_path": "part.SLDPRT"}, {"expected_document_path": None},
    {"names": []}, {"names": ("Revision",)}, {"names": ["Revision", "revision"]},
    {"names": [""]}, {"names": [" "]}, {"names": [1]}, {"names": ["a" * 241]},
    {"names": ["p" + str(i) for i in range(65)]},
    {"configuration_name": None}, {"configuration_name": "x" * 241},
])
def test_invalid_request_does_not_touch_native(setup, params):
    sw, calls = setup
    result = run(sw, **params)
    assert result["status"] == "error"
    assert sw.pid_reads == 0 and calls == []


@pytest.mark.parametrize("change", ["pid", "pid_bool", "path", "type_bool", "type_float", "dirty_int", "configuration_empty", "no_document"])
def test_identity_failure_stops_before_property(setup, change):
    sw, calls = setup
    if change == "pid": sw.pid = 43
    if change == "pid_bool": sw.pid = True
    if change == "path": sw.ActiveDoc.path = r"C:\project\other.SLDPRT"
    if change == "type_bool": sw.ActiveDoc.kind = True
    if change == "type_float": sw.ActiveDoc.kind = 1.0
    if change == "dirty_int": sw.ActiveDoc.dirty = 0
    if change == "configuration_empty": sw.ActiveDoc.configuration.Name = ""
    if change == "no_document": sw.ActiveDoc = None
    result = run(sw)
    assert result["status"] == "error" and calls == []


def test_inactive_configuration_never_resolves_or_activates(setup):
    sw, calls = setup
    result = run(sw, configuration_name="Other")
    assert result["status"] == "error" and calls == []
    assert sw.ActiveDoc.configuration.Name == "Default"


@pytest.mark.parametrize("status", [0, 1, 2])
def test_cached_missing_and_resolved_results_remain_distinct(setup, monkeypatch, status):
    sw, _ = setup
    monkeypatch.setattr(reader, "read_custom_property",
                        lambda model, name, *, configuration_name: property_row(name, configuration_name, status))
    result = run(sw)
    assert result["status"] == "ok"
    assert result["properties"][0]["status"] == status
    assert result["properties"][0]["exists"] == (status != 1)
    assert result["properties"][0]["was_resolved"] == (status == 2)


@pytest.mark.parametrize("updates", [
    {"status": 99}, {"status": True}, {"exists": "true"}, {"exists": False},
    {"was_resolved": 1}, {"is_linked": None}, {"raw": None},
    {"resolved": 7}, {"name": "Other"}, {"configuration": "Other"},
])
def test_malformed_property_result_stops(setup, monkeypatch, updates):
    sw, calls = setup
    def read(model, name, *, configuration_name):
        calls.append(name)
        return property_row(name, configuration_name, **updates)
    monkeypatch.setattr(reader, "read_custom_property", read)
    result = run(sw, names=["Revision", "Never"])
    assert result["status"] == "error" and calls == ["Revision"]
    assert result["properties"] == [] and not result["read_complete"]


@pytest.mark.parametrize("change", ["dirty", "configuration", "path", "title", "pid"])
def test_state_change_after_getter_stops_before_next_property(setup, monkeypatch, change):
    sw, calls = setup
    def read(model, name, *, configuration_name):
        calls.append(name)
        if change == "dirty": model.dirty = True
        if change == "configuration": model.configuration.Name = "Other"
        if change == "path": model.path = r"C:\project\other.SLDPRT"
        if change == "title": model.title = "Changed"
        if change == "pid": sw.pid = 43
        return property_row(name, configuration_name)
    monkeypatch.setattr(reader, "read_custom_property", read)
    result = run(sw, names=["Revision", "Never"])
    assert result["status"] == "error" and calls == ["Revision"]
    assert not result["state_unchanged"] and not result["read_complete"]


def test_existing_dirty_document_can_be_read_without_saving(setup):
    sw, _ = setup
    sw.ActiveDoc.dirty = True
    result = run(sw)
    assert result["status"] == "ok"
    assert result["before"]["needs_save"] is True and result["after"]["needs_save"] is True


def test_first_exception_is_not_retried(setup, monkeypatch):
    sw, calls = setup
    def read(model, name, *, configuration_name):
        calls.append(name)
        raise RuntimeError("Native getter failed")
    monkeypatch.setattr(reader, "read_custom_property", read)
    result = run(sw, names=["Revision", "Never"])
    assert calls == ["Revision"]
    assert result["error"] == {"type": "RuntimeError", "message": "Native getter failed"}
    assert result["status"] == "error"


def test_reuses_existing_get6_reader_without_setter(setup, monkeypatch):
    from scripts import sw_document_data
    sw, calls = setup
    class Variant:
        def __init__(self, _kind, value):
            self.value = value
    class Manager:
        def Get6(self, name, cached, raw, resolved, was_resolved, linked):
            calls.append(("Get6", name, cached))
            raw.value, resolved.value = "R23", "R23"
            was_resolved.value, linked.value = True, False
            return 2
        def Add3(self, *_args):
            raise AssertionError("No property write permitted")
    manager = Manager()
    sw.ActiveDoc.Extension = SimpleNamespace(CustomPropertyManager=lambda scope: manager)
    monkeypatch.setattr(sw_document_data, "VARIANT", Variant)
    monkeypatch.setattr(reader, "read_custom_property", sw_document_data.read_custom_property)
    result = run(sw, configuration_name="Default")
    assert result["status"] == "ok"
    assert calls == [("Get6", "Revision", False)]
    assert not result["model_saved"]
