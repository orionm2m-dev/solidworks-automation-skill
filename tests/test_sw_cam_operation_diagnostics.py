"""单个 CAM 操作的只读诊断回归；全部接口均为受限模拟对象。"""
from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_generation as generation

CLSID = "{00000000-0000-0000-0000-000000000001}"
TLB = "verified/camworks.tlb"


@pytest.fixture
def graph(monkeypatch):
    """建立多 setup 的选择图，未选择操作没有可读取的诊断接口。"""
    snapshot = {"path": r"C:\qualification\part.sldprt", "title": "part.sldprt",
                "type": 1, "needs_save": False}
    rows = [
        {"setup_index": 0, "operation_index": 0, "turn_operation_type": 1,
         "toolpath_generated": False, "toolpath_record_counts": []},
        {"setup_index": 1, "operation_index": 0, "turn_operation_type": 2,
         "toolpath_generated": False, "toolpath_record_counts": []},
        {"setup_index": 1, "operation_index": 1, "turn_operation_type": 3,
         "toolpath_generated": True, "toolpath_record_counts": [7]},
    ]
    initial = {"machine_type": 3, "feature_setup_count": 2, "feature_counts_by_setup": [2, 2],
               "feature_count": 4, "operation_setup_count": 2, "operation_count": 3,
               "operations": rows, "stock": {"type": 3, "parameters_modified": False,
                                              "length_units": "native_API_units_not_assumed"}}
    state = {"document": snapshot, "inventory": initial, "typed_failures": set()}
    forbidden = [Mock(side_effect=AssertionError("diagnostics must not mutate")) for _ in range(6)]
    doc = SimpleNamespace(ExtractMachinableFeatures=forbidden[0], Save=forbidden[1])
    app = SimpleNamespace(ActiveDocGOP=forbidden[2], ActiveDocGTP=forbidden[3])
    operation = SimpleNamespace(TimeTakenForGTP=Mock(return_value="00:00:02"),
                                ToolpathFeedLength=Mock(return_value=42.5),
                                GetIsToolpathGenerated=Mock(return_value=True),
                                GenerateToolpath=forbidden[4], PostProcess=forbidden[5])
    turn = SimpleNamespace(OpernType=Mock(return_value=3))
    licensed = SimpleNamespace(GetIsLicensed=Mock(return_value=True))
    stock = SimpleNamespace(GetBarStockParameters=Mock(return_value=(1.5, 40.0, 2.0, 0.0, 3)),
                            GetTurnWorkpieceType=Mock(side_effect=lambda: state["inventory"]["stock"]["type"]))
    raw_selected, raw_other0, raw_other1, raw_stock = object(), object(), object(), object()

    def collection(items):
        return SimpleNamespace(Count=len(items), Item=Mock(side_effect=items.__getitem__))

    setup0 = SimpleNamespace(IGetEnumOperations=Mock(return_value=collection([raw_other0])))
    setup1 = SimpleNamespace(IGetEnumOperations=Mock(return_value=collection([raw_other1, raw_selected])))
    machine = SimpleNamespace(IGetEnumOpSetups=Mock(return_value=collection([setup0, setup1])),
                              IGetWorkpiece=Mock(return_value=raw_stock))
    sw = object()
    context = Mock(side_effect=lambda *_: (deepcopy(state["document"]), doc, object(), machine, app))
    inventories = Mock(side_effect=lambda *_: deepcopy(state["inventory"]))
    document = Mock(side_effect=lambda _: deepcopy(state["document"]))

    def typed(obj, name, path):
        assert path == TLB
        if name in state["typed_failures"]:
            raise RuntimeError("SECRET diagnostics COM error")
        if name == "ICWDispatchCollection":
            assert hasattr(obj, "Count") and hasattr(obj, "Item")
            return obj
        if name == "ICWBaseOpSetup":
            assert obj is setup0 or obj is setup1
            return obj
        if name == "ICWTurnWorkpiece":
            assert obj is raw_stock
            return stock
        assert obj is raw_selected, "Diagnostics must target only the selected raw operation"
        return {"ICWOperation": operation, "ICWTurnOperation": turn, "ICWObject": licensed}[name]

    typed_mock = Mock(side_effect=typed)
    monkeypatch.setattr(generation, "_context", context)
    monkeypatch.setattr(generation, "_inventory", inventories)
    monkeypatch.setattr(generation, "_typed", typed_mock)
    monkeypatch.setattr(generation, "document_snapshot", document)

    def run(setup_index=1, operation_index=1):
        return generation.inspect_operation(sw, CLSID, TLB,
                                            setup_index=setup_index, operation_index=operation_index)

    return SimpleNamespace(state=state, sw=sw, machine=machine, operation=operation,
                           turn=turn, licensed=licensed, stock=stock, forbidden=forbidden,
                           context=context, inventories=inventories, document=document,
                           typed=typed_mock, raw_selected=raw_selected, run=run)


