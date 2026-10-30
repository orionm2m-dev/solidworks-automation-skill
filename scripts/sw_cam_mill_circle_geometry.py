"""Pure local geometry proof for observed circular MILL contours.

No CAD calls or assumed absolute coordinate frame. Raw sense and direction
integers are retained without assigning cutting-direction semantics.
"""
from __future__ import annotations
import math

TAU = 2.0 * math.pi


class GeometryProofError(ValueError):
    """A stable failure code with bounded geometric evidence."""
    def __init__(self, code, **details):
        self.code, self.details = code, details
        super().__init__(code)


def _reject(code, **details):
    raise GeometryProofError(code, **details)


def _number(value, label):
    if type(value) not in (int, float):
        _reject("FINITE_JSON_NUMBER_REQUIRED", field=label)
    try:
        value = float(value)
    except (OverflowError, ValueError):
        _reject("FINITE_JSON_NUMBER_REQUIRED", field=label)
    if not math.isfinite(value):
        _reject("FINITE_JSON_NUMBER_REQUIRED", field=label)
    return value


def _point(value, label):
    if type(value) not in (list, tuple) or len(value) != 3:
        _reject("EXACT_ARRAY_SHAPE_REQUIRED", field=label)
    return [_number(x, label) for x in value]


def _sub(a, b):
    return [x-y for x, y in zip(a, b)]


def _dot(a, b):
    try:
        value = math.fsum(x*y for x, y in zip(a, b))
    except (ValueError, OverflowError):
        _reject("COMPUTED_VALUE_NONFINITE")
    if not math.isfinite(value):
        _reject("COMPUTED_VALUE_NONFINITE")
    return value


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _norm(a):
    value = math.hypot(*a)
    if not math.isfinite(value):
        _reject("COMPUTED_VALUE_NONFINITE")
    return value


def _unit(a):
    length = _norm(a)
    if length == 0:
        _reject("DEGENERATE_DIRECTION")
    return [x/length for x in a]


def _distance(a, b):
    return _norm(_sub(a, b))


def _angle_distance(a, b):
    return abs((a-b+math.pi) % TAU - math.pi)


def _long(value, label):
    if type(value) is not int or not -(2**31) <= value < 2**31:
        _reject("STRICT_NATIVE_LONG_REQUIRED", field=label)
    return value


def _basis(normal):
    seed = [0.0, 0.0, 0.0]
    seed[min(range(3), key=lambda i: abs(normal[i]))] = 1.0
    u = _unit(_cross(normal, seed))
    return u, _cross(normal, u)


