"""整文档 CAM 仿真导出的门禁、回执和 ABI 测试；不连接 CAD。"""
from copy import deepcopy
import hashlib
import json
import os
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
            assert system == "" and units == 0
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



def test_prepare_output_preserves_mapped_drive_while_resolving_separate_boundary(probe, monkeypatch):
    from pathlib import PureWindowsPath

    lexical_root = PureWindowsPath("Z:/project")
    canonical_root = PureWindowsPath("//fixture-server/share/project")
    created = []
    class MappedPath:
        def __init__(self, value): self.value = PureWindowsPath(value)
        def __str__(self): return str(self.value)
        @property
        def parent(self): return MappedPath(self.value.parent)
        def is_absolute(self): return self.value.is_absolute()
        def is_dir(self): return self.value == lexical_root
        def mkdir(self): created.append(str(self.value))
        def resolve(self, strict=False):
            assert strict is True
            return canonical_root / self.value.relative_to(lexical_root)
    real_path = simulation.Path
    monkeypatch.setattr(simulation, "Path", lambda value: MappedPath(value) if str(value).startswith("Z:") else real_path(value))
    counts, native_directory, canonical_directory = simulation._prepare_output(
        expected_document_path=probe.state["document"]["path"], expected_feature_count=3,
        expected_operation_count=5, expected_operation_setup_count=1, expected_generated_operation_count=1,
        output_dir="Z:/project/new-export", qualification_only=True,
        acknowledge_document_wide_simulation=True, message_policy="vendor_default")
    assert str(native_directory) == str(lexical_root / "new-export")
    assert canonical_directory == canonical_root / "new-export"
    assert created == [str(lexical_root / "new-export")]
    assert counts["generated_operation_count"] == 1


def test_preview_sends_lexical_drive_paths_and_records_canonical_receipt(probe, monkeypatch):
    from pathlib import PureWindowsPath

    native_directory = PureWindowsPath("Z:/project/new-export")
    probe.directory.mkdir()
    canonical_directory = probe.directory.resolve(strict=True)
    counts = {"feature_count": 3, "operation_count": 5, "operation_setup_count": 1, "generated_operation_count": 1}
    monkeypatch.setattr(simulation, "_prepare_output", Mock(return_value=(counts, native_directory, canonical_directory)))
    boundary = Mock()
    monkeypatch.setattr(simulation, "_check_output_path", boundary)
    probe.app.ActiveDocSaveSimulationImage = Mock(return_value=False)
    probe.app.ActiveDocSaveStlFileFromSimulation = Mock(return_value=(7, False))
    report = preview(probe, action="export_state")
    image_path, stl_path = str(native_directory / "simulation.jpg"), str(native_directory / "simulation.stl")
    probe.app.ActiveDocSaveSimulationImage.assert_called_once_with(image_path)
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_called_once_with(stl_path, "", 0)
    assert report["native_calls"][0]["native_path"] == image_path
    assert report["native_calls"][1]["native_path"] == stl_path
    assert report["output_dir"] == str(native_directory)
    assert report["output_dir_canonical"] == str(canonical_directory)
    assert report["receipt_path"] == str(canonical_directory / "receipt.json")
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == report
    assert boundary.call_count == 4


def test_output_boundary_rejects_changed_directory_mapping(probe, monkeypatch):
    probe.directory.mkdir()
    canonical = probe.directory.resolve(strict=True)
    real_resolve = Path.resolve
    def resolve(path, strict=False):
        if path == probe.directory:
            return canonical.parent / "redirected"
        return real_resolve(path, strict=strict)
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="identity changed"):
        simulation._check_output_path(probe.directory / "simulation.stl", probe.directory, canonical)
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()


def test_output_boundary_rejects_dangling_symlink_without_native_overwrite(probe, monkeypatch):
    probe.directory.mkdir()
    canonical = probe.directory.resolve(strict=True)
    output = probe.directory / "simulation.stl"
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: True if path == output else real_is_symlink(path))
    with pytest.raises(FileExistsError):
        simulation._check_output_path(output, probe.directory, canonical)
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()