def assert_read_only(f, report):
    """诊断报告不得声称执行、保存或已知原生执行状态。"""
    assert report["mutation_attempted"] is False
    assert report["generation_attempted"] is False
    assert report["model_saved"] is False
    assert report["native_execution_state"] == "unknown"
    for writer in f.forbidden:
        writer.assert_not_called()


def test_selected_operation_uses_exact_typed_interfaces_and_preserves_inventory(graph):
    f = graph
    before = deepcopy(f.state)
    report = f.run()
    assert report["status"] == "ok"
    assert report["inventory"] == before["inventory"]
    assert report["inventory_after"] == before["inventory"]
    assert report["inventory_unchanged"] is True
    assert report["active_document_unchanged"] is True
    assert report["selected_operation_unchanged"] is True
    assert report["diagnostics_complete"] is True
    assert f.state == before
    selected = report["selected_operation"]
    assert (selected["setup_index"], selected["operation_index"]) == (1, 1)
    assert selected["time_taken_for_gtp_raw"] == "00:00:02"
    assert selected["time_taken_for_gtp_available"] is True
    assert selected["time_taken_for_gtp_truncated"] is False
    assert selected["feed_length_native_units"] == 42.5
    assert selected["feed_length_available"] is True
    assert selected["length_units_verified"] is False
    assert selected["object_license"] == {
        "available": True, "is_licensed": True, "scope": "unknown", "source": "ICWObject.GetIsLicensed",
    }
    assert report["stock"]["bar_parameters_available"] is True
    assert report["stock"]["bar_parameters"] == {
        "startZ": 1.5, "length": 40.0, "odOff": 2.0, "idOff": 0.0, "eCWTurnWpAttribute": 3,
    }
    for name in ("ICWOperation", "ICWTurnOperation", "ICWObject"):
        assert any(call.args == (f.raw_selected, name, TLB) for call in f.typed.call_args_list)
    assert f.inventories.call_count == 2
    assert_read_only(f, report)


@pytest.mark.parametrize("field", ["setup_index", "operation_index"])
@pytest.mark.parametrize("value", [True, "1", 1.0, -1, 512, None])
def test_indices_are_strict_and_checked_before_context(graph, field, value):
    report = graph.run(**{field: value})
    assert report["status"] == "error"
    graph.context.assert_not_called()
    graph.typed.assert_not_called()
    for writer in graph.forbidden:
        writer.assert_not_called()


@pytest.mark.parametrize("setup,operation", [(2, 0), (0, 1), (1, 2)])
def test_out_of_range_selection_never_reads_another_operation(graph, setup, operation):
    report = graph.run(setup_index=setup, operation_index=operation)
    assert report["status"] == "error"
    graph.operation.TimeTakenForGTP.assert_not_called()
    graph.licensed.GetIsLicensed.assert_not_called()
    for writer in graph.forbidden:
        writer.assert_not_called()


@pytest.mark.parametrize("getter,flag", [
    ("time", "time_taken_for_gtp_available"), ("feed", "feed_length_available"),
    ("license", "license"), ("stock", "stock"),
])
def test_optional_getter_failure_preserves_both_inventories(graph, getter, flag):
    f = graph
    method = {"time": f.operation.TimeTakenForGTP, "feed": f.operation.ToolpathFeedLength,
              "license": f.licensed.GetIsLicensed, "stock": f.stock.GetBarStockParameters}[getter]
    method.side_effect = RuntimeError("SECRET diagnostics COM error")
    before = deepcopy(f.state["inventory"])
    report = f.run()
    assert report["status"] == "ok"
    assert report["inventory"] == report["inventory_after"] == before
    assert report["diagnostics_complete"] is False
    assert report["diagnostics"]
    assert all("field" in item and "issue" in item for item in report["diagnostics"])
    assert "SECRET" not in json.dumps(report)
    if flag == "license":
        assert report["selected_operation"]["object_license"]["available"] is False
        assert report["selected_operation"]["object_license"]["is_licensed"] is None
    elif flag == "stock":
        assert report["stock"]["bar_parameters_available"] is False
        assert report["stock"]["bar_parameters"] is None
    else:
        assert report["selected_operation"][flag] is False
    assert_read_only(f, report)


