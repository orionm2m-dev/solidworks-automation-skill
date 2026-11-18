"""Exercise the real dispatch guard with fake application boundary objects only."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib.util
import os
import pytest
from scripts import sw_cam_dispatch_guard as guard_module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def append_module():
    path = Path(os.environ.get("APPEND_MODULE_UNDER_TEST", str(Path(__file__).parents[1] / "scripts/sw_cam_append_finish_definitions.py")))
    spec = importlib.util.spec_from_file_location("append_guard_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owned_case(tmp_path, monkeypatch, append_module):
    m = append_module
    source = tmp_path / "source.sldprt"; source.write_bytes(b"unchanged saved qualification source")
    authority = tmp_path / "authority.json"; authority.write_bytes(b'{"immutable":true}')
    source_sha, authority_sha = digest(source), digest(authority)
    document = dict(path=str(source), title="source.sldprt", type=1, needs_save=False)
    events = []
    handles = []
    state = dict(pid=123, insertions=0, after_insert=None, next_id=362)
    feature = SimpleNamespace(native_id=359)
    anchor = SimpleNamespace(native_id=361)
    feature.QueryInterface = lambda interface: feature
    anchor.QueryInterface = lambda interface: anchor
    header = dict(native_id=359, suppressed=False)
    def insert(kind, default_id, after):
        assert kind == 1 and default_id == 2 and after is anchor
        assert events[-1] == "pending"
        events.append("insert")
        state["insertions"] += 1
        document["needs_save"] = True
        value = SimpleNamespace(native_id=state["next_id"])
        if state["after_insert"]:
            state["after_insert"]()
        return value
    feature.InsertOperation = insert
    feature.GetTdbIdForDefaultOperation = lambda kind, name: 2
    doc = SimpleNamespace(GetCWObjectFromID=lambda kind, oid: (feature if kind == 1 else anchor, True),
                          GetCWObjectID=lambda value: (value.native_id, True))
    sw = SimpleNamespace(GetProcessID=lambda: state["pid"])
    native_getters = []
    def member(owner, name, *args):
        native_getters.append(name)
        result = getattr(owner, name)
        return result(*args) if callable(result) else result
    monkeypatch.setattr(guard_module, "_member", member)
    monkeypatch.setattr(guard_module, "raw_part_identity", lambda unused: deepcopy(document))
    monkeypatch.setattr(guard_module, "_typed", lambda owner, interface, tlb: owner)
    monkeypatch.setattr(m, "_member", member)
    monkeypatch.setattr(m, "_is_comtypes_pointer", lambda value: isinstance(value, SimpleNamespace))
    monkeypatch.setattr(m, "read_header", lambda *args, **kwargs: (deepcopy(header), feature))
    def evidence():
        assert digest(authority) == authority_sha
    def owner():
        assert state["pid"] == 123
    def guard():
        assert not handles or not handles[-1].summary()["active"]
        g = guard_module.ScopedCamDispatchGuard(sw, "not-opened.tlb", process_id=123,
            expected_document=deepcopy(document), source_sha256=source_sha,
            evidence_pins=[dict(path=str(authority), sha256=authority_sha)],
            verify_evidence=evidence, verify_owned_process=owner, check_events=lambda: None)
        handles.append(g)
        return g
    ctx = m.AppendContext.__new__(m.AppendContext)
    ctx.native = {"doc": doc}; ctx.guard = guard; ctx.added_rows = []
    ctx.append_plan = dict(state=dict(target_header=header, reference_header=dict(native_id=70),
        operations=[dict(native_id=361)], features=[dict(geometry=dict(native_id=359)), dict(geometry=dict(native_id=70))],
        operation_setups=[dict(native_id=94)], feature_setups=[dict(native_id=72)]))
    row = dict(role="floor", feature_native_id=359, feature_owner_setup_native_id=72,
               operation_setup_native_id=94, default_operation_id=2, default_operation_name="Default",
               expected_bottom_finish=True)
    returned = []
    def on_return(value):
        returned.append(value); events.append("returned")
    return SimpleNamespace(module=m, context=ctx, row=row, source=source, authority=authority,
        document=document, state=state, guards=handles, events=events, returned=returned,
        native_getters=native_getters, pending=lambda: events.append("pending"), on_return=on_return,
        make_guard=guard, doc=doc)


def test_real_guard_rejects_reads_after_dispatch_even_when_callback_returns(owned_case):
    c = owned_case
    with c.make_guard() as g:
        raw = g.dispatch_once(lambda: SimpleNamespace(native_id=362), persist_pending=lambda: None)
        assert g.summary()["native_call_returned"] is True
        with pytest.raises(ValueError, match="closed, invalid or already claimed"):
            g.read(c.doc, "GetCWObjectID", raw)
    assert not c.guards[-1].summary()["active"]
    assert "GetCWObjectID" not in c.native_getters


def test_actual_insert_uses_fresh_closed_previous_guard_for_id_readback(owned_case):
    c = owned_case
    oid = c.context.insert(c.row, 361, pending=c.pending, returned=c.on_return)
    assert oid == 362 and c.state["insertions"] == 1
    assert c.events == ["pending", "insert", "returned"] and len(c.returned) == 1
    assert len(c.guards) == 2
    first, second = (g.summary() for g in c.guards)
    assert first["claimed"] and first["native_call_attempted"] and first["native_call_returned"]
    assert not second["claimed"] and not second["native_call_attempted"]
    assert not first["active"] and not second["active"]
    assert not first["invalid"] and not second["invalid"]
    assert c.guards[0].expected_document["needs_save"] is False
    assert c.guards[1].expected_document["needs_save"] is True
    assert not any(name.startswith(("Save", "Generate", "Set")) for name in c.native_getters)


@pytest.mark.parametrize("change", ["source", "evidence", "owner"])
def test_new_read_scope_rejects_post_insert_drift_without_retry_or_save(owned_case, change):
    c = owned_case
    if change == "source": c.state["after_insert"] = lambda: c.source.write_bytes(b"changed source")
    elif change == "evidence": c.state["after_insert"] = lambda: c.authority.write_bytes(b"changed evidence")
    else: c.state["after_insert"] = lambda: c.state.update(pid=456)
    with pytest.raises((ValueError, AssertionError)):
        c.context.insert(c.row, 361, pending=c.pending, returned=c.on_return)
    assert c.state["insertions"] == 1 and len(c.returned) == 1
    assert c.events == ["pending", "insert", "returned"]
    assert all(not g.summary()["active"] for g in c.guards)
    assert not any(name.startswith(("Save", "Generate", "Set")) for name in c.native_getters)


@pytest.mark.parametrize("duplicate", [361, 359, 94, 72])
def test_actual_id_readback_rejects_existing_identity_without_reinsertion(owned_case, duplicate):
    c = owned_case; c.state["next_id"] = duplicate
    with pytest.raises(ValueError, match="identity collision"):
        c.context.insert(c.row, 361, pending=c.pending, returned=c.on_return)
    assert c.state["insertions"] == 1 and len(c.returned) == 1
    assert not any(name.startswith(("Save", "Generate", "Set")) for name in c.native_getters)
