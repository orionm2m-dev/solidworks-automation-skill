from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest
from scripts import sw_cam_events as events

_staged = Path(__file__).resolve().parents[1] / "sw_cam_mill_levels.py"
if _staged.exists():
    _spec = importlib.util.spec_from_file_location("staged_mill_levels", _staged)
    cam = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(cam)
else:
    from scripts import sw_cam_mill_levels as cam

READS = [
    "QueryInterface.IDispatch.feature", "QueryInterface.ICWMillOperation",
    "ICWMillOperation.GetMachiningDepth", "QueryInterface.ICWMillOperation3",
    "ICWMillOperation3.GetOverrideMachiningDepth", "ICWMillOperation3.GetToolpathParam",
    "QueryInterface.ICWToolpathParam", "ICWToolpathParam.GetToolpathParameters",
    "ICWMillOperation3.GetSetupParameters", "QueryInterface.ICWPosition",
    "ICWPosition.GetCoordinates", "QueryInterface.ICWUnitVector", "ICWUnitVector.GetCoordinates",
]


def operation(native_id=114, index=0, **kw):
    return dict(native_id=native_id, setup_index=0, operation_index=index,
        mill_operation_type=index, base_operation_type=1, suppressed=False,
        linked_feature_ids=[111], toolpath_generated=index == 0,
        toolpath_record_counts=[68] if index == 0 else []) | kw


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path = tmp_path / "qualification.sldprt"
    path.write_bytes(b"saved single-feature MILL qualification")
    receipt = tmp_path / "read.json"
    sha = cam._file_hash(path)
    current = dict(
        document=dict(path=str(path), title=path.name, type=1, needs_save=False),
        saved_file_sha256=sha, current_machine=dict(machine_type=1, name="Mill"),
        mill_catalogue=[dict(machine_type=1, name="Mill")],
        feature_setups=[dict(native_id=64, feature_count=1)],
        operation_counts=[2], operation_setup_count=1, material_raw="6061-T6",
        selected_feature=dict(native_id=111, volume_type=6, depth_native=3.),
        operations=[operation(), operation(115, 1)])
    control = dict(on_call=None, on_capture=None, on_exit=None, values={})
    data = dict(subscribed=False, active=False, disconnected=False, event_count=0,
        overflow=0, callback_errors=[], callback_error_count=0,
        subscription_error=None, disconnect_errors=[])
    seen = []

    class Session:
        def __enter__(self):
            data.update(subscribed=True, active=True, disconnected=False)
            return self

        def __exit__(self, *_):
            data.update(active=False, disconnected=True)
            if control["on_exit"]:
                control["on_exit"]()

        def summary(self):
            return deepcopy(data)

    def called(label, default):
        assert data["active"]
        durable = json.loads(receipt.read_text())
        assert durable["phase"] == label
        assert durable["native_dispatch_pending"] is True
        assert durable["native_reads"][-1]["attempted"] is True
        assert durable["native_reads"][-1]["returned"] is False
        assert all(row["returned"] and row["validated"] for row in durable["native_reads"][:-1])
        seen.append(label)
        if control["on_call"]:
            control["on_call"](label)
        return control["values"].get(label, default)

    feature, dispatch, raw_op, other, transform = (object() for _ in range(5))
    origin = N(GetCoordinates=Mock(side_effect=lambda: called("ICWPosition.GetCoordinates", (0., 0., 0.))))
    vector = N(GetCoordinates=Mock(side_effect=lambda: called("ICWUnitVector.GetCoordinates", (0., 0., 2.))))
    params = N(GetToolpathParameters=Mock(side_effect=lambda: called(
        "ICWToolpathParam.GetToolpathParameters", (False, False, False, 0, False, 19., 22.))))
    base = N(GetMachiningDepth=Mock(side_effect=lambda f: called("ICWMillOperation.GetMachiningDepth", 3.)))
    op3 = N(
        GetOverrideMachiningDepth=Mock(side_effect=lambda f: called("ICWMillOperation3.GetOverrideMachiningDepth", False)),
        GetToolpathParam=Mock(side_effect=lambda: called("ICWMillOperation3.GetToolpathParam", params)),
        GetSetupParameters=Mock(side_effect=lambda: called("ICWMillOperation3.GetSetupParameters", (transform, origin, vector))))
    typed_objects = {"ICWMillOperation": base, "ICWMillOperation3": op3,
                     "ICWToolpathParam": params, "ICWPosition": origin, "ICWUnitVector": vector}
    expected_raw = {"ICWMillOperation": raw_op, "ICWMillOperation3": raw_op,
                    "ICWToolpathParam": params, "ICWPosition": origin, "ICWUnitVector": vector}

    def typed(raw, name, _):
        assert raw is expected_raw[name]
        return called("QueryInterface." + name, typed_objects[name])

    def capture(*_, **kw):
        assert data["active"]
        kw["check"]()
        if control["on_capture"]:
            control["on_capture"]()
        kw["check"]()
        kw["diagnostic"].update(state=deepcopy(current))
        return deepcopy(current), dict(selected_feature=feature, operations={114: raw_op, 115: other})

    captures = Mock(side_effect=capture)
    bootstrap = Mock(return_value=object())
    sw = N(GetProcessID=Mock(return_value=62876))
    monkeypatch.setattr(cam, "capture_mill_feature_state", captures)
    monkeypatch.setattr(cam, "_bootstrap", bootstrap)
    monkeypatch.setattr(cam, "document_snapshot", lambda *_: deepcopy(current["document"]))
    monkeypatch.setattr(cam, "_typed", typed)
    monkeypatch.setattr(cam, "_dispatch_feature", lambda f: called("QueryInterface.IDispatch.feature", dispatch) if f is feature else None)
    monkeypatch.setattr(events, "CamMessageSession", lambda *_: Session())

    def run(**kw):
        args = dict(process_id=62876, expected_document_path=str(path), expected_source_sha256=sha,
            expected_feature_native_id=111, expected_operation_native_id=114,
            expected_mill_operation_type=0, expected_toolpath_record_counts=[68],
            expected_ungenerated_operation_ids=[115],
            qualification_only=True, acknowledge_disposable_copy=True, receipt_path=str(receipt))
        return cam.inspect_mill_operation_levels(sw, "clsid", "tlb", **(args | kw))

    return N(**locals())


