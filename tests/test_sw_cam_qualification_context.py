"""资格上下文只读回归；模拟原生图与真实 ctypes 指针，不连接 CAD。"""
from copy import deepcopy
from ctypes import CFUNCTYPE, POINTER, c_int, py_object
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_operation_profile as profiles
from scripts import sw_cam_qualification_context as cam

TLB = "verified/camworks.tlb"


@pytest.fixture
def graph(monkeypatch, tmp_path):
    document = {"path": str(tmp_path / "sample.sldprt"), "title": "sample.sldprt",
                "type": 1, "needs_save": False}
    inventory = {"operations": [{"setup_index": 0, "operation_index": 0,
        "turn_operation_type": 2, "toolpath_generated": False}], "operation_count": 1}
    bindings = {}
    def bind(raw, name, obj):
        bindings[id(raw), name] = obj
        return obj
    def typed(raw, name, path):
        assert path == TLB
        return bindings[id(raw), name]
    def collection(raw, path):
        assert path == TLB and isinstance(raw, list)
        return raw
    raw_operation, raw_setup, raw_tool, raw_holder = [object() for _ in range(4)]
    raw_features = [object(), object()]
    features = [bind(raw, "ICWTurnFeature", SimpleNamespace(
        IGetAllDefaultOperations=Mock(return_value=("Exact Thread; A", " Thread B ")),
        GetTdbIdForDefaultOperation=Mock(side_effect=[0, 27]))) for raw in raw_features]
    forbidden = [Mock(side_effect=AssertionError("No native mutation")) for _ in range(5)]
    operation = bind(raw_operation, "ICWOperation", SimpleNamespace(
        IGetAllFeatures=Mock(return_value=raw_features), IGetTool=Mock(return_value=raw_tool),
        GenerateToolpath=forbidden[0], AddFeature=forbidden[1]))
    turning = bind(raw_operation, "ICWTurnOperation", SimpleNamespace(
        OpernType=Mock(return_value=2), SetTool=forbidden[2]))
    tool = bind(raw_tool, "ICWTool", SimpleNamespace(ToolType=Mock(return_value=15)))
    turn_tool = bind(raw_tool, "ICWTurnTool", SimpleNamespace(
        IGetTurnToolHolder=Mock(return_value=raw_holder)))
    positions, raw_positions = [], []
    for coordinates in [(1., 2., 3.), (4., 5., 6.), (7., 8., 9.), (10., 11., 12.)]:
        raw = object()
        raw_positions.append(raw)
        positions.append(bind(raw, "ICWPosition", SimpleNamespace(GetCoordinates=Mock(return_value=coordinates))))
    raw_curves = [object(), object()]
    curves = [bind(raw, "ICWCurve", SimpleNamespace(GetTypeOfCurve=Mock(return_value=kind),
        GetStart=Mock(return_value=raw_positions[0]), GetEnd=Mock(return_value=raw_positions[1]),
        GetMid=Mock(return_value=raw_positions[2]))) for raw, kind in zip(raw_curves, [0, 1])]
    arc = bind(raw_curves[1], "ICWArc", SimpleNamespace(
        CenterPoint=Mock(return_value=raw_positions[3]), IGetRadius=Mock(return_value=2.5),
        IGetSense=Mock(return_value=-1)))
    indexes = []
    def at_index(pointer):
        indexes.append(pointer.contents.value)
        return raw_curves[pointer.contents.value]
    # 真实 C ABI 强制接收 INT*；直接传 Python int 将被 ctypes 拒绝。
    native_at_index = CFUNCTYPE(py_object, POINTER(c_int))(at_index)
    raw_chain = object()
    chain = bind(raw_chain, "ICWSegChain", SimpleNamespace(
        IGetNumChains=Mock(return_value=1), GetNumOfCurves=Mock(return_value=2),
        GetCurveAtIndex=native_at_index, IGetNextChain=Mock(return_value=None)))
    holder = bind(raw_holder, "ICWTurnToolHolder", SimpleNamespace(
        GetHolderProfile=Mock(return_value=raw_chain),
        GetHolderProfileInDownLeftOrientation=Mock(return_value=raw_chain), CreateSTL=forbidden[3]))
    setup = bind(raw_setup, "ICWBaseOpSetup", SimpleNamespace(IGetEnumOperations=Mock(return_value=[raw_operation])))
    machine = SimpleNamespace(IGetEnumOpSetups=Mock(return_value=[raw_setup]))
    sw = SimpleNamespace(Save=forbidden[4])
    context = Mock(return_value=(deepcopy(document), object(), object(), machine, object()))
    inventories = Mock(side_effect=lambda *_: deepcopy(inventory))
    snapshots = Mock(side_effect=lambda *_: deepcopy(document))
    reader = Mock(wraps=cam._member)
    def profile(raw, path, read, budget, result):
        assert path == TLB
        budget[0] += 1
        result.update(native_feature_index=raw_features.index(raw), segments=[])
    profile_reader = Mock(side_effect=profile)
    tool_reader = Mock(side_effect=lambda raw, op, path, read, result: result.update(present=True))
    monkeypatch.setattr(cam, "_context", context)
    monkeypatch.setattr(cam, "_inventory", inventories)
    monkeypatch.setattr(cam, "document_snapshot", snapshots)
    monkeypatch.setattr(cam, "_member", reader)
    monkeypatch.setattr(cam, "_typed", typed)
    monkeypatch.setattr(profiles, "_typed", typed)
    monkeypatch.setattr(cam, "_collection", collection)
    monkeypatch.setattr(cam, "_read_profile", profile_reader)
    monkeypatch.setattr(cam, "_read_tool", tool_reader)
    def run(**changes):
        options = dict(expected_document_path=document["path"], setup_index=0, operation_index=0,
            expected_operation_type=2, linked_feature_indices=[1], holder_profile="operation")
        return cam.inspect_qualification_context(sw, "clsid", TLB, **(options | changes))
    return SimpleNamespace(**locals())