def test_output_boundary_rejects_canonical_escape(probe, monkeypatch):
    probe.directory.mkdir()
    canonical = probe.directory.resolve(strict=True)
    output = probe.directory / "simulation.stl"
    real_resolve = Path.resolve
    def resolve(path, strict=False):
        if path == output:
            return canonical.parent / "outside" / "simulation.stl"
        return real_resolve(path, strict=strict)
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="escapes"):
        simulation._check_output_path(output, probe.directory, canonical)
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()


@pytest.fixture
def geometry(probe):
    state = probe.state
    state.update(wip_return=True, stock_return=True, target_return=True, wip_files=True,
                 on_wip=None, on_stock=None, on_target=None)
    def export(kind, *args):
        saved = json.loads(probe.receipt.read_text(encoding="utf-8"))
        assert saved["phase"] == {"wip": "CreateSTLOfWIPs2", "stock": "CreateSTLOfStock", "target": "CreateSTLOfTargetInFCSSpace"}[kind]
        assert saved["native_calls"][-1]["returned"] is False
        assert saved["native_calls"][-1]["attempted"] is True
        if kind == "wip":
            assert args[2:] == ("", 0, 0)
        elif kind == "stock":
            assert args[1:] == ("", 0)
        else:
            assert args[1:] == (0,)
        if state["on_" + kind]:
            state["on_" + kind]()
        if kind == "wip":
            assert args[1] == "wip.stl" and args[0].endswith(os.sep)
            if state["wip_files"]:
                for name in ("wip_setup1.stl", "wip_setup2.stl"):
                    # 与 vendor 原生实现相同的字符串拼接，不能用 Path 自动补分隔符。
                    Path(args[0] + name).write_bytes(b"solid wip")
        else:
            Path(args[0]).write_bytes(("solid " + kind).encode())
        return state[kind + "_return"]
    machine = SimpleNamespace(**{name: Mock(side_effect=lambda *args, kind=kind: export(kind, *args))
        for kind, name in (("wip", "CreateSTLOfWIPs2"), ("stock", "CreateSTLOfStock"), ("target", "CreateSTLOfTargetInFCSSpace"))})
    probe.typed.return_value = machine
    def run(**changes):
        return simulation.export_geometry(object(), "verified-clsid", "verified.tlb", **dict(
            expected_document_path=state["document"]["path"], expected_feature_count=3, expected_operation_count=5,
            expected_operation_setup_count=1, expected_generated_operation_count=1,
            output_dir=str(probe.directory), qualification_only=True,
            acknowledge_document_wide_export=True, message_policy="vendor_default",
            export_kinds=["wip", "stock", "target"]) | changes)
    return SimpleNamespace(run=run, machine=machine, probe=probe)


def test_geometry_exports_all_wip_files_stock_target_and_bool_contract(geometry):
    report = geometry.run()
    assert report["status"] == "review_required" and report["export_files_verified"]
    assert not report["may_continue"] and not report["simulation_frame_export_claimed"]
    assert not report["simulation_requested"] and not report["explicit_gtp_requested"]
    assert report["exports"]["wip"]["source"] == "all_wip_parts_all_setups"
    assert len(report["exports"]["wip"]["files"]) == 2
    assert report["native_calls_returned"] and report["messages"]["disconnected"]
    assert not report["native_parameters"]["coordinate_system_and_unit_meaning_verified_for_entrypoint"]
    for item in report["exports"].values():
        assert item["native_return"] is True and item["contract_valid"]
        for evidence in item["files"]:
            assert evidence["bytes"] > 0 and len(evidence["sha256"]) == 64
    assert json.loads(geometry.probe.receipt.read_text(encoding="utf-8")) == report
    geometry.probe.native.assert_not_called()
    geometry.probe.app.ActiveDocGTP.assert_not_called()
    geometry.probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()


