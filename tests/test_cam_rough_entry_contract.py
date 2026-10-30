"""粗加工入口变更的合成回归；不连接 CAD。"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import sw_cam_rough_entry_cas as sut


def snapshots():
    before = dict(candidate={"tool": 7}, levels={"depth": 2},
        entry={"entry": {"GetEntryExitType": {"raw": 2}}, "feed": 100},
        context={"document": {"needs_save": False}, "saved_file_sha256": "a" * 64,
            "operations": [dict(native_id=11, toolpath_generated=True, toolpath_record_counts=[8]),
                           dict(native_id=12, toolpath_generated=True, toolpath_record_counts=[4])]})
    after = deepcopy(before)
    after["entry"]["entry"]["GetEntryExitType"]["raw"] = 4
    after["context"]["document"]["needs_save"] = True
    after["context"]["operations"][0].update(toolpath_generated=False, toolpath_record_counts=[])
    return before, after


def test_exact_entry_edit_requires_regeneration():
    before, after = snapshots()
    result = sut.verify_entry_delta(before, after, operation_id=11, expected_old=2, new_value=4)
    assert result["regeneration_required"] is True
    assert result["path_invalidation_observed"] is True
    assert result["path_valid_for_changed_entry_verified"] is False
    assert before["entry"]["entry"]["GetEntryExitType"]["raw"] == 2


@pytest.mark.parametrize("change", ["tool", "levels", "feed", "sibling", "source", "dirty_int", "bool_count", "negative_count", "too_many", "float_mode", "missing", "duplicate"])
def test_protected_or_malformed_changes_rejected(change):
    before, after = snapshots()
    if change == "tool": after["candidate"]["tool"] = 8
    if change == "levels": after["levels"]["depth"] = 3
    if change == "feed": after["entry"]["feed"] = 101
    if change == "sibling": after["context"]["operations"][1]["toolpath_record_counts"] = []
    if change == "source": after["context"]["saved_file_sha256"] = "b" * 64
    if change == "dirty_int": after["context"]["document"]["needs_save"] = 1
    if change == "bool_count": after["context"]["operations"][0]["toolpath_record_counts"] = [True]
    if change == "negative_count": after["context"]["operations"][0]["toolpath_record_counts"] = [-1]
    if change == "too_many": after["context"]["operations"][0]["toolpath_record_counts"] = [1] * 33
    if change == "float_mode": after["entry"]["entry"]["GetEntryExitType"]["raw"] = 4.0
    if change == "missing": after["context"]["operations"].pop(0)
    if change == "duplicate": after["context"]["operations"].append(deepcopy(after["context"]["operations"][0]))
    with pytest.raises(ValueError):
        sut.verify_entry_delta(before, after, operation_id=11, expected_old=2, new_value=4)


class Guard:
    def __init__(self, value=2):
        self.value = value
        self.claimed = False
    def read(self, obj, method, feature):
        assert method == "GetEntryExitType"
        return self.value
    def dispatch_once(self, call, persist_pending):
        if self.claimed:
            raise ValueError("already dispatched")
        self.claimed = True
        persist_pending()
        return call()


def dispatch(monkeypatch, result=0, observed=2, native_error=False):
    report = dict(setter_call_count=0, setter_returned=False, native_dispatch_pending=False)
    saved, calls = [], []
    def member(obj, method, *args):
        calls.append((obj, method, args))
        assert saved[-1]["setter_attempted"] is True
        assert saved[-1]["native_dispatch_pending"] is True
        if native_error: raise RuntimeError("transport interrupted")
        return result
    monkeypatch.setattr(sut, "_member", member)
    guard = Guard(observed)
    def run():
        return sut.dispatch_entry_once(guard, "rough", "feature", expected_old=2, new_value=4,
            report=report, persist=lambda: saved.append(deepcopy(report)),
            claim=lambda: saved.append(deepcopy(report)))
    return run, report, saved, calls


def test_single_setter_persists_pending_and_raw_result(monkeypatch):
    run, report, saved, calls = dispatch(monkeypatch)
    assert run() == 0
    assert calls == [("rough", "SetEntryExitType", ("feature", 4))]
    assert saved[-1]["native_return_type"] == "int"
    assert saved[-1]["native_return_value"] == 0
    assert saved[-1]["native_dispatch_pending"] is False
    with pytest.raises(ValueError): run()
    assert len(calls) == 1


@pytest.mark.parametrize("result", [None, True, False, 0.0, 1, -1, "0", object()])
def test_bad_return_is_preserved_before_rejection(monkeypatch, result):
    run, report, saved, calls = dispatch(monkeypatch, result=result)
    with pytest.raises(ValueError): run()
    assert len(calls) == 1 and report["setter_returned"] is True
    assert saved[-1]["native_return_type"] == type(result).__name__
    assert saved[-1]["native_dispatch_pending"] is False
    assert report["setter_call_count"] == 1


@pytest.mark.parametrize("observed", [3, 2.0, True, None])
def test_stale_comparison_never_dispatches(monkeypatch, observed):
    run, report, saved, calls = dispatch(monkeypatch, observed=observed)
    with pytest.raises(ValueError): run()
    assert calls == [] and saved == [] and report["setter_call_count"] == 0


def test_interruption_remains_pending(monkeypatch):
    run, report, saved, calls = dispatch(monkeypatch, native_error=True)
    with pytest.raises(RuntimeError): run()
    assert len(calls) == 1 and report["native_dispatch_pending"] is True
    assert report["setter_returned"] is False


def test_contract_reads_real_synthetic_enum_file(tmp_path):
    values = dict(PLUNGE=0, ENTRYDRILL=1, RAMP=2, ENTRY_HOLE=3, HELICAL=4, RAMP_ON_LEADIN=5)
    source = tmp_path / "synthetic_type_library.py"
    source.write_text("\n".join("CW_ENTRY_EXIT_%s = %s" % item for item in values.items()), encoding="utf-8")
    contract = dict(interface="ICWRghMillOp", tlb_path=str(source), tlb_sha256=sut._file_hash(source), exact_scope={"tool": 7},
        methods=[dict(name="GetEntryExitType", dispid=58), dict(name="SetEntryExitType", dispid=88,
            **{"in": ["IDispatch feature", "LONG type"], "return": "HRESULT only; no retval"})])
    data = dict(scope="OFFLINE_ROUGH_ENTRY_RECIPE_REVIEW_V1", status="PROPOSAL_REQUIRES_ONE_NATIVE_QUALIFICATION_AND_CL_READBACK",
        native_interface_contract=contract, primary_documentation=dict(enum_constants=values, named_enum_binding_in_method_signature=False))
    proof = tmp_path / "recipe.json"
    proof.write_text(json.dumps(data), encoding="utf-8")
    result = sut.load_entry_contract(str(proof), sut._file_hash(proof), 2, 4)
    assert result["enum_constants"] == values
    assert result["resulting_entry_geometry_verified"] is False
    for old, new in [(2, 2), (True, 4), (2, 4.0), (-1, 4), (2, 6)]:
        with pytest.raises(ValueError): sut.load_entry_contract(str(proof), sut._file_hash(proof), old, new)
    source.write_text(source.read_text().replace("HELICAL = 4", "HELICAL = 5"), encoding="utf-8")
    with pytest.raises(ValueError): sut.load_entry_contract(str(proof), sut._file_hash(proof), 2, 4)


def lifecycle(monkeypatch, tmp_path, returned=0, drift=False, native_error=False):
    from scripts import sw_cam_events
    before, after = snapshots()
    source = tmp_path / "part.SLDPRT"
    source.write_bytes(b"synthetic")
    before["context"]["document"]["path"] = str(source)
    after["context"]["document"]["path"] = str(source)
    if drift: after["context"]["operations"][1]["toolpath_record_counts"] = [9]
    evidence = tmp_path / "parent.json"
    evidence.write_text("{}", encoding="utf-8")
    pin = dict(path=str(evidence), sha256=sut._file_hash(evidence))
    loaded = dict(state=before["context"], payload={k:before[k] for k in ("candidate", "levels", "entry")}, pin=pin, pins=[pin])
    args = dict(process_id=123, expected_document_path=str(source), expected_source_sha256="a"*64,
        qualification_only=True, acknowledge_disposable_copy=True, message_policy="vendor_default",
        receipt_path=str(tmp_path / "result.json"), expected_candidate_tool_native_id=7,
        target_feature_native_id=13, target_operation_native_id=11, target_operation_setup_native_id=17)
    calls = []
    class NativeGuard(Guard):
        def __enter__(self): return self
        def __exit__(self, *exc): pass
        def read(self, obj, method, *values):
            if method == "GetCWObjectFromID": return ("feature", True)
            return super().read(obj, method, *values)
        def typed(self, value, name): return value
        def summary(self): return dict(claimed=True, native_call_attempted=True, native_call_returned=True, invalid=False)
    class Context:
        def __init__(self, *a): pass
        def files(self): pass
        def identity(self): return deepcopy((after if calls else before)["context"]["document"])
        def guard(self): return NativeGuard()
    class Session:
        def __init__(self, *a): self.active=False
        def __enter__(self): self.active=True; return self
        def __exit__(self, *a): self.active=False
        def summary(self): return dict(subscribed=True, active=self.active, disconnected=not self.active, event_count=0)
    def capture(ctx, state, diag):
        diag["capture_complete"] = True
        data = deepcopy(after if calls else before)
        return data["context"], dict(doc="doc", operations={11:"rough"}), data["levels"], None, data["entry"], data["candidate"]
    def member(obj, method, *values):
        marker = sut.entry_marker(str(source), "a"*64, 11, 13, 2, 4)
        assert json.loads(marker.read_text())["native_dispatch_pending"] is True
        calls.append((method, values))
        if native_error: raise RuntimeError("interrupted")
        return returned
    monkeypatch.setattr(sut, "load_completed_route_save", lambda *a, **kw: deepcopy(loaded))
    monkeypatch.setattr(sut, "load_wip_witness", lambda *a: ({}, pin, [pin]))
    monkeypatch.setattr(sut, "load_entry_contract", lambda *a: dict(pin=pin, source_pin=pin,
        exact_scope=dict(feature_native_id=13, operation_native_id=11, operation_setup_native_id=17, tool_native_id=7)))
    monkeypatch.setattr(sut, "RouteCheckpointContext", Context)
    monkeypatch.setattr(sut, "capture_route_checkpoint", capture)
    monkeypatch.setattr(sut, "_bootstrap", lambda *a: "app")
    monkeypatch.setattr(sut, "_object_id", lambda *a: 13)
    monkeypatch.setattr(sut, "_member", member)
    monkeypatch.setattr(sw_cam_events, "CamMessageSession", Session)
    def run(**overrides):
        return sut.edit_rough_entry(None, "clsid", "tlb", wip_witness_receipt_path=str(evidence),
            wip_witness_receipt_sha256=pin["sha256"], entry_contract_path=str(evidence), entry_contract_sha256=pin["sha256"],
            expected_old=2, new_value=4, acknowledge_experimental_enum=True,
            saved_gtp_receipt_path=str(evidence), saved_gtp_receipt_sha256=pin["sha256"],
            owned_startup_receipt_path=str(evidence), owned_startup_receipt_sha256=pin["sha256"], **(args|overrides))
    return run, calls, args


def test_lifecycle_completes_without_generation_or_save(monkeypatch, tmp_path):
    run, calls, args = lifecycle(monkeypatch, tmp_path)
    result = run()
    assert result["status"] == "review_required", result
    assert result["readback_verified"] and result["protected_operations_verified"]
    assert result["GTP_attempted"] is False and result["model_saved"] is False
    assert calls == [("SetEntryExitType", ("feature", 4))]
    prior = Path(result["marker_path"]).read_bytes()
    repeated = run(receipt_path=str(tmp_path / "another.json"))
    assert repeated["status"] == "error" and repeated["mutation_attempted"] is False
    assert len(calls) == 1 and Path(result["marker_path"]).read_bytes() == prior


@pytest.mark.parametrize("options", [dict(returned=True), dict(returned=None), dict(returned=-1), dict(drift=True), dict(native_error=True)])
def test_lifecycle_partial_failure_preserves_marker(monkeypatch, tmp_path, options):
    run, calls, args = lifecycle(monkeypatch, tmp_path, **options)
    result = run()
    assert result["status"] == "uncertain", result
    assert result["readback_verified"] is False and len(calls) == 1
    marker = Path(result["marker_path"])
    assert marker.is_file()
    disk = json.loads(Path(args["receipt_path"]).read_text())
    assert disk["mutation_attempted"] is True and disk["setter_call_count"] == 1
    if options.get("native_error"):
        assert disk["native_dispatch_pending"] is True and disk["setter_returned"] is False
    elif not options.get("drift"):
        assert disk["setter_returned"] is True and disk["native_dispatch_pending"] is False
    repeated = run(receipt_path=str(tmp_path / "replay.json"))
    assert repeated["status"] == "error" and len(calls) == 1
