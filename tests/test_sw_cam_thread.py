"""THREAD 单次插入及默认参数资格验证；仅模拟接口与本地回执，不连接 CAD。"""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_events as events
from scripts import sw_cam_thread as cam

TLB = "verified/camworks.tlb"
DOUBLE = ("GetPitchValue", "GetDepthPerCutValue", "GetLastDepthPerCutValue", "GetStartLengthValue",
          "GetEndLengthValue", "GetEntryAngleValue", "GetWithdrawAngleValue", "GetActualPitchValue",
          "GetLeadinAmtValue", "GetLeadinAngleValue", "GetLeadoutAmtValue", "GetLeadoutAngleValue",
          )
DISABLED_GETTERS = ("GetMinZLimit", "GetMaxZLimit", "GetMaxZTurnMethod", "GetMinZTurnMethod",
    "IsMultiStartThread", "GetMaxZUseSetupDefn", "GetMinZUseSetupDefn", "CutType_ConstantCutDepth",
    "InfeedType", "ReverseCut", "MirrorAboutCenterline", "Chamfer", "CannedCycleOutput")
INTEGER = ("GetNumFinalPassValue", "GetNumStartThreadsValue", "GetLeadinTypeValue", "GetLeadoutTypeValue")


def addition(before, new_id=99):
    after = deepcopy(before)
    after["document"]["needs_save"] = True
    for row in after["operations"]:
        if row["operation_index"] >= 2:
            row["operation_index"] += 1
    after["operations"].insert(2, dict(setup_index=0, operation_index=2, native_id=new_id,
        turn_operation_type=12, linked_feature_ids=[501]))
    for row in after["inventory"]["operations"]:
        if row["operation_index"] >= 2:
            row["operation_index"] += 1
    after["inventory"]["operations"].insert(2, dict(setup_index=0, operation_index=2,
        turn_operation_type=12, toolpath_generated=False, toolpath_record_counts={}))
    after["inventory"]["operation_count"] += 1
    return after


