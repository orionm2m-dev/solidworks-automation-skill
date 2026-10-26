"""车削刀片单字段定义的共享引用、持久回执及 fail-stop 回归；不连接 CAD。"""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_turn_tool as cam
from scripts import sw_cam_events as events


def ref(index, kind=2):
    return {"setup_index": 0, "operation_index": index, "expected_operation_type": kind}


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path = tmp_path / "working.sldprt"
    path.write_bytes(b"fixture")
    receipt = tmp_path / "change.json"
    before = {"document": {"path": str(path), "title": path.name, "type": 1, "needs_save": False},
        "inventory": {"operations": [
            {"setup_index": 0, "operation_index": 0, "turn_operation_type": 2, "toolpath_generated": False},
            {"setup_index": 0, "operation_index": 1, "turn_operation_type": 2, "toolpath_generated": False},
            {"setup_index": 0, "operation_index": 2, "turn_operation_type": 1, "toolpath_generated": True}]},
        "selected_operation": ref(0), "selected_tool_group": 0, "station_id": "native-A",
        "affected_operations": [ref(0), ref(1)],
        "operation_tools": [{"operation": ref(0), "tool_group": 0}, {"operation": ref(1), "tool_group": 0},
                            {"operation": ref(2, 1), "tool_group": 1}],
        "tool_groups": [{"insert_type_raw": 1, "dimensions_native": {"NoseRadius": .8, "Thickness": 4., "InscribedCircle": 12.}},
                        {"insert_type_raw": 2, "dimensions_native": {"Width": 1., "Radius1": .05, "Radius2": .05, "Thickness": 2.}}],
        "linked_features": [{"name": "profile", "start_native": [1., 2., 3.]}],
        "selected_tool": {"present": True, "insert_type_raw": 1, "info_raw": "native tool",
                          "dimensions_native": {"NoseRadius": .8, "Thickness": 4., "InscribedCircle": 12.},
                          "holder": {"shape_raw": 1}}}
    state = {"current": deepcopy(before), "writes": [], "on_write": None, "on_exit": None, "on_snapshot": None}
    class Tool:
        def __setattr__(self, field, value):
            durable = json.loads(receipt.read_text(encoding="utf-8"))
            assert durable["mutation_attempted"] and durable["phase"] == "property_put"
            assert not durable["native_call_returned"]
            state["writes"].append((field, value))
            if state["on_write"]: state["on_write"]()
            state["current"]["tool_groups"][0]["dimensions_native"][field] = value
            state["current"]["selected_tool"]["dimensions_native"][field] = value
            state["current"]["selected_tool"]["info_raw"] = "updated size"
            state["current"]["document"]["needs_save"] = True
    tool = Tool()
    class Session:
        def __init__(self):
            self.data = dict(subscribed=False, disconnected=False, event_count=0, overflow=0,
                             callback_errors=[], disconnect_errors=[])
        def __enter__(self):
            self.data["subscribed"] = True
            return self
        def __exit__(self, *args):
            self.data["disconnected"] = True
            if state["on_exit"]: state["on_exit"]()
        def summary(self): return deepcopy(self.data)
    session = Session()
    def snapshot(*args, **kwargs):
        check = kwargs.get("check", lambda: None)
        check()
        if state["on_snapshot"]: state["on_snapshot"]()
        check()
        return deepcopy(state["current"]), {"app": object(), "turn_tool": tool}
    snapshots = Mock(side_effect=snapshot)
    monkeypatch.setattr(cam, "_snapshot", snapshots)
    monkeypatch.setattr(cam, "document_snapshot", lambda *_: deepcopy(state["current"]["document"]))
    monkeypatch.setattr(events, "CamMessageSession", Mock(return_value=session))
    defaults = dict(expected_document_path=str(path), setup_index=0, operation_index=0,
                    expected_operation_type=2, field="NoseRadius", qualification_only=True,
                    message_policy="vendor_default")
    def prepare(**changes):
        return cam.configure_turn_tool(object(), "clsid", "verified.tlb", **(defaults | dict(action="prepare") | changes))
    def apply(**changes):
        values = dict(action="apply", value_native=.1, expected_state_sha256=cam._digest(before),
                      allowed_affected_operations=[ref(0), ref(1)], receipt_path=str(receipt))
        return cam.configure_turn_tool(object(), "clsid", "verified.tlb", **(defaults | values | changes))
    return SimpleNamespace(**locals())


