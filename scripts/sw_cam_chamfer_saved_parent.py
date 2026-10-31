"""Historical saved contour checkpoint for a later saved CAM operation.

The exact insertion source is proved by a separate archive. The caller must
check its current source independently; no historical source SHA is substituted.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_chamfer_insert_defaults as parent
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest

exports, group = parent.exports, parent.group


def load_historical_chamfer_parent(path, digest, *, process_id, expected_document_path,
                                   expected_source_sha256, historical_source_path):
    archive = Path(historical_source_path)
    require(archive.is_absolute() and archive.suffix.casefold() == '.sldprt'
        and archive.is_file() and not archive.is_symlink()
        and exports._key(archive) != exports._key(expected_document_path),
        'Separate actual historical insertion-source archive required')
    archivepin = exports._pin(archive)
    require(archivepin['sha256'] == expected_source_sha256, 'Historical insertion-source archive hash differs')
    data, receiptpin = read_pin(path, digest)
    require(data['module_pin'] == exports._pin(parent.__file__) and data['process_id'] == process_id
        and exports._key(data['source_path']) == exports._key(expected_document_path)
        and exports._key(data['receipt_path']) == exports._key(path)
        and data['saved_source_sha256'] == expected_source_sha256,
        'Historical insertion source/process/runtime differs')
    params = dict(process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=data['initial_source_sha256'],
        checkpoint_receipt_path=data['parent_pin']['path'], checkpoint_receipt_sha256=data['parent_pin']['sha256'],
        tool_source_archive_path=data['tool_source_archive_pin']['path'],
        feature_native_id=data['feature_native_id'], anchor_operation_native_id=data['anchor_operation_native_id'],
        default_operation_id=data['default_operation_id'], default_operation_name=data['default_operation_name'])
    loaded = parent.load_inputs(params, check_current=False)
    require(all(group.exact(loaded[left], data[right]) for left, right in (
        ('pins', 'live_pins'), ('offline_export_proof_pins', 'offline_proof_pins'),
        ('insertion_phase_retired_pins', 'phase_retired_pins'), ('parent_pin', 'parent_pin'),
        ('tool_source_archive_pin', 'tool_source_archive_pin'))), 'Exact historical parent and phase closure required')
    cp = parent.validate_terminal(data, loaded)
    require(cp['current']['source_sha256'] == expected_source_sha256, 'Historical saved checkpoint source differs')
    marker = parent.marker_path(data['source_path'], data['initial_source_sha256'],
                                data['feature_native_id'], data['anchor_operation_native_id'])
    mark, markerpin = read_pin(str(marker), data['marker_pin']['sha256'])
    require(exports._key(marker) == exports._key(data['marker_pin']['path'])
        and group.exact(mark, parent.Journal(data, path, marker).marker_state()),
        'Completed historical insertion marker differs')
    live = exports._merge([p for p in loaded['pins']
        if exports._key(p['path']) != exports._key(data['parent_pin']['path'])], [receiptpin])
    offline = exports._merge(loaded['offline_export_proof_pins'], [data['parent_pin'], markerpin])
    result = dict(cp['current'], pins=live, parent_pin=receiptpin, group_marker_pin=markerpin,
        current_context_sha256=_digest(cp['current']), generated_pin=deepcopy(loaded['generated_pin']),
        settings=deepcopy(cp['settings']), generated_face_operation_id=cp['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(cp['toolpath_record_counts']),
        local_tool_candidate=deepcopy(cp['local_tool_candidate']), profile_contract=deepcopy(cp['profile_contract']),
        candidate_qualification=deepcopy(cp['candidate_qualification']), inserted_contour=deepcopy(cp['inserted_contour']),
        tool_checkpoint=loaded['tool_checkpoint'], operation_checkpoint=data,
        offline_export_proof_pins=offline, bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),
        authority_kind='saved_ungenerated_contour_defaults',
        tool_source_archive_pin=deepcopy(loaded['tool_source_archive_pin']), insertion_source_archive_pin=archivepin,
        historical_source_only=True, current_source_bytes_verified=False)
    exports._check(live); exports._check(offline)
    require(_file_hash(archive) == expected_source_sha256, 'Historical insertion-source archive changed during validation')
    return result