@pytest.fixture
def probe(monkeypatch, tmp_path):
    path = tmp_path / "qualification.sldprt"
    path.write_bytes(b"saved qualification fixture")
    receipt = tmp_path / "attempt.json"
    document = dict(path=str(path), title=path.name, type=1, needs_save=False)
    rows = [dict(setup_index=0, operation_index=i, turn_operation_type=2,
        toolpath_generated=i != 1, toolpath_record_counts={"linear": 36} if i != 1 else {}) for i in range(3)]
    before = dict(document=document, saved_file_sha256=cam._file_hash(path),
        inventory=dict(operation_count=3, operation_setup_count=1, feature_count=1, operations=rows),
        operations=[dict(setup_index=0, operation_index=i, native_id=10+i,
                         turn_operation_type=2, linked_feature_ids=[501]) for i in range(3)],
        selected_operation=dict(setup_index=0, operation_index=1, expected_operation_type=2),
        selected_operation_id=11, linked_feature_index=0, selected_feature_id=501,
        selected_profile=dict(name="full native profile", segments=[{"start_native": [1., 2., 3.]}]),
        thread_catalog=dict(names_resolved=True, entries=[dict(name=" Thread; exact ", tdb_id_raw=17)]),
        native_id_scope="current_document_requires_fresh_prepare_after_reopen")
    after = addition(before)
    state = dict(current=deepcopy(before), on_capture=None, on_insert=None, on_exit=None,
                 on_enter=None, on_metadata=None)
    forbidden = [Mock(side_effect=AssertionError("Generation/save is forbidden")) for _ in range(4)]
    sw = SimpleNamespace(Save=forbidden[0])
    raw_new, after_operation = object(), object()
    doc = SimpleNamespace(GetCWObjectID=Mock(return_value=(99, True)), Save=forbidden[1])
    app = SimpleNamespace(ActiveDocGTP=forbidden[2], ActiveDocGOP=forbidden[3])
    class Session:
        def __init__(self):
            self.data = dict(subscribed=False, disconnected=False, event_count=0, overflow=0,
                             callback_errors=[], disconnect_errors=[])
        def __enter__(self):
            self.data["subscribed"] = True
            if state["on_enter"]: state["on_enter"]()
            return self
        def __exit__(self, *args):
            self.data["disconnected"] = True
            if state["on_exit"]: state["on_exit"]()
        def summary(self): return deepcopy(self.data)
    session = Session()
    def insert(kind, default_id, previous):
        durable = json.loads(receipt.read_text(encoding="utf-8"))
        assert durable["phase"] == "InsertOperation" and durable["mutation_attempted"]
        assert not durable["native_call_returned"]
        assert (kind, default_id, previous) == (12, 17, after_operation)
        state["current"] = deepcopy(after)
        if state["on_insert"]: state["on_insert"]()
        return raw_new
    feature = SimpleNamespace(InsertOperation=Mock(side_effect=insert))
    handles = dict(doc=doc, app=app, feature=feature, after_operation=after_operation,
                   operations={99: {"raw": raw_new}})
    def capture(*args, check=lambda: None, diagnostic=None):
        check()
        if diagnostic is not None: diagnostic["stage"] = "mock_capture"
        if state["on_capture"]: state["on_capture"](diagnostic["phase"])
        check()
        return deepcopy(state["current"]), handles
    captures = Mock(side_effect=capture)
    snapshots = Mock(side_effect=lambda *_: deepcopy(state["current"]["document"]))
    def metadata(raw, native_doc, path, read, result):
        assert (raw, native_doc, path) == (raw_new, doc, TLB)
        result.update(native_id=99, operation_type=12, toolpath_generated=False,
                      parameters_native={"GetPitchValue": 1.5})
        if state["on_metadata"]: state["on_metadata"]()
    metadata_reader = Mock(side_effect=metadata)
    session_factory = Mock(return_value=session)
    monkeypatch.setattr(cam, "_capture", captures)
    monkeypatch.setattr(cam, "document_snapshot", snapshots)
    monkeypatch.setattr(cam, "_read_thread_operation", metadata_reader)
    monkeypatch.setattr(events, "CamMessageSession", session_factory)
    defaults = dict(expected_document_path=str(path), setup_index=0, operation_index=1,
        expected_operation_type=2, linked_feature_index=0, qualification_only=True, message_policy="vendor_default")
    def prepare(**changes):
        return cam.qualify_thread_operation(sw, "clsid", TLB, **(defaults | dict(action="prepare") | changes))
    def apply(**changes):
        options = dict(action="apply", expected_state_sha256=cam._digest(before), default_name=" Thread; exact ",
                       expected_default_id=17, receipt_path=str(receipt))
        return cam.qualify_thread_operation(sw, "clsid", TLB, **(defaults | options | changes))
    return SimpleNamespace(**locals())


def assert_no_production_claims(probe, report):
    for name in ("generation_attempted", "model_saved", "may_continue", "thread_process_qualified",
                 "thread_span_verified", "full_thread_depth_verified", "major_minor_diameters_verified",
                 "units_verified", "physical_tool_qualified"):
        assert report[name] is False
    for forbidden in probe.forbidden: forbidden.assert_not_called()


def test_prepare_is_read_only_and_hashes_saved_profile_catalog_state(probe):
    report = probe.prepare()
    assert report["status"] == "ok" and report["state_sha256"] == cam._digest(probe.before)
    assert report["feature_profile_sha256"] == cam._digest(probe.before["selected_profile"])
    assert not probe.receipt.exists() and not report["mutation_attempted"]
    probe.feature.InsertOperation.assert_not_called()
    probe.session_factory.assert_not_called()
    assert probe.captures.call_count == 1
    assert_no_production_claims(probe, report)


def test_apply_inserts_once_after_durable_receipt_preserving_two_existing_toolpaths(probe):
    saved_bytes = probe.path.read_bytes()
    report = probe.apply()
    assert report["status"] == "review_required" and report["insertion_readback_verified"]
    assert report["native_call_returned"] and report["new_operation_id"] == 99
    probe.feature.InsertOperation.assert_called_once_with(12, 17, probe.after_operation)
    assert probe.metadata_reader.call_count == 2
    assert probe.captures.call_count >= 4
    assert report["after_cleanup"] == probe.after
    old = [row for row in report["after_cleanup"]["inventory"]["operations"] if row["toolpath_generated"]]
    assert len(old) == 2 and all(row["toolpath_record_counts"] == {"linear": 36} for row in old)
    assert probe.path.read_bytes() == saved_bytes
    assert json.loads(probe.receipt.read_text())["insertion_readback_verified"] is True
    assert_no_production_claims(probe, report)


