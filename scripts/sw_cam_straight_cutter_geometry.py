"""Nominal straight flat-end cutter profile validation, without physical claims."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_shared_cutter_geometry import FIELDS, INTEGER_FIELDS, values, close, number, TOL
from scripts.sw_cam_shared_holder_geometry import verify_holder_profile


def validate_target(target):
    if type(target) is not dict or set(target) != {f[0] for f in FIELDS}:
        raise ValueError("Exactly ten declared cutter fields required")
    for name, value in target.items():
        if name in INTEGER_FIELDS:
            if type(value) is not int: raise ValueError("Strict integer field required")
        elif number(value) <= 0: raise ValueError("Positive dimension required")
    if target['MillToolShankType'] != 0 or not 1 <= target['NoOfFlutes'] <= 32:
        raise ValueError("Bounded straight shank required")
    if not (close(target['CutDiameter'], target['ShoulderDia'])
            and close(target['CutDiameter'], target['ShankDia'])
            and close(target['EffCutlength'], target['ShoulderLength'])
            and close(target['EffCutlength'], target['ShankLength'])
            and 0 < target['EffCutlength'] < target['Protrusion'] < target['OverallLen']):
        raise ValueError("Equal diameter/no neck and explicit inactive L6 normalization required")
    return dict(target)


def verify_profile(profile, target, *, shank_only=False):
    validate_target(target)
    radius = target['CutDiameter'] / 2
    low = target['EffCutlength'] if shank_only else 0
    high = target['OverallLen']
    chains = profile.get('chains')
    if profile.get('status') != 'observed' or type(chains) is not list or not 1 <= len(chains) <= 16 or profile.get('declared_chain_count') != len(chains):
        raise ValueError("Complete bounded observed profile required")
    intervals = []; count = 0
    def point(raw):
        if type(raw) not in (list, tuple) or len(raw) != 3: raise ValueError("Exact XYZ required")
        x, y, z = map(number, raw)
        if abs(y) > TOL or x < -TOL or x > radius + TOL or z < low-TOL or z > high+TOL:
            raise ValueError("Profile exceeds nominal straight envelope")
        return x, z
    for chain in chains:
        curves = chain.get('curves')
        if chain.get('read_complete') is not True or type(curves) is not list or chain.get('declared_curve_count') != len(curves):
            raise ValueError("Incomplete curve chain")
        for curve in curves:
            count += 1
            if count > 256 or curve.get('read_complete') is not True or type(curve.get('curve_type')) is not int or curve['curve_type'] != 0:
                raise ValueError("Only bounded line profiles accepted")
            a, b = point(curve['start_native']), point(curve['end_native'])
            if close(a[1], b[1]):
                if not any(close(a[1], z) for z in (low, target['EffCutlength'], high)):
                    raise ValueError("Unexpected radial seam")
                continue
            if not close(a[0], radius) or not close(b[0], radius):
                raise ValueError("Chamfer, neck or tapered section differs from nominal square end")
            intervals.append(tuple(sorted((a[1], b[1]))))
    cursor = low
    for start, end in sorted(intervals):
        if start > cursor+TOL: raise ValueError("Gap in longitudinal silhouette")
        cursor = max(cursor, end)
    if cursor < high-TOL: raise ValueError("Incomplete silhouette extent")
    return dict(status='PASS', curve_count=count, shank_only=shank_only, raw_tolerance=TOL,
                physical_microedge_verified=False, physical_tool_identity_verified=False)


def verify_full_delta(before, after, target, holder_recipe):
    validate_target(target)
    for full in (before, after):
        if full.get('geometry_read_complete') is not True or full.get('profile_complete') is not True:
            raise ValueError("Complete tool, holder and profile capture required")
        mill = full['mill_tool']
        if full['tool_type_raw'] != 1 or mill['type_raw'] != 1 or mill['subtype_raw'] != 3 or not close(mill['end_radius_native'], 0):
            raise ValueError("Nominal flat-end/BOTH classification must remain unchanged")
    actual_values = values(after)
    for name, wanted in target.items():
        actual = actual_values[name]
        if name in INTEGER_FIELDS:
            if type(actual) is not int or actual != wanted: raise ValueError("Integral target mismatch")
        elif not close(actual, wanted): raise ValueError("Scalar target mismatch")
    if not close(after['holder']['holder_protrusion_native'], target['Protrusion']):
        raise ValueError("Holder protrusion coupling mismatch")
    if str(Path(after['holder']['name'])).casefold() != str(Path(holder_recipe['file_path'])).casefold():
        raise ValueError("Pinned custom holder reference mismatch")
    proofs = [verify_profile(after['profiles']['tool'], target), verify_profile(after['profiles']['shank'], target, shank_only=True)]
    holder_proof = verify_holder_profile(after['profiles']['holder'], holder_recipe, target['Protrusion'])
    expected = deepcopy(before)
    for name, section, key in FIELDS:
        (expected[section] if section else expected)[key] = (after[section] if section else after)[key]
    expected['holder']['holder_protrusion_native'] = after['holder']['holder_protrusion_native']
    expected['holder']['name'] = after['holder']['name']
    expected['profiles'] = after['profiles']; expected['profile_budget'] = after['profile_budget']
    if expected != after: raise ValueError("Undeclared tool/holder metadata or scalar change")
    return dict(nominal_cutter_verified=True, profile_comparisons=proofs, holder_profile_comparison=holder_proof,
                L6_inactive_normalization=True, physical_collet_seating_verified=False,
                physical_microedge_verified=False, production_qualified=False)
