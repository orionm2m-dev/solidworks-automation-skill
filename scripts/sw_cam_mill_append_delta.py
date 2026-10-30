"""Validate a selected additive MILL operation plan without replacing prior work."""
from copy import deepcopy
from scripts.sw_cam_profile_sketch import _same_bodies

OPERATION_KEYS = (
    "operations", "operation_setups", "operation_counts", "operation_count",
    "operation_setup_count",
)

def _integer(value, name):
    if type(value) is not int or not 0 < value < 2**32:
        raise ValueError(name + " must be a positive strict native ID")
    return value

def _inventory(state):
    rows = state["operations"]
    setups = state["operation_setups"]
    if type(rows) is not list or len(rows) > 128:
        raise ValueError("Bounded operation inventory required")
    if type(state["operation_count"]) is not int or state["operation_count"] != len(rows):
        raise ValueError("Operation count mismatch")
    if type(setups) is not list or not 1 <= len(setups) <= 16:
        raise ValueError("Bounded setup inventory required")
    if type(state["operation_setup_count"]) is not int or state["operation_setup_count"] != len(setups) or len(state["operation_counts"]) != len(setups):
        raise ValueError("Setup count mismatch")
    if any(type(n) is not int or not 0 <= n <= 128 for n in state["operation_counts"]):
        raise ValueError("Strict bounded setup counts required")
    if any(type(r.get(k)) is not int for r in rows for k in ("setup_index", "operation_index", "setup_native_id")):
        raise ValueError("Strict native indices and owners required")
    if any(type(s.get(k)) is not int for s in setups for k in ("index", "operation_count")):
        raise ValueError("Strict setup indices and counts required")
    ids = [_integer(r["native_id"], "operation ID") for r in rows]
    sids = [_integer(s["native_id"], "setup ID") for s in setups]
    if len(ids) != len(set(ids)) or len(sids) != len(set(sids)):
        raise ValueError("Duplicate native identity")
    for index, setup in enumerate(setups):
        local = [r for r in rows if r["setup_index"] == index]
        if setup["index"] != index or setup["operation_count"] != len(local):
            raise ValueError("Setup index/count mismatch")
        if state["operation_counts"][index] != len(local):
            raise ValueError("Setup operation count mismatch")
        if [r["operation_index"] for r in local] != list(range(len(local))):
            raise ValueError("Non-contiguous operation order")
        if any(r["setup_native_id"] != setup["native_id"] for r in local):
            raise ValueError("Operation owner mismatch")
    if sum(state["operation_counts"]) != len(rows):
        raise ValueError("Unowned operation")
    return rows, setups

def verify_added_plan(before, after, feature_id, operation_setup_id):
    """Accept new definitions for one previously unplanned feature only.

    Existing operations can shift indices as new definitions are inserted, but
    their relative order, owner, tool, parameters and paths must stay identical.
    This checks the captured fields only, not unobserved operation parameters.
    """
    _integer(feature_id, "feature ID")
    _integer(operation_setup_id, "operation setup ID")
    old, old_setups = _inventory(before)
    new, new_setups = _inventory(after)
    if [(s["index"], s["native_id"]) for s in old_setups] != [
        (s["index"], s["native_id"]) for s in new_setups
    ]:
        raise ValueError("Operation setups changed")
    for previous, observed in zip(old_setups, new_setups):
        protected_setup = deepcopy(previous)
        protected_setup["operation_count"] = observed["operation_count"]
        if protected_setup != observed:
            raise ValueError("Captured setup properties changed")
    if operation_setup_id not in [s["native_id"] for s in old_setups]:
        raise ValueError("Target operation setup missing")
    if any(feature_id in r["linked_feature_ids"] for r in old):
        raise ValueError("Target already has operations; no replay")
    old_by_id = {r["native_id"]: r for r in old}
    retained = [r for r in new if r["native_id"] in old_by_id]
    if [r["native_id"] for r in retained] != [r["native_id"] for r in old]:
        raise ValueError("Existing operations removed or reordered")
    for row in retained:
        previous = deepcopy(old_by_id[row["native_id"]])
        observed = deepcopy(row)
        previous.pop("operation_index")
        observed.pop("operation_index")
        if previous != observed:
            raise ValueError("Existing operation content changed")
    added = [r for r in new if r["native_id"] not in old_by_id]
    if not 1 <= len(added) <= 32:
        raise ValueError("Expected 1..32 new definitions")
    for row in added:
        if (row["setup_native_id"] != operation_setup_id
            or row["linked_feature_ids"] != [feature_id]
            or row["suppressed"] is not False
            or row["toolpath_generated"] is not False
            or row["toolpath_record_counts"] != []
            or row["assigned_tool"].get("native_read_complete") is not True):
            raise ValueError("New definition owner/link/path/tool mismatch")
    protected = deepcopy(before)
    for key in OPERATION_KEYS:
        protected[key] = deepcopy(after[key])
    protected["document"]["needs_save"] = after["document"]["needs_save"]
    old_bodies = before["sw_reference"]["solids"]
    new_bodies = after["sw_reference"]["solids"]
    if not _same_bodies(old_bodies, new_bodies):
        raise ValueError("Solid geometry changed beyond existing mass tolerance")
    # Preserve every other body field exactly; only existing rel=1e-10 mass
    # reread noise is permitted. No snapshot or CAM field is normalized.
    for expected_body, observed_body in zip(protected["sw_reference"]["solids"], new_bodies):
        expected_body["mass_raw"] = deepcopy(observed_body["mass_raw"])
    if protected != after:
        raise ValueError("Unrequested captured context change")
    return deepcopy(added)