@pytest.mark.parametrize("name,value", [("linked_feature_index", True), ("linked_feature_index", -1),
    ("linked_feature_index", 64), ("operation_index", False), ("expected_operation_type", 0),
    ("qualification_only", 1), ("message_policy", "accept"), ("action", "insert"),
    ("expected_document_path", "relative.sldprt")])
def test_invalid_common_inputs_fail_before_capture(probe, name, value):
    with pytest.raises(ValueError): probe.prepare(**{name: value})
    probe.captures.assert_not_called()
    assert not probe.receipt.exists()


@pytest.mark.parametrize("name,value", [("default_name", "Thread"), ("expected_default_id", 17),
    ("expected_state_sha256", "a" * 64), ("receipt_path", "unused.json")])
def test_prepare_forbids_mutation_inputs(probe, name, value):
    with pytest.raises(ValueError): probe.prepare(**{name: value})
    probe.captures.assert_not_called()


@pytest.mark.parametrize("name,value", [("expected_default_id", 0), ("expected_default_id", True),
    ("expected_default_id", -1), ("expected_default_id", 2147483648), ("expected_default_id", 17.),
    ("default_name", ""), ("expected_state_sha256", "A" * 64),
    ("expected_state_sha256", "x" * 63), ("receipt_path", "relative.json")])
def test_invalid_apply_inputs_fail_before_receipt_or_capture(probe, name, value):
    with pytest.raises(ValueError): probe.apply(**{name: value})
    probe.captures.assert_not_called()
    assert not probe.receipt.exists()


@pytest.mark.parametrize("change", [dict(expected_state_sha256="0" * 64), dict(default_name="Thread; exact"),
                                  dict(expected_default_id=18)])
def test_stale_hash_or_nonexact_catalog_match_prevents_insert(probe, change):
    report = probe.apply(**change)
    assert report["status"] == "error" and not report["mutation_attempted"]
    probe.feature.InsertOperation.assert_not_called()
    probe.session_factory.assert_not_called()


@pytest.mark.parametrize("change", ["dirty", "unresolved_catalog", "changed_file_hash"])
def test_dirty_or_unqualified_preflight_blocks_insertion(probe, change):
    if change == "dirty": probe.state["current"]["document"]["needs_save"] = True
    elif change == "unresolved_catalog": probe.state["current"]["thread_catalog"]["names_resolved"] = False
    else: probe.state["current"]["saved_file_sha256"] = "b" * 64
    report = probe.apply()
    assert report["status"] == "error" and not report["mutation_attempted"]
    probe.feature.InsertOperation.assert_not_called()


def test_existing_receipt_replay_is_rejected_without_any_capture(probe):
    probe.receipt.write_text("historical")
    with pytest.raises(ValueError): probe.apply()
    assert probe.receipt.read_text() == "historical"
    probe.captures.assert_not_called()


def test_attempt_receipt_failure_never_enters_native_insert(probe, monkeypatch):
    original = cam._write_receipt
    def write(path, report, **options):
        if report["phase"] == "InsertOperation": raise OSError("disk fault")
        return original(path, report, **options)
    monkeypatch.setattr(cam, "_write_receipt", write)
    report = probe.apply()
    assert report["status"] == "uncertain" and not report["native_call_returned"]
    probe.feature.InsertOperation.assert_not_called()


def test_native_insert_exception_stops_without_readback_or_retry(probe):
    probe.feature.InsertOperation.side_effect = RuntimeError("native failure")
    report = probe.apply()
    assert report["status"] == "uncertain" and not report["native_call_returned"]
    assert probe.captures.call_count == 2
    probe.metadata_reader.assert_not_called()
    probe.feature.InsertOperation.assert_called_once()
    assert_no_production_claims(probe, report)


@pytest.mark.parametrize("result", [None, False])
def test_null_native_return_never_runs_id_or_metadata_readback(probe, result):
    probe.feature.InsertOperation.side_effect = None
    probe.feature.InsertOperation.return_value = result
    report = probe.apply()
    assert report["status"] == "uncertain" and report["native_call_returned"]
    assert not report["native_result_present"]
    probe.doc.GetCWObjectID.assert_not_called()
    probe.metadata_reader.assert_not_called()