def test_prepare_is_read_only_and_fingerprints_full_profile_tool_state(probe):
    result = probe.prepare()
    assert result["status"] == "ok" and result["apply_eligible"]
    assert result["state_sha256"] == cam._digest(probe.before)
    assert result["profile_sha256"] == cam._digest(probe.before["linked_features"])
    assert result["tool_sha256"] == cam._digest(probe.before["selected_tool"])
    assert not result["mutation_attempted"] and not result["may_continue"]
    assert probe.state["writes"] == [] and not probe.receipt.exists()
    events.CamMessageSession.assert_not_called()


@pytest.mark.parametrize("field,value", [("NoseRadius", .1), ("Thickness", 3.9), ("InscribedCircle", 9.5)])
def test_one_property_put_durable_intent_return_and_post_cleanup_readback(probe, field, value):
    result = probe.apply(field=field, value_native=value)
    assert result["status"] == "review_required" and result["readback_verified"]
    assert result["native_call_returned"] and result["messages"]["disconnected"]
    assert result["verification_scope"] == "all_operation_references_after_event_cleanup"
    assert probe.state["writes"] == [(field, value)]
    assert result["after_cleanup"]["tool_groups"][0]["dimensions_native"][field] == value
    assert result["after_cleanup"]["tool_groups"][1] == probe.before["tool_groups"][1]
    assert not result["may_continue"] and not result["physical_tool_qualified"]
    assert not result["generation_attempted"] and not result["model_saved"]
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("field,value", [("Width", 0), ("Thickness", 0), ("InscribedCircle", 0),
    ("NoseRadius", -1), ("NoseRadius", True), ("NoseRadius", float("nan")), ("NoseRadius", "1"),
    ("HolderShape", 1)])
def test_bad_dimension_inputs_fail_without_cad_or_receipt(probe, field, value):
    with pytest.raises(ValueError):
        probe.apply(field=field, value_native=value)
    probe.snapshots.assert_not_called()
    assert not probe.receipt.exists()


@pytest.mark.parametrize("extra", ["receipt_path", "value_native", "expected_state_sha256", "allowed_affected_operations"])
def test_prepare_rejects_mutation_arguments(probe, extra):
    with pytest.raises(ValueError):
        probe.prepare(**{extra: "not allowed"})
    probe.snapshots.assert_not_called()


@pytest.mark.parametrize("change", ["profile", "tool", "inventory", "station"])
def test_stale_expected_old_state_blocks_write(probe, change):
    if change == "profile": probe.state["current"]["linked_features"][0]["name"] = "different"
    elif change == "tool": probe.state["current"]["selected_tool"]["holder"]["shape_raw"] = 2
    elif change == "inventory": probe.state["current"]["inventory"]["extra"] = 1
    else: probe.state["current"]["station_id"] = "different"
    result = probe.apply()
    assert result["status"] == "error" and not result["mutation_attempted"]
    assert probe.state["writes"] == []


def test_generated_shared_operation_blocks_but_generated_unrelated_operation_is_allowed(probe):
    probe.state["current"]["inventory"]["operations"][1]["toolpath_generated"] = True
    result = probe.prepare()
    assert not result["apply_eligible"] and len(result["affected_generated_operations"]) == 1
    result = probe.apply(expected_state_sha256=cam._digest(probe.state["current"]))
    assert result["status"] == "error" and probe.state["writes"] == []


@pytest.mark.parametrize("allowed", [[ref(0)], [ref(0), ref(1), ref(2, 1)]])
def test_all_and_only_shared_operations_must_be_explicitly_allowed(probe, allowed):
    assert probe.apply(allowed_affected_operations=allowed)["status"] == "error"
    assert probe.state["writes"] == []


def test_same_operation_with_different_type_is_still_duplicate(probe):
    with pytest.raises(ValueError):
        probe.apply(allowed_affected_operations=[ref(0), ref(1), ref(1, 4)])
    probe.snapshots.assert_not_called()


@pytest.mark.parametrize("change", ["dirty", "wrong_document", "inapplicable", "noop"])
def test_document_applicability_and_noop_guards(probe, change):
    kwargs = {}
    if change == "dirty": probe.state["current"]["document"]["needs_save"] = True
    elif change == "wrong_document": probe.state["current"]["document"]["path"] += ".other"
    elif change == "inapplicable": kwargs["field"] = "Width"
    else: kwargs["value_native"] = .8
    assert probe.apply(**kwargs)["status"] == "error"
    assert probe.state["writes"] == []


