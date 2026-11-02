"""Continue four observed definitions; no Insert action is available here."""
from copy import deepcopy
from pathlib import Path
from math import isfinite, nextafter, inf, ulp
import hashlib
from scripts import sw_cam_local_operation_packet as prior
from scripts.sw_cam_rough_firstcut import require
engine=prior.engine
group=prior.group
common=prior.common
assembly=prior.assembly
config=engine.config
generation=engine.generation
SCOPE='EXISTING_LOCAL_DEFINITIONS_DEPTH_REPRESENTATION_CONTINUATION_V1'
ACTION='continue_local_group_definitions'
ACK='adopt4_verified_definitions_assign4_configure_generate4_save1_export1_no_insert_no_replay'
PARAMS={'process_id','expected_document_path','expected_source_sha256','failed_receipt_path','failed_receipt_sha256','failed_marker_path','failed_marker_sha256','module_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}
PARENT_PRODUCER_SHA='5be473db515e0b74e43dab83ced6d39e8c7e31824855707d77c7f739e4c257bf'

def adopt_levels(expected,actual):
    require(type(expected)is dict and type(actual)is dict and set(expected)==set(actual),'Exact machining level keys required')
    a=expected['levels']['machining_depth_native'];b=actual['levels']['machining_depth_native']
    require(type(a)is float and type(b)is float and isfinite(a)and isfinite(b)and a>0 and b>0,'Finite positive native depth doubles required')
    low=high=a
    for _ in range(4):low=nextafter(low,-inf);high=nextafter(high,inf)
    require(low<=b<=high and abs(a-b)<=1e-12,'Depth representation exceeds four ULP or 1e-12 mm')
    adopted=deepcopy(expected);adopted['levels']['machining_depth_native']=b
    require(group.exact(adopted,actual),'A non-depth machining level differs')
    return adopted,dict(expected_native_mm=a,observed_native_mm=b,absolute_delta_mm=abs(a-b),ulp_of_expected_mm=ulp(a),representable_steps_limit=4,absolute_limit_mm=1e-12,all_other_levels_exact=True,geometric_allowance_changed=False)

def partial_contract(r,loaded):
    require(r['scope']==prior.SCOPE and r['status']=='uncertain'and r['phase']=='finished'and r['failed_phase']=='insert:right_finish','Exact completed-definition failure required')
    require(r['module_pin']['sha256']==PARENT_PRODUCER_SHA and prior._file_hash(prior.__file__)==PARENT_PRODUCER_SHA,'Historical producer differs')
    require(r['issue']['type']=='ValueError'and r['issue']['locations']==[dict(file='sw_cam_local_operation_group.py',function='run_backend',line=164),dict(file='sw_cam_rough_firstcut.py',function='require',line=38)],'Only the exact depth-comparison stop may be adopted')
    require(r['mutation_attempted']is True and r['model_saved']is False and r['readback_verified']is False and r.get('native_dispatch_pending')is False and r.get('cleanup_session_active')is False and not r.get('cleanup_issue'),'Completed clean nonpending definition-only stop required')
    require(not any(k in r for k in ('after_tool_parameters','after_tools','configured','generated','saved','save_stage','completed_gtp_counts')),'No later action may be adopted')
    require(group.exact(r['ownership'],loaded['ownership'])and r['source_sha256']==loaded['source_sha256'],'Same owned process lifetime and saved source required')
    require(group.exact(r['current_document'],loaded['guide_parameters']['document']),'Exact archived document state required')
    prior.clean_events(r)
    baseline=loaded['guide_parameters']['expected_parameters']
    require(group.exact(r['before'],baseline),'Historical saved17/8 baseline differs')
    expected=prior.projection.project_context(loaded['local_verified_context'],loaded['local_recipe'],r['actual_default_catalogues'],r['request']['choices'],verify_feature=prior.mixed.verify_pocket,feed_policy=r['request']['feed_policy'])
    plan=engine.validate_plan(r['plan'],baseline)
    require(group.exact(plan,expected['local_plan']),'Original plan differs from sealed choices and actual catalogues')
    require(set(r['actions'])=={'insert:'+k for k in engine.KEYS},'Only four insertion actions may exist')
    engine.protect_snapshot(baseline,r['definitions'],4)
    current=deepcopy(baseline['binding']);anchor=current['operations'][-1]['native_id']
    targets=[];changes=[];own={v['operation_native_id']:v for v in r['definitions']['parameters']}
    for i,row in enumerate(plan['rows']):
        action=r['actions']['insert:'+row['key']];oid=action['actual_native_id']
        require(type(oid)is int and all(action.get(k)is True for k in ('attempted','returned','readback_verified'))and action.get('native_dispatch_pending')is False,'All four insertions must be completed and verified')
        after=deepcopy(current);after['operations'].append(deepcopy(r['definitions']['binding']['operations'][17+i]))
        after['operation_setups'][current['operations'][-1]['setup_index']]['operation_count']+=1
        definition=engine.definitions.verify_one_addition(current,after,row,oid,anchor)
        require(group.exact(definition,action['observed']),'Insertion evidence differs from actual definition')
        levels,change=adopt_levels(row['expected_levels'],own[oid]['levels'])
        row['expected_levels']=levels;change['operation_native_id']=oid;changes.append(change)
        targets.append(dict(deepcopy(row),operation_native_id=oid,assigned_tool=deepcopy(definition['assigned_tool'])))
        current=after;anchor=oid
    require(group.exact(current,r['definitions']['binding']),'Final definition inventory differs')
    require(r['actual_new_ids']==engine.learned_contract(targets,plan,baseline),'Actual four IDs differ')
    return dict(plan=plan,targets=targets,depth_adoption=changes,definitions=deepcopy(r['definitions']))

def marker_path(p):
    key='\0'.join((SCOPE,common._key(p['expected_document_path']),p['expected_source_sha256'],p['failed_receipt_sha256']))
    return common.local_evidence_root()/('local_definitions_continue_'+hashlib.sha256(key.encode()).hexdigest()+'.json')

class Journal(assembly.Journal):
    def _marker_state(self):
        value=super()._marker_state();value.update(scope=SCOPE,adopted_receipt_pin=self.report['adopted_receipt_pin']);return value
    def pending(self,name):
        require(not name.startswith('insert:'),'Insertion is forbidden in a definition continuation')
        return super().pending(name)

class NativeBackend(prior.NativeBackend):
    def insert(self,*args,**kwargs):raise ValueError('Insertion is forbidden in a definition continuation')

def prepare_request(request,*,creation_loader=None):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact continuation action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact continuation parameter set required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31 and p['acknowledgement']==ACK,'Selected PID and explicit continuation acknowledgement required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute explicit path required')
        if key.endswith('_sha256'):prior._sha(value)
    require(p['module_sha256']==prior._file_hash(__file__),'Continuation producer changed')
    failed,failedpin=prior.read_json_pin(p['failed_receipt_path'],p['failed_receipt_sha256'],limit=32*1024*1024)
    marker,markerpin=prior.read_json_pin(p['failed_marker_path'],p['failed_marker_sha256'],limit=1024*1024)
    old=failed['request']
    for key in ('process_id','expected_source_sha256'):require(group.exact(p[key],old[key]),'Original source/PID differs')
    require(common._key(p['expected_document_path'])==common._key(old['expected_document_path']),'Original document path differs')
    require(common._key(p['failed_marker_path'])==common._key(prior.marker_path(old)),'Original source marker path differs')
    wanted=assembly.Journal(failed,old['receipt_path'],p['failed_marker_path'])._marker_state()
    require(group.exact(marker,wanted),'Original completed-definition marker differs')
    for name in ('expected_document_path','source_backup_path'):
        path=Path(old[name]);require(path.is_file()and not path.is_symlink()and prior._file_hash(path)==p['expected_source_sha256'],'Saved source or immutable backup changed')
    recipe,recipepin=prior.read_json_pin(old['recipe_path'],old['recipe_sha256'])
    loader=prior.serial.load_completed if creation_loader is None else creation_loader
    outer=loader(str(Path(old['tool_receipt_path']).resolve()),old['tool_receipt_sha256'],process_id=p['process_id'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    loaded=prior.projection.project_context(outer,recipe,None,old['choices'],verify_feature=prior.mixed.verify_pocket,feed_policy=old['feed_policy'])
    loaded.update(source_sha256=outer['source_sha256'],tool_catalogue_ids=engine.ids(outer['serial_flat_catalogue'],'native_id'),local_verified_context=deepcopy(outer),local_recipe=deepcopy(recipe),sealed_choices=deepcopy(old['choices']),sealed_feed_policy=deepcopy(old['feed_policy']))
    adopted=partial_contract(failed,loaded);loaded.update(local_plan=adopted['plan'],adopted_definition_context=adopted)
    toolpin=common._pin(old['tool_receipt_path'])
    require(toolpin['sha256']==old['tool_receipt_sha256']and group.exact(failed['tool_receipt_pin'],toolpin),'Tool creation authority differs')
    require(group.exact(failed['recipe_pin'],recipepin),'Original recipe authority differs')
    prior.partition_pins(outer,loaded,[failedpin,markerpin,toolpin,recipepin,common._pin(old['source_backup_path']),common._pin(__file__)])
    selfpin=common._pin(__file__);loaded['pins']=common._merge(loaded['pins'],[selfpin])
    loaded['phase_proof_pins']=[v for v in loaded['phase_proof_pins']if common._key(v['path'])!=common._key(selfpin['path'])]
    require(len(loaded['pins'])<=63,'Native closure plus source must remain within64')
    loaded['pin_partition'].update(live_file_count=len(loaded['pins']),maximum_with_source=len(loaded['pins'])+1,phase_proof_count=len(loaded['phase_proof_pins']))
    registration=common.discover_export_registration(loaded,outer['registration']['clsid'])
    require(group.exact(registration,outer['registration']),'Checked native registration changed')
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in loaded['pins'],'Exact typelib required')
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['native_guard_preflight']=prior.guard_reuse.guard_constructor_preflight(p,loaded,typelib)
    abi=dict(generation=prior.native.generation.audit(typelib,loaded['generated_pin']),nc=prior.micro.audit(typelib,loaded['generated_pin']))
    receipt=common._local_receipt(p['receipt_path']);continuation_marker=marker_path(p)
    outputs=[receipt,Path(p['progress_path']),continuation_marker,prior.cl.prior._fresh_path(p['saved_cl_path'])]
    protected={common._key(v['path'])for v in loaded['pins']+loaded['phase_proof_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in outputs})==len(outputs),'Separate fresh continuation outputs required')
    for out in outputs:require(not out.exists()and not out.is_symlink()and common._key(out)not in protected,'Prior continuation or evidence alias forbids replay')
    for out in outputs[:3]:require(out.parent.is_dir(),'Existing output parent required')
    loaded.update(dispatch_ready=True,adopted_receipt_pin=failedpin,adopted_marker_pin=markerpin)
    return p,loaded,failed,registration,typelib,abi,receipt,continuation_marker,toolpin,recipepin

def run_once(backend,journal,loaded,hooks=None):
    require(not journal.created and not journal.claimed,'Existing or claimed Journal cannot be re-entered')
    require(not journal.receipt.exists()and not journal.marker.exists(),'Existing continuation evidence forbids replay')
    hooks=assembly.hooks()if hooks is None else hooks
    r=journal.report;baseline=deepcopy(loaded['guide_parameters']['expected_parameters'])
    adopted=loaded['adopted_definition_context'];plan=deepcopy(adopted['plan'])
    backend.learned=deepcopy(adopted['targets'])
    r.update(scope=SCOPE,status='error',phase='preflight',actions={},actual_new_ids=engine.ids(backend.learned,'operation_native_id'),mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,model_saved=False,readback_verified=False,automatic_retry=False,automatic_rollback=False,operation_creation_attempted=False,physical_cutting_conditions_qualified=False,production_qualified=False,geometry_accepted=False,persistence_after_reopen_verified=False,continuation_ready=False,plan=deepcopy(plan),depth_adoption=deepcopy(adopted['depth_adoption']))
    try:
        journal.create();backend.start();r['before']=backend.capture_snapshot('adopt_existing_definitions',full=True)
        require(group.exact(r['before'],adopted['definitions']),'Fresh complete21/12 state differs from archived definitions')
        r['definitions']=deepcopy(r['before']);engine.protect_snapshot(baseline,r['definitions'],4)
        own={x['operation_native_id']:x for x in r['definitions']['parameters']};assigned_ids=[]
        for target in backend.learned:
            oid=target['operation_native_id'];require(group.exact(own[oid]['levels'],target['expected_levels']),'Adopted actual machining levels differ')

            label='SetTool:'+str(oid);journal.execute(label,lambda pending:backend.assign(target,pending));backend.refresh_dirty()
            target['assigned_tool']=deepcopy(plan['tool'])
            captured=backend.capture_snapshot('after_tool_'+str(oid),own=target)
            engine.protect_binding(baseline['binding'],captured['binding'],4)
            assigned_ids.append(oid);engine.verify_assigned_binding(r['definitions']['binding'],captured['binding'],assigned_ids,plan['tool'])
            require(len(captured['parameters'])==1,'Exactly assigned own parameter group required')
            actual=captured['parameters'][0];hooks.verify_assignment(own[oid],actual,target,loaded)
            require(actual['operation_native_id']==oid and group.exact(actual['tool']['generic'],plan['tool']),'Immediate assigned tool readback differs')
            config.verify_automatic_target(own[oid],actual)
            r.setdefault('after_tool_parameters',{})[str(oid)]=deepcopy(actual);journal.verified(label,actual)
        r['after_tools']=backend.capture_snapshot('after_tools',full=True);engine.protect_snapshot(baseline,r['after_tools'],4)
        engine.verify_assigned_binding(r['definitions']['binding'],r['after_tools']['binding'],assigned_ids,plan['tool'])
        for actual in r['after_tools']['parameters'][8:]:
            require(group.exact(actual,r['after_tool_parameters'][str(actual['operation_native_id'])]),'Another assignment changed an already observed target')
        for target in backend.learned:hooks.configure_selected(backend,journal,target,loaded)
        r['configured']=backend.capture_snapshot('configured',full=True);engine.protect_snapshot(baseline,r['configured'],4)
        hooks.verify_configured(r['after_tools'],r['configured'],backend.learned,loaded)
        counts={}
        for target in backend.learned:
            label='GTP:'+str(target['operation_native_id']);journal.execute(label,lambda pending:backend.generate(target,pending));backend.refresh_dirty()
            outcome=backend.outcome(target);generation.status_contract(outcome,target,True)
            counts[target['operation_native_id']]=deepcopy(outcome['record_counts']);journal.verified(label,outcome)
        r['generated']=backend.capture_snapshot('generated',full=True)
        # Persist completed GTP evidence before checking automatic parameter changes.
        r['completed_gtp_counts']=deepcopy(counts);r['learned_targets']=deepcopy(backend.learned);journal.persist()
        r['generation_verification']=engine.verify_generation(r['configured'],r['generated'],backend.learned,counts,plan['feed_policy'])
        r['save_stage']={};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['generated'])
            r['saved']=backend.capture_snapshot('saved',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['generated']),'Save changed complete21/12 snapshot')
        def save():
            value=backend.save();entry=r['actions']['SaveActiveDocument'];require(entry['attempted']is True,'Save bypassed pending')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value))
            r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved source did not advance')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding'])
        r['saved_cl_verification']=hooks.verify_saved_cl(loaded['generated']['saved_cl'],r['saved_cl'],backend.learned,r['saved'])
        backend.finish();r.update(status='saved_existing_local_group_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:
        from scripts.sw_cam import _error
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:
            from scripts.sw_cam import _error
            r.update(status='uncertain'if r['mutation_attempted']else'error',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r

def validate_completed(report,loaded):
    r=report;baseline=loaded['guide_parameters']['expected_parameters']
    require(r['scope']==SCOPE and r['status']=='saved_existing_local_group_review_required'and r['phase']=='finished','Completed local group receipt required')
    require(r['model_saved']is True and r['readback_verified']is True and r['continuation_ready']is True and r.get('native_dispatch_pending')is False,'Saved verified nonpending group required')
    for key in ('production_qualified','physical_cutting_conditions_qualified','geometry_accepted','persistence_after_reopen_verified'):
        require(r[key]is False,'Unqualified machining and persistence boundaries must remain explicit')
    require(not r.get('issue')and not r.get('cleanup_issue'),'No unresolved native or cleanup failure permitted')
    prior.clean_events(r)
    require(group.exact(r['before'],loaded['adopted_definition_context']['definitions']),'Exact adopted21/12 baseline required')
    require(group.exact(r['adopted_receipt_pin'],loaded['adopted_receipt_pin'])and group.exact(r['adopted_marker_pin'],loaded['adopted_marker_pin']),'Adoption authority changed')
    require(r.get('operation_creation_attempted')is False,'Continuation cannot insert operations')
    require(group.exact(r['definitions'],r['before']),'Definitions differ from exact freshly adopted state')
    plan=engine.validate_plan(r['plan'],baseline);targets=r['learned_targets']
    require(group.exact(plan,loaded['adopted_definition_context']['plan'])and group.exact(r['depth_adoption'],loaded['adopted_definition_context']['depth_adoption']),'Only exact observed depth normalization is allowed')
    ids=engine.learned_contract(targets,plan,baseline)
    require(r['actual_new_ids']==ids and group.exact(plan['feed_policy'],loaded['sealed_feed_policy']),'Learned IDs or sealed feed policy changed')
    engine.protect_snapshot(baseline,r['definitions'],4);engine.protect_snapshot(baseline,r['after_tools'],4)
    engine.protect_snapshot(baseline,r['configured'],4)
    engine.verify_assigned_binding(r['definitions']['binding'],r['after_tools']['binding'],ids,loaded['configuration_tool'])
    prior.recipe_hooks.verify_configured(r['after_tools'],r['configured'],targets,loaded)
    counts={int(k):v for k,v in r['completed_gtp_counts'].items()}
    engine.verify_generation(r['configured'],r['generated'],targets,counts,plan['feed_policy'])
    require(group.exact(r['generated'],r['saved']),'Saved complete state changed')
    actions=r['actions'];required=['SetTool:'+str(i)for i in ids]+['GTP:'+str(i)for i in ids]+['SaveActiveDocument']
    allowed=set(required)
    for target in targets:
        oid=str(target['operation_native_id']);specs=engine.config.ROUGH_FIELDS if target['operation_type']==0 else engine.config.FINISH_FIELDS
        required += [oid+':'+spec[0]for spec in specs]+[oid+':NC:GetSpndlSpeed',oid+':NC:XYFeed']
        if target['operation_type']==0:required += [oid+':entry:'+name for name in ('CreateStartPointInstance','CreatePosition','SetPointCoordinates','SetPointPosition','AddStartPoint','SetStartPointList')]
        allowed.add('CNC0:'+oid)
    allowed.update(required)
    require(set(required)<=set(actions)<=allowed,'Exact declared action set required; no unrelated action may be adopted')
    for name,row in actions.items():
        require(row.get('readback_verified')is True and row.get('native_dispatch_pending',False)is False,'All actions must have complete readback')
        if row['attempted']is True:require(row['returned']is True,'Every claimed native action must return')
        else:require(row.get('observed',{}).get('already_satisfied')is True,'Only explicit already-satisfied actions may be unclaimed')
    for prefix,total in [('insert:',0),('SetTool:',4),('GTP:',4)]:
        require(sum(name.startswith(prefix)for name in actions)==total,'Bounded native action count differs')
    native_required=['SetTool:'+str(i)for i in ids]+['GTP:'+str(i)for i in ids]+['SaveActiveDocument']
    native_required += [str(t['operation_native_id'])+':entry:'+name for t in targets if t['operation_type']==0 for name in ('CreateStartPointInstance','CreatePosition','SetPointCoordinates','SetPointPosition','AddStartPoint','SetStartPointList')]
    require(all(actions[n]['attempted']is True and actions[n]['returned']is True for n in native_required),'Required actions must actually execute once')
    definitions={row['native_id']:row for row in r['definitions']['binding']['operations']}
    for target in targets:
        oid=target['operation_native_id']
        assigned=actions['SetTool:'+str(oid)]['observed']
        require(group.exact(assigned,r['after_tool_parameters'][str(oid)]),'SetTool action readback differs from immediate own snapshot')
        outcome=actions['GTP:'+str(oid)]['observed']
        prior.native.generation.status_contract(outcome,target,True)
        require(group.exact(outcome['record_counts'],counts[oid]),'GTP action readback differs from completed path counts')
    new=prior._sha(r['saved_source_sha256']);require(new!=r['source_sha256'],'Saved source must advance')
    require(actions['SaveActiveDocument']['observed']==new,'Save readback hash differs')
    require(r['source_transition']['source_before_sha256']==r['source_sha256']and r['source_transition']['source_after_sha256']==new and type(r['source_transition']['strict_save_return'])is int and r['source_transition']['strict_save_return']==0,'Exact native source transition required')
    require(r['source_transition']['document']['needs_save']is False,'Saved document must be clean')
    proof=prior.cl.verify_saved(loaded['generated']['saved_cl'],r['saved_cl'],targets,r['saved'])
    require(r['saved_cl']['source_sha256']==new,'CL export must refer to new saved source')
    require([x['phase']for x in r['phase_proof_checks']]==['before_native_start','before_save','after_export_and_cleanup']and all(x['verified']is True for x in r['phase_proof_checks']),'Whole phase authority checks required')
    return dict(status='saved_local_group_authority_verified',operation_ids=ids,
        protected_operations=17,protected_parameters=8,protected_cl_streams=14,
        saved_operations=21,saved_parameters=12,saved_cl_streams=18,cl_verification=proof,
        source_sha256=new,nominal_geometry_accepted=False,physical_cutting_conditions_qualified=False,production_qualified=False)


def dispatch_request(request,*,validate_only=False):
    p,loaded,failed,registration,typelib,abi,receipt,marker,pin,recipe_pin=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE,
        expected_counts=dict(operations=21,parameters=12,paths=18,tools=21),
        pin_partition=loaded['pin_partition'],native_guard_preflight=loaded['native_guard_preflight'],
        feature_ids=[v['header']['native_id']for v in loaded['root_pocket_full_features']],tool_native_id=loaded['configuration_tool']['native_id'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['phase_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=deepcopy(p),module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
            adopted_receipt_pin=deepcopy(loaded['adopted_receipt_pin']),adopted_marker_pin=deepcopy(loaded['adopted_marker_pin']),
            ownership=deepcopy(loaded['ownership']),tool_receipt_pin=pin,recipe_pin=recipe_pin,
            live_pins=deepcopy(loaded['pins']),phase_proof_pins=deepcopy(loaded['phase_proof_pins']),
            pin_partition=deepcopy(loaded['pin_partition']),native_source_audit=deepcopy(loaded['native_source_audit']),
            interface_audit=abi,tool_dimensions=deepcopy(loaded['local_tool_dimensions']))
        journal=Journal(report,receipt,marker)
        backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist,before_generate=prior.nc.before_generate,exporter=prior.cl.export_saved)
        result=run_once(backend,journal,loaded)
        if result['readback_verified']is True:
            try:
                result['terminal_verification']=validate_completed(result,loaded)
                result['saved_checkpoint']=dict(source_path=p['expected_document_path'],source_sha256=result['saved_source_sha256'],document=deepcopy(result['source_transition']['document']),
                    configuration=deepcopy(loaded['guide_parameters']['configuration']),snapshot=deepcopy(result['saved']),saved_cl=deepcopy(result['saved_cl']),
                    learned_targets=deepcopy(result['learned_targets']),tool_catalogue=deepcopy(loaded['serial_flat_catalogue']),tool_dimensions=deepcopy(loaded['local_tool_dimensions']),
                    full_native_features=deepcopy(loaded['root_pocket_full_features']),feature_specs=deepcopy(loaded['root_pocket_specs']),
                    current_counts=dict(operations=21,parameters=12,paths=18,tools=21),nominal_geometry_accepted=False,production_qualified=False)
            except Exception as exc:
                from scripts.sw_cam import _error
                result.update(status='uncertain',readback_verified=False,continuation_ready=False,terminal_issue=_error(exc))
            journal.persist()
        return result
