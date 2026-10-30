"""Offline checks for one bounded presentation restoration."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ["SOLIDWORKS_TEST_RUNTIME"]) if os.environ.get("SOLIDWORKS_TEST_RUNTIME") else ROOT
spec = importlib.util.spec_from_file_location("restore_under_test", ROOT / "scripts/sw_assembly_presentation_restore.py")
restore = importlib.util.module_from_spec(spec); spec.loader.exec_module(restore)
spec = importlib.util.spec_from_file_location("axis_test_reuse", RUNTIME / "tests/test_sw_explode_axis_rebind.py")
reuse = importlib.util.module_from_spec(spec); spec.loader.exec_module(reuse)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def scene(tmp_path, monkeypatch):
    state = reuse.scene.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setattr(restore, "axes", reuse.repair)
    assert reuse.prepare(state)["status"] == "ok"
    prior = reuse.apply(state)
    assert prior["repair_verified"] is True
    state["snapshot"]["components"][0]["matrix"][11] = .09
    prior.update(status="uncertain", phase="failed", failed_phase="setter_verified",
                 error={"type": "ValueError", "message": "Final structure, reverse flags or dependencies differ"},
                 repair_verified=False, after_snapshot=restore.audit._mapped_snapshot(state["snapshot"], {}))
    prior.pop("snapshot_matches_expected", None)
    prior_path = tmp_path / "prior.json"
    prior_path.write_text(json.dumps(prior), encoding="utf-8")
    state.update(prior=prior, prior_path=prior_path, calls=[], mode=None)
    def collapse(exploded, view):
        assert exploded is False and view == "Existing"
        receipt = json.loads(Path(state["restoration_receipt"]).read_text(encoding="utf-8"))
        assert receipt["mutation_attempted"] is True and receipt["native_dispatch_pending"] is True
        assert Path(str(state["restore_prepare_path"])+".apply_attempt.json").exists()
        state["calls"].append((exploded, view))
        if state["mode"] == "raise_before": raise RuntimeError("native outcome unknown")
        if state["mode"] != "noop": state["snapshot"] = deepcopy(state["expected"])
        if state["mode"] == "raise_after": raise RuntimeError("native outcome unknown")
        if state["mode"] == "axis":
            state["snapshot"]["native_step_sequence"][0]["angle_rad"] = 1.0
        if state["mode"] == "flags": state["flags"][0]["reverse_rotation"] = False
        if state["mode"] == "dependency": state["part"].write_bytes(b"changed")
        if state["mode"] == "source": state["top"].write_bytes(b"changed")
        if state["mode"] == "dirty": state["dirty"] = False
        if state["mode"] == "configuration": state["model"].ConfigurationManager.ActiveConfiguration.Name = "Other"
        if state["mode"] == "pid": state["pid"] = 43
        if state["mode"] == "path": state["path"] = "Other.SLDASM"
        if state["mode"] == "return_none": return None
        if state["mode"] == "return_int": return 1
        if state["mode"] == "return_false": return False
        return True
    state["model"].ShowExploded2 = collapse
    state["restore_params"] = dict(
        process_id=42, expected_document_path=str(state["top"]), expected_file_sha256=sha(state["top"]),
        prior_rebind_receipt_path=str(prior_path), prior_rebind_receipt_sha256=sha(prior_path),
        explode_view_name="Existing")
    return state


def prepare(state, name="restore_prepare.json", **changes):
    path = state["tmp"] / name
    params = dict(state["restore_params"], action="prepare", receipt_path=str(path))
    params.update(changes)
    result = restore.restore_assembly_presentation(object(), **params)
    state.update(restore_prepare_path=path, restore_prepared=result)
    return result


def apply(state, name="restore_apply.json", **changes):
    path = state["tmp"] / name
    state["restoration_receipt"] = path
    params = dict(state["restore_params"], action="apply", receipt_path=str(path),
                  expected_state_sha256=state["restore_prepared"]["state_sha256"],
                  prepare_receipt_path=str(state["restore_prepare_path"]),
                  prepare_receipt_sha256=sha(state["restore_prepare_path"]))
    params.update(changes)
    return restore.restore_assembly_presentation(object(), **params)


def prior_change(state, change):
    change(state["prior"])
    state["prior_path"].write_text(json.dumps(state["prior"]), encoding="utf-8")
    state["restore_params"]["prior_rebind_receipt_sha256"] = sha(state["prior_path"])


def test_prepare_read_only_apply_exactly_once_and_no_save(scene):
    before = deepcopy(scene["snapshot"])
    result = prepare(scene)
    assert result["status"] == "ok", result.get("error")
    assert scene["snapshot"] == before and scene["calls"] == []
    result = apply(scene)
    assert result["status"] == "review_required", result.get("error")
    assert result["presentation_restored"] and result["snapshot_matches_expected"]
    assert result["reverse_flags_unchanged"] and result["source_files_unchanged"]
    assert scene["calls"] == [(False, "Existing")]
    assert scene["dirty"] is True and result["model_saved"] is False
    assert scene["snapshot"] == scene["expected"]
    assert apply(scene, "replay.json")["status"] == "error"
    assert len(scene["calls"]) == 1


@pytest.mark.parametrize("change", [
    lambda p: p.update(status="ok"), lambda p: p.update(phase="setter_verified"),
    lambda p: p.update(failed_phase="preflight"), lambda p: p.update(native_dispatch_pending=True),
    lambda p: p.update(model_saved=True), lambda p: p.update(mutation_attempted=1),
    lambda p: p.update(repair_verified=True), lambda p: p.update(completed_setters=3),
    lambda p: p.update(completed_setters=True), lambda p: p["error"].update(message="other error"),
    lambda p: p.update(state_sha256="0"*64), lambda p: p["setters"].pop(),
    lambda p: p["setters"][0].update(returned=False), lambda p: p["setters"][0].update(readback_verified=1),
    lambda p: p["setters"][0].update(return_value=True), lambda p: p["setters"][0].update(argument_index=True),
    lambda p: p["setters"][0].update(method="Other"),
    lambda p: p["after_snapshot"]["native_step_sequence"][0].update(angle_rad=3.0),
    lambda p: p["after_snapshot"]["components"][0].update(native_id=44),
    lambda p: p["after_reverse_flags"][0].update(reverse_rotation=False),
    lambda p: p["after_reverse_flags"][0].update(reverse_rotation=1),
    lambda p: p["after_document"].update(needs_save=False),
    lambda p: p["after_document"].update(active_configuration="Other"),
])
def test_ineligible_prior_never_enters_native_mutation(scene, change):
    prior_change(scene, change)
    result = prepare(scene)
    assert result["status"] == "error" and not result["mutation_attempted"]
    assert scene["calls"] == []


@pytest.mark.parametrize("params", [
    {"process_id":True}, {"process_id":0}, {"expected_file_sha256":"0"*64},
    {"prior_rebind_receipt_sha256":"0"*64}, {"explode_view_name":"Other"},
    {"explode_view_name":False}, {"action":"collapse"}, {"expected_state_sha256":"0"*64},
])
def test_bad_request_no_mutation(scene, params):
    assert prepare(scene, **params)["status"] == "error"
    assert scene["calls"] == []


@pytest.mark.parametrize("change", ["pose","step","flags","dirty","pid","kind","config","part","top","prior","baseline"])
def test_changed_prepared_state_stops_before_collapse(scene, change):
    assert prepare(scene)["status"] == "ok"
    if change == "pose": scene["snapshot"]["components"][0]["matrix"][9] = .02
    if change == "step": scene["snapshot"]["native_step_sequence"][0]["distance_m"] = .02
    if change == "flags": scene["flags"][0]["reverse_rotation"] = False
    if change == "dirty": scene["dirty"] = False
    if change == "pid": scene["pid"] = 43
    if change == "kind": scene["kind"] = 1
    if change == "config": scene["model"].ConfigurationManager.ActiveConfiguration.Name = "Other"
    if change in ("part","top","baseline"): scene[change].write_bytes(b"changed")
    if change == "prior": scene["prior_path"].write_text("{}")
    result = apply(scene)
    assert result["status"] == "error" and not result["mutation_attempted"]
    assert scene["calls"] == []


@pytest.mark.parametrize("mode", [
    "noop","raise_before","raise_after","axis","flags","dependency","source","dirty",
    "configuration","pid","path","return_none","return_int","return_false",
])
def test_failed_native_or_readback_stops_without_retry(scene, mode):
    assert prepare(scene)["status"] == "ok"
    scene["mode"] = mode
    result = apply(scene)
    assert result["status"] == "uncertain" and not result["presentation_restored"]
    assert len(scene["calls"]) == 1
    assert result["model_saved"] is False
    assert apply(scene, "new_output.json")["status"] == "error"
    assert len(scene["calls"]) == 1


def test_durable_intent_failure_never_dispatches(scene, monkeypatch):
    assert prepare(scene)["status"] == "ok"
    original = restore._write_receipt
    def writer(path, data, *args, **kwargs):
        if data.get("phase") == "collapse_intent": raise OSError("receipt locked")
        return original(path, data, *args, **kwargs)
    monkeypatch.setattr(restore, "_write_receipt", writer)
    result = apply(scene)
    assert result["status"] == "uncertain" and result["mutation_attempted"] is True
    assert scene["calls"] == []
    assert Path(str(scene["restore_prepare_path"])+".apply_attempt.json").exists()


def test_stale_prepared_digest_rejected(scene):
    assert prepare(scene)["status"] == "ok"
    result = apply(scene, expected_state_sha256="0"*64)
    assert result["status"] == "error" and scene["calls"] == []


def test_source_hash_unchanged_and_same_file_state(scene):
    before = {name:sha(scene[name]) for name in ("top","part","baseline")}
    assert prepare(scene)["status"] == "ok"
    assert apply(scene)["presentation_restored"]
    assert before == {name:sha(scene[name]) for name in before}
