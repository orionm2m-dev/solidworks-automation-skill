"""Reconcile an interrupted verified prefix, then configure only untouched fields.

The existing configuration module stays immutable. No SetTool, InsertOperation,
GTP, Close, Exit or replay of an attempted scalar operation is available here.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import re
from scripts import sw_cam_guide_group_configuration as config
from scripts import sw_cam_guide_field_read_batch as fields
from scripts.sw_cam import _error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_rough_firstcut import require

reader,group,common=config.reader,config.group,config.common
PREPARE_SCOPE='GUIDE_PARTIAL_CONFIGURATION_RECONCILIATION_V1'
SCOPE='GUIDE_CONFIGURATION_REMAINDER_SAVE_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','expected_configuration','addin_clsid',
    'module_sha256','partial_receipt_path','partial_receipt_sha256','writer_exit_path','writer_exit_sha256',
    'prepared_receipt_path','prepared_receipt_sha256','receipt_path','progress_path'}


def specs(row):return config.ROUGH_FIELDS if row['operation_type']==0 else config.FINISH_FIELDS

def action_order(recipe):
    return [str(row['operation_native_id'])+':SetTool' for row in recipe['rows']]+[
        str(row['operation_native_id'])+':'+spec[0] for row in recipe['rows'] for spec in specs(row)]


def validate_partial(partial,exit_proof,pin):
    require(partial.get('scope')==config.SCOPE and partial.get('module_pin')==common._pin(config.__file__),
        'Exact executed configuration writer required')
    require(partial.get('mutation_attempted') is True and partial.get('native_dispatch_pending') is False,
        'Interrupted verified prefix with no pending dispatch required')
    require(not any(partial.get(k) for k in ('save_attempted','model_saved','GTP_attempted','continuation_ready')),
        'Only unsaved, ungenerated partial configurations can resume')
    require(not any(k in partial for k in ('issue','failed_phase','cleanup_issue','receipt_write_error')),
        'This continuation only accepts a cleanly recorded interrupted prefix')
    actions=partial['actions'];order=action_order(partial['recipe'])
    require(4<=len(actions)<len(order) and list(actions)==order[:len(actions)],'Exact ordered completed prefix required')
    for name,action in actions.items():
        require(action.get('status')=='verified' and action.get('readback_verified') is True,
            'Unknown or unverified native action cannot replay: '+name)
        require(not action.get('native_dispatch_pending'),'Pending native call cannot replay')
        if action.get('attempted') is True:
            ret=action.get('native_return',{})
            require(action.get('returned') is True and ret.get('python_type')=='int'
                and ret.get('value_recorded') is True and type(ret.get('value')) is int and ret['value']==0,
                'Strict confirmed native return required')
        else:
            require(action.get('attempted') is False and action.get('returned') is False
                and action.get('observed',{}).get('already_satisfied') is True,
                'Only explicit already-satisfied skips are accepted')
    changed=set();last=None
    for row in partial['recipe']['rows']:
        oid=row['operation_native_id'];action=actions[str(oid)+':SetTool'];reference=action['observed']
        require(reference['operation_native_id']==oid and reference['capture_label']=='after_tool_'+str(oid),
            'Tool capture reference changed')
        last=config.resolve_capture_reference(partial,reference);changed.add(oid)
        config.verify_binding(partial['before']['binding'],last['binding'],
            partial['after_tools']['parameters'][0]['tool']['generic'],changed)
    require(group.exact(last,partial['after_tools']),'Post-tool authority differs from last confirmed capture')
    require(type(exit_proof) is dict and exit_proof.get('client_present') is False
        and exit_proof.get('no_new_candidate_server_at_or_after_client_start') is True
        and exit_proof.get('client_result_status')=='timeout' and exit_proof.get('client_exit_code')==1,
        'Explicit prior writer exit observation required')
    require(exit_proof.get('native_receipt_sha256')==pin['sha256']
        and exit_proof.get('native_phase')==partial['phase'] and exit_proof.get('native_dispatch_pending') is False
        and exit_proof.get('save_attempted') is False and exit_proof.get('source_sha256')==partial['source_sha256']
        and common._key(exit_proof.get('source',''))==common._key(partial['source_path']),
        'Writer exit/source/partial lineage differs')
    message=partial.get('messages',{})
    require(not any(message.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count',
        'subscription_error','disconnect_errors')),'Prior CAM error requires separate diagnosis')
    return order[len(actions):]


def reconcile(partial,actual,wanted):
    recipe=partial['recipe'];ids={r['operation_native_id']for r in recipe['rows']}
    config.verify_binding(partial['before']['binding'],actual['binding'],wanted,ids)
    result=[]
    require(len(actual['parameters'])==4,'Four complete current parameter groups required')
    for old,current,row in zip(partial['after_tools']['parameters'],actual['parameters'],recipe['rows']):
        oid=row['operation_native_id']
        require(current.get('read_complete') is True and current['operation_native_id']==oid
            and current['feature_native_id']==row['feature_native_id'],'Current parameter identity differs')
        require(group.exact(config.protected_parameters(old),config.protected_parameters(current)),
            'NC, levels, tooling or another unselected parameter changed')
        for spec in specs(row):
            name=str(oid)+':'+spec[0];target=row['fields'][spec[0]];now=config.field_value(current,spec)
            if name in partial['actions']:
                require(group.exact(now,target),'Confirmed field no longer equals approved target: '+name)
            else:
                baseline=config.field_value(old,spec)
                require(group.exact(now,baseline) or group.exact(now,target),
                    'Untouched field differs from recorded default and approved target: '+name)
                result.append(dict(action=name,target=deepcopy(row),field=spec[0],observed=deepcopy(now),
                    wanted=deepcopy(target),write_required=not group.exact(now,target)))
    return result


class ResumeContext(group.GroupContext):
    def files(self):
        super().files()
        pins=self.loaded['configuration_pins']+self.loaded['resume_pins']
        require(4<=len(pins)<=9,'Bounded current resume authority required')
        common._check(pins)


class NativeBackend(config.NativeBackend):
    def __init__(self,loaded,args,sw,clsid,typelib_path,report,persist):
        super().__init__(loaded,args,sw,clsid,typelib_path,report,persist)
        self.ctx=ResumeContext(loaded,dict(args,**loaded['ids']),sw,typelib_path,None,self.events,loaded['state'])
        self.ctx.expected_document=deepcopy(loaded['partial']['current_document'])

    def acquire_document(self):
        self.boundary()
        with self.ctx.guard() as g:
            self.doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3')
            self.save_app=g.typed(self.ctx.app,'ICWApp')

    def read_fields(self,target,names=None):
        diagnostic={};self.report.setdefault('field_readbacks',[]).append(diagnostic);self.persist()
        started=perf_counter()
        try:
            return fields.read_field_values(self,target,field_names=names,diagnostic=diagnostic)['field_values']
        finally:
            diagnostic['total_elapsed_seconds']=perf_counter()-started;self.persist()

    def check_prepared(self,prepared):
        # No second full parameter read: current ordered route and every recipe
        # field are compared to the immediately preceding reconciliation.
        self.acquire_document();stats=dict(binding_native_calls=0,binding_checks=0,binding_elapsed_seconds=0.)
        state=dict(member='',returned=False,read_index=0)
        check=fields.make_configuration_check(self,self.doc,stats)
        batch=reader.ParameterReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
            process_id=self.args['process_id'],expected_document=self.ctx.identity(),
            source_sha256=self.ctx.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events,
            retained_objects=(self.doc,),verify_retained_binding=check,max_native_calls=reader.MAX_CALLS,
            progress=lambda:None,progress_state=state)
        try:
            with batch:
                before,_=config.definitions.read_current_binding(self.doc,read=batch.read,typed=batch.typed)
                require(group.exact(before,prepared['binding']),'Prepared route changed')
                after,_=config.definitions.read_current_binding(self.doc,read=batch.read,typed=batch.typed)
                require(group.exact(before,after),'Current route changed during binding read')
            batch.require_complete()
        finally:self.report['prepared_binding_read']=dict(batch=batch.summary(),configuration=stats);self.persist()
        for row,reference in zip(self.loaded['partial']['recipe']['rows'],prepared['parameters']):
            current=self.read_fields(row)
            require(group.exact(current,{s[0]:config.field_value(reference,s)for s in specs(row)}),
                'Prepared scalar configuration changed')


def close_checked(backend,report):
    backend.close()
    if getattr(backend,'session',None) is not None:
        backend.events(False);report['cleanup_session_active']=backend.session_active
        require(backend.session_active is False,'Subscriber remained active')


def run_prepare(backend,report,persist,loaded):
    report.update(scope=PREPARE_SCOPE,status='error',phase='preflight',read_only=True,mutation_attempted=False,
        save_attempted=False,GTP_attempted=False,readback_verified=False,continuation_ready=False)
    try:
        backend.start();report['actual']=backend.capture_parameters('reconcile')
        report['remaining']=reconcile(loaded['partial'],report['actual'],loaded['configuration_tool'])
        backend.finish();report['document']=deepcopy(backend.ctx.expected_document)
        report.update(status='observed',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc))
    finally:
        try:close_checked(backend,report)
        except Exception as exc:report.update(status='error',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        persist()
    return report


class ResumeJournal(config.ConfigurationJournal):
    def _marker_state(self):
        value=super()._marker_state();value['scope']=SCOPE
        value['source_partial_receipt_pin']=self.report['source_partial_receipt_pin']
        return value


def run_resume(backend,journal,loaded):
    require(not journal.created and not journal.claimed,'No reentry/replay of a resume journal')
    r=journal.report;partial=loaded['partial'];prepared=loaded['prepared'];recipe=partial['recipe'];wanted=loaded['configuration_tool']
    r.update(scope=SCOPE,status='error',phase='preflight',actions={},mutation_attempted=False,native_call_attempted=False,
        native_call_returned=False,native_dispatch_pending=False,readback_verified=False,model_saved=False,
        save_attempted=False,GTP_attempted=False,SetTool_attempted=False,automatic_retry=False,continuation_ready=False,
        production_qualified=False,physical_cutting_conditions_qualified=False,persistence_after_reopen_verified=False,
        inherited_verified_action_names=list(partial['actions']),configured_operation_ids=[])
    try:
        journal.create();backend.start();backend.check_prepared(prepared['actual'])
        remaining=reconcile(partial,prepared['actual'],wanted)
        require(group.exact(remaining,prepared['remaining']),'Prepared remainder changed')
        for row in remaining:
            label=row['action'];target=row['target'];spec=next(s for s in specs(target)if s[0]==row['field'])
            require(label not in partial['actions'],'An already attempted field cannot replay')
            r['phase']=label;journal.persist()
            # Earlier approved setters can update aliases. Re-read this current
            # field instead of using the preparation's old skip/write decision.
            current=backend.read_fields(target,[row['field']])[row['field']]
            r.setdefault('fields_before',{})[label]=deepcopy(current);journal.persist()
            if group.exact(current,row['wanted']):
                journal.entry(label);journal.verified(label,dict(already_satisfied=True,value=current));continue
            started=perf_counter()
            journal.execute(label,lambda pending:backend.set_field(target,spec,row['wanted'],pending))
            r.setdefault('timing',{})[label]=dict(native_guard_and_write_seconds=perf_counter()-started)
            started=perf_counter();backend.refresh_dirty()
            r['timing'][label]['refresh_seconds']=perf_counter()-started
            actual=backend.read_fields(target,[row['field']])[row['field']]
            require(group.exact(actual,row['wanted']),'Remaining field readback differs')
            journal.verified(label,actual)
        r['configured']=backend.capture_parameters('configured')
        config.verify_configured(partial['after_tools'],r['configured'],recipe,wanted)
        for a,b in zip(partial['after_tools']['parameters'],r['configured']['parameters']):
            require(group.exact(config.protected_parameters(a),config.protected_parameters(b)),
                'Remaining setters changed an unselected parameter')
        r['configuration_readback_verified']=True;r['configured_operation_ids']=[v['operation_native_id']for v in recipe['rows']]
        r['save_stage']={};journal.entry('SaveActiveDocument');r['save_attempted']=True;journal.persist()
        expected=deepcopy(r['configured'])
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(expected)
            actual=backend.capture_parameters('saved');config.verify_configured(partial['after_tools'],actual,recipe,wanted)
            r['saved']=actual;return actual
        def verify(value):require(group.exact(value,expected),'Save changed complete configuration')
        def save():
            value=backend.save();entry=r['actions']['SaveActiveDocument']
            require(entry['attempted'] is True and entry.get('native_dispatch_pending') is True,'Save bypassed pending')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value))
            r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved bytes did not change')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256']);backend.finish()
        r['saved_checkpoint_context']=dict(process_id=r['request']['process_id'],ownership=deepcopy(r['ownership']),
            document=deepcopy(r['source_transition']['document']),source_sha256=r['saved_source_sha256'],
            configuration=deepcopy(loaded['guide_parameters']['configuration']),snapshot_key='saved',snapshot_sha256=group._digest(r['saved']),
            prior_source_sha256=r['source_sha256'],prior_parameter_receipt_pin=deepcopy(loaded['prepared_pin']),
            persistence_after_reopen_verified=False)
        r.update(status='saved_configuration_no_toolpath',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r


def prepare_request(request):
    require(type(request) is dict and set(request)=={'action','params'}
        and request['action'] in ('prepare_partial_guide_configuration','resume_partial_guide_configuration'),'Exact continuation action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact bounded continuation keys required')
    require(p['module_sha256']==_file_hash(__file__),'Continuation module changed')
    partial,partial_pin=read_pin(p['partial_receipt_path'],p['partial_receipt_sha256'])
    exit_proof,exit_pin=read_pin(p['writer_exit_path'],p['writer_exit_sha256'])
    validate_partial(partial,exit_proof,partial_pin)
    for key in ('process_id','expected_source_sha256','expected_configuration','addin_clsid'):
        require(type(p[key]) is type(partial['request'][key]) and p[key]==partial['request'][key],'Partial caller binding differs')
    require(common._key(p['expected_document_path'])==common._key(partial['source_path']),'Partial document differs')
    rp={k:v for k,v in partial['request'].items()if k in reader.PARAMS}
    rp.update(module_sha256=_file_hash(reader.__file__),receipt_path=p['receipt_path'],progress_path=p['progress_path'])
    _,loaded,registration,typelib,_,receipt=reader.prepare_request(dict(action='read_guide_actual_parameters',params=rp))
    require(group.exact(loaded['ownership'],partial['ownership']),'Owned process lineage changed')
    saved_doc=deepcopy(loaded['state']['document']);saved_doc['needs_save']=partial['current_document']['needs_save']
    require(type(saved_doc['needs_save']) is bool and group.exact(saved_doc,partial['current_document']),'Current partial identity differs')
    config.validate_recipe(partial['recipe'],loaded['guide_parameters'])
    require(sum(common._key(v['path'])==common._key(partial['request']['recipe_path']) and v['sha256']==partial['request']['recipe_sha256'] for v in partial['configuration_pins'])==1,'Approved recipe pin absent')
    recipe,recipe_pin=read_pin(partial['request']['recipe_path'],partial['request']['recipe_sha256'])
    require(group.exact(recipe,partial['recipe']),'Approved recipe changed')
    tool=deepcopy(next(v['assigned_tool']for v in loaded['state']['operations']if v['native_id']==320))
    require(tool['native_id']==273 and tool['cut_diameter_native']==2.,'Saved qualified D2 tool required')
    loaded.update(partial=partial,partial_pin=partial_pin,writer_exit_pin=exit_pin,configuration_tool=tool,configuration_recipe=recipe,
        configuration_pins=deepcopy(partial['configuration_pins']),resume_pins=[partial_pin,exit_pin,common._pin(__file__),common._pin(fields.__file__)])
    loaded['pins']=common._merge(loaded['pins'],[common._pin(config.__file__)])
    require(len(loaded['pins'])<=64,'Existing bounded native pin closure exceeded')
    if request['action']=='prepare_partial_guide_configuration':
        require(p['prepared_receipt_path'] is None and p['prepared_receipt_sha256'] is None,'Read preparation cannot consume a previous preparation')
    else:
        prepared,prepared_pin=read_pin(p['prepared_receipt_path'],p['prepared_receipt_sha256'])
        require(prepared.get('scope')==PREPARE_SCOPE and prepared.get('status')=='observed'
            and prepared.get('readback_verified') is True and prepared.get('continuation_ready') is True
            and prepared.get('mutation_attempted') is False and prepared.get('module_pin')==common._pin(__file__),
            'Complete current read-only reconciliation required')
        require(prepared.get('source_partial_receipt_pin')==partial_pin and prepared.get('writer_exit_pin')==exit_pin
            and group.exact(prepared['ownership'],loaded['ownership']),'Prepared authority differs')
        require(not any(k in prepared for k in ('issue','failed_phase','cleanup_issue','receipt_write_error'))
            and prepared.get('read_only') is True and prepared.get('save_attempted') is False and prepared.get('GTP_attempted') is False
            and prepared.get('source_sha256')==p['expected_source_sha256']
            and group.exact(prepared.get('document'),partial['current_document']),'Prepared result is not a complete unchanged read')
        clean_events(prepared)
        require(group.exact(reconcile(partial,prepared['actual'],tool),prepared['remaining']),'Prepared plan differs')
        loaded.update(prepared=prepared,prepared_pin=prepared_pin);loaded['resume_pins'].append(prepared_pin)
    for name in ('pins','configuration_pins','resume_pins'):common._check(loaded[name])
    marker=common.local_evidence_root()/('guide_resume_'+group._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),
        sha256=p['expected_source_sha256'],partial=partial_pin['sha256']))+'.json')
    require(not marker.exists() and not marker.is_symlink(),'Prior remainder attempt cannot replay')
    forbidden={common._key(v['path'])for name in ('pins','configuration_pins','resume_pins')for v in loaded[name]}
    require(common._key(receipt)not in forbidden and common._key(p['progress_path'])not in forbidden
        and common._key(marker)not in forbidden and common._key(marker)not in {common._key(receipt),common._key(p['progress_path'])},
        'Output or marker aliases an authority')
    return p,loaded,registration,typelib,receipt,marker


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,receipt,marker=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,never_attempted_actions=validate_partial(
        loaded['partial'],read_pin(p['writer_exit_path'],p['writer_exit_sha256'])[0],loaded['partial_pin']),
        live_pin_count=len(loaded['pins']),extra_authority_pin_count=len(loaded['configuration_pins'])+len(loaded['resume_pins']))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(request=p,module_pin=common._pin(__file__),ownership=loaded['ownership'],
            source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],recipe_sha256=loaded['partial']['recipe_sha256'],
            recipe=loaded['partial']['recipe'],source_partial_receipt_pin=loaded['partial_pin'],writer_exit_pin=loaded['writer_exit_pin'],
            source_after_tools_reference=dict(receipt_pin=loaded['partial_pin'],key='after_tools',sha256=group._digest(loaded['partial']['after_tools'])),
            live_pins=loaded['pins'],configuration_pins=loaded['configuration_pins'],resume_pins=loaded['resume_pins'],
            interface_audit=deepcopy(loaded['partial']['interface_audit']),interface_audit_reused_from=loaded['partial_pin'])
        if request['action']=='prepare_partial_guide_configuration':
            _write_receipt(receipt,report,create=True);persist=lambda:_write_receipt(receipt,report)
            backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,persist)
            return run_prepare(backend,report,persist,loaded)
        report['prepared_receipt_pin']=loaded['prepared_pin'];journal=ResumeJournal(report,receipt,marker)
        backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_resume(backend,journal,loaded)
