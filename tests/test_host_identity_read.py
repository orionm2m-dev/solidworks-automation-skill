import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from copy import deepcopy
import pytest

from cam_public_test_support import add_runtime, required_module
R=add_runtime()
m=required_module("sw_cam_host_identity_read")

@pytest.fixture
def state(tmp_path):
    p = dict(process_id=123, expected_process_creation_time=1.5, expected_document_path=str(tmp_path / "part.SLDPRT"),
        expected_source_sha256="a" * 64, expected_configuration="Default", expected_dirty=False,
        receipt_path=str(tmp_path / "identity.json"), lifecycle_marker_pin={"path": str(tmp_path / "marker.json"), "sha256": "b" * 64})
    old = dict(mvid="339e4829-82ce-4274-b7b0-cac5ed1ec64c", dll={"path": str(tmp_path / "old.dll")}, tlb={"path": str(tmp_path / "old.tlb")})
    new = dict(mvid="1a0e318f-9857-4c43-9aa1-29a9867b64df", dll={"path": str(tmp_path / "new.dll")})
    raw = dict(schema_version=1, scope="TURN_INPROCESS_READ_V1", engine_version="turn-reader-1", stage="request",
        status="error", message="REQUEST_FIELDS", read_only=True, mutation_attempted=False, readback_verified=False,
        process_id=123, host_module_version_id=old["mvid"], host_assembly_location=old["dll"]["path"], elapsed_ms=0.1)
    return p, old, new, raw

@pytest.mark.parametrize("which", ["old", "new"])
def test_classifies_both_known_artifacts(state, which):
    p, old, new, raw = state
    selected = old if which == "old" else new
    raw.update(host_module_version_id=selected["mvid"], host_assembly_location=selected["dll"]["path"])
    result = m.classify_identity(raw, p, old, new)
    assert result["loaded_artifact"] == which and not result["mill_interface_qualified"]

@pytest.mark.parametrize("field,value", [("schema_version", True), ("process_id", True), ("process_id", 124),
    ("stage", "finished"), ("message", "other"), ("mutation_attempted", True), ("readback_verified", True),
    ("read_only", False), ("elapsed_ms", float("nan")), ("inventory", {}), ("document_after", {}),
    ("host_module_version_id", "00000000-0000-0000-0000-000000000000"), ("host_assembly_location", "wrong.dll")])
def test_identity_rejects_unproven_response(state, field, value):
    p, old, new, raw = state; raw[field] = value
    with pytest.raises((ValueError, TypeError)): m.classify_identity(raw, p, old, new)

class Fake:
    def __init__(self, state):
        self.p, self.old, self.new, self.raw = state; self.calls = 0; self.documents = 0
    def owner(self): return dict(process_id=self.p["process_id"], create_time=1.5, alive=True, executable="C:/program/sldworks.exe")
    def document(self):
        self.documents += 1
        return dict(path=self.p["expected_document_path"], title="part.SLDPRT", type=1, needs_save=False, configuration="Default")
    def identity_once(self): self.calls += 1; return json.dumps(self.raw)


def test_read_once_keeps_native_error_as_identity_success(state):
    p, old, new, _ = state; b = Fake(state)
    r = m.run_prepared((p, old, new, []), backend=b)
    assert r["status"] == "observed_host_identity" and r["readback_verified"] and b.calls == 1
    assert r["host_response"]["status"] == "error" and not r["host_response"]["readback_verified"]
    assert not r["mutation_attempted"] and not r["GTP_attempted"] and not r["registration_attempted"]
    before = Path(p["receipt_path"]).read_bytes()
    with pytest.raises(ValueError): m.run_prepared((p, old, new, []), backend=b)
    assert b.calls == 1 and Path(p["receipt_path"]).read_bytes() == before


def test_raw_persisted_before_validator_rejects(state, monkeypatch):
    p, old, new, _ = state; b = Fake(state)
    def reject(*args):
        observed = json.loads(Path(p["receipt_path"]).read_text("utf-8-sig"))
        assert observed["raw_host_response"] == json.dumps(b.raw)
        raise ValueError("stop")
    monkeypatch.setattr(m, "classify_identity", reject)
    r = m.run_prepared((p, old, new, []), backend=b)
    assert r["status"] == "error" and b.calls == 1 and not r["readback_verified"]
    assert r["raw_host_response"] == json.dumps(b.raw)


def test_changed_original_marker_detected(state, tmp_path):
    p, old, new, _ = state; b = Fake(state)
    marker = tmp_path / "original.json"; marker.write_text("original")
    pin = m.lifecycle.pin(marker)
    def read(): b.calls += 1; marker.write_text("changed"); return json.dumps(b.raw)
    b.identity_once = read
    r = m.run_prepared((p, old, new, [pin]), backend=b)
    assert r["status"] == "error" and not r["readback_verified"] and b.calls == 1


