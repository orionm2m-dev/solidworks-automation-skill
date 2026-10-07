"""检查、重建无尺寸约束的四段胶囊草图；保留草图及其切除特征。"""
from __future__ import annotations

import math

try:
    from .sw_connect import get_com_member as member
except ImportError:
    from sw_connect import get_com_member as member


TOL = 1e-7  # 米；只用于几何回读比较。


def _xyz(point):
    return [float(member(point, name)) for name in ("X", "Y", "Z")]


def _distance(a, b):
    return math.dist(a, b)


def analyze_capsule(segments):
    """识别两条直线和两个外侧半圆组成的平面闭合胶囊，坐标单位为米。"""
    arcs = [s for s in segments if s["type"] == 1]
    lines = [s for s in segments if s["type"] == 0]
    if len(segments) != 4 or len(arcs) != 2 or len(lines) != 2:
        raise ValueError("仅支持两条直线和两个半圆的四段草图")
    if any(s["construction"] for s in segments):
        raise ValueError("不支持构造线")
    c0, c1 = (s["center"] for s in arcs)
    span = _distance(c0, c1)
    radius = arcs[0]["radius"]
    if not math.isfinite(radius) or radius <= TOL or span <= TOL:
        raise ValueError("胶囊尺寸无效")
    axis = [(b-a)/span for a, b in zip(c0, c1)]
    normal = [-axis[1], axis[0], 0.0]
    if abs(axis[2]) > TOL:
        raise ValueError("胶囊必须在草图 XY 平面内")
    endpoints = []
    for i, arc in enumerate(arcs):
        c = arc["center"]
        if abs(arc["radius"]-radius) > TOL or abs(arc["length"]-math.pi*radius) > TOL:
            raise ValueError("端部必须是等半径半圆")
        for p in (arc["start"], arc["end"]):
            if abs(p[2]) > TOL or abs(c[2]) > TOL:
                raise ValueError("非平面草图")
            if min(_distance(p, [c[j]+sign*radius*normal[j] for j in range(3)])
                   for sign in (-1, 1)) > TOL:
                raise ValueError("半圆端点未与长轴垂直")
            endpoints.append(p)
        if _distance(arc["start"], arc["end"]) < 2*radius-TOL:
            raise ValueError("半圆端点退化")
        # 中点必须朝外，避免错误识别两个内凹半圆。
        a = [arc["start"][j]-c[j] for j in range(3)]
        mid = [-arc["direction"]*a[1], arc["direction"]*a[0], 0.0]
        dot = sum(mid[j]*axis[j] for j in range(3))
        if (i == 0 and dot >= 0) or (i == 1 and dot <= 0):
            raise ValueError("半圆方向朝内")
    remaining = list(endpoints)
    for line in lines:
        if abs(line["length"]-span) > TOL:
            raise ValueError("直线长度不匹配")
        delta = [line["end"][j]-line["start"][j] for j in range(3)]
        if abs(abs(sum(delta[j]*axis[j] for j in range(3)))-span) > TOL:
            raise ValueError("直线未与胶囊长轴平行")
        for p in (line["start"], line["end"]):
            found = next((i for i, q in enumerate(remaining) if _distance(p, q) <= TOL), None)
            if found is None:
                raise ValueError("轮廓不闭合或重复端点")
            remaining.pop(found)
    return {"center_m": [(a+b)/2 for a, b in zip(c0, c1)], "axis": axis,
            "length_mm": (span+2*radius)*1000, "width_mm": radius*2000}


