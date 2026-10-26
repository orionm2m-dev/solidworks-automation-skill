"""实际端点的纯几何证明；不调用 CAD/COM，不假设绝对坐标系。"""
from __future__ import annotations

import math


class GeometryProofError(ValueError):
    """使用稳定原因码报告输入或几何约束失败。"""

    def __init__(self, code, **details):
        self.code = code
        self.details = details
        super().__init__(code)


def _reject(code, **details):
    raise GeometryProofError(code, **details)


def _number(value, label):
    if type(value) not in (int, float):
        _reject("FINITE_JSON_NUMBER_REQUIRED", field=label)
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _reject("FINITE_JSON_NUMBER_REQUIRED", field=label)
    if not math.isfinite(result):
        _reject("FINITE_JSON_NUMBER_REQUIRED", field=label)
    return result


def _sequence(value, size, label):
    if type(value) not in (list, tuple) or len(value) != size:
        _reject("EXACT_ARRAY_SHAPE_REQUIRED", field=label, size=size)
    return value


def _point(value, label):
    return [_number(v, label) for v in _sequence(value, 3, label)]


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _dot(a, b):
    return math.fsum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]]


def _norm(v):
    result = math.hypot(*v)
    if not math.isfinite(result):
        _reject("COMPUTED_DISTANCE_NONFINITE")
    return result


def _unit(v):
    length = _norm(v)
    if length == 0:
        _reject("DEGENERATE_DIRECTION")
    return [x/length for x in v]


def _tolerance(a, b, absolute, relative):
    return absolute + relative*max(abs(a), abs(b))


def _distance(a, b):
    return _norm(_sub(a, b))


def _rectangle(points, absolute, relative, angular, label):
    vectors = [_sub(points[(i+1) % 4], points[i]) for i in range(4)]
    lengths = [_norm(edge) for edge in vectors]
    if any(length <= absolute for length in lengths):
        _reject("ZERO_OR_UNRESOLVED_EDGE", contour=label)
    directions = [_unit(edge) for edge in vectors]
    if any(abs(_dot(directions[i], directions[(i+1) % 4])) > angular for i in range(4)):
        _reject("RECTANGLE_ORTHOGONALITY_FAILED", contour=label)
    normal = _unit(_cross(directions[0], directions[1]))
    longest = max(lengths)
    linear_tolerance = _tolerance(longest, longest, absolute, relative)
    if any(abs(_dot(_sub(point, points[0]), normal)) > linear_tolerance for point in points[1:]):
        _reject("RECTANGLE_PLANARITY_FAILED", contour=label)
    for i in range(2):
        if (_norm([a+b for a, b in zip(vectors[i], vectors[i+2])]) > linear_tolerance
                or abs(lengths[i] - lengths[i+2]) > _tolerance(lengths[i], lengths[i+2], absolute, relative)):
            _reject("OPPOSITE_EDGES_DIFFER", contour=label)
    pairs = [(lengths[0]+lengths[2])/2, (lengths[1]+lengths[3])/2]
    short, long = sorted(pairs)
    if long - short <= _tolerance(long, short, absolute, relative):
        _reject("ASYMMETRIC_RECTANGLE_REQUIRED", contour=label)
    diagonals = [_distance(points[0], points[2]), _distance(points[1], points[3])]
    expected_diagonal = math.hypot(short, long)
    if any(abs(value-expected_diagonal) > _tolerance(value, expected_diagonal, absolute, relative) for value in diagonals):
        _reject("DIAGONALS_INCONSISTENT", contour=label)
    center = [math.fsum(point[i]/4 for point in points) for i in range(3)]
    return {"points": points, "edge_lengths": lengths, "short": short, "long": long,
        "diagonal": sum(value/2 for value in diagonals), "diagonals": diagonals,
        "normal": normal, "center": center}


