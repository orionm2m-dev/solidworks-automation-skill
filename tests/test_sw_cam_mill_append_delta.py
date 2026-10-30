from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sw_cam_mill_append_delta import verify_added_plan

def sample():
    before = json.loads((Path(__file__).parent / "saved_plan_fixture.json").read_text(encoding='utf-8'))
    after = deepcopy(before)
    row = deepcopy(before["operations"][0])
    row.update(native_id=150, linked_feature_ids=[64], operation_index=0)
    row["assigned_tool"]["native_id"] = 151
    after["operations"].insert(0, row)
    for i, operation in enumerate(after["operations"]):
        operation["operation_index"] = i
    after["operation_count"] = 3
    after["operation_counts"][0] = 3
    after["operation_setups"][0]["operation_count"] = 3
    return before, after

def test_added_definition_preserves_prior_work():
    before, after = sample()
    assert [r["native_id"] for r in verify_added_plan(before, after, 64, 93)] == [150]
    assert before["operation_count"] == 2

@pytest.mark.parametrize("fault", [
    "old_tool", "old_path", "old_owner", "old_suppression", "remove_old", "reorder_old",
    "duplicate_id", "foreign_target", "new_path", "new_suppressed", "missing_tool",
    "stock", "feature", "source", "count", "setup_count", "index", "existing_target",
    "no_new", "foreign_setup",
])
def test_rejects_unrequested_changes(fault):
    b, a = sample()
    if fault == "old_tool": a["operations"][1]["assigned_tool"]["cut_diameter_native"] = 2
    elif fault == "old_path": a["operations"][1]["toolpath_generated"] = True
    elif fault == "old_owner": a["operations"][1]["setup_native_id"] = 94
    elif fault == "old_suppression": a["operations"][1]["suppressed"] = True
    elif fault == "remove_old": a["operations"].pop()
    elif fault == "reorder_old":
        a["operations"][1], a["operations"][2] = a["operations"][2], a["operations"][1]
        for i,r in enumerate(a["operations"]): r["operation_index"] = i
    elif fault == "duplicate_id": a["operations"][0]["native_id"] = 143
    elif fault == "foreign_target": a["operations"][0]["linked_feature_ids"] = [70]
    elif fault == "new_path": a["operations"][0]["toolpath_record_counts"] = [12]
    elif fault == "new_suppressed": a["operations"][0]["suppressed"] = True
    elif fault == "missing_tool": a["operations"][0]["assigned_tool"]["native_read_complete"] = False
    elif fault == "stock": a["stock"] = {}
    elif fault == "feature": a["features"] = []
    elif fault == "source": a["saved_file_sha256"] = "0"*64
    elif fault == "count": a["operation_count"] = 0
    elif fault == "setup_count": a["operation_setup_count"] = 0
    elif fault == "index": a["operations"][1]["operation_index"] = 99
    elif fault == "existing_target": b["operations"][0]["linked_feature_ids"] = [64]
    elif fault == "no_new": a = deepcopy(b)
    elif fault == "foreign_setup": a["operations"][0]["setup_native_id"] = 94
    with pytest.raises(ValueError):
        verify_added_plan(b, a, 64, 93)

@pytest.mark.parametrize("where", ["setup_index", "operation_index", "setup_count", "operation_count", "setups_count"])
def test_rejects_boolean_indices(where):
    b, a = sample()
    if where in ("setup_index", "operation_index"): a["operations"][0][where] = False
    elif where == "setup_count": a["operation_counts"][1] = False
    elif where == "operation_count": a["operation_setups"][1]["operation_count"] = False
    else: a["operation_setup_count"] = True
    with pytest.raises(ValueError): verify_added_plan(b, a, 64, 93)

@pytest.mark.parametrize("fault", ["scope", "setup_metadata"])
def test_protects_full_setup_context(fault):
    b,a=sample()
    if fault=="scope": a["operation_inventory_scope"]="different"
    else:
        b["operation_setups"][0]["origin"]=[0,0,0]
        a["operation_setups"][0]["origin"]=[1,0,0]
    with pytest.raises(ValueError): verify_added_plan(b,a,64,93)
