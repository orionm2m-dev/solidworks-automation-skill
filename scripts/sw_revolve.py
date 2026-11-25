"""@brief 按轮廓点旋转：同一草图内画闭合轮廓与中心线，检查轮廓不跨越旋转轴，再 FeatureRevolve2。"""
from __future__ import annotations

import math

try:
    from .sw_part import _ensure_sketch_selected, profile_arc_center
except ImportError:
    from sw_part import _ensure_sketch_selected, profile_arc_center


def arc_points(x1, y1, x2, y2, bulge, samples=16):
    """@brief 弧段上的采样点（含端点），bulge = tan(θ/4)，>0 逆时针。"""
    cx, cy = profile_arc_center(x1, y1, x2, y2, bulge)
    radius = math.hypot(x1 - cx, y1 - cy)
    start = math.atan2(y1 - cy, x1 - cx)
    sweep = 4.0 * math.atan(bulge)
    return [(cx + radius * math.cos(start + sweep * i / samples), cy + radius * math.sin(start + sweep * i / samples))
            for i in range(samples + 1)]


def profile_points(vertices, samples=16):
    """@brief 轮廓的全部检查点：顶点与每段圆弧上的采样点，附带所属顶点序号。"""
    points = []
    count = len(vertices)
    for index, (x1, y1, bulge) in enumerate(vertices):
        x2, y2, _next = vertices[(index + 1) % count]
        points.append((index, x1, y1))
        if bulge:
            points.extend((index, x, y) for x, y in arc_points(x1, y1, x2, y2, bulge, samples)[1:-1])
    return points


def axis_segment(axis, vertices, axis_points=None, margin=0.005):
    """
    @brief 旋转轴（草图坐标，米）。sketch_x / sketch_y 为过草图原点的坐标轴，长度覆盖轮廓投影并留余量。
    @return ((x1, y1), (x2, y2))
    """
    xs = [x for _i, x, _y in profile_points(vertices)]
    ys = [y for _i, _x, y in profile_points(vertices)]
    if axis == "sketch_x":
        return (min(xs) - margin, 0.0), (max(xs) + margin, 0.0)
    if axis == "sketch_y":
        return (0.0, min(ys) - margin), (0.0, max(ys) + margin)
    if axis == "points":
        if not axis_points or len(axis_points) != 2:
            raise ValueError("axis='points' requires axis_points_mm with two points")
        (x1, y1), (x2, y2) = axis_points
        if math.hypot(x2 - x1, y2 - y1) < 1e-6:
            raise ValueError("axis_points_mm must be two different points")
        return (float(x1), float(y1)), (float(x2), float(y2))
    raise ValueError(f"unknown axis {axis!r}")


def check_profile_side(vertices, p1, p2, tolerance=1e-7):
    """
    @brief 轮廓必须整体位于旋转轴一侧（可贴在轴上）。
    @return +1 或 -1（轮廓所在侧）；
    @raise ValueError 指出跨到另一侧的顶点序号，或轮廓全部落在轴上。
    """
    (x1, y1), (x2, y2) = p1, p2
    length = math.hypot(x2 - x1, y2 - y1)
    side = 0
    first = None
    for index, x, y in profile_points(vertices):
        distance = ((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) / length
        if abs(distance) <= tolerance:
            continue
        current = 1 if distance > 0 else -1
        if side == 0:
            side, first = current, index
        elif current != side:
            raise ValueError(f"profile crosses the revolve axis near profile_points_mm[{index}] "
                             f"(profile_points_mm[{first}] is on the other side)")
    if side == 0:
        raise ValueError("profile lies on the revolve axis")
    return side


def revolve_feature(model, sketch_ref, angle_rad, cut=False, merge=True):
    """
    @brief FeatureRevolve2，单方向给定角度；草图内唯一的中心线即旋转轴。
    @return IFeature 或 None。
    """
    _ensure_sketch_selected(model, sketch_ref)
    return model.FeatureManager.FeatureRevolve2(
        True,               # SingleDir
        True,               # IsSolid
        False,              # IsThin
        bool(cut),          # IsCut
        False,              # ReverseDir
        False,              # BothDirectionUpToSameEntity
        0, 0,               # Dir1Type, Dir2Type: swEndCondBlind
        float(angle_rad), 0.0,
        False, False,       # OffsetReverse1/2
        0.0, 0.0,           # OffsetDistance1/2
        0, 0.0, 0.0,        # ThinType, ThinThickness1/2
        True if cut else bool(merge),
        True, True,         # UseFeatScope, UseAutoSelect
    )
