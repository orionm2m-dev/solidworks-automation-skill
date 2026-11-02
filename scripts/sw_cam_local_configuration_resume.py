"""Adopt a completed configuration prefix; configure only the remainder and save.

No operation insertion, tool assignment or toolpath generation is exposed. The
interrupted receipt remains immutable, including its unconfirmed event cleanup.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
from scripts import sw_cam_local_operation_continue as parent
from scripts import sw_cam_local_configuration_cl as cl
from scripts.sw_cam_rough_firstcut import require
prior=parent.prior;engine=parent.engine;group=parent.group;common=parent.common
config=parent.config;generation=parent.generation;assembly=parent.assembly
SCOPE='VERIFIED_LOCAL_CONFIGURATION_PREFIX_REMAINING_SAVE_V1'
ACTION='resume_local_group_configuration'
ACK='adopt30_verified_actions_configure_remaining_save1_export14_no_insert_no_settool_no_gtp'
PARAMS={'process_id','expected_document_path','expected_source_sha256','partial_receipt_path','partial_receipt_sha256','partial_marker_path','partial_marker_sha256','writer_stop_receipt_path','writer_stop_receipt_sha256','module_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}
PARENT_SHA='f211f6851d5a7da2afb6b9739d004ea5acab858a9def435e0716ac6ea7024195'
ENTRY_ACTIONS=('CreateStartPointInstance','CreatePosition','SetPointCoordinates','SetPointPosition','AddStartPoint','SetStartPointList')

def expected_prefix(ids):
    return ['SetTool:'+str(i)for i in ids]+[str(ids[0])+':'+s[0]for s in config.ROUGH_FIELDS]+[str(ids[0])+':NC:'+k for k in ('GetSpndlSpeed','XYFeed')]+[str(ids[0])+':entry:'+k for k in ENTRY_ACTIONS]+[str(ids[1])+':'+s[0]for s in config.FINISH_FIELDS[:10]]

def verified_action(row):
    require(row.get('readback_verified')is True and row.get('native_dispatch_pending',False)is False and row.get('status')=='verified','Completed nonpending action required')
    require(type(row.get('attempted'))is bool and type(row.get('returned'))is bool,'Strict action outcome flags required')
    if row['attempted']:
        require(row.get('native_dispatch_pending')is False and row['returned']is True and group.exact(row['native_return'],dict(python_type='int',value_recorded=True,value=0)),'Exact returned native HRESULT0 required')
    else:require(row['returned']is False and row.get('observed',{}).get('already_satisfied')is True,'Only observed already-satisfied action may be unattempted')

def captured_own(report,label,oid):
    rows=[c for c in report['captures']if c.get('label')==label]
    require(len(rows)==1 and len(rows[0]['parameters'])==1,'One immutable own capture required')
    row=config.parameter_projection(rows[0]['parameters'][0]);require(row['operation_native_id']==oid and row['read_complete']is True,'Own capture belongs to another operation')
    require(group.exact(rows[0]['binding'],report['after_tools']['binding']),'Own capture binding changed')
    return row

def expected_partial_snapshot(report):
    """Exact prefix: completed first rough+entry, first ten second-finish fields."""
    r=report;ids=r['actual_new_ids'];require(len(ids)==4 and len(set(ids))==4,'Four exact IDs required')
    require(list(r['actions'])==expected_prefix(ids)and len(r['actions'])==30,'Only the exact thirty-action prefix may be adopted')
    for value in r['actions'].values():verified_action(value)
    expected=deepcopy(r['after_tools']);byid={v['operation_native_id']:v for v in expected['parameters']}
    require(len(expected['parameters'])==12 and len(byid)==12,'Exact full21/12 after-tool snapshot required')
    rough=captured_own(r,'entry_after_'+str(ids[0]),ids[0]);old=byid[ids[0]]
    require(group.exact(prior.recipe_hooks.controlled_projection(old,entry_initialized=True),prior.recipe_hooks.controlled_projection(rough,entry_initialized=True)),'Completed rough changed unrequested fields')
    target=r['plan']['rows'][0]
    for spec in config.ROUGH_FIELDS:
        actual=config.field_value(rough,spec);require(group.exact(actual,target['fields'][spec[0]]),'Completed rough field differs from sealed target')
        a=r['actions'][str(ids[0])+':'+spec[0]];observed=a['observed'].get('value')if not a['attempted']else a['observed']
        require(group.exact(observed,actual),'Completed rough action/capture differs')
    require(group.exact(rough['nc']['feeds_compensation'],r['nc_readbacks'][str(ids[0])]['values']),'Completed rough NC differs')
    prior.micro.verify_final(rough['nc']['feeds_compensation'])
    nc_before=old['nc']['feeds_compensation']
    for field in ('GetSpndlSpeed','XYFeed'):
        observed=r['actions'][str(ids[0])+':NC:'+field]['observed']
        require(type(observed)is dict and set(observed)=={'readback','verification'},'Exact recorded NC readback evidence required')
        proof=prior.micro.verify_readback(nc_before,observed['readback'],field)
        require(group.exact(proof,observed['verification']),'Recorded NC verification differs')
        nc_before=observed['readback']
    require(group.exact(nc_before,rough['nc']['feeds_compensation']),'Recorded final NC action differs from complete own capture')
    factory=r['actions'][str(ids[0])+':entry:CreateStartPointInstance']['observed']
    require(group.exact(factory,dict(type_raw=1,returned_nonnull=True)),'Recorded point factory outcome differs')
    position=r['actions'][str(ids[0])+':entry:CreatePosition']['observed']
    require(group.exact(position,dict(coordinates=[0.0,0.0,0.0],returned_nonnull=True)),'Recorded position factory outcome differs')
    prior.entry.verify_startpoint(rough['startpoints'],target['entry_point_native'])
    require(group.exact(rough['startpoints'],r['entry_readbacks'][str(ids[0])]),'Completed attached entry differs')
    for key in ('SetPointCoordinates','SetPointPosition'):
        require(group.exact(r['actions'][str(ids[0])+':entry:'+key]['observed'],target['entry_point_native']),'Completed point coordinates differ')
    for key in ('AddStartPoint','SetStartPointList'):
        require(group.exact(r['actions'][str(ids[0])+':entry:'+key]['observed'],dict(count=1,type_raw=1,position_native=target['entry_point_native'])),'Completed point attachment differs')
    for index,row in enumerate(expected['parameters']):
        if row['operation_native_id']==ids[0]:expected['parameters'][index]=rough
    finish=byid[ids[1]];target=r['plan']['rows'][1]
    for spec in config.FINISH_FIELDS[:10]:
        key=spec[0];action=r['actions'][str(ids[1])+':'+key]
        value=action['observed']if action['attempted']else action['observed']['value']
        require(group.exact(value,target['fields'][key]),'Completed finish action differs from sealed target')
        finish['finish_fields'][key]=deepcopy(value)
        member=config.finish.DEFAULT_FIELDS[key]
        finish['finish'][member]['raw']=deepcopy(value[0]if key in ('first_depth','max_depth','side_step')else value)
    return expected

def partial_contract(r,loaded):
    require(r['scope']==parent.SCOPE and r['status']=='error'and r['phase']==str(r['actual_new_ids'][1])+':perimeter'and r.get('issue')is None,'Exact interrupted configuration prefix required')
    require(r['module_pin']['sha256']==PARENT_SHA and prior._file_hash(parent.__file__)==PARENT_SHA,'Frozen prefix producer changed')
    require(r['mutation_attempted']is True and r['model_saved']is False and r['readback_verified']is False and r['native_dispatch_pending']is False,'Unsaved nonpending prefix required')
    require(not any(k in r for k in ('configured','generated','save_stage','saved','completed_gtp_counts')),'A later stage may not be silently adopted')
    require(group.exact(r['ownership'],loaded['ownership'])and r['source_sha256']==loaded['source_sha256'],'Same saved source and process lifetime required')
    require(group.exact(r['current_document'],loaded['guide_parameters']['document']),'Archived SW document state changed')
    m=r['messages'];require(m['subscribed']is True and m['active']is True and m['disconnected']is False and not any(m.get(k)for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'Exact interrupted event observation required; cleanup is not inferred')
    a=loaded['adopted_definition_context'];baseline=loaded['guide_parameters']['expected_parameters']
    require(group.exact(r['before'],a['definitions'])and group.exact(r['definitions'],r['before'])and group.exact(r['plan'],a['plan'])and group.exact(r['depth_adoption'],a['depth_adoption']),'Adopted definition/plan lineage differs')
    require(group.exact(r['adopted_receipt_pin'],loaded['adopted_receipt_pin'])and group.exact(r['adopted_marker_pin'],loaded['adopted_marker_pin']),'Definition authority pins differ')
    targets=deepcopy(a['targets']);ids=engine.ids(targets,'operation_native_id')
    require(r['actual_new_ids']==ids,'Exact four existing operation IDs required')
    engine.protect_snapshot(baseline,r['after_tools'],4)
    engine.verify_assigned_binding(r['definitions']['binding'],r['after_tools']['binding'],ids,r['plan']['tool'])
    old={v['operation_native_id']:v for v in r['definitions']['parameters']}
    actual={v['operation_native_id']:v for v in r['after_tools']['parameters']}
    for target in targets:
        oid=target['operation_native_id'];target['assigned_tool']=deepcopy(r['plan']['tool'])
        require(group.exact(r['actions']['SetTool:'+str(oid)]['observed'],r['after_tool_parameters'][str(oid)])and group.exact(actual[oid],r['after_tool_parameters'][str(oid)]),'Immediate assignment authority differs')
        prior.recipe_hooks.verify_assignment(old[oid],actual[oid],target,loaded);config.verify_automatic_target(old[oid],actual[oid])
    expected=expected_partial_snapshot(r);cl.contract(expected['binding'],baseline['binding'],targets)
    return dict(targets=targets,expected_snapshot=expected,adopted_action_names=expected_prefix(ids),old_cleanup_confirmed=False)

def writer_stop_contract(stop,p,partialpin):
    require(stop['scope']=='POST_CLIENT_TIMEOUT_WRITER_OBSERVATION'and stop['process_id']==p['process_id']and stop['source_sha256']==p['expected_source_sha256'],'Matching writer observation required')
    require(common._key(stop['partial_receipt_path'])==common._key(partialpin['path'])and stop['partial_receipt_sha256']==partialpin['sha256']and stop['canonical_receipt_unchanged']is True,'Writer stop must bind exact frozen partial receipt')
    require(stop['timed_out_writer_pid']is None and stop['exact_writer_pid_recorded']is False and stop['client_exited']is True and type(stop['client_exit_code'])is int and stop['client_exit_code']==1,'No invented writer PID or unfinished client allowed')
    require(stop['native_dispatch_pending']is False and stop['verified_action_count']==30 and stop['owned_process_mutex_acquired_and_released']is True and stop['old_event_cleanup_confirmed']is False,'Exact observed nonpending stop/lock required')
    proc,pin=prior.read_json_pin(stop['candidate_process_observation']['path'],stop['candidate_process_observation']['sha256'])
    require(proc['candidates']==[]and proc['process_name_filter']=='python*'and proc['command_line_filter']=='*solidworks-automation*'and proc['created_since_utc']==stop['candidate_process_observation']['created_since_utc']and stop['candidate_process_observation']['matching_process_count']==0,'No remaining candidate writer process required')
    client,clientpin=prior.read_json_pin(stop['client_result']['path'],stop['client_result']['sha256'],limit=8*1024*1024)
    require(client['status']=='timeout','Actual client timeout evidence required')
    return [pin,clientpin]

def marker_path(p):
    key='\0'.join((SCOPE,common._key(p['expected_document_path']),p['expected_source_sha256'],p['partial_receipt_sha256']))
    return common.local_evidence_root()/('local_config_resume_'+hashlib.sha256(key.encode()).hexdigest()+'.json')

class Journal(assembly.Journal):
    def _marker_state(self):return dict(super()._marker_state(),scope=SCOPE,adopted_receipt_pin=self.report['adopted_receipt_pin'])
    def entry(self,name):
        require(name not in self.report.get('adopted_action_names',[])and not name.startswith(('insert:','SetTool:','GTP:')),'Previously completed or forbidden action cannot be issued')
        return super().entry(name)

class NativeBackend(prior.NativeBackend):
    def insert(self,*a,**k):raise ValueError('Operation insertion forbidden')
    def assign(self,*a,**k):raise ValueError('Tool reassignment forbidden')
    def generate(self,*a,**k):raise ValueError('Generation forbidden in configuration checkpoint')

def configure_remaining(backend,journal,target,loaded):
    oid=target['operation_native_id'];done=set(journal.report['adopted_action_names'])
    for spec in config.ROUGH_FIELDS if target['operation_type']==0 else config.FINISH_FIELDS:
        label=str(oid)+':'+spec[0]
        if label in done:continue
        wanted=target['fields'][spec[0]];old=backend.field(target,spec)
        if group.exact(old,wanted):journal.entry(label);journal.verified(label,dict(already_satisfied=True,value=old));continue
        journal.execute(label,lambda pending,spec=spec,wanted=wanted:backend.set_field(target,spec,wanted,pending));backend.refresh_dirty()
        actual=backend.field(target,spec);require(group.exact(actual,wanted),'Remaining field readback differs');journal.verified(label,actual)
    nc_names=[str(oid)+':NC:'+x for x in ('GetSpndlSpeed','XYFeed')]
    require(all(x in done for x in nc_names)or not any(x in done for x in nc_names),'Partial NC adoption is outside this verified prefix')
    if not all(x in done for x in nc_names):prior.nc.configure_nc(backend,journal,target,loaded)
    if target['operation_type']==0:
        names=[str(oid)+':entry:'+x for x in ENTRY_ACTIONS]
        require(all(x in done for x in names)or not any(x in done for x in names),'Partial entry factory cannot be replayed')
        if not all(x in done for x in names):prior.entry.apply_entry(backend,journal,target,target['entry_point_native'])

def prepare_request(request,*,creation_loader=None):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact configuration-resume action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact configuration-resume fields required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31 and p['acknowledgement']==ACK,'Selected PID and exact no-GTP acknowledgement required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v)is str and Path(v).is_absolute(),'Absolute explicit path required')
        if k.endswith('_sha256'):prior._sha(v)
    require(p['module_sha256']==prior._file_hash(__file__),'Configuration-resume producer changed')
    partial,ppin=prior.read_json_pin(p['partial_receipt_path'],p['partial_receipt_sha256'],limit=32*1024*1024)
    marker,mpin=prior.read_json_pin(p['partial_marker_path'],p['partial_marker_sha256'],limit=8*1024*1024)
    stop,stop_pin=prior.read_json_pin(p['writer_stop_receipt_path'],p['writer_stop_receipt_sha256'])
    stop_pins=writer_stop_contract(stop,p,ppin)
    original=partial['request']
    for key in ('process_id','expected_source_sha256'):require(group.exact(p[key],original[key]),'Original source/PID differs')
    require(common._key(p['expected_document_path'])==common._key(original['expected_document_path']),'Original document differs')
    require(common._key(p['partial_marker_path'])==common._key(parent.marker_path(original)),'Exact interrupted source marker required')
    wanted=parent.Journal(partial,original['receipt_path'],p['partial_marker_path'])._marker_state()
    require(group.exact(marker,wanted),'Interrupted marker differs from immutable partial receipt')
    failed,failedpin=prior.read_json_pin(original['failed_receipt_path'],original['failed_receipt_sha256'],limit=32*1024*1024)
    firstmarker,firstmarkerpin=prior.read_json_pin(original['failed_marker_path'],original['failed_marker_sha256'])
    old=failed['request'];require(common._key(original['failed_marker_path'])==common._key(prior.marker_path(old)),'Original definition marker path differs')
    require(group.exact(firstmarker,assembly.Journal(failed,old['receipt_path'],original['failed_marker_path'])._marker_state()),'Original definition marker differs')
    for name in ('expected_document_path','source_backup_path'):
        path=Path(old[name]);require(path.is_file()and not path.is_symlink()and prior._file_hash(path)==p['expected_source_sha256'],'Current source or immutable tool checkpoint changed')
    recipe,recipepin=prior.read_json_pin(old['recipe_path'],old['recipe_sha256'])
    loader=prior.serial.load_completed if creation_loader is None else creation_loader
    outer=loader(str(Path(old['tool_receipt_path']).resolve()),old['tool_receipt_sha256'],process_id=p['process_id'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    loaded=prior.projection.project_context(outer,recipe,None,old['choices'],verify_feature=prior.mixed.verify_pocket,feed_policy=old['feed_policy'])
    loaded.update(source_sha256=outer['source_sha256'],tool_catalogue_ids=engine.ids(outer['serial_flat_catalogue'],'native_id'),local_verified_context=deepcopy(outer),local_recipe=deepcopy(recipe),sealed_choices=deepcopy(old['choices']),sealed_feed_policy=deepcopy(old['feed_policy']))
    adopted=parent.partial_contract(failed,loaded)
    loaded.update(local_plan=adopted['plan'],adopted_definition_context=adopted,adopted_receipt_pin=failedpin,adopted_marker_pin=firstmarkerpin)
    context=partial_contract(partial,loaded)
    toolpin=common._pin(old['tool_receipt_path']);require(toolpin['sha256']==old['tool_receipt_sha256']and group.exact(partial['tool_receipt_pin'],toolpin)and group.exact(partial['recipe_pin'],recipepin),'Exact original tool/recipe pins required')
    extras=common._merge([ppin,mpin,stop_pin,failedpin,firstmarkerpin,toolpin,recipepin,common._pin(old['source_backup_path']),common._pin(parent.__file__),common._pin(__file__),common._pin(cl.__file__)],stop_pins,partial['live_pins'],partial['phase_proof_pins'])
    prior.partition_pins(outer,loaded,extras)
    additions=[common._pin(__file__),common._pin(cl.__file__)]
    loaded['pins']=common._merge(loaded['pins'],additions);keys={common._key(x['path'])for x in additions}
    loaded['phase_proof_pins']=[x for x in loaded['phase_proof_pins']if common._key(x['path'])not in keys]
    require(len(loaded['pins'])+1<=64,'Complete native closure plus source must remain within64')
    loaded['pin_partition'].update(live_file_count=len(loaded['pins']),maximum_with_source=len(loaded['pins'])+1,phase_proof_count=len(loaded['phase_proof_pins']))
    registration=common.discover_export_registration(loaded,outer['registration']['clsid']);require(group.exact(registration,outer['registration']),'Exact checked registration required')
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb');require(common._pin(typelib)in loaded['pins'],'Exact native typelib required')
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['native_guard_preflight']=prior.guard_reuse.guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);mark=marker_path(p);outputs=[receipt,Path(p['progress_path']),mark,prior.cl.prior._fresh_path(p['saved_cl_path'])]
    protected={common._key(x['path'])for x in loaded['pins']+loaded['phase_proof_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in outputs})==4,'Separate output files required')
    for out in outputs:require(not out.exists()and not out.is_symlink()and common._key(out)not in protected,'Existing output or evidence alias forbids replay')
    for out in outputs[:3]:require(out.parent.is_dir(),'Existing output parent required')
    loaded.update(configuration_resume_context=context,configuration_resume_partial=deepcopy(partial),configuration_resume_pin=ppin,configuration_resume_marker_pin=mpin,writer_stop_pin=stop_pin,dispatch_ready=True)
    return p,loaded,registration,typelib,receipt,mark

def run_once(backend,journal,loaded):
    require(not journal.created and not journal.claimed and not journal.receipt.exists()and not journal.marker.exists(),'Fresh journal/output required before any report mutation')
    r=journal.report;c=loaded['configuration_resume_context'];partial=loaded['configuration_resume_partial'];baseline=loaded['guide_parameters']['expected_parameters']
    backend.learned=deepcopy(c['targets'])
    r.update(status='error',phase='preflight',actions={},adopted_action_names=deepcopy(c['adopted_action_names']),actual_new_ids=engine.ids(backend.learned,'operation_native_id'),mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,model_saved=False,readback_verified=False,automatic_retry=False,automatic_rollback=False,operation_creation_attempted=False,tool_assignment_attempted=False,GTP_attempted=False,physical_cutting_conditions_qualified=False,production_qualified=False,geometry_accepted=False,persistence_after_reopen_verified=False,old_event_cleanup_confirmed=False)
    try:
        journal.create();backend.start();r['before']=backend.capture_snapshot('adopt_verified_configuration_prefix',full=True)
        require(group.exact(r['before'],c['expected_snapshot']),'Fresh21/12 differs from exact archived30-action projection')
        engine.protect_snapshot(baseline,r['before'],4);r['reconciliation_verified']=True;journal.persist()
        r['nc_readbacks']=deepcopy(partial['nc_readbacks']);r['entry_readbacks']=deepcopy(partial['entry_readbacks'])
        for target in backend.learned:configure_remaining(backend,journal,target,loaded)
        r['configured']=backend.capture_snapshot('configured_before_save',full=True);engine.protect_snapshot(baseline,r['configured'],4)
        prior.recipe_hooks.verify_configured(partial['after_tools'],r['configured'],backend.learned,loaded)
        cl.contract(r['configured']['binding'],baseline['binding'],backend.learned)
        r['save_stage']={};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['configured'])
            r['saved']=backend.capture_snapshot('saved_configuration',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['configured']),'Save changed complete configured21/12 state')
        def save():
            value=backend.save();entry=journal.report['actions']['SaveActiveDocument'];require(entry['attempted']is True,'Save bypassed pending')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value));r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved source did not advance');r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding']);r['saved_cl_verification']=cl.verify_saved(loaded['generated']['saved_cl'],r['saved_cl'],backend.learned,r['saved'])
        r['learned_targets']=deepcopy(backend.learned);backend.finish();r.update(status='saved_local_configuration_review_required',phase='finished',readback_verified=True,continuation_ready=True)
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

def remaining_action_names(targets,adopted):
    names=[]
    for t in targets:
        oid=str(t['operation_native_id'])
        names += [oid+':'+s[0]for s in config.ROUGH_FIELDS if t['operation_type']==0]if t['operation_type']==0 else [oid+':'+s[0]for s in config.FINISH_FIELDS]
        names += [oid+':NC:'+k for k in ('GetSpndlSpeed','XYFeed')]
        if t['operation_type']==0:names += [oid+':entry:'+k for k in ENTRY_ACTIONS]
    return [n for n in names if n not in adopted]+['SaveActiveDocument']

def validate_completed(r,loaded):
    c=loaded['configuration_resume_context'];partial=loaded['configuration_resume_partial'];baseline=loaded['guide_parameters']['expected_parameters']
    require(r['scope']==SCOPE and r['status']=='saved_local_configuration_review_required'and r['phase']=='finished'and r['readback_verified']is True and r['model_saved']is True and r['reconciliation_verified']is True,'Completed saved configuration checkpoint required')
    require(not r.get('issue')and not r.get('cleanup_issue')and not r.get('terminal_issue')and r.get('native_dispatch_pending')is False,'No pending or unresolved outcome permitted')
    prior.clean_events(r)
    for key in ('GTP_attempted','tool_assignment_attempted','operation_creation_attempted','physical_cutting_conditions_qualified','production_qualified','geometry_accepted','persistence_after_reopen_verified','old_event_cleanup_confirmed'):
        require(r[key]is False,'Configuration-only boundaries must remain explicit')
    require(group.exact(r['adopted_receipt_pin'],loaded['configuration_resume_pin'])and group.exact(r['adopted_marker_pin'],loaded['configuration_resume_marker_pin'])and group.exact(r['writer_stop_pin'],loaded['writer_stop_pin']),'Exact adopted/stop authority pins required')
    require(group.exact(r['before'],c['expected_snapshot'])and group.exact(r['adopted_action_names'],c['adopted_action_names']),'Exact reconciled prefix differs')
    require(group.exact(r['learned_targets'],c['targets']),'Retained target identities/assignments differ')
    actions=r['actions'];required=set(remaining_action_names(c['targets'],c['adopted_action_names']))
    optional={'CNC0:'+str(t['operation_native_id'])for t in c['targets']}
    require(required<=set(actions)<=required|optional and not set(actions).intersection(c['adopted_action_names']),'Only remaining declared actions may appear')
    for name,row in actions.items():
        require(not name.startswith(('insert:','SetTool:','GTP:')),'Forbidden action in configuration checkpoint');verified_action(row)
    engine.protect_snapshot(baseline,r['configured'],4);prior.recipe_hooks.verify_configured(partial['after_tools'],r['configured'],c['targets'],loaded)
    require(group.exact(r['configured'],r['saved']),'Saved snapshot differs from configured state')
    cl.contract(r['saved']['binding'],baseline['binding'],c['targets'])
    new=prior._sha(r['saved_source_sha256']);require(new!=r['source_sha256']and actions['SaveActiveDocument']['attempted']is True and actions['SaveActiveDocument']['observed']==new,'One actual changed-source save required')
    transition=r['source_transition'];require(transition['source_before_sha256']==r['source_sha256']and transition['source_after_sha256']==new and type(transition['strict_save_return'])is int and transition['strict_save_return']==0 and transition['document']['needs_save']is False,'Exact native Save transition required')
    proof=cl.verify_saved(loaded['generated']['saved_cl'],r['saved_cl'],c['targets'],r['saved'])
    require(r['saved_cl']['source_sha256']==new,'CL must belong to saved source')
    require([v['phase']for v in r['phase_proof_checks']]==['before_native_start','before_save','after_export_and_cleanup']and all(v['verified']is True for v in r['phase_proof_checks']),'Full phase proof checks required')
    return dict(status='saved_configuration_authority_verified',adopted_actions=30,new_generated_paths=0,saved_operations=21,saved_parameters=12,saved_cl_streams=14,cl_verification=proof,source_sha256=new,production_qualified=False,nominal_geometry_accepted=False)

def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,receipt,mark=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE,pin_partition=loaded['pin_partition'],native_guard_preflight=loaded['native_guard_preflight'],adopted_actions=30,remaining_actions=remaining_action_names(loaded['configuration_resume_context']['targets'],loaded['configuration_resume_context']['adopted_action_names']),expected_counts=dict(operations=21,parameters=12,paths=14,tools=21),GTP_allowed=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=2,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['phase_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,request=deepcopy(p),module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],adopted_receipt_pin=deepcopy(loaded['configuration_resume_pin']),adopted_marker_pin=deepcopy(loaded['configuration_resume_marker_pin']),writer_stop_pin=deepcopy(loaded['writer_stop_pin']),ownership=deepcopy(loaded['ownership']),live_pins=deepcopy(loaded['pins']),phase_proof_pins=deepcopy(loaded['phase_proof_pins']),pin_partition=deepcopy(loaded['pin_partition']),tool_dimensions=deepcopy(loaded['local_tool_dimensions']))
        journal=Journal(r,receipt,mark)
        backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,r,journal.persist,before_generate=prior.nc.before_generate,exporter=cl.export_saved)
        run_once(backend,journal,loaded)
        if r['readback_verified']is True:
            try:
                r['terminal_verification']=validate_completed(r,loaded)
                r['saved_checkpoint']=dict(source_path=p['expected_document_path'],source_sha256=r['saved_source_sha256'],document=deepcopy(r['source_transition']['document']),configuration=deepcopy(loaded['guide_parameters']['configuration']),snapshot=deepcopy(r['saved']),saved_cl=deepcopy(r['saved_cl']),learned_targets=deepcopy(r['learned_targets']),tool_catalogue=deepcopy(loaded['serial_flat_catalogue']),tool_dimensions=deepcopy(loaded['local_tool_dimensions']),current_counts=dict(operations=21,parameters=12,paths=14,tools=21),GTP_complete=False,nominal_geometry_accepted=False,production_qualified=False)
            except Exception as exc:
                from scripts.sw_cam import _error
                r.update(status='uncertain',readback_verified=False,continuation_ready=False,terminal_issue=_error(exc))
            journal.persist()
        return r

