"""在已锁定零件中创建经模型坐标回读验证的单线二维 XZ 草图。"""
from __future__ import annotations

import math

def _call_method(obj, name, *args):
    # 已由本机 TLB 确认的 METHOD：先标记，禁止 getattr 提前作为 PROPERTYGET 执行。
    # 从 Python 类型取适配器，避免为了查找适配器而发起另一次 COM 读取。
    flag = getattr(type(obj), "_FlagAsMethod", None)
    if flag is not None:
        flag(obj, name)
    return getattr(obj, name)(*args)


def _numbers(values, size, label):
    if not isinstance(values, (list, tuple)) or len(values) != size:
        raise ValueError(f"{label}: invalid array shape")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError(f"{label}: finite numbers required")
    return [float(v) for v in values]


def _inputs(endpoints, tolerance):
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 0 < tolerance <= 1e-6:
        raise ValueError("invalid tolerance_m")
    if not isinstance(endpoints, (list, tuple)) or len(endpoints) != 2:
        raise ValueError("exactly two endpoints required")
    points = [_numbers(p, 3, "endpoint") for p in endpoints]
    if math.dist(*points) <= tolerance:
        raise ValueError("degenerate line")
    if any(abs(p[1]) > tolerance for p in points):
        raise ValueError("endpoints must be in the model XZ meridian")
    return points


def _double_array(values):
    # 显式 SAFEARRAY(DOUBLE)，避免 VARIANT 元素数组改变本机 ABI。
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(values))


def _point(math_utility, xyz, transform):
    point = _call_method(math_utility, "CreatePoint", _double_array(xyz))
    if point is None:
        raise ValueError("CreatePoint returned null")
    moved = _call_method(point, "MultiplyTransform", transform)
    if moved is None:
        raise ValueError("MultiplyTransform returned null")
    return _numbers(moved.ArrayData, 3, "transformed point")


def _features(model, limit=512):
    feature = _call_method(model, "FirstFeature")
    seen = set()
    retained = []
    while feature is not None:
        if len(retained) >= limit or id(feature) in seen:
            raise ValueError("feature traversal incomplete")
        seen.add(id(feature))
        retained.append(feature)
        yield feature
        feature = _call_method(feature, "GetNextFeature")


def inspect_meridional_plane(sw, model, endpoints_model_m, *, tolerance_m=1e-8):
    """只读选择唯一 XZ 参考平面；输入为模型米坐标，返回记录及 IFeature。"""
    points = _inputs(endpoints_model_m, tolerance_m)
    math_utility = _call_method(sw, "GetMathUtility")
    matches = []
    for feature in _features(model):
        if _call_method(feature, "GetTypeName2") != "RefPlane":
            continue
        plane = _call_method(feature, "GetSpecificFeature2")
        transform = plane.Transform
        matrix = _numbers(transform.ArrayData, 16, "plane transform")
        origin = _point(math_utility, [0.0, 0.0, 0.0], transform)
        # 官方 IRefPlane 示例以规范平面的 +Z 为法向；用两点差避免平移。
        normal_point = _point(math_utility, [0.0, 0.0, 1.0], transform)
        normal = [a - b for a, b in zip(normal_point, origin)]
        length = math.sqrt(sum(x * x for x in normal))
        if not math.isfinite(length) or length <= 0:
            raise ValueError("invalid plane normal")
        normal = [x / length for x in normal]
        if abs(normal[0]) > 1e-9 or abs(normal[2]) > 1e-9 or abs(abs(normal[1]) - 1) > 1e-9:
            continue
        if abs(origin[1]) > tolerance_m:
            continue
        distances = [abs(sum((p[i] - origin[i]) * normal[i] for i in range(3))) for p in points]
        if max(distances) > tolerance_m:
            continue
        name = feature.Name
        if not isinstance(name, str) or not name:
            raise ValueError("invalid plane name")
        record = {"name": name, "origin_model_m": origin, "normal_model": normal,
                  "plane_to_model_transform": matrix, "endpoint_distances_m": distances,
                  "frame": "model_XZ", "units": "m"}
        matches.append((record, feature))
    if len(matches) != 1:
        raise ValueError(f"expected one matching XZ reference plane, found {len(matches)}")
    return matches[0]


def _as_sketch_line(segment):
    # GetSketchSegments 返回 ISketchSegment；端点方法属于 ISketchLine。
    import pythoncom
    import pywintypes
    from win32com.client import Dispatch
    raw = segment._oleobj_.QueryInterface(
        pywintypes.IID("{83A33DC1-27C5-11CE-BFD4-00400513BB57}"), pythoncom.IID_IDispatch)
    return Dispatch(raw)


def _read_line(sw, math_utility, sketch, endpoints, tolerance):
    if _call_method(sketch, "Is3D") is not False:
        raise ValueError("sketch is not confirmed 2D")
    segments = _call_method(sketch, "GetSketchSegments")
    if not isinstance(segments, (tuple, list)) or len(segments) != 1:
        raise ValueError("expected exactly one sketch segment")
    line = segments[0]
    kind = _call_method(line, "GetType")
    if type(kind) is not int or kind != 0 or line.ConstructionGeometry is not False:
        raise ValueError("expected one non-construction line")
    line = _as_sketch_line(line)
    inverse = _call_method(sketch.ModelToSketchTransform, "Inverse")
    points = []
    for method in ("GetStartPoint2", "GetEndPoint2"):
        point = _call_method(line, method)
        local = _numbers([point.X, point.Y, point.Z], 3, "sketch point")
        points.append(_point(math_utility, local, inverse))
    if any(math.dist(a, b) > tolerance for a, b in zip(points, endpoints)):
        raise ValueError("sketch endpoints differ from requested model coordinates")
    return points


