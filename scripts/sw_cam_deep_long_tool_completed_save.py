"""Save four completed deep toolpaths with their exact observed geometric feed.

No tool assignment, parameter setter or generation is allowed. Only the
observed XY feed500 to1000 transition in four named operations is adopted;
production cutting conditions remain unqualified.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,re
from scripts import sw_cam_deep_long_tool_replace as base
from scripts import sw_cam_deep_long_tool_gtp_recover as recovered
from scripts import sw_cam_long_cut_reconciliation as reconciliation
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _error
from scripts.sw_cam_mill_selected_plan_evidence import clean_events
writer,group,common,cl,config,generation=base.writer,base.group,base.common,base.cl,base.config,base.generation
SCOPE='DEEP_LONG_TOOL_COMPLETED_PATHS_SAVE_V1'
ACTION='save_completed_deep_guide_toolpaths'
IDS=base.IDS
PARAMS={'process_id','expected_document_path','expected_source_sha256','module_sha256','generated_receipt_path','generated_receipt_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}


def feed_transition(before,after):
    expected=deepcopy(before);changes=[]
    require([x['operation_native_id']for x in expected['parameters']]==[322,324,326,328,*IDS],'Exact eight groups required')
    for row in expected['parameters']:
        if row['operation_native_id']in IDS:
            nc=row['nc']['feeds_compensation'];require(nc==dict(GetSpndlSpeed=4000.,GetTlpComp=1,GetCNCComp=0,GetRetractType=0,XYFeed=500.),'Exact prior geometric NC/feed required')
            nc['XYFeed']=1000.;changes.append(dict(operation_native_id=row['operation_native_id'],field='nc.feeds_compensation.XYFeed',requested=500.,observed=1000.))
    require(group.exact(expected,after),'Generated state differs beyond the four observed feeds')
    return dict(scope='EXACT_OBSERVED_DEEP_XY_FEED_ADOPTION_V1',changes=changes,nominal_geometry_only=True,physical_cutting_conditions_qualified=False,production_qualified=False,cause_verified=False)


def completed_gtp_contract(r,loaded,p):
    require(r.get('scope')==recovered.SCOPE and r.get('module_pin')==common._pin(recovered.__file__),'Exact frozen recovery producer required')
    require(r.get('status')=='uncertain' and r.get('phase')=='finished' and r.get('failed_phase')=='GTP:336','Exact completed-generation/pre-Save stop required')
    require(r.get('issue')=={'type':'ValueError','hresult':None,'actual_return_type':None,'locations':[
      {'file':'sw_cam_deep_long_tool_gtp_recover.py','function':'run_backend','line':164},
      {'file':'sw_cam_deep_long_tool_replace.py','function':'verify_parameters','line':77},
      {'file':'sw_cam_rough_firstcut.py','function':'require','line':38}]},'Exact observed-feed contract failure required')
    for key in ('adoption_verified','GTP_attempted','mutation_attempted','native_call_attempted','native_call_returned'):
        require(r.get(key)is True,'Incomplete generated state: '+key)
    for key in ('SetTool_attempted','setter_attempted','save_attempted','model_saved','readback_verified','continuation_ready','native_dispatch_pending','cleanup_session_active','automatic_retry','automatic_rollback','operation_creation_attempted','tool_creation_attempted'):
        require(r.get(key)is False,'Unexpected pre-Save state: '+key)
    require(not any(k in r for k in ('saved','saved_cl','saved_source_sha256','source_transition','save_stage','cleanup_issue','receipt_write_error')),'Prior or uncertain Save must not replay')
    clean_events(r)
    require(group.exact(r['ownership'],loaded['ownership']) and r['request']['process_id']==p['process_id']==r['ownership']['process_id'],'Exact owned process required')
    require(r['source_sha256']==p['expected_source_sha256'] and common._key(r['source_path'])==common._key(p['expected_document_path']),'Exact unchanged saved source required')
    assigned,ap=reconciliation.read_pin(r['adopted_assignment_receipt_pin']['path'],r['adopted_assignment_receipt_pin']['sha256'])
    require(ap==r['adopted_assignment_receipt_pin'],'Exact assignment pin required')
    recovered.partial_contract(assigned,loaded,p)
    stopped,zp=reconciliation.read_pin(r['zero_native_predecessor_pin']['path'],r['zero_native_predecessor_pin']['sha256'])
    require(zp==r['zero_native_predecessor_pin'] and group.exact(recovered.zero_native_contract(stopped,assigned,p),r['zero_native_proof']),'Exact zero-native lineage required')
    require(group.exact(r['adopted_actions'],assigned['actions']) and r['tool_creation_pin']==assigned['tool_creation_pin'],'Assignment/tool authority changed')
    require(group.exact(r['before'],assigned['configured']) and group.exact(r['configured'],r['before']),'Actual adopted state changed')
    require(group.exact(r['replacement_tool'],loaded['replacement_tool_dimensions']),'Actual assigned tool profile differs')
    require(list(r['actions'])==['GTP:'+str(i)for i in IDS],'Exactly four completed GTP actions required')
    counts={}
    for target in loaded['deep_targets']:
        oid=target['operation_native_id'];a=r['actions']['GTP:'+str(oid)]
        require(a.get('status')=='verified' and all(a.get(k)is True for k in ('attempted','returned','readback_verified')) and a.get('native_dispatch_pending')is False,'Unverified GTP cannot be saved')
        require(a.get('native_return')=={'python_type':'int','value_recorded':True,'value':0},'Strict GTP S_OK required')
        generation.status_contract(a['observed'],target,True);counts[oid]=a['observed']['record_counts']
    base.verify_route(assigned['before']['binding'],r['generated']['binding'],loaded['configuration_tool'],IDS,counts)
    policy=feed_transition(r['configured'],r['generated'])
    require(group.exact(r['before_cl_reference'],loaded['created_saved_cl']),'Protected prior fourteen paths differ')
    require(group.exact(r['current_document'],loaded['guide_parameters']['document']),'Actual document identity differs')
    return deepcopy(r['generated']),policy


def marker_path(p):
    key=SCOPE+'|'+common._key(p['expected_document_path'])+'|'+p['expected_source_sha256']
    return common.local_evidence_root()/('deep_completed_save_'+hashlib.sha256(key.encode()).hexdigest()+'.once.json')


class Journal(base.Journal):
    def _marker_state(self):
        value=super()._marker_state();value.update(scope=SCOPE,adopted_generated_receipt_pin=deepcopy(self.report['adopted_generated_receipt_pin']))
        return value


class NativeBackend(base.NativeBackend):
    def assign(self,*a):raise ValueError('Save-only action cannot assign tools')
    def generate(self,*a):raise ValueError('Save-only action cannot regenerate paths')
    def set_field(self,*a):raise ValueError('Save-only action cannot change recipe')
    def set_nc(self,*a):raise ValueError('Save-only action cannot change observed feeds')


def run_backend(backend,journal,loaded):
    require(not journal.created and not journal.claimed,'A prior Save attempt cannot replay')
    r=journal.report;r.update(status='error',phase='preflight',actions={},mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
      SetTool_attempted=False,setter_attempted=False,GTP_attempted=False,save_attempted=False,model_saved=False,readback_verified=False,continuation_ready=False,
      operation_creation_attempted=False,tool_creation_attempted=False,automatic_retry=False,automatic_rollback=False,physical_cutting_conditions_qualified=False,
      geometry_acceptance_complete=False,production_qualified=False,persistence_after_reopen_verified=False)
    try:
        journal.create();backend.start();wanted=loaded['replacement_tool_dimensions']
        r['before']=backend.capture_snapshot('adopted_completed_paths',full=True)
        require(group.exact(r['before'],loaded['adopted_snapshot']),'Live seventeen/eight state differs from completed GTP snapshot')
        r['adoption_verified']=True;r['generated']=deepcopy(r['before']);r['before_cl_reference']=deepcopy(loaded['created_saved_cl']);cl._verified(r['before_cl_reference'])
        r['generated_state_verified_before_save']=True
        r['save_stage']={};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['generated'])
            r['saved']=backend.capture_snapshot('saved',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['generated']),'Save changed complete route or parameters')
        def save():
            value=backend.save();entry=r['actions']['SaveActiveDocument'];require(entry['attempted']is True,'Save bypassed pending marker')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value));r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Save did not advance source hash')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding']);r['protected_cl']=base.verify_protected_cl(r['before_cl_reference'],r['saved_cl']);r['cutcom_review']=cl.verify_no_new_cutcom(r['saved_cl']);r['saved_actual_four_paths_exported']=True;backend.finish()
        r['replacement_checkpoint_context']=dict(source_sha256=r['saved_source_sha256'],prior_source_sha256=r['source_sha256'],tool_creation_pin=deepcopy(r['tool_creation_pin']),
          document=deepcopy(r['source_transition']['document']),configuration=deepcopy(loaded['guide_parameters']['configuration']),saved_snapshot=deepcopy(r['saved']),
          saved_cl=deepcopy(r['saved_cl']),learned_targets=deepcopy(backend.learned),tool_dimensions=deepcopy(wanted),tool_catalogue_ids=deepcopy(loaded['tool_catalogue_ids']),
          operation_order=list(base.OLD+IDS),generated_ids=list(cl.OLD)+list(IDS),process_id=r['request']['process_id'],ownership=deepcopy(r['ownership']),persistence_after_reopen_verified=False)
        for target in r['replacement_checkpoint_context']['learned_targets']:
            target['reference_nc']=deepcopy(next(x['nc']['feeds_compensation']for x in r['saved']['parameters']if x['operation_native_id']==target['operation_native_id']))
        r.update(status='saved_completed_deep_paths_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        try:journal.persist()
        except Exception as exc:r['receipt_write_error']=_error(exc);r['continuation_ready']=False
    return r


def validate_completed_save(r,generated):
    require(r.get('scope')==SCOPE and r.get('module_pin')==common._pin(__file__) and r.get('status')=='saved_completed_deep_paths_review_required' and r.get('phase')=='finished','Completed installed Save-only producer required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','receipt_write_error')),'Uncertain Save cannot authorize geometry')
    pinned,pin=reconciliation.read_pin(r['adopted_generated_receipt_pin']['path'],r['adopted_generated_receipt_pin']['sha256'])
    require(pin==r['adopted_generated_receipt_pin'] and group.exact(pinned,generated),'Exact immutable completed-GTP evidence required')
    require(group.exact(r['adopted_GTP_actions'],generated['actions']) and r['tool_creation_pin']==generated['tool_creation_pin'],'Historical actions/tool authority changed')
    require(group.exact(r['before'],generated['generated']) and group.exact(r['generated'],r['before']) and group.exact(r['saved'],r['before']),'Save changed the accepted full state')
    require(group.exact(r['feed_adoption'],feed_transition(generated['configured'],r['before'])),'Exact geometric feed adoption required')
    for key in ('SetTool_attempted','setter_attempted','GTP_attempted','operation_creation_attempted','tool_creation_attempted','native_dispatch_pending','cleanup_session_active','automatic_retry','automatic_rollback','physical_cutting_conditions_qualified','production_qualified'):
        require(r.get(key)is False,'Save-only action exceeded scope: '+key)
    for key in ('adoption_verified','save_attempted','model_saved','readback_verified','continuation_ready','generated_state_verified_before_save','saved_actual_four_paths_exported'):
        require(r.get(key)is True,'Incomplete Save proof: '+key)
    clean_events(r);require(list(r['actions'])==['SaveActiveDocument'],'Exactly one Save action required')
    action=r['actions']['SaveActiveDocument'];require(action.get('status')=='verified' and all(action.get(k)is True for k in ('attempted','returned','readback_verified')) and action.get('native_dispatch_pending')is False and action.get('native_return')=={'python_type':'int','value_recorded':True,'value':0},'Strict completed Save S_OK required')
    require(r['source_sha256']==generated['source_sha256'] and r['request']['process_id']==generated['request']['process_id'] and group.exact(r['ownership'],generated['ownership']),'Exact owned source lineage required')
    checkpoint=r['replacement_checkpoint_context'];require(group.exact(checkpoint['saved_snapshot'],r['saved']) and checkpoint['saved_cl']==r['saved_cl'],'Saved snapshot/CL checkpoint differs')
    require(group.exact(checkpoint['tool_dimensions'],r['replacement_tool']) and group.exact(r['replacement_tool'],generated['replacement_tool']),'Actual tool profile differs')
    writer.fields.learned_targets(checkpoint['learned_targets']);require(tuple(t['operation_native_id']for t in checkpoint['learned_targets'])==IDS and tuple((t['feature_native_id'],t['operation_type'])for t in checkpoint['learned_targets'])==base.PAIRS,'Exact four targets required')
    for target in checkpoint['learned_targets']:
        row=next(x for x in r['saved']['parameters']if x['operation_native_id']==target['operation_native_id'])
        require(group.exact(target['reference_nc'],row['nc']['feeds_compensation']) and group.exact(target['reference_tool_dimensions'],row['tool']) and group.exact(target['assigned_tool'],checkpoint['tool_dimensions']['generic']) and target['tool_native_id']==checkpoint['tool_dimensions']['generic']['native_id'],'Learned saved NC/tool differs')
    base.verify_protected_cl(generated['before_cl_reference'],r['saved_cl']);cl.verify_no_new_cutcom(r['saved_cl'])
    sha=r['saved_source_sha256'];transition=r['source_transition']
    require(type(sha)is str and re.fullmatch('[0-9a-f]{64}',sha) and sha!=r['source_sha256'] and action['observed']==sha,'One actual new Save digest required')
    require(checkpoint['source_sha256']==sha and checkpoint['prior_source_sha256']==r['source_sha256'] and transition['source_before_sha256']==r['source_sha256'] and transition['source_after_sha256']==sha and type(transition['strict_save_return'])is int and transition['strict_save_return']==0,'Exact strict source transition required')
    require(group.exact(transition['document'],checkpoint['document']) and checkpoint['document']['needs_save']is False and common._key(checkpoint['document']['path'])==common._key(r['source_path']),'Exact saved document required')
    require(checkpoint['operation_order']==list(base.OLD+IDS) and checkpoint['generated_ids']==list(cl.OLD)+list(IDS) and checkpoint['process_id']==r['request']['process_id'] and group.exact(checkpoint['ownership'],r['ownership']),'Saved route/process checkpoint differs')
    return checkpoint


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'} and request['action']==ACTION,'Exact completed-path Save action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact Save-only parameters required')
    require(p['acknowledgement']=='adopt_observed_1000_for_nominal_geometry_only_save_completed_paths','Explicit nominal-only observed-feed choice required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned process ID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Explicit absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
    require(p['module_sha256']==base._file_hash(__file__),'Save-only module changed')
    generated,gp=reconciliation.read_pin(p['generated_receipt_path'],p['generated_receipt_sha256']);cp=generated['tool_creation_pin']
    context=reconciliation.load_completed(cp['path'],cp['sha256'],process_id=p['process_id'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    loaded=base.projection_from_creation(context);loaded['adopted_snapshot'],loaded['feed_adoption']=completed_gtp_contract(generated,loaded,p)
    require(base._file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Saved source changed before Save-only adoption')
    marker=recovered.marker_path(generated['request']);mark,mp=reconciliation.read_pin(str(marker),base._file_hash(marker))
    require(group.exact(mark,recovered.Journal(generated,generated['request']['receipt_path'],marker)._marker_state()),'Completed-generation marker changed')
    loaded['pins']=common._merge(loaded['pins'],[common._pin(__file__)]);require(len(loaded['pins'])<=64,'Bounded active closure exceeds64')
    from scripts import sw_cam_deep_long_tool_gtp_continue as historical
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],generated['checkpoint_pins'],generated['live_pins'],[gp,mp,common._pin(recovered.__file__),common._pin(historical.__file__),common._pin(reconciliation.__file__),generated['adopted_assignment_receipt_pin'],generated['zero_native_predecessor_pin']])
    require(len(loaded['checkpoint_pins'])<=320,'Bounded historical closure exceeds320')
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,context['long_cut_tool_checkpoint']['registration']['clsid']);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in loaded['pins'],'Actual typelib differs');abi=base.audit_interfaces(typelib,loaded['generated_pin'])
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name'];loaded['native_guard_preflight']=base.guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);once=marker_path(p);export=cl._fresh_path(p['saved_cl_path'])
    outputs=[receipt,progress,once,export];protected={common._key(x['path'])for x in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(x)for x in outputs})==4 and not protected.intersection(map(common._key,outputs)),'Save-only output alias')
    require(all(not x.exists() and not x.is_symlink()for x in outputs),'Prior Save attempt/output exists; no replay')
    require(all(x.parent.is_dir()for x in (receipt,progress,once)),'Existing evidence parents required')
    return p,loaded,registration,typelib,abi,receipt,once,generated,gp


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,generated,gp=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,maximum_SetTool=0,maximum_GTP=0,maximum_Save=1,adoption_pending_live_snapshot=True,native_guard_preflight=loaded['native_guard_preflight'],feed_adoption=loaded['feed_adoption'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=base.authority.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=deepcopy(loaded['ownership']),
          tool_creation_pin=deepcopy(generated['tool_creation_pin']),adopted_generated_receipt_pin=gp,adopted_GTP_actions=deepcopy(generated['actions']),feed_adoption=deepcopy(loaded['feed_adoption']),
          interface_audit=abi,live_pins=deepcopy(loaded['pins']),checkpoint_pins=deepcopy(loaded['checkpoint_pins']),replacement_tool=deepcopy(loaded['replacement_tool_dimensions']))
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_backend(backend,journal,loaded)