def test_real_constructor_and_fixed_reader_callgraph(state, monkeypatch):
    p, old, new, raw = state; b = m.NativeBackend(p, old); events = []
    assert type(b.reader) is m.loader.LoaderBackend
    assert all(callable(getattr(b, name)) for name in ("owner", "document", "application", "identity_once"))
    assert all(not hasattr(b, name) for name in ("load_once", "unload_once", "register_once", "save", "generate", "start_events"))
    interface = object(); raw_object = object()
    class App:
        def GetProcessID(self): events.append("pid"); return 123
        def GetAddInObject(self, clsid):
            assert clsid == m.common.HOST_CLSID; events.append("get_existing"); return raw_object
    class Typed:
        def ReadTurnSnapshot(self, text):
            assert text == "{}"; events.append("read_empty_once"); return json.dumps(raw)
    class Unknown:
        def QueryInterface(self, selected):
            assert selected is interface; events.append("qi_turn"); return Typed()
    from scripts import sw_cam_comtypes as bridge
    def marshal(value): assert value is raw_object; return Unknown()
    monkeypatch.setattr(bridge, "_marshal_pywin32_unknown", marshal)
    def typelib(path, *, mill):
        assert path == old["tlb"]["path"] and mill is False; events.append("abi"); return None, interface, "ReadTurnSnapshot"
    monkeypatch.setattr(m.lifecycle, "type_library", typelib)
    b.reader.sw = App()
    assert json.loads(b.identity_once()) == raw
    assert events == ["abi", "pid", "get_existing", "qi_turn", "read_empty_once"]
    with pytest.raises(ValueError): b.identity_once()
    assert events.count("read_empty_once") == 1


def test_real_reader_qi_failure_never_calls_method(state, monkeypatch):
    p, old, new, raw = state; b = m.NativeBackend(p, old); calls = []
    from scripts import sw_cam_comtypes as bridge
    class App:
        def GetProcessID(self): return 123
        def GetAddInObject(self, clsid): return object()
    class Unknown:
        def QueryInterface(self, selected): calls.append("qi"); raise ValueError("unsupported")
    monkeypatch.setattr(bridge, "_marshal_pywin32_unknown", lambda value: Unknown())
    monkeypatch.setattr(m.lifecycle, "type_library", lambda *a, **kw: (None, object(), "ReadTurnSnapshot"))
    b.reader.sw = App()
    with pytest.raises(ValueError): b.identity_once()
    with pytest.raises(ValueError): b.identity_once()
    assert calls == ["qi"]


@pytest.fixture
def failed(state):
    p = state[0]
    actions = {name: dict(attempted=True, returned=True, verified=True, result=0)
        for name in ("UnloadOwnedHost", "RegisterCurrentUserHost", "LoadVersionedHost")}
    actions["RegisterCurrentUserHost"]["result"] = dict(typelib_hresult=0, scope="CurrentUser",
        class_mapping="existing_Register_CurrentUser_version_derived")
    actions["ReadMillSnapshot"] = dict(attempted=True, returned=False, verified=False)
    oldp = {k: p[k] for k in ("process_id", "expected_process_creation_time", "expected_document_path", "expected_configuration")}
    oldp["module_sha256"] = m.common.digest(m.lifecycle.__file__)
    return dict(scope=m.lifecycle.SCOPE, status="uncertain", phase="finished", native_dispatch_pending=True,
        model_saved=False, GTP_attempted=False, model_change_requested=False, readback_verified=False,
        loaded_mvid_verified=False, automatic_replay=False, actions=actions, request=oldp,
        issue=dict(type="COMError", hresult=-2147467262, locations=[
            dict(file="sw_cam_mill_host_lifecycle.py", function="_read"), dict(function="QueryInterface")]),
        events_after=dict(subscribed=True, active=False, event_count=0, overflow=0, callback_error_count=0,
            callback_errors=[], subscription_error=None, disconnect_errors=[], disconnected=True))


def test_exact_failed_lifecycle_contract(state, failed):
    assert m.failure_contract(failed, state[0]) == failed["request"]

@pytest.mark.parametrize("fault", ["returned", "load_result", "registration", "error", "location", "active", "replay", "source_owner"])
def test_other_failure_is_not_identity_authority(state, failed, fault):
    if fault == "returned": failed["actions"]["ReadMillSnapshot"]["returned"] = True
    if fault == "load_result": failed["actions"]["LoadVersionedHost"]["result"] = True
    if fault == "registration": failed["actions"]["RegisterCurrentUserHost"]["result"]["scope"] = "LocalMachine"
    if fault == "error": failed["issue"]["hresult"] = -1
    if fault == "location": failed["issue"]["locations"] = []
    if fault == "active": failed["events_after"]["active"] = True
    if fault == "replay": failed["automatic_replay"] = True
    if fault == "source_owner": failed["request"]["process_id"] = 124
    with pytest.raises(ValueError): m.failure_contract(failed, state[0])
