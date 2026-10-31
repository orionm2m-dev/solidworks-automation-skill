"""Resume the verified four-action prefix of one interrupted pocket finish.

Read the complete partial state before changing only the remaining eleven
fields. Reuse the existing selected generation and single-save implementation.
No assignment replay, tool creation, operation creation, or automatic recovery.
"""
from copy import deepcopy
from pathlib import Path
import json
import re
from scripts import sw_cam_pocket_finish_apply as original
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
from scripts.sw_cam_rough_firstcut import require

common, group = original.common, original.group
SCOPE = 'PARTIAL_POCKET_FINISH_CONTINUATION_V1'
AUTHORITY = original.AUTHORITY
PREFIX_KEYS = ('SetTool', 'field:out_independent', 'field:first_depth', 'field:max_depth')
PREFIX_FIELDS = original.FIELDS[:3]
UNCHANGED_FIELD = next(x for x in original.FIELDS if x[0] == 'previous_allowance')
REMAINING_FIELDS = tuple(x for x in original.FIELDS[3:] if x[0] != 'previous_allowance')
NEW_ACTIONS = tuple('field:' + x[0] for x in REMAINING_FIELDS) + ('GenerateToolpath', 'SaveActiveDocument')
PARAMS = {'process_id','expected_document_path','expected_source_sha256','addin_clsid',
 'receipt_path','progress_path','failed_receipt_path','failed_receipt_sha256',
 'original_module_archive_path','original_module_archive_sha256','original_marker_path',
 'original_marker_sha256','expected_module_sha256'}


def verified_action(a):
    require(a.get('attempted') is True and a.get('returned') is True and a.get('pending') is False
        and a.get('readback_verified') is True and a.get('native_return_type') == 'int'
        and type(a.get('native_return_value')) is int and a['native_return_value'] == 0,
        'Inherited or new action must have strict-zero return and completed readback')


def validate_failed(failed):
    require(failed.get('scope') == original.SCOPE and failed.get('status') == 'uncertain'
        and failed.get('phase') == 'finished' and failed.get('failed_phase') == 'field:max_depth'
        and failed.get('mutation_attempted') is True and failed.get('readback_verified') is False
        and failed.get('model_saved') is False and failed.get('configuration_readback_verified') is False
        and failed.get('actual_full_capture_count') == 0 and failed.get('phase_proofs_verified') is False,
        'Exact interrupted four-action configuration required')
    require(set(failed['actions']) == set(PREFIX_KEYS)
        and not any(k in failed for k in ('configured','generated','final','save_stage','saved_source_sha256','cleanup_issue')),
        'Only the recorded four configuration actions may precede this continuation')
    require(failed.get('issue',{}).get('type') == 'OSError'
        and failed.get('phase_proof_error',{}).get('type') == 'OSError'
        and any(x.get('function') == '_file_hash' for x in failed['issue'].get('locations',[]))
        and any(x.get('function') == '_file_hash' for x in failed['phase_proof_error'].get('locations',[])),
        'Exact filesystem-proof interruption required')
    clean_events(failed)
    require(all(failed[k] is False for k in original.FORBIDDEN), 'Forbidden historical action')
    baseline = failed['loaded_context_before']
    require(baseline['source_sha256'] == baseline['state']['saved_file_sha256'] == failed['initial_source_sha256'],
        'Original saved baseline differs')
    original.verify_route(baseline, failed['initial_headers'], assigned=False, generated=False)
    original.verify_parameters(baseline['pocket_parameters'], failed['initial_parameters']['parameters'], configured=False)
    require(group.exact(failed['initial_parameters']['startpoints'], baseline['pocket_startpoints'])
        and group.exact(failed['initial_catalogue'], baseline['neck_tool_checkpoint']['catalogue']),
        'Historical complete point/catalogue baseline differs')
    require(set(failed['initial_fields']) == {x[0] for x in original.FIELDS}
        and all(original.initial_field_matches(x, failed['initial_fields'][x[0]]) for x in original.FIELDS),
        'Historical direct scalar baseline differs')
    for a in failed['actions'].values(): verified_action(a)
    require(group.exact(failed['actions']['SetTool']['observed'], original.wanted_assignment(baseline)),
        'Inherited assignment does not match the saved candidate')
    for spec in PREFIX_FIELDS:
        require(group.exact(failed['actions']['field:' + spec[0]]['observed'], spec[6]), 'Inherited direct value differs')
    doc = deepcopy(failed['current_document']); expected = deepcopy(baseline['state']['document'])
    require(type(doc.get('needs_save')) is bool, 'Recorded document flag required')
    expected['needs_save'] = doc['needs_save']
    require(group.exact(expected, doc), 'Historical owned document identity differs')
    return baseline


