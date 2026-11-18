"""Pure analytic gate for four observed guide-island loops; no application access."""
from copy import deepcopy
import math


def require(value, message):
    if not value:
        raise ValueError(message)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Finite numeric required')
    return float(value)


def vector(value, size):
    require(type(value) is list and len(value) == size, 'Exact vector size required')
    return [number(x) for x in value]


def close(a, b, tolerance):
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def validate_loop(curves, tolerance):
    require(type(curves) is list and len(curves) == 4, 'Exactly four analytic curves required')
    require(sorted(c.get('kind') for c in curves) == ['ARC', 'ARC', 'LINE', 'LINE'],
            'Exactly two ARC and two LINE records required')
    for index, curve in enumerate(curves):
        a = vector(curve['start_xy_mm'], 2)
        b = vector(curve['end_xy_mm'], 2)
        require(math.dist(a, b) > tolerance, 'Degenerate edge')
        require(close(b, vector(curves[(index + 1) % 4]['start_xy_mm'], 2), tolerance),
                'Ordered loop is not closed')
        if curve['kind'] == 'ARC':
            centre = vector(curve['centre_xy_mm'], 2)
            mid = vector(curve['mid_xy_mm'], 2)
            radius = number(curve['radius_mm'])
            require(radius > 0, 'Positive radius required')
            for point in (a, b, mid):
                require(abs(math.dist(point, centre) - radius) <= tolerance,
                        'Arc samples are not on its declared circle')
            require(math.dist(a, mid) > tolerance and math.dist(b, mid) > tolerance,
                    'Arc midpoint degenerates to an endpoint')


def curve_equal(a, b, tolerance):
    if a['kind'] != b['kind']:
        return False
    ends = ((a['start_xy_mm'], a['end_xy_mm']), (a['end_xy_mm'], a['start_xy_mm']))
    if not any(close(x, b['start_xy_mm'], tolerance) and close(y, b['end_xy_mm'], tolerance)
               for x, y in ends):
        return False
    if a['kind'] == 'LINE':
        return True
    return (close(a['centre_xy_mm'], b['centre_xy_mm'], tolerance)
            and abs(a['radius_mm'] - b['radius_mm']) <= tolerance
            and close(a['mid_xy_mm'], b['mid_xy_mm'], tolerance))


def loop_equal(a, b, tolerance):
    # The observed chain may choose another cyclic start or the opposite direction.
    return all(sum(curve_equal(curve, candidate, tolerance) for candidate in b) == 1 for curve in a)


def analytic_chain(raw, *, expected_z_mm, tolerance_mm, native_to_world):
    """Decode only exact public LINE/ARC observations, using an explicitly supplied transform.

    native_to_world is a pure caller function fixed by independent frame evidence.
    This function never infers a length scale, frame, curve role, or index base.
    """
    require(callable(native_to_world), 'Explicit native-to-world transform required')
    require(type(raw) is dict and raw.get('status') == 'observed', 'Observed native contour required')
    chains = raw.get('chains')
    require(type(chains) is list and len(chains) == 1 and chains[0].get('read_complete') is True,
            'One complete native chain required')
    curves = chains[0].get('curves')
    require(type(curves) is list and len(curves) == 4, 'Four native curves required')

    def point(value):
        world = vector(list(native_to_world(vector(value, 3))), 3)
        require(abs(world[2] - expected_z_mm) <= tolerance_mm, 'Curve is outside pinned world plane')
        return world[:2]

    out = []
    for curve in curves:
        require(curve.get('read_complete') is True, 'Complete native curve required')
        kind = curve.get('curve_type')
        require(type(kind) is int and kind in (0, 1), 'Only exact native LINE/ARC accepted')
        row = dict(kind='LINE' if kind == 0 else 'ARC', start_xy_mm=point(curve['start_native']),
                   end_xy_mm=point(curve['end_native']))
        if kind == 1:
            row.update(centre_xy_mm=point(curve['centre_native']), mid_xy_mm=point(curve['mid_native']))
            # Radius is measured from transformed points; raw native units are not assumed.
            row['radius_mm'] = math.dist(row['centre_xy_mm'], row['start_xy_mm'])
            number(curve['radius_native'])
            normal = vector(curve['normal_native'], 3)
            require(abs(math.sqrt(sum(x*x for x in normal)) - 1) <= 1e-8, 'Unit arc normal required')
        out.append(row)
    validate_loop(out, tolerance_mm)
    return out


def verify_four_loops(expected, observed, *, tolerance_mm):
    """Compare actual analytic loops with pinned native-R25 target curves.

    This proves the requested planar loops only, never vertical depth, stock,
    accessibility, feature association, toolpaths, or production qualification.
    """
    tolerance = number(tolerance_mm)
    require(0 < tolerance <= 0.001, 'Fixed geometric comparison tolerance must be at most0.001mm')
    require(type(expected) is list and type(observed) is list and len(expected) == len(observed) == 4,
            'Exactly four expected and observed islands required')
    for loop in expected + observed:
        validate_loop(loop, tolerance)
    mapping = []
    used = set()
    for index, actual in enumerate(observed):
        matches = [i for i, reference in enumerate(expected) if loop_equal(actual, reference, tolerance)]
        require(len(matches) == 1 and matches[0] not in used, 'Missing, duplicate, shifted, or ambiguous island')
        used.add(matches[0])
        mapping.append(dict(observed_index=index, expected_index=matches[0]))
    return dict(four_planar_islands_verified=True, analytic_line_arc_only=True,
                comparison_tolerance_mm=tolerance, mapping=mapping,
                world_depth_verified=False, frame_inferred=False, stock_verified=False,
                toolpath_verified=False, production_qualified=False)