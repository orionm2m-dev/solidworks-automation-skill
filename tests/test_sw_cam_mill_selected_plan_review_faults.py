"""Independent receipt-loss and evidence-drift tests; no native application calls."""
import json

import pytest

from test_selected_plan import engine, m, SOURCE, SAVED


def ready_action(engine, action):
    if action == "save_checked":
        plan = engine.run()
        assert plan["readback_verified"]
        engine.plan = plan
        engine.plan_pin = {"sha256": SOURCE}
    return len(engine.calls)


@pytest.mark.parametrize("action", ["plan_once", "save_checked"])
def test_intent_receipt_failure_prevents_native_dispatch(engine, monkeypatch, action):
    calls_before = ready_action(engine, action)
    write = m._write_receipt

    def fail_intent(path, report, **kwargs):
        if report["action"] == action and report["native_dispatch_pending"]:
            raise OSError("intent receipt unavailable")
        return write(path, report, **kwargs)

    monkeypatch.setattr(m, "_write_receipt", fail_intent)
    result = engine.run(action)
    assert len(engine.calls) == calls_before
    assert not result["readback_verified"]
    assert not result["model_saved"]
    assert not result["native_call_returned"]


@pytest.mark.parametrize("action", ["plan_once", "save_checked"])
def test_lost_native_return_receipt_remains_uncertain_without_replay(engine, monkeypatch, action):
    calls_before = ready_action(engine, action)
    write = m._write_receipt

    def fail_return(path, report, **kwargs):
        if report["action"] == action and report["phase"] == "native_returned":
            raise OSError("native return receipt unavailable")
        return write(path, report, **kwargs)

    monkeypatch.setattr(m, "_write_receipt", fail_return)
    result = engine.run(action)
    assert len(engine.calls) == calls_before + 1
    assert result["native_call_returned"]
    assert result["status"] == "uncertain"
    assert not result["readback_verified"]
    assert not result["model_saved"]
    assert not result["GTP_attempted"]


@pytest.mark.parametrize("action", ["plan_once", "save_checked"])
def test_lost_final_success_receipt_cannot_claim_saved_or_verified(engine, monkeypatch, tmp_path, action):
    calls_before = ready_action(engine, action)
    write = m._write_receipt

    def fail_success(path, report, **kwargs):
        if report["action"] == action and report["readback_verified"]:
            raise OSError("final success receipt unavailable")
        return write(path, report, **kwargs)

    monkeypatch.setattr(m, "_write_receipt", fail_success)
    result = engine.run(action)
    assert len(engine.calls) == calls_before + 1
    assert result["status"] == "uncertain"
    assert not result["readback_verified"]
    assert not result["model_saved"]
    latest = max(tmp_path.glob("*.json"), key=lambda p: int(p.stem))
    saved_receipt = json.loads(latest.read_text(encoding="utf-8"))
    assert not saved_receipt["readback_verified"]
    if action == "save_checked":
        # Native save happened; loss of its evidence must not cause another save.
        assert engine.current["saved_file_sha256"] == SAVED
        assert engine.current["document"]["needs_save"] is False


def test_evidence_drift_after_capture_stops_before_mutation(engine, monkeypatch):
    capture = m.capture_selected_plan
    drift = {"changed": False}

    def guarded_files():
        if drift["changed"]:
            raise ValueError("pinned evidence changed")

    def capture_then_drift(*args, **kwargs):
        result = capture(*args, **kwargs)
        drift["changed"] = True
        return result

    monkeypatch.setattr(engine.evidence, "check_files", guarded_files)
    monkeypatch.setattr(m, "capture_selected_plan", capture_then_drift)
    result = engine.run()
    assert result["status"] == "error"
    assert not result["mutation_attempted"]
    assert not engine.calls


def test_evidence_drift_after_gop_never_replays_or_saves(engine, monkeypatch):
    member = m._member
    drift = {"changed": False}

    def guarded_files():
        if drift["changed"]:
            raise ValueError("pinned evidence changed")

    def member_then_drift(obj, name, *args):
        value = member(obj, name, *args)
        if name == "GenerateOpPlan":
            drift["changed"] = True
        return value

    monkeypatch.setattr(engine.evidence, "check_files", guarded_files)
    monkeypatch.setattr(m, "_member", member_then_drift)
    result = engine.run()
    assert result["status"] == "uncertain"
    assert engine.calls == [("feature79", "GenerateOpPlan", (1,))]
    assert not result["readback_verified"]
    assert not result["model_saved"]


def test_save_return_then_unreadable_file_hash_stays_uncertain(engine, monkeypatch):
    ready_action(engine, "save_checked")
    file_hash = m._file_hash

    def fail_after_save(path):
        if engine.current["saved_file_sha256"] == SAVED:
            raise OSError("saved file temporarily unreadable")
        return file_hash(path)

    monkeypatch.setattr(m, "_file_hash", fail_after_save)
    result = engine.run("save_checked")
    assert result["status"] == "uncertain"
    assert engine.calls == [
        ("feature79", "GenerateOpPlan", (1,)),
        ("app", "SaveActiveDocument", ()),
    ]
    assert not result["readback_verified"]
    assert not result["save_readback_verified"]
    assert not result["model_saved"]


def test_cleanup_failure_after_delta_verification_never_claims_success(engine, monkeypatch):
    import scripts.sw_cam_events as events

    current_session = events.CamMessageSession

    class BadCleanup(current_session):
        def summary(self):
            result = super().summary()
            if result.get("disconnected"):
                result["disconnect_errors"] = ["disconnect failure"]
            return result

    monkeypatch.setattr(events, "CamMessageSession", BadCleanup)
    result = engine.run()
    assert result["status"] == "uncertain"
    assert engine.calls == [("feature79", "GenerateOpPlan", (1,))]
    assert not result["readback_verified"]
    assert not result["operation_delta_verified"]
    assert not result["model_saved"]