@pytest.mark.parametrize("when", ["enter", "pre_insert", "insert_return", "cleanup"])
def test_messages_stop_at_boundary_without_later_native_actions(probe, when):
    def message(): probe.session.data["event_count"] = 1
    if when == "enter": probe.state["on_enter"] = message
    elif when == "pre_insert":
        probe.state["on_capture"] = lambda phase: message() if phase == "pre_insert" else None
    elif when == "insert_return": probe.state["on_insert"] = message
    else: probe.state["on_exit"] = message
    report = probe.apply()
    assert report["status"] in {"error", "uncertain"}
    assert not report["insertion_readback_verified"]
    if when in {"enter", "pre_insert"}: probe.feature.InsertOperation.assert_not_called()
    if when == "insert_return":
        probe.doc.GetCWObjectID.assert_not_called()
        probe.metadata_reader.assert_not_called()
        assert probe.captures.call_count == 2
    if when == "cleanup": assert probe.metadata_reader.call_count == 1
    assert_no_production_claims(probe, report)


@pytest.mark.parametrize("phase", ["pre_insert", "after_cleanup"])
def test_capture_drift_blocks_or_invalidates_single_insertion(probe, phase):
    def change(current_phase):
        if current_phase == phase: probe.state["current"]["selected_profile"]["name"] = "changed"
    probe.state["on_capture"] = change
    report = probe.apply()
    assert report["status"] == ("error" if phase == "pre_insert" else "uncertain")
    assert not report["insertion_readback_verified"]
    assert probe.feature.InsertOperation.call_count == (0 if phase == "pre_insert" else 1)


def test_final_metadata_document_drift_cannot_receive_verified_result(probe):
    def change():
        if probe.metadata_reader.call_count == 2:
            probe.state["current"]["document"]["path"] = "C:/other.sldprt"
    probe.state["on_metadata"] = change
    report = probe.apply()
    assert report["status"] == "uncertain"
    assert not report["insertion_readback_verified"]


@pytest.mark.parametrize("mutation", ["extra", "removed", "order", "old_type", "old_gtp", "old_records",
    "new_gtp", "new_records", "new_type", "new_link", "new_position", "profile", "file", "path"])
def test_exact_addition_rejects_unapproved_inventory_or_identity_change(probe, mutation):
    after = deepcopy(probe.after)
    if mutation == "extra": after["operations"].append(deepcopy(after["operations"][2]))
    elif mutation == "removed": after["operations"].pop(0)
    elif mutation == "order": after["operations"][0], after["operations"][1] = after["operations"][1], after["operations"][0]
    elif mutation == "old_type": after["operations"][0]["turn_operation_type"] = 4
    elif mutation == "old_gtp": after["inventory"]["operations"][0]["toolpath_generated"] = False
    elif mutation == "old_records": after["inventory"]["operations"][0]["toolpath_record_counts"] = {"linear": 37}
    elif mutation == "new_gtp": after["inventory"]["operations"][2]["toolpath_generated"] = True
    elif mutation == "new_records": after["inventory"]["operations"][2]["toolpath_record_counts"] = {"linear": 1}
    elif mutation == "new_type": after["operations"][2]["turn_operation_type"] = 2
    elif mutation == "new_link": after["operations"][2]["linked_feature_ids"] = [502]
    elif mutation == "new_position": after["operations"][2]["operation_index"] = 3
    elif mutation == "profile": after["selected_profile"]["name"] = "changed"
    elif mutation == "file": after["saved_file_sha256"] = "c" * 64
    else: after["document"]["path"] = "other.sldprt"
    with pytest.raises(ValueError): cam._verify_addition(probe.before, after, 99)


@pytest.mark.parametrize("new_id", [True, 0, -1, 11])
def test_new_id_cannot_alias_preexisting_operation_or_boolean(probe, new_id):
    with pytest.raises(ValueError): cam._verify_addition(probe.before, probe.after, new_id)


