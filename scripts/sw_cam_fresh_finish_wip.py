"""Export one all-setups WIP from a saved fresh Finish and completed CL proof."""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_fresh_finish_recipe as saved
from scripts import sw_cam_finish_lengths as lengths
from scripts import sw_cam_completed_gtp_wip as core
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_rough_firstcut import require
common,group,protected=saved.common,saved.group,lengths.protected
SCOPE='SAVED_FRESH_FINISH_WIP_EXPORT_V1'
PARAMS=lengths.PARAMS|{'CL_receipt_path','CL_receipt_sha256','baseline_wip_path','baseline_wip_sha256','baseline_receipt_path','baseline_receipt_sha256','project_root','output_dir'}


def validate_CL(r,loaded,p):
    require(r['scope']=='SAVED_FRESH_FINISH_CL_EXPORT_V1' and r['status']=='review_required' and r['phase']=='finished'
        and r['native_dispatch_pending'] is False,'Completed exact fresh Finish CL required')
    for name in ('native_call_returned','readback_verified','output_verified','phase_proofs_verified_after_export','protected_streams_verified','checkpoint_export_readback_verified'):require(r[name] is True,'CL proof incomplete: '+name)
    for name in ('model_saved','GTP_attempted','GOP_attempted','AFR_attempted','simulation_attempted','stock_edit_attempted','tool_edit_attempted','setter_attempted','assignment_attempted','automatic_replay'):require(r[name] is False,'Unexpected CL side effect: '+name)
    require(not any(k in r for k in ('issue','failed_phase','cleanup_error','receipt_write_error')),'Uncertain CL cannot anchor WIP')
    require(r['process_id']==p['process_id'] and r['saved_checkpoint_pin']['sha256']==p['checkpoint_receipt_sha256']
        and common._key(r['saved_checkpoint_pin']['path'])==common._key(p['checkpoint_receipt_path']),'CL owner/parent differs')
    before=r['before'];require(group.exact(before,r['after']) and group.exact(before['mill_state'],loaded['state']),'CL saved state differs')
    a=loaded['fresh_finish_result'];association=r['protected_stream_association']
    require(before['selected_operation_native_id']==a['native_id'] and before['selected_feature_native_id']==a['feature_native_id']
        and before['expected_toolpath_record_counts']==a['record_counts'],'CL selected result differs')
    require(association['prior_five_complete_streams_unchanged'] is True and association['added_block']==5
        and association['added_operation_native_id']==a['native_id']
        and association['unchanged']==[dict(native_id=oid,old_block=i,new_block=i) for i,oid in enumerate([267,247,248,271,143])],'Protected CL stream association differs')
    expected=[dict(operation_native_id=row['native_id'],toolpath_record_counts=row['toolpath_record_counts']) for row in loaded['state']['operations'] if row['toolpath_generated'] is True]
    require(before['expected_generated_operations']==expected and [x['operation_native_id'] for x in expected]==[267,247,248,271,143,a['native_id']],'Exact six-path order required')
    return expected


def validate_baseline(receipt,prior_CL,wip_pin,expected):
    require(receipt['scope']=='SAVED_ROUGH_POCKET_WIP_EXPORT_V1' and receipt['status']=='review_required' and receipt['phase']=='finished','Completed prior rough WIP required')
    for name in ('readback_verified','export_files_verified','checkpoint_export_readback_verified','phase_proofs_verified_after_export'):require(receipt[name] is True,'Baseline WIP proof incomplete')
    for name in ('GTP_attempted','GOP_attempted','model_saved','setter_attempted','assignment_attempted','automatic_replay'):require(receipt[name] is False,'Baseline WIP unexpected action')
    require(type(receipt['native_call_count']) is int and receipt['native_call_count']==1 and receipt['native_scope']=='all_wip_parts_all_setups'
        and receipt['single_operation_scope_claimed'] is False and type(receipt['export_quality_raw']) is int and receipt['export_quality_raw']==0,'Exact whole-machine FINE baseline required')
    require(receipt['expected_generated_operations']==expected[:5] and group.exact(receipt['before'],receipt['after']),'Baseline five-path route differs')
    prior_state=prior_CL['before']['mill_state'];require(receipt['source_sha256']==receipt['before']['saved_file_sha256']==prior_state['saved_file_sha256']
        and receipt['saved_checkpoint_pin']['sha256']==prior_CL['saved_checkpoint_pin']['sha256'],'Baseline source/checkpoint differs from protected CL')
    files=receipt['files'];require(type(files) is list and len(files)==1 and files[0]['sha256']==wip_pin['sha256'] and files[0]['bytes']==wip_pin['bytes']
        and files[0]['stl_extension'] is True and wip_pin['bytes']>0,'Baseline STL differs')


