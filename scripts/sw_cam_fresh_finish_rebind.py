"""Read-only binding of saved fresh-finish evidence to a newly owned session.

The historical receipt keeps its original PID and bytes. Existing grouped reads
verify the saved route and guides in the new session before a separate binding
receipt can authorize later reads. No setters, generation, saving or opening.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_guide_group_reader as guide
from scripts import sw_cam_mill_saved_plan_rebind as ownership_reader
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require

common, checkpoint, group = guide.common, guide.checkpoint, guide.group
SCOPE = 'SAVED_FRESH_FINISH_OWNED_SESSION_REBIND_V1'
PARAMS = guide.PARAMS | {'previous_process_id', 'owned_startup_receipt_path', 'owned_startup_receipt_sha256'}


def validate_request(request):
    require(type(request) is dict and set(request) == {'action', 'params'}
        and request['action'] == 'rebind_fresh_finish_session', 'Exact read-only rebind action required')
    p = request['params']
    require(type(p) is dict and set(p) == PARAMS, 'Exact session rebind parameters required')
    base = {k: v for k, v in p.items() if k in guide.PARAMS}
    base['module_sha256'] = _file_hash(guide.__file__)
    guide.validate_request(dict(action='read_shallow_guide_group', params=base))
    require(p['module_sha256'] == _file_hash(__file__), 'Exact rebind implementation required')
    require(type(p['previous_process_id']) is int and 0 < p['previous_process_id'] < 2**31
        and p['previous_process_id'] != p['process_id'], 'Distinct strict historical and new PID required')
    require(type(p['owned_startup_receipt_path']) is str and Path(p['owned_startup_receipt_path']).is_absolute(),
        'Absolute owned startup receipt required')
    require(type(p['owned_startup_receipt_sha256']) is str
        and guide.re.fullmatch('[0-9a-f]{64}', p['owned_startup_receipt_sha256']), 'Exact startup SHA required')
    return deepcopy(p)


def bind_new_owner(historical, startup, *, previous_process_id, process_id):
    """Provisional read context only. This is not a verified session receipt."""
    require(type(previous_process_id) is int and type(process_id) is int and previous_process_id != process_id,
        'Explicit distinct session identities required')
    require(historical['ownership']['process_id'] == previous_process_id
        and startup['process_id'] == process_id and startup['alive'] is True,
        'Historical and new startup ownership differ')
    require(historical['ownership']['create_time'] != startup['create_time'], 'New process creation time required')
    require(common._key(historical['ownership']['executable']) == common._key(startup['executable']),
        'Same SOLIDWORKS executable required')
    require(_digest(group.current_projection(historical)) == historical['current_context_sha256'],
        'Historical context digest differs')
    result = deepcopy(historical)
    result['ownership'] = deepcopy(startup)
    result['current_context_sha256'] = _digest(group.current_projection(result))
    result['rebind_provisional_read_context'] = True
    return result


def load_inputs(p):
    # The recorded PID is validated as history; it is never rewritten or passed
    # off as the current process. The new owner is independently proven below.
    historical = checkpoint.load_completed(p['checkpoint_receipt_path'], p['checkpoint_receipt_sha256'],
        process_id=p['previous_process_id'], expected_document_path=p['expected_document_path'],
        expected_source_sha256=p['expected_source_sha256'])
    guide.expected(historical)
    startup, startup_pin = ownership_reader.load_owned_startup(
        p['owned_startup_receipt_path'], p['owned_startup_receipt_sha256'], p['process_id'])
    provisional = bind_new_owner(historical, startup,
        previous_process_id=p['previous_process_id'], process_id=p['process_id'])
    loaded = guide.prepare_loaded(provisional)
    loaded['pins'] = common._merge(loaded['pins'], [startup_pin,
        common._pin(ownership_reader.__file__), common._pin(__file__)])
    require(len(loaded['pins']) <= 63, 'Reserve one audited TLB pin inside the existing64-file read bound')
    loaded['rebind_historical_context_sha256'] = historical['current_context_sha256']
    loaded['rebind_startup_pin'] = startup_pin
    common._check(loaded['pins']); common._check(loaded['offline_export_proof_pins'])
    return loaded


def verify_readback(report, loaded):
    require(report.get('status') == 'observed' and report.get('phase') == 'finished'
        and report.get('readback_verified') is True and report.get('group_baseline_read_complete') is True,
        'Completed exact group read required before session association')
    require(not any(k in report for k in ('issue', 'failed_phase', 'cleanup_issue', 'receipt_write_error')),
        'Uncertain read cannot rebind authority')
    for key in ('mutation_attempted', 'save_attempted', 'GTP_attempted', 'production_qualified'):
        require(report.get(key) is False, 'Unexpected rebind side effect: ' + key)
    clean_events(report)
    wanted = guide.expected(loaded)
    require(group.exact(report['before'], wanted) and group.exact(report['after'], wanted),
        'Current saved route or guide geometry headers differ')
    require(group.exact(report['before_document'], loaded['state']['document'])
        and group.exact(report['after_document'], loaded['state']['document']), 'Saved clean document changed')
    require(group.exact(report['configuration_before'], report['configuration_after']), 'CAM/SW configuration changed')
    guide.configuration_binding.require_binding(report['configuration_after'])
    require(report['configuration_after']['sw_configuration_name'] == report['request']['expected_configuration'],
        'Requested current SW configuration differs')
    require(_file_hash(report['request']['expected_document_path']) == report['request']['expected_source_sha256'],
        'Saved source changed during rebind')


def load_verified_rebind(path, sha256, current):
    report, pin = read_pin(path, sha256)
    require(report.get('scope') == SCOPE and report.get('session_rebind_verified') is True
        and report.get('historical_receipt_modified') is False, 'Verified separate session association required')
    require(report['module_pin'] == common._pin(__file__) and report['guide_module_pin'] == common._pin(guide.__file__),
        'Executed rebind/guide reader changed')
    p = validate_request(dict(action='rebind_fresh_finish_session', params=report['request']))
    for key in ('process_id', 'expected_source_sha256', 'checkpoint_receipt_sha256', 'expected_configuration', 'addin_clsid'):
        require(group.exact(p[key], current[key]), 'Rebind request lineage differs: ' + key)
    for key in ('expected_document_path', 'checkpoint_receipt_path'):
        require(common._key(p[key]) == common._key(current[key]), 'Rebind path differs: ' + key)
    loaded = load_inputs(p)
    require(report['historical_checkpoint_pin'] == loaded['parent_pin']
        and report['startup_pin'] == loaded['rebind_startup_pin']
        and group.exact(report['new_ownership'], loaded['ownership'])
        and report['historical_context_sha256'] == loaded['rebind_historical_context_sha256']
        and report['new_context_sha256'] == loaded['current_context_sha256'], 'Complete association chain differs')
    verify_readback(report, loaded)
    loaded['pins'] = common._merge(loaded['pins'], [pin])
    require(len(loaded['pins']) <= 63, 'Rebound receipt must leave room for TLB pin')
    loaded['rebind_provisional_read_context'] = False
    loaded['session_rebind_receipt_pin'] = pin
    return loaded


def dispatch_request(request, *, validate_only=False):
    p = validate_request(request); loaded = load_inputs(p)
    registration = common.discover_export_registration(loaded, p['addin_clsid'])
    typelib = str(Path(registration['addin_path']).parent / 'camworks.tlb')
    audit = guide.audit_interfaces(typelib, loaded['generated_pin'])
    loaded['pins'] = common._merge(loaded['pins'], [common._pin(typelib)])
    require(len(loaded['pins']) <= 64, 'Existing bounded audited read scope required')
    receipt = common._local_receipt(p['receipt_path']); progress = Path(p['progress_path'])
    protected = [p['expected_document_path']] + [v['path'] for k in ('pins', 'offline_export_proof_pins', 'bootstrap_export_pins') for v in loaded[k]]
    keys = {common._key(v) for v in protected}
    require(common._key(receipt) not in keys and common._key(progress) not in keys
        and common._key(receipt) != common._key(progress) and progress.suffix.lower() == '.json'
        and progress.parent.is_dir() and not progress.exists() and not progress.is_symlink(), 'Fresh distinct nonaliased outputs required')
    if validate_only:
        return dict(status='validated_offline', native_called=False, selected=guide.expected(loaded),
            historical_process_id=p['previous_process_id'], new_process_id=p['process_id'],
            session_rebind_verified=False, live_pin_count=len(loaded['pins']))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=p['process_id']):
        common._check(loaded['pins']); common._check(loaded['offline_export_proof_pins'])
        sw, _ = connect_solidworks(process_id=p['process_id'], launch_new_instance=False, wait_seconds=1)
        report = dict(scope=SCOPE, status='reading', phase='prepared', request=deepcopy(p),
            module_pin=common._pin(__file__), guide_module_pin=common._pin(guide.__file__),
            historical_checkpoint_pin=loaded['parent_pin'], startup_pin=loaded['rebind_startup_pin'],
            historical_context_sha256=loaded['rebind_historical_context_sha256'], new_context_sha256=loaded['current_context_sha256'],
            new_ownership=deepcopy(loaded['ownership']), interface_audit=audit,
            live_pins=loaded['pins'], offline_proof_pins=loaded['offline_export_proof_pins'],
            read_only=True, session_rebind_verified=False, historical_receipt_modified=False,
            readback_verified=False, group_baseline_read_complete=False, reference_parameter_reads_complete=False,
            guide_operation_parameters_observed=False, mutation_attempted=False, save_attempted=False, GTP_attempted=False,
            production_qualified=False, automatic_retry=False, ready_for_mutation=False, full_geometry_reread=False)
        _write_receipt(receipt, report, create=True)
        persist = lambda: _write_receipt(receipt, report)
        backend = guide.NativeBackend(loaded, p, sw, registration['clsid'], typelib, report, persist)
        guide.run_backend(backend, report, persist)
        try:
            for name in ('pins', 'offline_export_proof_pins', 'bootstrap_export_pins'): common._check(loaded[name])
            verify_readback(report, loaded)
            report.update(session_rebind_verified=True, guides_already_read_in_this_batch=True,
                rebind_scope='saved source bytes, ordered route/links/counts/generic tools, guide and reference headers, configuration mapping; no new geometry or cutting qualification')
        except Exception as exc:
            report.update(status='error', session_rebind_verified=False, readback_verified=False, association_issue=_error(exc))
        persist()
        return report
