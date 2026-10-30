"""Pure validation of a truncated-cone cutter and a conservative shank bound.

Native X is radius, Y is zero, Z is distance from physical tip. No coordinate
fit, rotation, scaling, native access or manufacturing tolerance is inferred.
"""
import math

NUMERIC_GUARD_MM = 1e-8
MAX_CHAINS, MAX_CURVES = 8, 64
CONTRACT = {
    'part': '2.FC.06020090.1',
    'length_unit': 'mm',
    'coordinates': {'X': 'radius', 'Y': 'zero', 'Z': 'axial_from_tip', 'scale': 1.0},
    'tip_flat_diameter_mm': 0.6,
    'cutting_diameter_mm': 2.0,
    'cone_height_mm': 0.7,
    'flank_angle_deg': 45.0,
    'shank_diameter_mm': 3.0,
    'overall_length_mm': 40.0,
    'noncutting_profile': 'conservative_cylinder',
}
STAGES = ('after_end_dia', 'after_taper_length', 'after_taper_angle', 'complete')


def require(value, message):
    if not value:
        raise ValueError(message)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Finite numeric value required')
    return float(value)


def validate_contract(contract):
    require(type(contract) is dict and set(contract) == set(CONTRACT), 'Exact profile contract fields required')
    for key, expected in CONTRACT.items():
        value = contract[key]
        if type(expected) is float:
            require(number(value) == expected, 'Unsupported nominal profile contract: ' + key)
        elif type(expected) is dict:
            require(type(value) is dict and set(value) == set(expected), 'Exact coordinate mapping required')
            require(all(type(value[k]) is str and value[k] == expected[k] for k in ('X', 'Y', 'Z'))
                    and number(value['scale']) == 1., 'Explicit X radius/Y zero/Z tip axial/scale1 required')
        else:
            require(type(value) is str and value == expected, 'Unsupported nominal profile contract: ' + key)


def near(a, b):
    return math.dist(a, b) <= NUMERIC_GUARD_MM


def point(raw):
    require(type(raw) in (list, tuple) and len(raw) == 3, 'Native XYZ point required')
    x, y, z = map(number, raw)
    require(abs(y) <= NUMERIC_GUARD_MM and x >= -NUMERIC_GUARD_MM,
            'Profile must use nonnegative X radius, Y0; no rotation or fit')
    return (x, z)


def profile_lines(profile):
    require(type(profile) is dict and profile.get('status') == 'observed', 'Complete observed profile required')
    chains, count = profile.get('chains'), profile.get('declared_chain_count')
    require(type(chains) is list and type(count) is int and count == len(chains)
            and 1 <= count <= MAX_CHAINS, 'Complete bounded profile chains required')
    lines, zero = [], []
    for i, chain in enumerate(chains):
        require(type(chain) is dict, 'Chain record required')
        curves, count = chain.get('curves'), chain.get('declared_curve_count')
        require(type(chain.get('index')) is int and chain['index'] == i
                and chain.get('read_complete') is True and type(curves) is list
                and type(count) is int and count == len(curves) and 0 <= count <= 32,
                'Complete ordered bounded profile curves required')
        for j, curve in enumerate(curves):
            require(type(curve) is dict and type(curve.get('index')) is int and curve['index'] == j
                    and curve.get('read_complete') is True and type(curve.get('curve_type')) is int
                    and curve['curve_type'] == 0, 'Only complete native LINE records supported')
            require(len(lines) + len(zero) < MAX_CURVES, 'Profile curve budget exceeded')
            a, b = point(curve['start_native']), point(curve['end_native'])
            item = dict(chain=i, curve=j, a=a, b=b)
            (zero if near(a, b) else lines).append(item)
    require(lines, 'Nonempty profile required')
    return lines, zero


def interval_on_segment(a, b, start, end):
    dx, dz = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dz * dz
    require(length2 > 0, 'Nonzero expected edge required')
    values = []
    for p in (a, b):
        t = ((p[0] - start[0]) * dx + (p[1] - start[1]) * dz) / length2
        foot = (start[0] + t * dx, start[1] + t * dz)
        if not near(p, foot) or t < -NUMERIC_GUARD_MM / math.sqrt(length2) or t > 1 + NUMERIC_GUARD_MM / math.sqrt(length2):
            return None
        values.append(min(1., max(0., t)))
    return tuple(sorted(values))


def coverage(intervals, *, required, label, length=1.):
    ordered = sorted(intervals)
    numeric = NUMERIC_GUARD_MM / length
    end = None
    for low, high in ordered:
        if end is not None:
            require(low >= end - numeric, 'Overlapping/duplicated profile edge: ' + label)
            if required:
                require(low <= end + numeric, 'Gap in profile edge: ' + label)
        end = high if end is None else max(end, high)
    if required:
        require(bool(ordered) and ordered[0][0] <= numeric and end >= 1 - numeric,
                'Missing full profile edge: ' + label)


