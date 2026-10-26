"""只读车削操作关联轮廓与刀具尺寸；不生成、不修改、不猜测单位或坐标系。"""
from __future__ import annotations

import math

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _collection, _context, _inventory, _typed

_MAX_FEATURES = 64
_MAX_SEGMENTS = 512


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("CAM value must be a finite native number")
    return float(value)


def _integer(value):
    if type(value) is not int:
        raise ValueError("CAM value must be an integer")
    return value


def _values(value, count):
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError("Unexpected native OUT parameter shape")
    return value


def _text(value):
    if not isinstance(value, str):
        raise ValueError("CAM value must be a BSTR string")
    return value[:1000]


def _position(raw, typelib_path, read):
    position = _typed(raw, "ICWPosition", typelib_path)
    return list(map(_number, _values(read(position, "GetCoordinates"), 3)))


def _read_segment(raw, feature, typelib_path, read, result=None):
    result = {} if result is None else result
    segment = _typed(raw, "ICWTurnSegment", typelib_path)
    result["curve_type_raw"] = _integer(read(segment, "GetTurnSegmentType"))
    result["start_native"] = _position(read(segment, "GetStartPosition"), typelib_path, read)
    result["end_native"] = _position(read(segment, "GetEndPosition"), typelib_path, read)
    # GetAllowance 的 false 语义未记录，几何检查不需要此可选 getter。
    result["allowance"] = {"available": False, "reason": "not_requested_unqualified_optional_getter"}
    kind = result["curve_type_raw"]
    if kind not in {0, 1}:
        result.update(curve_parameters_available=False, curve_parameters_status="unsupported_curve_type")
        return result
    method = "GetLineSegmentParam" if kind == 0 else "GetArcSegmentParam"
    values = _values(read(segment, method, feature), 6)
    if type(values[5]) is not bool:
        raise ValueError(f"{method} did not return a Boolean")
    result["curve_parameters_native_return"] = values[5]
    result["curve_parameters_available"] = values[5]
    if not values[5]:
        # false 时 OUT 数据未获成功确认，不能把零值或残留值当作尺寸。
        result["curve_parameters_status"] = "native_returned_false"
        return result
    result["curve_parameters_status"] = "available"
    if kind == 0:
        result["line_native"] = dict(zip(
            ("start_diameter", "end_diameter", "length_along_axis", "true_length", "taper_angle"),
            map(_number, values[:5])))
    else:
        result["arc_native"] = dict(zip(
            ("start_diameter", "end_diameter", "length_along_axis", "radius"),
            map(_number, values[:4])))
        result["arc_native"]["centre_native"] = _position(values[4], typelib_path, read)
    return result


def _read_profile(raw, typelib_path, read, budget, result=None, *, collection_reader=None):
    result = {} if result is None else result
    base = _typed(raw, "ICWFeature", typelib_path)
    turn = _typed(raw, "ICWTurnFeature", typelib_path)
    result["name"] = _text(read(base, "FeatureName"))
    result["feature_type_raw"] = _integer(read(base, "FeatType"))
    result["turn_feature_type_raw"] = _integer(read(turn, "GetTurnFeatureType"))
    result["attribute_id_raw"] = _integer(read(turn, "Attribute"))
    result["attribute_name"] = _text(read(turn, "GetAttributeName"))
    result["diameters_native"] = dict(zip(("minimum", "maximum"),
        map(_number, _values(read(turn, "GetMinMaxDiameter"), 2))))
    result["start_native"] = list(map(_number, _values(read(turn, "GetStartPosition"), 3)))
    result["end_native"] = list(map(_number, _values(read(turn, "GetEndPosition"), 3)))
    raw_segments = read(turn, "IGetEnumTurnSegments")
    segments = (_collection(raw_segments, typelib_path) if collection_reader is None
                else collection_reader(raw_segments, _MAX_SEGMENTS - budget[0]))
    budget[0] += len(segments)
    if budget[0] > _MAX_SEGMENTS:
        raise ValueError("Linked profile segment count exceeds inspection limit")
    result["segment_count"] = len(segments)
    result["segments"] = []
    for raw_segment in segments:
        item = {}
        result["segments"].append(item)
        _read_segment(raw_segment, turn, typelib_path, read, item)
    return result