def test_optional_license_interface_failure_does_not_discard_other_diagnostics(graph):
    graph.state["typed_failures"].add("ICWObject")
    report = graph.run()
    assert report["status"] == "ok"
    assert report["diagnostics_complete"] is False
    assert report["selected_operation"]["object_license"]["available"] is False
    assert report["selected_operation"]["time_taken_for_gtp_available"] is True
    assert report["selected_operation"]["feed_length_available"] is True
    assert report["stock"]["bar_parameters_available"] is True
    assert_read_only(graph, report)


@pytest.mark.parametrize("interface", ["ICWOperation", "ICWTurnOperation"])
def test_required_operation_interface_failure_is_error(graph, interface):
    graph.state["typed_failures"].add(interface)
    report = graph.run()
    assert report["status"] == "error"
    assert "SECRET" not in json.dumps(report)
    for writer in graph.forbidden:
        writer.assert_not_called()


@pytest.mark.parametrize("stock_type", [0, 1, 2, 4, 5])
def test_bar_parameters_not_requested_for_other_stock_types(graph, stock_type):
    graph.state["inventory"]["stock"]["type"] = stock_type
    report = graph.run()
    assert report["status"] == "ok"
    assert report["stock"]["type"] == stock_type
    assert report["stock"]["bar_parameters_available"] is False
    assert report["stock"]["bar_parameters"] is None
    graph.stock.GetBarStockParameters.assert_not_called()
    assert_read_only(graph, report)


def test_time_text_is_bounded_and_not_interpreted_as_progress(graph):
    graph.operation.TimeTakenForGTP.return_value = "x" * 1200
    report = graph.run()
    selected = report["selected_operation"]
    assert selected["time_taken_for_gtp_raw"] == "x" * 1000
    assert selected["time_taken_for_gtp_truncated"] is True
    assert selected["time_taken_for_gtp_available"] is True
    assert report["native_execution_state"] == "unknown"


@pytest.mark.parametrize("getter,value", [
    ("time", 12), ("feed", float("nan")), ("feed", float("inf")),
    ("stock", (0.0, float("nan"), 0.0, 0.0, 1)),
    ("stock", (0.0, 1.0)),
])
def test_optional_invalid_data_cannot_be_reported_as_available(graph, getter, value):
    method = {"time": graph.operation.TimeTakenForGTP, "feed": graph.operation.ToolpathFeedLength,
              "stock": graph.stock.GetBarStockParameters}[getter]
    method.return_value = value
    report = graph.run()
    assert report["status"] == "ok"
    assert report["diagnostics_complete"] is False
    assert report["diagnostics"]
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("change", ["path", "dirty", "missing"])
def test_final_document_change_is_reported(graph, change):
    after = deepcopy(graph.state["document"])
    if change == "path":
        after["path"] = r"C:\other\part.sldprt"
    elif change == "dirty":
        after["needs_save"] = True
    else:
        after = None
    graph.document.return_value = after
    graph.document.side_effect = None
    report = graph.run()
    assert report["status"] == "review_required"
    assert report["active_document_unchanged"] is False
    assert report["document_after"] == after
    assert_read_only(graph, report)


def test_inventory_change_between_reads_is_reported(graph):
    before = deepcopy(graph.state["inventory"])
    after = deepcopy(before)
    after["operations"][0]["toolpath_generated"] = True
    graph.inventories.side_effect = [before, after]
    report = graph.run()
    assert report["status"] == "review_required"
    assert report["inventory_unchanged"] is False
    assert report["inventory"] == before
    assert report["inventory_after"] == after
    assert_read_only(graph, report)


@pytest.mark.parametrize("change", ["type", "generated"])
def test_selected_operation_disagreement_with_inventory_requires_review(graph, change):
    if change == "type":
        graph.turn.OpernType.return_value = 4
    else:
        graph.operation.GetIsToolpathGenerated.return_value = False
    report = graph.run()
    assert report["status"] == "review_required"
    assert report["selected_operation_unchanged"] is False
    assert report["inventory_unchanged"] is True
    assert report["active_document_unchanged"] is True
    assert_read_only(graph, report)



def test_feed_length_is_not_requested_without_generated_toolpath(graph):
    graph.state["inventory"]["operations"][2].update(toolpath_generated=False, toolpath_record_counts=[])
    graph.operation.GetIsToolpathGenerated.return_value = False
    report = graph.run()
    assert report["status"] == "ok"
    assert report["selected_operation"]["feed_length_available"] is False
    assert report["selected_operation"]["feed_length_native_units"] is None
    graph.operation.ToolpathFeedLength.assert_not_called()
    assert report["native_execution_state"] == "unknown"
    assert_read_only(graph, report)
