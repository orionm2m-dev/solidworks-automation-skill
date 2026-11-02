"""One serial CAM snapshot21/12 and exact18 CL; no model Save or host calls."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
from scripts import sw_cam_saved18_restarted_dirty_verify as dirty
from scripts import sw_cam_local_optimization as opt
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
common,group,require=opt.common,opt.group,opt.require
SCOPE='SAVED_EIGHTEEN_SERIAL_OBSERVED_DIRTY_REBIND_V1'
ACTION='verify_saved_eighteen_serial_dirty'
ACK='verify_observed_dirty21_12_export18_no_save_no_gtp_no_host_no_replay'
DIRTY_SHA='ab4f20647188adde419f25189a8c265e12d77251ee7ce309a76d25115cf2b1e4'
PARAMS={'process_id','expected_document_path','expected_source_sha256','dirty_request_path','dirty_request_sha256','host_failure_path','host_failure_sha256','module_sha256','receipt_path','saved_cl_path','acknowledgement'}

def forbidden(*args,**kwargs):raise ValueError('Mutation or host operation forbidden in serial saved-state verification')

class ReadOnlyParameters(opt.native.base.NativeBackend):
    insert=assign=set_field=set_nc=generate=save=forbidden
    def __init__(self,*args):
        super().__init__(*args,before_generate=forbidden,exporter=forbidden)
        self.learned=deepcopy(self.loaded['deep_targets'])

def failed_host_contract(r,loaded,original):
    require(r.get('scope')==dirty.SCOPE and r.get('status')=='error'and r.get('phase')=='finished','Completed read-only host failure required')
    require(r.get('module_pin',{}).get('sha256')==DIRTY_SHA and r.get('read_only')is True,'Exact failed read-only producer required')
    require(r.get('identity_attempted')is True and 'identity'in r,'Observed host identity required')
    require(r['ownership']==loaded['ownership']and r['source_sha256']==loaded['source_sha256'],'Failed attempt belongs to another source or process')
    for key,value in original['params'].items():require(group.exact(r['request'][key],value),'Failed request lineage differs')
    require(all(r.get(k)is False for k in ('mutation_attempted','model_saved','GTP_attempted','host_load_attempted','registration_attempted','readback_verified','persistence_after_reopen_verified','automatic_replay','production_qualified')),'Failed host attempt had an unexpected side effect or acceptance')
    require(not any(k in r for k in ('events_before','events_after','mill_read_attempted','raw_host_response','host_response','projection','cl_export','cl_verification','cleanup_issue','cleanup_session_active')),'Host failure reached CAM; no serial fallback replay is authorized')
    require(r['identity']['loaded_artifact']=='old','Only the observed old host identity failure is supported')
    return dict(original_status='error',original_receipt_modified=False,host_identity_observed=deepcopy(r['identity']),host_native_compatibility_qualified=False,CAM_read_attempted=False)

def marker_path(p):
    key='\0'.join((SCOPE,common._key(p['expected_document_path']),p['expected_source_sha256'],str(p['process_id']),p['host_failure_sha256']))
    return Path(p['receipt_path']).with_name('serial_saved18_'+hashlib.sha256(key.encode()).hexdigest()+'.json')

def partition(loaded,extra):
    opt.partition_pins(loaded,extra)
    this=common._pin(__file__);loaded['pins']=common._merge(loaded['pins'],[this])
    loaded['phase_proof_pins']=[v for v in loaded['phase_proof_pins']if common._key(v['path'])!=common._key(this['path'])]
    require(len(loaded['pins'])<=63,'Serial native closure plus current source exceeds shared64 bound')
    loaded['pin_partition'].update(live_file_count=len(loaded['pins']),maximum_with_source=len(loaded['pins'])+1,phase_proof_count=len(loaded['phase_proof_pins']),serial_read_only_adapter=True)
    common._check(loaded['pins']);common._check(loaded['phase_proof_pins'])

def prepare(request,*,completed=False):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact serial verification action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS and p['acknowledgement']==ACK,'Exact serial verification parameters required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Owned positive PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute paths required')
        if key.endswith('_sha256'):opt.prior._sha(value)
    require(p['module_sha256']==opt.prior._file_hash(__file__)and common._pin(dirty.__file__)['sha256']==DIRTY_SHA,'Frozen serial/lineage implementations required')
    original,requestpin=opt.prior.read_json_pin(p['dirty_request_path'],p['dirty_request_sha256'])
    # Native-free original preparation rechecks exact source, verified process
    # transition and raw dirty observation. Its host routines are never invoked.
    oldp,loaded,q,old,new,ref,pins,*_=dirty.prepare(original,completed=True)
    require(loaded['ownership']['process_id']==p['process_id']and loaded['source_sha256']==p['expected_source_sha256']and common._key(loaded['guide_parameters']['document']['path'])==common._key(p['expected_document_path']),'Exact owned current source/document required')
    require(loaded['guide_parameters']['document']['needs_save']is True,'Observed dirty input must remain explicit')
    failed,failedpin=opt.prior.read_json_pin(p['host_failure_path'],p['host_failure_sha256'])
    history=failed_host_contract(failed,loaded,original)
    extra=common._merge(pins,[requestpin,failedpin,common._pin(dirty.__file__)])
    partition(loaded,extra)
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    tlb=str(Path(loaded['registration']['addin_path']).parent/'camworks.tlb')
    guard=opt.prior.guard_reuse.guard_constructor_preflight(p,loaded,tlb)
    loaded['serial_verification']=dict(dirty_request_pin=requestpin,host_failure_pin=failedpin,host_failure_history=history,native_guard_preflight=guard)
    out=common._local_receipt(p['receipt_path']);mark=marker_path(p)
    clpath=Path(p['saved_cl_path'])if completed else opt.cl._fresh_path(p['saved_cl_path'])
    protected={common._key(v['path'])for v in loaded['pins']+loaded['phase_proof_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in (out,mark,clpath)})==3,'Distinct serial outputs required')
    for v in (out,mark,clpath):require(not v.is_symlink()and common._key(v)not in protected and(completed or not v.exists()),'Existing or aliased serial output forbids replay')
    require(out.parent.is_dir(),'Existing local receipt directory required')
    return p,loaded,q,tlb,out,mark

def run_prepared(prepared,*,backend=None,sw=None):
    p,l,q,tlb,out,mark=prepared
    require(not out.exists()and not mark.exists(),'Serial attempt may not be replayed or overwritten')
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request={k:deepcopy(p[k])for k in PARAMS},module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=deepcopy(l['ownership']),serial_verification=deepcopy(l['serial_verification']),qualified_authority_pin=deepcopy(l['qualified_authority_pin']),read_only=True,clean=False,observed_dirty=True,host_native_compatibility_qualified=False,host_read_attempted=False,host_load_attempted=False,registration_attempted=False,mutation_attempted=False,model_saved=False,GTP_attempted=False,readback_verified=False,persistence_after_reopen_verified=False,automatic_replay=False,production_qualified=False,document_boundaries=[],live_pins=deepcopy(l['pins']),phase_proof_pins=deepcopy(l['phase_proof_pins']),pin_partition=deepcopy(l['pin_partition']))
    _write_receipt(mark,dict(scope=SCOPE,status='pending',receipt_path=str(out),automatic_replay=False),create=True)
    def persist():_write_receipt(out,r,create=not out.exists())
    persist();b=backend or ReadOnlyParameters(l,p,sw,l['registration']['clsid'],tlb,r,persist)
    def boundary(label):
        b.boundary();doc=b.ctx.identity()
        require(group.exact(doc,l['guide_parameters']['document'])and doc['needs_save']is True,'Observed dirty document changed during serial verification')
        require(opt.prior._file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Saved source changed during read-only verification')
        r['document_boundaries'].append(dict(label=label,document=deepcopy(doc),source_sha256=p['expected_source_sha256']));persist()
    try:
        b.start();boundary('before_parameters');r['phase']='serial_parameters';r['parameter_read_attempted']=True;persist()
        r['snapshot']=b.capture_snapshot('serial_rebind21_12',full=True);persist()
        require(group.exact(r['snapshot'],l['current_snapshot']),'Complete current21/12 differs from saved source')
        boundary('after_parameters');r['phase']='export18';r['cl_export']={};persist()
        opt.cl.export_current_cl(b,'serial_rebind18',r['snapshot']['binding'],p['saved_cl_path'],r['cl_export'])
        output=r['cl_export']['output'];expected=q['saved_cl']['output']
        require(output['sha256']==expected['sha256']and output['bytes']==expected['bytes'],'All18 native CL bytes differ from saved authority')
        r['cl_verification']=dict(all18_complete_streams_bit_identical=True,expected_output=deepcopy(expected),actual_output=deepcopy(output));boundary('after_export')
        b.finish();r.update(status='saved_eighteen_serial_dirty_verified',phase='finished',readback_verified=True,persistence_after_reopen_verified=True,saved_cam_equivalence_verified=True,source_unchanged_verified=True,verified_counts=dict(operations=21,parameters=12,features=6,paths=18));persist()
    except Exception as exc:r.update(status='error',phase='finished',issue=_error(exc),readback_verified=False,persistence_after_reopen_verified=False)
    finally:
        try:opt.generation.close_checked(b,r)
        except Exception as exc:r.update(status='error',cleanup_issue=_error(exc),readback_verified=False,persistence_after_reopen_verified=False)
        persist();_write_receipt(mark,dict(scope=SCOPE,status=r['status'],receipt_pin=common._pin(out),automatic_replay=False))
    return r

def validate_completed(r,loaded,q):
    require(r.get('scope')==SCOPE and r.get('status')=='saved_eighteen_serial_dirty_verified'and r.get('phase')=='finished','Completed serial dirty verification required')
    require(all(r.get(k)is True for k in ('read_only','observed_dirty','readback_verified','persistence_after_reopen_verified','saved_cam_equivalence_verified','source_unchanged_verified','parameter_read_attempted')),'All serial verification facts required')
    require(all(r.get(k)is False for k in ('clean','host_native_compatibility_qualified','host_read_attempted','host_load_attempted','registration_attempted','mutation_attempted','model_saved','GTP_attempted','automatic_replay','production_qualified')),'Serial authority must not claim host qualification or mutation')
    require(not any(k in r for k in ('issue','cleanup_issue','terminal_issue')),'Unresolved read-only state')
    opt.prior.clean_events(r)
    require(group.exact(r['ownership'],loaded['ownership'])and r['source_sha256']==loaded['source_sha256']==q['source_sha256']and common._key(r['source_path'])==common._key(loaded['guide_parameters']['document']['path']),'Serial owner/source/document mismatch')
    require(group.exact(r['qualified_authority_pin'],loaded['qualified_authority_pin'])and group.exact(r['serial_verification'],loaded['serial_verification']),'Exact serial lineage required')
    require(group.exact(r['snapshot'],loaded['current_snapshot'])and r['verified_counts']==dict(operations=21,parameters=12,features=6,paths=18),'Exact saved21/12/6 snapshot required')
    require([v['label']for v in r['document_boundaries']]==['before_parameters','after_parameters','after_export']and all(group.exact(v['document'],loaded['guide_parameters']['document'])and v['document']['needs_save']is True and v['source_sha256']==q['source_sha256']for v in r['document_boundaries']),'Stable raw dirty identity required')
    e=r['cl_export'];opt.cl._verified(e)
    require(e['source_sha256']==q['source_sha256']and e['output']['sha256']==q['saved_cl']['output']['sha256']and e['output']['bytes']==q['saved_cl']['output']['bytes'],'Exact saved18 native export required')
    require(e['expected_generated_operations']==q['saved_cl']['expected_generated_operations']and r['cl_verification']==dict(all18_complete_streams_bit_identical=True,expected_output=q['saved_cl']['output'],actual_output=e['output']),'Exact complete18 CL linkage required')
    require([v['phase']for v in r['phase_proof_checks']]==['before_native_start','after_export_and_cleanup']and all(v['verified']is True for v in r['phase_proof_checks']),'Complete read-only phase proofs required')
    return dict(status='serial_observed_dirty_saved_equivalence_verified',counts=r['verified_counts'],host_native_compatibility_qualified=False,model_saved=False,GTP_attempted=False,production_qualified=False)

def dispatch_request(request,*,validate_only=False):
    prepared=prepare(request);p,l,q,tlb,out,mark=prepared
    if validate_only:return dict(status='validated_offline',native_called=False,counts=dict(operations=21,parameters=12,paths=18),pin_partition=l['pin_partition'],native_guard_preflight=l['serial_verification']['native_guard_preflight'],host_native_compatibility_qualified=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=2,process_id=p['process_id']):
        common._check(l['pins']);common._check(l['phase_proof_pins']);sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=run_prepared(prepared,sw=sw)
        if r['readback_verified']is True:
            try:r['terminal_verification']=validate_completed(r,l,q)
            except Exception as exc:r.update(status='error',readback_verified=False,persistence_after_reopen_verified=False,saved_cam_equivalence_verified=False,terminal_issue=_error(exc));_write_receipt(out,r);_write_receipt(mark,dict(scope=SCOPE,status=r['status'],receipt_pin=common._pin(out),automatic_replay=False))
            else:_write_receipt(out,r);_write_receipt(mark,dict(scope=SCOPE,status=r['status'],receipt_pin=common._pin(out),automatic_replay=False))
        return r

def load_completed_rebind(path,digest,*,check_current=True):
    require(check_current is True,'Current exact source verification required')
    r,rpin=opt.prior.read_json_pin(path,digest)
    require(r.get('module_pin')==common._pin(__file__),'Exact serial verification producer required')
    prepared=prepare(dict(action=ACTION,params=deepcopy(r['request'])),completed=True);p,l,q,tlb,out,mark=prepared
    require(common._key(out)==common._key(path),'Serial receipt output path differs')
    proof=validate_completed(r,l,q);require(group.exact(proof,r['terminal_verification']),'Terminal serial contract differs')
    marker=dirty.read_pin(common._pin(mark));require(marker==dict(scope=SCOPE,status=r['status'],receipt_pin=rpin,automatic_replay=False),'Serial completion marker differs')
    l['reopened_checkpoint_pin']=rpin;l['serial_rebind_qualified']=True;l['host_native_compatibility_qualified']=False
    l['checkpoint_pins']=common._merge(l['checkpoint_pins'],[rpin,common._pin(__file__)])
    return l,q,r,common._merge(l['pins'],l['phase_proof_pins'],[rpin,common._pin(mark)])