def _read_tool(raw, raw_operation, typelib_path, read, result=None):
    result = {} if result is None else result
    if raw is None or not bool(raw):
        result["present"] = False
        return result
    result["present"] = True
    base = _typed(raw, "ICWTool", typelib_path)
    result["tool_type_raw"] = _integer(read(base, "ToolType"))
    result["info_raw"] = _text(read(base, "GetToolInfoString"))
    result["dimensions_native"] = {}
    if result["tool_type_raw"] != 15:
        result.update(parameters_status="unavailable", reason="generic_tool_is_not_turning_tool")
        return result
    turn = _typed(raw, "ICWTurnTool", typelib_path)
    result["turn_tool_type_raw"] = _integer(read(turn, "ToolType"))
    if result["turn_tool_type_raw"] != 1:
        # TURN 机床也可分配钻头；不向非车刀请求刀片尺寸或夹持器。
        result.update(parameters_status="unavailable", reason="unsupported_turn_tool_type")
        return result
    result["insert_type_raw"] = _integer(read(turn, "InsertType"))
    insert_type = result["insert_type_raw"]
    if insert_type not in {1, 2, 3, 4, 5, 6, 7, 8, 15, 16}:
        result.update(parameters_status="unavailable", reason="unsupported_insert_type")
        return result
    result["parameters_status"] = "available"
    dimensions = {}
    result["dimensions_native"] = dimensions
    dimensions["Thickness"] = _number(read(turn, "Thickness"))
    # 按类型库声明的适用插片类型选择 getter；不同枚举不得互相替代。
    fields = []
    if insert_type in {2, 3}:
        fields += ["Width", "length"]
    if insert_type == 2:
        fields += ["Radius1", "Radius2"]
    if insert_type in {1, 3}:
        fields += ["IncludedAngle"]
    if insert_type in {1, 3, 4, 5, 6, 7, 16}:
        fields += ["NoseRadius"]
    if insert_type in {1, 4, 5, 6, 7, 8, 16}:
        fields += ["InscribedCircle"]
    for name in fields:
        dimensions[name] = _number(read(turn, name))
    raw_holder = read(turn, "IGetTurnToolHolder")
    holder_data = {"present": raw_holder is not None and bool(raw_holder)}
    result["holder"] = holder_data
    if not holder_data["present"]:
        return result
    holder = _typed(raw_holder, "ICWTurnToolHolder", typelib_path)
    kind = _integer(read(holder, "GetHolderType"))
    holder_data["holder_type_raw"] = kind
    holder_data["holder_id_raw"] = _integer(read(holder, "GetHolderId"))
    if kind in {1, 2}:
        holder_data["orientation_for_operation_raw"] = _integer(
            read(holder, "GetToolOrientationForOperation", raw_operation))
        holder_data["shape_raw"] = _integer(read(holder, "HolderShape"))
        fields = ["GetHolderThickness", "ShankLength", "LeadAngle", "BackClearAngle",
                  "FrontClearAngle", "ZInsertOffset", "XInsertOffset", "Protrusion"]
        fields += ["ShankWidth"] if kind == 1 else ["BoringBarDiameter"]
        holder_data["dimensions_native"] = {}
        for name in fields:
            holder_data["dimensions_native"][name] = _number(read(holder, name))
    return result