def test_existing_receipt_prevents_replay_before_any_native_read(probe):
    probe.receipt.write_text("immutable", encoding="utf-8")
    with pytest.raises(ValueError): probe.apply()
    probe.snapshots.assert_not_called()
    assert probe.receipt.read_text() == "immutable"


def test_property_put_exception_is_uncertain_no_readback_retry_or_rollback(probe):
    def failed(): raise RuntimeError("native property put failed")
    probe.state["on_write"] = failed
    result = probe.apply()
    assert result["status"] == "uncertain" and not result["native_call_returned"]
    assert probe.snapshots.call_count == 2
    assert probe.session.data["disconnected"]
    assert len(probe.state["writes"]) == 1


def test_event_after_property_put_stops_before_native_readback(probe):
    probe.state["on_write"] = lambda: probe.session.data.update(event_count=1)
    result = probe.apply()
    assert result["status"] == "uncertain" and result["native_call_returned"]
    assert not result["readback_verified"] and probe.snapshots.call_count == 2


@pytest.mark.parametrize("change", ["profile", "unrelated_tool", "usage", "document"])
def test_post_cleanup_changes_invalidate_verification(probe, change):
    def drift():
        current = probe.state["current"]
        if change == "profile": current["linked_features"][0]["name"] = "changed"
        elif change == "unrelated_tool": current["tool_groups"][1]["dimensions_native"]["Width"] = 12.
        elif change == "usage": current["affected_operations"].append(ref(2, 1))
        else: current["document"]["path"] += ".other"
    probe.state["on_exit"] = drift
    result = probe.apply()
    assert result["readback_before_cleanup_verified"]
    assert result["status"] == "uncertain" and not result["readback_verified"]


def test_receipt_failure_before_property_put_blocks_mutation(probe, monkeypatch):
    original = cam._write_receipt
    def fail(path, report, **kwargs):
        if not kwargs.get("create"): raise OSError("storage unavailable")
        return original(path, report, **kwargs)
    monkeypatch.setattr(cam, "_write_receipt", fail)
    result = probe.apply()
    assert result["status"] == "uncertain" and probe.state["writes"] == []
    assert not result["readback_verified"]


@pytest.fixture
def native_graph(monkeypatch):
    document = {"path": "working.sldprt", "title": "working.sldprt", "type": 1, "needs_save": False}
    a = SimpleNamespace(identity=object(), native_id=101, ToolType=15, InsertType=1, NoseRadius=.8, Thickness=4., InscribedCircle=12.)
    b = SimpleNamespace(identity=object(), native_id=202, ToolType=15, InsertType=2, Width=1., Radius1=.05, Radius2=.05, Thickness=2.)
    operations = [SimpleNamespace(identity=object(), OpernType=2, IGetTool=Mock(return_value=tool),
                                 IGetAllFeatures=Mock(return_value=[object()])) for tool in (a, a, b)]
    for index, operation in enumerate(operations): operation.native_id = 1001 + index
    native_doc = SimpleNamespace(
        GetCWObjectID=Mock(side_effect=lambda obj: (obj.native_id, True)),
        GetCWObjectFromID=Mock(return_value=(a, True)))
    station = SimpleNamespace(GetStationId="native-id", GetTool=a, OperationsUsingThisTool=operations[:2])
    a.GetToolStation = station
    setup = SimpleNamespace(IGetEnumOperations=operations)
    machine = SimpleNamespace(IGetEnumOpSetups=[setup])
    inventory = {"operations": [{"setup_index": 0, "operation_index": i, "turn_operation_type": 2,
                                "toolpath_generated": False} for i in range(3)]}
    monkeypatch.setattr(cam, "_context", lambda *_: (deepcopy(document), native_doc, object(), machine, object()))
    inventory_reader = Mock(side_effect=lambda *_: deepcopy(inventory))
    document_reader = Mock(side_effect=lambda *_: deepcopy(document))
    monkeypatch.setattr(cam, "_inventory", inventory_reader)
    monkeypatch.setattr(cam, "document_snapshot", document_reader)
    def typed(raw, interface, *_):
        if interface == "ICWTurnTool":
            return SimpleNamespace(**(vars(raw) | {"ToolType": getattr(raw, "turn_subtype", 1)}))
        return raw
    monkeypatch.setattr(cam, "_typed", typed)
    monkeypatch.setattr(cam, "_identity", lambda raw: raw.identity)
    monkeypatch.setattr(cam, "_collection", lambda raw, *_: list(raw))
    profile_reader = Mock(side_effect=lambda *args: args[-1].update({"name": "known profile"}))
    tool_reader = Mock(side_effect=lambda *args: args[-1].update({"present": True, "dimensions_native": {"NoseRadius": .8}}))
    monkeypatch.setattr(cam, "_read_profile", profile_reader)
    monkeypatch.setattr(cam, "_read_tool", tool_reader)
    def run(**kwargs): return cam._snapshot(object(), "clsid", "tlb", ref(0), **kwargs)
    return SimpleNamespace(**locals())


