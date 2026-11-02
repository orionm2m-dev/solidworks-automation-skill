"""Generate only four previously assigned deep paths after a verified pre-dispatch stop.

The failed assignment receipt stays immutable. This continuation adopts its exact
live configuration and never repeats SetTool, restores fields, creates tools or
closes the document. Existing native generation/save/export implementations are reused.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json,re
from scripts import sw_cam_deep_long_tool_replace as base
from scripts import sw_cam_long_cut_reconciliation as reconciliation
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _member,_error
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_mill_selected_plan_evidence import clean_events

writer,group,common,cl,config,generation=base.writer,base.group,base.common,base.cl,base.config,base.generation
SCOPE='DEEP_LONG_TOOL_ZERO_NATIVE_GTP_RECOVERY_V1'
ACTION='recover_zero_native_deep_guide_generation'
IDS=base.IDS
PARAMS={'process_id','expected_document_path','expected_source_sha256','module_sha256',
 'partial_receipt_path','partial_receipt_sha256','zero_native_receipt_path','zero_native_receipt_sha256','previous_generation_receipt_path','previous_generation_receipt_sha256',
 'receipt_path','progress_path','saved_cl_path','acknowledgement'}


def partial_contract(r,loaded,p):
    require(r.get('scope')==base.SCOPE and r.get('module_pin')==common._pin(base.__file__),'Exact frozen replacement producer required')
    require(r.get('status')=='uncertain' and r.get('phase')=='finished' and r.get('failed_phase')=='GTP:330','Exact pre-GTP stopped phase required')
    require(r.get('issue',{}).get('type')=='ValueError' and r['issue'].get('locations')==[
      {'file':'sw_cam_deep_long_tool_replace.py','function':'<lambda>','line':184},
      {'file':'sw_cam_deep_long_tool_replace.py','function':'generate','line':134},
      {'file':'sw_cam_rough_firstcut.py','function':'require','line':38}], 'Exact historical background predicate stop required')
    require(not any(k in r for k in ('cleanup_issue','receipt_write_error','saved_source_sha256','saved','saved_cl','source_transition')),'No uncertain Save or cleanup may be adopted')
    for key in ('GTP_attempted','save_attempted','model_saved','setter_attempted','native_dispatch_pending','readback_verified','continuation_ready','automatic_retry','automatic_rollback','operation_creation_attempted','tool_creation_attempted','cleanup_session_active'):
        require(r.get(key)is False,'Unexpected partial flag: '+key)
    require(r.get('SetTool_attempted')is True and r.get('mutation_attempted')is True,'Four completed assignments required')
    clean_events(r)
    require(p['process_id']==r['request']['process_id']==r['ownership']['process_id'] and group.exact(r['ownership'],loaded['ownership']),'Partial receipt owned process identity differs')
    require(common._key(p['expected_document_path'])==common._key(r['source_path'])==common._key(r['current_document']['path']),'Partial source path differs')
    require(p['expected_source_sha256']==r['source_sha256']==r['request']['expected_source_sha256'],'Partial saved source differs')
    baseline=base.baseline_contract(loaded)
    require(group.exact(r['before'],baseline),'Created-tool saved baseline differs')
    require(group.exact(r['replacement_tool'],loaded['replacement_tool_dimensions']),'Actual assigned tool profile differs')
    names=['SetTool:'+str(i)for i in IDS]+['GTP:330'];require(list(r['actions'])==names,'No additional or pending action may be adopted')
    for oid in IDS:
        a=r['actions']['SetTool:'+str(oid)]
        require(a.get('status')=='verified' and all(a.get(k)is True for k in ('attempted','returned','readback_verified')) and a.get('native_dispatch_pending')is False,'Assignment is not fully verified')
        require(a.get('native_return')=={'python_type':'int','value_recorded':True,'value':0},'Strict SetTool S_OK required')
        row=next(x for x in r['configured']['parameters']if x['operation_native_id']==oid)
        require(group.exact(row,a['observed']),'Immediate assignment and final configuration differ')
    require(r['actions']['GTP:330']=={'status':'prepared','attempted':False,'returned':False,'readback_verified':False},'GTP was already attempted or has an unknown outcome')
    base.verify_route(baseline['binding'],r['configured']['binding'],loaded['configuration_tool'],IDS)
    base.verify_parameters(baseline['parameters'],r['configured']['parameters'],loaded['replacement_tool_dimensions'])
    require(len(r['outcomes'])==1,'One stopped pre-dispatch outcome required')
    outcome=r['outcomes'][0];generation.status_contract(outcome,loaded['deep_targets'][0],None)
    row=next(x for x in r['configured']['binding']['operations']if x['native_id']==330)
    require(outcome['background_over_before']is False and outcome['background_over_after']is False and outcome['record_counts']==row['toolpath_record_counts'],'Exact observed false diagnostics/retained path required')
    require(group.exact(r['current_document'],loaded['guide_parameters']['document']),'Actual documented SW identity differs; do not infer dirty state')
    require(group.exact(r['before_cl_reference'],loaded['created_saved_cl']),'Original saved fourteen paths differ')
    return deepcopy(r['configured'])


def zero_native_contract(stopped,assigned,p):
    """Only this pinned Python evaluation-order failure has a zero-native proof.

    An attempted/pending native marker otherwise remains non-replayable. Here
    the exact callback first evaluates g.typed after claim. Real guard _observe
    rejects before its _typed callback; _member/GenerateToolpath is unreachable.
    """
    from scripts import sw_cam_deep_long_tool_gtp_continue as historical
    from scripts import sw_cam_dispatch_guard as dispatch_guard
    require(stopped.get('scope')==historical.SCOPE and stopped.get('module_pin')==common._pin(historical.__file__),'Exact frozen predecessor producer required')
    require(stopped.get('status')=='uncertain' and stopped.get('phase')=='finished' and stopped.get('failed_phase')=='GTP:330','Exact stopped first-GTP phase required')
    require(stopped.get('issue')=={'type':'ValueError','hresult':None,'actual_return_type':None,'locations':[
      {'file':'sw_cam_dispatch_guard.py','function':'_observe','line':124},
      {'file':'sw_cam_dispatch_guard.py','function':'_fast','line':89},
      {'file':'sw_cam_dispatch_guard.py','function':'_require_live','line':78}]},'Exact guard-order exception required; unknown outcomes cannot replay')
    require(stopped.get('actions')=={'GTP:330':{'status':'pending','attempted':True,'returned':False,'readback_verified':False,'native_dispatch_pending':True}},'Any other action or return excludes zero-native recovery')
    for k in ('adoption_verified','GTP_attempted','mutation_attempted','native_call_attempted','native_dispatch_pending'):
        require(stopped.get(k)is True,'Exact predecessor pending state required: '+k)
    for k in ('SetTool_attempted','setter_attempted','save_attempted','model_saved','readback_verified','continuation_ready','native_call_returned','cleanup_session_active','operation_creation_attempted','tool_creation_attempted','automatic_retry','automatic_rollback'):
        require(stopped.get(k)is False,'Unexpected predecessor state: '+k)
    require(not any(k in stopped for k in ('generated','saved','saved_source_sha256','saved_cl','source_transition','cleanup_issue','receipt_write_error')),'Post-GTP or uncertain cleanup evidence cannot be adopted')
    clean_events(stopped)
    require(group.exact(stopped['ownership'],assigned['ownership']) and stopped['request']['process_id']==assigned['request']['process_id']==p['process_id'],'Same exact owned process required')
    require(stopped['source_sha256']==assigned['source_sha256']==p['expected_source_sha256'] and common._key(stopped['source_path'])==common._key(p['expected_document_path']),'Unchanged saved source required')
    require(group.exact(stopped['before'],assigned['configured']) and group.exact(stopped['configured'],assigned['configured']),'Adopted live configuration changed')
    require(group.exact(stopped['adopted_actions'],assigned['actions']) and stopped['tool_creation_pin']==assigned['tool_creation_pin'] and group.exact(stopped['replacement_tool'],assigned['replacement_tool']),'Assignment/tool lineage changed')
    pinned,pin=reconciliation.read_pin(stopped['adopted_assignment_receipt_pin']['path'],stopped['adopted_assignment_receipt_pin']['sha256'])
    require(group.exact(pinned,assigned) and pin==stopped['adopted_assignment_receipt_pin'],'Exact original assignment evidence required')
    require(group.exact(stopped['outcomes'],assigned['outcomes']),'Pre-dispatch outcome changed')
    guard_pin=common._pin(dispatch_guard.__file__)
    require(guard_pin in stopped['live_pins'],'Exact historical guard implementation required')
    # Code shape pins the argument-evaluation proof; no vendor semantics assumed.
    import ast,inspect,textwrap
    tree=ast.parse(textwrap.dedent(inspect.getsource(historical.NativeBackend.generate)))
    expected=ast.parse("return g.dispatch_once(lambda:_member(g.typed(raw,'ICWMillOperation'),'GenerateToolpath'),persist_pending=pending)").body[0]
    returns=[n for n in ast.walk(tree)if isinstance(n,ast.Return)]
    require(len(returns)==1 and ast.dump(returns[0],include_attributes=False)==ast.dump(expected,include_attributes=False),'Historical callback shape changed')
    return dict(scope='EXACT_TYPED_AFTER_CLAIM_ZERO_NATIVE_PROOF_V1',historical_module_pin=common._pin(historical.__file__),guard_pin=guard_pin,
      pending_marker_preserved=True,native_GenerateToolpath_entered=False,typed_interface_callback_entered=False,
      basis='Pinned Python argument evaluation and exact real-guard stack before _typed/_member; not a generic permission to retry pending mutations.')


def prior_background_contract(r):
    require(r.get('scope')==writer.SCOPE and r.get('status')=='saved_deep_guides_review_required' and r.get('phase')=='finished','Successful prior deep generation receipt required')
    require(r.get('readback_verified')is True and r.get('model_saved')is True and not any(k in r for k in ('issue','failed_phase','cleanup_issue')),'Prior native generation was not verified')
    proofs=[]
    for t in r['learned_targets']:
        a=r['actions']['GTP:'+str(t['operation_native_id'])];v=a['observed'];generation.status_contract(v,t,True)
        require(a['status']=='verified' and a['attempted']is True and a['returned']is True and a['readback_verified']is True,'Prior targeted GTP not verified')
        require(v['background_over_before']is False and v['background_over_after']is False,'Prior exact false diagnostics required')
        proofs.append(dict(operation_native_id=t['operation_native_id'],record_counts=v['record_counts'],background_over_before=False,background_over_after=False))
    require(len(proofs)==4,'Four verified prior generation observations required')
    return dict(shared_status_contract_pin=common._pin(generation.__file__),verified_prior_false_diagnostics=proofs,
      interpretation='Diagnostic bool only; not a proof of global idle. Use exact ownership, synchronous dispatch and actual generated-path readback.')


def marker_path(p):
    key=SCOPE+'|'+common._key(p['expected_document_path'])+'|'+p['expected_source_sha256']
    return common.local_evidence_root()/('deep_assigned_gtp_'+hashlib.sha256(key.encode()).hexdigest()+'.once.json')


class Journal(base.Journal):
    def _marker_state(self):
        value=super()._marker_state();value.update(scope=SCOPE,adopted_assignment_receipt_pin=deepcopy(self.report['adopted_assignment_receipt_pin']),zero_native_predecessor_pin=deepcopy(self.report['zero_native_predecessor_pin']))
        return value


class NativeBackend(base.NativeBackend):
    def assign(self,*args):raise ValueError('Continuation cannot repeat SetTool')
    def set_field(self,*args):raise ValueError('Continuation cannot change recipe fields')
    def set_nc(self,*args):raise ValueError('Continuation cannot change NC settings')
    def generate(self,target,pending):
        require(group.exact(self.read_nc(target),target['reference_nc']),'Exact saved NC/feed required before GTP')
        generation.status_contract(self.outcome(target),target,None)
        with self.ctx.guard()as g:
            raw,_=self.target(g,target);tool,_=read_generic_tool(raw,self.doc,g.read,g.typed)
            require(group.exact(tool,self.loaded['configuration_tool']),'Adopted tool changed before GTP')
            mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)


def run_backend(backend,journal,loaded):
    require(not journal.created and not journal.claimed,'A prior continuation may never replay')
    r=journal.report
    r.update(status='error',phase='preflight',actions={},mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
      SetTool_attempted=False,setter_attempted=False,GTP_attempted=False,save_attempted=False,model_saved=False,readback_verified=False,continuation_ready=False,
      operation_creation_attempted=False,tool_creation_attempted=False,automatic_retry=False,automatic_rollback=False,physical_cutting_conditions_qualified=False,
      geometry_acceptance_complete=False,production_qualified=False,persistence_after_reopen_verified=False)
    try:
        baseline=base.baseline_contract(loaded);wanted=loaded['replacement_tool_dimensions'];journal.create();backend.start()
        r['before']=backend.capture_snapshot('adopted_live_configuration',full=True)
        require(group.exact(r['before'],loaded['adopted_snapshot']),'Live seventeen/eight state differs from verified assignment snapshot')
        r['configured']=deepcopy(r['before']);r['adoption_verified']=True
        r['before_cl_reference']=deepcopy(loaded['created_saved_cl']);cl._verified(r['before_cl_reference']);counts={}
        for target in backend.learned:
            oid=target['operation_native_id'];name='GTP:'+str(oid)
            journal.execute(name,lambda pending:backend.generate(target,pending));backend.refresh_dirty()
            observed=backend.outcome(target);generation.status_contract(observed,target,True)
            counts[oid]=deepcopy(observed['record_counts']);journal.verified(name,observed)
        r['generated']=backend.capture_snapshot('generated',full=True)
        base.verify_route(baseline['binding'],r['generated']['binding'],loaded['configuration_tool'],IDS,counts)
        base.verify_parameters(baseline['parameters'],r['generated']['parameters'],wanted)
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
        r.update(status='saved_assigned_deep_generation_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        try:journal.persist()
        except Exception as exc:r['receipt_write_error']=_error(exc);r['continuation_ready']=False
    return r


def validate_completed_continuation(r,failed):
    require(r.get('scope')==SCOPE and r.get('module_pin')==common._pin(__file__) and r.get('status')=='saved_assigned_deep_generation_review_required' and r.get('phase')=='finished','Completed installed continuation required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','receipt_write_error')),'Uncertain continuation rejected')
    stopped,zp=reconciliation.read_pin(r['zero_native_predecessor_pin']['path'],r['zero_native_predecessor_pin']['sha256'])
    require(zp==r['zero_native_predecessor_pin'] and group.exact(zero_native_contract(stopped,failed,r['request']),r['zero_native_proof']),'Exact independently preserved zero-native predecessor required')
    require(r.get('adoption_verified')is True and group.exact(r['before'],failed['configured']) and group.exact(r['configured'],r['before']),'Exact prior live state adoption required')
    for key in ('SetTool_attempted','setter_attempted','operation_creation_attempted','tool_creation_attempted','native_dispatch_pending','cleanup_session_active','automatic_retry','automatic_rollback'):
        require(r.get(key)is False,'Unexpected continuation action or pending state: '+key)
    for key in ('GTP_attempted','save_attempted','model_saved','readback_verified','continuation_ready','generated_state_verified_before_save','saved_actual_four_paths_exported'):
        require(r.get(key)is True,'Incomplete continuation proof: '+key)
    clean_events(r)
    require(list(r['actions'])==['GTP:'+str(i)for i in IDS]+['SaveActiveDocument'],'Exactly four GTP and one Save required')
    for action in r['actions'].values():
        require(action.get('status')=='verified' and all(action.get(k)is True for k in ('attempted','returned','readback_verified')) and action.get('native_dispatch_pending')is False,'Unverified continuation action')
        require(action.get('native_return')=={'python_type':'int','value_recorded':True,'value':0},'Strict native S_OK required')
    pinned,pin=reconciliation.read_pin(r['adopted_assignment_receipt_pin']['path'],r['adopted_assignment_receipt_pin']['sha256'])
    require(group.exact(pinned,failed) and pin==r['adopted_assignment_receipt_pin'],'Exact immutable assignment receipt required')
    require(group.exact(r['adopted_actions'],failed['actions']) and r['tool_creation_pin']==failed['tool_creation_pin'],'Historical assignment or tool authority changed')
    require(r['source_sha256']==failed['source_sha256'] and r['request']['process_id']==failed['request']['process_id'] and group.exact(r['ownership'],failed['ownership']),'Exact assignment lineage required')
    checkpoint=r['replacement_checkpoint_context'];targets=checkpoint['learned_targets'];counts={}
    writer.fields.learned_targets(targets)
    require(tuple(t['operation_native_id']for t in targets)==IDS and tuple((t['feature_native_id'],t['operation_type'])for t in targets)==base.PAIRS,'Exact four deep targets required')
    require(group.exact(checkpoint['tool_dimensions'],r['replacement_tool']) and group.exact(r['replacement_tool'],failed['replacement_tool']),'Adopted actual complete tool profile differs')
    require(all(group.exact(t['assigned_tool'],checkpoint['tool_dimensions']['generic']) and group.exact(t['reference_tool_dimensions'],checkpoint['tool_dimensions'])for t in targets),'Learned target tool differs')
    for t in targets:
        v=r['actions']['GTP:'+str(t['operation_native_id'])]['observed'];generation.status_contract(v,t,True);counts[t['operation_native_id']]=v['record_counts']
    generic=checkpoint['tool_dimensions']['generic'];base.verify_route(failed['before']['binding'],r['generated']['binding'],generic,IDS,counts)
    base.verify_parameters(failed['before']['parameters'],r['generated']['parameters'],checkpoint['tool_dimensions'])
    require(group.exact(r['generated'],r['saved']) and group.exact(r['saved'],checkpoint['saved_snapshot']),'Saved full state differs')
    base.verify_protected_cl(failed['before_cl_reference'],r['saved_cl']);cl.verify_no_new_cutcom(r['saved_cl'])
    require(checkpoint['saved_cl']==r['saved_cl'] and checkpoint['source_sha256']==r['saved_source_sha256'] and checkpoint['prior_source_sha256']==r['source_sha256'],'Saved CL/source checkpoint differs')
    transition=r['source_transition'];sha=r['saved_source_sha256']
    require(type(sha)is str and re.fullmatch('[0-9a-f]{64}',sha) and sha!=r['source_sha256'],'One new saved source digest required')
    require(r['actions']['SaveActiveDocument']['observed']==sha and transition['source_before_sha256']==r['source_sha256'] and transition['source_after_sha256']==sha and type(transition['strict_save_return'])is int and transition['strict_save_return']==0,'Exact strict Save transition required')
    require(group.exact(transition['document'],checkpoint['document']) and checkpoint['document']['needs_save']is False and common._key(checkpoint['document']['path'])==common._key(r['source_path']),'Exact clean saved document required')
    require(checkpoint['operation_order']==list(base.OLD+IDS) and checkpoint['generated_ids']==list(cl.OLD)+list(IDS) and checkpoint['process_id']==r['request']['process_id'] and group.exact(checkpoint['ownership'],r['ownership']),'Saved route/process checkpoint differs')
    return checkpoint


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'} and request['action']==ACTION,'Exact assigned-generation action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact continuation parameters required')
    require(p['acknowledgement']=='recover_proven_zero_native_dispatch_only_no_SetTool_replay','Explicit no-replay adoption required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Explicit absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
    require(p['module_sha256']==base._file_hash(__file__),'Continuation module changed')
    failed,fp=reconciliation.read_pin(p['partial_receipt_path'],p['partial_receipt_sha256'])
    cr=failed['request'];context=reconciliation.load_completed(cr['tool_creation_receipt_path'],cr['tool_creation_receipt_sha256'],process_id=p['process_id'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    loaded=base.projection_from_creation(context);loaded['adopted_snapshot']=partial_contract(failed,loaded,p)
    stopped,zp=reconciliation.read_pin(p['zero_native_receipt_path'],p['zero_native_receipt_sha256'])
    loaded['zero_native_proof']=zero_native_contract(stopped,failed,p)
    from scripts import sw_cam_deep_long_tool_gtp_continue as historical
    previous_marker=historical.marker_path(stopped['request']);previous_mark,zmp=reconciliation.read_pin(str(previous_marker),base._file_hash(previous_marker))
    require(group.exact(previous_mark,historical.Journal(stopped,stopped['request']['receipt_path'],previous_marker)._marker_state()),'Pending predecessor marker changed')
    loaded['zero_native_predecessor_pin']=zp
    require(base._file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Saved source changed after assignment stop')
    marker=base.marker_path(cr);oldmark,mp=reconciliation.read_pin(str(marker),base._file_hash(marker))
    require(group.exact(oldmark,base.Journal(failed,cr['receipt_path'],marker)._marker_state()),'Original once-marker no longer matches stopped receipt')
    success,sp=reconciliation.read_pin(p['previous_generation_receipt_path'],p['previous_generation_receipt_sha256']);loaded['background_contract']=prior_background_contract(success)
    loaded['pins']=common._merge(loaded['pins'],[common._pin(__file__)])
    require(len(loaded['pins'])<=64,'Active dispatch closure exceeds64')
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],[fp,mp,sp,zp,zmp,common._pin(historical.__file__),common._pin(reconciliation.__file__)])
    require(len(loaded['checkpoint_pins'])<=320,'Bounded historical closure exceeded')
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,context['long_cut_tool_checkpoint']['registration']['clsid']);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in loaded['pins'],'Actual typelib differs');abi=base.audit_interfaces(typelib,loaded['generated_pin'])
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name'];loaded['native_guard_preflight']=base.guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);once=marker_path(p);export=cl._fresh_path(p['saved_cl_path'])
    outputs=[receipt,progress,once,export];protected={common._key(x['path'])for x in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(x)for x in outputs})==4 and not protected.intersection(map(common._key,outputs)),'Continuation output alias')
    require(all(not x.exists() and not x.is_symlink()for x in outputs),'Prior continuation or output exists; no automatic replay')
    require(all(x.parent.is_dir()for x in (receipt,progress,once)),'Existing evidence parents required')
    return p,loaded,registration,typelib,abi,receipt,once,failed,fp


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,failed,fp=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,maximum_SetTool=0,maximum_GTP=4,maximum_Save=1,adoption_pending_live_snapshot=True,native_guard_preflight=loaded['native_guard_preflight'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=base.authority.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=deepcopy(loaded['ownership']),
          zero_native_predecessor_pin=deepcopy(loaded['zero_native_predecessor_pin']),zero_native_proof=deepcopy(loaded['zero_native_proof']),tool_creation_pin=deepcopy(failed['tool_creation_pin']),adopted_assignment_receipt_pin=fp,adopted_actions=deepcopy(failed['actions']),background_contract=deepcopy(loaded['background_contract']),
          interface_audit=abi,live_pins=deepcopy(loaded['pins']),checkpoint_pins=deepcopy(loaded['checkpoint_pins']),replacement_tool=deepcopy(loaded['replacement_tool_dimensions']))
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_backend(backend,journal,loaded)