def create_single_line_sketch(sw, model, *, endpoints_model_m, sketch_name,
                              expected_plane=None, tolerance_m=1e-8,
                              diagnostic=None, check=lambda: None):
    """创建唯一命名单线草图并回读；调用方负责 PID/文档/互斥/回执与实体不变检查。

    失败保留 diagnostic 和已创建草图，仅退出本次编辑；不删除、不保存、不调用 CAM。
    """
    result = diagnostic if diagnostic is not None else {}
    result.update(verified=False, sketch_name=sketch_name, stage="validate", sketch_exited=False)
    points = _inputs(endpoints_model_m, tolerance_m)
    if not isinstance(sketch_name, str) or not sketch_name or len(sketch_name) > 255 or any(c in sketch_name for c in "\\/:*?<>|\r\n"):
        raise ValueError("invalid sketch_name")
    manager = model.SketchManager
    if manager.ActiveSketch is not None:
        raise ValueError("an existing sketch is active")
    before_names = [f.Name for f in _features(model)]
    if any(str(n).casefold() == sketch_name.casefold() for n in before_names):
        raise ValueError("sketch name already exists")
    result["stage"] = "inspect_plane"
    plane_record, plane_feature = inspect_meridional_plane(sw, model, points, tolerance_m=tolerance_m)
    result["plane"] = plane_record
    if expected_plane is not None and plane_record != expected_plane:
        raise ValueError("reference plane changed since prepare")
    math_utility = _call_method(sw, "GetMathUtility")
    entered = False
    sketch = None
    failure = None
    saved_add_to_db = None
    add_to_db_touched = False
    try:
        result["stage"] = "select_plane"
        check()
        _call_method(model, "ClearSelection2", True)
        check()
        if _call_method(plane_feature, "Select2", False, 0) is not True:
            raise ValueError("reference plane selection failed")
        check()
        result["stage"] = "enter_sketch"
        entered = True
        _call_method(manager, "InsertSketch", True)
        sketch = manager.ActiveSketch
        if sketch is None or _call_method(sketch, "Is3D") is not False:
            raise ValueError("new 2D sketch not active")
        if _call_method(sketch, "GetSketchSegments") not in (None, (), []):
            raise ValueError("new sketch is not empty")
        result["stage"] = "transform_endpoints"
        transform = sketch.ModelToSketchTransform
        result["model_to_sketch_transform"] = _numbers(transform.ArrayData, 16, "sketch transform")
        local = [_point(math_utility, p, transform) for p in points]
        result["endpoints_sketch_m"] = local
        if any(abs(p[2]) > tolerance_m for p in local):
            raise ValueError("active sketch plane does not contain endpoints")
        inverse = _call_method(transform, "Inverse")
        if any(math.dist(_point(math_utility, p, inverse), q) > tolerance_m for p, q in zip(local, points)):
            raise ValueError("sketch transform inverse roundtrip failed")
        matching = []
        for feature in _features(model):
            if _call_method(feature, "GetTypeName2") == "ProfileFeature" and _call_method(sw, "IsSame", _call_method(feature, "GetSpecificFeature2"), sketch) == 1:
                matching.append(feature)
        if len(matching) != 1 or matching[0].Name in before_names:
            raise ValueError("new sketch feature identity not confirmed")
        sketch_feature = matching[0]
        result["created_feature_original_name"] = sketch_feature.Name
        saved_add_to_db = manager.AddToDB
        if type(saved_add_to_db) is not bool:
            raise ValueError("invalid AddToDB state")
        check()
        add_to_db_touched = True
        manager.AddToDB = True
        result["stage"] = "create_line"
        check()
        line = _call_method(manager, "CreateLine", *local[0][:2], 0.0, *local[1][:2], 0.0)
        if line is None:
            raise ValueError("CreateLine returned null")
        result["line_created"] = True
        result["stage"] = "rename_sketch"
        check()
        sketch_feature.Name = sketch_name
        if sketch_feature.Name != sketch_name:
            raise ValueError("sketch rename not confirmed")
        result["stage"] = "read_line"
        result["endpoints_model_m"] = _read_line(sw, math_utility, sketch, points, tolerance_m)
        check()
    except Exception as exc:
        failure = exc
        result["error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        raise
    finally:
        cleanup_errors = []
        if add_to_db_touched:
            try:
                manager.AddToDB = saved_add_to_db
            except Exception as exc:
                cleanup_errors.append(str(exc)[:1000])
        if entered:
            try:
                active = manager.ActiveSketch
                if active is not None:
                    if sketch is not None and _call_method(sw, "IsSame", active, sketch) != 1:
                        raise ValueError("active sketch changed; refusing to close another sketch")
                    _call_method(manager, "InsertSketch", True)
                result["sketch_exited"] = manager.ActiveSketch is None
                if not result["sketch_exited"]:
                    raise ValueError("sketch edit did not exit")
            except Exception as exc:
                cleanup_errors.append(str(exc)[:1000])
        if cleanup_errors:
            result["cleanup_errors"] = cleanup_errors
            if failure is None:
                raise RuntimeError("sketch cleanup failed")
    result["stage"] = "verify_closed_sketch"
    result["endpoints_model_m"] = _read_line(sw, math_utility, sketch, points, tolerance_m)
    check()
    result.update(verified=True, stage="complete")
    return result