@pytest.mark.parametrize("returned", [False, 1, (0, True), None])
def test_geometry_failed_wip_return_keeps_evidence_and_stops_all_following_exports(geometry, returned):
    geometry.probe.state["wip_return"] = returned
    report = geometry.run()
    assert not report["export_files_verified"] and "wip" in report["export_errors"]
    assert report["exports"]["wip"]["files"]
    assert report["status"] == "error" and report["aborted_after_export"] == "wip"
    assert report["remaining_exports_skipped"] == ["stock", "target"]
    geometry.machine.CreateSTLOfStock.assert_not_called()
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_not_called()


def test_geometry_true_without_wip_files_is_not_success(geometry):
    geometry.probe.state["wip_files"] = False
    report = geometry.run()
    assert "wip" in report["export_errors"] and not report["exports"]["wip"]["verified"]
    assert report["status"] == "error"
    geometry.machine.CreateSTLOfStock.assert_not_called()
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_not_called()


@pytest.mark.parametrize("change", ["document", "dirty", "inventory", "message"])
def test_geometry_export_guard_stops_remaining_calls(geometry, change):
    def changed():
        state = geometry.probe.state
        if change == "document":
            state["document"]["path"] += ".foreign"
        elif change == "dirty":
            state["document"]["needs_save"] = True
        elif change == "inventory":
            state["inventory"]["feature_count"] += 1
        else:
            geometry.probe.session.report["event_count"] = 1
    geometry.probe.state["on_wip"] = changed
    report = geometry.run()
    assert report["status"] == "review_required" and not report["may_continue"]
    geometry.machine.CreateSTLOfStock.assert_not_called()
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_not_called()
    assert report["messages"]["disconnected"]


@pytest.mark.parametrize("changes", [{"qualification_only": 1}, {"acknowledge_document_wide_export": False},
    {"expected_generated_operation_count": True}, {"expected_operation_count": 4}])
def test_geometry_scope_and_counts_prevent_calls(geometry, changes):
    if "expected_operation_count" in changes:
        assert geometry.run(**changes)["status"] == "error"
    else:
        with pytest.raises(ValueError):
            geometry.run(**changes)
    geometry.machine.CreateSTLOfWIPs2.assert_not_called()


def test_geometry_existing_directory_prevents_replay(geometry):
    geometry.probe.directory.mkdir()
    with pytest.raises(FileExistsError):
        geometry.run()
    geometry.probe.context.assert_not_called()


def test_geometry_receipt_precedes_call_and_output_collision_is_not_overwritten(geometry, monkeypatch):
    real_writer = simulation._write_receipt
    path = geometry.probe.directory / "stock.stl"
    def write(receipt, report, **kwargs):
        value = real_writer(receipt, report, **kwargs)
        if report["phase"] == "CreateSTLOfStock":
            path.write_bytes(b"existing")
        return value
    monkeypatch.setattr(simulation, "_write_receipt", write)
    report = geometry.run()
    assert report["status"] == "error"
    assert path.read_bytes() == b"existing"
    geometry.machine.CreateSTLOfStock.assert_not_called()
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_not_called()


