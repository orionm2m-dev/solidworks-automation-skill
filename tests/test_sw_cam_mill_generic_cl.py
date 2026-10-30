"""Bounded MILL output qualification; no application or CAM connection."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest
from scripts import sw_cam_events as events

_staged = Path(__file__).resolve().parents[1] / "sw_cam_mill_generic_cl.py"
if _staged.exists():
    _spec = importlib.util.spec_from_file_location("staged_mill_generic_cl", _staged)
    cam = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(cam)
else:
    from scripts import sw_cam_mill_generic_cl as cam


def operation(native_id=214, index=0, **kw):
    return dict(native_id=native_id, setup_index=0, operation_index=index,
        mill_operation_type=index, base_operation_type=1, suppressed=False,
        linked_feature_ids=[211], toolpath_generated=index == 0,
        toolpath_record_counts=[68] if index == 0 else []) | kw


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path = tmp_path / "qualification.sldprt"
    path.write_bytes(b"saved single-feature MILL qualification")
    output = tmp_path / "exclusive" / "machine.cl"
    receipt = tmp_path / "export.json"
    sha = cam._file_hash(path)
    current = dict(
        document=dict(path=str(path), title=path.name, type=1, needs_save=False),
        saved_file_sha256=sha, current_machine=dict(machine_type=1, name="Mill"),
        feature_setups=[dict(native_id=64, feature_count=1)],
        operation_counts=[2], operation_setup_count=1, material_raw="6061-T6",
        selected_feature=dict(native_id=211, volume_type=6, depth_native=3.),
        operations=[operation(), operation(215, 1)])
    control = dict(on_call=None, on_capture=None, on_enter=None, on_exit=None, on_post=None)
    data = dict(subscribed=False, active=False, disconnected=False, event_count=0,
        overflow=0, callback_errors=[], callback_error_count=0,
        subscription_error=None, disconnect_errors=[])
    seen = []
    class Session:
        def __enter__(self):
            data.update(subscribed=True, active=True, disconnected=False)
            if control["on_enter"]: control["on_enter"]()
            return self
        def __exit__(self, *_):
            data.update(active=False, disconnected=True)
            if control["on_exit"]: control["on_exit"]()
        def summary(self): return deepcopy(data)
    def called(name):
        assert data["active"]
        seen.append(name)
        if control["on_call"]: control["on_call"](name)
    machine = N(GetController2=Mock(return_value=(True, "", False)))
    def post(file):
        called("SaveCLFile")
        intent = json.loads(receipt.read_text())
        assert intent["phase"] == "SaveCLFile" and intent["native_dispatch_pending"] is True
        assert intent["native_call_attempted"] is False
        assert file == str(output) and not output.exists()
        if control["on_post"]: return control["on_post"]()
        output.write_bytes(b"UNINTERPRETED GENERIC CL\n")
        return 0
    machine.SaveCLFile = Mock(side_effect=post)
    def typed(raw, name, _):
        assert raw is machine and name == "ICWMachine5"
        called("QueryInterface(ICWMachine5)")
        return raw
    original = cam._member
    model = N(GetPathName=Mock(side_effect=lambda: current["document"]["path"]),
              GetTitle=Mock(side_effect=lambda: current["document"]["title"]),
              GetType=Mock(side_effect=lambda: current["document"]["type"]),
              GetSaveFlag=Mock(side_effect=lambda: current["document"]["needs_save"]))
    sw = N(GetProcessID=Mock(return_value=731), ActiveDoc=model)
    def member(obj, name, *args):
        if obj is machine and name != "SaveCLFile": called(name)
        assert obj is sw or obj is machine or obj is model
        return original(obj, name, *args)
    def capture(*_, **kw):
        assert data["active"]
        kw["check"]()
        if control["on_capture"]: control["on_capture"]()
        kw["check"]()
        kw["diagnostic"].update(state=deepcopy(current))
        return deepcopy(current), dict(machine=machine)
    captures = Mock(side_effect=capture)
    bootstrap = Mock(return_value=object())
    monkeypatch.setattr(cam, "capture_mill_feature_state", captures)
    monkeypatch.setattr(cam, "_bootstrap", bootstrap)
    monkeypatch.setattr(cam, "_typed", typed)
    monkeypatch.setattr(cam, "_member", member)
    monkeypatch.setattr(events, "CamMessageSession", lambda *_: Session())
    def call(action="inspect", **kw):
        args = dict(process_id=731, expected_document_path=str(path), expected_source_sha256=sha,
            expected_feature_native_id=211, expected_operation_native_id=214,
            expected_mill_operation_type=0, expected_toolpath_record_counts=[68],
            expected_ungenerated_operation_ids=[215], action=action,
            qualification_only=True, acknowledge_disposable_copy=True, acknowledge_machine_scope=True)
        if action != "inspect": args["output_path"] = str(output)
        return cam.export_mill_generic_cl(sw, "clsid", "tlb", **(args | kw))
    def apply(**kw):
        prepared = call("prepare")
        assert prepared["status"] == "ok", prepared
        return call("apply", **(dict(expected_state_sha256=prepared["state_sha256"],
                                    receipt_path=str(receipt)) | kw))
    return N(**locals())


def test_one_native_export_preserves_inventory_and_requires_offline_review(probe):
    p = probe.call("prepare")
    assert p["status"] == "ok" and p["apply_eligible"]
    assert not probe.output.parent.exists() and not probe.receipt.exists()
    r = probe.call("apply", expected_state_sha256=p["state_sha256"], receipt_path=str(probe.receipt))
    assert r["status"] == "review_required" and r["output_verified"] and r["readback_verified"]
    assert r["before"] == r["after"] and probe.captures.call_count == 4
    assert r["native_hresult"] == 0 and type(r["native_hresult"]) is int
    assert r["export_scope"] == "whole_current_mill_machine" and not r["selected_operation_scope"]
    assert r["before"]["mill_state"]["operations"][1]["toolpath_record_counts"] == []
    for flag in ("productionNC", "production_qualified", "model_saved", "controller_changed",
                 "GTP_attempted", "GOP_attempted", "AFR_attempted", "tool_readers_used",
                 "raw_CL_record_getters_used", "simulation_attempted", "physical_depth_verified",
                 "units_verified", "coordinate_frame_verified", "post_cleanup_cam_read_performed"):
        assert r[flag] is False
    probe.machine.SaveCLFile.assert_called_once_with(str(probe.output))
    assert set(probe.seen) == {"QueryInterface(ICWMachine5)", "GetController2", "SaveCLFile"}
    assert json.loads(probe.receipt.read_text()) == r


@pytest.mark.parametrize("field,value", [
    ("process_id", True), ("expected_feature_native_id", 0),
    ("expected_operation_native_id", 214.), ("expected_mill_operation_type", False),
    ("expected_toolpath_record_counts", [True]), ("expected_toolpath_record_counts", [0]),
    ("expected_toolpath_record_counts", (68,)), ("expected_toolpath_record_counts", [100001]),
    ("expected_ungenerated_operation_ids", [214]), ("expected_ungenerated_operation_ids", [215,215]),
    ("expected_ungenerated_operation_ids", [False]), ("expected_ungenerated_operation_ids", (215,)),
    ("expected_source_sha256", "bad"), ("expected_document_path", "relative.sldprt"),
    ("qualification_only", 1), ("acknowledge_disposable_copy", False),
    ("acknowledge_machine_scope", 1), ("message_policy", "accept"), ("action", "retry"),
])
def test_invalid_inputs_stop_before_any_cam(probe, field, value):
    r = probe.call(**{field: value})
    assert r["status"] == "error"
    probe.bootstrap.assert_not_called()
    probe.captures.assert_not_called()
    probe.machine.SaveCLFile.assert_not_called()


@pytest.mark.parametrize("change", [
    "pid", "pid_bool", "dirty", "dirty_integer", "source", "document", "selected_count",
    "selected_flag", "selected_type", "selected_suppressed", "selected_link",
    "sibling_generated", "sibling_records", "sibling_suppressed", "sibling_link",
    "wrong_sibling", "duplicate", "additional", "snapshot_source",
])
def test_exact_scope_and_saved_document_preconditions(probe, change):
    state = probe.current
    a,b = state["operations"]
    if change == "pid": probe.sw.GetProcessID.return_value = 732
    elif change == "pid_bool": probe.sw.GetProcessID.return_value = True
    elif change == "dirty": state["document"]["needs_save"] = True
    elif change == "dirty_integer": state["document"]["needs_save"] = 0
    elif change == "source": probe.path.write_bytes(b"changed")
    elif change == "document": state["document"]["path"] = str(probe.path.with_name("other.sldprt"))
    elif change == "selected_count": a["toolpath_record_counts"] = [67]
    elif change == "selected_flag": a["toolpath_generated"] = False
    elif change == "selected_type": a["mill_operation_type"] = 1
    elif change == "selected_suppressed": a["suppressed"] = True
    elif change == "selected_link": a["linked_feature_ids"] = [999]
    elif change == "sibling_generated": b["toolpath_generated"] = True
    elif change == "sibling_records": b["toolpath_record_counts"] = [0]
    elif change == "sibling_suppressed": b["suppressed"] = True
    elif change == "sibling_link": b["linked_feature_ids"] = [999]
    elif change == "wrong_sibling": b["native_id"] = 999
    elif change == "duplicate": b["native_id"] = a["native_id"]
    elif change == "additional": state["operations"].append(operation(999,2))
    elif change == "snapshot_source": state["saved_file_sha256"] = "b"*64
    r = probe.call("prepare")
    assert r["status"] == "error", r
    probe.machine.SaveCLFile.assert_not_called()


@pytest.mark.parametrize("change", ["hash", "controller", "feature", "sibling_type", "output", "process"])
def test_changed_prepared_state_stops_before_dispatch(probe, change):
    prepared = probe.call("prepare")
    args = dict(expected_state_sha256=prepared["state_sha256"], receipt_path=str(probe.receipt))
    if change == "hash": args["expected_state_sha256"] = "f"*64
    elif change == "controller": probe.machine.GetController2.return_value = (False, "new", True)
    elif change == "feature": probe.current["selected_feature"]["depth_native"] = 5.
    elif change == "sibling_type": probe.current["operations"][1]["mill_operation_type"] = 2
    elif change == "output": args["output_path"] = str(probe.output.with_name("changed.cl"))
    elif change == "process":
        probe.sw.GetProcessID.return_value = 732
        args["process_id"] = 732
    r = probe.call("apply", **args)
    assert r["status"] == "error" and not r["native_call_attempted"]
    assert not probe.output.parent.exists() and not probe.receipt.exists()
    probe.machine.SaveCLFile.assert_not_called()


def test_drift_between_apply_captures_stops(probe):
    p = probe.call("prepare")
    def drift():
        if probe.captures.call_count == 3:
            probe.current["selected_feature"]["depth_native"] = 4.
    probe.control["on_capture"] = drift
    r = probe.call("apply", expected_state_sha256=p["state_sha256"], receipt_path=str(probe.receipt))
    assert r["status"] == "error" and not probe.receipt.exists()
    probe.machine.SaveCLFile.assert_not_called()


@pytest.mark.parametrize("change", ["missing", "empty", "sidecar", "dirty", "source",
    "controller", "records", "sibling_generated", "feature", "exception", "hresult1", "boolfalse", "none", "oversized"])
def test_partial_export_failure_retains_evidence_and_never_replays(probe, change):
    def post():
        if change != "missing": probe.output.write_bytes(b"" if change == "empty" else b"RAW")
        if change == "exception": raise RuntimeError("native result unknown")
        if change == "sidecar": (probe.output.parent/"extra.txt").write_text("unexpected")
        elif change == "dirty": probe.current["document"]["needs_save"] = True
        elif change == "source": probe.path.write_bytes(b"changed")
        elif change == "controller": probe.machine.GetController2.return_value = (True,"changed",True)
        elif change == "records": probe.current["operations"][0]["toolpath_record_counts"] = [69]
        elif change == "sibling_generated": probe.current["operations"][1]["toolpath_generated"] = True
        elif change == "feature": probe.current["selected_feature"]["depth_native"] = 4.
        elif change == "hresult1": return 1
        elif change == "boolfalse": return False
        elif change == "none": return None
        elif change == "oversized":
            with probe.output.open("wb") as stream: stream.truncate(64*1024*1024+1)
        return 0
    probe.control["on_post"] = post
    r = probe.apply()
    assert r["status"] == "uncertain" and not r["output_verified"] and not r["readback_verified"]
    assert r["native_call_attempted"] and not r["automatic_retry_permitted"]
    preserved = probe.receipt.read_bytes()
    assert probe.call("apply", expected_state_sha256="a"*64, receipt_path=str(probe.receipt))["status"] == "error"
    assert probe.receipt.read_bytes() == preserved
    probe.machine.SaveCLFile.assert_called_once()


@pytest.mark.parametrize("when", ["enter", "capture", "qi", "controller", "export", "exit"])
def test_first_event_stops_next_native_call(probe, when):
    prepared = probe.call("prepare")
    start = len(probe.seen)
    def event(): probe.data["event_count"] = 1
    if when == "enter": probe.control["on_enter"] = event
    elif when == "capture": probe.control["on_capture"] = event
    elif when == "exit": probe.control["on_exit"] = event
    else:
        label = {"qi":"QueryInterface(ICWMachine5)", "controller":"GetController2", "export":"SaveCLFile"}[when]
        probe.control["on_call"] = lambda name: event() if name == label else None
    r = probe.call("apply", expected_state_sha256=prepared["state_sha256"], receipt_path=str(probe.receipt))
    assert r["status"] in {"error","uncertain"} and not r["output_verified"]
    assert probe.data["disconnected"]
    if when in {"enter","capture"}: assert probe.seen[start:] == []
    elif when in {"qi","controller","export"}: assert probe.seen[-1] == label
    if when in {"enter","capture","qi","controller"}: probe.machine.SaveCLFile.assert_not_called()


@pytest.mark.parametrize("change", ["output", "sidecar", "disconnect"])
def test_cleanup_failure_invalidates_output_without_further_cam(probe, change):
    p = probe.call("prepare")
    def callback():
        if change == "output": probe.output.write_bytes(b"changed")
        elif change == "sidecar": (probe.output.parent/"late.txt").write_text("x")
        else: probe.data["disconnect_errors"].append("failed")
    probe.control["on_exit"] = callback
    r = probe.call("apply", expected_state_sha256=p["state_sha256"], receipt_path=str(probe.receipt))
    assert r["status"] == "uncertain" and not r["output_verified"]
    probe.machine.SaveCLFile.assert_called_once()


@pytest.mark.parametrize("phase", ["SaveCLFile","SaveCLFile_returned","finished"])
def test_receipt_publication_failure_controls_dispatch_and_validation(probe, monkeypatch, phase):
    original = cam._write_receipt
    def fail(path, report, **kw):
        if report["phase"] == phase: raise OSError("receipt unavailable")
        original(path, report, **kw)
    monkeypatch.setattr(cam, "_write_receipt", fail)
    r = probe.apply()
    assert not r["output_verified"]
    assert probe.machine.SaveCLFile.call_count == (phase != "SaveCLFile")


@pytest.mark.parametrize("change", ["existing_dir","existing_receipt","extension","unc","dotdot",
                                    "inspect_output","prepare_receipt","apply_no_hash","apply_no_receipt"])
def test_exclusive_action_paths(probe, change):
    args = {}
    if change == "existing_dir": probe.output.parent.mkdir()
    elif change == "existing_receipt": probe.receipt.write_text("KEEP")
    elif change == "extension": args["output_path"] = str(probe.output.with_suffix(".nc"))
    elif change == "unc": args["output_path"] = r"\\server\share\new\file.cl"
    elif change == "dotdot": args["output_path"] = str(probe.output.parent/".."/"new"/"file.cl")
    elif change == "inspect_output":
        r = probe.call(output_path=str(probe.output))
    elif change == "prepare_receipt": args["receipt_path"] = str(probe.receipt)
    elif change == "apply_no_hash": r = probe.call("apply", receipt_path=str(probe.receipt))
    elif change == "apply_no_receipt": r = probe.call("apply", expected_state_sha256="a"*64)
    if change == "existing_receipt":
        r = probe.apply()
        assert probe.receipt.read_text() == "KEEP"
    elif change not in {"inspect_output","apply_no_hash","apply_no_receipt"}:
        r = probe.call("prepare", **args)
    assert r["status"] == "error"
    probe.machine.SaveCLFile.assert_not_called()


def test_machine5_interface_failure_never_dispatches(probe, monkeypatch):
    monkeypatch.setattr(cam, "_typed", Mock(side_effect=RuntimeError("QI unsupported")))
    assert probe.call("prepare")["status"] == "error"
    assert not probe.output.parent.exists() and not probe.receipt.exists()
    probe.machine.SaveCLFile.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("needs_save", None), ("needs_save", 0), ("needs_save", 1), ("needs_save", 0.),
    ("type", True), ("type", 1.), ("type", None),
])
def test_raw_document_identity_is_not_coerced(probe, field, value):
    probe.current["document"][field] = value
    assert probe.call("prepare")["status"] == "error"
    probe.bootstrap.assert_not_called()
    probe.machine.SaveCLFile.assert_not_called()