def _circle_chain(rows, absolute, relative, angular, label):
    if type(rows) not in (list, tuple) or not 1 <= len(rows) <= 64:
        _reject("BOUNDED_NONEMPTY_CURVE_CHAIN_REQUIRED", contour=label)
    parsed = []
    for index, row in enumerate(rows):
        if type(row) is not dict:
            _reject("CURVE_RECORD_REQUIRED", contour=label, index=index)
        kind = row.get("curve_type")
        if type(kind) is not int or kind not in (1, 2):
            _reject("SUPPORTED_CIRCULAR_CURVE_TYPE_REQUIRED", contour=label, index=index)
        try:
            center = _point(row["centre_native"], label+".centre_native")
            radius = _number(row["radius_native"], label+".radius_native")
            normal_raw = _point(row["normal_native"], label+".normal_native")
            normal = _unit(normal_raw)
            if radius <= absolute:
                _reject("POSITIVE_RESOLVED_RADIUS_REQUIRED", contour=label)
            item = {"curve_type":kind, "centre_native":center,
                    "radius_native":radius, "normal_native":normal_raw, "normal_unit":normal}
            if kind == 2:
                item["direction_raw"] = _long(row["direction_raw"], label+".direction_raw")
            else:
                item["sense_raw"] = _long(row["sense_raw"], label+".sense_raw")
                for field in ("start_native", "end_native", "mid_native"):
                    item[field] = _point(row[field], label+"."+field)
        except KeyError as exc:
            _reject("MISSING_CURVE_FIELD", contour=label, field=str(exc.args[0]))
        parsed.append(item)
    if any(p["curve_type"] == 2 for p in parsed):
        if len(parsed) != 1 or parsed[0]["curve_type"] != 2:
            _reject("ONE_FULL_CIRCLE_OR_ARC_CHAIN_REQUIRED", contour=label)
        p = parsed[0]
        return {"representation":"explicit_circle_type_2", "center":p["centre_native"],
                "radius":p["radius_native"], "normal":p["normal_unit"],
                "angular_coverage":TAU, "curve_count":1, "curves":parsed,
                "direction_semantics_verified":False}
    if len(parsed) < 2:
        _reject("AMBIGUOUS_SINGLE_ARC_NOT_FULL_CIRCLE", contour=label)
    center, radius, normal = (parsed[0][k] for k in ("centre_native","radius_native","normal_unit"))
    linear = absolute + relative*radius
    angle_tol = angular + 2.0*linear/radius
    if angle_tol >= 0.01:
        _reject("ANGULAR_RESOLUTION_INSUFFICIENT", contour=label)
    u, v = _basis(normal)
    spans, intervals, endpoints = [], [], []
    for index, p in enumerate(parsed):
        if _distance(p["centre_native"], center) > linear:
            _reject("ARC_CENTRES_DIFFER", contour=label, index=index)
        if abs(p["radius_native"]-radius) > linear:
            _reject("ARC_RADII_DIFFER", contour=label, index=index)
        if _norm(_cross(p["normal_unit"], normal)) > angular:
            _reject("ARC_NORMALS_NOT_PARALLEL", contour=label, index=index)
        angles = []
        for field in ("start_native", "end_native", "mid_native"):
            delta = _sub(p[field], center)
            if abs(_norm(delta)-radius) > linear:
                _reject("ARC_POINT_OFF_CIRCLE", contour=label, index=index, field=field)
            if abs(_dot(delta, normal)) > linear:
                _reject("ARC_POINT_OFF_PLANE", contour=label, index=index, field=field)
            angles.append(math.atan2(_dot(delta,v),_dot(delta,u)) % TAU)
        if _distance(p["start_native"], p["end_native"]) <= linear:
            _reject("COINCIDENT_ARC_ENDPOINTS_AMBIGUOUS", contour=label, index=index)
        start, end, mid = angles
        ccw = (end-start) % TAU
        choices = []
        if _angle_distance(mid, start+ccw/2) <= angle_tol:
            choices.append((start, ccw, 1))
        if _angle_distance(mid, start-(TAU-ccw)/2) <= angle_tol:
            choices.append((end, TAU-ccw, -1))
        if len(choices) != 1:
            _reject("ARC_MIDPOINT_DOES_NOT_SELECT_UNIQUE_SPAN", contour=label, index=index)
        begin, span, sign = choices[0]
        if min(span, TAU-span) <= angle_tol:
            _reject("ARC_SPAN_UNRESOLVED", contour=label, index=index)
        spans.append({"index":index,"span_radians":span,"witness_orientation":sign})
        end_angle = begin+span
        if end_angle <= TAU:
            intervals.append((begin,end_angle,index))
        else:
            intervals.extend([(begin,TAU,index),(0.0,end_angle-TAU,index)])
        endpoints.extend([(index,0,p["start_native"]),(index,1,p["end_native"])])
    # Every endpoint must join exactly one endpoint of a different primitive.
    adjacency = [set() for _ in parsed]
    maximum_join = 0.0
    for i,(curve,side,point) in enumerate(endpoints):
        matches = [(other,_distance(point,q)) for j,(other,other_side,q) in enumerate(endpoints)
                   if i != j and _distance(point,q) <= linear]
        if len(matches) != 1 or matches[0][0] == curve:
            _reject("ARC_CHAIN_JOIN_NOT_UNIQUE", contour=label, endpoint=i, matches=len(matches))
        adjacency[curve].add(matches[0][0]);maximum_join=max(maximum_join,matches[0][1])
    visited, pending = set(), [0]
    while pending:
        index=pending.pop()
        if index not in visited:
            visited.add(index);pending.extend(adjacency[index]-visited)
    if len(visited) != len(parsed):
        _reject("ARC_CHAIN_DISCONNECTED", contour=label)
    intervals.sort()
    cursor=0.0
    for start,end,index in intervals:
        if start > cursor+angle_tol:
            _reject("ARC_COVERAGE_GAP", contour=label, index=index)
        if start < cursor-angle_tol:
            _reject("ARC_COVERAGE_OVERLAP", contour=label, index=index)
        cursor=max(cursor,end)
    if abs(cursor-TAU) > angle_tol or abs(math.fsum(s["span_radians"] for s in spans)-TAU) > len(parsed)*angle_tol:
        _reject("ARC_COVERAGE_NOT_ONE_FULL_TURN", contour=label)
    return {"representation":"geometrically_complete_arc_chain", "center":center,
            "radius":radius,"normal":normal,"angular_coverage":math.fsum(s["span_radians"] for s in spans),
            "curve_count":len(parsed),"curves":parsed,"arc_spans":spans,
            "maximum_endpoint_join_residual":maximum_join,
            "angular_coverage_tolerance":angle_tol,"direction_semantics_verified":False}