def _read(model, sketch_name):
    if int(member(model, "GetType")) != 1:
        raise ValueError("仅支持零件文档")
    feature = member(model, "FeatureByName", sketch_name)
    if feature is None or str(member(feature, "GetTypeName2")) != "ProfileFeature":
        raise ValueError(f"找不到二维草图: {sketch_name}")
    sketch = member(feature, "GetSpecificFeature2")
    if bool(member(sketch, "Is3D")):
        raise ValueError("不支持三维草图")
    segments, refs = [], []
    for seg in member(sketch, "GetSketchSegments") or []:
        kind = int(member(seg, "GetType"))
        if kind not in (0, 1):
            raise ValueError("仅支持圆弧和直线")
        entry = {"type": kind, "construction": bool(member(seg, "ConstructionGeometry")),
                 "length": float(member(seg, "GetLength"))}
        for key, api in (("start", "GetStartPoint2"), ("end", "GetEndPoint2")):
            point = member(seg, api)
            entry[key] = _xyz(point)
            refs.append((point, entry[key]))
        if kind == 1:
            point = member(seg, "GetCenterPoint2")
            entry["center"] = _xyz(point)
            entry["radius"] = float(member(seg, "GetRadius"))
            entry["direction"] = int(member(seg, "GetRotationDir"))
            refs.insert(0, (point, entry["center"]))
        segments.append(entry)
    try:
        report = analyze_capsule(segments)
    except ValueError as exc:
        raise ValueError(f"{exc}; segments={segments}") from exc
    report.update({"sketch_name": sketch_name, "segments": segments,
                   "read_only": bool(member(model, "IsOpenedReadOnly")),
                   "save_flag": bool(member(model, "GetSaveFlag")),
                   "relations": int(member(member(sketch, "RelationManager"), "GetRelationsCount", 0)),
                   "has_dimensions": member(feature, "GetFirstDisplayDimension") is not None,
                   "slot_count": int(member(sketch, "GetSketchSlotCount"))})
    return report, feature, refs


def inspect_capsule_sketch(model, sketch_name):
    """只读返回胶囊尺寸、方向、草图关系和原始几何。"""
    report, _, _ = _read(model, sketch_name)
    return report


def _health(model):
    bodies = list(member(model, "GetBodies2", 0, False) or [])
    faults = [int(member(body, "Check2")) for body in bodies]
    errors = []
    features = []
    feature = member(model, "FirstFeature")
    while feature is not None:
        features.append({"name": str(member(feature, "Name")), "type": str(member(feature, "GetTypeName2"))})
        code = int(member(feature, "GetErrorCode"))
        if code:
            errors.append({"feature": str(member(feature, "Name")), "code": code})
        feature = member(feature, "GetNextFeature")
    return {"solid_bodies": len(bodies), "body_checks": faults, "feature_errors": errors, "features": features}


def _same_shape(a, b):
    return (abs(a["length_mm"]-b["length_mm"]) < TOL*1000 and
            abs(a["width_mm"]-b["width_mm"]) < TOL*1000 and
            _distance(a["center_m"], b["center_m"]) < TOL and
            abs(abs(sum(x*y for x, y in zip(a["axis"], b["axis"])))-1) < TOL)


