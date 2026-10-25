"""车削轮廓与刀具只读诊断测试；仅模拟本地接口，不连接 CAD。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from scripts import sw_cam_operation_profile as profile

CLSID = "verified-clsid"
TLB = "verified/camworks.tlb"


@pytest.fixture
def graph(monkeypatch):
    """两个 setup 中仅选中操作可访问，所有原生写操作均禁止。"""
    document = {"path": r"C:\qualification\profile.sldprt", "title": "profile.sldprt",
                "type": 1, "needs_save": False}
    inventory = {"feature_count": 1, "operation_setup_count": 2, "operation_count": 3,
                 "operations": [
                     {"setup_index": 0, "operation_index": 0, "turn_operation_type": 1},
                     {"setup_index": 1, "operation_index": 0, "turn_operation_type": 2},
                     {"setup_index": 1, "operation_index": 1, "turn_operation_type": 3,
                      "toolpath_generated": False}], "stock": {"type": 3}}
    state = {"document": document, "inventory": inventory}
    interfaces = {}
    def bind(raw, name, obj):
        interfaces[id(raw), name] = obj
        return obj
    def typed(raw, name, path):
        assert path == TLB
        return interfaces[id(raw), name]
    def collection(raw, path):
        assert path == TLB
        assert isinstance(raw, list)
        return raw
    raw_operation, raw_feature, raw_tool, raw_holder = [object() for _ in range(4)]
    raw_start, raw_end, raw_centre = [object() for _ in range(3)]
    start = bind(raw_start, "ICWPosition", SimpleNamespace(GetCoordinates=Mock(return_value=(1., 2., 3.))))
    end = bind(raw_end, "ICWPosition", SimpleNamespace(GetCoordinates=Mock(return_value=(4., 5., 6.))))
    centre = bind(raw_centre, "ICWPosition", SimpleNamespace(GetCoordinates=Mock(return_value=(7., 8., 9.))))
    raw_line, raw_arc = object(), object()
    def segment(kind):
        return SimpleNamespace(GetTurnSegmentType=Mock(return_value=kind),
            GetStartPosition=Mock(return_value=raw_start), GetEndPosition=Mock(return_value=raw_end),
            GetAllowance=Mock(side_effect=AssertionError("Unqualified optional getter must not be called")),
            GetLineSegmentParam=Mock(return_value=(10., 11., 12., 13., 14., True)),
            GetArcSegmentParam=Mock(return_value=(21., 22., 23., 24., raw_centre, True)))
    line = bind(raw_line, "ICWTurnSegment", segment(0))
    arc = bind(raw_arc, "ICWTurnSegment", segment(1))
    base_feature = bind(raw_feature, "ICWFeature", SimpleNamespace(FeatureName=Mock(return_value="Groove"), FeatType=Mock(return_value=2)))
    feature = bind(raw_feature, "ICWTurnFeature", SimpleNamespace(
        GetTurnFeatureType=Mock(return_value=2), Attribute=Mock(return_value=4),
        GetAttributeName=Mock(return_value="native attribute"), GetMinMaxDiameter=Mock(return_value=(9., 31.)),
        GetStartPosition=Mock(return_value=(1., 2., 3.)), GetEndPosition=Mock(return_value=(4., 5., 6.)),
        IGetEnumTurnSegments=Mock(return_value=[raw_line, raw_arc])))
    forbidden = [Mock(side_effect=AssertionError("Native mutation is forbidden")) for _ in range(6)]
    operation = bind(raw_operation, "ICWOperation", SimpleNamespace(
        IGetAllFeatures=Mock(return_value=[raw_feature]), IGetTool=Mock(return_value=raw_tool),
        GenerateToolpath=forbidden[0], AddFeature=forbidden[1]))
    turning = bind(raw_operation, "ICWTurnOperation", SimpleNamespace(OpernType=Mock(return_value=3), SetTool=forbidden[2]))
    tool = bind(raw_tool, "ICWTool", SimpleNamespace(ToolType=Mock(return_value=15), GetToolInfoString=Mock(return_value="native tool")))
    turn_tool = bind(raw_tool, "ICWTurnTool", SimpleNamespace(
        ToolType=Mock(return_value=1), InsertType=Mock(return_value=2), IGetTurnToolHolder=Mock(return_value=raw_holder)))
    tool_fields = {name: Mock(return_value=float(i + 1)) for i, name in enumerate(
        ("Thickness", "Width", "length", "Radius1", "Radius2", "IncludedAngle", "NoseRadius", "InscribedCircle"))}
    for name, method in tool_fields.items(): setattr(turn_tool, name, method)
    holder = bind(raw_holder, "ICWTurnToolHolder", SimpleNamespace(
        GetHolderType=Mock(return_value=1), GetHolderId=Mock(return_value=17),
        GetToolOrientationForOperation=Mock(return_value=4), HolderShape=Mock(return_value=2)))
    holder_fields = {name: Mock(return_value=float(i + 20)) for i, name in enumerate(
        ("GetHolderThickness", "ShankLength", "LeadAngle", "BackClearAngle", "FrontClearAngle",
         "ZInsertOffset", "XInsertOffset", "Protrusion", "ShankWidth", "BoringBarDiameter"))}
    for name, method in holder_fields.items(): setattr(holder, name, method)
    raw_setup0, raw_setup1 = object(), object()
    setup0 = bind(raw_setup0, "ICWBaseOpSetup", SimpleNamespace(IGetEnumOperations=Mock(side_effect=AssertionError("Wrong setup"))))
    setup1 = bind(raw_setup1, "ICWBaseOpSetup", SimpleNamespace(IGetEnumOperations=Mock(return_value=[object(), raw_operation])))
    machine = SimpleNamespace(IGetEnumOpSetups=Mock(return_value=[raw_setup0, raw_setup1]))
    sw = object()
    doc = SimpleNamespace(Save=forbidden[3])
    app = SimpleNamespace(ActiveDocGOP=forbidden[4], ActiveDocGTP=forbidden[5])
    context = Mock(side_effect=lambda *_: (deepcopy(state["document"]), doc, object(), machine, app))
    inventories = Mock(side_effect=lambda *_: deepcopy(state["inventory"]))
    snapshots = Mock(side_effect=lambda _: deepcopy(state["document"]))
    typed_mock = Mock(side_effect=typed)
    reader = Mock(wraps=profile._member)
    monkeypatch.setattr(profile, "_context", context)
    monkeypatch.setattr(profile, "_inventory", inventories)
    monkeypatch.setattr(profile, "document_snapshot", snapshots)
    monkeypatch.setattr(profile, "_typed", typed_mock)
    monkeypatch.setattr(profile, "_collection", collection)
    monkeypatch.setattr(profile, "_member", reader)
    def run(**kwargs):
        options = {"setup_index": 1, "operation_index": 1, "expected_operation_type": 3}
        options.update(kwargs)
        return profile.inspect_operation_profile(sw, CLSID, TLB, **options)
    return SimpleNamespace(**locals())


def assert_read_only(graph, report):
    for key in ("may_continue", "mutation_attempted", "generation_attempted", "model_saved",
                "units_verified", "coordinate_frame_verified", "tool_fit_verified", "production_process_qualified"):
        assert report[key] is False
    for writer in graph.forbidden: writer.assert_not_called()
    graph.line.GetAllowance.assert_not_called()
    graph.arc.GetAllowance.assert_not_called()


def test_selected_profile_preserves_native_out_order_and_state(graph):
    before = deepcopy(graph.state)
    report = graph.run()
    assert report["status"] == "ok"
    assert graph.state == before
    assert report["inventory_before"] == report["inventory_after"] == before["inventory"]
    assert report["document_before"] == report["document_after"] == before["document"]
    assert report["inventory_unchanged"] is report["active_document_unchanged"] is True
    assert report["linked_feature_count"] == 1
    assert report["geometry_parameters_complete"] is True
    feature = report["linked_features"][0]
    assert feature["diameters_native"] == {"minimum": 9., "maximum": 31.}
    assert feature["start_native"] == [1., 2., 3.]
    assert feature["end_native"] == [4., 5., 6.]
    line, arc = feature["segments"]
    assert line["line_native"] == {"start_diameter": 10., "end_diameter": 11., "length_along_axis": 12.,
                                   "true_length": 13., "taper_angle": 14.}
    assert arc["arc_native"] == {"start_diameter": 21., "end_diameter": 22., "length_along_axis": 23.,
                                 "radius": 24., "centre_native": [7., 8., 9.]}
    assert line["allowance"] == {"available": False, "reason": "not_requested_unqualified_optional_getter"}
    assert "allowance_native" not in line
    assert line["start_native"] == [1., 2., 3.] and arc["end_native"] == [4., 5., 6.]
    graph.line.GetLineSegmentParam.assert_called_once_with(graph.feature)
    graph.arc.GetArcSegmentParam.assert_called_once_with(graph.feature)
    graph.line.GetArcSegmentParam.assert_not_called()
    graph.arc.GetLineSegmentParam.assert_not_called()
    graph.setup0.IGetEnumOperations.assert_not_called()
    assert any(c.args == (graph.raw_centre, "ICWPosition", TLB) for c in graph.typed_mock.call_args_list)
    assert any(c.args == (graph.raw_operation, "ICWOperation", TLB) for c in graph.typed_mock.call_args_list)
    graph.holder.GetToolOrientationForOperation.assert_called_once_with(graph.operation)
    assert graph.inventories.call_count == 2
    graph.snapshots.assert_called_once_with(graph.sw)
    assert_read_only(graph, report)


@pytest.mark.parametrize("name", ["setup_index", "operation_index"])
@pytest.mark.parametrize("value", [True, False, "1", 1., -1, 512, None])
def test_bad_indices_fail_before_context(graph, name, value):
    report = graph.run(**{name: value})
    assert report["status"] == "error"
    graph.context.assert_not_called()
    graph.reader.assert_not_called()
    assert_read_only(graph, report)


@pytest.mark.parametrize("value", [True, False, "3", 3., 0, -1, 17, None])
def test_expected_type_is_a_strict_bounded_integer(graph, value):
    report = graph.run(expected_operation_type=value)
    assert report["status"] == "error"
    graph.context.assert_not_called()
    assert_read_only(graph, report)


@pytest.mark.parametrize("options", [{"setup_index": 2}, {"operation_index": 2}, {"expected_operation_type": 4}])
def test_missing_selection_or_inventory_type_mismatch_stops_before_native_selection(graph, options):
    report = graph.run(**options)
    assert report["status"] == "error"
    graph.machine.IGetEnumOpSetups.assert_not_called()
    graph.operation.IGetAllFeatures.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()


def test_direct_operation_type_change_stops_before_profile_or_tool(graph):
    graph.turning.OpernType.return_value = 4
    report = graph.run()
    assert report["status"] == "error"
    graph.operation.IGetAllFeatures.assert_not_called()
    graph.operation.IGetTool.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()


@pytest.mark.parametrize("stage", ["GetEndPosition", "GetLineSegmentParam", "GetArcSegmentParam", "Width", "ShankLength"])
def test_first_exception_stops_all_remaining_native_reads(graph, stage):
    getter = {"GetEndPosition": graph.line.GetEndPosition, "GetLineSegmentParam": graph.line.GetLineSegmentParam,
              "GetArcSegmentParam": graph.arc.GetArcSegmentParam,
              "Width": graph.turn_tool.Width, "ShankLength": graph.holder.ShankLength}[stage]
    getter.side_effect = RuntimeError("SECRET native failure")
    report = graph.run()
    assert report["status"] == "error" and report["failed_stage"] == stage
    assert graph.reader.call_args.args[1] == stage
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()
    assert "SECRET" not in json.dumps(report)
    assert_read_only(graph, report)


@pytest.mark.parametrize("name", ["GetLineSegmentParam", "GetArcSegmentParam"])
@pytest.mark.parametrize("native_bool", [0, 1, None, "true"])
def test_native_final_out_must_be_actual_boolean(graph, name, native_bool):
    segment = graph.arc if name == "GetArcSegmentParam" else graph.line
    method = getattr(segment, name)
    method.return_value = (*method.return_value[:-1], native_bool)
    report = graph.run()
    assert report["status"] == "error"
    assert graph.reader.call_args.args[1] == name
    graph.operation.IGetTool.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()
    if name == "GetArcSegmentParam": graph.centre.GetCoordinates.assert_not_called()


@pytest.mark.parametrize("coordinates", [(1., 2.), (1., 2., 3., True), (True, 2., 3.),
                                          (1., float("nan"), 3.), (1., 2., float("inf")), "123"])
def test_position_requires_three_finite_native_coordinates(graph, coordinates):
    graph.start.GetCoordinates.return_value = coordinates
    report = graph.run()
    assert report["status"] == "error"
    assert graph.reader.call_args.args[1] == "GetCoordinates"
    graph.line.GetEndPosition.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()


@pytest.mark.parametrize("name,value", [("GetLineSegmentParam", (10., 11., 12., 13., True)),
    ("GetLineSegmentParam", (10., 11., 12., 13., float("nan"), True)),
    ("GetArcSegmentParam", (21., 22., 23., True))])
def test_invalid_native_shape_or_nonfinite_parameter_stops_inspection(graph, name, value):
    segment = graph.arc if name == "GetArcSegmentParam" else graph.line
    getattr(segment, name).return_value = value
    report = graph.run()
    assert report["status"] == "error"
    assert graph.reader.call_args.args[1] == name
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()


def test_unknown_curve_retains_endpoints_without_guessing_parameters(graph):
    graph.line.GetTurnSegmentType.return_value = 7
    result = profile._read_segment(graph.raw_line, graph.feature, TLB, profile._member)
    assert result["curve_type_raw"] == 7 and result["curve_parameters_available"] is False
    assert result["start_native"] == [1., 2., 3.]
    assert result["end_native"] == [4., 5., 6.]
    assert result["allowance"] == {"available": False, "reason": "not_requested_unqualified_optional_getter"}
    assert "allowance_native" not in result
    graph.line.GetAllowance.assert_not_called()
    graph.line.GetLineSegmentParam.assert_not_called()
    graph.line.GetArcSegmentParam.assert_not_called()


@pytest.mark.parametrize("kind,expected", [
    (2, {"Thickness", "Width", "length", "Radius1", "Radius2"}),
    (3, {"Thickness", "Width", "length", "IncludedAngle", "NoseRadius"}),
    (1, {"Thickness", "IncludedAngle", "NoseRadius", "InscribedCircle"}),
    (8, {"Thickness", "InscribedCircle"}), (15, {"Thickness"}), (0, {"Thickness"})])
def test_insert_type_controls_documented_dimensions_not_generic_tool_type(graph, kind, expected):
    graph.turn_tool.InsertType.return_value = kind
    for name, method in graph.tool_fields.items():
        if name not in expected: method.side_effect = AssertionError("Getter is invalid for insert type")
    result = profile._read_tool(graph.raw_tool, graph.operation, TLB, profile._member)
    assert result["tool_type_raw"] == 15 and result["insert_type_raw"] == kind
    assert set(result["dimensions_native"]) == expected
    for name, method in graph.tool_fields.items():
        if name in expected: method.assert_called_once_with()
        else: method.assert_not_called()


@pytest.mark.parametrize("kind", [0, 1, 2, 99])
def test_holder_type_gates_dimensions_and_receives_selected_operation(graph, kind):
    graph.holder.GetHolderType.return_value = kind
    common = {"GetHolderThickness", "ShankLength", "LeadAngle", "BackClearAngle",
              "FrontClearAngle", "ZInsertOffset", "XInsertOffset", "Protrusion"}
    expected = common | ({"ShankWidth"} if kind == 1 else {"BoringBarDiameter"}) if kind in {1, 2} else set()
    for name, method in graph.holder_fields.items():
        if name not in expected: method.side_effect = AssertionError("Getter is invalid for holder type")
    result = profile._read_tool(graph.raw_tool, graph.operation, TLB, profile._member)["holder"]
    assert result["holder_type_raw"] == kind
    assert set(result.get("dimensions_native", {})) == expected
    for name, method in graph.holder_fields.items():
        if name in expected: method.assert_called_once_with()
        else: method.assert_not_called()
    if kind in {1, 2}: graph.holder.GetToolOrientationForOperation.assert_called_once_with(graph.operation)
    else:
        graph.holder.GetToolOrientationForOperation.assert_not_called()
        graph.holder.HolderShape.assert_not_called()


def test_absent_tool_and_holder_are_reported_without_querying_null(graph):
    assert profile._read_tool(None, graph.operation, TLB, profile._member) == {"present": False}
    graph.typed_mock.assert_not_called()
    graph.turn_tool.IGetTurnToolHolder.return_value = None
    result = profile._read_tool(graph.raw_tool, graph.operation, TLB, profile._member)
    assert result["holder"] == {"present": False}
    graph.holder.GetHolderType.assert_not_called()


@pytest.mark.parametrize("changed", ["document", "inventory"])
def test_successful_reads_detect_state_changes_without_qualification_claims(graph, changed):
    if changed == "document":
        after = deepcopy(graph.state["document"])
        after["needs_save"] = True
        graph.snapshots.return_value = after
        graph.snapshots.side_effect = None
    else:
        after = deepcopy(graph.state["inventory"])
        after["operation_count"] += 1
        graph.inventories.side_effect = [deepcopy(graph.state["inventory"]), after]
    report = graph.run()
    assert report["status"] == "review_required"
    assert report["reason"] == "CAM_STATE_CHANGED_DURING_PROFILE_INSPECTION"
    assert report["active_document_unchanged"] is (changed != "document")
    assert report["inventory_unchanged"] is (changed != "inventory")
    assert_read_only(graph, report)


def test_feature_limit_prevents_all_feature_reads_and_final_readback(graph):
    graph.operation.IGetAllFeatures.return_value = [graph.raw_feature] * 65
    report = graph.run()
    assert report["status"] == "error"
    graph.base_feature.FeatureName.assert_not_called()
    graph.operation.IGetTool.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()


def test_segment_limit_is_shared_across_linked_features(graph, monkeypatch):
    monkeypatch.setattr(profile, "_MAX_SEGMENTS", 3)
    graph.operation.IGetAllFeatures.return_value = [graph.raw_feature, graph.raw_feature]
    report = graph.run()
    assert report["status"] == "error"
    assert len(report["linked_features"]) == 2
    assert report["linked_features"][1]["name"] == "Groove"
    graph.line.GetLineSegmentParam.assert_called_once()
    graph.arc.GetArcSegmentParam.assert_called_once()
    graph.operation.IGetTool.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()


@pytest.mark.parametrize("kind", ["line", "arc"])
def test_false_curve_result_keeps_endpoints_but_ignores_every_other_out_value(graph, kind):
    segment = graph.line if kind == "line" else graph.arc
    name = "GetLineSegmentParam" if kind == "line" else "GetArcSegmentParam"
    getattr(segment, name).return_value = (object(), object(), object(), object(), object(), False)
    report = graph.run()
    assert report["status"] == "ok"
    result = report["linked_features"][0]["segments"][0 if kind == "line" else 1]
    assert result["curve_parameters_available"] is False
    assert result["curve_parameters_status"] == "native_returned_false"
    assert result["curve_parameters_native_return"] is False
    assert report["geometry_parameters_complete"] is False
    assert result["start_native"] == [1., 2., 3.]
    assert result["end_native"] == [4., 5., 6.]
    assert "line_native" not in result and "arc_native" not in result
    assert result["allowance"] == {"available": False, "reason": "not_requested_unqualified_optional_getter"}
    if kind == "arc": graph.centre.GetCoordinates.assert_not_called()
    assert graph.inventories.call_count == 2
    graph.snapshots.assert_called_once_with(graph.sw)
    assert_read_only(graph, report)


@pytest.mark.parametrize("kind", ["line", "arc"])
def test_curve_exception_preserves_feature_and_partial_segment(graph, kind):
    segment = graph.line if kind == "line" else graph.arc
    name = "GetLineSegmentParam" if kind == "line" else "GetArcSegmentParam"
    getattr(segment, name).side_effect = RuntimeError("native failure")
    report = graph.run()
    assert report["status"] == "error" and report["failed_stage"] == name
    feature = report["linked_features"][0]
    assert feature["name"] == "Groove"
    assert feature["diameters_native"] == {"minimum": 9., "maximum": 31.}
    assert len(feature["segments"]) == (1 if kind == "line" else 2)
    partial = feature["segments"][-1]
    assert partial["curve_type_raw"] == (0 if kind == "line" else 1)
    assert partial["start_native"] == [1., 2., 3.]
    assert partial["end_native"] == [4., 5., 6.]
    assert "line_native" not in partial and "arc_native" not in partial
    if kind == "arc":
        assert feature["segments"][0]["line_native"]["true_length"] == 13.
        graph.centre.GetCoordinates.assert_not_called()
    graph.operation.IGetTool.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()
    assert_read_only(graph, report)


def test_feature_exception_preserves_prior_feature_fields(graph):
    graph.feature.GetAttributeName.side_effect = RuntimeError("native failure")
    report = graph.run()
    assert report["status"] == "error"
    partial = report["linked_features"][0]
    assert partial["name"] == "Groove"
    assert partial["feature_type_raw"] == 2
    assert partial["turn_feature_type_raw"] == 2
    assert partial["attribute_id_raw"] == 4
    assert "attribute_name" not in partial
    graph.feature.GetMinMaxDiameter.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()
    assert_read_only(graph, report)


def test_width_exception_preserves_tool_metadata_and_read_thickness(graph):
    graph.turn_tool.Width.side_effect = RuntimeError("native failure")
    report = graph.run()
    assert report["status"] == "error" and report["failed_stage"] == "Width"
    tool = report["tool"]
    assert tool["present"] is True
    assert tool["tool_type_raw"] == 15 and tool["turn_tool_type_raw"] == 1
    assert tool["insert_type_raw"] == 2 and tool["info_raw"] == "native tool"
    assert tool["dimensions_native"] == {"Thickness": 1.}
    graph.turn_tool.length.assert_not_called()
    graph.turn_tool.IGetTurnToolHolder.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()
    assert_read_only(graph, report)


def test_holder_exception_preserves_tool_and_already_read_holder_fields(graph):
    graph.holder.ShankLength.side_effect = RuntimeError("native failure")
    report = graph.run()
    assert report["status"] == "error" and report["failed_stage"] == "ShankLength"
    tool = report["tool"]
    assert set(tool["dimensions_native"]) == {"Thickness", "Width", "length", "Radius1", "Radius2"}
    holder = tool["holder"]
    assert holder["present"] is True and holder["holder_type_raw"] == 1
    assert holder["holder_id_raw"] == 17
    assert holder["orientation_for_operation_raw"] == 4 and holder["shape_raw"] == 2
    assert holder["dimensions_native"] == {"GetHolderThickness": 20.}
    graph.holder.LeadAngle.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()
    assert_read_only(graph, report)


def test_arc_centre_exception_preserves_confirmed_numeric_out_values(graph):
    graph.centre.GetCoordinates.side_effect = RuntimeError("native failure")
    report = graph.run()
    assert report["status"] == "error" and report["failed_stage"] == "GetCoordinates"
    partial = report["linked_features"][0]["segments"][1]
    assert partial["start_native"] == [1., 2., 3.]
    assert partial["end_native"] == [4., 5., 6.]
    assert partial["arc_native"] == {"start_diameter": 21., "end_diameter": 22.,
                                      "length_along_axis": 23., "radius": 24.}
    assert partial["curve_parameters_native_return"] is True
    graph.operation.IGetTool.assert_not_called()
    assert graph.inventories.call_count == 1
    graph.snapshots.assert_not_called()
    assert_read_only(graph, report)


def test_profile_optional_collection_reader_gets_remaining_budget_before_items(graph, monkeypatch):
    from scripts import sw_cam_turn_feature_attribute as attribute
    monkeypatch.setattr(attribute, "_typed", lambda obj, *_: obj)
    collection = SimpleNamespace(Count=2, Item=Mock())
    graph.feature.IGetEnumTurnSegments.return_value = collection
    monkeypatch.setattr(profile, "_collection", Mock(side_effect=AssertionError("Ungarded collection bypass")))
    reader = Mock(side_effect=lambda raw, limit: attribute._items(raw, TLB, profile._member, limit=limit))
    with pytest.raises(ValueError, match="remaining qualification bound"):
        profile._read_profile(graph.raw_feature, TLB, profile._member, [511], collection_reader=reader)
    reader.assert_called_once_with(collection, 1)
    collection.Item.assert_not_called()
    graph.line.GetTurnSegmentType.assert_not_called()


def test_profile_nested_item_event_stops_later_items_and_segment_getters(graph, monkeypatch):
    from scripts import sw_cam_turn_feature_attribute as attribute
    monkeypatch.setattr(attribute, "_typed", lambda obj, *_: obj)
    collection = SimpleNamespace(Count=2, Item=Mock(return_value=graph.raw_line))
    graph.feature.IGetEnumTurnSegments.return_value = collection
    def guarded(obj, name, *args):
        value = profile._member(obj, name, *args)
        if obj is collection and name == "Item":
            raise ValueError("CAM event after Item")
        return value
    with pytest.raises(ValueError, match="CAM event after Item"):
        profile._read_profile(graph.raw_feature, TLB, guarded, [0],
            collection_reader=lambda raw, limit: attribute._items(raw, TLB, guarded, limit=limit))
    collection.Item.assert_called_once_with(0)
    graph.line.GetTurnSegmentType.assert_not_called()