@pytest.fixture
def native(monkeypatch):
    raw, raw_feature, raw_tool = object(), object(), object()
    operation = SimpleNamespace(GetIsToolpathGenerated=Mock(return_value=False),
        IGetAllFeatures=Mock(side_effect=AssertionError("Ancillary feature reads are disabled")),
        IGetTool=Mock(side_effect=AssertionError("Ancillary tool reads are disabled")))
    turning = SimpleNamespace(OpernType=Mock(return_value=12))
    thread = SimpleNamespace()
    for name in DOUBLE: setattr(thread, name, Mock(return_value=1.25))
    for name in DISABLED_GETTERS:
        setattr(thread, name, Mock(side_effect=AssertionError("Unqualified metadata getter must remain disabled")))
    for name in INTEGER: setattr(thread, name, Mock(return_value=2))
    tool = SimpleNamespace(ToolType=Mock(return_value=15))
    bindings = {(id(raw), "ICWOperation"): operation, (id(raw), "ICWTurnOperation"): turning,
        (id(raw), "ICWTurnThreadOp"): thread, (id(raw_tool), "ICWTool"): tool}
    doc = SimpleNamespace(GetCWObjectID=Mock(side_effect=lambda obj: (99 if obj is operation else 501 if obj is raw_feature else 701, True)))
    def typed(obj, name, path):
        assert path == TLB
        return bindings[id(obj), name]
    profile_reader = Mock(side_effect=AssertionError("Ancillary profile reads are disabled"))
    tool_reader = Mock(side_effect=AssertionError("Ancillary tool metadata reads are disabled"))
    reader = Mock(wraps=cam._member)
    monkeypatch.setattr(cam, "_typed", typed)
    monkeypatch.setattr(cam, "_collection", lambda obj, path: obj)
    monkeypatch.setattr(cam, "_read_profile", profile_reader)
    monkeypatch.setattr(cam, "_read_tool", tool_reader, raising=False)
    result = {}
    def run(): return cam._read_thread_operation(raw, doc, TLB, reader, result)
    return SimpleNamespace(**locals())


def test_active_16_read_members_preserve_exact_names_and_strict_scalar_types(native):
    native.run()
    values = native.result["parameters_native"]
    assert set(values) == set(DOUBLE + INTEGER) and len(values) == 16
    assert all(type(values[name]) is float for name in DOUBLE)
    assert all(type(values[name]) is int for name in INTEGER)
    assert "linked_features" not in native.result and "tool" not in native.result
    assert native.result["ancillary_metadata"]["reason"] == "unqualified_THREAD_additional_getters_disabled"
    native.operation.IGetAllFeatures.assert_not_called()
    native.operation.IGetTool.assert_not_called()
    native.profile_reader.assert_not_called()
    native.tool_reader.assert_not_called()
    assert native.result["parameter_metadata_complete"] is False
    assert native.result["supported_parameter_reads_complete"] is True
    assert native.result["declared_parameter_count"] == 29 and native.result["read_parameter_count"] == 16
    assert set(native.result["unavailable_getters"]) == set(DISABLED_GETTERS)
    for name in DISABLED_GETTERS: getattr(native.thread, name).assert_not_called()
    assert not native.result["units_verified"] and not native.result["thread_span_verified"]
    assert all(not call.args[1].startswith("Set") for call in native.reader.call_args_list)


def test_generation_flag_still_rejects_numeric_one(native):
    native.operation.GetIsToolpathGenerated.return_value = 1
    with pytest.raises(ValueError): native.run()
    assert native.reader.call_args.args[1] == "GetIsToolpathGenerated"
    native.thread.GetPitchValue.assert_not_called()


@pytest.mark.parametrize("name", INTEGER)
def test_long_and_enum_getters_reject_boolean(native, name):
    getattr(native.thread, name).return_value = True
    with pytest.raises(ValueError): native.run()
    assert native.reader.call_args.args[1] == name
    native.operation.IGetAllFeatures.assert_not_called()


@pytest.mark.parametrize("name", DOUBLE)
def test_double_getters_reject_nonfinite_value(native, name):
    getattr(native.thread, name).return_value = float("inf")
    with pytest.raises(ValueError): native.run()
    assert native.reader.call_args.args[1] == name
    native.operation.IGetAllFeatures.assert_not_called()


@pytest.mark.parametrize("value", [True, "1.5", None])
def test_double_getter_rejects_coercible_or_missing_value(native, value):
    native.thread.GetPitchValue.return_value = value
    with pytest.raises(ValueError): native.run()
    assert native.result["parameters_native"] == {}


@pytest.mark.parametrize("value", [(0, True), (99, False), (99, 1), (True, True),
    (4294967296, True), (99,), None])
def test_native_id_requires_positive_ulong_and_strict_success_flag(native, value):
    native.doc.GetCWObjectID.side_effect = None
    native.doc.GetCWObjectID.return_value = value
    with pytest.raises(ValueError): native.run()
    native.turning.OpernType.assert_not_called()