def partial_parameters(before):
    result = original.projected(before)
    result['144']['finish'].update(FirstDepthCut=.3, MaxDepthCut=.3)
    result['144']['leads']['lead_out']['GetIsSameLeadinout'] = False
    return result


def verify_partial(baseline, failed, capture, direct):
    original.verify_route(baseline, capture['state'], assigned=True, generated=False)
    expected = partial_parameters(baseline['pocket_parameters'])
    observed = original.normalize_nc_roundoff(expected, original.projected(capture['parameters']))
    require(group.exact(expected, observed), 'Partial parameters changed outside the verified prefix')
    require(group.exact(capture['startpoints'], baseline['pocket_startpoints'])
        and group.exact(capture['catalogue'], baseline['neck_tool_checkpoint']['catalogue']),
        'Partial startpoint or nineteen-tool catalogue differs')
    wanted = deepcopy(failed['initial_fields'])
    for spec in PREFIX_FIELDS: wanted[spec[0]] = deepcopy(spec[6])
    require(group.exact(direct, wanted), 'Partial direct values differ from the four-action prefix')
    require(group.exact(direct['previous_allowance'], UNCHANGED_FIELD[6]), 'Unchanged allowance must already match the recipe')
    return observed


def marker_path(source, sha, failed_sha):
    return common.local_evidence_root() / ('pocket_finish_continue_' + _digest(dict(scope=SCOPE,
        source=common._key(source), source_sha256=sha, failed_receipt_sha256=failed_sha)) + '.json')


class Journal(original.Journal):
    def marker_state(self):
        r = self.report
        return dict(super().marker_state(), scope=SCOPE, failed_receipt_pin=r['failed_receipt_pin'],
            inherited_action_count=4, new_action_count=len(r['actions']), automatic_replay=False)


def validate_request(request):
    require(type(request) is dict and set(request) == {'action','params'}
        and request['action'] == 'continue_partial_pocket_finish', 'Exact explicit partial continuation required')
    p = request['params']; require(type(p) is dict and set(p) == PARAMS, 'Exact continuation fields required')
    require(type(p['process_id']) is int and p['process_id'] > 0, 'Owned PID required')
    for key,value in p.items():
        if key.endswith('_path'): require(type(value) is str and Path(value).is_absolute(), 'Absolute evidence/source path required')
        if key.endswith('_sha256'): require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value), 'Exact SHA256 required')
    require(p['expected_module_sha256'] == _file_hash(__file__), 'Current continuation module hash differs')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']), 'Exact CAM CLSID required')
    return deepcopy(p)


def failed_evidence(p):
    failed,pin = read_pin(p['failed_receipt_path'],p['failed_receipt_sha256'])
    validate_failed(failed)
    module = common._pin(p['original_module_archive_path'])
    marker = common._pin(p['original_marker_path'])
    require(module['sha256'] == p['original_module_archive_sha256'] == failed['module_pin']['sha256'] == _file_hash(original.__file__)
        and marker['sha256'] == p['original_marker_sha256'], 'Exact original writer/marker archives required')
    mark,_ = read_pin(marker['path'],marker['sha256'])
    require(group.exact(mark, original.Journal(failed,failed['receipt_path'],Path(marker['path'])).marker_state()),
        'Original immutable once marker differs')
    common._check(failed['live_pins']); common._check(failed['offline_proof_pins']); common._check(failed['bootstrap_export_pins'])
    return failed,pin,module,marker


def load_inputs(p):
    failed,failedpin,modulepin,markerpin = failed_evidence(p)
    require(failed['process_id'] == p['process_id'] and common._key(failed['source_path']) == common._key(p['expected_document_path'])
        and failed['initial_source_sha256'] == p['expected_source_sha256'] == _file_hash(p['expected_document_path']),
        'Exact unchanged saved source and owned process required')
    baseline = deepcopy(failed['loaded_context_before'])
    recipe,recipepin = read_pin(failed['recipe_pin']['path'],failed['recipe_pin']['sha256']); original.validate_recipe(recipe)
    # A completed CL adapter is not called by the resumed writer or its readers.
    retired = [x for x in baseline['pins'] if Path(x['path']).name == 'sw_cam_pocket_rough_exports.py']
    require(len(retired) == 1, 'Exact completed rough CL phase pin required')
    live = common._merge([x for x in baseline['pins'] if x not in retired],[common._pin(__file__)])
    offline = common._merge(baseline['offline_export_proof_pins'],retired,[failedpin,modulepin,markerpin,recipepin])
    require(len(live) <= 64, 'Bounded continuation live closure required')
    baseline.update(pins=live,offline_export_proof_pins=offline)
    runtime = deepcopy(baseline)
    runtime['state']['document'] = deepcopy(failed['current_document'])
    next(x for x in runtime['state']['operations'] if x['native_id']==144)['assigned_tool'] = original.wanted_assignment(baseline)
    runtime['current_context_sha256'] = _digest(group.current_projection(runtime))
    common._check(live); common._check(offline)
    return baseline,runtime,failed,failedpin,modulepin,markerpin


