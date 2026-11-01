"""Portable contract tests: fake CAM, synthetic saved receipt, no native execution."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from wall_test_fixtures import failed_wall_receipt

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("apply_all_tested", ROOT / "scripts/sw_cam_wall_apply_all.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def baseline():
    prior = failed_wall_receipt()
    loaded = prior["loaded_context_before"]
    loaded["pocket_parameters"] = deepcopy(prior["configured"]["parameters"])
    loaded["pocket_parameters"]["144"]["finish"]["PerimeterPassType"] = 2
    return loaded


def status(generated=False):
    return dict(operation_native_id=144, feature_native_id=79, tool_native_id=273,
                background_over_before=False, background_over_after=False,
                generated=generated, generated_for_feature=generated,
                record_counts=[800] if generated else [])


class Backend:
    def __init__(self, loaded, report, fail=None):
        self.loaded, self.report, self.fail = loaded, report, fail
        self.calls = []; self.values = {x[0]: deepcopy(x[5]) for x in m.FIELDS}
        self.generated = False; self.saved = False; self.changed = False
    def start(self): self.calls.append("start")
    def boundary(self): pass
    def refresh_dirty(self): pass
    def field(self, spec): return deepcopy(self.values[spec[0]])
    def set_field(self, spec, pending):
        pending(); self.calls.append(spec[0]); self.changed = True
        if self.fail == "pending": raise RuntimeError("call interrupted")
        if self.fail != "readback": self.values[spec[0]] = deepcopy(spec[6])
        if self.fail == "bool_hresult": return False
        if self.fail == spec[0]: return 1
        return 0
    def restrictions(self):
        return dict(LeadInOutApplyToAll=self.values["apply_to_all"],
                    GougeCheck=not (self.fail == "gouge" and self.changed))
    def outcome(self):
        result = status(self.generated)
        if self.fail == "unstable_background" and self.generated:
            result["background_over_after"] = True
        return result
    def generate(self, pending):
        pending(); self.calls.append("GTP")
        self.generated = self.fail != "empty"
        if self.fail == "GTP": return 1
        if self.fail == "GTP_bool": return True
        return 0
    def capture(self):
        state = deepcopy(self.loaded["state"])
        state["document"]["needs_save"] = self.changed and not self.saved
        if self.generated:
            state["operations"][-1].update(toolpath_generated=True, toolpath_record_counts=[800])
        if self.saved: state["saved_file_sha256"] = "b" * 64
        result = dict(state=state, parameters=deepcopy(self.loaded["pocket_parameters"]),
                      startpoints=deepcopy(self.loaded["pocket_startpoints"]),
                      restrictions=self.restrictions())
        if self.fail == "rough_drift" and self.changed:
            result["state"]["operations"][-2]["toolpath_record_counts"] = [1]
        if self.fail == "floor_drift" and self.changed:
            result["parameters"]["144"]["finish"]["BottomFinOpt"] = True
        if self.fail == "save_drift" and self.saved:
            result["state"]["sw_reference"]["solids"][0]["mass_raw"][0] += .1
        return result
    def capture_full(self, label):
        self.calls.append("full:" + label); result = self.capture()
        result["catalogue"] = deepcopy(self.loaded["neck_tool_checkpoint"]["catalogue"])
        return result
    def capture_narrow(self, label):
        self.calls.append("narrow:" + label); return self.capture()
    def save(self):
        self.calls.append("Save"); self.saved = True
        return 1 if self.fail == "save" else 0
    def saved_hash(self, stage):
        self.report["source_transition"] = dict(source_before_sha256="a" * 64,
                                               source_after_sha256="b" * 64, strict_save_return=0)
        return "b" * 64
    def finish(self):
        self.report["messages"] = dict(subscribed=True, disconnected=True, active=False)
    def close(self): self.calls.append("close")


def run(tmp_path, fail=None):
    loaded = baseline()
    report = dict(scope=m.SCOPE, source_path=str(tmp_path / "part.SLDPRT"),
        initial_source_sha256="a" * 64, checkpoint_pin={}, diagnostic_pin={}, plan_pin={},
        loaded_context_before=deepcopy(loaded), actions={}, status="prepared", phase="prepared", mutation_attempted=False,
        model_saved=False, readback_verified=False, **{key: False for key in m.FORBIDDEN})
    journal = m.Journal(report, tmp_path / "receipt.json", tmp_path / "once.json")
    backend = Backend(loaded, report, fail)
    m.run_backend(backend, journal, loaded)
    return report, backend


def test_success_nine_writes_one_gtp_one_save_two_full_captures(tmp_path):
    r, b = run(tmp_path)
    assert r["status"] == "saved_generated_review_required", r.get("issue")
    assert r["model_saved"] and r["readback_verified"] and r["generation_verified"]
    assert set(r["actions"]) == set(m.ACTIONS)
    assert [x for x in b.calls if x in {f[0] for f in m.FIELDS}] == [f[0] for f in m.FIELDS]
    assert b.calls.count("GTP") == b.calls.count("Save") == 1
    assert len([x for x in b.calls if x.startswith("full:")]) == 2
    assert len([x for x in b.calls if x.startswith("narrow:")]) == 2
    assert all(r[key] is False for key in m.FORBIDDEN)


def test_equal_leads_are_explicitly_reapplied(tmp_path):
    assert all(x[5] == x[6] for x in m.LEADS)
    _, b = run(tmp_path)
    assert b.calls.index("apply_to_all") < b.calls.index("lead_in_angle")
    assert all(b.calls.count(x[0]) == 1 for x in m.LEADS)


def test_empty_gtp_is_recorded_without_save_or_replay(tmp_path):
    r, b = run(tmp_path, "empty")
    assert r["status"] == "no_toolpath_no_save" and r["readback_verified"]
    assert not r["model_saved"] and not r["generation_verified"]
    assert r["generated_record_counts"] == [] and r["generation_status"]["generated"] is False
    assert b.calls.count("GTP") == 1 and "Save" not in b.calls
    assert len([x for x in b.calls if x.startswith("full:")]) == 1
    assert (tmp_path / "once.json").is_file()


@pytest.mark.parametrize("fail", ["pending", "readback", "bool_hresult", "apply_to_all", "lead_out_overlap",
                                  "gouge", "rough_drift", "floor_drift"])
def test_partial_or_drift_never_generates(tmp_path, fail):
    r, b = run(tmp_path, fail)
    assert r["status"] == "uncertain" and not r["readback_verified"]
    assert "GTP" not in b.calls and "Save" not in b.calls
    if fail == "readback": assert r["actions"]["field:apply_to_all"]["observed"] is False
    if fail == "pending": assert r["actions"]["field:apply_to_all"]["pending"] is True
    if fail in ("gouge", "rough_drift", "floor_drift"): assert "configured" in r


@pytest.mark.parametrize("fail", ["GTP", "GTP_bool", "unstable_background"])
def test_unconfirmed_generation_never_saves(tmp_path, fail):
    r, b = run(tmp_path, fail)
    assert not r["readback_verified"] and b.calls.count("GTP") == 1 and "Save" not in b.calls


@pytest.mark.parametrize("fail", ["save", "save_drift"])
def test_failed_save_is_not_repeated_or_accepted(tmp_path, fail):
    r, b = run(tmp_path, fail)
    assert not r["readback_verified"] and b.calls.count("Save") == 1
    if fail == "save_drift": assert "final" in r


def test_marker_prevents_second_candidate_even_with_new_output_path(tmp_path):
    r, _ = run(tmp_path, "empty")
    second = deepcopy(r); second["actions"] = {}
    j = m.Journal(second, tmp_path / "renamed.json", tmp_path / "once.json")
    with pytest.raises(ValueError): j.pending("field:apply_to_all")


def test_writer_rejects_gouge_and_unapproved_geometry_without_native_calls():
    b = object.__new__(m.NativeBackend)
    for spec in (("gouge", "ICWFinishMillOp3", "GougeCheck", "GougeCheck", "property", True, False),
                 m.SPEC[:-1] + (False,), m.LEADS[0][:-1] + (45.,), m.SPEC[:-1] + (1,)):
        with pytest.raises(ValueError): b.set_field(spec, lambda: pytest.fail("dispatch forbidden"))
    with pytest.raises(RuntimeError): b.assign(None)


def test_verified_lead_scope_delegates_existing_raw_writer():
    b = object.__new__(m.NativeBackend)
    with patch.object(m.original.NativeBackend, "set_field", return_value=0) as writer:
        for spec in m.FIELDS: assert b.set_field(spec, None) == 0
    assert writer.call_count == 9


def test_request_rejects_unowned_or_extra_fields_before_loading(tmp_path):
    params = {key: "a" * 64 if key.endswith("_sha256") else str(tmp_path / key)
              for key in m.PARAMS}
    params.update(process_id=7, addin_clsid="{00000000-0000-0000-0000-000000000000}",
                  module_sha256=m._file_hash(m.__file__))
    request = dict(action="apply_wall_leads_to_all", params=params)
    assert m.validate_request(request)["process_id"] == 7
    for key, value in (("process_id", True), ("process_id", 0), ("module_sha256", "b" * 64)):
        bad = deepcopy(request); bad["params"][key] = value
        with pytest.raises(ValueError): m.validate_request(bad)
    request["params"]["GougeCheck"] = False
    with pytest.raises(ValueError): m.validate_request(request)


def test_cli_validate_only_propagates_without_native_dispatch(tmp_path, capsys):
    request = tmp_path / "request.json"; request.write_text("{}")
    with patch.object(m, "dispatch_request", return_value=dict(status="validated_offline", native_called=False)) as dispatch:
        assert m.main(["--request", str(request), "--validate-only"]) == 0
    dispatch.assert_called_once_with({}, validate_only=True)
    assert json.loads(capsys.readouterr().out)["native_called"] is False


def test_saved_terminal_produces_export_context_and_rejects_empty(tmp_path):
    r, _ = run(tmp_path)
    r["phase_proofs_verified"] = True
    for key in m.group.CURRENT_KEYS:
        r["loaded_context_before"].setdefault(key, None)
    context = m.validate_terminal(r)
    assert context["generated_pocket_finish"]["record_counts"] == [800]
    assert context["generated_pocket_finish"]["lead_apply_to_all"] is True
    assert context["wall_apply_all_recipe"]["restrictions"]["GougeCheck"] is True
    empty = deepcopy(r); empty.update(status="no_toolpath_no_save", model_saved=False, generation_verified=False)
    with pytest.raises(ValueError): m.validate_terminal(empty)


@pytest.mark.parametrize("field,new", [("model_saved", False), ("generation_verified", False),
                                        ("phase_proofs_verified", False), ("production_qualified", True)])
def test_terminal_tampering_cannot_become_export_authority(tmp_path, field, new):
    r, _ = run(tmp_path); r["phase_proofs_verified"] = True
    r[field] = new
    with pytest.raises(ValueError): m.validate_terminal(r)


def test_completed_loader_real_synthetic_files_source_and_marker(tmp_path):
    r, _ = run(tmp_path); r["phase_proofs_verified"] = True
    for key in m.group.CURRENT_KEYS: r["loaded_context_before"].setdefault(key, None)
    source = tmp_path / "saved part.SLDPRT"; source.write_bytes(b"synthetic saved model")
    sha = m._file_hash(source)
    r.update(source_path=str(source), process_id=7, module_pin=m.common._pin(m.__file__),
             saved_source_sha256=sha, live_pins=[], offline_proof_pins=[], bootstrap_export_pins=[],
             checkpoint_pin={"path": str(tmp_path / "old.json"), "sha256": "c" * 64})
    r["source_transition"]["source_after_sha256"] = sha
    r["save_stage"]["saved_file_sha256"] = sha
    r["final"]["state"]["saved_file_sha256"] = sha
    r["checkpoint_digest"] = m._digest(m.group.current_projection(m.validate_terminal(r)))
    receipt = tmp_path / "completed.json"; marker = tmp_path / "terminal.json"
    marker.write_text(json.dumps(m.Journal(r, receipt, marker).marker_state()))
    r["marker_pin"] = m.common._pin(marker); receipt.write_text(json.dumps(r))
    with patch.object(m, "marker_path", return_value=marker):
        context = m.load_completed(str(receipt), m._file_hash(receipt), process_id=7,
            expected_document_path=str(source), expected_source_sha256=sha)
        assert context["generated_pocket_finish"]["native_id"] == 144
        with pytest.raises(ValueError):
            m.load_completed(str(receipt), m._file_hash(receipt), process_id=8,
                expected_document_path=str(source), expected_source_sha256=sha)
        marker.write_text("{}")
        with pytest.raises(ValueError):
            m.load_completed(str(receipt), m._file_hash(receipt), process_id=7,
                expected_document_path=str(source), expected_source_sha256=sha)