def test_geometry_machine5_return_only_bool_abi_in_memory():
    from ctypes import HRESULT, POINTER, c_int
    from comtypes import COMObject, COMMETHOD, GUID, IUnknown
    from comtypes.automation import BSTR, VARIANT_BOOL
    from scripts.sw_cam_comtypes import _INTERFACES
    assert _INTERFACES["ICWMachine5"] == "{3767818E-318E-4F18-BBD2-572DB04B45F0}"
    class Contract(IUnknown):
        _iid_ = GUID("{239AC565-3604-4345-AFC4-A0111CCF281B}")
        _methods_ = [COMMETHOD([], HRESULT, "CreateSTLOfWIPs2", (["in"], BSTR, "folder"),
            (["in"], BSTR, "filename"), (["in"], BSTR, "cs"), (["in"], c_int, "units"),
            (["in"], c_int, "quality"), (["out", "retval"], POINTER(VARIANT_BOOL), "saved")),
            COMMETHOD([], HRESULT, "CreateSTLOfStock", (["in"], BSTR, "path"), (["in"], BSTR, "cs"),
                (["in"], c_int, "units"), (["out", "retval"], POINTER(VARIANT_BOOL), "saved")),
            COMMETHOD([], HRESULT, "CreateSTLOfTargetInFCSSpace", (["in"], BSTR, "path"),
                (["in"], c_int, "units"), (["out", "retval"], POINTER(VARIANT_BOOL), "saved"))]
    class Server(COMObject):
        _com_interfaces_ = [Contract]
        def CreateSTLOfWIPs2(self, folder, filename, cs, units, quality):
            assert (folder, filename, cs, units, quality) == ("folder", "wip.stl", "", 0, 0)
            return True
        def CreateSTLOfStock(self, path, cs, units):
            assert (path, cs, units) == ("stock.stl", "", 0)
            return False
        def CreateSTLOfTargetInFCSSpace(self, path, units):
            assert (path, units) == ("target.stl", 0)
            return True
    owner = Server()
    pointer = owner.QueryInterface(Contract)
    assert pointer.CreateSTLOfWIPs2("folder", "wip.stl", "", 0, 0) is True
    assert pointer.CreateSTLOfStock("stock.stl", "", 0) is False
    assert pointer.CreateSTLOfTargetInFCSSpace("target.stl", 0) is True


def test_geometry_preserves_extended_local_path(geometry):
    native_directory = "\\\\?\\" + str(geometry.probe.directory)
    report = geometry.run(output_dir=native_directory)
    assert report["export_files_verified"] and report["output_dir"] == native_directory
    assert report["native_calls"][0]["native_path"].startswith(native_directory)


@pytest.mark.parametrize("failure", ["false", "invalid", "no_file", "exception"])
def test_geometry_failure_never_reads_cad_after_failed_call(geometry, monkeypatch, failure):
    def failed():
        monkeypatch.setattr(simulation, "_inventory", Mock(side_effect=AssertionError("No CAD read after failure")))
        monkeypatch.setattr(simulation, "document_snapshot", Mock(side_effect=AssertionError("No CAD read after failure")))
        if failure == "exception":
            raise RuntimeError("native export failed")
    geometry.probe.state.update(on_wip=failed, wip_return=False if failure == "false" else
                               (1 if failure == "invalid" else True), wip_files=failure != "no_file")
    report = geometry.run()
    assert report["status"] == ("uncertain" if failure == "exception" else "error")
    assert report["messages"]["disconnected"] and not report["may_continue"]
    simulation._inventory.assert_not_called()
    simulation.document_snapshot.assert_not_called()
    geometry.machine.CreateSTLOfStock.assert_not_called()
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_not_called()


def test_geometry_persists_false_return_before_file_read_or_cleanup(geometry, monkeypatch):
    real_evidence = simulation._file_evidence
    def evidence(path):
        durable = json.loads(geometry.probe.receipt.read_text(encoding="utf-8"))
        assert durable["native_calls"][0]["attempted"] and durable["native_calls"][0]["returned"]
        assert durable["exports"]["wip"]["native_return"] is False
        return real_evidence(path)
    monkeypatch.setattr(simulation, "_file_evidence", evidence)
    geometry.probe.state["wip_return"] = False
    assert geometry.run()["status"] == "error"


def test_geometry_cannot_call_native_when_attempt_receipt_cannot_be_written(geometry, monkeypatch):
    real_writer = simulation._write_receipt
    def writer(path, report, **kwargs):
        if report["native_calls"] and report["native_calls"][-1]["attempted"]:
            raise OSError("Cannot persist attempt")
        return real_writer(path, report, **kwargs)
    monkeypatch.setattr(simulation, "_write_receipt", writer)
    report = geometry.run()
    assert report["status"] == "uncertain"
    geometry.machine.CreateSTLOfWIPs2.assert_not_called()
    geometry.machine.CreateSTLOfStock.assert_not_called()