def test_read_only_exact_sequence_two_snapshots_and_persisted_results(probe):
    out = probe.run()
    assert out["status"] == "ok" and out["readback_verified"] and out["levels_read_complete"]
    assert probe.seen == READS and probe.captures.call_count == 2
    assert out["before"] == out["after"] == probe.current
    assert out["levels"]["machining_depth_native"] == 3.
    assert out["levels"]["override_machining_depth"] is False
    assert out["levels"]["toolpath_parameters"]["start_Z_native"] == 22.
    assert out["setup"]["axis_native"] == [0., 0., 2.]
    assert out["setup"]["axis_normalized_for_report_only"] == [0., 0., 1.]
    assert all(row["validated"] and row["returned"] for row in out["native_reads"])
    for flag in ("may_continue", "mutation_attempted", "model_saved", "GTP_attempted",
                 "record_access_attempted", "export_attempted", "simulation_attempted",
                 "units_verified", "physical_depth_verified", "production_qualified",
                 "post_cleanup_CAM_getters"):
        assert out[flag] is False
    probe.base.GetMachiningDepth.assert_called_once_with(probe.dispatch)
    probe.op3.GetOverrideMachiningDepth.assert_called_once_with(probe.dispatch)
    assert out["messages"]["disconnected"] and json.loads(probe.receipt.read_text()) == out


@pytest.mark.parametrize("label", READS)
def test_first_native_failure_stops_and_preserves_return_history(probe, label):
    def fail(name):
        if name == label:
            raise RuntimeError("controlled native failure")
    probe.control["on_call"] = fail
    out = probe.run()
    assert out["status"] == "error" and out["failed_phase"] == label
    assert out["readback_verified"] is False and probe.captures.call_count == 1
    assert probe.seen == READS[:READS.index(label) + 1]
    assert out["native_reads"][-1]["raised"] is True
    assert out["native_reads"][-1]["returned"] is False
    assert json.loads(probe.receipt.read_text()) == out
    probe.run()
    assert probe.seen == READS[:READS.index(label) + 1]


@pytest.mark.parametrize(("label", "value"), [
    ("ICWMillOperation.GetMachiningDepth", float("nan")),
    ("ICWMillOperation.GetMachiningDepth", True),
    ("ICWMillOperation3.GetOverrideMachiningDepth", 0),
    ("ICWMillOperation3.GetToolpathParam", None),
    ("ICWToolpathParam.GetToolpathParameters", (False,) * 6),
    ("ICWToolpathParam.GetToolpathParameters", (False, False, False, True, False, 19., 22.)),
    ("ICWToolpathParam.GetToolpathParameters", (False, False, False, 0, 0, 19., 22.)),
    ("ICWToolpathParam.GetToolpathParameters", (False, False, False, 0, False, float("inf"), 22.)),
    ("ICWMillOperation3.GetSetupParameters", (object(), object())),
    ("ICWMillOperation3.GetSetupParameters", (object(), None, object())),
    ("ICWMillOperation3.GetSetupParameters", (None, object(), object())),
    ("ICWPosition.GetCoordinates", (0., 0.)),
    ("ICWUnitVector.GetCoordinates", (0., False, 1.)),
    ("QueryInterface.ICWUnitVector", None),
])
def test_native_shape_type_and_finite_validation_precedes_next_call(probe, label, value):
    probe.control["values"][label] = value
    out = probe.run()
    assert out["status"] == "error" and out["failed_phase"] == label
    assert probe.seen == READS[:READS.index(label) + 1]
    row = out["native_reads"][-1]
    assert row["returned"] is True and row["validated"] is False
    assert json.loads(probe.receipt.read_text()) == out


def test_zero_axis_does_not_claim_complete_or_run_final_capture(probe):
    probe.control["values"]["ICWUnitVector.GetCoordinates"] = (0., 0., 0.)
    out = probe.run()
    assert out["status"] == "error" and not out["levels_read_complete"]
    assert probe.captures.call_count == 1


