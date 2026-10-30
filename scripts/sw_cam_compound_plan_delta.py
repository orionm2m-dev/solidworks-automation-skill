"""Pure scoped validation for replacing one compound feature operation plan."""
from copy import deepcopy
from scripts.sw_cam_mill_append_delta import _inventory, OPERATION_KEYS
from scripts.sw_cam_profile_sketch import _same_bodies
from scripts.sw_cam_mill_stock_export_evidence import _require

def same_observed_context(before, after, *, allow_dirty=False, allow_saved_source=False):
    expected = deepcopy(before)
    if allow_dirty:
        _require(type(after["document"].get("needs_save")) is bool, "Strict dirty flag required")
        expected["document"]["needs_save"] = after["document"]["needs_save"]
    if allow_saved_source:
        expected["saved_file_sha256"] = after["saved_file_sha256"]
    a, b = expected["sw_reference"]["solids"], after["sw_reference"]["solids"]
    if not _same_bodies(a, b):
        return False
    for left, right in zip(a, b):
        left["mass_raw"] = deepcopy(right["mass_raw"])
    return expected == after

def target_operations(state, feature_id, setup_id):
    operations, _ = _inventory(state)
    rows = [r for r in operations if feature_id in r["linked_feature_ids"]]
    _require(1 <= len(rows) <= 32, "Bounded nonempty target operation membership required")
    for r in rows:
        _require(r["linked_feature_ids"] == [feature_id] and r["setup_native_id"] == setup_id
            and r["suppressed"] is False and r["toolpath_generated"] is False
            and r["toolpath_record_counts"] == []
            and r["assigned_tool"].get("native_read_complete") is True
            and r["assigned_tool"].get("is_mill_tool") is True,
            "Exact unsuppressed target definitions with complete generic tools and no paths required")
    return rows

def verify_replaced_plan(before, after, feature_id, setup_id):
    old, old_setups = _inventory(before)
    new, new_setups = _inventory(after)
    target_operations(before, feature_id, setup_id)
    target = target_operations(after, feature_id, setup_id)
    types = [r["mill_operation_type"] for r in target]
    _require(all(type(v) is int and v in (0, 1) for v in types) and set(types) == {0, 1},
             "Replacement must contain rough0 and finish1 only, with both present")
    _require(len(old_setups) == len(new_setups), "Operation setups changed")
    for previous, current in zip(old_setups, new_setups):
        expected = deepcopy(previous)
        expected["operation_count"] = current["operation_count"]
        _require(expected == current, "Operation setup identity/properties changed")
    protected_old = [r for r in old if feature_id not in r["linked_feature_ids"]]
    protected_new = [r for r in new if feature_id not in r["linked_feature_ids"]]
    _require([r["native_id"] for r in protected_old] == [r["native_id"] for r in protected_new],
             "Non-target operation membership/order changed")
    for previous, current in zip(protected_old, protected_new):
        a, b = deepcopy(previous), deepcopy(current)
        a.pop("operation_index"); b.pop("operation_index")
        _require(a == b, "Non-target operation/tool/path changed")
    protected_ids = {r["native_id"] for r in protected_old}
    _require(not protected_ids.intersection(r["native_id"] for r in target),
             "Target operation replaced a protected identity")
    expected = deepcopy(before)
    for key in OPERATION_KEYS:
        expected[key] = deepcopy(after[key])
    _require(same_observed_context(expected, after, allow_dirty=True),
             "Unrequested feature/stock/source/context change")
    return deepcopy(target)

def verify_strategy_details(before, after, attribute_id, name):
    _require(type(attribute_id) is int and attribute_id > 0, "Positive TechDB strategy ID required")
    expected = deepcopy(before)
    strategy = expected["strategy"]["compound_strategy"]
    strategy.update(attribute_id=attribute_id, attribute_name=name, active_attribute_name=name)
    _require(expected == after, "Unexpected target metadata or protected full-tool change")
    return True

def target_tool_metadata_verified(observations, target_rows):
    before=observations.get("after",{})
    after=observations.get("saved",{})
    details=after.get("selected_tool_details",{})
    if (before != after or details.get("metadata_read_complete") is not True
        or details.get("profile_complete") is not True
        or details.get("generic_operation_context_unchanged") is not True
        or details.get("canonical_state_changed") is not False):
        return False
    items=details.get("items")
    if type(items) is not list or [r.get("operation_native_id") for r in items] != [r["native_id"] for r in target_rows]:
        return False
    for observation, operation in zip(items,target_rows):
        full=observation.get("full_tool",{})
        if (observation.get("tool_metadata_complete") is not True or observation.get("status") != "observed"
            or observation.get("mill_operation_type") != operation["mill_operation_type"]
            or full.get("tool_native_id") != operation["assigned_tool"]["native_id"]
            or full.get("geometry_read_complete") is not True or full.get("profile_complete") is not True):
            return False
    return True
