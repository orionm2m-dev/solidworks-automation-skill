"""TURN drill profile coverage using portable fake COM objects only."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_sw_cam_operation_profile import graph, assert_read_only, TLB
from scripts import sw_cam_operation_profile as profile
from scripts import sw_cam_comtypes as bridge


@pytest.fixture
def drill_graph(graph):
    graph.turn_tool.ToolType.return_value = 2
    graph.turn_tool.InsertType.side_effect = AssertionError("Drill cannot read InsertType")
    graph.turn_tool.IGetTurnToolHolder.side_effect = AssertionError("Drill cannot read insert holder")
    for method in graph.tool_fields.values():
        method.side_effect = AssertionError("Drill cannot read insert dimensions")
    values = {"ShankDia": 0.049, "TipAngle": 118., "TipLength": 0.014721,
              "EffectiveLength": 0.080, "TotalLength": 0.120, "ShoulderLength": 0.060}
    drill = SimpleNamespace(**{key: Mock(return_value=value) for key, value in values.items()},
                            NoOfFlutes=Mock(return_value=2))
    graph.bind(graph.raw_tool, "ICWDrillTool", drill)
    for name, value in {"CutDiameter": 0.049, "Protrusion": 0.070, "InEffectiveLength": 0.010}.items():
        setattr(graph.tool, name, Mock(return_value=value))
    graph.drill = drill
    graph.turning.OpernType.return_value = 9
    graph.inventory["operations"][2]["turn_operation_type"] = 9
    graph.drill_operation = graph.bind(graph.raw_operation, "ICWTurnDrillOp", SimpleNamespace(
        DrillCycleType=Mock(return_value=2), GenerateLeftOver=Mock(return_value=False),
        LEFTOVER_TYPE=Mock(return_value=0)))
    return graph


def run(graph, **changes):
    return graph.run(expected_operation_type=9, **changes)


def forbid_insert_chain(graph):
    graph.turn_tool.InsertType.assert_not_called()
    graph.turn_tool.IGetTurnToolHolder.assert_not_called()
    for method in graph.tool_fields.values(): method.assert_not_called()
    for method in graph.holder_fields.values(): method.assert_not_called()
    assert not any(call.args[1] == "ICWTurnToolHolder" for call in graph.typed_mock.call_args_list)


def test_drill_reports_observed_unsupported_without_geometry_qi(drill_graph):
    g = drill_graph
    result = run(g)
    assert result["status"] == "review_required"
    assert result["reason"] == "CAM_TOOL_PARAMETERS_UNAVAILABLE"
    tool = result["tool"]
    assert tool["tool_kind"] == "turn_drill"
    assert tool["parameters_status"] == "unavailable"
    assert tool["reason"] == "turn_drill_geometry_interface_observed_unsupported"
    assert tool["unsupported_interface"] == "ICWDrillTool"
    assert tool["observed_hresult"] == -2147467262
    assert tool["interface_probe_attempted"] is False
    assert tool["dimensions_native"] == {}
    assert "flute_count" not in tool and "insert_type_raw" not in tool
    assert tool["holder"]["available"] is False and tool["holder"]["requested"] is False
    assert result["inventory_before"] == result["inventory_after"]
    assert result["document_before"] == result["document_after"]
    assert "operation_parameters" not in result
    g.drill_operation.DrillCycleType.assert_not_called()
    assert not any(call.args[1] == "ICWDrillTool" for call in g.typed_mock.call_args_list)
    for name in ("CutDiameter", "Protrusion", "InEffectiveLength"):
        getattr(g.tool, name).assert_not_called()
    for method in vars(g.drill).values(): method.assert_not_called()
    forbid_insert_chain(g)
    assert_read_only(g, result)


def test_optional_operation_fields_are_honest_about_missing_depth(drill_graph):
    g = drill_graph
    result = run(g, include_operation_parameters=True)
    assert result["status"] == "review_required"
    data = result["operation_parameters"]
    assert data["fields_native"] == {"DrillCycleType": 2, "GenerateLeftOver": False, "LEFTOVER_TYPE": 0}
    assert data["read_complete"] is True and data["machining_depth_available"] is False
    assert data["enum_semantics_verified"] is False
    assert set(data["unavailable_fields"]) == {"machining_depth", "entry_plane", "tip_overtravel", "through", "retract_plane", "retract_amount"}
    assert not any(call.args[1] == "ICWTurnCenterDrillOp" for call in g.typed_mock.call_args_list)
    assert_read_only(g, result)


def test_skip_tool_still_permits_explicit_operation_getters(drill_graph):
    g = drill_graph
    result = run(g, include_tool=False, include_operation_parameters=True)
    assert result["status"] == "ok" and result["operation_parameters"]["read_complete"]
    g.operation.IGetTool.assert_not_called()
    assert not any(call.args[1] == "ICWDrillTool" for call in g.typed_mock.call_args_list)


def test_shared_helper_default_does_not_expand_other_holder_readers(drill_graph):
    g = drill_graph
    result = profile._read_tool(g.raw_tool, g.operation, TLB, profile._member)
    assert result["parameters_status"] == "unavailable"
    assert result["reason"] == "unsupported_turn_tool_type"
    assert not any(call.args[1] == "ICWDrillTool" for call in g.typed_mock.call_args_list)
    forbid_insert_chain(g)


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_operation_flag_strict_before_context(graph, value):
    result = graph.run(include_operation_parameters=value)
    assert result["status"] == "error"
    graph.context.assert_not_called()


def test_operation_parameters_reject_other_turn_types_before_context(graph):
    assert graph.run(include_operation_parameters=True)["status"] == "error"
    graph.context.assert_not_called()






def test_unsupported_drill_interface_is_not_retried_on_repeated_inspection(drill_graph):
    g = drill_graph
    del g.interfaces[id(g.raw_tool), "ICWDrillTool"]
    for _ in range(2):
        result = run(g)
        assert result["status"] == "review_required"
        assert result["tool"]["parameters_status"] == "unavailable"
    assert not any(call.args[1] == "ICWDrillTool" for call in g.typed_mock.call_args_list)
    g.tool.CutDiameter.assert_not_called()
    forbid_insert_chain(g)


@pytest.mark.parametrize("field,value", [("DrillCycleType", True), ("GenerateLeftOver", 0),
    ("GenerateLeftOver", 1), ("LEFTOVER_TYPE", "0")])
def test_operation_raw_types_are_checked_without_boolean_coercion(drill_graph, field, value):
    g = drill_graph
    getattr(g.drill_operation, field).return_value = value
    result = run(g, include_operation_parameters=True)
    assert result["status"] == "error" and result["failed_stage"] == field
    assert result["operation_parameters"]["read_complete"] is False
    g.operation.IGetTool.assert_not_called()
    g.operation.IGetAllFeatures.assert_not_called()


def test_drill_read_keeps_existing_inventory_drift_detection(drill_graph):
    g = drill_graph
    original = deepcopy(g.inventory)
    def after_read():
        g.inventory["operations"][2]["toolpath_generated"] = True
        return 2
    g.turn_tool.ToolType.side_effect = after_read
    result = run(g)
    assert result["status"] == "review_required"
    assert result["inventory_before"] == original
    assert result["inventory_unchanged"] is False
    assert_read_only(g, result)


@pytest.mark.parametrize("name,iid", [
    ("ICWDrillTool", "{7532C747-3BC4-11D6-A9AF-00062999E55F}"),
    ("ICWTurnDrillOp", "{44ADE2D0-3FA3-44C6-9B3D-8952D60FC0BB}")])
def test_bridge_interface_exact_iid_is_verified_without_com(monkeypatch, name, iid):
    cls = SimpleNamespace(_iid_=iid)
    monkeypatch.setattr(bridge, "_load_type_library", lambda _: SimpleNamespace(**{name: cls}))
    assert bridge._interface_class(name, "fixture.tlb") is cls
    cls._iid_ = "{00000000-0000-0000-0000-000000000000}"
    with pytest.raises(ValueError): bridge._interface_class(name, "fixture.tlb")