def prepare(p,baseline,runtime,failed,failedpin,modulepin,markerpin,audit):
    receipt = common._local_receipt(p['receipt_path']); marker = marker_path(p['expected_document_path'],p['expected_source_sha256'],failedpin['sha256'])
    paths = [receipt,marker] + [Path(p['progress_path']).with_name(Path(p['progress_path']).stem+'.'+label+'.json')
        for label in ('partial_reconcile','configured','generated','saved')]
    protected = {common._key(x['path']) for x in runtime['pins'] + runtime['offline_export_proof_pins'] + runtime['bootstrap_export_pins']}
    protected.add(common._key(p['expected_document_path']))
    require(len({common._key(x) for x in paths}) == len(paths) and not protected.intersection(common._key(x) for x in paths), 'Evidence aliases protected input')
    require(all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths), 'Fresh continuation evidence/marker required')
    r = dict(schema_version=1,scope=SCOPE,status='prepared',phase='prepared',actions={},process_id=p['process_id'],
        source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],receipt_path=str(receipt),
        module_pin=common._pin(__file__),recipe_pin=deepcopy(failed['recipe_pin']),parent_pin=deepcopy(baseline['parent_pin']),
        failed_receipt_pin=failedpin,original_module_archive_pin=modulepin,original_marker_pin=markerpin,
        loaded_context_before=deepcopy(baseline),live_pins=deepcopy(runtime['pins']),offline_proof_pins=deepcopy(runtime['offline_export_proof_pins']),
        bootstrap_export_pins=deepcopy(runtime['bootstrap_export_pins']),setter_interface_audit=audit,
        inherited_actions=deepcopy(failed['actions']),inherited_action_count=4,new_action_count=0,
        initial_headers=deepcopy(failed['initial_headers']),initial_parameters=deepcopy(failed['initial_parameters']),
        initial_catalogue=deepcopy(failed['initial_catalogue']),initial_fields=deepcopy(failed['initial_fields']),
        reused_initial_captures=True,reused_full_capture_count=1,actual_full_capture_count=0,
        mutation_attempted=False,configuration_readback_verified=False,readback_verified=False,model_saved=False,
        phase_proofs_verified=False,unchanged_previous_allowance_verified=False,**{k:False for k in original.FORBIDDEN})
    return r,marker


def run_backend(backend,journal,baseline,failed):
    r = journal.report
    try:
        backend.start()
        headers = backend.headers('partial_reconcile')
        r['reconciled'] = dict(state=deepcopy(headers),**backend.parameters('partial_reconcile'),catalogue=backend.catalogue())
        r['reconciled_fields'] = {spec[0]:backend.field(spec) for spec in original.FIELDS}
        verify_partial(baseline,failed,r['reconciled'],r['reconciled_fields'])
        r['partial_state_readback_verified'] = True
        r['unchanged_previous_allowance_verified'] = True; journal.persist()
        for spec in REMAINING_FIELDS:
            require(group.exact(backend.field(spec),r['reconciled_fields'][spec[0]]), 'Field drifted before its remaining setter')
            original.action(backend,journal,'field:'+spec[0],lambda pending,spec=spec:backend.set_field(spec,pending),
                lambda spec=spec:backend.field(spec),spec[6])
        r['configured'] = backend.capture_narrow('configured')
        original.verify_capture(baseline,r['configured'],configured=True,generated=False)
        r['configuration_readback_verified'] = True; journal.persist()
        original.generate_and_save(backend,journal,baseline)
        r['new_action_count'] = len(r['actions'])
        require(set(r['actions']) == set(NEW_ACTIONS), 'Continuation dispatched outside remaining fields/GTP/Save')
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try: backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
        journal.persist()
    return r


