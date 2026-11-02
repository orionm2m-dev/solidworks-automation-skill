"""Once-only twelve selected depth/pitch setters, GTP4, Save1 and protected CL18.

No tool/feed/entry-point/feature/operation creation. Unknown GTP parameter drift
stops before Save and preserves actual completed GTP evidence without replay.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
from scripts import sw_cam_local_generation as base
from scripts import sw_cam_local_optimization_fields as fields
from scripts import sw_cam_local_optimization_cl as cl
from scripts import sw_cam_local_optimization_native as native
from scripts.sw_cam_rough_firstcut import require
configured=base.configured;prior=base.prior;common=base.common;group=base.group
engine=base.engine;config=base.config;generation=base.generation
SCOPE='EXISTING_LOCAL_FOUR_DEPTH_PITCH_OPTIMIZATION_V1'
ACTION='optimize_existing_local_group'
ACK='optimize_selected_depth_pitch12_generate4_save1_export18_no_recreation_no_feed_change'

class Journal(configured.assembly.Journal):
    def _marker_state(self):
        return dict(super()._marker_state(),scope=SCOPE,qualified_receipt_pin=self.report['qualified_receipt_pin'],rebind_receipt_pin=self.report['rebind_receipt_pin'],recipe_pin=self.report['recipe_pin'])
    def entry(self,name):
        require(name in fields.action_names(self.report['learned_targets']),'Action outside selected depth/pitch/GTP/Save plan')
        return super().entry(name)
    def pending(self,name):
        if not name.startswith('GTP:')and name!='SaveActiveDocument':self.report['parameter_setter_attempted']=True
        return super().pending(name)

def configure_selected(backend,journal,loaded):
    original={p['operation_native_id']:p for p in journal.report['before']['parameters']}
    plans={p['operation_native_id']:p for p in loaded['optimization_plan']['rows']}
    for target in backend.learned:
        oid=target['operation_native_id'];wanted=fields.desired_values(plans[oid])
        for spec in fields.specs(target):
            label=str(oid)+':'+spec[0];value=backend.field(target,spec)
            require(group.exact(value,fields.field_value(original[oid],spec)),'Selected scalar changed since fresh snapshot')
            if group.exact(value,wanted[spec[0]]):
                journal.entry(label);journal.verified(label,dict(already_satisfied=True,value=deepcopy(value)));continue
            journal.execute(label,lambda pending,spec=spec:backend.set_field(target,spec,wanted[spec[0]],pending))
            backend.refresh_dirty();value=backend.field(target,spec)
            require(group.exact(value,wanted[spec[0]]),'Immediate exact setter readback differs')
            journal.verified(label,deepcopy(value))

def describe_nc_drift(before,after,targets,counts):
    normal=deepcopy(after);old={p['operation_native_id']:p for p in before['parameters']};selected={t['operation_native_id']for t in targets};changes=[]
    from math import isfinite
    for p in normal['parameters']:
        oid=p['operation_native_id']
        if oid not in selected:continue
        for key in ('GetSpndlSpeed','XYFeed'):
            a=old[oid]['nc']['feeds_compensation'][key];b=p['nc']['feeds_compensation'][key]
            if group.exact(a,b):continue
            require(type(b)in(int,float)and isfinite(b)and b>0,'Unbounded NC change')
            changes.append(dict(operation_native_id=oid,field=key,before=deepcopy(a),observed=deepcopy(b)));p['nc']['feeds_compensation'][key]=deepcopy(a)
    require(changes,'No exact NC-only differences');fields.verify_regenerated(before,normal,targets,counts)
    return dict(status='EXACT_NC_ONLY_DIFFERENCES_REVIEW_REQUIRED',changes=changes,automatic_acceptance=False,automatic_restore=False,GTP_replay_allowed=False,CL_feed_update_without_GTP_qualified=False,production_qualified=False)

def run_once(backend,journal,loaded):
    require(not journal.created and not journal.claimed and not journal.receipt.exists()and not journal.marker.exists(),'Fresh unclaimed generation journal required before any report change')
    r=journal.report;c=loaded['optimization'];baseline=loaded['guide_parameters']['expected_parameters']
    backend.learned=deepcopy(c['targets']);ids=engine.ids(backend.learned,'operation_native_id')
    r.update(status='error',phase='preflight',actions={},actual_new_ids=ids,learned_targets=deepcopy(backend.learned),
        mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
        GTP_attempted=False,model_saved=False,readback_verified=False,automatic_retry=False,automatic_rollback=False,
        operation_creation_attempted=False,tool_assignment_attempted=False,parameter_setter_attempted=False,
        physical_cutting_conditions_qualified=False,production_qualified=False,geometry_accepted=False,persistence_after_reopen_verified=False,
        continuation_ready=False,completed_gtp_counts={},feed_policy={t['key']:[]for t in backend.learned})
    try:
        journal.create();backend.start();r['before']=backend.capture_snapshot('saved_existing_before_optimization',full=True)
        require(group.exact(r['before'],c['snapshot']),'Fresh complete21/12 differs from verified reopened saved route')
        cl.contract(r['before']['binding'],baseline['binding'],backend.learned)
        fields.validate_plan(loaded['optimization_plan'],backend.learned,r['before'])
        r['plan']=deepcopy(loaded['optimization_plan']);journal.persist()
        configure_selected(backend,journal,loaded)
        r['configured']=backend.capture_snapshot('configured_optimization',full=True);journal.persist()
        r['configuration_verification']=fields.verify_configured(r['before'],r['configured'],r['plan']);journal.persist()
        counts={}
        for target in backend.learned:
            oid=target['operation_native_id'];label='GTP:'+str(oid)
            def pending():r['GTP_attempted']=True;journal.pending(label)
            journal.entry(label)
            # The reused generate implementation binds typed interfaces before
            # dispatch_once claims the vendor call. Its Boolean diagnostic is
            # required to be a bool, without inventing True as an idle signal.
            result=backend.generate(target,pending)
            action=r['actions'][label];require(action['attempted']is True,'Generation bypassed pending journal')
            action.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(result))
            r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist()
            require(type(result)is int and result==0,'Exact GenerateToolpath HRESULT0 required')
            backend.refresh_dirty();outcome=backend.outcome(target);generation.status_contract(outcome,target,True)
            counts[oid]=deepcopy(outcome['record_counts']);r['completed_gtp_counts']=deepcopy(counts);journal.verified(label,outcome)
        r['generated']=backend.capture_snapshot('generated_four',full=True);journal.persist()
        try:r['generation_verification']=fields.verify_regenerated(r['configured'],r['generated'],backend.learned,counts)
        except Exception:
            try:r['nc_restore_candidate']=describe_nc_drift(r['configured'],r['generated'],backend.learned,counts)
            except Exception:r['nc_restore_candidate']=dict(status='NOT_PROVEN_NC_ONLY',automatic_restore=False,GTP_replay_allowed=False)
            journal.persist();raise
        r['save_stage']={};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['generated'])
            r['saved']=backend.capture_snapshot('saved_generated_four',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['generated']),'Save changed the complete generated21/12 snapshot')
        def save():
            value=backend.save();a=r['actions']['SaveActiveDocument'];require(a['attempted']is True,'Save bypassed pending')
            a.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value));r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved source did not advance');r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding'])
        r['saved_cl_verification']=cl.verify_saved(loaded['optimization']['prior_cl'],r['saved_cl'],backend.learned,r['saved'])
        backend.finish();r.update(status='saved_existing_local_optimization_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:
        from scripts.sw_cam import _error
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:
            from scripts.sw_cam import _error
            r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r


def validate_completed(r,loaded):
    c=loaded['optimization'];targets=c['targets'];ids=engine.ids(targets,'operation_native_id')
    require(r['scope']==SCOPE and r['status']=='saved_existing_local_optimization_review_required'and r['phase']=='finished','Completed optimization receipt required')
    require(r['readback_verified']is True and r['model_saved']is True and r['GTP_attempted']is True and r['continuation_ready']is True and r['native_dispatch_pending']is False,'Complete saved nonpending optimization required')
    require(not any(r.get(k)for k in ('issue','cleanup_issue','terminal_issue','nc_restore_candidate')),'Unresolved state cannot authorize saved result')
    prior.clean_events(r)
    require(r['source_sha256']==loaded['source_sha256']and common._key(r['source_path'])==common._key(loaded['guide_parameters']['document']['path'])and group.exact(r['ownership'],loaded['ownership'])and r['request']['process_id']==loaded['ownership']['process_id'],'Terminal original source, document or owned process differs')
    for key in ('operation_creation_attempted','tool_assignment_attempted','physical_cutting_conditions_qualified','production_qualified','geometry_accepted','persistence_after_reopen_verified'):
        require(r[key]is False,'Unqualified or forbidden scope must remain false')
    for key in ('qualified_receipt_pin','rebind_receipt_pin','recipe_pin'):
        require(group.exact(r[key],loaded[key]),'Exact input authority pin required')
    require(group.exact(r['learned_targets'],targets)and r['actual_new_ids']==ids and group.exact(r['before'],c['snapshot']),'Exact reopened targets and snapshot required')
    fields.validate_plan(r['plan'],targets,r['before']);require(group.exact(r['plan'],loaded['optimization_plan']),'Sealed plan differs')
    proof=fields.verify_configured(r['before'],r['configured'],r['plan']);require(group.exact(proof,r['configuration_verification']),'Configured delta evidence differs')
    require(list(r['actions'])==fields.action_names(targets),'Only exact twelve setter rows/GTP4/Save1 order allowed')
    plans={p['operation_native_id']:p for p in r['plan']['rows']}
    for target in targets:
        oid=target['operation_native_id'];wanted=fields.desired_values(plans[oid])
        for spec in fields.specs(target):
            action=r['actions'][str(oid)+':'+spec[0]];configured.verified_action(action)
            observed=action['observed']if action['attempted']is True else action['observed']['value']
            require(group.exact(observed,wanted[spec[0]]),'Setter observation differs from sealed target')
    counts={int(k):v for k,v in r['completed_gtp_counts'].items()};require(set(counts)==set(ids),'All four GTP outcomes required')
    for t in targets:
        a=r['actions']['GTP:'+str(t['operation_native_id'])];configured.verified_action(a)
        require(a['attempted']is True and a['returned']is True,'Each GTP must have one actual vendor call')
        generation.status_contract(a['observed'],t,True);require(group.exact(a['observed']['record_counts'],counts[t['operation_native_id']]),'GTP outcome differs')
    require(group.exact(r['feed_policy'],{t['key']:[]for t in targets}),'No feed transition allowed')
    proof=fields.verify_regenerated(r['configured'],r['generated'],targets,counts)
    require(group.exact(proof,r['generation_verification'])and group.exact(r['saved'],r['generated']),'Exact saved regeneration evidence required')
    a=r['actions']['SaveActiveDocument'];configured.verified_action(a);new=prior._sha(r['saved_source_sha256'])
    require(a['attempted']is True and a['observed']==new and new!=r['source_sha256'],'Actual single changed-source Save required')
    transition=r['source_transition'];require(transition['source_before_sha256']==r['source_sha256']and transition['source_after_sha256']==new and type(transition['strict_save_return'])is int and transition['strict_save_return']==0 and transition['document']['needs_save']is False,'Strict Save and clean saved document required')
    expected_saved_document=deepcopy(loaded['guide_parameters']['document'])
    require(expected_saved_document.get('needs_save')is True,'Explicit verified observed-dirty input required')
    expected_saved_document['needs_save']=False
    require(group.exact(transition['document'],expected_saved_document),'Save may change only the observed dirty flag to False')
    stage=r['save_stage'];require(stage.get('save_attempted')is True and stage.get('native_call_returned')is True and stage.get('save_pending')is False and stage.get('save_readback_verified')is True and stage.get('native_return_type')=='int'and type(stage.get('native_return_value'))is int and stage['native_return_value']==0 and stage['saved_file_sha256']==new,'Exact single-save stage must be complete')
    require(group.exact(stage['before'],r['generated'])and group.exact(stage['after'],r['saved']),'Save stage snapshots differ from actual generated/saved captures')
    cp=cl.verify_saved(c['prior_cl'],r['saved_cl'],targets,r['saved'])
    require(group.exact(cp,r['saved_cl_verification'])and r['saved_cl']['source_sha256']==new,'Saved18 CL authority differs')
    require([v['phase']for v in r['phase_proof_checks']]==['before_native_start','before_save','after_export_and_cleanup']and all(v['verified']is True for v in r['phase_proof_checks']),'Phase proof checks required')
    return dict(status='saved_existing_optimization_authority_verified',operations=21,parameters=12,paths=18,regenerated_paths=4,protected_old_paths=14,source_sha256=new,geometry_accepted=False,production_qualified=False)


PARAMS={'process_id','expected_document_path','expected_source_sha256','qualified_receipt_path','qualified_receipt_sha256','rebind_receipt_path','rebind_receipt_sha256','recipe_path','recipe_sha256','module_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}


def marker_path(p):
    identity='\0'.join((SCOPE,common._key(p['expected_document_path']),p['expected_source_sha256']))
    return common.local_evidence_root()/('existing_local_optimize_'+hashlib.sha256(identity.encode()).hexdigest()+'.json')


def partition_pins(loaded,extras):
    """Keep executed readers/guards/setters live; completed factories stay immutable proof."""
    import importlib,sys,inspect
    packet=prior
    retired={'sw_cam_guide_group_definitions','sw_cam_local_operation_context','sw_cam_local_operation_cl','sw_cam_local_operation_nc','sw_cam_local_operation_recipe','sw_cam_local_startpoint'}
    added=('sw_cam_local_serial_optimization','sw_cam_local_optimization_fields','sw_cam_local_optimization_native','sw_cam_local_optimization_cl','sw_cam_generic_cl_reader_bounded','sw_cam_deep_guide_cl','sw_cam_thread_postprocess','sw_cam_chamfer_cl_review')
    names=tuple(n for n in packet.LIVE_MODULES if n not in retired)+added
    require(len(names)==len(set(names)),'Duplicate native module role')
    modules=[importlib.import_module('scripts.'+n)for n in names]
    inherited=common._merge(loaded['pins'],loaded.get('checkpoint_pins',[]),loaded.get('phase_proof_pins',[]),loaded.get('bootstrap_export_pins',[]),extras)
    metadata=[v for v in inherited if Path(v['path']).name.lower()=='camworks.tlb'];require(len(metadata)==1,'One pinned CAM typelib required')
    live=common._merge([common._pin(m.__file__)for m in modules],[loaded['generated_pin']],metadata)
    imported=[common._pin(m.__file__)for n,m in tuple(sys.modules.items())if n.startswith('scripts.')and getattr(m,'__file__',None)and Path(m.__file__).suffix=='.py']
    allpins=common._merge(inherited,imported,live);keys={common._key(v['path'])for v in live};source=common._key(loaded['guide_parameters']['document']['path'])
    mutable=[v for v in allpins if common._key(v['path'])==source]
    require(all(v['sha256']==loaded['source_sha256']for v in mutable),'Initial current source pin differs')
    phase=[v for v in allpins if common._key(v['path'])not in keys and common._key(v['path'])!=source]
    require(1<=len(live)<=63 and len(phase)<=1024,'Bounded complete native/proof closure required')
    methods=[]
    for name in ('__init__','start','boundary','refresh_dirty','save','saved_hash','finish','close','events','batch','target','typed_field','owner','field','set_field','capture_snapshot','capture_binding','generate','outcome','export','verify_catalogue','_read_existing_nc'):
        fn=getattr(native.NativeBackend,name);path=inspect.getsourcefile(fn)
        require(path and common._key(path)in keys,'Executed native method outside live closure: '+name);methods.append(dict(method=name,path=str(Path(path).resolve())))
    for fn in (cl.export_current_cl,cl._session,cl.post._controller,native.read_generic_tool,native.micro.existing._values):
        path=inspect.getsourcefile(fn);require(path and common._key(path)in keys,'Native helper source outside live closure')
    common._check(allpins)
    loaded.update(pins=live,checkpoint_pins=[],phase_proof_pins=phase,initial_source_pins=mutable)
    loaded['pin_partition']=dict(live_file_count=len(live),maximum_with_source=len(live)+1,phase_proof_count=len(phase),initial_mutable_source_pin_count=len(mutable),all_evidence_preserved=True,phase_checkpoints=['prepare','before_native_start','before_save','after_export_and_cleanup'],proof_only_retired_modules=sorted(retired),source_update_rule='Only ctx saved_hash updates current source; old immutable backup remains pinned')
    loaded['native_source_audit']=dict(methods=methods,live_modules=list(names),native_called=False)
    return loaded['pin_partition']


def prepare_request(request,*,rebind_loader=None):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact optimization action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact sealed optimization fields required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31 and p['acknowledgement']==ACK,'Selected PID and exact bounded acknowledgement required')
    for key,v in p.items():
        if key.endswith('_path'):require(type(v)is str and Path(v).is_absolute(),'Absolute explicit path required')
        if key.endswith('_sha256'):prior._sha(v)
    require(p['module_sha256']==prior._file_hash(__file__),'Optimization implementation differs')
    from scripts import sw_cam_saved18_serial_completed as reopened
    callback=rebind_loader or reopened.load_completed_rebind
    loaded,q,receipt,extra=callback(p['rebind_receipt_path'],p['rebind_receipt_sha256'],check_current=True)
    require(q['source_sha256']==loaded['source_sha256']==p['expected_source_sha256']and loaded['ownership']['process_id']==p['process_id'],'Verified reopened source/PID differs')
    require(common._key(loaded['guide_parameters']['document']['path'])==common._key(p['expected_document_path'])and loaded['guide_parameters']['document']['needs_save']is True,'Exact verified observed-dirty reopened document required')
    qpin=common._pin(p['qualified_receipt_path']);require(qpin['sha256']==p['qualified_receipt_sha256']and common._key(qpin['path'])==common._key(loaded['qualified_authority_pin']['path'])and qpin['sha256']==loaded['qualified_authority_pin']['sha256'],'Qualified saved18 authority differs')
    recipe,recipepin=prior.read_json_pin(p['recipe_path'],p['recipe_sha256'],limit=1024*1024)
    snapshot=deepcopy(loaded['current_snapshot']);targets=deepcopy(loaded['deep_targets'])
    fields.validate_plan(recipe,targets,snapshot);cl.contract(snapshot['binding'],loaded['guide_parameters']['expected_parameters']['binding'],targets)
    rebindpin=common._pin(p['rebind_receipt_path']);require(rebindpin['sha256']==p['rebind_receipt_sha256'],'Parsed rebind receipt changed')
    loaded.update(optimization=dict(snapshot=snapshot,targets=targets,prior_cl=deepcopy(q['prior_cl'])),optimization_plan=recipe,qualified_receipt_pin=qpin,rebind_receipt_pin=rebindpin,recipe_pin=recipepin)
    require(prior._file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current saved source differs')
    partition_pins(loaded,common._merge(extra,[qpin,rebindpin,recipepin,common._pin(reopened.__file__)]))
    callback_pin=common._pin(reopened.__file__)
    loaded['pins']=common._merge(loaded['pins'],[callback_pin])
    loaded['phase_proof_pins']=[v for v in loaded['phase_proof_pins']if common._key(v['path'])!=common._key(callback_pin['path'])]
    require(len(loaded['pins'])<=63,'Completed loader plus current source exceeds shared64 bound')
    loaded['pin_partition'].update(live_file_count=len(loaded['pins']),maximum_with_source=len(loaded['pins'])+1,phase_proof_count=len(loaded['phase_proof_pins']),serial_completed_loader_live=True)
    common._check(loaded['pins']);common._check(loaded['phase_proof_pins'])
    registration=common.discover_export_registration(loaded,loaded['registration']['clsid']);require(group.exact(registration,loaded['registration']),'Checked CAM registration differs')
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb');require(common._pin(typelib)in loaded['pins'],'Exact native typelib required')
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['native_guard_preflight']=prior.guard_reuse.guard_constructor_preflight(p,loaded,typelib)
    loaded['interface_audit']=native.audit_final_depth(typelib,loaded['generated_pin'])
    out=common._local_receipt(p['receipt_path']);mark=marker_path(p);outputs=[out,Path(p['progress_path']),mark,cl._fresh_path(p['saved_cl_path'])]
    protected={common._key(v['path'])for v in loaded['pins']+loaded['phase_proof_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in outputs})==4,'Distinct exclusive outputs required')
    for value in outputs:require(not value.exists()and not value.is_symlink()and common._key(value)not in protected,'Existing output or aliased evidence forbids replay')
    for value in outputs[:3]:require(value.parent.is_dir(),'Output parent must exist')
    return p,loaded,registration,typelib,out,mark


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,out,mark=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,allowed_actions='depth_pitch12+GTP4+Save1+CL18',pin_partition=loaded['pin_partition'],native_guard_preflight=loaded['native_guard_preflight'],interface_audit=loaded['interface_audit'],targets=engine.ids(loaded['optimization']['targets'],'operation_native_id'),production_qualified=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=2,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['phase_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,request=deepcopy(p),module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=deepcopy(loaded['ownership']),live_pins=deepcopy(loaded['pins']),phase_proof_pins=deepcopy(loaded['phase_proof_pins']),pin_partition=deepcopy(loaded['pin_partition']),tool_dimensions=deepcopy(loaded['local_tool_dimensions']),qualified_receipt_pin=deepcopy(loaded['qualified_receipt_pin']),rebind_receipt_pin=deepcopy(loaded['rebind_receipt_pin']),recipe_pin=deepcopy(loaded['recipe_pin']),interface_audit=deepcopy(loaded['interface_audit']))
        journal=Journal(r,out,mark)
        backend=native.NativeBackend(loaded,p,sw,registration['clsid'],typelib,r,journal.persist,before_generate=native.forbidden_legacy_generation_hook,exporter=cl.export_saved)
        run_once(backend,journal,loaded)
        if r['readback_verified']is True:
            try:
                r['terminal_verification']=validate_completed(r,loaded)
                r['saved_checkpoint']=dict(source_path=p['expected_document_path'],source_sha256=r['saved_source_sha256'],document=deepcopy(r['source_transition']['document']),configuration=deepcopy(loaded['guide_parameters']['configuration']),snapshot=deepcopy(r['saved']),saved_cl=deepcopy(r['saved_cl']),learned_targets=deepcopy(r['learned_targets']),tool_catalogue=deepcopy(loaded['serial_flat_catalogue']),tool_dimensions=deepcopy(loaded['local_tool_dimensions']),current_counts=dict(operations=21,parameters=12,paths=18,tools=21),GTP_complete=True,nominal_geometry_accepted=False,production_qualified=False)
            except Exception as exc:
                from scripts.sw_cam import _error
                r.update(status='uncertain',readback_verified=False,continuation_ready=False,terminal_issue=_error(exc))
            journal.persist()
        return r