def resize_capsule_sketch(model, sketch_name, length_mm, width_mm,
                          center_x_mm=None, center_y_mm=None):
    """原位修改无约束胶囊，不保存；回读或重建失败则撤销并验证恢复。

    仅支持单配置零件、四段草图，无尺寸、无关系、无原生 Slot 对象。
    保留草图、方向和切除特征；默认保留中心，可指定草图 XY 绝对中心（mm）。
    替换四个原生草图段，段级引用必须复核。
    """
    if not all(math.isfinite(x) for x in (length_mm, width_mm)) or not 0 < width_mm < length_mm:
        raise ValueError("尺寸必须满足有限值且 0 < width_mm < length_mm")
    if (center_x_mm is None) != (center_y_mm is None):
        raise ValueError("必须同时指定 center_x_mm 和 center_y_mm")
    if center_x_mm is not None and not all(math.isfinite(x) for x in (center_x_mm, center_y_mm)):
        raise ValueError("中心坐标必须是有限值")
    if len(member(model, "GetConfigurationNames") or []) != 1:
        raise ValueError("只支持单配置零件")
    if member(member(model, "SketchManager"), "ActiveSketch") is not None:
        raise ValueError("请先退出当前草图编辑")
    before, feature, refs = _read(model, sketch_name)
    if before["relations"] or before["has_dimensions"] or before["slot_count"]:
        raise ValueError("草图具有关系、尺寸或原生 Slot 对象；请使用尺寸编辑工具")
    if before["read_only"]:
        raise ValueError("文档以只读方式打开，拒绝修改")
    health_before = _health(model)
    if health_before["feature_errors"] or any(health_before["body_checks"]) or not health_before["solid_bodies"]:
        raise ValueError(f"修改前零件检查未通过: {health_before}")
    expected = dict(before, length_mm=float(length_mm), width_mm=float(width_mm))
    if center_x_mm is not None:
        expected["center_m"] = [float(center_x_mm)/1000, float(center_y_mm)/1000, 0.0]
    if _same_shape(before, expected):
        return {"success": True, "changed": False, "before": before, "after": before,
                "health": health_before, "saved": False, "segment_references_preserved": True, "review_required": True}
    axis, center = before["axis"], before["center_m"]
    axial_scale = (length_mm-width_mm)/(before["length_mm"]-before["width_mm"])
    radial_scale = width_mm/before["width_mm"]
    def transform(old):
        delta = [old[i]-center[i] for i in range(3)]
        parallel = sum(delta[i]*axis[i] for i in range(3))
        return [expected["center_m"][i]+axial_scale*parallel*axis[i]+radial_scale*(delta[i]-parallel*axis[i])
                for i in range(3)]
    extension = member(model, "Extension")
    member(model, "ClearSelection2", True)
    if not member(feature, "Select2", False, 0):
        raise RuntimeError("无法选择目标草图")
    member(extension, "StartRecordingUndoObject")
    finished = False
    changed = False
    active = None
    try:
        member(model, "EditSketch")
        active = member(member(model, "SketchManager"), "ActiveSketch")
        selected_sketch = member(feature, "GetSpecificFeature2")
        if active is None or active._oleobj_ != selected_sketch._oleobj_:
            raise RuntimeError("未进入目标草图")
        changed = True
        manager = member(model, "SketchManager")
        old_add_to_db = bool(member(manager, "AddToDB"))
        try:
            for index, seg in enumerate(member(active, "GetSketchSegments") or []):
                if not member(seg, "Select", index != 0):
                    raise RuntimeError("无法选择原草图段")
            if not member(extension, "DeleteSelection2", 0):
                raise RuntimeError("无法删除所选草图段")
            manager.AddToDB = True
            for seg in before["segments"]:
                start, end = transform(seg["start"]), transform(seg["end"])
                if seg["type"] == 1:
                    c = transform(seg["center"])
                    created = member(manager, "CreateArc", *c, *start, *end, seg["direction"])
                else:
                    created = member(manager, "CreateLine", *start, *end)
                if created is None:
                    raise RuntimeError("创建原生草图段失败")
        finally:
            manager.AddToDB = old_add_to_db
        member(member(model, "SketchManager"), "InsertSketch", True)
        rebuilt = bool(member(model, "EditRebuild3"))
        after = inspect_capsule_sketch(model, sketch_name)
        health = _health(model)
        if not rebuilt or not _same_shape(after, expected) or health != health_before:
            raise RuntimeError(f"修改后尺寸/重建/实体检查未通过: {health}")
        finished = bool(member(extension, "FinishRecordingUndoObject2", "Resize capsule sketch", False))
        member(model, "ClearSelection2", True)
        member(model, "GraphicsRedraw2")
        return {"success": True, "changed": True, "before": before, "after": after,
                "health": health, "saved": False, "segment_references_preserved": False,
                "undo_record_created": finished, "review_required": True}
    except Exception as exc:
        try:
            if member(member(model, "SketchManager"), "ActiveSketch") is not None:
                member(member(model, "SketchManager"), "InsertSketch", True)
            if not finished:
                finished = bool(member(extension, "FinishRecordingUndoObject2", "Resize capsule sketch", False))
            if changed and finished:
                member(model, "EditUndo2", 1)
                member(model, "EditRebuild3")
            rollback = _same_shape(inspect_capsule_sketch(model, sketch_name), before) and _health(model) == health_before
        except Exception:
            rollback = False
        return {"success": False, "error": str(exc), "rollback_verified": rollback,
                "saved": False, "segment_references_preserved": False, "review_required": True}