@pytest.mark.parametrize(("key", "value"), [
    ("process_id", True), ("expected_source_sha256", "stale"),
    ("expected_operation_native_id", 0), ("expected_mill_operation_type", True),
    ("expected_toolpath_record_counts", [True]), ("expected_toolpath_record_counts", [0]),
    ("expected_toolpath_record_counts", [100001]), ("expected_toolpath_record_counts", (68,)),
    ("expected_ungenerated_operation_ids", [115, 115]),
    ("expected_ungenerated_operation_ids", [114]), ("expected_ungenerated_operation_ids", [False]),
    ("qualification_only", False), ("acknowledge_disposable_copy", 1),
    ("message_policy", "silent"), ("expected_document_path", "relative.sldprt"),
])
def test_invalid_inputs_do_not_bootstrap(probe, key, value):
    out = probe.run(**{key: value})
    assert out["status"] == "error" and not probe.seen
    probe.bootstrap.assert_not_called()


@pytest.mark.parametrize("case", [
    "dirty", "wrong_pid", "file_hash", "wrong_type", "wrong_link",
    "selected_not_generated", "wrong_records", "other_generated", "other_records",
    "extra_operation", "missing_operation", "duplicate_operation", "event",
])
def test_preconditions_block_all_new_native_reads(probe, case):
    row = probe.current["operations"][0]
    if case == "dirty": probe.current["document"]["needs_save"] = True
    if case == "wrong_pid": probe.sw.GetProcessID.return_value = 8
    if case == "file_hash": probe.path.write_bytes(b"changed")
    if case == "wrong_type": row["mill_operation_type"] = 1
    if case == "wrong_link": row["linked_feature_ids"] = [112]
    if case == "selected_not_generated": row["toolpath_generated"] = False
    if case == "wrong_records": row["toolpath_record_counts"] = [67]
    if case == "other_generated": probe.current["operations"][1]["toolpath_generated"] = True
    if case == "other_records": probe.current["operations"][1]["toolpath_record_counts"] = [1]
    if case == "extra_operation": probe.current["operations"].append(operation(116, 2))
    if case == "missing_operation": probe.current["operations"].pop()
    if case == "duplicate_operation": probe.current["operations"].append(deepcopy(row))
    if case == "event": probe.control["on_capture"] = lambda: probe.data.update(event_count=1)
    out = probe.run()
    assert out["status"] == "error" and not probe.seen and not out["native_read_attempted"]


@pytest.mark.parametrize("case", ["event", "dirty", "file"])
def test_each_boundary_stops_after_native_return_before_followup(probe, case):
    def change(label):
        if label == READS[2]:
            if case == "event": probe.data["event_count"] = 1
            if case == "dirty": probe.current["document"]["needs_save"] = True
            if case == "file": probe.path.write_bytes(b"changed")
    probe.control["on_call"] = change
    out = probe.run()
    assert out["status"] == "error" and not out["readback_verified"]
    assert probe.seen == READS[:3] and out["native_reads"][-1]["returned"]
    assert probe.captures.call_count == 1


@pytest.mark.parametrize("case", ["feature", "other_operation", "material"])
def test_final_snapshot_rejects_ram_changes_with_clean_document(probe, case):
    def change():
        if probe.captures.call_count == 2:
            if case == "feature": probe.current["selected_feature"]["depth_native"] = 4.
            if case == "other_operation": probe.current["operations"][1]["mill_operation_type"] = 8
            if case == "material": probe.current["material_raw"] = "changed"
    probe.control["on_capture"] = change
    out = probe.run()
    assert out["status"] == "error" and not out["readback_verified"]
    assert probe.seen == READS and probe.captures.call_count == 2
    assert out["before"] != out["after"]


@pytest.mark.parametrize("case", ["event", "disconnect", "document"])
def test_cleanup_failure_does_not_issue_cam_reads(probe, case):
    def change():
        if case == "event": probe.data["event_count"] = 1
        if case == "disconnect": probe.data["disconnected"] = False
        if case == "document": probe.current["document"]["title"] = "changed"
    probe.control["on_exit"] = change
    out = probe.run()
    assert out["status"] == "error" and not out["readback_verified"]
    assert probe.seen == READS and probe.captures.call_count == 2


def test_receipt_intent_failure_prevents_new_native_dispatch(probe, monkeypatch):
    writer = cam._write_receipt
    def write(path, report, **kw):
        if report["native_dispatch_pending"]:
            raise OSError("intent not durable")
        return writer(path, report, **kw)
    monkeypatch.setattr(cam, "_write_receipt", write)
    out = probe.run()
    assert out["status"] == "error" and probe.seen == []
    assert not out["native_read_attempted"]


def test_existing_receipt_rejects_even_before_bootstrap(probe):
    probe.receipt.write_text('{"previous":"evidence"}')
    out = probe.run()
    assert out["status"] == "error" and not probe.seen
    probe.bootstrap.assert_not_called()
    assert json.loads(probe.receipt.read_text()) == {"previous": "evidence"}