def assert_no_writes(graph, result):
    for key in ("mutation_attempted", "generation_attempted", "model_saved", "may_continue",
                "thread_inserted", "thread_process_qualified", "holder_fit_verified",
                "units_verified", "coordinate_frame_verified"):
        assert result[key] is False
    for writer in graph.forbidden:
        writer.assert_not_called()


def test_selected_catalog_then_actual_holder_geometry_uses_native_pointer_abi(graph):
    result = graph.run()
    assert result["status"] == "ok"
    assert result["inventory_unchanged"] and result["active_document_unchanged"]
    assert result["inventory_before"] == result["inventory_after"] == graph.inventory
    selected = result["thread_catalogs"][0]
    assert selected["linked_feature_index"] == selected["profile"]["native_feature_index"] == 1
    assert [entry["name"] for entry in selected["catalog"]["entries"]] == ["Exact Thread; A", " Thread B "]
    assert [entry["tdb_id_raw"] for entry in selected["catalog"]["entries"]] == [0, 27]
    assert all(entry["id_validity_assumed"] is False for entry in selected["catalog"]["entries"])
    graph.features[0].IGetAllDefaultOperations.assert_not_called()
    graph.features[1].IGetAllDefaultOperations.assert_called_once_with(12)
    assert graph.features[1].GetTdbIdForDefaultOperation.call_args_list[0].args == (12, "Exact Thread; A")
    assert graph.indexes == [0, 1]
    calls = [call.args[1] for call in graph.reader.call_args_list]
    assert calls.index("GetTdbIdForDefaultOperation") < calls.index("GetHolderProfile")
    holder = result["holder_profile"]
    assert holder["curve_count"] == 2 and holder["parameters_complete"]
    line, arc = holder["chains"][0]["curves"]
    assert line["start_native"] == [1., 2., 3.] and line["end_native"] == [4., 5., 6.]
    assert arc["mid_native"] == [7., 8., 9.] and arc["centre_native"] == [10., 11., 12.]
    assert arc["radius_native"] == 2.5 and arc["sense_raw"] == -1
    assert not arc["sense_semantics_verified"]
    assert not holder["coordinate_frame_verified"] and not holder["units_verified"]
    graph.holder.GetHolderProfile.assert_called_once_with(graph.operation)
    graph.holder.GetHolderProfileInDownLeftOrientation.assert_not_called()
    graph.chain.IGetNextChain.assert_not_called()
    assert graph.inventories.call_count == 2
    graph.snapshots.assert_called_once_with(graph.sw)
    assert_no_writes(graph, result)


