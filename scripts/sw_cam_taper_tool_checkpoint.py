"""Read completed FACE lineage after a later tool-only Save.

This helper checks immutable receipts, markers and derived dependency roles.
It deliberately does not read the mutable model file: the caller must verify
its own final source hash and tool-only transition before using this lineage.
No CAD connection, mutation, replay, export or source-file substitution occurs.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_checkpoint_reconfigure as prior


def load_historical_parent(path, digest, *, process_id, expected_document_path, expected_source_sha256, historical_source_path):
    """Validate completed immutable FACE lineage; caller must separately bind current source bytes."""
    prior.require(type(expected_source_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_source_sha256) and (type(expected_document_path) is str) and Path(expected_document_path).is_absolute(), 'Exact historical SHA256 and absolute source path required')
    prior.require(type(historical_source_path) is str, 'Historical archive path must be a string')
    archive = Path(historical_source_path)
    prior.require(type(historical_source_path) is str and archive.is_absolute()
        and archive.suffix.casefold() == '.sldprt' and archive.is_file() and not archive.is_symlink()
        and prior.key(archive) != prior.key(expected_document_path),
        'Separate regular historical source archive required')
    prior.require(prior._file_hash(archive) == expected_source_sha256,
        'Historical saved model bytes differ')
    archive_pin = dict(path=str(archive), sha256=expected_source_sha256)
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
    (data, receiptpin) = read_pin(path, digest)
    cp = prior.validate_terminal(data)
    clean_events(data)
    prior.require(data['module_pin'] == prior.pin(prior.__file__) and type(process_id) is int and (data['process_id'] == process_id) and (prior.key(data['source_path']) == prior.key(expected_document_path)) and (prior.key(data['receipt_path']) == prior.key(path)) and (data['saved_source_sha256'] == expected_source_sha256 == cp['current']['source_sha256']), 'Historical runtime/process/source binding differs; current source bytes are caller responsibility')
    (parent, parentpin) = read_pin(data['parent_pin']['path'], data['parent_pin']['sha256'])
    prior.require(parent.get('scope') == prior.exports.RECOVERY_SCOPE and parent.get('status') == 'observed' and (parent.get('phase') == 'finished') and (parent.get('read_only') is True) and (parent.get('read_pending') is False) and (parent.get('full_capture_count') == 1) and (type(parent.get('native_mutation_calls')) is int) and (parent['native_mutation_calls'] == 0) and (parent['module_pin'] == prior.pin(prior.exports.__file__)) and (parent['process_id'] == process_id) and (prior.key(parent['source_path']) == prior.key(expected_document_path)) and (parent['source_sha256'] == data['source_sha256']) and all((parent.get(k) is False for k in ('GTP_attempted', 'model_saved', 'setter_attempted', 'automatic_replay'))) and (not any((k in parent for k in ('issue', 'failed_phase', 'cleanup_issue', 'receipt_write_error')))) and (parent.get('readback_verified') is True) and (parent.get('state_reconciled') is True) and (parent.get('original_group_completion_claimed') is False) and prior.group.exact(parent['checkpoint']['current'], data['current_before']) and prior.group.exact(parent['checkpoint']['settings'], data['settings_before']) and (parent['checkpoint_sha256'] == prior._digest(parent['checkpoint'])), 'Previous verified authority differs')
    clean_events(parent)
    (plan, planpin) = read_pin(data['recipe_pin']['path'], data['recipe_pin']['sha256'])
    prior.require(plan == data['plan'], 'Correction plan differs')
    prior.validate_plan(plan, dict(data['current_before'], settings=data['settings_before'], parent_pin=parentpin))
    retired = data['retired_offline']
    prior.require(len(retired) == 3, 'Exact original phase proof required')
    prior.check(retired)
    prior.check(data['live_pins'])
    prior.require(len(data['live_pins']) == 63 and (not any((prior.key(p['path']) == prior.key(expected_document_path) for p in data['live_pins']))), 'Exact bounded immutable closure required')
    parent_live = prior.merge([p for p in parent['live_pins'] if prior.key(p['path']) != prior.key(parent['failed_group_pin']['path'])], [parentpin])
    prior.require(len(parent_live) == 64, 'Previous recovery closure differs')
    expected_retired = prior._retirements(dict(data['current_before'], pins=parent_live))
    prior.require(expected_retired == retired, 'Dependency phase roles differ')
    retired_keys = {prior.key(p['path']) for p in retired}
    expected_live = prior.merge([p for p in parent_live if prior.key(p['path']) not in retired_keys], [prior.pin(prior.__file__), prior.pin(Path(prior.group.__file__).parent / 'sw_cam_ud14_save.py')])
    prior.require(data['live_pins'] == expected_live, 'Exact derived reconfiguration closure differs')
    marker = prior.marker_path(data['source_path'], data['source_sha256'])
    (mark, markpin) = read_pin(str(marker), data['marker_pin']['sha256'])
    prior.require(prior.key(data['marker_pin']['path']) == prior.key(marker) and mark == prior.Journal(data, data['receipt_path'], marker)._marker_state(), 'Stable local terminal marker differs')
    prior.check([data['previous_recovery_marker_pin']])
    live = prior.merge([p for p in data['live_pins'] if prior.key(p['path']) != prior.key(parentpin['path'])], [receiptpin, markpin])
    prior.require(len(live) == 64, 'Terminal closure must remain64')
    for protected in ('historical_move_marker_pin', 'previous_group_marker_pin'):
        prior.require(any((prior.key(p['path']) == prior.key(data[protected]['path']) and p['sha256'] == data[protected]['sha256'] for p in live)), 'Original uncertain mutation marker must remain live')
    generated = [p for p in live if Path(p['path']).name.startswith('_FE488661_')]
    prior.require(len(generated) == 1, 'Generated library binding missing')
    result = dict(cp['current'], pins=live, current_context_sha256=prior._digest(cp['current']), parent_pin=receiptpin, group_marker_pin=markpin, generated_pin=generated[0], settings=deepcopy(cp['settings']), generated_face_operation_id=267, toolpath_record_counts=deepcopy(cp['toolpath_record_counts']), reconfigure_retired_pins=retired, historical_parent_pin=parentpin, reconfigure_receipt=data, authority_kind='reconfigured_saved_group', bootstrap_export_pins=[p for p in retired if Path(p['path']).name == 'sw_cam_installation.py'], offline_export_proof_pins=[p for p in retired if Path(p['path']).name != 'sw_cam_installation.py'])
    prior.exports.operation_contract(result)
    result.update(historical_source_only=True, current_source_bytes_verified=False, historical_source_pin=archive_pin)
    prior.check([archive_pin])
    return result
