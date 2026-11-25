"""@brief 按区域查询零件的面：类型、法向/轴线/半径、面积与包围盒（毫米，零件坐标），只读。"""
from __future__ import annotations

import math

try:
    from .sw_connect import get_com_member
except ImportError:
    from sw_connect import get_com_member

_MM = 1000.0
SOLID_BODY = 0
KINDS = ("plane", "cylinder", "cone", "sphere", "torus", "other")


def _vector(values, count):
    data = [float(v) for v in list(values)[:count]]
    if len(data) != count or not all(math.isfinite(v) for v in data):
        raise ValueError(f"expected {count} finite values, got {values!r}")
    return data


def _mm(values):
    return [round(v * _MM, 4) for v in values]


def _unit(values):
    length = math.sqrt(sum(v * v for v in values))
    return [round(v / length, 6) for v in values] if length > 1e-12 else None


def _plane_from_params(params):
    """
    @brief PlaneParams 的 6 个数：法向与基点。两组都可能是单位长，按“法向为单位向量”判断；
        都是单位长时按 SolidWorks 文档的顺序（法向在前）。
    @return (normal, root_point)
    """
    first, second = params[:3], params[3:6]
    first_unit = abs(math.sqrt(sum(v * v for v in first)) - 1.0) < 1e-6
    second_unit = abs(math.sqrt(sum(v * v for v in second)) - 1.0) < 1e-6
    if second_unit and not first_unit:
        return second, first
    return first, second


def describe_face(face):
    """@brief 单个面的几何描述；读取失败的项记录在 errors 中。"""
    row = {"type": "other", "errors": []}
    try:
        row["area_mm2"] = round(float(get_com_member(face, "GetArea")) * _MM * _MM, 4)
    except Exception as exc:
        row["errors"].append(f"GetArea: {exc}")
    try:
        row["box_mm"] = _mm(_vector(get_com_member(face, "GetBox"), 6))
    except Exception as exc:
        row["errors"].append(f"GetBox: {exc}")
    sense = True
    try:
        sense = bool(get_com_member(face, "FaceInSurfaceSense"))
    except Exception:
        pass
    try:
        surface = get_com_member(face, "GetSurface")
        if get_com_member(surface, "IsPlane"):
            params = _vector(get_com_member(surface, "PlaneParams"), 6)
            normal, root = _plane_from_params(params)
            normal = _unit(normal)
            # SolidWorks 2026 实测（长方体 6 面、旋转件槽两壁）：FaceInSurfaceSense=False 时 PlaneParams 法向即
            # 指向材料外侧；True 时相反。
            row.update(type="plane", surface_params=params, root_point_mm=_mm(root), face_in_surface_sense=sense,
                       normal=normal if (not sense or normal is None) else [-v for v in normal])
        elif get_com_member(surface, "IsCylinder"):
            p = _vector(get_com_member(surface, "CylinderParams"), 7)
            row.update(type="cylinder", axis_point_mm=_mm(p[0:3]), axis_direction=_unit(p[3:6]),
                       radius_mm=round(p[6] * _MM, 4), diameter_mm=round(2 * p[6] * _MM, 4), face_in_surface_sense=sense)
        elif get_com_member(surface, "IsCone"):
            p = _vector(get_com_member(surface, "ConeParams"), 8)
            row.update(type="cone", axis_point_mm=_mm(p[0:3]), axis_direction=_unit(p[3:6]),
                       radius_mm=round(p[6] * _MM, 4), half_angle_deg=round(math.degrees(p[7]), 4))
        elif get_com_member(surface, "IsSphere"):
            p = _vector(get_com_member(surface, "SphereParams"), 4)
            row.update(type="sphere", center_mm=_mm(p[0:3]), radius_mm=round(p[3] * _MM, 4))
        elif get_com_member(surface, "IsTorus"):
            p = _vector(get_com_member(surface, "TorusParams"), 8)
            row.update(type="torus", center_mm=_mm(p[0:3]), axis_direction=_unit(p[3:6]),
                       major_radius_mm=round(p[6] * _MM, 4), minor_radius_mm=round(p[7] * _MM, 4))
    except Exception as exc:
        row["errors"].append(f"surface: {exc}")
    return row


def _box_relation(face_box, query, mode, tolerance):
    if mode == "inside":
        return all(query[i] - tolerance <= face_box[i] and face_box[i + 3] <= query[i + 3] + tolerance for i in range(3))
    return all(face_box[i] <= query[i + 3] + tolerance and face_box[i + 3] >= query[i] - tolerance for i in range(3))


def query_faces(model, box_mm, mode="intersects", kinds=None, limit=100, tolerance_mm=0.01):
    """
    @brief 找出包围盒与查询盒相交（mode=intersects）或完全落在其中（mode=inside）的面。
    @param box_mm [xmin, ymin, zmin, xmax, ymax, zmax]，零件坐标，毫米。
    @param kinds 只返回这些类型（plane/cylinder/cone/sphere/torus/other）；None 为全部。
    @return dict：matched_count、returned_count、truncated、faces（含 body_index、face_index）。
    """
    query = [float(v) for v in box_mm]
    if len(query) != 6 or any(query[i] > query[i + 3] for i in range(3)):
        raise ValueError("box_mm must be [xmin, ymin, zmin, xmax, ymax, zmax] with min <= max")
    if mode not in ("intersects", "inside"):
        raise ValueError("mode must be 'intersects' or 'inside'")
    wanted = set(kinds or KINDS)
    unknown = wanted - set(KINDS)
    if unknown:
        raise ValueError(f"unknown kinds {sorted(unknown)}")
    bodies = list(get_com_member(model, "GetBodies2", SOLID_BODY, False) or [])
    total = 0
    matches = []
    errors = []
    for body_index, body in enumerate(bodies):
        try:
            faces = list(get_com_member(body, "GetFaces") or [])
        except Exception as exc:
            errors.append(f"body {body_index}: GetFaces: {exc}")
            continue
        for face_index, face in enumerate(faces):
            total += 1
            try:
                face_box = _mm(_vector(get_com_member(face, "GetBox"), 6))
            except Exception as exc:
                errors.append(f"body {body_index} face {face_index}: GetBox: {exc}")
                continue
            if not _box_relation(face_box, query, mode, tolerance_mm):
                continue
            row = describe_face(face)
            if row["type"] not in wanted:
                continue
            matches.append({"body_index": body_index, "face_index": face_index, **row})
    rows = matches[:max(int(limit), 0)]
    return {"status": "ok", "body_count": len(bodies), "total_face_count": total, "matched_count": len(matches),
            "returned_count": len(rows), "truncated": len(matches) > len(rows), "box_mm": query, "mode": mode,
            "faces": rows, "errors": errors,
            "coordinates": "part coordinates, mm; plane normal points out of the material"}