def test_down_left_is_explicit_native_route(graph):
    result = graph.run(holder_profile="down_left")
    assert result["status"] == "ok"
    graph.holder.GetHolderProfileInDownLeftOrientation.assert_called_once_with(graph.operation)
    graph.holder.GetHolderProfile.assert_not_called()
    assert_no_writes(graph, result)


def test_none_never_reads_tool_or_holder(graph):
    result = graph.run(holder_profile="none")
    assert result["status"] == "ok" and result["holder_profile"]["reason"] == "not_requested"
    graph.operation.IGetTool.assert_not_called()
    graph.tool_reader.assert_not_called()
    assert_no_writes(graph, result)


@pytest.mark.parametrize("name,value", [
    ("setup_index", True), ("setup_index", -1), ("operation_index", False),
    ("operation_index", 512), ("expected_operation_type", True), ("expected_operation_type", 0),
    ("expected_operation_type", 17), ("linked_feature_indices", []),
    ("linked_feature_indices", (0,)), ("linked_feature_indices", [True]),
    ("linked_feature_indices", [0, 0]), ("linked_feature_indices", [64]),
    ("linked_feature_indices", [0.]), ("holder_profile", "auto"), ("holder_profile", None)])
def test_invalid_selection_fails_before_context(graph, name, value):
    result = graph.run(**{name: value})
    assert result["status"] == "error" and result["failed_stage"] == "validate_inputs"
    graph.context.assert_not_called()
    graph.reader.assert_not_called()
    assert_no_writes(graph, result)


@pytest.mark.parametrize("change", [dict(expected_document_path="different.sldprt"),
    dict(expected_operation_type=3), dict(linked_feature_indices=[2])])
def test_document_operation_or_feature_guard_blocks_catalog_and_holder(graph, change):
    result = graph.run(**change)
    assert result["status"] == "error"
    graph.features[1].IGetAllDefaultOperations.assert_not_called()
    graph.operation.IGetTool.assert_not_called()
    graph.snapshots.assert_not_called()


@pytest.mark.parametrize("raw", [None, 3, True, ["a", 5], [["nested"]], [""], ["x" * 1001], ["a"] * 65])
def test_unqualified_catalog_shape_is_preserved_without_lookup(raw):
    feature = SimpleNamespace(IGetAllDefaultOperations=Mock(return_value=raw),
        GetTdbIdForDefaultOperation=Mock(side_effect=AssertionError("No guessed name")))
    result = {}
    cam._catalog(feature, cam._member, result, [0])
    assert result["names_resolved"] is False and result["entries"] == []
    assert result["native_variant_metadata_preserved"] is False
    assert result["converted_result_shape"]["python_type"] == type(raw).__name__
    feature.GetTdbIdForDefaultOperation.assert_not_called()
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("raw", ["name;not,a split", ["name;not,a split"], ("name;not,a split",)])
def test_catalog_preserves_exact_bstr_name_and_raw_zero_id(raw):
    feature = SimpleNamespace(IGetAllDefaultOperations=Mock(return_value=raw),
        GetTdbIdForDefaultOperation=Mock(return_value=0))
    result = {}
    cam._catalog(feature, cam._member, result, [0])
    assert result["names_resolved"]
    feature.GetTdbIdForDefaultOperation.assert_called_once_with(12, "name;not,a split")
    assert result["entries"] == [{"name": "name;not,a split", "lookup_attempted": True,
        "tdb_id_raw": 0, "id_validity_assumed": False}]


def test_name_budget_is_shared_between_features():
    feature = SimpleNamespace(IGetAllDefaultOperations=Mock(return_value=["one", "two"]),
        GetTdbIdForDefaultOperation=Mock())
    result = {}
    cam._catalog(feature, cam._member, result, [63])
    assert not result["names_resolved"]
    feature.GetTdbIdForDefaultOperation.assert_not_called()


