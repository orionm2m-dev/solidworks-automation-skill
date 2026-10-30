from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest
from scripts import sw_cam_events as events

_staged = Path(__file__).resolve().parents[1] / "scripts/sw_cam_mill_rough_boundary.py"
if _staged.exists():
    _spec = importlib.util.spec_from_file_location("staged_mill_rough_boundary", _staged)
    cam = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(cam)
else:
    from scripts import sw_cam_mill_rough_boundary as cam

READS = [
    "QueryInterface.IDispatch.feature", "QueryInterface.ICWRghMillOp",
    "ICWRghMillOp.GetToolDiameterPercent", "ICWRghMillOp.SideAllow",
    "ICWRghMillOp.GetStepOver", "ICWRghMillOp.PocketMethod",
    "ICWRghMillOp.GetContainType", "ICWRghMillOp.GetContainAllowance",
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

    feature, dispatch, raw_op, other = (object() for _ in range(4))

    class Rough:
        def __init__(self):
            self.GetToolDiameterPercent = Mock(side_effect=lambda f: called(
                "ICWRghMillOp.GetToolDiameterPercent", 75.))
            self.GetStepOver = Mock(side_effect=lambda: called("ICWRghMillOp.GetStepOver", (True, 40.)))
            self.GetContainType = Mock(side_effect=lambda: called("ICWRghMillOp.GetContainType", 0))
            self.GetContainAllowance = Mock(side_effect=lambda: called("ICWRghMillOp.GetContainAllowance", .1))

        @property
        def SideAllow(self):
            return called("ICWRghMillOp.SideAllow", .25)

        @property
        def PocketMethod(self):
            return called("ICWRghMillOp.PocketMethod", 2)

    rough = Rough()
    typed_objects = {"ICWRghMillOp": rough}
    expected_raw = {"ICWRghMillOp": raw_op}

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
    model = N(
        GetPathName=Mock(side_effect=lambda: current["document"]["path"]),
        GetTitle=Mock(side_effect=lambda: current["document"]["title"]),
        GetType=Mock(side_effect=lambda: current["document"]["type"]),
        GetSaveFlag=Mock(side_effect=lambda: current["document"]["needs_save"]))
    sw = N(GetProcessID=Mock(return_value=62876), ActiveDoc=model)
    monkeypatch.setattr(cam, "capture_mill_feature_state", captures)
    monkeypatch.setattr(cam, "_bootstrap", bootstrap)
    monkeypatch.setattr(cam, "_typed", typed)
    monkeypatch.setattr(cam, "_dispatch_feature", lambda f: called("QueryInterface.IDispatch.feature", dispatch) if f is feature else None)
    monkeypatch.setattr(events, "CamMessageSession", lambda *_: Session())

    def run(**kw):
        args = dict(process_id=62876, expected_document_path=str(path), expected_source_sha256=sha,
            expected_feature_native_id=111, expected_operation_native_id=114,
            expected_mill_operation_type=0, expected_toolpath_record_counts=[68],
            expected_ungenerated_operation_ids=[115],
            qualification_only=True, acknowledge_disposable_copy=True, receipt_path=str(receipt))
        return cam.inspect_mill_rough_boundary(sw, "clsid", "tlb", **(args | kw))

    return N(**locals())


def test_read_only_exact_sequence_two_snapshots_and_persisted_results(probe):
    out = probe.run()
    assert out["status"] == "ok" and out["readback_verified"] and out["boundary_parameters_read_complete"]
    assert probe.seen == READS and probe.captures.call_count == 2
    assert out["before"] == out["after"] == probe.current
    assert out["boundary_parameters"] == dict(
        tool_diameter_percent_native=75., side_allowance_native=.25,
        stepover=dict(is_percent=True, value_native=40.), pocket_method_raw=2,
        contain_type_raw=0, contain_allowance_native=.1)
    assert out["air_segment_semantics_verified"] is False
    assert out["boundary_geometry_verified"] is False
    assert all(row["validated"] and row["returned"] for row in out["native_reads"])
    for flag in ("may_continue", "mutation_attempted", "model_saved", "GTP_attempted",
                 "record_access_attempted", "export_attempted", "simulation_attempted",
                 "units_verified", "physical_depth_verified", "production_qualified",
                 "post_cleanup_CAM_getters"):
        assert out[flag] is False
    probe.rough.GetToolDiameterPercent.assert_called_once_with(probe.dispatch)
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
    ("ICWRghMillOp.GetToolDiameterPercent", float("nan")),
    ("ICWRghMillOp.GetToolDiameterPercent", True),
    ("ICWRghMillOp.SideAllow", float("inf")),
    ("ICWRghMillOp.SideAllow", "0.25"),
    ("ICWRghMillOp.GetStepOver", (False,)),
    ("ICWRghMillOp.GetStepOver", (0, 40.)),
    ("ICWRghMillOp.GetStepOver", (False, True)),
    ("ICWRghMillOp.GetStepOver", (True, float("nan"))),
    ("ICWRghMillOp.PocketMethod", False),
    ("ICWRghMillOp.PocketMethod", 2.0),
    ("ICWRghMillOp.GetContainType", 2147483648),
    ("ICWRghMillOp.GetContainAllowance", None),
    ("QueryInterface.ICWRghMillOp", None),
])
def test_native_shape_type_and_finite_validation_precedes_next_call(probe, label, value):
    probe.control["values"][label] = value
    out = probe.run()
    assert out["status"] == "error" and out["failed_phase"] == label
    assert probe.seen == READS[:READS.index(label) + 1]
    row = out["native_reads"][-1]
    assert row["returned"] is True and row["validated"] is False
    assert json.loads(probe.receipt.read_text()) == out


def test_raw_settings_are_not_normalized_or_declared_physical_proof(probe):
    probe.control["values"]["ICWRghMillOp.GetToolDiameterPercent"] = -2.
    probe.control["values"]["ICWRghMillOp.SideAllow"] = -.5
    probe.control["values"]["ICWRghMillOp.GetStepOver"] = (False, .8)
    out = probe.run()
    assert out["status"] == "ok"
    assert out["boundary_parameters"]["tool_diameter_percent_native"] == -2.
    assert out["boundary_parameters"]["side_allowance_native"] == -.5
    assert out["boundary_parameters"]["stepover"] == dict(is_percent=False, value_native=.8)
    assert not out["air_segment_semantics_verified"] and not out["boundary_geometry_verified"]


@pytest.mark.parametrize(("key", "value"), [
    ("process_id", True), ("expected_source_sha256", "stale"),
    ("expected_operation_native_id", 0), ("expected_mill_operation_type", True),
    ("expected_mill_operation_type", 1),
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


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_strict_document_type_blocks_bootstrap(probe, value):
    probe.current["document"]["type"] = value
    out = probe.run()
    assert out["status"] == "error" and not probe.seen
    probe.bootstrap.assert_not_called()


@pytest.mark.parametrize("value", [0, 1, None, "False", ""])
def test_strict_raw_dirty_flag_blocks_bootstrap(probe, value):
    probe.current["document"]["needs_save"] = value
    out = probe.run()
    assert out["status"] == "error" and not probe.seen
    probe.bootstrap.assert_not_called()


def test_missing_raw_document_blocks_bootstrap(probe):
    probe.sw.ActiveDoc = None
    out = probe.run()
    assert out["status"] == "error" and not probe.seen
    probe.bootstrap.assert_not_called()
