"""Pure provenance gate for addressing one created, unconfigured local tool.

File hashes and current-process checks are responsibilities of the caller. This
validator never opens files, connects to CAM, repairs an old report or retries
creation. Its returned baseline is historical evidence, not a fresh snapshot.
"""
from copy import deepcopy
import json
import math
import re
from scripts import sw_cam_taper_tool_candidate as base


def require(value, message):
    if not value:
        raise ValueError(message)


def exact(a, b):
    return json.dumps(a, sort_keys=True, allow_nan=False, separators=(',', ':')) == json.dumps(
        b, sort_keys=True, allow_nan=False, separators=(',', ':'))


def positive(value):
    return type(value) is int and value > 0


def _batch(row):
    require(type(row) is dict and row.get('read_scope_complete') is True
            and row.get('read_only') is True and row.get('active') is False
            and row.get('invalid') is False and row.get('write_lease') is False
            and row.get('native_call_attempted') is False,
            'Completed read-only batch required')


def _catalogue(rows):
    require(type(rows) is list and rows, 'Nonempty catalogue required')
    ids = []
    for row in rows:
        require(type(row) is dict and positive(row.get('native_id'))
                and positive(row.get('tool_type_raw')), 'Strict tool ID/type required')
        for name in ('CutDiameter', 'Protrusion', 'StnNo'):
            value = row.get(name)
            require(type(value) in (int, float) and math.isfinite(value),
                    'Finite catalogue field required')
        ids.append(row['native_id'])
    require(len(ids) == len(set(ids)), 'Duplicate catalogue ID')
    return ids


