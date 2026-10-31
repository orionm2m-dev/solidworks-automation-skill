"""Historical saved-tool checkpoint for subsequent saved CAM steps.

The original model bytes are proved by a separate archive. The caller must
independently check the current model; no source hash is substituted here.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_taper_tool_resume as resume
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest

exports, group = resume.exports, resume.group


def load_historical_resume_parent(path, digest, *, process_id, expected_document_path,
                                  expected_source_sha256, historical_source_path):
    archive=Path(historical_source_path)
    require(archive.is_absolute() and archive.suffix.casefold()=='.sldprt'
        and archive.is_file() and not archive.is_symlink()
        and exports._key(archive)!=exports._key(expected_document_path),
        'Separate actual historical tool-source archive required')
    archivepin=exports._pin(archive)
    require(archivepin['sha256']==expected_source_sha256,'Historical tool-source archive hash differs')
    data,receiptpin=read_pin(path,digest)
    require(data['module_pin']==exports._pin(resume.__file__) and data['process_id']==process_id
        and exports._key(data['source_path'])==exports._key(expected_document_path)
        and exports._key(data['receipt_path'])==exports._key(path)
        and data['saved_source_sha256']==expected_source_sha256,
        'Historical resumed source/process/runtime differs')
    params=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=data['initial_source_sha256'],
        checkpoint_receipt_path=data['parent_pin']['path'],checkpoint_receipt_sha256=data['parent_pin']['sha256'],
        historical_source_path=data['historical_source_pin']['path'],
        recipe_path=data['recipe_pin']['path'],recipe_sha256=data['recipe_pin']['sha256'],
        catalogue_receipt_path=data['catalogue_pin']['path'],catalogue_receipt_sha256=data['catalogue_pin']['sha256'],
        failed_receipt_path=data['failure_pin']['path'],failed_receipt_sha256=data['failure_pin']['sha256'],
        creation_marker_path=data['creation_marker_pin']['path'],creation_marker_sha256=data['creation_marker_pin']['sha256'],
        expected_created_tool_native_id=data['new_tool_native_id'])
    parent=resume.load_inputs(params,check_current=False)
    cp=resume.validate_terminal(data,parent['failed_attempt'])
    require(cp['current']['source_sha256']==expected_source_sha256
        and group.exact(group.current_projection(parent),data['current_before'])
        and all(group.exact(parent[left],data[right]) for left,right in (
            ('settings','settings_before'),('pins','live_pins'),
            ('offline_export_proof_pins','offline_proof_pins'),('resume_retired_pins','phase_retired_pins'),
            ('generated_face_operation_id','generated_face_operation_id'),
            ('toolpath_record_counts','toolpath_record_counts'),('recipe','recipe'),
            ('historical_source_pin','historical_source_pin'))),
        'Exact historical resumed authority and derivation required')
    marker=resume.marker_path(data['source_path'],data['initial_source_sha256'],data['new_tool_native_id'],
                              data['creation_marker_pin']['sha256'])
    mark,markpin=read_pin(str(marker),data['marker_pin']['sha256'])
    require(exports._key(data['marker_pin']['path'])==exports._key(marker)
        and group.exact(mark,resume.Journal(data,path,marker).marker_state()),
        'Stable completed resume marker differs')
    retired={exports._key(data['failure_pin']['path']),exports._key(data['creation_marker_pin']['path'])}
    live=exports._merge([p for p in parent['pins'] if exports._key(p['path']) not in retired],[receiptpin])
    offline=exports._merge(parent['offline_export_proof_pins'],[data['failure_pin'],data['creation_marker_pin'],markpin])
    result=dict(cp['current'],pins=live,current_context_sha256=_digest(cp['current']),
        parent_pin=receiptpin,group_marker_pin=markpin,generated_pin=deepcopy(parent['generated_pin']),
        settings=deepcopy(cp['settings']),generated_face_operation_id=cp['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(cp['toolpath_record_counts']),
        local_tool_candidate=deepcopy(cp['local_tool_candidate']),profile_contract=deepcopy(cp['profile_contract']),
        candidate_qualification=deepcopy(cp['candidate_qualification']),tool_checkpoint=data,
        bootstrap_export_pins=deepcopy(parent['bootstrap_export_pins']),offline_export_proof_pins=offline,
        authority_kind='resumed_saved_taper_candidate',tool_source_archive_pin=archivepin,
        historical_source_only=True,current_source_bytes_verified=False)
    exports._check(live);exports._check(offline);exports.operation_contract(result)
    require(_file_hash(archive)==expected_source_sha256,'Historical tool-source archive changed during validation')
    return result