def test_geometry_stock_false_stops_target(geometry):
    geometry.probe.state["stock_return"] = False
    report = geometry.run()
    assert report["status"] == "error" and report["aborted_after_export"] == "stock"
    assert report["exports"]["wip"]["verified"] and not report["exports"]["stock"]["verified"]
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_not_called()


@pytest.mark.parametrize("kinds", [["target"], ["stock"], ["wip"], ["target", "stock"]])
def test_geometry_exports_only_requested_kinds_in_requested_order(geometry, kinds):
    report = geometry.run(export_kinds=kinds)
    expected = {"target": "CreateSTLOfTargetInFCSSpace", "stock": "CreateSTLOfStock", "wip": "CreateSTLOfWIPs2"}
    assert report["export_files_verified"] and report["export_kinds"] == kinds
    assert [call["method"] for call in report["native_calls"]] == [expected[kind] for kind in kinds]
    for kind in set(expected) - set(kinds):
        getattr(geometry.machine, expected[kind]).assert_not_called()


def test_geometry_default_requests_only_wip(geometry):
    report = geometry.run(export_kinds=None)
    assert report["export_kinds"] == ["wip"] and report["export_files_verified"]
    geometry.machine.CreateSTLOfStock.assert_not_called()
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_not_called()


@pytest.mark.parametrize("kinds", [[], "wip", ("wip",), [True], ["all"], ["wip", "wip"], ["wip", "stock", "target", "wip"]])
def test_geometry_invalid_selector_prevents_directory_and_com(geometry, kinds):
    with pytest.raises(ValueError):
        geometry.run(export_kinds=kinds)
    assert not geometry.probe.directory.exists()
    geometry.probe.context.assert_not_called()


def test_preview_explicit_close_calls_native_once_without_launch_or_exports(probe):
    def close():
        saved = json.loads(probe.receipt.read_text(encoding="utf-8"))
        assert saved["phase"] == "ActiveDocCloseSimulation" and saved["preview_close_requested"]
    probe.app.ActiveDocCloseSimulation = Mock(side_effect=close)
    report = preview(probe, action="close")
    assert report["status"] == "review_required" and report["preview_close_requested"]
    assert not report["preview_visibility_verified"] and not report["may_continue"]
    assert report["native_calls_returned"] and report["messages"]["disconnected"]
    probe.app.ActiveDocCloseSimulation.assert_called_once_with()
    probe.app.ActiveDocLaunchSimulation.assert_not_called()
    probe.app.ActiveDocSaveSimulationImage.assert_not_called()
    probe.app.ActiveDocSaveStlFileFromSimulation.assert_not_called()
    probe.native.assert_not_called()


def test_geometry_wip_native_folder_has_separator_and_concat_stays_in_owned_subdirectory(geometry):
    report = geometry.run(export_kinds=["wip"])
    folder = str(geometry.probe.directory / "wip") + os.sep
    assert report["export_files_verified"]
    assert report["native_calls"][0]["native_folder"] == folder
    geometry.machine.CreateSTLOfWIPs2.assert_called_once_with(folder, "wip.stl", "", 0, 0)
    assert all(Path(item["path"]).parent == geometry.probe.directory / "wip"
               for item in report["exports"]["wip"]["files"])
    assert not list(geometry.probe.directory.glob("wip*.stl"))


def test_geometry_wip_collision_created_after_attempt_receipt_prevents_native_overwrite(geometry, monkeypatch):
    original = simulation._write_receipt
    collision = geometry.probe.directory / "wip" / "wip.stl"
    def write(path, report, **kwargs):
        value = original(path, report, **kwargs)
        if report["native_calls"] and report["native_calls"][0]["attempted"]:
            if not collision.exists():
                collision.write_bytes(b"existing evidence")
        return value
    monkeypatch.setattr(simulation, "_write_receipt", write)
    report = geometry.run(export_kinds=["wip"])
    assert report["reason"] == "CAM_WIP_OUTPUT_DIRECTORY_CHANGED"
    assert collision.read_bytes() == b"existing evidence"
    geometry.machine.CreateSTLOfWIPs2.assert_not_called()