def test_metadata_first_getter_exception_preserves_earlier_reads(native):
    native.thread.GetEndLengthValue.side_effect = RuntimeError("native fault")
    with pytest.raises(RuntimeError): native.run()
    assert native.result["parameters_native"]["GetStartLengthValue"] == 1.25
    assert "GetEndLengthValue" not in native.result["parameters_native"]
    native.thread.GetEntryAngleValue.assert_not_called()
    native.operation.IGetAllFeatures.assert_not_called()


@pytest.mark.parametrize("kind,generated", [(2, False), (12, True), (12, 1)])
def test_returned_operation_must_be_un_generated_thread(native, kind, generated):
    native.turning.OpernType.return_value = kind
    native.operation.GetIsToolpathGenerated.return_value = generated
    with pytest.raises(ValueError): native.run()
    native.thread.GetPitchValue.assert_not_called()


def test_capture_rejects_missing_selected_feature_before_profile_catalog_or_file_read(native, monkeypatch, tmp_path):
    path = tmp_path / "qualification.sldprt"
    document = dict(path=str(path), title=path.name, type=1, needs_save=False)
    raw_setup = object()
    setup = SimpleNamespace(IGetEnumOperations=Mock(return_value=[native.raw]))
    machine = SimpleNamespace(IGetEnumOpSetups=Mock(return_value=[raw_setup]))
    native.bindings[id(native.doc), "ICWDoc3"] = native.doc
    native.bindings[id(raw_setup), "ICWBaseOpSetup"] = setup
    native.operation.IGetAllFeatures.side_effect = None
    native.operation.IGetAllFeatures.return_value = []
    native.turning.OpernType.return_value = 2
    file_reader = Mock(side_effect=AssertionError("Missing feature must stop before saved-file read"))
    inventories = Mock(return_value={"operations": []})
    monkeypatch.setattr(cam, "_context", Mock(return_value=(document, native.doc, object(), machine, object())))
    monkeypatch.setattr(cam, "_inventory", inventories)
    monkeypatch.setattr(cam, "_file_hash", file_reader)
    diagnostic = {}
    with pytest.raises(ValueError, match="linked feature index"):
        cam._capture(object(), "clsid", TLB,
            dict(setup_index=0, operation_index=0, expected_operation_type=2), 0, str(path), diagnostic=diagnostic)
    assert diagnostic["operations"][0]["linked_feature_ids"] == []
    native.profile_reader.assert_not_called()
    file_reader.assert_not_called()
    assert inventories.call_count == 1


@pytest.fixture
def recovery(native, monkeypatch, tmp_path):
    path = tmp_path / "existing_thread.sldprt"
    path.write_bytes(b"saved file before unsaved thread insertion")
    document = dict(path=str(path), title=path.name, type=1, needs_save=True)
    inventory = dict(operation_count=3, operations=[
        dict(setup_index=0, operation_index=0, turn_operation_type=12,
             toolpath_generated=False, toolpath_record_counts={}),
        dict(setup_index=0, operation_index=1, turn_operation_type=2,
             toolpath_generated=True, toolpath_record_counts={"linear": 36}),
        dict(setup_index=0, operation_index=2, turn_operation_type=1,
             toolpath_generated=True, toolpath_record_counts={"linear": 40})])
    raw_setup = object()
    setup = SimpleNamespace(IGetEnumOperations=Mock(return_value=[native.raw, object(), object()]))
    machine = SimpleNamespace(IGetEnumOpSetups=Mock(return_value=[raw_setup]))
    native.bindings[id(native.doc), "ICWDoc3"] = native.doc
    native.bindings[id(raw_setup), "ICWBaseOpSetup"] = setup
    forbidden = [Mock(side_effect=AssertionError("Recovery must not mutate or subscribe")) for _ in range(6)]
    sw = SimpleNamespace(Save=forbidden[0])
    native.operation.GenerateToolpath = forbidden[1]
    native.doc.Save = forbidden[2]
    context = Mock(return_value=(deepcopy(document), native.doc, object(), machine, object()))
    inventories = Mock(side_effect=lambda *_: deepcopy(inventory))
    snapshots = Mock(side_effect=lambda *_: deepcopy(document))
    hashes = Mock(return_value=cam._file_hash(path))
    monkeypatch.setattr(cam, "_context", context)
    monkeypatch.setattr(cam, "_inventory", inventories)
    monkeypatch.setattr(cam, "document_snapshot", snapshots)
    monkeypatch.setattr(cam, "_file_hash", hashes)
    monkeypatch.setattr(cam, "qualify_thread_operation", forbidden[3])
    monkeypatch.setattr(events, "CamMessageSession", forbidden[4])
    monkeypatch.setattr(cam, "_write_receipt", forbidden[5])
    def run(**changes):
        options = dict(expected_document_path=str(path), setup_index=0, operation_index=0,
                       expected_operation_type=12, expected_thread_native_id=99)
        return cam.inspect_thread_operation(sw, "clsid", TLB, **(options | changes))
    return SimpleNamespace(**locals())


