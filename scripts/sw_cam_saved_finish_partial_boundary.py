"""Pure verification of a saved Finish interrupted before its first CL export.

The producer remains uncertain. File identity, runtime, live owner and a fresh
native state are separate caller obligations; this function performs no I/O.
"""
from copy import deepcopy
import math
import ntpath
import re
from scripts import sw_cam_current_finish_generation_delta as delta

require = delta.require
exact = delta.exact
SCOPE = 'CURRENT_ORDINARY_CIRCULAR_FINISH_GENERATION_V1'
REASON = 'SW_RUNTIME_SOURCE_CHANGED: restart MCP from the configured runtime directory'

def _path(value):
    require(type(value) is str and ntpath.isabs(value), 'Explicit absolute path required')
    return ntpath.normcase(ntpath.normpath(value))

def _clean_messages(value):
    expected = dict(policy='vendor_default', response='default_unknown', subscribed=True,
                    disconnected=True, active=False, event_count=0, events=[], overflow=0,
                    callback_errors=[], callback_error_count=0, subscription_error=None,
                    disconnect_errors=[])
    require(exact(value, expected), 'Complete clean disconnected event summary required')

def _returned_zero(value):
    return exact(value, dict(attempted=True, returned=True, native_dispatch_pending=False,
                            native_return_type='int', native_return_value=0))