def test_native_usage_is_crosschecked_against_every_operation_tool_identity(native_graph):
    state, native = native_graph.run()
    assert state["affected_operations"] == [ref(0), ref(1)]
    assert [item["tool_group"] for item in state["operation_tools"]] == [0, 0, 1]
    assert native["turn_tool"].native_id == native_graph.a.native_id
    for operation in native_graph.operations: operation.IGetTool.assert_called()


@pytest.mark.parametrize("failure", ["omitted_shared", "extra_unshared", "foreign", "duplicate", "wrong_station_tool"])
@pytest.mark.parametrize("station_id", ["native-id", ""])
def test_inconsistent_native_shared_reference_sources_block(native_graph, failure, station_id):
    g = native_graph
    g.station.GetStationId = station_id
    if failure == "omitted_shared": g.station.OperationsUsingThisTool = g.operations[:1]
    elif failure == "extra_unshared": g.station.OperationsUsingThisTool = g.operations
    elif failure == "foreign": g.station.OperationsUsingThisTool = [SimpleNamespace(identity=object(), native_id=9999)]
    elif failure == "duplicate": g.station.OperationsUsingThisTool = [g.operations[0]] * 2
    else: g.station.GetTool = g.b
    expected = {"omitted_shared": "CAM_TOOL_SHARED_USAGE_MISMATCH",
                "extra_unshared": "CAM_TOOL_SHARED_USAGE_MISMATCH",
                "foreign": "CAM_TOOL_USAGE_REFERENCES_INVALID",
                "duplicate": "CAM_TOOL_USAGE_REFERENCES_INVALID",
                "wrong_station_tool": "CAM_TOOL_STATION_IDENTITY_MISMATCH"}[failure]
    with pytest.raises(cam.CamToolStateError) as caught: g.run()
    assert caught.value.reason == expected
    g.profile_reader.assert_not_called()
    g.tool_reader.assert_not_called()


def test_only_standard_iunknown_identity_is_queried(monkeypatch):
    import comtypes
    marker = object()
    query = Mock(return_value=marker)
    obj = SimpleNamespace(QueryInterface=query)
    assert cam._identity(obj) is marker
    query.assert_called_once_with(comtypes.IUnknown)


def test_heterogeneous_plan_does_not_query_drill_as_turn_tool(native_graph, monkeypatch):
    g = native_graph
    g.b.ToolType = 3
    queried = []
    def typed(raw, interface, *_):
        queried.append((raw, interface))
        if raw is g.b and interface == "ICWTurnTool":
            raise AssertionError("A drill must never be queried as a turning insert")
        return g.typed(raw, interface)
    monkeypatch.setattr(cam, "_typed", typed)
    state, _native = g.run()
    assert state["affected_operations"] == [ref(0), ref(1)]
    assert state["tool_groups"][1] == {"cam_object_id": 202, "tool_type_raw": 3, "insert_type_raw": None,
        "dimensions_native": {}, "parameter_scope": "non_turn_dimensions_not_read", "turn_tool_type_raw": None}
    assert not any(raw is g.b and interface == "ICWTurnTool" for raw, interface in queried)


def test_non_turn_selected_tool_is_rejected_before_station_or_profile(native_graph):
    native_graph.a.ToolType = 3
    with pytest.raises(ValueError, match="ToolType=15"):
        native_graph.run()