@pytest.mark.parametrize("where", ["inventory", "final_document", "attempt_receipt"])
def test_geometry_late_preflight_message_prevents_native_entry(geometry, monkeypatch, where):
    original_inventory = simulation._inventory
    original_document = simulation.document_snapshot
    original_writer = simulation._write_receipt
    final_reads = 0
    def is_final_stage():
        return geometry.probe.receipt.exists() and json.loads(
            geometry.probe.receipt.read_text(encoding="utf-8"))["phase"] == "CreateSTLOfWIPs2"
    def inventory(*args):
        value = original_inventory(*args)
        if where == "inventory" and is_final_stage():
            geometry.probe.session.report["event_count"] = 1
        return value
    def document(*args):
        nonlocal final_reads
        value = original_document(*args)
        if is_final_stage():
            final_reads += 1
            if where == "final_document" and final_reads == 2:
                geometry.probe.session.report["event_count"] = 1
        return value
    def write(path, report, **kwargs):
        value = original_writer(path, report, **kwargs)
        if where == "attempt_receipt" and report["native_calls"] and report["native_calls"][0]["attempted"]:
            geometry.probe.session.report["event_count"] = 1
        return value
    monkeypatch.setattr(simulation, "_inventory", inventory)
    monkeypatch.setattr(simulation, "document_snapshot", document)
    monkeypatch.setattr(simulation, "_write_receipt", write)
    report = geometry.run(export_kinds=["wip"])
    assert report["reason"] == "CAM_MESSAGES_REQUIRE_REVIEW" and not report["may_continue"]
    assert report["messages"]["disconnected"]
    geometry.machine.CreateSTLOfWIPs2.assert_not_called()


def test_stock_only_export_before_afr_allows_exact_zero_counts(geometry):
    geometry.probe.state["inventory"].update(feature_count=0,operation_count=0,operation_setup_count=0,operations=[])
    report=geometry.run(export_kinds=["stock"],expected_feature_count=0,expected_operation_count=0,
                        expected_operation_setup_count=0,expected_generated_operation_count=0)
    assert report["export_files_verified"] and report["native_calls_returned"]
    assert list(report["exports"])==["stock"]
    geometry.machine.CreateSTLOfStock.assert_called_once()
    geometry.machine.CreateSTLOfWIPs2.assert_not_called()
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_not_called()


@pytest.mark.parametrize("kinds", [["wip"],["stock","wip"],["stock","target"],["target","wip"]])
def test_zero_counts_never_enable_wip_or_mixed_batch(geometry,kinds):
    with pytest.raises(ValueError):
        geometry.run(export_kinds=kinds,expected_feature_count=0,expected_operation_count=0,
                     expected_operation_setup_count=0,expected_generated_operation_count=0)
    geometry.probe.context.assert_not_called()
    assert not geometry.probe.directory.exists()


def test_stock_zero_expectations_must_match_actual_inventory(geometry):
    report=geometry.run(export_kinds=["stock"],expected_feature_count=0,expected_operation_count=0,
                        expected_operation_setup_count=0,expected_generated_operation_count=0)
    assert report["status"]=="error"
    geometry.machine.CreateSTLOfStock.assert_not_called()


def test_target_only_before_afr_exports_fcs_geometry_with_two_native_arguments(geometry):
    geometry.probe.state["inventory"].update(feature_count=0,operation_count=0,operation_setup_count=0,operations=[])
    report=geometry.run(export_kinds=["target"],expected_feature_count=0,expected_operation_count=0,
                        expected_operation_setup_count=0,expected_generated_operation_count=0)
    assert report["export_files_verified"] and report["exports"]["target"]["source"]=="target_part_in_FCS"
    assert report["native_parameters"]["target_reference_frame"]=="native_FCS"
    geometry.machine.CreateSTLOfTargetInFCSSpace.assert_called_once_with(str(geometry.probe.directory/"target.stl"),0)
    geometry.machine.CreateSTLOfStock.assert_not_called()
    geometry.machine.CreateSTLOfWIPs2.assert_not_called()