def validate_terminal(r):
    require(r['scope'] == SCOPE and r['status'] == 'review_required' and r['phase'] == 'finished'
        and all(r.get(k) is True for k in ('readback_verified','configuration_readback_verified','model_saved',
            'phase_proofs_verified','partial_state_readback_verified','unchanged_previous_allowance_verified'))
        and r['actual_full_capture_count'] == 1 and r['inherited_action_count'] == 4 and r['new_action_count'] == 13,
        'Complete bounded continuation and single saved result required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error'))
        and all(r[k] is False for k in original.FORBIDDEN), 'Uncertain or expanded continuation cannot become saved authority')
    require(set(r['actions']) == set(NEW_ACTIONS), 'Only the eleven remaining fields, GTP and Save are permitted')
    failed,_,_,_ = failed_evidence(dict(failed_receipt_path=r['failed_receipt_pin']['path'],
        failed_receipt_sha256=r['failed_receipt_pin']['sha256'],
        original_module_archive_path=r['original_module_archive_pin']['path'],
        original_module_archive_sha256=r['original_module_archive_pin']['sha256'],
        original_marker_path=r['original_marker_pin']['path'],original_marker_sha256=r['original_marker_pin']['sha256']))
    require(group.exact(r['inherited_actions'],failed['actions']) and set(r['actions']) == set(NEW_ACTIONS), 'Inherited prefix or new action inventory changed')
    for key in ('initial_headers','initial_parameters','initial_catalogue','initial_fields'):
        require(group.exact(r[key],failed[key]), 'Reused historical capture changed')
    baseline = r['loaded_context_before']
    require(group.exact(group.current_projection(baseline),group.current_projection(failed['loaded_context_before']))
        and group.exact(baseline['pocket_parameters'],failed['loaded_context_before']['pocket_parameters']), 'Historical current baseline changed')
    verify_partial(baseline,failed,r['reconciled'],r['reconciled_fields'])
    for a in r['actions'].values(): verified_action(a)
    for spec in REMAINING_FIELDS:
        require(group.exact(r['actions']['field:'+spec[0]]['observed'],spec[6]), 'New direct readback changed')
    for key,generated in (('configured',False),('generated',True),('final',True)):
        counts = original.verify_capture(baseline,r[key],configured=True,generated=generated,
            saved_sha=r['saved_source_sha256'] if key=='final' else None)
        if generated:require(group.exact(counts,r['generated_record_counts']), 'Saved path count differs')
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'], 'Single Save readback missing')
    require(r['source_transition']['strict_save_return']==0 and r['source_transition']['source_before_sha256']==r['initial_source_sha256']
        and r['source_transition']['source_after_sha256']==r['saved_source_sha256'], 'Saved source transition differs')
    original.equivalent_projection(original.save_projection(r['generated']),original.save_projection(r['final']))
    clean_events(r)
    return original.make_context(r)


def execute(sw,clsid,typelib,*,baseline,runtime,failed,params,report,marker):
    journal=Journal(report,params['receipt_path'],marker);_write_receipt(params['receipt_path'],report,create=True)
    backend=original.NativeBackend(runtime,params,sw,clsid,typelib,report,journal.persist)
    result=run_backend(backend,journal,baseline,failed)
    try:
        common._check(runtime['offline_export_proof_pins']);common._check(runtime['bootstrap_export_pins']);result['phase_proofs_verified']=True
        if result.get('readback_verified') is True:
            context=validate_terminal(result);result['checkpoint_digest']=_digest(group.current_projection(context));journal.persist()
            result['marker_pin']=common._pin(marker);journal.persist()
            require(result['marker_pin']['sha256']==_file_hash(marker),'Stable continuation marker required')
    except Exception as exc:result.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
    journal.persist();return result


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id
        and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved continuation source/process differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    context=validate_terminal(r);require(r['checkpoint_digest']==_digest(group.current_projection(context)), 'Saved continuation digest differs')
    marker=marker_path(r['source_path'],r['initial_source_sha256'],r['failed_receipt_pin']['sha256'])
    mark,markpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(mark,Journal(r,path,marker).marker_state()), 'Exact immutable terminal marker differs')
    live=common._merge([x for x in r['live_pins'] if common._key(x['path'])!=common._key(r['parent_pin']['path'])],[pin])
    require(len(live)<=64,'Bounded completed continuation closure required')
    context.update(pins=live,offline_export_proof_pins=common._merge(r['offline_proof_pins'],[r['parent_pin'],markpin]),parent_pin=pin,group_marker_pin=markpin)
    return context


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);baseline,runtime,failed,failedpin,modulepin,markerpin=load_inputs(p)
    registration=common.discover_export_registration(runtime,p['addin_clsid']);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=original.audit_recipe(typelib,runtime['generated_pin'])
    report,marker=prepare(p,baseline,runtime,failed,failedpin,modulepin,markerpin,audit)
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(runtime['pins']),
        inherited_action_count=4,remaining_field_count=len(REMAINING_FIELDS),new_action_count=len(NEW_ACTIONS),marker=str(marker),setter_interface_audit=audit)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(runtime['pins']);common._check(runtime['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,registration['clsid'],typelib,baseline=baseline,runtime=runtime,failed=failed,params=p,report=report,marker=marker)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args(argv);result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