def assert_recovery_read_only(recovery, result):
    for key in ("mutation_attempted", "generation_attempted", "model_saved", "may_continue",
                "thread_process_qualified", "parameter_metadata_complete"):
        assert result[key] is False
    for forbidden in recovery.forbidden: forbidden.assert_not_called()
    recovery.native.operation.IGetAllFeatures.assert_not_called()
    recovery.native.operation.IGetTool.assert_not_called()
    recovery.native.profile_reader.assert_not_called()
    recovery.native.tool_reader.assert_not_called()
    for name in DISABLED_GETTERS: getattr(recovery.native.thread, name).assert_not_called()


def test_recovery_reads_existing_dirty_thread_without_insert_save_generation_or_z_getters(recovery):
    old_bytes = recovery.path.read_bytes()
    result = recovery.run()
    assert result["status"] == "review_required" and result["supported_readback_verified"]
    assert result["document_before"]["needs_save"] and result["document_after"]["needs_save"]
    assert result["observed_thread_native_id"] == 99
    assert result["inventory_before"] == result["inventory_after"] == recovery.inventory
    assert result["inventory_unchanged"] and result["active_document_unchanged"] and result["saved_file_unchanged"]
    assert result["thread_operation"]["read_parameter_count"] == 16
    assert result["metadata_limits"]["GetMinZLimit"]["hresult"] == -2147417851
    assert "GetMinZLimit" not in result["thread_operation"]["parameters_native"]
    assert "GetMaxZLimit" not in result["thread_operation"]["parameters_native"]
    assert recovery.hashes.call_count == 2 and recovery.inventories.call_count == 2
    assert recovery.path.read_bytes() == old_bytes
    assert_recovery_read_only(recovery, result)


@pytest.mark.parametrize("name,value", [("setup_index", True), ("operation_index", -1),
    ("operation_index", 512), ("expected_operation_type", 2), ("expected_operation_type", True),
    ("expected_thread_native_id", True), ("expected_thread_native_id", 0),
    ("expected_thread_native_id", 4294967296), ("expected_thread_native_id", 99.),
    ("expected_document_path", "relative.sldprt")])
def test_recovery_invalid_target_is_rejected_before_context(recovery, name, value):
    result = recovery.run(**{name: value})
    assert result["status"] == "error" and result["failed_stage"] == "validate_inputs"
    recovery.context.assert_not_called()
    assert_recovery_read_only(recovery, result)


def test_recovery_mismatched_native_id_prevents_all_metadata_and_file_reads(recovery):
    result = recovery.run(expected_thread_native_id=100)
    assert result["status"] == "error" and result["observed_thread_native_id"] == 99
    recovery.native.thread.GetPitchValue.assert_not_called()
    recovery.hashes.assert_not_called()
    recovery.snapshots.assert_not_called()
    assert recovery.inventories.call_count == 1
    assert_recovery_read_only(recovery, result)


def test_recovery_wrong_document_stops_before_inventory(recovery, tmp_path):
    result = recovery.run(expected_document_path=str(tmp_path / "another.sldprt"))
    assert result["status"] == "error"
    recovery.inventories.assert_not_called()
    recovery.native.thread.GetPitchValue.assert_not_called()
    assert_recovery_read_only(recovery, result)


@pytest.mark.parametrize("mismatch", ["missing", "inventory_type", "native_type"])
def test_recovery_selected_operation_must_remain_thread(recovery, mismatch):
    if mismatch == "missing": recovery.inventory["operations"].pop(0)
    elif mismatch == "inventory_type": recovery.inventory["operations"][0]["turn_operation_type"] = 2
    else: recovery.native.turning.OpernType.return_value = 2
    result = recovery.run()
    assert result["status"] == "error"
    recovery.native.thread.GetPitchValue.assert_not_called()
    recovery.snapshots.assert_not_called()
    assert_recovery_read_only(recovery, result)


