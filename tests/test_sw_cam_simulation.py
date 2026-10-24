"""整文档 CAM 仿真导出的门禁、回执和 ABI 测试；不连接 CAD。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_simulation as simulation


@pytest.fixture
def probe(tmp_path, monkeypatch):
    part = tmp_path / "calibration.sldprt"
    part.write_bytes(b"fixture")
    directory = tmp_path / "simulation-output"
    document = {"path": str(part), "title": part.name, "type": 1, "needs_save": False}
    inventory = {"machine_type": 3, "feature_count": 3, "operation_count": 5, "operation_setup_count": 1,
                 "operations": [{"setup_index": 0, "operation_index": i, "turn_operation_type": i + 1,
                                 "toolpath_generated": i == 2, "toolpath_record_counts": [36] if i == 2 else []}
                                for i in range(5)]}
    state = {"document": document, "inventory": inventory, "on_native": None, "on_image": None,
             "on_stl": None, "on_enter": None, "on_exit": None, "native_result": (0, 0),
             "image_result": True, "stl_result": (0, True), "image_bytes": b"image-fixture",
             "stl_bytes": b"solid fixture\nendsolid fixture\n"}
    sw, doc, machine = object(), object(), object()
    receipt = directory / "receipt.json"

    def durable_stage(expected):
        report = json.loads(receipt.read_text(encoding="utf-8"))
        assert report["phase"] == expected and report["mutation_attempted"] is True

    def native_call(*args):
        assert args == (True, False, False)
        durable_stage("RunSimulationSilent")
        if state["on_native"]:
            state["on_native"]()
        return state["native_result"]

    def image_export(path):
        durable_stage("ActiveDocSaveSimulationImage")
        if state["on_image"]:
            state["on_image"]()
        if state["image_bytes"] is not None:
            Path(path).write_bytes(state["image_bytes"])
        return state["image_result"]

    def stl_export(path, system, units):
        durable_stage("ActiveDocSaveStlFileFromSimulation")
        assert (system, units) == ("", 0)
        if state["on_stl"]:
            state["on_stl"]()
        if state["stl_bytes"] is not None:
            Path(path).write_bytes(state["stl_bytes"])
        return state["stl_result"]

    typed_doc = SimpleNamespace(RunSimulationSilent=Mock(side_effect=native_call))
    app = SimpleNamespace(ActiveDocSaveSimulationImage=Mock(side_effect=image_export),
                          ActiveDocSaveStlFileFromSimulation=Mock(side_effect=stl_export),
                          ActiveDocGTP=Mock(), ActiveDocGOP=Mock(), ActiveDocLaunchSimulation=Mock())
    context = Mock(side_effect=lambda *_: (deepcopy(state["document"]), doc, object(), machine, app))
    typed = Mock(return_value=typed_doc)
    monkeypatch.setattr(simulation, "_context", context)
    monkeypatch.setattr(simulation, "_inventory", Mock(side_effect=lambda *_: deepcopy(state["inventory"])))
    monkeypatch.setattr(simulation, "_typed", typed)
    monkeypatch.setattr(simulation, "document_snapshot", Mock(side_effect=lambda *_: deepcopy(state["document"])))

    class Session:
        def __init__(self):
            self.report = {"subscribed": False, "disconnected": False, "event_count": 0, "overflow": 0,
                           "callback_errors": [], "callback_error_count": 0, "disconnect_errors": []}
            self.enter_error = None
        def __enter__(self):
            if self.enter_error:
                raise self.enter_error
            self.report["subscribed"] = True
            if state["on_enter"]:
                state["on_enter"]()
            return self
        def __exit__(self, *args):
            self.report["disconnected"] = True
            if state["on_exit"]:
                state["on_exit"]()
        def summary(self):
            return deepcopy(self.report)

    session = Session()
    factory = Mock(return_value=session)
    monkeypatch.setattr(simulation, "CamMessageSession", factory)
    values = dict(expected_document_path=str(part), expected_feature_count=3, expected_operation_count=5,
                  expected_operation_setup_count=1, expected_generated_operation_count=1,
                  output_dir=str(directory), qualification_only=True,
                  acknowledge_document_wide_simulation=True, message_policy="vendor_default")
    def run(**changes):
        return simulation.run_simulation(sw, "verified-clsid", "verified.tlb", **{**values, **changes})
    return SimpleNamespace(state=state, directory=directory, receipt=receipt, native=typed_doc.RunSimulationSilent,
                           app=app, context=context, typed=typed, doc=doc, session=session, factory=factory, run=run)


def test_document_wide_call_exports_hashes_and_retains_review_requirement(probe):
    report = probe.run()
    assert report["status"] == "review_required" and report["reason"] == "SIMULATION_OUTPUTS_REQUIRE_REVIEW"
    assert report["export_files_verified"] and report["native_call_returned"]
    assert not report["native_completion_verified"] and not report["may_continue"]
    assert not report["production_process_qualified"] and not report["single_operation_scope_claimed"]
    assert not report["model_saved"] and not report["nc_exported"]
    assert report["messages"]["disconnected"]
    probe.typed.assert_called_once_with(probe.doc, "ICWDoc3", "verified.tlb")
    probe.native.assert_called_once_with(True, False, False)
    probe.app.ActiveDocGTP.assert_not_called()
    probe.app.ActiveDocGOP.assert_not_called()
    probe.app.ActiveDocLaunchSimulation.assert_not_called()
    for kind, data_key in (("image", "image_bytes"), ("stl", "stl_bytes")):
        evidence = report["exports"][kind]
        assert evidence["bytes"] == len(probe.state[data_key])
        assert evidence["sha256"] == hashlib.sha256(probe.state[data_key]).hexdigest()
        assert evidence["content_reviewed"] is False
    assert report["stl_export_return"] == {"error_code": 0, "saved": True, "coordinate_system": "default",
                                           "units": "millimeters", "unit_code": 0}
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == report


@pytest.mark.parametrize("field,value", [("qualification_only", False), ("qualification_only", 1),
    ("acknowledge_document_wide_simulation", False), ("acknowledge_document_wide_simulation", 1.0),
    ("message_policy", "yes"), ("expected_feature_count", True), ("expected_operation_count", 0),
    ("expected_operation_setup_count", 1.0), ("expected_generated_operation_count", 6),
    ("expected_document_path", "relative.sldprt"), ("output_dir", "relative-output")])
def test_invalid_scope_and_counts_refuse_before_directory_or_com(probe, field, value):
    with pytest.raises(ValueError):
        probe.run(**{field: value})
    assert not probe.directory.exists()
    probe.context.assert_not_called()


def test_existing_output_directory_prevents_replay_and_preserves_files(probe):
    probe.directory.mkdir()
    evidence = probe.directory / "receipt.json"
    evidence.write_text("prior attempt", encoding="utf-8")
    with pytest.raises(FileExistsError):
        probe.run()
    assert evidence.read_text(encoding="utf-8") == "prior attempt"
    probe.context.assert_not_called()


@pytest.mark.parametrize("change", ["dirty", "foreign", "not_part", "features", "operations", "setups", "generated", "empty_records"])
def test_preflight_refuses_changed_document_or_exact_counts_before_native(probe, change):
    if change == "dirty":
        probe.state["document"]["needs_save"] = True
    elif change == "foreign":
        probe.state["document"]["path"] += ".foreign"
    elif change == "not_part":
        probe.state["document"]["type"] = 2
    elif change == "generated":
        probe.state["inventory"]["operations"][0]["toolpath_generated"] = True
    elif change == "empty_records":
        probe.state["inventory"]["operations"][2]["toolpath_record_counts"] = []
    else:
        key = {"features": "feature_count", "operations": "operation_count", "setups": "operation_setup_count"}[change]
        probe.state["inventory"][key] += 1
    report = probe.run()
    assert report["status"] == "error" and not report["mutation_attempted"]
    probe.native.assert_not_called()
    probe.app.ActiveDocSaveSimulationImage.assert_not_called()


@pytest.mark.parametrize("when", ["on_enter", "on_native", "on_image"])
def test_native_messages_stop_next_mutating_stage(probe, when):
    probe.state[when] = lambda: probe.session.report.update(event_count=1)
    report = probe.run()
    assert report["status"] == "review_required" and not report["may_continue"]
    assert report["messages"]["disconnected"]
    if when == "on_enter":
        probe.native.assert_not_called()
    if when != "on_image":
        probe.app.ActiveDocSaveSimulationImage.assert_not_called()
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()


@pytest.mark.parametrize("when", ["on_enter", "on_native", "on_image"])
def test_document_switch_stops_next_mutating_stage(probe, when):
    probe.state[when] = lambda: probe.state["document"].update(path="another.sldprt")
    report = probe.run()
    assert report["status"] == "review_required" and not report["may_continue"]
    if when == "on_enter":
        probe.native.assert_not_called()
    if when != "on_image":
        probe.app.ActiveDocSaveSimulationImage.assert_not_called()
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()


def test_document_wide_side_effect_is_reported_without_claiming_single_operation_scope(probe):
    def change_other_operation():
        probe.state["inventory"]["operations"][0].update(toolpath_generated=True, toolpath_record_counts=[17])
        probe.state["document"]["needs_save"] = True
    probe.state["on_native"] = change_other_operation
    report = probe.run()
    assert report["export_files_verified"] and report["inventory_changed_by_simulation"]
    assert report["inventory_changed"] and not report["single_operation_scope_claimed"]
    assert report["document_after"]["needs_save"] and not report["model_saved"]
    assert report["inventory_before"]["operations"][0]["toolpath_generated"] is False
    assert report["inventory_after"]["operations"][0]["toolpath_generated"] is True


@pytest.mark.parametrize("returned", [None, True, (0,), (0, 0, 0), (False, 0), (-1, 0), (0, "0")])
def test_unknown_simulation_contract_never_triggers_exports(probe, returned):
    probe.state["native_result"] = returned
    report = probe.run()
    assert report["status"] == "error" and report["native_call_returned"]
    assert not report["native_completion_verified"]
    probe.app.ActiveDocSaveSimulationImage.assert_not_called()
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()


def test_native_call_exception_is_uncertain_and_not_replayed(probe):
    probe.native.side_effect = RuntimeError("native completion unavailable")
    report = probe.run()
    assert report["status"] == "uncertain" and not report["native_call_returned"]
    assert report["messages"]["disconnected"]
    probe.native.assert_called_once()
    probe.app.ActiveDocSaveSimulationImage.assert_not_called()
    with pytest.raises(FileExistsError):
        probe.run()


@pytest.mark.parametrize("field,value", [("image_result", False), ("image_result", 1), ("image_bytes", None), ("image_bytes", b"")])
def test_invalid_image_result_or_file_stops_stl_export(probe, field, value):
    probe.state[field] = value
    report = probe.run()
    assert report["status"] == "error" and not report["export_files_verified"]
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()


@pytest.mark.parametrize("returned", [(True, 0), (False, True), (0, 1), (1, True), (0, False), None, (0,)])
def test_stl_return_requires_error_then_strict_bool_and_success(probe, returned):
    probe.state["stl_result"] = returned
    report = probe.run()
    assert report["status"] == "error" and not report["export_files_verified"]
    assert "image" in report["exports"]
    assert "stl" not in report["exports"]


def test_messages_during_disconnect_preserve_exports_but_block_continuation(probe):
    probe.state["on_exit"] = lambda: probe.session.report.update(event_count=1)
    report = probe.run()
    assert report["export_files_verified"] and report["status"] == "review_required"
    assert report["reason"] == "CAM_MESSAGES_REQUIRE_REVIEW" and not report["may_continue"]


def test_receipt_failure_before_native_call_blocks_mutation(probe, monkeypatch):
    real_writer = simulation._write_receipt
    def writer(path, report, *, create=False):
        if report["phase"] == "RunSimulationSilent":
            raise OSError("receipt unavailable")
        return real_writer(path, report, create=create)
    monkeypatch.setattr(simulation, "_write_receipt", writer)
    report = probe.run()
    assert report["status"] == "uncertain"
    probe.native.assert_not_called()
    probe.app.ActiveDocSaveSimulationImage.assert_not_called()


def test_comtypes_multiout_order_matches_vendor_declarations_in_memory():
    from ctypes import HRESULT, POINTER, c_int
    from comtypes import COMObject, COMMETHOD, GUID, IUnknown
    from comtypes.automation import BSTR, VARIANT_BOOL

    class Contract(IUnknown):
        _iid_ = GUID("{3F18ACD5-E584-495B-AE4D-58334D61B70E}")
        _methods_ = [
            COMMETHOD([], HRESULT, "RunSimulationSilent", (["in"], VARIANT_BOOL, "difference"),
                      (["in"], VARIANT_BOOL, "save_stl"), (["in"], VARIANT_BOOL, "save_image"),
                      (["out"], POINTER(c_int), "gouges"), (["out"], POINTER(c_int), "undercuts")),
            COMMETHOD([], HRESULT, "ActiveDocSaveStlFileFromSimulation", (["in"], BSTR, "path"),
                      (["in"], BSTR, "system"), (["in"], c_int, "units"),
                      (["out"], POINTER(c_int), "error_code"), (["out", "retval"], POINTER(VARIANT_BOOL), "saved")),
        ]
    class Server(COMObject):
        _com_interfaces_ = [Contract]
        def RunSimulationSilent(self, difference, save_stl, save_image):
            assert difference is True and save_stl is False and save_image is False
            return 2, 3
        def ActiveDocSaveStlFileFromSimulation(self, path, system, units):
            return 0, True
    owner = Server()
    interface = owner.QueryInterface(Contract)
    assert tuple(interface.RunSimulationSilent(True, False, False)) == (2, 3)
    result = interface.ActiveDocSaveStlFileFromSimulation("fixture.stl", "", 0)
    assert result[0] == 0 and type(result[0]) is int
    assert result[1] is True


def test_dirty_change_during_final_inventory_read_stops_simulation(probe, monkeypatch):
    calls = 0
    def inventory(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            probe.state["document"]["needs_save"] = True
        return deepcopy(probe.state["inventory"])
    monkeypatch.setattr(simulation, "_inventory", inventory)
    report = probe.run()
    assert report["status"] == "error" and not report["mutation_attempted"]
    probe.native.assert_not_called()
    probe.app.ActiveDocSaveSimulationImage.assert_not_called()


@pytest.mark.parametrize("stage", ["RunSimulationSilent", "ActiveDocSaveSimulationImage", "ActiveDocSaveStlFileFromSimulation"])
def test_messages_arriving_during_receipt_write_stop_the_next_native_call(probe, monkeypatch, stage):
    real_writer = simulation._write_receipt
    def writer(path, report, *, create=False):
        real_writer(path, report, create=create)
        if report["phase"] == stage:
            probe.session.report["event_count"] = 1
    monkeypatch.setattr(simulation, "_write_receipt", writer)
    report = probe.run()
    assert report["status"] == "review_required"
    if stage == "RunSimulationSilent":
        probe.native.assert_not_called()
    if stage != "ActiveDocSaveStlFileFromSimulation":
        probe.app.ActiveDocSaveSimulationImage.assert_not_called()
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()



def preview(probe, *, action="launch_play", **changes):
    """复用纯内存 CAM 夹具，不调用静默仿真入口。"""
    values = dict(action=action, expected_document_path=probe.state["document"]["path"],
                  expected_feature_count=3, expected_operation_count=5, expected_operation_setup_count=1,
                  expected_generated_operation_count=1, output_dir=str(probe.directory), qualification_only=True,
                  acknowledge_document_wide_simulation=True, message_policy="vendor_default")
    values.update(changes)
    return simulation.preview_simulation(object(), "verified-clsid", "verified.tlb", **values)


def test_preview_launch_then_play_is_durable_once_and_never_closes(probe):
    order = []
    def call(name):
        report = json.loads(probe.receipt.read_text(encoding="utf-8"))
        assert report["phase"] == name
        assert report["native_calls"][-1] == {"method": name, "returned": False}
        order.append(name)
    probe.app.ActiveDocLaunchSimulation.side_effect = lambda: call("ActiveDocLaunchSimulation")
    probe.app.ActiveDocPlaySimulation = Mock(side_effect=lambda: call("ActiveDocPlaySimulation"))
    probe.app.ActiveDocCloseSimulation = Mock()
    report = preview(probe)
    assert order == ["ActiveDocLaunchSimulation", "ActiveDocPlaySimulation"]
    assert report["status"] == "review_required" and report["native_calls_returned"]
    assert not report["native_completion_verified"] and not report["playback_completion_verified"]
    assert not report["preview_visibility_verified"] and not report["preview_close_requested"]
    assert not report["may_continue"] and not report["silent_simulation_requested"]
    assert report["messages"]["disconnected"]
    probe.app.ActiveDocLaunchSimulation.assert_called_once_with()
    probe.app.ActiveDocPlaySimulation.assert_called_once_with()
    probe.app.ActiveDocCloseSimulation.assert_not_called()
    probe.app.ActiveDocSaveSimulationImage.assert_not_called()
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()
    probe.app.ActiveDocGTP.assert_not_called()
    probe.native.assert_not_called()
    probe.typed.assert_not_called()
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == report


@pytest.mark.parametrize("failure", ["native_error", "message", "document"])
def test_preview_launch_failure_or_guard_change_prevents_play_and_close(probe, failure):
    if failure == "native_error":
        probe.app.ActiveDocLaunchSimulation.side_effect = RuntimeError("launch failed")
    elif failure == "message":
        probe.app.ActiveDocLaunchSimulation.side_effect = lambda: probe.session.report.update(event_count=1)
    else:
        probe.app.ActiveDocLaunchSimulation.side_effect = lambda: probe.state["document"].update(path="foreign.sldprt")
    probe.app.ActiveDocPlaySimulation = Mock()
    probe.app.ActiveDocCloseSimulation = Mock()
    report = preview(probe)
    assert report["status"] in {"uncertain", "review_required"} and not report["may_continue"]
    probe.app.ActiveDocPlaySimulation.assert_not_called()
    probe.app.ActiveDocCloseSimulation.assert_not_called()
    probe.native.assert_not_called()
    assert report["messages"]["disconnected"]


def test_preview_checks_messages_after_play(probe):
    probe.app.ActiveDocPlaySimulation = Mock(side_effect=lambda: probe.session.report.update(event_count=1))
    report = preview(probe)
    assert report["status"] == "review_required" and report["reason"] == "CAM_MESSAGES_REQUIRE_REVIEW"
    assert report["native_calls_returned"] and not report["native_completion_verified"]
    probe.app.ActiveDocPlaySimulation.assert_called_once()


def test_preview_final_inventory_dirty_change_blocks_launch(probe, monkeypatch):
    count = 0
    def inventory(*args):
        nonlocal count
        count += 1
        if count == 2:
            probe.state["document"]["needs_save"] = True
        return deepcopy(probe.state["inventory"])
    monkeypatch.setattr(simulation, "_inventory", inventory)
    report = preview(probe)
    assert report["status"] == "error" and not report["mutation_attempted"]
    probe.app.ActiveDocLaunchSimulation.assert_not_called()


@pytest.mark.parametrize("failure", ["false", "integer", "exception", "empty_file", "missing_file"])
def test_preview_export_attempts_stl_independently_after_image_failure(probe, failure):
    if failure == "exception":
        probe.app.ActiveDocSaveSimulationImage.side_effect = RuntimeError("image export unavailable")
    else:
        if failure in {"false", "integer"}:
            probe.state["image_result"] = False if failure == "false" else 1
        else:
            probe.state["image_bytes"] = b"" if failure == "empty_file" else None
    report = preview(probe, action="export_state")
    assert report["status"] == "review_required" and not report["export_files_verified"]
    assert "image" in report["export_errors"] and "stl" in report["exports"]
    probe.app.ActiveDocSaveSimulationImage.assert_called_once()
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_called_once_with(str(probe.directory / "simulation.stl"), "", 0)
    probe.app.ActiveDocLaunchSimulation.assert_not_called()
    probe.native.assert_not_called()


def test_preview_export_preserves_image_when_stl_fails(probe):
    probe.state["stl_result"] = (8, False)
    report = preview(probe, action="export_state")
    assert "image" in report["exports"] and "stl" in report["export_errors"]
    assert report["native_calls"][1]["error_code"] == 8
    assert not report["export_files_verified"] and not report["may_continue"]


@pytest.mark.parametrize("change", ["message", "document"])
def test_preview_export_does_not_attempt_other_format_after_safety_guard_failure(probe, change):
    probe.state["image_result"] = False
    if change == "message":
        probe.state["on_image"] = lambda: probe.session.report.update(event_count=1)
    else:
        probe.state["on_image"] = lambda: probe.state["document"].update(path="foreign.sldprt")
    report = preview(probe, action="export_state")
    assert report["status"] == "review_required"
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()
    assert not report["may_continue"]


def test_preview_exports_verify_files_without_launch_or_simulation(probe):
    report = preview(probe, action="export_state")
    assert report["export_files_verified"] and report["native_calls_returned"]
    assert report["status"] == "review_required" and not report["native_completion_verified"]
    assert report["exports"]["image"]["sha256"] == hashlib.sha256(probe.state["image_bytes"]).hexdigest()
    assert report["exports"]["stl"]["sha256"] == hashlib.sha256(probe.state["stl_bytes"]).hexdigest()
    probe.app.ActiveDocLaunchSimulation.assert_not_called()
    probe.native.assert_not_called()


def test_preview_never_overwrites_individual_output_and_still_attempts_other_format(probe):
    image = probe.directory / "simulation.jpg"
    probe.state["on_enter"] = lambda: image.write_bytes(b"prior artifact")
    report = preview(probe, action="export_state")
    assert image.read_bytes() == b"prior artifact"
    assert report["export_errors"]["image"]["type"] == "FileExistsError"
    assert "stl" in report["exports"]
    probe.app.ActiveDocSaveSimulationImage.assert_not_called()
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_called_once()


def test_preview_existing_directory_prevents_launch_replay(probe):
    probe.directory.mkdir()
    with pytest.raises(FileExistsError):
        preview(probe)
    probe.context.assert_not_called()
    probe.app.ActiveDocLaunchSimulation.assert_not_called()