def inspect_operation_profile(sw, clsid, typelib_path, *, setup_index, operation_index,
                              expected_operation_type, include_tool=True):
    """读取已绑定会话的指定操作、关联轮廓及刀具；首个失败立即停止后续读取。

    参数为已验证插件与类型库、零基索引和预期操作类型。返回原始数值及前后
    文档/清单快照；坐标系、单位、刀具可达性及加工合格性必须另行验证。
    """
    report = {"status": "error", "may_continue": False, "mutation_attempted": False,
              "generation_attempted": False, "model_saved": False,
              "units_verified": False, "coordinate_frame_verified": False,
              "tool_fit_verified": False, "production_process_qualified": False}
    stage = "validate_inputs"

    def read(obj, name, *args):
        nonlocal stage
        stage = name
        return _member(obj, name, *args)

    try:
        if type(include_tool) is not bool:
            raise ValueError("include_tool must be a strict Boolean")
        report["include_tool"] = include_tool
        for name, value in (("setup_index", setup_index), ("operation_index", operation_index)):
            if type(value) is not int or not 0 <= value <= 511:
                raise ValueError(f"{name} must be an integer in [0, 511]")
        if type(expected_operation_type) is not int or not 1 <= expected_operation_type <= 16:
            raise ValueError("expected_operation_type must be an integer in [1, 16]")
        stage = "context"
        before, _doc, _part, machine, _app = _context(sw, clsid, typelib_path)
        report["document_before"] = before
        stage = "inventory_before"
        initial = _inventory(machine, typelib_path)
        report["inventory_before"] = initial
        selected = next((item for item in initial["operations"]
                         if item["setup_index"] == setup_index and
                         item["operation_index"] == operation_index), None)
        if selected is None or selected["turn_operation_type"] != expected_operation_type:
            raise ValueError("Selected operation does not match the expected inventory/type")
        setups = _collection(read(machine, "IGetEnumOpSetups"), typelib_path)
        setup = _typed(setups[setup_index], "ICWBaseOpSetup", typelib_path)
        operations = _collection(read(setup, "IGetEnumOperations"), typelib_path)
        raw = operations[operation_index]
        operation = _typed(raw, "ICWOperation", typelib_path)
        turning = _typed(raw, "ICWTurnOperation", typelib_path)
        if _integer(read(turning, "OpernType")) != expected_operation_type:
            raise ValueError("Selected operation type changed during inspection")
        report["selected_operation"] = dict(selected)
        linked = _collection(read(operation, "IGetAllFeatures"), typelib_path)
        if len(linked) > _MAX_FEATURES:
            raise ValueError("Linked feature count exceeds inspection limit")
        report["linked_features"] = []
        budget = [0]
        report["linked_feature_count"] = len(linked)
        for feature in linked:
            item = {}
            report["linked_features"].append(item)
            _read_profile(feature, typelib_path, read, budget, item)
        report["geometry_parameters_complete"] = all(
            segment.get("curve_parameters_available") for feature in report["linked_features"]
            for segment in feature["segments"])
        report["tool"] = {}
        if include_tool:
            _read_tool(read(operation, "IGetTool"), operation, typelib_path, read, report["tool"])
        else:
            report["tool"].update(requested=False, parameters_status="not_requested")
        stage = "inventory_after"
        after_inventory = _inventory(machine, typelib_path)
        stage = "document_after"
        after = document_snapshot(sw)
        report.update(inventory_after=after_inventory, document_after=after,
                      inventory_unchanged=initial == after_inventory,
                      active_document_unchanged=before == after)
        unchanged = initial == after_inventory and before == after
        report["status"] = "ok" if unchanged else "review_required"
        if not unchanged:
            report["reason"] = "CAM_STATE_CHANGED_DURING_PROFILE_INSPECTION"
        elif include_tool and report["tool"].get("parameters_status") == "unavailable":
            report.update(status="review_required", reason="CAM_TOOL_PARAMETERS_UNAVAILABLE")
    except Exception as exc:
        report.update(status="error", reason="CAM_OPERATION_PROFILE_INSPECTION_FAILED",
                      failed_stage=stage, issue=_error(exc))
    return report