def _prepare_native_graph(graph, tmp_path):
    """通过真实 snapshot 路由验证只读 prepare，不使用文件或 CAD 替身外的对象。"""
    document_path = tmp_path / "station-qualification.sldprt"
    graph.document.update(path=str(document_path), title=document_path.name)
    return cam.configure_turn_tool(object(), "clsid", "tlb",
        expected_document_path=str(document_path), setup_index=0, operation_index=0,
        expected_operation_type=2, action="prepare", field="NoseRadius",
        qualification_only=True, message_policy="vendor_default")


def test_empty_station_bstr_prepares_with_verified_shared_references(native_graph, tmp_path):
    g = native_graph
    g.station.GetStationId = ""
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "ok" and report["apply_eligible"] is True
    assert report["before"]["station_id"] == ""
    assert report["before"]["affected_operations"] == [ref(0), ref(1)]
    assert [item["tool_group"] for item in report["before"]["operation_tools"]] == [0, 0, 1]
    assert len(report["snapshot_diagnostics"]) == 1
    diagnostic = report["snapshot_diagnostics"][0]
    assert diagnostic["phase"] == "initial" and diagnostic["stage"] == "complete"
    assert diagnostic["station_id_raw"] == ""
    assert diagnostic["document"] == report["before"]["document"]
    assert diagnostic["inventory"] == report["before"]["inventory"]
    assert diagnostic["tool_groups"] == report["before"]["tool_groups"]
    assert diagnostic["linked_features"] == [{"name": "known profile"}]
    assert diagnostic["selected_tool"]["dimensions_native"] == {"NoseRadius": .8}
    assert not report["mutation_attempted"] and not report["may_continue"]
    assert g.inventory_reader.call_count == 2
    g.document_reader.assert_called_once()


@pytest.mark.parametrize("station_id", [None, 0, False])
def test_nonstring_station_id_blocks_with_raw_value_and_explicit_reason(native_graph, tmp_path, station_id):
    g = native_graph
    g.station.GetStationId = station_id
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error"
    assert report["reason"] == "CAM_TOOL_STATION_ID_TYPE_INVALID"
    assert report["failed_stage"] == "GetStationId"
    assert not report["mutation_attempted"] and not report["readback_verified"]
    diagnostic = report["snapshot_diagnostics"][0]
    assert diagnostic["phase"] == "initial" and diagnostic["stage"] == "GetStationId"
    assert "station_id_raw" in diagnostic and diagnostic["station_id_raw"] is station_id
    assert diagnostic["document"] == g.document and diagnostic["inventory"] == g.inventory
    assert len(diagnostic["tool_groups"]) == 2 and len(diagnostic["operation_tools"]) == 3
    g.profile_reader.assert_not_called()
    g.tool_reader.assert_not_called()
    assert g.inventory_reader.call_count == 1
    g.document_reader.assert_not_called()


def test_failure_after_station_keeps_initial_phase_identity_and_scanned_groups(native_graph, tmp_path):
    g = native_graph
    g.station.GetStationId = ""
    g.operations[0].IGetAllFeatures.side_effect = RuntimeError("SECRET native failure")
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error" and report["failed_stage"] == "IGetAllFeatures"
    assert not report["mutation_attempted"]
    diagnostic = report["snapshot_diagnostics"][0]
    assert diagnostic["phase"] == "initial" and diagnostic["stage"] == "IGetAllFeatures"
    assert diagnostic["station_id_raw"] == ""
    assert len(diagnostic["operation_tools"]) == 3
    assert len(diagnostic["tool_groups"]) == 2
    assert diagnostic["tool_groups"][0]["dimensions_native"]["NoseRadius"] == .8
    assert "SECRET" not in json.dumps(report)
    g.profile_reader.assert_not_called()
    g.tool_reader.assert_not_called()
    assert g.inventory_reader.call_count == 1
    g.document_reader.assert_not_called()


def test_profile_failure_preserves_already_read_profile_and_station_diagnostics(native_graph, tmp_path):
    g = native_graph
    def fail(raw, typelib_path, read, budget, partial):
        partial.update(name="partial native profile")
        read(SimpleNamespace(GetAttributeName=Mock(side_effect=RuntimeError("native failure"))), "GetAttributeName")
    g.profile_reader.side_effect = fail
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error" and report["failed_stage"] == "GetAttributeName"
    diagnostic = report["snapshot_diagnostics"][0]
    assert diagnostic["phase"] == "initial" and diagnostic["station_id_raw"] == "native-id"
    assert diagnostic["linked_features"] == [{"name": "partial native profile"}]
    assert len(diagnostic["tool_groups"]) == 2
    g.tool_reader.assert_not_called()
    assert g.inventory_reader.call_count == 1
    g.document_reader.assert_not_called()