def test_recovery_native_exception_preserves_partial_parameters_without_after_reads(recovery):
    recovery.native.thread.GetLeadoutAngleValue.side_effect = RuntimeError("private server fault")
    result = recovery.run()
    assert result["status"] == "error" and result["failed_stage"] == "GetLeadoutAngleValue"
    partial = result["thread_operation"]
    assert partial["parameters_native"]["GetLeadoutAmtValue"] == 1.25
    assert "GetLeadoutAngleValue" not in partial["parameters_native"]
    assert set(partial["unavailable_getters"]) == set(DISABLED_GETTERS)
    recovery.native.operation.IGetAllFeatures.assert_not_called()
    assert recovery.hashes.call_count == 1 and recovery.inventories.call_count == 1
    recovery.snapshots.assert_not_called()
    assert "private server fault" not in json.dumps(result)
    assert_recovery_read_only(recovery, result)


@pytest.mark.parametrize("changed", ["inventory", "document", "saved_file"])
def test_recovery_final_state_drift_is_not_verified(recovery, changed):
    if changed == "inventory":
        after = deepcopy(recovery.inventory)
        after["operations"][1]["toolpath_record_counts"] = {"linear": 37}
        recovery.inventories.side_effect = [deepcopy(recovery.inventory), after]
    elif changed == "document":
        after = deepcopy(recovery.document)
        after["path"] = "C:/changed.sldprt"
        recovery.snapshots.side_effect = None
        recovery.snapshots.return_value = after
    else: recovery.hashes.side_effect = ["a" * 64, "b" * 64]
    result = recovery.run()
    assert result["status"] == "error" and result["supported_readback_verified"] is False
    assert result["reason"] == "CAM_STATE_CHANGED_DURING_THREAD_RECOVERY"
    assert_recovery_read_only(recovery, result)


def test_recovery_final_native_identity_change_stops_before_final_inventory(recovery):
    reads = []
    def identity(obj):
        if obj is recovery.native.operation:
            reads.append(obj)
            return (99 if len(reads) < 3 else 100, True)
        return (501 if obj is recovery.native.raw_feature else 701, True)
    recovery.native.doc.GetCWObjectID.side_effect = identity
    result = recovery.run()
    assert result["status"] == "error" and result["failed_stage"] == "GetCWObjectID"
    assert result["thread_operation"]["supported_parameter_reads_complete"]
    assert recovery.inventories.call_count == 1 and recovery.hashes.call_count == 1
    recovery.snapshots.assert_not_called()
    assert_recovery_read_only(recovery, result)


def test_unavailable_metadata_distinguishes_two_observed_faults_from_eleven_untested_getters(native):
    native.run()
    excluded = native.result["unavailable_getters"]
    observed = {name for name, detail in excluded.items() if detail["reason"] == "observed_CAM_SERVERFAULT"}
    assert observed == {"GetMinZLimit", "GetMaxZTurnMethod"}
    assert all(excluded[name]["hresult"] == -2147417851 for name in observed)
    untested = set(DISABLED_GETTERS) - observed
    assert len(untested) == 11
    assert all(excluded[name]["reason"] == "untested_disabled_after_CAM_SERVERFAULT" for name in untested)
    assert all("hresult" not in excluded[name] for name in untested)
    called = {call.args[1] for call in native.reader.call_args_list}
    assert not called.intersection(DISABLED_GETTERS)
    for name in DISABLED_GETTERS: getattr(native.thread, name).assert_not_called()


def test_scalar_metadata_does_not_convert_historical_tool_failure_to_tool_absence(native):
    native.operation.IGetTool.side_effect = RuntimeError("historical COM failure -2147220990")
    native.run()
    native.operation.IGetTool.assert_not_called()
    assert "tool" not in native.result
    assert "linked_features" not in native.result
    assert native.result["ancillary_metadata"]["reason"] == "unqualified_THREAD_additional_getters_disabled"
    ancillary = native.result["ancillary_metadata"]
    assert ancillary["IGetTool"] == {"observed_hresult": -2147220990, "presence_verified": False}
    assert ancillary["linked_profiles_read"] is ancillary["tool_read"] is ancillary["holder_read"] is False
    assert native.result["readback_scope"] == "identity_and_16_confirmed_thread_scalars"
    assert native.result["physical_tool_qualified"] is False
    assert native.result["read_parameter_count"] == 16