def verify_partial(receipt, configuration_receipt, *, source_sha256, process_id,
                   process_create_time):
    """Return only proven saved-boundary facts; never promote terminal status."""
    r = receipt; c = configuration_receipt
    require(type(r) is dict and type(c) is dict, 'Producer and configuration required')
    require(type(source_sha256) is str and re.fullmatch('[0-9a-f]{64}', source_sha256), 'Strict source SHA required')
    require(type(process_id) is int and 0 < process_id < 2**32, 'Strict owned PID required')
    require(type(process_create_time) in (int, float) and math.isfinite(process_create_time) and process_create_time > 0, 'Finite owned lifetime required')
    require(r['scope'] == SCOPE and r['status'] == 'uncertain' and r['phase'] == 'finished' and r['reason'] == REASON, 'Only exact interrupted producer permitted')
    for key in ('issue', 'cleanup_error', 'runtime_error'):
        issue = r[key]
        require(type(issue) is dict and issue.get('type') == 'RuntimeIdentityError' and issue.get('hresult') is None and issue.get('actual_return_type') is None, 'Only runtime identity failure is recoverable')
    require(r['failed_phase'] == 'Count', 'Exact pre-export guard failure required')
    request = r['request']; binding = r['binding']
    require(exact(binding, {k:v for k,v in request.items() if k not in ('receipt_path', 'saved_cl_path')}), 'Producer binding differs')
    require(request['qualification_only'] is True and request['message_policy'] == 'vendor_default', 'Qualification-only request required')
    for value in (request, c['request']):
        require(type(value['process_id']) is int and value['process_id'] == process_id and exact(value['expected_process_create_time'], process_create_time), 'Owner lifetime differs')
    require(_path(request['expected_document_path']) == _path(c['request']['expected_document_path']), 'Document binding differs')
    require(_path(r['receipt_path']) == _path(request['receipt_path']), 'Producer receipt binding differs')
    pin = r['configuration_receipt_pin']
    require(_path(pin['path']) == _path(request['configuration_receipt_path']) == _path(c['receipt_path']) and pin['sha256'] == request['configuration_receipt_sha256'], 'Configuration pin binding differs')
    require(c['scope'] == 'CURRENT_ORDINARY_CIRCULAR_FINISH_CONFIGURATION_V1' and c['status'] == 'review_required' and c['phase'] == 'finished', 'Completed configuration required')
    for key in ('configuration_saved', 'model_saved', 'save_readback_verified', 'source_update_verified', 'readback_verified', 'runtime_unchanged'):
        require(c[key] is True, 'Unverified configuration: '+key)
    require(not any(k in c for k in ('issue','cleanup_error','runtime_error')), 'Configuration failure is not accepted')
    _clean_messages(c['messages']); _clean_messages(r['messages'])
    before_sha = request['expected_source_sha256']
    require(before_sha == r['source_before_sha256'] == c['source_after_sha256'] == c['saved_file_sha256'], 'Configured source binding differs')
    require(source_sha256 == r['source_after_sha256'] == r['saved_file_sha256'], 'Saved source differs')
    true_flags = ('receipt_created','marker_created','mutation_attempted','native_call_attempted','native_call_returned','GTP_attempted','save_attempted','model_saved','save_readback_verified','source_update_verified','generation_verified','save_returned_zero')
    false_flags = ('native_dispatch_pending','GOP_attempted','AFR_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','CL_export_attempted','reference_geometry_creation_attempted','operation_creation_attempted','generation_saved','readback_verified','runtime_unchanged','automatic_replay','automatic_rollback','production_qualified','machining_eligible','reopen_persistence_verified')
    for key in true_flags: require(r[key] is True, 'Saved boundary fact absent: '+key)
    for key in false_flags: require(r[key] is False, 'Unexpected partial producer fact: '+key)
    ids = r['selected_operation_native_ids']; fid = r['selected_feature_native_id']
    require(type(ids) is list and len(ids) == 1 and type(ids[0]) is int and ids[0] > 0 and type(fid) is int and fid > 0, 'Actual selected identity required')
    oid = ids[0]
    require(type(c['selected_operation_native_id']) is int and c['selected_operation_native_id'] == oid, 'Configured operation differs')
    names = ['GTP:'+str(oid), 'SaveActiveDocument', 'postCL']
    require(exact(r['allowed_actions'], names) and set(r['actions']) == set(names), 'Only original GTP, Save and unattempted export allowed')
    for name in names[:2]: require(_returned_zero(r['actions'][name]), 'Exact returned int0 required: '+name)
    require(exact(r['actions']['postCL'], dict(attempted=False,returned=False,native_dispatch_pending=False)), 'CL must never have been attempted')
    require(exact(r['save_stage'], dict(save_pending=False,native_call_returned=True,native_return_type='int',native_return_value=0)), 'Exact saved stage required')
    require([x.get('label') for x in r['captures']] == ['before','generated','saved'], 'Exactly three full captures required')
    for capture in r['captures']:
        label = capture['label']; state = r[label]
        require(capture.get('capture_complete') is True and exact(capture['state'],state), 'Capture copy differs: '+label)
        require(all(state.get(k) is True for k in ('capture_complete','extended_capture_complete','parameter_capture_complete')), 'Incomplete full capture: '+label)
        require(type(state['sketch_state']['pid']) is int and state['sketch_state']['pid'] == process_id, 'Captured owner differs')
        require(_path(state['document']['path']) == _path(request['expected_document_path']), 'Captured document differs')
    require(delta.configuration.circular.circular_state_equal(r['before'],c['saved']), 'Fresh before differs from completed configuration')
    generation = delta.verify_generation(r['before'],r['generated'],oid,fid)
    saved = delta.verify_saved(r['generated'],r['saved'],oid,fid,source_sha256)
    require(exact(generation,r['generation_proof']) and exact(saved,r['saved_proof']), 'Stored boundary proof differs from recomputation')
    planes = r['plane_observations']
    require(set(planes) == {'before','generated','saved'}, 'Only three complete plane observations required')
    for value in planes.values(): require(exact(value,c['plane_observations']['saved']), 'Saved setup planes changed')
    checks = r['capture_pin_checks']; labels = ['before','planes_before','generated','planes_generated','saved','planes_saved','compact_before_save']
    require([x.get('label') for x in checks] == labels, 'Exact full and interrupted compact check sequence required')
    for i,check in enumerate(checks):
        require(check.get('entry_verified') is True and check.get('exit_verified') is (i < 6), 'Boundary verification flags differ')
        require(type(check.get('nested_checks_deferred')) is int and check['nested_checks_deferred'] >= 0, 'Invalid deferred check count')
    post = r['postCL']
    require(set(post) == {'source_sha256','document','output_path','native_dispatch_pending','native_call_returned','capture_policy'}, 'Partial export contains unqualified result')
    require(post['source_sha256'] == source_sha256 and exact(post['document'],r['saved']['document']) and _path(post['output_path']) == _path(request['saved_cl_path']), 'Unattempted output binding differs')
    require(post['native_dispatch_pending'] is False and post['native_call_returned'] is False and post['capture_policy'] == 'full_saved_then_compact_export_boundaries', 'Only unattempted export boundary permitted')
    rows = delta.positive_rows(r['saved'])
    require(len(rows) == 21 and sum(sum(x['toolpath_record_counts']) for x in rows) == 83961+generation['selected_record_count'], 'Saved positive inventory differs')
    return dict(scope='SAVED_FINISH_BEFORE_FIRST_CL_EXPORT_BOUNDARY_V1', operation_id=oid,
                feature_id=fid, state=deepcopy(r['saved']), planes=deepcopy(planes['saved']),
                positive_rows=rows, generation_proof=generation, saved_proof=saved,
                source_sha256=source_sha256, original_status_preserved='uncertain',
                original_runtime_unchanged=False, export_attempted=False,
                fresh_native_boundary_required=True, physical_toolpath_qualified=False)
