"""One WIP18 export from directly verified clean optimized Save authority.

No recursive historical source load. The old source is used only as historical
Save-validator input; the native guard binds solely the new clean saved source.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,inspect,re
from scripts import sw_cam_local_ulp_save as producer
from scripts import sw_cam_deep_guide_wip as legacy
from scripts import sw_cam_finish_lengths as lengths
from scripts import sw_cam_saved18_wip_binding as binding
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
common,group,require=producer.common,producer.group,producer.require
core,generation=legacy.core,legacy.generation
SCOPE='SAVED_OPTIMIZED_EIGHTEEN_WIP_EXPORT_V1'
ACTION='export_saved_optimized_eighteen_wip'
ACK='export_saved18_whole_machine_wip1_no_generation_no_save_no_settings'
PRODUCER_SHA='bb5ae9dfd96f9b475668e42cf2403aa1e9e91fb5a37def248abdaad272f4f319'
BINDING_SHA='86b0951ef543d5cc4dab158dba4fd8e55065d1489547444e5ce3bb513f1f563a'
PARAMS={'process_id','expected_document_path','expected_source_sha256','saved_receipt_path','saved_receipt_sha256','module_sha256','receipt_path','output_dir','project_root','acknowledgement'}


def direct(pin):
    p=Path(pin['path']);require(p.is_absolute()and p.is_file()and not p.is_symlink(),'Regular direct evidence required')
    actual=common._pin(p);require(actual['sha256']==pin['sha256'],'Direct evidence changed')
    if 'bytes'in pin:require(p.stat().st_size==pin['bytes'],'Direct evidence size changed')
    return actual


def read(pin,limit=8*1024*1024):
    direct(pin);return producer.opt.prior.read_json_pin(pin['path'],pin['sha256'],limit=limit)[0]


def parent_authority(path,digest):
    r,rpin=producer.opt.prior.read_json_pin(path,digest,limit=8*1024*1024)
    require(r['module_pin']==common._pin(producer.__file__)and r['module_pin']['sha256']==PRODUCER_SHA,'Exact executed Save producer required')
    require(r['cleanup_session_active']is False and not any(k in r for k in ('issue','cleanup_issue','terminal_issue')),'Completed parent cleanup required')
    direct(dict(path=r['request']['receipt_path'],sha256=digest))
    q=read(r['qualified_receipt_pin']);require(q['source_sha256']==r['source_sha256'],'Historical prior14 context differs')
    old_doc=deepcopy(r['source_transition']['document']);old_doc['needs_save']=True
    historical=dict(optimizer_receipt_pin=deepcopy(r['optimizer_receipt_pin']),ownership=deepcopy(r['ownership']),source_sha256=r['source_sha256'],guide_parameters=dict(document=old_doc),optimization=dict(targets=deepcopy(r['learned_targets']),prior_cl=deepcopy(q['prior_cl'])),ulp_continuation=deepcopy(r['adopted_proof']))
    # Pure terminal validation: old b75 is compared as historical text only.
    terminal=producer.validate_completed(r,historical);require(group.exact(terminal,r['terminal_verification']),'Parent terminal proof differs')
    marker=producer.marker_path(r['request']);markerpin=common._pin(marker)
    observed=read(markerpin);expected=producer.Journal(deepcopy(r),Path(r['request']['receipt_path']),marker)._marker_state()
    require(group.exact(observed,expected),'Parent terminal marker differs')
    cp=deepcopy(r['saved_checkpoint'])
    for key,value in [('source_path',r['source_path']),('source_sha256',r['saved_source_sha256']),('document',r['source_transition']['document']),('snapshot',r['saved']),('saved_cl',r['saved_cl']),('learned_targets',r['learned_targets']),('tool_dimensions',r['tool_dimensions'])]:require(group.exact(cp[key],value),'Canonical saved checkpoint differs: '+key)
    conf=cp['configuration'];require(conf['sw_configuration_name']==r['request']['expected_configuration']and conf['names_consistent']is True and conf['associated_sw_configuration_matches']is True,'Saved configuration differs')
    ids=[v['native_id']for v in cp['tool_catalogue']];require(len(ids)==len(set(ids))==21,'Exact21 tool catalogue IDs required')
    require(r['catalogue_readbacks']and all(v['native_ids']==ids for v in r['catalogue_readbacks']),'Saved catalogue readbacks differ')
    candidates=[v for v in r['phase_proof_pins']if Path(v['path']).name=='ACTUAL_ROOT_SERIAL_TOOL_SAVED_NATIVE.json'];require(len(candidates)==1,'One pinned serial feature-owner metadata receipt required')
    serialpin=candidates[0];serial=read(serialpin);sc=serial['checkpoint']
    owners={str(v['geometry']['native_id']):v['setup_native_id']for v in sc['state']['features']if str(v['geometry']['native_id'])in cp['snapshot']['binding']['features']}
    require(set(owners)==set(cp['snapshot']['binding']['features'])and all(type(v)is int and v>0 for v in owners.values()),'Complete exact feature setup owners required')
    currentpin=dict(path=cp['source_path'],sha256=cp['source_sha256']);direct(currentpin);direct(cp['saved_cl']['output']);direct(q['prior_cl']['output']);direct(r['optimizer_receipt_pin'])
    proof=dict(verified=True,receipt_sha256=rpin['sha256'],source_sha256=cp['source_sha256'],process_id=r['ownership']['process_id'],checkpoint_sha256=binding.digest(cp),producer_terminal=deepcopy(terminal))
    bound=binding.bind_verified_checkpoint(cp,receipt_pin=rpin,terminal_proof=proof,expected_source_sha256=cp['source_sha256'],expected_document_path=cp['source_path'],process_id=r['ownership']['process_id'],verify_direct_pin=direct)
    protected=deepcopy(cp['snapshot']);protected['binding']['operations']=protected['binding']['operations'][:17];protected['parameters']=protected['parameters'][:8]
    for setup in protected['binding']['operation_setups']:setup['operation_count']=sum(o['setup_native_id']==setup['native_id']for o in protected['binding']['operations'])
    generated=[v for v in r['live_pins']if Path(v['path']).name.startswith('_FE488661_0BD8_11D6_2012_2018CE99E55F_')and Path(v['path']).suffix=='.py'];require(len(generated)==1,'Exact generated CAM metadata required')
    bootstrap=[v for v in r['phase_proof_pins']if Path(v['path']).name=='sw_cam_installation.py'];require(len(bootstrap)==1,'Exact installation bootstrap pin required')
    bootstrap_deps=[v for v in r['phase_proof_pins']if Path(v['path']).name=='cad_installation.py'];require(len(bootstrap_deps)==1,'Exact installation dependency pin required')
    directpins=common._merge(bootstrap,bootstrap_deps,[rpin,markerpin,r['qualified_receipt_pin'],r['optimizer_receipt_pin'],serialpin,cp['saved_cl']['output'],q['prior_cl']['output'],common._pin(producer.__file__),common._pin(legacy.__file__)])
    loaded=dict(bootstrap_export_pins=bootstrap,pins=deepcopy(r['live_pins']),source_sha256=cp['source_sha256'],ownership=deepcopy(r['ownership']),generated_pin=generated[0],guide_parameters=dict(document=deepcopy(cp['document']),configuration=deepcopy(conf),baseline=deepcopy(cp['snapshot']['binding']),expected_parameters=protected,targets=[]),current_snapshot=deepcopy(cp['snapshot']),deep_targets=deepcopy(cp['learned_targets']),local_feature_owners=owners,configuration_tool=deepcopy(cp['learned_targets'][0]['assigned_tool']),serial_flat_catalogue=deepcopy(cp['tool_catalogue']),local_tool_dimensions=deepcopy(cp['tool_dimensions']),tool_dimensions=deepcopy(cp['tool_dimensions']),registration=deepcopy(sc['registration']),checkpoint_pins=directpins,configuration_pins=[rpin],state=dict(document=deepcopy(cp['document']),saved_file_sha256=cp['source_sha256']))
    return loaded,bound,rpin


def forbidden(*args,**kwargs):raise ValueError('Only guarded CreateSTLOfWIPs2 export is permitted')


class ReadBackend(producer.NativeBackend):
    insert=assign=set_field=set_nc=generate=save=export=forbidden


def native_pins(loaded):
    # These old roles are only used by parent terminal validation before native.
    retired={'sw_cam_local_serial_optimization.py','sw_cam_local_optimization_cl.py','sw_cam_deep_guide_cl.py','sw_cam_generic_cl_reader_bounded.py','sw_cam_thread_postprocess.py','sw_cam_chamfer_cl_review.py'}
    prior=loaded['pins'];phase=[v for v in prior if Path(v['path']).name in retired]
    live=common._merge([v for v in prior if Path(v['path']).name not in retired],[common._pin(__file__),common._pin(binding.__file__),common._pin(core.__file__),common._pin(lengths.__file__),common._pin(lengths.finish.__file__)])
    loaded.update(pins=live,phase_proof_pins=common._merge(loaded['checkpoint_pins'],phase),checkpoint_pins=common._merge(loaded['checkpoint_pins'],phase))
    require(len(live)<=63,'WIP live closure plus saved source exceeds64')
    keys={common._key(v['path'])for v in live};audit=[]
    for name in ('__init__','start','boundary','close','finish','events','batch','target','capture_snapshot','capture_binding','verify_catalogue'):
        path=inspect.getsourcefile(getattr(ReadBackend,name));require(path and common._key(path)in keys,'WIP reader method outside live closure: '+name);audit.append(dict(method=name,path=path))
    for fn in (producer.projection,binding.validate_capture,binding.run_existing_core,core.run_one_wip_export,core.collect_wip_files,lengths.read_lengths,lengths.ReadBatch.read,lengths.ReadBatch.typed,lengths.protected.binding,lengths.finish.interface_class):require(common._key(inspect.getsourcefile(fn))in keys,'WIP helper outside live closure')
    loaded['pin_partition']=dict(live_file_count=len(live),maximum_with_source=len(live)+1,phase_proof_count=len(loaded['phase_proof_pins']),retired_phase_only=sorted(retired),recursive_ancestry_replayed=False,current_source_only=True,native_methods=audit)
    common._check(live);common._check(loaded['phase_proof_pins'])


def comparison_bound(raw_bound):
    value=deepcopy(raw_bound);canonical,policy=producer.projection(raw_bound['snapshot'])
    value.update(snapshot=canonical,raw_saved_binding_sha256=raw_bound['binding_sha256'],roundoff_comparison_only=True)
    value.pop('binding_sha256');value['binding_sha256']=binding.digest(value)
    return value,policy


def marker_path(p):
    key=group._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))
    return common.local_evidence_root()/('saved18_optimized_wip_'+key+'.json')


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact WIP18 action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS and p['acknowledgement']==ACK,'Exact bounded WIP18 request required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path')or key in ('output_dir','project_root'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):producer.opt.prior._sha(value)
    require(p['module_sha256']==common._pin(__file__)['sha256']and common._pin(binding.__file__)['sha256']==BINDING_SHA,'Frozen WIP adapter/binding required')
    loaded,raw,rpin=parent_authority(p['saved_receipt_path'],p['saved_receipt_sha256'])
    require(loaded['ownership']['process_id']==p['process_id']and loaded['source_sha256']==p['expected_source_sha256']and common._key(raw['source_path'])==common._key(p['expected_document_path']),'Exact current saved owner/source required')
    native_pins(loaded)
    registration=common.discover_export_registration(loaded,loaded['registration']['clsid']);require(group.exact(registration,loaded['registration']),'Saved CAM registration differs')
    tlb=str(Path(registration['addin_path']).parent/'camworks.tlb');require(common._pin(tlb)in loaded['pins'],'Exact current CAM typelib required')
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    guard=producer.opt.prior.guard_reuse.guard_constructor_preflight(p,loaded,tlb)
    length_audit=lengths.audit(tlb,loaded['generated_pin'])
    mark=marker_path(p);directory,canonical=core.output_plan(p['output_dir'],p['project_root'],p['receipt_path'],p['expected_document_path'],loaded['pins']+loaded['phase_proof_pins'],mark)
    compared,policy=comparison_bound(raw)
    return p,dict(loaded=loaded,raw_bound=raw,bound=compared,comparison_policy=policy,pin=rpin,registration=registration,typelib=tlb,marker=mark,directory=directory,canonical=canonical,native_guard_preflight=guard,length_interface_audit=length_audit)


def capture_lengths(backend,raw,report,persist,label,doc,machine):
    def retained():
        backend.events();require(_member(doc,'GetDocType')==1 and _member(machine,'MachType')==1,'Retained MILL binding changed');backend.events()
    def progress(name,returned):report.update(current_length_read=name,native_length_read_pending=not returned)
    batch=lengths.ReadBatch(backend.sw,backend.typelib_path,generated_pin=backend.loaded['generated_pin'],progress=progress,process_id=backend.args['process_id'],expected_document=backend.ctx.identity(),source_sha256=backend.args['expected_source_sha256'],evidence_pins=backend.loaded['pins'],verify_evidence=backend.ctx.files,verify_owned_process=backend.ctx.owned,check_events=backend.events,retained_objects=(doc,machine),verify_retained_binding=retained,max_native_calls=600)
    observed=[];report.setdefault('native_length_readbacks',[]).append(dict(label=label,rows=observed));persist()
    try:
        with batch:
            for target in backend.learned:
                oid,fid=target['operation_native_id'],target['feature_native_id']
                before,operation,_=lengths.protected.binding(doc,raw['binding'],oid,fid,read=batch.read,typed=batch.typed)
                scalars=[];item=dict(operation_native_id=oid,toolpath_record_counts=deepcopy(before['record_counts']),scalar_observations=scalars,binding_before=before,readback_verified=False);observed.append(item);persist()
                def record(key,value):
                    scalars.append(dict(key=key,returned_type=type(value).__name__,value=value if value is None or type(value)in(bool,int,float,str)else None));persist()
                item['lengths']=lengths.read_lengths(operation,read=batch.read,record=record);persist()
                after,_,_=lengths.protected.binding(doc,raw['binding'],oid,fid,read=batch.read,typed=batch.typed)
                item['binding_after']=after;require(group.exact(before,after),'Native length target changed');item['readback_verified']=True;persist()
        batch.require_complete()
    finally:report.setdefault('native_length_batches',[]).append(dict(label=label,batch=batch.summary()));persist()
    if label=='after':require(group.exact(observed,report['native_length_readbacks'][0]['rows']),'Native length statistics changed')


def capture_existing(backend,p,plan,report,persist,label):
    raw=backend.capture_snapshot('wip18_'+label,full=True)
    compared,proof=producer.projection(raw,plan['bound']['snapshot'])
    report.setdefault('raw_captures',[]).append(dict(label=label,snapshot=deepcopy(raw),roundoff=proof));persist()
    with backend.ctx.guard()as guard:
        active=guard.read(backend.ctx.app,'IGetActiveDoc');doc=guard.typed(active,'ICWDoc3');part=guard.typed(active,'ICWPartDoc')
        machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine')
        require(guard.read(doc,'GetDocType')==1 and guard.read(machine,'MachType')==1,'Exact MILL document required')
    capture_lengths(backend,raw,report,persist,label,doc,machine)
    identity=backend.ctx.identity();require(group.exact(identity,plan['raw_bound']['document'])and identity['needs_save']is False,'Clean saved identity changed')
    direct(dict(path=p['expected_document_path'],sha256=p['expected_source_sha256']))
    return identity,compared,dict(machine=machine)


def run_backend(backend,p,plan,report,persist):
    directory,canonical=plan['directory'],plan['canonical'];claimed=False
    try:
        backend.learned=deepcopy(plan['loaded']['deep_targets']);backend.start();directory.mkdir();require(directory.resolve(strict=True)==canonical,'WIP output directory changed')
        def claim():
            nonlocal claimed
            require(directory.resolve(strict=True)==canonical and not any(directory.iterdir()),'WIP output changed before dispatch')
            _write_receipt(plan['marker'],dict(scope=SCOPE,source_sha256=p['expected_source_sha256'],receipt_path=p['receipt_path'],output_dir=str(directory),status='native_export_claimed_no_replay'),create=True)
            claimed=True
        binding.run_existing_core(core,plan['bound'],report,capture_existing=lambda label:capture_existing(backend,p,plan,report,persist,label),guard_factory=backend.ctx.guard,persist=persist,claim=claim,invoke=lambda machine:_member(machine,'CreateSTLOfWIPs2',*report['native_parameters']),collect=lambda:core.collect_wip_files(directory,canonical),verify_direct_pin=direct)
        backend.finish()
        require(group.exact(backend.ctx.identity(),plan['raw_bound']['document'])and core.collect_wip_files(directory,canonical)==report['files'],'Post-cleanup source/WIP changed')
        common._check(plan['loaded']['pins']);common._check(plan['loaded']['phase_proof_pins']);direct(dict(path=p['expected_document_path'],sha256=p['expected_source_sha256']))
        for key in ('GTP_attempted','GOP_attempted','AFR_attempted','model_saved','setter_attempted','assignment_attempted','simulation_attempted','automatic_retry','automatic_replay','geometry_verified','mesh_error_bound_qualified','temporal_collision_verified','production_qualified'):require(report[key]is False,'Forbidden WIP action or qualification')
        require([v['label']for v in report['raw_captures']]==['before','after'],'Exactly two complete raw captures required')
        report.update(status='review_required',phase='finished',phase_proofs_verified_after_export=True,checkpoint_export_readback_verified=True,outer_cleanup_still_required=False)
    except Exception as exc:report.update(status='uncertain'if report['mutation_attempted']else'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,export_files_verified=False,checkpoint_export_readback_verified=False,binding_readback_verified=False,outer_cleanup_still_required=True)
    finally:
        try:generation.close_checked(backend,report)
        except Exception as exc:report.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,export_files_verified=False,checkpoint_export_readback_verified=False,binding_readback_verified=False,outer_cleanup_still_required=True)
        persist()
        if claimed:_write_receipt(plan['marker'],dict(scope=SCOPE,status=report['status'],source_sha256=p['expected_source_sha256'],receipt_pin=common._pin(p['receipt_path']),automatic_replay=False))
    return report


def dispatch_request(request,*,validate_only=False):
    p,plan=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,saved_source_sha256=p['expected_source_sha256'],expected_generated_operations=plan['bound']['expected_generated_operations'],pin_partition=plan['loaded']['pin_partition'],native_guard_preflight=plan['native_guard_preflight'],length_interface_audit=plan['length_interface_audit'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(plan['loaded']['pins']);common._check(plan['loaded']['phase_proof_pins']);sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=binding.new_report(plan['bound'],output_dir=plan['directory'],implementation_pin=common._pin(__file__))
        report.update(adapter_scope=SCOPE,request=deepcopy(p),ownership=deepcopy(plan['loaded']['ownership']),raw_saved_binding=deepcopy(plan['raw_bound']),comparison_policy=deepcopy(plan['comparison_policy']),runtime_pins=deepcopy(plan['loaded']['pins']),checkpoint_pins=deepcopy(plan['loaded']['phase_proof_pins']),marker_path=str(plan['marker']),phase_proofs_verified_after_export=False,checkpoint_export_readback_verified=False,raw_NC_values_preserved=True,length_interface_audit=deepcopy(plan['length_interface_audit']),length_units_semantics_verified=False,length_geometry_acceptance_complete=False,tool_catalogue_scope='all21 nativeIDs and complete assigned operation tool parameters; no holder clearance qualification')
        persist=lambda:_write_receipt(p['receipt_path'],report)
        _write_receipt(p['receipt_path'],report,create=True)
        backend=ReadBackend(plan['loaded'],p,sw,plan['registration']['clsid'],plan['typelib'],report,persist,before_generate=forbidden,exporter=forbidden)
        return run_backend(backend,p,plan,report,persist)