def cutting_geometry(tool_lines):
    nose = [s for s in tool_lines if abs(s['a'][1]) <= NUMERIC_GUARD_MM
            and abs(s['b'][1]) <= NUMERIC_GUARD_MM]
    require(nose, 'Physical flat nose at axialZ0 required')
    radius = max(max(s['a'][0], s['b'][0]) for s in nose)
    require(radius > NUMERIC_GUARD_MM, 'Nonzero flat nose radius required')
    coverage([tuple(sorted((s['a'][0] / radius, s['b'][0] / radius))) for s in nose],
             required=True, label='flat nose', length=radius)
    slopes = []
    for s in tool_lines:
        a, b = sorted((s['a'], s['b']), key=lambda p:p[1])
        if b[0] - a[0] > NUMERIC_GUARD_MM and b[1] - a[1] > NUMERIC_GUARD_MM:
            slopes.append((a, b))
    cursor, start, used, first_direction = (radius, 0.), (radius, 0.), set(), None
    for _ in range(len(slopes) + 1):
        candidates = [(i, a, b) for i, (a, b) in enumerate(slopes) if i not in used and near(a, cursor)]
        if not candidates:
            break
        require(len(candidates) == 1, 'Ambiguous or duplicated cone at flat nose')
        i, a, b = candidates[0]
        direction = (b[0] - a[0], b[1] - a[1])
        if first_direction is not None:
            cross = abs(first_direction[0] * direction[1] - first_direction[1] * direction[0])
            if cross > NUMERIC_GUARD_MM * math.hypot(*first_direction):
                break
        else:
            first_direction = direction
        used.add(i)
        cursor = b
    require(used and cursor[1] > NUMERIC_GUARD_MM, 'Connected outward cone from flat nose required')
    return dict(tip_radius_mm=radius, cone_start_rz_mm=list(start),
                cone_end_rz_mm=list(cursor), cone_height_mm=cursor[1],
                maximum_cutting_radius_mm=cursor[0],
                physical_flank_angle_deg=math.degrees(math.atan2(cursor[0] - radius, cursor[1])))


def validate_edge_set(lines, zero, allowed, required, label):
    intervals = {name: [] for name in allowed}
    for segment in lines:
        hits = [(name, interval_on_segment(segment['a'], segment['b'], *edge))
                for name, edge in allowed.items()]
        hits = [(name, interval) for name, interval in hits if interval is not None]
        require(len(hits) == 1, 'Unmatched or ambiguous ' + label + ' profile edge')
        name, interval = hits[0]
        intervals[name].append(interval)
    for name, edge in allowed.items():
        coverage(intervals[name], required=name in required, label=label + ':' + name,
                 length=math.dist(*edge))
    require(len(zero) <= 32, 'Degenerate point budget exceeded')
    for segment in zero:
        require(any(interval_on_segment(segment['a'], segment['b'], *edge) is not None
                    for edge in allowed.values()), 'Unexpected external zero-length profile point')
    return {name: len(values) for name, values in intervals.items()}


def validate_native_profiles(profiles, contract, *, stage='complete'):
    validate_contract(contract)
    require(type(stage) is str and stage in STAGES, 'Exact profile validation stage required')
    require(type(profiles) is dict and set(profiles) == {'tool', 'shank'}, 'Both complete native profiles required')
    tool, tool_zero = profile_lines(profiles['tool'])
    shank, shank_zero = profile_lines(profiles['shank'])
    geometry = cutting_geometry(tool)
    require(abs(geometry['tip_radius_mm'] - .3) <= NUMERIC_GUARD_MM, 'Flat nose diameter must be0.6mm')
    if stage in ('after_taper_length', 'after_taper_angle', 'complete'):
        require(abs(geometry['cone_height_mm'] - .7) <= NUMERIC_GUARD_MM, 'Physical cutting cone height must be0.7mm')
    if stage in ('after_taper_angle', 'complete'):
        require(near(tuple(geometry['cone_end_rz_mm']), (1., .7)),
                'Physical cone must end atR1/Z0.7: maxD2/flank45deg')
    detail = None
    if stage == 'complete':
        tool_allowed = {
            'nose': ((0., 0.), (.3, 0.)), 'cone': ((.3, 0.), (1., .7)),
            'shoulder_or_cut_rear_cap': ((0., .7), (1.5, .7)),
            'body': ((1.5, .7), (1.5, 40.)),
            'rear_cap': ((0., 40.), (1.5, 40.)), 'axis': ((0., 0.), (0., 40.))}
        shank_allowed = {
            'body': ((1.5, .7), (1.5, 40.)),
            'front_cap': ((0., .7), (1.5, .7)),
            'rear_cap': ((0., 40.), (1.5, 40.)), 'axis': ((0., .7), (0., 40.))}
        detail = dict(tool=validate_edge_set(tool, tool_zero, tool_allowed, {'nose', 'cone'}, 'tool'),
                      shank=validate_edge_set(shank, shank_zero, shank_allowed, {'body'}, 'shank'))
    return dict(scope='TRUNCATED_CONE_AND_CONSERVATIVE_SHANK_PROFILE_V1', stage=stage,
                part=contract['part'], complete_qualified=stage == 'complete', geometry=geometry,
                native_numeric_profile_match=True, comparison_guard_mm=NUMERIC_GUARD_MM,
                comparison_guard_is_manufacturing_tolerance=False,
                explicit_coordinates=contract['coordinates'].copy(), explicit_length_unit='mm',
                physical_units_independently_verified=False, factory_profile=False,
                noncutting_profile='conservative_cylinder', noncutting_radius_mm=1.5,
                noncutting_z_interval_mm=[.7, 40.], profile_edge_counts=detail,
                assignment_performed=False, generation_performed=False,
                save_performed=False, production_qualified=False)

