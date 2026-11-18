"""Continue completed circle creation with explicit historical/current owner evidence."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_current_circular_finish_owner as owner
from scripts.sw_cam_thread import _file_hash
require=owner.require;exact=owner.exact


def load_prior(v,manifest,manifest_pin,physical_sha):
    from scripts import sw_cam_current_circular_finish_configuration_authority as authority
    require(type(manifest)is dict and manifest.get('scope')==owner.SCOPE,'Exact current-owner manifest required')
    proof,proof_pin=owner.pin_read(manifest['historical_authority_pin'])
    require(proof.get('scope')=='PARTIAL_FLOOR_CL_FILE_RECONCILIATION_V1'and proof.get('status')=='PASS_SCOPED_RECONCILIATION','Completed historical CL reconciliation required')
    raw,raw_pin=authority._pin_record(proof['raw_partial_save_receipt_pin']);old=raw['request']['params']
    require(type(old['process_id'])is int and old['process_id']!=v['process_id']and old['expected_process_create_time']!=v['expected_process_create_time'],'Distinct historical/current owner required')
    data=authority._load_prior_saved_native(raw,raw_pin,process_id=old['process_id'],process_create_time=old['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'],reconciliation=proof,reconciliation_pin=proof_pin,physical_source_sha256=physical_sha)
    require(owner.same_pin(data['authority_pin'],proof_pin),'Historical authority binding differs')
    result=owner._bind_validated_history(manifest,manifest_pin,data,old,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'],physical_source_sha256=physical_sha)
    result['pins'].append(authority._full_pin(dict(path=__file__,sha256=_file_hash(__file__))))
    return result


def verify_completed_transition(receipt,prepare,data,v):
    proof=owner.verify_projection(data,v)
    require(proof is not None and receipt.get('owner_transition_verified_before_mutation')is True,'Completed full native comparison before owner-transition mutation required')
    require(exact(receipt.get('owner_comparison_projection'),proof)and exact(prepare.get('owner_comparison_projection'),proof),'Creation and preparation owner projections differ')
    require(prepare.get('before_provenance')==owner.PROVENANCE and prepare.get('native_observation_performed')is False and type(prepare.get('native_read_count'))is int and prepare['native_read_count']==0,'Preparation must remain explicitly file-only')
    require(exact(prepare.get('actions'),{})and exact(prepare.get('captures'),[])and prepare.get('marker_created')is False and prepare.get('native_call_attempted')is False,'File-only preparation must not contain native actions')
    module=Path(owner.__file__)
    pins=receipt.get('evidence_pins');require(type(pins)is list and any(owner.history.common.same_path(p.get('path',''),module)and p.get('sha256')==_file_hash(module)for p in pins),'Exact completed owner adapter code pin required')
    require(owner.same_pin(receipt['authority_pin'],data['owner_manifest_pin'])and owner.same_pin(prepare['authority_pin'],data['owner_manifest_pin']),'Owner manifest lineage differs')
    return dict(owner_transition_verified=True,historical_receipts_preserved=True,comparison_projection_only=True)