def test_different_com_wrappers_share_verified_native_cam_tool_and_operation_ids(native_graph, tmp_path):
    g = native_graph
    second_tool = SimpleNamespace(**(vars(g.a) | {"identity": object()}))
    station_tool = SimpleNamespace(**(vars(g.a) | {"identity": object()}))
    roundtrip_tool = SimpleNamespace(**(vars(g.a) | {"identity": object()}))
    usage_aliases = [SimpleNamespace(native_id=op.native_id, identity=object()) for op in g.operations[:2]]
    g.operations[1].IGetTool.return_value = second_tool
    g.station.GetTool = station_tool
    g.station.GetStationId = ""
    g.station.OperationsUsingThisTool = usage_aliases
    g.native_doc.GetCWObjectFromID.return_value = (roundtrip_tool, True)
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "ok" and report["apply_eligible"] is True
    before = report["before"]
    assert before["affected_operations"] == [ref(0), ref(1)]
    assert [row["tool_native_id"] for row in before["operation_tools"]] == [101, 101, 202]
    assert [row["operation_native_id"] for row in before["operation_tools"]] == [1001, 1002, 1003]
    assert [row["cam_object_id"] for row in before["tool_groups"]] == [101, 202]
    assert before["station_tool_native_id"] == 101
    assert before["station_usage_operation_ids"] == [1001, 1002]
    assert before["native_id_scope"] == "current_CAM_document_snapshot_not_persistent_across_reopen"
    diagnostic = report["snapshot_diagnostics"][0]
    assert diagnostic["station_wrapper_equals_selected"] is False
    assert diagnostic["tool_roundtrip"] == {"object_type": 5, "requested_id": 101,
        "status": True, "returned_id": 101, "tool_type_raw": 15}
    assert all(row["returned"] and row["status"] is True and row["object_id"] > 0
               for row in diagnostic["native_id_reads"])
    g.native_doc.GetCWObjectFromID.assert_called_once_with(5, 101)
    assert not report["mutation_attempted"] and not report["may_continue"]


@pytest.mark.parametrize("value", [0, -1, 4294967296, True, 1., None, "1001"])
def test_native_id_requires_strict_positive_ulong_and_preserves_failed_read(native_graph, tmp_path, value):
    g = native_graph
    g.operations[0].native_id = value
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error" and report["reason"] == "CAM_OBJECT_ID_NOT_CONFIRMED"
    assert report["failed_stage"] == "GetCWObjectID"
    diagnostic = report["snapshot_diagnostics"][0]
    assert diagnostic["phase"] == "initial"
    assert len(diagnostic["native_id_reads"]) == 1
    entry = diagnostic["native_id_reads"][0]
    assert entry["label"] == "operation[0,0]" and entry["returned"] is True
    assert entry["status"] is True
    assert entry["object_id"] == (value if type(value) is int else {"unexpected_type": type(value).__name__})
    g.operations[0].IGetTool.assert_not_called()
    g.native_doc.GetCWObjectFromID.assert_not_called()
    g.profile_reader.assert_not_called()
    g.document_reader.assert_not_called()
    assert not report["mutation_attempted"]


@pytest.mark.parametrize("status", [False, 0, 1, None, "true"])
def test_native_id_status_must_be_actual_true_boolean(native_graph, tmp_path, status):
    g = native_graph
    g.native_doc.GetCWObjectID.side_effect = lambda obj: (obj.native_id, status)
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error" and report["reason"] == "CAM_OBJECT_ID_NOT_CONFIRMED"
    assert report["snapshot_diagnostics"][0]["native_id_reads"][0]["status"] == (
        status if type(status) is bool else {"unexpected_type": type(status).__name__})
    g.operations[0].IGetTool.assert_not_called()
    g.native_doc.GetCWObjectFromID.assert_not_called()
    assert not report["mutation_attempted"]