def scope_pins(loaded,runtime):
    names={'sw_cam_fresh_finish_recipe.py','sw_cam_fresh_finish_field_batch.py','sw_cam_chamfer_insert_defaults.py','sw_cam_finish_defaults_progress.py'}
    retired=[p for p in loaded['pins'] if Path(p['path']).name in names]
    require({Path(p['path']).name for p in retired}==names,'Exact unused writer/default-reader proof roles required')
    loaded['pins']=common._merge([p for p in loaded['pins'] if p not in retired],runtime)
    loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],retired)
    require(1<=len(loaded['pins'])<=64,'WIP live evidence exceeds existing guard bound')
    return retired


def marker_path(p):
    return common.local_evidence_root()/('fresh_finish_wip_'+_digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),source_sha256=p['expected_source_sha256'],operation_native_id=p['operation_native_id']))+'.json')


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='export_saved_fresh_finish_wip','Exact WIP action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact WIP parameters required')
    for k in ('process_id','operation_native_id','feature_native_id'):require(type(p[k]) is int and 0<p[k]<2**31,'Strict identity required')
    for k,v in p.items():
        if k.endswith('_path') or k in ('project_root','output_dir'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'WIP module changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM registration required');return p


def prepare(p):
    loaded=saved.load_completed(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],**{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')});lengths.authority(loaded,p)
    CL,cpin=read_pin(p['CL_receipt_path'],p['CL_receipt_sha256']);expected=validate_CL(CL,loaded,p)
    common._check([CL['output'],CL['protected_cl_pin'],CL['protected_cl_recovery_pin']])
    prior,priorpin=read_pin(CL['protected_cl_receipt_pin']['path'],CL['protected_cl_receipt_pin']['sha256'])
    baseline,bpin=read_pin(p['baseline_receipt_path'],p['baseline_receipt_sha256']);wip=common._pin(p['baseline_wip_path']);wip['bytes']=Path(wip['path']).stat().st_size
    require(wip['sha256']==p['baseline_wip_sha256'] and Path(wip['path']).suffix.casefold()=='.stl','Exact baseline STL required');validate_baseline(baseline,prior,wip,expected)
    retired=scope_pins(loaded,[common._pin(__file__),common._pin(lengths.__file__),common._pin(protected.__file__),common._pin(core.__file__)])
    loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],[cpin,priorpin,bpin,wip,CL['output'],CL['protected_cl_pin'],CL['protected_cl_recovery_pin']])
    for name in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
    reg=common.discover_export_registration(loaded,p['addin_clsid']);tlb=str(Path(reg['addin_path']).parent/'camworks.tlb')
    marker=marker_path(p);directory,canonical=core.output_plan(p['output_dir'],p['project_root'],p['receipt_path'],p['expected_document_path'],loaded['pins']+loaded['offline_export_proof_pins'],marker)
    return dict(loaded=loaded,CL_pin=cpin,baseline_receipt_pin=bpin,baseline_wip_pin=wip,expected_generated_operations=expected,retired=retired,registration=reg,typelib_path=tlb,marker=marker,directory=directory,canonical=canonical)


def capture_compact(backend,doc,machine,p,label,report,persist):
    def retained():
        backend.events();require(_member(doc,'GetDocType')==1 and _member(machine,'MachType')==1,'Retained MILL binding changed');backend.events()
    def progress(name,returned):report.update(current_read=name,read_dispatch_pending=not returned)
    batch=lengths.ReadBatch(backend.sw,backend.typelib_path,generated_pin=backend.loaded['generated_pin'],progress=progress,process_id=p['process_id'],expected_document=backend.ctx.identity(),source_sha256=p['expected_source_sha256'],evidence_pins=backend.loaded['pins'],verify_evidence=backend.ctx.files,verify_owned_process=backend.ctx.owned,check_events=backend.events,retained_objects=(doc,machine),verify_retained_binding=retained,max_native_calls=400)
    try:
        with batch:
            inventory=lengths.inventory(doc,machine,read=batch.read,typed=batch.typed)
            row,_,_=protected.binding(doc,backend.loaded['state'],p['operation_native_id'],p['feature_native_id'],read=batch.read,typed=batch.typed)
            require(group.exact(inventory,lengths.projected_inventory(backend.loaded['state'])),'Saved compact inventory differs')
        batch.require_complete()
    finally:report.setdefault('read_batches',[]).append(dict(label=label,summary=batch.summary()));persist()
    state=dict(document=backend.ctx.identity(),saved_file_sha256=_file_hash(p['expected_document_path']),inventory=inventory,selected=row)
    require(state['document']==backend.loaded['state']['document'] and state['saved_file_sha256']==p['expected_source_sha256'],'Clean source changed')
    return state,{'machine':machine}