def prove_mill_circle_geometry(sketch_circle_m, top_curves_native, bottom_curves_native,
        requested_depth_native, axis_native, *, relative_tolerance=1e-6,
        sketch_absolute_tolerance_m=1e-10, native_absolute_tolerance=1e-8,
        angular_tolerance=1e-7):
    """Prove local circular shape and independently report axial separation.

    sketch_circle_m: center_model_m, radius_m, normal_model.
    Native rows: curve_type, centre_native, radius_native, normal_native and
    direction_raw (CIRCLE2), or start/end/mid_native and sense_raw (ARC1).
    A circle cannot establish absolute position or in-plane frame orientation.
    Coincident top/bottom planes prove a contour only, never physical depth.
    """
    settings={}
    for name,value,maximum in (
        ("relative_tolerance",relative_tolerance,1e-3),
        ("sketch_absolute_tolerance_m",sketch_absolute_tolerance_m,1e-6),
        ("native_absolute_tolerance",native_absolute_tolerance,1e-3),
        ("angular_tolerance",angular_tolerance,1e-3)):
        value=_number(value,name)
        if not 0 < value <= maximum:
            _reject("TOLERANCE_OUT_OF_BOUNDS",field=name)
        settings[name]=value
    relative,absolute,angular=(settings[k] for k in ("relative_tolerance","native_absolute_tolerance","angular_tolerance"))
    requested=_number(requested_depth_native,"requested_depth_native")
    if requested <= 0:
        _reject("POSITIVE_NATIVE_DEPTH_REQUIRED")
    if type(sketch_circle_m) is not dict:
        _reject("SKETCH_CIRCLE_RECORD_REQUIRED")
    try:
        center_m=_point(sketch_circle_m["center_model_m"],"sketch.center_model_m")
        radius_m=_number(sketch_circle_m["radius_m"],"sketch.radius_m")
        sketch_normal=_unit(_point(sketch_circle_m["normal_model"],"sketch.normal_model"))
    except KeyError as exc:
        _reject("MISSING_SKETCH_FIELD",field=str(exc.args[0]))
    if radius_m <= settings["sketch_absolute_tolerance_m"]:
        _reject("POSITIVE_RESOLVED_SKETCH_RADIUS_REQUIRED")
    radius_mm=radius_m*1000.0
    if not math.isfinite(radius_mm):
        _reject("COMPUTED_VALUE_NONFINITE")
    axis=_unit(_point(axis_native,"axis_native"))
    top=_circle_chain(top_curves_native,absolute,relative,angular,"top")
    bottom=_circle_chain(bottom_curves_native,absolute,relative,angular,"bottom")
    linear=absolute+relative*max(top["radius"],bottom["radius"])
    if abs(top["radius"]-bottom["radius"]) > linear:
        _reject("TOP_BOTTOM_RADII_DIFFER")
    for label,circle in (("top",top),("bottom",bottom)):
        if _norm(_cross(circle["normal"],axis)) > angular:
            _reject("CONTOUR_NORMAL_NOT_PARALLEL_TO_FEATURE_AXIS",contour=label)
    delta=_sub(bottom["center"],top["center"]);signed=_dot(delta,axis)
    lateral=_norm([delta[i]-signed*axis[i] for i in range(3)])
    if lateral > linear:
        _reject("TOP_BOTTOM_LATERAL_SHIFT",lateral_distance_native=lateral)
    separation=abs(signed);coplanar=separation <= absolute
    depth_tolerance=absolute+relative*max(separation,requested)
    if not coplanar and abs(separation-requested) > depth_tolerance:
        _reject("MEASURED_SEPARATION_DIFFERS_FROM_REQUESTED_DEPTH",
                measured_separation_native=separation,requested_depth_native=requested)
    scale=math.fsum([top["radius"]/2,bottom["radius"]/2])/radius_mm
    if not math.isfinite(scale) or scale <= 0:
        _reject("NATIVE_SCALE_NONFINITE")
    sketch_native=[x*1000*scale for x in center_m]
    if not all(math.isfinite(x) for x in sketch_native):
        _reject("COMPUTED_VALUE_NONFINITE")
    aligned_residual=_sub(top["center"],sketch_native)
    estimates=[{"contour":name,"observed_native_radius":circle["radius"],
                "known_sketch_radius_mm":radius_mm,"native_units_per_mm":circle["radius"]/radius_mm}
               for name,circle in (("top",top),("bottom",bottom))]
    return {"status":"review_required" if coplanar else "ok",
        "proof_scope":"local_observed_circle_geometry_only","contour_verified":True,
        "relation":"coplanar" if coplanar else "depth_separated",
        "native_units_per_mm":scale,"scale_estimates":estimates,
        "independent_in_plane_dimensions":1,"uniform_native_scale_is_measured_not_assumed_one":True,
        "sketch_circle_m":{"center_model_m":center_m,"radius_m":radius_m,"normal_model":sketch_normal},
        "top_circle_native":top,"bottom_circle_native":bottom,"axis_native_normalized":axis,
        "requested_depth_native":requested,"measured_separation_native":separation,
        "signed_separation_along_feature_axis_native":signed,"lateral_separation_native":lateral,
        "depth_residual_native":separation-requested,
        "depth_matches_requested_native":not coplanar,
        "measured_separation_mm_using_radial_scale":separation/scale,
        "top_bottom_coaxial_verified":True,
        "aligned_axes_center_residual_native":aligned_residual,
        "aligned_axes_center_residual_norm_native":_norm(aligned_residual),
        "aligned_axes_center_comparison_is_frame_proof":False,
        "sketch_native_normal_parallel_if_axes_aligned":_norm(_cross(sketch_normal,top["normal"])) <= angular,
        "coordinate_provenance_verified":False,"absolute_frame_verified":False,"absolute_native_frame":"unknown",
        "circle_in_plane_rotation_and_handedness_observable":False,
        "depth_axis_metric_independently_verified":False,"physical_depth_verified":False,
        "native_execution_verified":False,"direction_semantics_verified":False,
        "global_native_units_verified":False,"feed_units_verified":False,
        "tolerances":settings,"tolerance_scope":"Numerical proof guards, not manufacturing tolerances",
        "qualification_complete":False,"production_qualified":False,"may_continue":False}