@pytest.mark.parametrize("returned", [None, True, (1001,), (1001, True, 7), {"object_id": 1001, "status": True}])
def test_native_id_out_shape_is_validated_before_use(native_graph, tmp_path, returned):
    g = native_graph
    g.native_doc.GetCWObjectID.side_effect = None
    g.native_doc.GetCWObjectID.return_value = returned
    report = _prepare_native_graph(g, tmp_path)
    assert report["reason"] == "CAM_OBJECT_ID_INVALID_SHAPE"
    assert report["snapshot_diagnostics"][0]["native_id_reads"] == [
        {"label": "operation[0,0]", "returned": True}]
    g.operations[0].IGetTool.assert_not_called()
    assert not report["mutation_attempted"]


def test_native_id_exception_stops_without_omitting_attempt_diagnostics(native_graph, tmp_path):
    g = native_graph
    g.native_doc.GetCWObjectID.side_effect = RuntimeError("SECRET native failure")
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error" and report["failed_stage"] == "GetCWObjectID"
    assert report["snapshot_diagnostics"][0]["native_id_reads"] == [
        {"label": "operation[0,0]", "returned": False}]
    assert "SECRET" not in json.dumps(report)
    g.operations[0].IGetTool.assert_not_called()
    g.document_reader.assert_not_called()


def test_duplicate_native_operation_id_blocks_even_with_distinct_com_wrappers(native_graph, tmp_path):
    g = native_graph
    g.operations[1].native_id = g.operations[0].native_id
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error" and report["reason"] == "CAM_OPERATION_ID_DUPLICATE"
    assert len(report["snapshot_diagnostics"][0]["operation_tools"]) == 1
    g.operations[1].IGetTool.assert_not_called()
    g.native_doc.GetCWObjectFromID.assert_not_called()


@pytest.mark.parametrize("status", [0, 1, None, "true"])
def test_tool_roundtrip_requires_strict_boolean_status(native_graph, tmp_path, status):
    g = native_graph
    g.native_doc.GetCWObjectFromID.return_value = (g.a, status)
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error" and report["reason"] == "CAM_TOOL_ID_ROUNDTRIP_INVALID"
    assert report["failed_stage"] == "GetCWObjectFromID"
    diagnostic = report["snapshot_diagnostics"][0]
    assert diagnostic["tool_roundtrip"]["requested_id"] == 101
    assert "returned_id" not in diagnostic["tool_roundtrip"]
    assert "station_usage_operation_ids" not in diagnostic
    g.profile_reader.assert_not_called()
    g.document_reader.assert_not_called()


@pytest.mark.parametrize("returned", [None, (None, True), (False, True), (True,), (None, True, 1)])
def test_tool_roundtrip_requires_pair_and_nonnull_dispatch(native_graph, tmp_path, returned):
    g = native_graph
    g.native_doc.GetCWObjectFromID.return_value = returned
    report = _prepare_native_graph(g, tmp_path)
    assert report["reason"] == "CAM_TOOL_ID_ROUNDTRIP_INVALID"
    assert not report["mutation_attempted"]
    g.profile_reader.assert_not_called()
    g.document_reader.assert_not_called()


@pytest.mark.parametrize("mismatch", ["id", "type"])
def test_tool_roundtrip_must_return_selected_native_id_and_turning_type(native_graph, tmp_path, mismatch):
    g = native_graph
    again = SimpleNamespace(native_id=999 if mismatch == "id" else 101,
                            ToolType=3 if mismatch == "type" else 15)
    g.native_doc.GetCWObjectFromID.return_value = (again, True)
    report = _prepare_native_graph(g, tmp_path)
    assert report["reason"] == "CAM_TOOL_ID_ROUNDTRIP_MISMATCH"
    assert report["snapshot_diagnostics"][0]["tool_roundtrip"]["returned_id"] == again.native_id
    assert not report["mutation_attempted"]
    g.profile_reader.assert_not_called()
    g.document_reader.assert_not_called()


def test_maximum_ulong_tool_id_is_valid(native_graph):
    g = native_graph
    g.a.native_id = 4294967295
    state, _ = g.run()
    assert state["station_tool_native_id"] == 4294967295
    g.native_doc.GetCWObjectFromID.assert_called_once_with(5, 4294967295)


