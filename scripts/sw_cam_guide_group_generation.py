"""Generate four saved guide operations, protecting prior paths and parameters.

A bounded sequential native group; no machine/setup GTP, setters, tool assignment,
operation creation, machining, postprocessing or automatic replay.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import re
from scripts import sw_cam_guide_group_reopen as reopen
from scripts import sw_cam_guide_field_read_batch as fast
from scripts import sw_cam_guide_group_cl as cl
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require

configuration,reader,group,common=reopen.configuration,reopen.reader,reopen.group,reopen.common
SCOPE='SAVED_GUIDE_FOUR_SELECTED_GENERATION_V1'
TARGETS=reopen.TARGETS
PARAMS={'process_id','expected_document_path','expected_source_sha256','reopen_receipt_path','reopen_receipt_sha256',
    'module_sha256','receipt_path','progress_path','before_cl_path','generated_cl_path','saved_cl_path'}
CONTINUATION_PARAMS={'zero_attempt_receipt_path','zero_attempt_receipt_sha256'}


def completed_reopen(r,p):
    require(r.get('scope')==reopen.SCOPE and r.get('status')=='reopen_verified' and r.get('phase')=='finished'
        and r.get('module_pin')==common._pin(reopen.__file__),'Exact completed installed reopen required')
    for key in ('close_verified','reopen_verified','persistence_after_reopen_verified','readback_verified'):
        require(r.get(key)is True,'Reopen proof incomplete: '+key)
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','receipt_write_error'))
        and all(r.get(k)is False for k in ('native_dispatch_pending','save_attempted','GTP_attempted','automatic_retry')),
        'Uncertain or unexpected reopen effects')
    clean_events(r)
    require(r['request']['process_id']==p['process_id']==r['ownership']['process_id']
        and type(p['process_id'])is int and r['source_sha256']==p['expected_source_sha256']
        and common._key(r['source_path'])==common._key(p['expected_document_path']),'Reopened source or owner differs')
    require(set(r['actions'])=={'CloseActiveDocument','OpenDoc6'},'Unexpected reopen actions')
    for action in r['actions'].values():
        require(action.get('status')=='verified' and action.get('attempted')is True and action.get('returned')is True
            and action.get('readback_verified')is True and action.get('native_dispatch_pending')is False,'Reopen action incomplete')
    prior,pin=read_pin(r['request']['configuration_receipt_path'],r['request']['configuration_receipt_sha256'])
    selected=reopen.completed_checkpoint(prior,p)
    require(group.exact(prior['ownership'],r['ownership']) and group.exact(r['reopened'],selected['expected_parameters'])
        and group.exact(r['before_close_binding'],selected['baseline']),'Reopened state differs from saved checkpoint')
    return prior,pin,selected


def verify_binding(before,after,generated):
    a,b=deepcopy(before),deepcopy(after)
    require([v['native_id']for v in a['operations']]==reopen.ORDER
        and [v['native_id']for v in b['operations']]==reopen.ORDER,'Exact thirteen-operation order required')
    require(set(generated)<={v[0]for v in TARGETS},'Generation outside four selected guides')
    for row in b['operations']:
        oid=row['native_id']
        if oid not in generated:continue
        counts=generated[oid]
        require(type(counts)is list and len(counts)==1 and type(counts[0])is int and 0<counts[0]<=100000,
            'One bounded positive stream per selected operation required')
        require(row['toolpath_generated']is True and row['toolpath_record_counts']==counts,'Selected generated result changed')
        old=next(v for v in a['operations']if v['native_id']==oid)
        require(old['toolpath_generated']is False and old['toolpath_record_counts']==[],'Existing path cannot regenerate')
        row['toolpath_generated']=False;row['toolpath_record_counts']=[]
    require(group.exact(a,b),'Another operation, feature, assigned tool or path changed')


def verify_snapshot(baseline,observed,generated):
    verify_binding(baseline['binding'],observed['binding'],generated)
    require(group.exact(baseline['parameters'],observed['parameters']),'Generation changed saved explicit parameters or NC')


def status_contract(value,target,generated=None):
    require(value['operation_native_id']==target['operation_native_id'] and value['feature_native_id']==target['feature_native_id'],
        'Exact selected outcome identity required')
    require(type(value['background_over_before'])is bool and type(value['background_over_after'])is bool,'Background diagnostic must be strict Boolean')
    configuration.finish.status_contract(value,target,generated=generated)
    return value


def audit(typelib,pin):
    from ctypes import POINTER
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    from comtypes import BSTR
    from scripts.sw_cam_comtypes import _interface_class,_INTERFACES
    specs=(('ICWMillOperation','GenerateToolpath',9,(),()),
        ('ICWOperation','GetIsToolpathGeneratedForFeature',83,(POINTER(IDispatch),POINTER(VARIANT_BOOL)),(1,10)),
        ('ICWApp4','_get_IsBackgroundProcessForGTPOver',57,(POINTER(VARIANT_BOOL),),(10,)),
        ('ICWMachine4','SaveCLFile',14,(BSTR,),(1,)))
    result=[]
    for owner,name,ident,args,flags in specs:
        cls=reader.pocket._verify_generated_class(_interface_class(owner,str(typelib)),_INTERFACES[owner],pin)
        members=[v for v in cls._methods_ if v.name==name];require(len(members)==1,'Unique supported native member required')
        configuration.finish.finish.prior.require_abi(members[0],ident,args,flags)
        result.append(dict(interface=owner,member=name,dispid=ident))
    return dict(native_called=False,members=result)


class GenerationContext(reopen.CheckpointContext):
    def files(self):
        require(1<=len(self.loaded['checkpoint_pins'])<=32,'Bounded generation checkpoint closure required')
        super().files()


class NativeBackend(reopen.ParameterBackend):
    target=configuration.NativeBackend.target
    refresh_dirty=group.NativeBackend.refresh_dirty
    save=group.NativeBackend.save
    saved_hash=group.NativeBackend.saved_hash

    def __init__(self,loaded,args,sw,clsid,typelib_path,report,persist):
        super().__init__(loaded,args,sw,clsid,typelib_path,report,persist)
        self.ctx=GenerationContext(loaded,self.args,sw,typelib_path,None,self.events,{'document':loaded['guide_parameters']['document']})

    def batch(self,doc,progress,state,binding):
        # Existing retained-graph read batch, using fixed configuration reads on
        # its boundaries rather than nested ordinary guards on every getter.
        stats=dict(binding_native_calls=0,binding_checks=0,binding_elapsed_seconds=0.)
        check=fast.make_configuration_check(self,doc,stats)
        batch=configuration.NativeBackend.batch(self,doc,progress,state,check)
        self.report.setdefault('configuration_checks',[]).append(stats)
        return batch

    def capture_binding(self,label):
        self.boundary();state=dict(member='',returned=False,read_index=0)
        out=dict(label=label);self.report.setdefault('bindings',[]).append(out);self.persist()
        batch=self.batch(self.doc,lambda:None,state,lambda:None)
        try:
            with batch:out['binding'],_=configuration.definitions.read_current_binding(self.doc,read=batch.read,typed=batch.typed)
            batch.require_complete()
        finally:out['read_batch']=batch.summary();self.persist()
        return deepcopy(out['binding'])

    def outcome(self,target):
        from comtypes.automation import IDispatch
        with self.ctx.guard() as guard:
            raw,feature=self.target(guard,target);op=guard.typed(raw,'ICWOperation')
            before=guard.read(self.ctx.app,'IsBackgroundProcessForGTPOver')
            dispatch=guard.read(feature,'QueryInterface',IDispatch)
            result=dict(operation_native_id=_object_id(self.doc,op,guard.read),feature_native_id=_object_id(self.doc,feature,guard.read),
                background_over_before=before,generated=guard.read(op,'GetIsToolpathGenerated'),
                generated_for_feature=guard.read(op,'GetIsToolpathGeneratedForFeature',dispatch),
                record_counts=[guard.read(guard.typed(v,'ICWToolpath'),'RecordCount')for v in _items(guard.read(op,'IGetEnumToolpaths'),guard.typed,guard.read,1)],
                background_over_after=guard.read(self.ctx.app,'IsBackgroundProcessForGTPOver'))
        self.report.setdefault('outcomes',[]).append(deepcopy(result));self.persist()
        return result

    def generate(self,target,pending):
        status_contract(self.outcome(target),target,False)
        with self.ctx.guard() as guard:
            raw,_=self.target(guard,target);mill=guard.typed(raw,'ICWMillOperation')
            tool,_=read_generic_tool(raw,self.doc,guard.read,guard.typed)
            require(group.exact(tool,target['assigned_tool']),'Saved qualified tool changed before GTP')
            require(type(guard.read(self.ctx.app,'IsBackgroundProcessForGTPOver'))is bool,'Background diagnostic must be Boolean')
            return guard.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)

    def export_cl(self,label,binding):
        diagnostic={};self.report.setdefault('cl_exports',{})[label]=diagnostic;self.persist()
        try:return cl.export_current_cl(self,label,binding,self.args[label+'_cl_path'],diagnostic)
        finally:self.persist()


class Journal(group.GroupJournal):
    def claim_exports(self):
        require(self.created and not self.claimed,'Whole export/generation attempt already claimed')
        group._write_receipt(self.marker,self._marker_state(),create=True)
        self.claimed=True;self.marker_digest=_file_hash(self.marker)
        self.persist()

    def pending(self,name):
        if name.startswith('GenerateToolpath:'):self.report['GTP_attempted']=True
        return super().pending(name)

    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,status=r['status'],phase=r['phase'],source_path=r['source_path'],source_sha256=r['source_sha256'],
            receipt_path=str(self.receipt),reopen_receipt_pin=r['reopen_receipt_pin'],actions=deepcopy(r['actions']),
            native_dispatch_pending=r.get('native_dispatch_pending',False),zero_attempt_predecessor_pin=r.get('zero_attempt_predecessor_pin'),cl_exports=deepcopy(r.get('cl_exports',{})),automatic_replay=False)


def close_checked(backend,r):
    backend.close()
    if getattr(backend,'session',None)is not None:
        backend.events(False);r['cleanup_session_active']=backend.session_active
        require(backend.session_active is False,'CAM event subscriber remained active')


def run_backend(backend,journal,loaded):
    require(not journal.created and not journal.claimed,'Prior generation attempt cannot replay')
    r=journal.report;baseline=loaded['guide_parameters']['expected_parameters'];generated={}
    r.update(status='prepared',phase='preflight',actions={},mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        native_dispatch_pending=False,save_attempted=False,model_saved=False,GTP_attempted=False,readback_verified=False,continuation_ready=False,
        generated_operation_ids=[],automatic_retry=False,SetTool_attempted=False,setter_attempted=False,operation_creation_attempted=False,
        production_qualified=False,physical_cutting_conditions_qualified=False,geometry_acceptance_complete=False,persistence_after_reopen_verified=False)
    try:
        journal.create();backend.start();r['before']=backend.capture_parameters('before');verify_snapshot(baseline,r['before'],generated)
        journal.claim_exports()
        if loaded.get('zero_attempt') is not None:
            r['before_cl']=deepcopy(loaded['zero_attempt']['before_cl'])
            r['before_cl_reused_from']=deepcopy(loaded['zero_attempt_pin']);cl._verified(r['before_cl'])
        else:r['before_cl']=backend.export_cl('before',r['before']['binding'])
        journal.persist()
        for target in loaded['guide_parameters']['targets']:
            oid=target['operation_native_id'];label='GenerateToolpath:'+str(oid);r['phase']=label;journal.persist()
            started=perf_counter();journal.execute(label,lambda pending:backend.generate(target,pending))
            r.setdefault('timing',{})[label]=dict(native_dispatch_seconds=perf_counter()-started);r['GTP_attempted']=True
            backend.refresh_dirty();outcome=backend.outcome(target);status_contract(outcome,target,True)
            generated[oid]=deepcopy(outcome['record_counts']);actual=backend.capture_binding('generated_'+str(oid))
            verify_binding(baseline['binding'],actual,generated)
            journal.verified(label,outcome);r['generated_operation_ids']=list(generated);journal.persist()
        r['generated']=backend.capture_parameters('generated');verify_snapshot(baseline,r['generated'],generated)
        r['generated_cl']=backend.export_cl('generated',r['generated']['binding'])
        r['protected_cl_comparison']=cl.verify_protected(r['before_cl'],r['generated_cl'])
        r['protected_cl_verified']=True;journal.persist()
        r['generation_readback_verified']=True;r['save_stage']={};journal.entry('SaveActiveDocument');r['save_attempted']=True;journal.persist()
        expected=deepcopy(r['generated'])
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(expected)
            value=backend.capture_parameters('saved');verify_snapshot(baseline,value,generated);r['saved']=value;return value
        def verify(value):require(group.exact(value,expected),'Save changed generated CAM configuration')
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
            prior_source_sha256=r['source_sha256'],prior_reopen_receipt_pin=deepcopy(loaded['reopen_pin']),persistence_after_reopen_verified=False)
        r.update(status='saved_generated_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False,continuation_ready=False)
    finally:
        try:close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r


def zero_attempt_contract(prior,p,loaded):
    require(prior.get('scope')==SCOPE and prior.get('status')=='error' and prior.get('phase')=='finished'
        and prior.get('failed_phase')=='GenerateToolpath:322','Exact stopped first-generation attempt required')
    require(not any(k in prior for k in ('cleanup_issue','receipt_write_error')),'Incomplete cleanup cannot authorize continuation')
    for key in ('mutation_attempted','GTP_attempted','save_attempted','model_saved','native_call_attempted','native_call_returned','native_dispatch_pending'):
        require(prior.get(key)is False,'Previous attempt is not proven write-free: '+key)
    require(prior.get('generated_operation_ids')==[] and list(prior.get('actions',{}))==['GenerateToolpath:322'],'Unexpected previous action set')
    action=prior['actions']['GenerateToolpath:322']
    require(action==dict(status='prepared',attempted=False,returned=False,readback_verified=False),'Previous GTP was attempted or returned')
    issue=prior.get('issue',{})
    require(issue.get('type')=='ValueError' and any(v.get('function')=='status_contract'for v in issue.get('locations',[])),
        'Exact outcome-contract failure required')
    outcomes=prior.get('outcomes',[]);require(len(outcomes)==1,'Exactly one pre-dispatch outcome required')
    outcome=outcomes[0];status_contract(outcome,loaded['guide_parameters']['targets'][0],False)
    require(outcome['background_over_before']is False and outcome['background_over_after']is False,'Exact historical false diagnostic required')
    clean_events(prior)
    require(group.exact(prior['ownership'],loaded['ownership']) and prior['request']['process_id']==p['process_id']
        and prior['source_sha256']==p['expected_source_sha256']
        and common._key(prior['source_path'])==common._key(p['expected_document_path'])
        and group.exact(prior['reopen_receipt_pin'],loaded['reopen_pin']),'Previous source/owner/reopen lineage differs')
    require(group.exact(prior['before'],loaded['guide_parameters']['expected_parameters']),'Previous baseline differs')
    proof=prior['before_cl'];cl._verified(proof)
    require(proof['source_sha256']==p['expected_source_sha256']
        and group.exact(proof['document'],loaded['guide_parameters']['document'])
        and proof['expected_generated_operations']==cl.contract(prior['before']['binding'])
        and common._key(p['before_cl_path'])==common._key(proof['output']['path']),'Completed baseline CL differs')


def load_zero_attempt(p,loaded):
    prior,pin=read_pin(p['zero_attempt_receipt_path'],p['zero_attempt_receipt_sha256']);zero_attempt_contract(prior,p,loaded)
    original,original_pin=read_pin(prior['request']['receipt_path'],pin['sha256'])
    require(group.exact(original,prior),'Archived failed receipt differs from original')
    oldmarker=common.local_evidence_root()/('guide_generation_'+group._digest(dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    marker,markerpin=read_pin(str(oldmarker),_file_hash(oldmarker))
    require(marker.get('scope')==SCOPE and marker.get('status')==prior['status'] and marker.get('phase')==prior['phase']
        and marker.get('source_sha256')==prior['source_sha256'] and marker.get('native_dispatch_pending')is False
        and common._key(marker['receipt_path'])==common._key(prior['request']['receipt_path'])
        and group.exact(marker.get('actions'),prior['actions']) and group.exact(marker.get('cl_exports'),prior['cl_exports']),
        'Original once marker differs; do not remove or replace it')
    return prior,pin,common._merge([pin,original_pin,markerpin,prior['before_cl']['output']])


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='generate_four_saved_guides','Exact selected group action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)in(PARAMS,PARAMS|CONTINUATION_PARAMS),'Exact bounded generation request required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned process ID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
    require(p['module_sha256']==_file_hash(__file__),'Generation module changed')
    reopened,reopen_pin=read_pin(p['reopen_receipt_path'],p['reopen_receipt_sha256'])
    prior,priorpin,selected=completed_reopen(reopened,p)
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current saved source changed')
    pins=deepcopy(prior['live_pins']);require(1<=len(pins)<=64,'Bounded existing parameter reader closure required')
    generated=[v for v in pins if Path(v['path']).name.startswith('_FE488661_0BD8_11D6_2012_2018CE99E55F_')and Path(v['path']).suffix=='.py']
    require(len(generated)==1,'Pinned installed CAM metadata required')
    loaded=dict(pins=pins,ownership=deepcopy(prior['ownership']),guide_parameters=selected,generated_pin=generated[0],
        configuration_pins=deepcopy(prior['configuration_pins']),bootstrap_export_pins=[common._pin(reopen.installation.__file__)],
        reopen_pin=reopen_pin,configuration_tool=deepcopy(selected['targets'][0]['assigned_tool']),
        checkpoint_pins=common._merge(prior['configuration_pins'],[priorpin,reopen_pin]+selected['history_pins']+
            [common._pin(v)for v in (__file__,reopen.__file__,fast.__file__,cl.__file__)]+cl.dependency_pins()))
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,prior['request']['addin_clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb');require(common._pin(typelib)in pins,'Installed TLB changed')
    p['expected_configuration']=selected['configuration']['sw_configuration_name']
    if CONTINUATION_PARAMS<=set(p):
        prior_zero,zero_pin,zero_pins=load_zero_attempt(p,loaded)
        loaded.update(zero_attempt=prior_zero,zero_attempt_pin=zero_pin)
        loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],zero_pins)
        common._check(loaded['checkpoint_pins'])
    abi=audit(typelib,loaded['generated_pin'])
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path'])
    claim=dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256'])
    if loaded.get('zero_attempt_pin'):claim['zero_attempt_predecessor_sha256']=loaded['zero_attempt_pin']['sha256']
    marker=common.local_evidence_root()/('guide_generation_'+group._digest(claim)+'.json')
    outputs=[receipt,progress,marker]+[Path(p[x+'_cl_path'])for x in (('generated','saved')if loaded.get('zero_attempt_pin')else('before','generated','saved'))]
    protected={common._key(v['path'])for v in pins+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in outputs})==len(outputs),'Outputs must be distinct')
    for path in outputs:require(not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Fresh nonaliased output required')
    for path in (receipt,progress,marker):require(path.parent.is_dir(),'Existing diagnostic output parent required')
    if loaded.get('zero_attempt_pin'):
        dirs=[cl._fresh_path(p[k+'_cl_path']).parent for k in ('generated','saved')]
        require(len({common._key(v)for v in dirs})==2,'Distinct fresh continuation CL directories required')
    else:cl.validate_outputs(p)
    return p,loaded,registration,typelib,abi,receipt,marker


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,selected_ids=[v[0]for v in TARGETS],
        source_sha256=p['expected_source_sha256'],live_pin_count=len(loaded['pins']),checkpoint_pin_count=len(loaded['checkpoint_pins']),interface_audit=abi)
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),ownership=loaded['ownership'],source_path=p['expected_document_path'],
            source_sha256=p['expected_source_sha256'],reopen_receipt_pin=loaded['reopen_pin'],recipe=deepcopy(loaded['guide_parameters']['targets']),
            live_pins=loaded['pins'],checkpoint_pins=loaded['checkpoint_pins'],interface_audit=abi,
            zero_attempt_predecessor_pin=loaded.get('zero_attempt_pin'))
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_backend(backend,journal,loaded)
