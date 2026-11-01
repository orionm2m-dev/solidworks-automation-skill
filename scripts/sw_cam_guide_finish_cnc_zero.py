"""Qualify raw-zero CNC output for two existing guide finish operations.

Preserves eight complete paths; intentionally regenerates only the two finishes
following their explicit NC change. No tool assignment or production release.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import re
from scripts import sw_cam_guide_generated_reopen as saved_loader
from scripts import sw_cam_guide_finish_compensation as candidate
from scripts import sw_cam_guide_finish_cl as finish_cl
from scripts.sw_cam import _member,_error
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash

generation=saved_loader.generation
configuration,group,common,cl=generation.configuration,generation.group,generation.common,generation.cl
SCOPE='SAVED_GUIDE_TWO_FINISH_CNC_ZERO_CANDIDATE_V1'
IDS=(324,328)
PARAMS={'process_id','expected_document_path','expected_source_sha256','generated_receipt_path','generated_receipt_sha256',
    'warning_receipts','module_sha256','receipt_path','progress_path','generated_cl_path','saved_cl_path','acknowledgement'}
CONTINUATION_PARAMS={'zero_attempt_receipt_path','zero_attempt_receipt_sha256'}
MAX_CHECKPOINT_PINS=36


def path_state(binding,oid):
    rows=[v for v in binding['operations']if v['native_id']==oid];require(len(rows)==1,'Unique selected binding required')
    row=rows[0]
    value=dict(generated=row['toolpath_generated'],record_counts=deepcopy(row['toolpath_record_counts']))
    require(type(value['generated'])is bool and type(value['record_counts'])is list and len(value['record_counts'])<=1
        and all(type(x)is int and 0<x<=100000 for x in value['record_counts']),'Strict selected path state required')
    return value


def nc_row(snapshot,oid):
    rows=[v for v in snapshot['parameters']if v['operation_native_id']==oid];require(len(rows)==1,'Unique full parameter row required')
    return rows[0]


def expected_parameters(baseline,changed):
    value=deepcopy(baseline['parameters']);require(set(changed)<=set(IDS),'Only two finish NC changes permitted')
    for row in value:
        if row['operation_native_id']not in changed:continue
        require(row['nc']['feeds_compensation']['GetCNCComp']==1 and row['nc']['feeds_compensation']['GetTlpComp']==1
            and row['protected_finish']['compensation']==[1,1],'Exact inherited compensation baseline required')
        row['nc']['feeds_compensation']['GetCNCComp']=0;row['protected_finish']['compensation'][1]=0
    return value


def verify_binding(baseline,actual,changed,regenerated):
    require(set(changed)<=set(IDS) and set(regenerated)<=set(changed),'Unexpected correction or regeneration target')
    old,new=deepcopy(baseline),deepcopy(actual)
    require([v['native_id']for v in old['operations']]==generation.reopen.ORDER
        and [v['native_id']for v in new['operations']]==generation.reopen.ORDER,'Exact thirteen-operation order required')
    for row in new['operations']:
        oid=row['native_id']
        if oid not in changed:continue
        before=path_state(old,oid);after=path_state(new,oid)
        if oid in regenerated:
            require(after==dict(generated=True,record_counts=regenerated[oid]),'Selected regenerated path changed')
        else:require(after in (before,dict(generated=False,record_counts=[])),'NC change unexpectedly replaced selected path')
        row['toolpath_generated']=before['generated'];row['toolpath_record_counts']=before['record_counts']
    require(group.exact(old,new),'Another route, feature, tool or protected path changed')


def verify_snapshot(baseline,actual,changed,regenerated):
    verify_binding(baseline['binding'],actual['binding'],changed,regenerated)
    require(group.exact(actual['parameters'],expected_parameters(baseline,changed)),'NC correction changed other full parameters')


class CorrectionContext(generation.GenerationContext):
    def files(self):
        require(1<=len(self.loaded['checkpoint_pins'])<=MAX_CHECKPOINT_PINS,'Bounded correction checkpoint closure required')
        generation.reopen.CheckpointContext.files(self)
        old=self.loaded.get('zero_attempt_original_marker')
        if old:require(not Path(old).exists() and not Path(old).is_symlink(),'Original zero-dispatch attempt acquired a marker')


class NativeBackend(generation.NativeBackend):
    def __init__(self,loaded,args,sw,clsid,typelib_path,report,persist):
        super().__init__(loaded,args,sw,clsid,typelib_path,report,persist)
        self.ctx=CorrectionContext(loaded,self.args,sw,typelib_path,None,self.events,{'document':loaded['guide_parameters']['document']})

    def set_candidate(self,target,expected,state,pending):
        return candidate.set_raw_zero_candidate(self,target,expected,pending,path_state=state)

    def regenerate(self,target,expected,state,pending):
        require(target['operation_native_id']in IDS,'Only intentionally changed finishes may regenerate')
        outcome=self.outcome(target);generation.status_contract(outcome,target)
        require(dict(generated=outcome['generated'],record_counts=outcome['record_counts'])==state,'Changed finish path state differs')
        with self.ctx.guard()as guard:
            owner,owner2=candidate._owner(self,guard,target,state)
            observed=candidate._values(guard,owner,owner2)
            require(group.exact(observed,expected) and observed['GetCNCComp']==0 and observed['GetTlpComp']==1,
                'Exact raw-zero candidate and retained toolpath compensation required before regeneration')
            raw,_=self.target(guard,target);mill=guard.typed(raw,'ICWMillOperation')
            return guard.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)


class Journal(group.GroupJournal):
    def pending(self,name):
        if name.startswith('SetCNCComp:'):self.report['setter_attempted']=True
        if name.startswith('GenerateToolpath:'):self.report['GTP_attempted']=True
        return super().pending(name)
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,status=r['status'],phase=r['phase'],source_path=r['source_path'],source_sha256=r['source_sha256'],
            receipt_path=str(self.receipt),generated_checkpoint_pin=r['generated_checkpoint_pin'],zero_attempt_predecessor_pin=r.get('zero_attempt_predecessor_pin'),actions=deepcopy(r['actions']),
            native_dispatch_pending=r.get('native_dispatch_pending',False),automatic_replay=False)


def run_backend(backend,journal,loaded):
    require(not journal.created and not journal.claimed,'Existing correction attempt cannot replay')
    r=journal.report;baseline=loaded['guide_parameters']['expected_parameters'];changed=[];regenerated={}
    r.update(status='prepared',phase='preflight',actions={},mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        native_dispatch_pending=False,save_attempted=False,model_saved=False,GTP_attempted=False,setter_attempted=False,SetTool_attempted=False,
        operation_creation_attempted=False,automatic_retry=False,readback_verified=False,continuation_ready=False,changed_operation_ids=[],
        regenerated_operation_ids=[],geometry_acceptance_complete=False,production_qualified=False,physical_cutting_conditions_qualified=False,
        persistence_after_reopen_verified=False,numeric_enum_meaning_qualified=False,empirical_finish_cutcom_absence_verified=False)
    try:
        journal.create();backend.start();r['before']=backend.capture_parameters('before')
        verify_snapshot(baseline,r['before'],changed,regenerated)
        r['before_cl']=deepcopy(loaded['generated']['saved_cl']);cl._verified(r['before_cl']);journal.persist()
        current=r['before']
        for target in [v for v in loaded['guide_parameters']['targets']if v['operation_native_id']in IDS]:
            oid=target['operation_native_id'];label='SetCNCComp:'+str(oid);r['phase']=label;journal.persist()
            before_nc=deepcopy(nc_row(current,oid)['nc']['feeds_compensation']);state=path_state(current['binding'],oid)
            journal.execute(label,lambda pending:backend.set_candidate(target,before_nc,state,pending))
            backend.refresh_dirty();changed.append(oid);current=backend.capture_parameters('after_cnc_'+str(oid))
            verify_snapshot(baseline,current,changed,regenerated)
            after_nc=deepcopy(nc_row(current,oid)['nc']['feeds_compensation'])
            proof=candidate.verify_candidate_readback(before_nc,after_nc)
            r.setdefault('candidate_readbacks',[]).append(dict(operation_native_id=oid,before=before_nc,after=after_nc,proof=proof,
                parameter_snapshot_sha256=group._digest(current)))
            journal.verified(label,r['candidate_readbacks'][-1]);r['changed_operation_ids']=list(changed)
            state=path_state(current['binding'],oid);label='GenerateToolpath:'+str(oid);r['phase']=label;journal.persist()
            started=perf_counter();journal.execute(label,lambda pending:backend.regenerate(target,after_nc,state,pending))
            r.setdefault('timing',{})[label]=dict(native_dispatch_seconds=perf_counter()-started)
            backend.refresh_dirty();outcome=backend.outcome(target);generation.status_contract(outcome,target,True)
            regenerated[oid]=deepcopy(outcome['record_counts'])
            binding=backend.capture_binding('regenerated_'+str(oid));verify_binding(baseline['binding'],binding,changed,regenerated)
            current['binding']=deepcopy(binding);journal.verified(label,outcome)
            r['regenerated_operation_ids']=list(regenerated);journal.persist()
        require(changed==list(IDS) and list(regenerated)==list(IDS),'Exactly two finish corrections and generations required')
        r['generated']=backend.capture_parameters('generated');verify_snapshot(baseline,r['generated'],changed,regenerated)
        r['generated_cl']=backend.export_cl('generated',r['generated']['binding'])
        r['protected_cl_comparison']=finish_cl.verify_protected_eight(r['before_cl'],r['generated_cl'])
        r['finish_cutcom_review']=finish_cl.verify_finish_without_cutcom(r['generated_cl'])
        r.update(protected_cl_verified=True,empirical_finish_cutcom_absence_verified=True,generation_readback_verified=True)
        r['save_stage']={};journal.entry('SaveActiveDocument');r['save_attempted']=True;journal.persist();expected=deepcopy(r['generated'])
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(expected)
            value=backend.capture_parameters('saved');verify_snapshot(baseline,value,changed,regenerated);r['saved']=value;return value
        def verify(value):require(group.exact(value,expected),'Save changed corrected CAM snapshot')
        def save():
            value=backend.save();entry=r['actions']['SaveActiveDocument']
            require(entry['attempted']is True and entry.get('native_dispatch_pending')is True,'Save bypassed pending')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value))
            r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved bytes did not change')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        configuration.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export_cl('saved',r['saved']['binding'])
        r['saved_cl_comparison']=cl.verify_all(r['generated_cl'],r['saved_cl']);r['saved_cl_verified']=True
        backend.finish()
        r['saved_checkpoint_context']=dict(process_id=r['request']['process_id'],ownership=deepcopy(r['ownership']),
            document=deepcopy(r['source_transition']['document']),source_sha256=r['saved_source_sha256'],
            configuration=deepcopy(loaded['guide_parameters']['configuration']),snapshot_key='saved',snapshot_sha256=group._digest(r['saved']),
            prior_source_sha256=r['source_sha256'],prior_generated_checkpoint_pin=deepcopy(loaded['generated_checkpoint_pin']),
            persistence_after_reopen_verified=False)
        r.update(status='saved_finish_cnc_candidate_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',
        issue=_error(exc),readback_verified=False,continuation_ready=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r


def load_warnings(p,ownership):
    require(type(p['warning_receipts'])is list and len(p['warning_receipts'])==2,'Two exact historical warning receipts required')
    pins=[]
    for item in p['warning_receipts']:
        require(type(item)is dict and set(item)=={'path','sha256'},'Exact warning pin fields required')
        value,pin=read_pin(item['path'],item['sha256'])
        require(value.get('scope')=='EXACT_OWNED_CAM_INFORMATION_OK_V1' and value.get('status')=='dismissed'
            and value.get('process_id')==p['process_id'] and value.get('expected_creation_time')==ownership['create_time']
            and common._key(value.get('expected_executable',''))==common._key(ownership['executable'])
            and value.get('button_invocation_count')==1 and value.get('dismissal_confirmed')is True
            and value.get('action_pending')is False and value.get('save_called')is False and value.get('cancel_called')is False,
            'Warning acknowledgement owner or outcome differs')
        pins.append(pin)
    require(len({common._key(v['path'])for v in pins})==2,'Distinct warning receipts required')
    return pins


def zero_attempt_contract(prior,p,loaded):
    require(prior.get('scope')==SCOPE and prior.get('status')=='error' and prior.get('phase')=='finished'
        and prior.get('failed_phase')=='SetCNCComp:324','Exact stopped first-setter attempt required')
    require(not any(k in prior for k in ('cleanup_issue','receipt_write_error'))
        and prior.get('cleanup_session_active')is False,'Confirmed disconnected cleanup required')
    for key in ('mutation_attempted','native_call_attempted','native_call_returned','native_dispatch_pending','setter_attempted',
        'GTP_attempted','save_attempted','model_saved','SetTool_attempted','operation_creation_attempted','readback_verified','continuation_ready'):
        require(prior.get(key)is False,'Previous attempt not proven write-free: '+key)
    require(prior.get('changed_operation_ids')==[] and prior.get('regenerated_operation_ids')==[]
        and list(prior.get('actions',{}))==['SetCNCComp:324'],'Unexpected previous changes or action set')
    require(prior['actions']['SetCNCComp:324']==dict(status='prepared',attempted=False,returned=False,readback_verified=False),
        'Previous setter reached dispatch or returned')
    issue=prior.get('issue',{})
    require(issue.get('type')=='ValueError' and any(v.get('file')=='sw_cam_comtypes.py' and v.get('function')=='_interface_class'
        for v in issue.get('locations',[])),'Exact unsupported-interface pre-dispatch failure required')
    clean_events(prior)
    require(group.exact(prior['ownership'],loaded['ownership']) and prior['request']['process_id']==p['process_id']
        and prior['source_sha256']==p['expected_source_sha256']
        and common._key(prior['source_path'])==common._key(p['expected_document_path'])
        and group.exact(prior['generated_checkpoint_pin'],loaded['generated_checkpoint_pin']), 'Previous source, owner or generated checkpoint differs')
    require(group.exact(prior['before'],loaded['guide_parameters']['expected_parameters'])
        and group.exact(prior['before_cl'],loaded['generated']['saved_cl']), 'Previous full baseline or saved CL differs')
    require(prior['module_pin']['sha256']==prior['request']['module_sha256']!=p['module_sha256'],
        'A distinct corrected implementation is required')


def load_zero_attempt(p,loaded):
    prior,pin=read_pin(p['zero_attempt_receipt_path'],p['zero_attempt_receipt_sha256']);zero_attempt_contract(prior,p,loaded)
    original,original_pin=read_pin(prior['request']['receipt_path'],pin['sha256'])
    require(group.exact(original,prior),'Archived zero-attempt receipt differs from original')
    marker=common.local_evidence_root()/('finish_cnc_zero_'+group._digest(dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    require(not marker.exists() and not marker.is_symlink(),'Original attempt has a pending marker; no continuation allowed')
    return prior,pin,common._merge([pin,original_pin]),str(marker)


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'} and request['action']=='qualify_guide_finish_cnc_zero','Exact candidate action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)in(PARAMS,PARAMS|CONTINUATION_PARAMS),'Exact candidate parameter keys required')
    require(p['acknowledgement']=='qualify_raw_zero_preserve_offset_regenerate_only_selected_finish','Explicit controlled regeneration qualification required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
    require(p['module_sha256']==_file_hash(__file__),'Candidate module changed')
    previous,pin=read_pin(p['generated_receipt_path'],p['generated_receipt_sha256']);selected,addin=saved_loader.completed_generated(previous,p)
    warnings=load_warnings(p,previous['ownership'])
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Saved generated source changed')
    expected_parameters(selected['expected_parameters'],IDS)
    require([v['operation_native_id']for v in selected['targets']if v['operation_native_id']in IDS]==list(IDS),'Exact ordered finish pair required')
    pins=deepcopy(previous['live_pins']);require(1<=len(pins)<=64,'Bounded inherited runtime closure required')
    metadata=[v for v in pins if Path(v['path']).name.startswith('_FE488661_0BD8_11D6_2012_2018CE99E55F_')and Path(v['path']).suffix=='.py']
    require(len(metadata)==1,'Exact generated metadata required')
    checkpoint=common._merge(previous['checkpoint_pins'],[previous[k]['output']for k in ('before_cl','generated_cl','saved_cl')],warnings,
        [pin]+[common._pin(v)for v in (__file__,saved_loader.__file__,candidate.__file__,finish_cl.__file__)])
    require(len(checkpoint)<=MAX_CHECKPOINT_PINS,'Bounded candidate checkpoint closure required')
    loaded=dict(pins=pins,checkpoint_pins=checkpoint,configuration_pins=deepcopy(previous['checkpoint_pins']),
        bootstrap_export_pins=[common._pin(generation.reopen.installation.__file__)],generated_pin=metadata[0],
        ownership=deepcopy(previous['ownership']),guide_parameters=selected,generated=previous,generated_checkpoint_pin=pin,
        warning_receipt_pins=warnings)
    if CONTINUATION_PARAMS<=set(p):
        prior,priorpin,extra,oldmarker=load_zero_attempt(p,loaded)
        checkpoint=common._merge(checkpoint,extra);require(len(checkpoint)<=MAX_CHECKPOINT_PINS,'Bounded correction continuation closure required')
        loaded.update(checkpoint_pins=checkpoint,zero_attempt_predecessor_pin=priorpin,zero_attempt_original_marker=oldmarker)
    common._check(pins);common._check(checkpoint)
    registration=common.discover_export_registration(loaded,addin);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in pins,'Installed metadata differs');abi=dict(generation=generation.audit(typelib,metadata[0]),candidate=candidate.audit(typelib,metadata[0]))
    p['expected_configuration']=selected['configuration']['sw_configuration_name']
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path'])
    marker=common.local_evidence_root()/('finish_cnc_zero_'+group._digest(dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    if 'zero_attempt_predecessor_pin'in loaded:
        marker=marker.with_name(marker.stem+'_after_'+loaded['zero_attempt_predecessor_pin']['sha256']+'.json')
    exports=[cl._fresh_path(p[k])for k in ('generated_cl_path','saved_cl_path')]
    require(exports[0].parent!=exports[1].parent,'Separate fresh export directories required')
    outputs=[receipt,progress,marker]+exports;protected={common._key(v['path'])for v in pins+checkpoint}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in outputs})==len(outputs),'Separate candidate outputs required')
    for path in outputs:require(not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Fresh unaliased outputs required')
    for path in (receipt,progress,marker):require(path.parent.is_dir(),'Existing diagnostic parent required')
    return p,loaded,registration,typelib,abi,receipt,marker


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),
        checkpoint_pin_count=len(loaded['checkpoint_pins']),selected_finish_ids=list(IDS),protected_generated_paths=8)
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=generation.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
            ownership=loaded['ownership'],generated_checkpoint_pin=loaded['generated_checkpoint_pin'],warning_receipt_pins=loaded['warning_receipt_pins'],
            zero_attempt_predecessor_pin=loaded.get('zero_attempt_predecessor_pin'),
            live_pins=deepcopy(loaded['pins']),checkpoint_pins=deepcopy(loaded['checkpoint_pins']),interface_audit=abi,
            recipe=deepcopy(loaded['guide_parameters']['targets']),qualification_limit='Raw zero meaning requires actual CL evidence; geometry and manufacturing remain unqualified',
            before_cl_reuse_basis='Immediate owned saved continuation, no intervening CAM/user changes; counts alone are not a CL identity proof')
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_backend(backend,journal,loaded)