def test_catalog_converted_shape_is_bounded_and_preserves_nested_values():
    result = cam._converted_shape(("x", [None, True, 7, float("nan")]))
    assert result["python_type"] == "tuple"
    assert result["items"][1]["items"] == [{"python_type": "NoneType", "value": None},
        {"python_type": "bool", "value": True}, {"python_type": "int", "value": 7},
        {"python_type": "float", "value": "non_finite"}]
    assert cam._converted_shape([0] * 100)["truncated"]
    assert len(cam._converted_shape([0] * 100)["items"]) == 64
    assert cam._converted_shape(object())["unsupported_type"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("stage", ["GetTdbIdForDefaultOperation", "GetHolderProfile", "GetEnd", "IGetRadius"])
def test_first_native_exception_preserves_partial_data_and_stops_all_readback(graph, stage):
    getter = {"GetTdbIdForDefaultOperation": graph.features[1].GetTdbIdForDefaultOperation,
              "GetHolderProfile": graph.holder.GetHolderProfile,
              "GetEnd": graph.curves[0].GetEnd, "IGetRadius": graph.arc.IGetRadius}[stage]
    getter.side_effect = RuntimeError("private native details")
    result = graph.run()
    assert result["status"] == "error" and result["failed_stage"] == stage
    assert graph.reader.call_args.args[1] == stage
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()
    assert result["thread_catalogs"][0]["profile"]["native_feature_index"] == 1
    if stage == "GetTdbIdForDefaultOperation":
        graph.operation.IGetTool.assert_not_called()
        assert result["thread_catalogs"][0]["catalog"]["entries"][0]["lookup_attempted"]
    elif stage == "GetEnd":
        assert result["holder_profile"]["chains"][0]["curves"][0]["start_native"] == [1., 2., 3.]
    elif stage == "IGetRadius":
        arc = result["holder_profile"]["chains"][0]["curves"][1]
        assert arc["centre_native"] == [10., 11., 12.] and "radius_native" not in arc
        graph.arc.IGetSense.assert_not_called()
    assert "private native details" not in json.dumps(result)
    assert_no_writes(graph, result)


@pytest.mark.parametrize("raw_id", [True, "5", 5., None])
def test_catalog_id_requires_actual_integer_without_coercion(graph, raw_id):
    graph.features[1].GetTdbIdForDefaultOperation.side_effect = None
    graph.features[1].GetTdbIdForDefaultOperation.return_value = raw_id
    result = graph.run()
    assert result["status"] == "error"
    graph.operation.IGetTool.assert_not_called()
    graph.snapshots.assert_not_called()


@pytest.mark.parametrize("count", [-1, 33, True])
def test_chain_bound_checked_before_curve_access(graph, count):
    graph.chain.IGetNumChains.return_value = count
    result = graph.run()
    assert result["status"] == "error"
    graph.chain.GetNumOfCurves.assert_not_called()
    assert not graph.indexes and graph.inventories.call_count == 1


@pytest.mark.parametrize("count", [-1, 513, True])
def test_curve_bound_checked_before_curve_access(graph, count):
    graph.chain.GetNumOfCurves.return_value = count
    result = graph.run()
    assert result["status"] == "error" and not graph.indexes
    graph.snapshots.assert_not_called()


def test_declared_next_chain_missing_fails_without_readback(graph):
    graph.chain.IGetNumChains.return_value = 2
    result = graph.run()
    assert result["status"] == "error" and result["failed_stage"] == "IGetNextChain"
    assert len(result["holder_profile"]["chains"][0]["curves"]) == 2
    graph.snapshots.assert_not_called()


@pytest.mark.parametrize("missing", ["holder", "profile"])
def test_native_null_geometry_requires_review_without_export_fallback(graph, missing):
    if missing == "holder": graph.turn_tool.IGetTurnToolHolder.return_value = None
    else: graph.holder.GetHolderProfile.return_value = None
    result = graph.run()
    assert result["status"] == "review_required"
    assert result["holder_profile"]["available"] is False
    assert_no_writes(graph, result)


def test_unknown_curve_preserves_endpoints_without_arc_or_tessellation_guess(graph):
    graph.curves[1].GetTypeOfCurve.return_value = 3
    result = graph.run()
    assert result["status"] == "review_required"
    curve = result["holder_profile"]["chains"][0]["curves"][1]
    assert curve["start_native"] == [1., 2., 3.] and not curve["parameters_complete"]
    graph.arc.CenterPoint.assert_not_called()
    graph.curves[1].GetMid.assert_not_called()


@pytest.mark.parametrize("changed", ["inventory", "document"])
def test_changed_state_requires_review_and_never_allows_continuation(graph, changed):
    if changed == "inventory":
        after = deepcopy(graph.inventory)
        after["operation_count"] = 2
        graph.inventories.side_effect = [deepcopy(graph.inventory), after]
    else:
        after = deepcopy(graph.document)
        after["needs_save"] = True
        graph.snapshots.side_effect = None
        graph.snapshots.return_value = after
    result = graph.run()
    assert result["status"] == "review_required"
    assert result["reason"] == "CAM_STATE_CHANGED_DURING_CONTEXT_INSPECTION"
    assert result["inventory_unchanged" if changed == "inventory" else "active_document_unchanged"] is False
    assert_no_writes(graph, result)


def test_requested_feature_order_is_preserved(graph):
    result = graph.run(linked_feature_indices=[1, 0], holder_profile="none")
    assert result["status"] == "ok"
    assert [row["linked_feature_index"] for row in result["thread_catalogs"]] == [1, 0]
    assert [call.args[0] for call in graph.profile_reader.call_args_list] == graph.raw_features[::-1]


def test_curve_budget_is_shared_across_chains(graph):
    second_raw = object()
    second = graph.bind(second_raw, "ICWSegChain", SimpleNamespace(
        GetNumOfCurves=Mock(return_value=511), GetCurveAtIndex=Mock(), IGetNextChain=Mock()))
    graph.chain.IGetNumChains.return_value = 2
    graph.chain.IGetNextChain.return_value = second_raw
    result = graph.run()
    assert result["status"] == "error" and graph.indexes == [0, 1]
    second.GetCurveAtIndex.assert_not_called()
    graph.snapshots.assert_not_called()


def test_profile_failure_keeps_partial_feature_before_catalog_or_holder(graph):
    def fail(raw, path, read, budget, result):
        result.update(name="partial feature", segments=[{"start_native": [1., 2., 3.]}])
        read(graph.positions[0], "GetCoordinates")
    graph.profile_reader.side_effect = fail
    graph.positions[0].GetCoordinates.side_effect = RuntimeError("native fault")
    result = graph.run()
    assert result["status"] == "error" and result["failed_stage"] == "GetCoordinates"
    assert result["thread_catalogs"][0]["profile"]["name"] == "partial feature"
    graph.features[1].IGetAllDefaultOperations.assert_not_called()
    graph.operation.IGetTool.assert_not_called()
    graph.snapshots.assert_not_called()


def test_holder_method_returns_real_callable_com_pointer_without_default_item_invoke(graph):
    from ctypes import HRESULT
    from comtypes import COMObject, COMMETHOD, GUID, IUnknown, dispid

    class ICallableHolderChain(IUnknown):
        _iid_ = GUID("{F05966A2-EC10-4836-8C8D-C11C57B35ED6}")
        _methods_ = [COMMETHOD([dispid(0)], HRESULT, "Item",
            (["in"], c_int, "index"), (["out", "retval"], POINTER(c_int), "value"))]

    invoked = []
    class Server(COMObject):
        _com_interfaces_ = [ICallableHolderChain]
        def Item(self, index):
            invoked.append(index)
            return 1

    owner = Server()
    pointer = owner.QueryInterface(ICallableHolderChain)
    assert callable(pointer) and bool(pointer) and isinstance(pointer, IUnknown)
    graph.bind(pointer, "ICWSegChain", graph.chain)
    graph.holder.GetHolderProfile.return_value = pointer
    result = graph.run()
    assert result["status"] == "ok"
    graph.holder.GetHolderProfile.assert_called_once_with(graph.operation)
    assert invoked == []
    assert result["holder_profile"]["curve_count"] == 2
    assert_no_writes(graph, result)


def test_unsupported_tool_reader_stops_holder_chain_with_review_status(graph):
    graph.tool_reader.side_effect=lambda raw,op,path,read,result:result.update(
        present=True,parameters_status="unavailable",reason="unsupported_turn_tool_type")
    graph.turn_tool.IGetTurnToolHolder.side_effect=AssertionError("No holder accessor after unsupported tool")
    result=graph.run()
    assert result["status"]=="review_required"
    assert result["holder_profile"]["reason"]=="unsupported_tool_parameters"
    assert result["inventory_unchanged"] and result["active_document_unchanged"]
    graph.turn_tool.IGetTurnToolHolder.assert_not_called()
    graph.holder.GetHolderProfile.assert_not_called()