def run(sw,p,plan):
    loaded=plan['loaded'];directory,canonical=plan['directory'],plan['canonical'];report=dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],operation_native_id=p['operation_native_id'],feature_native_id=p['feature_native_id'],saved_checkpoint_pin=loaded['parent_pin'],CL_receipt_pin=plan['CL_pin'],baseline_wip_pin=plan['baseline_wip_pin'],baseline_wip_receipt_pin=plan['baseline_receipt_pin'],expected_generated_operations=plan['expected_generated_operations'],native_scope='all_wip_parts_all_setups',single_operation_scope_claimed=False,native_method='ICWMachine5.CreateSTLOfWIPs2',native_parameters=[str(directory)+'\\','wip.stl','',0,0],export_quality_raw=0,export_quality_label='FINE',native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,native_call_count=0,mutation_attempted=False,readback_verified=False,export_files_verified=False,files=[],GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,model_saved=False,setter_attempted=False,assignment_attempted=False,simulation_attempted=False,automatic_replay=False,automatic_retry=False,geometry_verified=False,geometry_acceptance_complete=False,mesh_error_bound_qualified=False,temporal_collision_verified=False,production_qualified=False,phase_proofs_verified_after_export=False,checkpoint_export_readback_verified=False,runtime_pins=loaded['pins'],offline_export_proof_pins=loaded['offline_export_proof_pins'],retired_offline_proof_pins=plan['retired'],marker_path=str(plan['marker']))
    persist=lambda:_write_receipt(p['receipt_path'],report);_write_receipt(p['receipt_path'],report,create=True)
    backend=group.NativeBackend(loaded,p,sw,plan['registration']['clsid'],plan['typelib_path'],report,persist)
    try:
        backend.start()
        with backend.ctx.guard() as g:
            active=g.read(backend.ctx.app,'IGetActiveDoc');doc=g.typed(active,'ICWDoc3');part=g.typed(active,'ICWPartDoc');machine=g.typed(g.read(part,'IGetMachine'),'ICWMachine')
            require(g.read(doc,'GetDocType')==1 and g.read(machine,'MachType')==1,'Exact MILL document required')
        directory.mkdir();require(directory.resolve(strict=True)==canonical,'WIP output directory identity changed')
        def claim():
            require(not any(directory.iterdir()) and directory.resolve(strict=True)==canonical,'WIP output changed before dispatch')
            _write_receipt(plan['marker'],dict(scope=SCOPE,source_sha256=p['expected_source_sha256'],operation_native_id=p['operation_native_id'],receipt_path=p['receipt_path'],output_dir=str(directory),status='native_export_claimed_no_replay'),create=True)
        def invoke(owner):return _member(owner,'CreateSTLOfWIPs2',*report['native_parameters'])
        core.run_one_wip_export(report,capture=lambda label:capture_compact(backend,doc,machine,p,label,report,persist),guard_factory=backend.ctx.guard,persist=persist,claim=claim,invoke=invoke,collect=lambda:core.collect_wip_files(directory,canonical))
        backend.finish()
        require(backend.ctx.identity()==loaded['state']['document'] and core.collect_wip_files(directory,canonical)==report['files'],'WIP/source changed after cleanup')
        for name in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
        report.update(status='review_required',phase='finished',phase_proofs_verified_after_export=True,checkpoint_export_readback_verified=True)
    except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,export_files_verified=False)
    finally:protected.close_and_observe(backend,report,persist)
    return report


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(plan['loaded']['pins']),expected_generated_operations=plan['expected_generated_operations'],native_parameters=[str(plan['directory'])+'\\','wip.stl','',0,0],retired_offline_proof_pins=plan['retired'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return run(sw,p,plan)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','phase','readback_verified','files','issue','native_called')}));return 0 if r.get('readback_verified') or r.get('status')=='validated_offline' else 1
if __name__=='__main__':raise SystemExit(main())