def validate_resume_evidence(failed, loaded, actual_marker_data):
    """Return immutable reuse inputs after the caller pins the three arguments.

    ``loaded`` is the exact historical v2 parent, before adding the resume
    module's own dependency closure. Live source/ownership/catalogue/holder
    checks must still run in the new process before any property dispatch.
    """
    require(type(failed) is dict and type(loaded) is dict, 'Structured evidence required')
    require(type(failed.get('schema_version')) is int and failed['schema_version'] == 1
            and failed.get('scope') == base.SCOPE and failed.get('status') == 'uncertain'
            and failed.get('phase') == failed.get('failed_phase') == 'AddNewTool3',
            'Exact post-creation failure stage required')
    action = dict(attempted=True, returned=True, pending=False,
                  native_return_type='POINTER(ICWTaperTool)', returned_interface_pointer=True)
    require(exact(failed.get('actions'), {'AddNewTool3': action}),
            'Only one completed creator and no later action may precede resume')
    require(failed.get('mutation_attempted') is True
            and failed.get('phase_proofs_verified_after_native') is True,
            'Creation and post-phase file checks must be recorded')
    for name in ('model_saved', 'readback_verified', 'automatic_retry', 'automatic_replay',
                 'assignment_attempted', 'GTP_attempted', 'GOP_attempted',
                 'operation_creation_attempted', 'production_qualified'):
        require(failed.get(name) is False, 'Unexpected failure flag: ' + name)
    for name in ('saved_source_sha256', 'source_transition', 'save_stage', 'field_readbacks',
                 'created_candidate', 'configured_candidate', 'final_candidate', 'checkpoint',
                 'candidate_reads', 'cleanup_issue', 'phase_proof_error'):
        require(name not in failed, 'Later or uncertain work exists: ' + name)
    require(type(failed.get('full_tool_snapshot_count')) is int
            and failed['full_tool_snapshot_count'] == 1
            and type(failed.get('candidate_profile_capture_count')) is int
            and failed['candidate_profile_capture_count'] == 0,
            'Exactly one old-tool snapshot and zero candidate captures required')
    issue = failed.get('issue', {})
    functions = {(r.get('file'), r.get('function')) for r in issue.get('locations', [])}
    require(issue.get('type') == 'ValueError' and issue.get('hresult') is None
            and ('sw_cam_comtypes.py', '_interface_class') in functions
            and ('sw_cam_generation.py', '_typed') in functions,
            'Expected unsupported typed-interface failure required')

    # Compare the original authority without rewriting hashes after installation.
    require(exact(failed['current_before'], base.group.current_projection(loaded))
            and failed['current_before_sha256'] == loaded['current_context_sha256']
            == base._digest(failed['current_before']), 'Historical context differs')
    for left, right in (('parent_pin', 'parent_pin'), ('historical_source_pin', 'historical_source_pin'),
                        ('recipe', 'recipe'), ('recipe_pin', 'recipe_pin'), ('catalogue_pin', 'catalogue_pin'),
                        ('settings_before', 'settings'), ('generated_face_operation_id', 'generated_face_operation_id'),
                        ('toolpath_record_counts', 'toolpath_record_counts'), ('live_pins', 'pins'),
                        ('offline_proof_pins', 'offline_export_proof_pins'), ('phase_retired_pins', 'tool_phase_retired')):
        require(exact(failed[left], loaded[right]), 'Historical binding differs: ' + left)
    source = failed['initial_source_sha256']
    require(type(source) is str and re.fullmatch('[0-9a-f]{64}', source)
            and source == loaded['source_sha256'] == loaded['state']['saved_file_sha256']
            == failed['historical_source_pin']['sha256'], 'Exact saved source required')
    ownership = loaded['ownership']
    require(positive(failed.get('process_id')) and ownership['process_id'] == failed['process_id']
            and ownership.get('alive') is True and type(ownership.get('create_time')) in (int, float)
            and math.isfinite(ownership['create_time']) and ownership['create_time'] > 0,
            'Original process ownership required')
    document = failed['current_document']
    require(type(document.get('needs_save')) is bool and document['needs_save'] is False
            and exact(document, loaded['state']['document'])
            and base.exports._key(document['path']) == base.exports._key(failed['source_path']),
            'Observed unchanged clean document identity required; dirty must not be inferred')
    require(exact(actual_marker_data, base.Journal(failed, failed['receipt_path'], 'unused').marker_state()),
            'Original creation marker must exactly match the completed failed receipt')

    messages = failed['messages']
    require(messages.get('subscribed') is True and type(messages.get('active')) is bool
            and type(messages.get('disconnected')) is bool
            and messages['active'] is not messages['disconnected'], 'Recorded event-session flags required')
    for name in ('event_count', 'overflow', 'callback_error_count'):
        require(type(messages.get(name)) is int and messages[name] == 0, 'Recorded event/error count must be zero')
    for name in ('events', 'callback_errors', 'disconnect_errors'):
        require(messages.get(name) == [], 'Recorded event/error list must be empty')
    require(messages.get('subscription_error') is None, 'Event subscription error present')

    baseline = failed['initial_observation']
    require(exact(baseline['route'], base.expected_route(loaded))
            and exact(baseline['units'], loaded['finish_payload']['unit_record'])
            and baseline['units']['metric_document_scope_observed'] is True,
            'Original route and metric observation differ')
    old_ids = _catalogue(baseline['tools'])
    require(len(old_ids) == 17 and set(baseline['protected_tools']) == {str(v) for v in old_ids},
            'Complete original seventeen-tool baseline required')
    for ident in old_ids:
        row = baseline['protected_tools'][str(ident)]
        require(row.get('profile_complete') is True, 'Complete original tool profile required')
        profiles = row['profiles']
        holder_profile = profiles.get('holder', row.get('holder', {}).get('profile'))
        for profile in (profiles['tool'], profiles['shank'], holder_profile):
            require(base.observed_profile_complete(profile) is True, 'Original tool/holder profile incomplete')
    old_working_id = str(loaded['finish_payload']['full_tool']['tool_native_id'])
    require(exact(baseline['protected_tools'][old_working_id], loaded['finish_payload']['full_tool']),
            'Qualified working tool differs from parent')
    diagnostics = failed['protected_tool_observations']
    require(type(diagnostics) is list and len(diagnostics) == 1, 'Only one historical snapshot allowed')
    diagnostic = diagnostics[0]
    require(diagnostic['label'] == 'initial' and diagnostic['catalogue_complete'] is True
            and exact(diagnostic['catalogue'], baseline['tools'])
            and exact(diagnostic['partial_protected_tools'], baseline['protected_tools'])
            and exact(diagnostic['route'], baseline['route']) and exact(diagnostic['units'], baseline['units']),
            'Persisted baseline diagnostic differs')
    reads = diagnostic['tool_reads']
    require([r['native_id'] for r in reads] == old_ids
            and all(r.get('read_complete') is True for r in reads), 'Every original tool must have completed readback')
    _batch(diagnostic['handle_batch'])
    require(len(diagnostic['batches']) == 5, 'All original profile batches required')
    for batch in diagnostic['batches']:
        _batch(batch)
    catalogues = failed['scalar_catalogue_reads']
    require(type(catalogues) is list and len(catalogues) == 2, 'Exactly before/after creation catalogues required')
    for observed in catalogues:
        require(observed['phase'] == 'finished' and observed['complete'] is True, 'Incomplete catalogue observation')
        _batch(observed['batch'])
        _catalogue(observed['rows'])
    require(exact(catalogues[0]['rows'], baseline['tools']), 'Initial catalogue differs')
    after = catalogues[1]['rows']
    new_id = failed['new_tool_native_id']
    base.verify_new_catalogue(baseline['tools'], after, new_id)
    require(len(after) == 18, 'Exactly eighteen tools after creation required')
    forbidden = {v['geometry']['native_id'] for v in loaded['state']['features']}
    forbidden.update(v['native_id'] for v in loaded['state']['operations']
                     + loaded['state']['feature_setups'] + loaded['state']['operation_setups'])
    require(new_id not in forbidden, 'Candidate ID collides with protected object')
    return dict(baseline=deepcopy(baseline), catalogue_after_creation=deepcopy(after),
        new_tool_native_id=new_id, current_document=deepcopy(document), ownership=deepcopy(ownership),
        source_sha256=source, creation_marker=deepcopy(actual_marker_data),
        event_cleanup_observed=messages['disconnected'] is True and messages['active'] is False,
        prior_python_exit_proved_by_receipt=False, requires_fresh_event_scope=True,
        requires_live_catalogue_identity_check=True, requires_reacquired_prior_holder_identities=True,
        historical_full_snapshot_count=1, required_fresh_full_snapshots=2,
        creator_replay_allowed=False, production_qualified=False)