def _chain(segments, absolute, relative, angular, label):
    _sequence(segments, 4, label)
    parsed = []
    for index, segment in enumerate(segments):
        _sequence(segment, 2, label + ".segment")
        parsed.append([_point(point, label + ".point") for point in segment])
    lengths = [_distance(start, end) for start, end in parsed]
    if any(length <= absolute for length in lengths):
        _reject("ZERO_OR_UNRESOLVED_EDGE", contour=label)
    closure_tolerance = _tolerance(max(lengths), max(lengths), absolute, relative)
    residuals = [_distance(parsed[i][1], parsed[(i+1) % 4][0]) for i in range(4)]
    if any(value > closure_tolerance for value in residuals):
        _reject("CHAIN_NOT_CLOSED", contour=label, closure_residuals=residuals)
    # Endpoint pairs remain raw evidence; no inferred/metadata-only bottom contour.
    rectangle = _rectangle([segment[0] for segment in parsed], absolute, relative, angular, label)
    rectangle["segments"] = parsed
    rectangle["closure_residuals"] = residuals
    return rectangle


def prove_mill_units_geometry(sketch_rectangle_m, top_segments_native, bottom_segments_native,
        requested_depth_native, *, relative_tolerance=1e-6, sketch_absolute_tolerance_m=1e-10,
        native_absolute_tolerance=1e-8, angular_tolerance=1e-7):
    """核对两个真实矩形轮廓与已知 SW 草图的尺度及深度一致性。

    草图为模型米单位的四个循环顶点；原生轮廓各含四条已验证直线的
    [start_xyz,end_xyz]。允许循环移位或反向；调用方必须先验证原生曲线类型。
    CreateMillFeature2.dDepth 的 ABI 是 DOUBLE；正整数只是当前实验的输入限制。
    返回原始端点、尺度及平面间距；不推断绝对坐标系、全局/进给单位或物理工艺。
    """
    bounds = (("relative_tolerance", relative_tolerance, 1e-3),
        ("sketch_absolute_tolerance_m", sketch_absolute_tolerance_m, 1e-6),
        ("native_absolute_tolerance", native_absolute_tolerance, 1e-3),
        ("angular_tolerance", angular_tolerance, 1e-3))
    settings = {}
    for name, value, maximum in bounds:
        value = _number(value, name)
        if not 0 < value <= maximum:
            _reject("TOLERANCE_OUT_OF_BOUNDS", field=name, maximum=maximum)
        settings[name] = value
    relative = settings["relative_tolerance"]
    sketch_absolute = settings["sketch_absolute_tolerance_m"]
    native_absolute = settings["native_absolute_tolerance"]
    angular = settings["angular_tolerance"]
    if type(requested_depth_native) is not int or not 1 <= requested_depth_native <= 2147483647:
        _reject("STRICT_POSITIVE_INTEGER_QUALIFICATION_DEPTH_REQUIRED")
    points = [_point(point, "sketch_rectangle_m") for point in _sequence(sketch_rectangle_m, 4, "sketch_rectangle_m")]
    sketch = _rectangle(points, sketch_absolute, relative, angular, "sketch")
    top = _chain(top_segments_native, native_absolute, relative, angular, "top")
    bottom = _chain(bottom_segments_native, native_absolute, relative, angular, "bottom")

    dimensions_mm = {key: sketch[key]*1000 for key in ("short", "long", "diagonal")}
    estimates = []
    for label, contour in (("top", top), ("bottom", bottom)):
        for dimension, physical_mm in dimensions_mm.items():
            scale = contour[dimension]/physical_mm
            if not math.isfinite(scale) or scale <= 0:
                _reject("NATIVE_SCALE_NONFINITE")
            estimates.append({"contour": label, "dimension": dimension,
                "observed_native_length": contour[dimension], "known_sketch_length_mm": physical_mm,
                "native_units_per_mm": scale})
    scale = math.fsum(row["native_units_per_mm"]/len(estimates) for row in estimates)
    for row in estimates:
        expected = row["known_sketch_length_mm"]*scale
        tolerance = native_absolute + sketch_absolute*1000*scale + relative*max(abs(expected), abs(row["observed_native_length"]))
        row["native_residual_at_fitted_scale"] = row["observed_native_length"] - expected
        if abs(row["native_residual_at_fitted_scale"]) > tolerance:
            _reject("INCONSISTENT_NATIVE_SCALE_OR_RECTANGLE_DIMENSIONS", measurement=row)

    if _norm(_cross(top["normal"], bottom["normal"])) > angular:
        _reject("TOP_BOTTOM_PLANES_NOT_PARALLEL")
    translation = _sub(bottom["center"], top["center"])
    signed_separation = _dot(translation, top["normal"])
    separation = abs(signed_separation)
    lateral = _norm([translation[i] - signed_separation*top["normal"][i] for i in range(3)])
    linear_tolerance = _tolerance(top["long"], bottom["long"], native_absolute, relative)
    if lateral > linear_tolerance:
        _reject("TOP_BOTTOM_LATERAL_SHIFT", lateral_distance_native=lateral)
    if separation <= native_absolute:
        _reject("DISTINCT_TOP_BOTTOM_PLANES_REQUIRED")

    matches = []
    for orientation in (1, -1):
        for shift in range(4):
            mapping = [(shift + orientation*i) % 4 for i in range(4)]
            residuals = [_norm(_sub(_sub(bottom["points"][mapping[i]], top["points"][i]), translation)) for i in range(4)]
            if max(residuals) <= linear_tolerance:
                matches.append({"bottom_indices_for_top": mapping, "maximum_translation_residual_native": max(residuals)})
    if len(matches) != 1:
        _reject("TOP_BOTTOM_NOT_UNIQUE_NORMAL_TRANSLATION", matching_correspondences=len(matches))
    depth_error = separation-requested_depth_native
    depth_tolerance = _tolerance(separation, requested_depth_native, native_absolute, relative)
    if abs(depth_error) > depth_tolerance:
        _reject("MEASURED_SEPARATION_DIFFERS_FROM_REQUESTED_DEPTH", measured_separation_native=separation,
            requested_depth_native=requested_depth_native, residual_native=depth_error)

    def public_rectangle(value):
        return {key: value[key] for key in ("points", "edge_lengths", "diagonals", "short", "long")}
    return {"status": "ok", "proof_scope": "observed_line_endpoint_rectangles_only",
        "native_units_per_mm": scale, "scale_estimates": estimates,
        "independent_in_plane_dimensions": 2, "diagonal_role": "redundant_geometric_cross_check",
        "uniform_native_scale_is_measured_not_assumed_one": True,
        "requested_depth_native": requested_depth_native, "measured_separation_native": separation,
        "depth_residual_native": depth_error, "measured_separation_mm_using_in_plane_scale": separation/scale,
        "depth_matches_requested_native": True, "top_bottom_normal_translation_verified": True,
        "correspondence": matches[0], "lateral_separation_native": lateral,
        "sketch_rectangle_m": public_rectangle(sketch),
        "top_rectangle_native": public_rectangle(top), "bottom_rectangle_native": public_rectangle(bottom),
        "native_segments_raw": {"top": top["segments"], "bottom": bottom["segments"]},
        "closure_residuals_native": {"top": top["closure_residuals"], "bottom": bottom["closure_residuals"]},
        "tolerances": settings, "angular_tolerance_interpretation": "unit_direction_dot_or_cross_residual",
        "native_curve_line_types_verified": False, "native_execution_verified": False,
        "coordinate_provenance_verified": False, "absolute_native_frame": "unknown",
        "depth_mm_uses_in_plane_scale": True, "depth_axis_metric_independently_verified": False,
        "global_native_units_verified": False, "feed_units_verified": False,
        "qualification_complete": False, "may_continue": False}
