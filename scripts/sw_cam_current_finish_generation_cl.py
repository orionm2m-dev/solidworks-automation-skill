"""Reuse exact empty-block verifier for historical20 to new21 positive streams."""
from hashlib import sha256
from scripts import sw_cam_empty_cl_comparison as comparison
from scripts.sw_cam_current_saved_parameter_fields import equal as exact
from scripts.sw_cam_current_saved_generation_delta import require

def project_verified_baseline(raw,historical_raw,historical_rows,baseline_rows,*,baseline_proof):
    empty=baseline_proof['empty_block'];added=baseline_proof['new_operation']['operation_native_id']
    proof,projected,observed=comparison.reconcile(raw,historical_raw,historical_rows,baseline_rows,empty_native_id=empty['native_id'],added_native_id=added,expected_empty_label=empty['label'])
    require(exact(proof,baseline_proof),'Historical comparison proof changed')
    first,last=proof['comparison_projection']['removed_raw_line_numbers'];lines=raw.splitlines(keepends=True);result=b''.join(lines[:first-1]+lines[last:])
    require(sha256(result).hexdigest()==proof['comparison_projection']['sha256']and len(result)==proof['comparison_projection']['bytes'],'Verified historical byte projection differs')
    return result,proof

def compare(raw,baseline_raw,historical_raw,historical_rows,baseline_rows,after_rows,*,baseline_proof,added_native_id):
    prior,prior_proof=project_verified_baseline(baseline_raw,historical_raw,historical_rows,baseline_rows,baseline_proof=baseline_proof)
    require(type(added_native_id)is int and added_native_id not in[r['operation_native_id']for r in baseline_rows],'Only genuinely new operation may be added')
    proof,projected,observed=comparison.reconcile(raw,prior,baseline_rows,after_rows,empty_native_id=prior_proof['empty_block']['native_id'],added_native_id=added_native_id,expected_empty_label=prior_proof['empty_block']['label'])
    proof['historical_baseline_projection']=dict(raw_sha256=sha256(baseline_raw).hexdigest(),comparison_sha256=sha256(prior).hexdigest(),recomputed_from_immutable_history=True,raw_modified=False)
    return proof,projected,observed
