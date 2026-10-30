"""Pure material-only validation for an empty, all-visible MILL qualification.

Reuse the AFR baseline contract, including real visible/all body counts: this
scope intentionally requires every captured solid visible. The inventory reader
and AFR validator must be installed first. No CAM calls or material/recipe
qualification occur here; raw diagnostic snapshots remain untouched.
"""
from copy import deepcopy
from scripts.sw_cam_mill_afr_delta import validate_empty_afr_baseline, _json
from scripts.sw_cam_profile_sketch import _same_bodies


def _material(value):
    if (type(value) is not str or not value.strip() or len(value) > 512 or
            '\x00' in value or value.strip().casefold() in {'unknown', 'unavailable'}):
        raise ValueError('Exact known bounded native material name required')
    return value


def validate_empty_mill_material_baseline(state):
    """Require the existing strict clean/empty/all-visible MILL baseline."""
    summary = validate_empty_afr_baseline(state)
    _material(state['material_raw'])
    return summary


def verify_mill_material_delta(before, after, expected_old_material, expected_new_material):
    """Accept only the exact material change and strict Boolean dirty-flag change.

    The unchanged body boxes remain type-sensitive. Only mass values may differ
    within the existing _same_bodies rel=1e-10, abs=0 rule. No snapshot is mutated.
    Returned readback facts do not qualify stock grade or a cutting recipe.
    """
    old = _material(expected_old_material)
    new = _material(expected_new_material)
    if old == new:
        raise ValueError('A material change is required; no-op is not a write')
    validate_empty_mill_material_baseline(before)
    if before['material_raw'] != old:
        raise ValueError('Prepared old material changed')
    if (type(after) is not dict or type(after.get('document')) is not dict or
            type(after['document'].get('needs_save')) is not bool):
        raise ValueError('Strict post-write document/dirty flag required')
    # The shared validator requires a clean state. Normalize only this allowed
    # Boolean for structural validation; compare the original poststate below.
    validation = deepcopy(after)
    validation['document']['needs_save'] = False
    validate_empty_mill_material_baseline(validation)
    if after['material_raw'] != new:
        raise ValueError('Exact new material readback required')
    b = before['sw_reference']['solids']
    a = after['sw_reference']['solids']
    if not _same_bodies(b, a):
        raise ValueError('Solid geometry changed beyond existing mass tolerance')
    expected = deepcopy(before)
    expected['material_raw'] = new
    expected['document']['needs_save'] = after['document']['needs_save']
    for expected_body, observed_body in zip(expected['sw_reference']['solids'], a):
        expected_body['mass_raw'] = deepcopy(observed_body['mass_raw'])
    if _json(expected) != _json(after):
        raise ValueError('Captured state changed outside the single material field')
    return dict(material_before=old, material_after=new, material_readback_verified=True,
        stock_grade_qualified=False, cutting_recipe_qualified=False)