def test_same_native_id_with_conflicting_wrapper_dimensions_blocks_change(native_graph, tmp_path):
    g = native_graph
    conflicting = SimpleNamespace(**(vars(g.a) | {"identity": object(), "NoseRadius": .7}))
    g.operations[1].IGetTool.return_value = conflicting
    report = _prepare_native_graph(g, tmp_path)
    assert report["status"] == "error" and report["reason"] == "CAM_TOOL_ID_ALIASES_DIFFER"
    assert "inconsistent_alias" in report["snapshot_diagnostics"][0]
    assert not report["mutation_attempted"] and not report["readback_verified"]
    g.native_doc.GetCWObjectFromID.assert_not_called()
    g.profile_reader.assert_not_called()
    g.document_reader.assert_not_called()


def test_false_reverse_lookup_is_diagnostic_but_positive_ids_and_full_usage_still_required(native_graph):
    g = native_graph
    sentinel = object()
    g.native_doc.GetCWObjectFromID.return_value = (sentinel, False)
    diagnostic = {}
    state, _native = cam._snapshot(object(), "clsid", "tlb", ref(0), diagnostics=diagnostic)
    assert state["affected_operations"] == [ref(0), ref(1)]
    assert state["station_tool_native_id"] == 101
    assert state["tool_roundtrip"] == {"object_type": 5, "requested_id": 101, "status": False,
        "available": False, "reason": "native_returned_false", "identity_proof_required": False}
    assert not any(entry["label"] == "tool_roundtrip" for entry in diagnostic["native_id_reads"])
    assert len(state["station_usage_operation_ids"]) == 2
    assert all(entry["status"] is True and entry["object_id"] > 0 for entry in diagnostic["native_id_reads"])


def test_false_reverse_lookup_does_not_allow_missing_shared_usage(native_graph):
    g = native_graph
    g.native_doc.GetCWObjectFromID.return_value = (None, False)
    g.station.OperationsUsingThisTool = g.operations[:1]
    with pytest.raises(cam.CamToolStateError) as error:
        g.run()
    assert error.value.reason == "CAM_TOOL_SHARED_USAGE_MISMATCH"


def test_native_propget_collection_is_not_invoked_as_default_item(native_graph, monkeypatch):
    from ctypes import POINTER, HRESULT, c_int
    from comtypes import IUnknown, GUID, COMMETHOD, dispid
    class ICallableCollectionFixture(IUnknown):
        _iid_ = GUID("{61B9118B-1A0E-4E8F-B008-7467CF679193}")
        _methods_ = [COMMETHOD([dispid(0)], HRESULT, "Item",
            (["in"], c_int, "index"), (["out", "retval"], POINTER(c_int), "value"))]
    collection_pointer = POINTER(ICallableCollectionFixture)()
    assert callable(collection_pointer) and isinstance(collection_pointer, IUnknown)
    reads = []
    g = native_graph
    class Station:
        GetStationId = "native-id"
        GetTool = g.a
        @property
        def OperationsUsingThisTool(self):
            reads.append("propget")
            return collection_pointer
    g.a.GetToolStation = Station()
    original_collection = cam._collection
    def collection(raw, path):
        if raw is collection_pointer:
            return g.operations[:2]
        return original_collection(raw, path)
    monkeypatch.setattr(cam, "_collection", collection)
    state, _native = g.run()
    assert state["affected_operations"] == [ref(0), ref(1)]
    assert reads == ["propget"]


@pytest.mark.parametrize("subtype",[0,2,3,99])
def test_mixed_turn_drill_scan_never_reads_insert_or_thickness(native_graph,subtype):
    g=native_graph
    g.b.turn_subtype=subtype
    g.b.InsertType=Mock(side_effect=AssertionError("No insert getter on unsupported subtype"))
    g.b.Thickness=Mock(side_effect=AssertionError("No drill Thickness"))
    state,_=g.run()
    assert state["tool_groups"][1]["dimensions_native"]=={}
    assert state["tool_groups"][1]["turn_tool_type_raw"]==subtype
    g.b.InsertType.assert_not_called();g.b.Thickness.assert_not_called()
    assert state["affected_operations"]==[ref(0),ref(1)]


def test_selected_drill_subtype_blocks_before_station_or_profile(native_graph):
    g=native_graph;g.a.turn_subtype=2
    g.a.InsertType=Mock(side_effect=AssertionError("No insert getter"))
    with pytest.raises(ValueError,match="selected tool must"):g.run()
    g.a.InsertType.assert_not_called();g.profile_reader.assert_not_called();g.tool_reader.assert_not_called()
