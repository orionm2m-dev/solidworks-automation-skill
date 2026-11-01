"""One bounded deep-guide definition/configuration/generation/save packet.

Dynamic operation IDs are accepted only from native insertion returns and checked
against linked features. Prior thirteen definitions and ten CL streams remain
protected. A pending or partial native action is never replayed automatically.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_deep_guide_preflight as inspect
from scripts import sw_cam_deep_guide_fields as fields
from scripts import sw_cam_deep_guide_cl as cl
from scripts import sw_cam_guide_group_definitions as definitions
from scripts import sw_cam_guide_group_configuration as config
from scripts import sw_cam_guide_finish_compensation as nc
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_thread import _object_id,_file_hash
from scripts.sw_cam import _member,_error
from scripts.sw_cam_rough_firstcut import require

authority,common,group=inspect.authority,inspect.common,inspect.group
reader,generation=config.reader,authority.generation
SCOPE='SAVED_DEEP_GUIDE_FOUR_PACKET_V1'
PAIRS=((80,0),(80,1),(81,0),(81,1))
PARAMS={'process_id','expected_document_path','expected_source_sha256','inspect_receipt_path','inspect_receipt_sha256',
 'zero_attempt_receipt_path','zero_attempt_receipt_sha256','failed_writer_archive_path','failed_writer_archive_sha256',
 'failed_request_archive_path','failed_request_archive_sha256','source_backup_path','source_backup_sha256','choices','module_sha256','receipt_path','progress_path','before_cl_path','generated_cl_path','saved_cl_path','acknowledgement'}


def projected_baseline(loaded):
    value=deepcopy(loaded['guide_parameters']['expected_parameters'])
    value['binding']['features'].update(deepcopy(loaded['deep_headers']))
    return value


def protected_binding(baseline,current):
    require(current['operations'][:13]==baseline['operations']and len(current['operations'])in range(13,18),'Protected13 operation metadata changed')
    v=deepcopy(current);v['operations']=v['operations'][:13]
    require(len(v['operation_setups'])==len(baseline['operation_setups']),'Setup count changed')
    added=len(current['operations'])-13
    require(v['operation_setups'][0]['native_id']==93,'Exact operation setup93 required')
    v['operation_setups'][0]['operation_count']-=added
    require(group.exact(v,baseline),'Protected setup/feature geometry changed')


def verify_generated(configured,generated,counts,targets):
    ids=[r['operation_native_id']for r in targets];require(set(counts)==set(ids)and len(ids)==4,'Four actual new GTP results required')
    actual=deepcopy(generated)
    for row in actual['binding']['operations']:
        if row['native_id']not in ids:continue
        require(row['toolpath_generated']is True and row['toolpath_record_counts']==counts[row['native_id']],'Generated selected path differs')
        row['toolpath_generated']=False;row['toolpath_record_counts']=[]
    require(group.exact(configured,actual),'Generation changed parameters or another route')


def protected_selected(row):
    value=config.protected_parameters(row)
    value['nc']['feeds_compensation'].pop('GetCNCComp')
    if 'protected_finish'in value:value['protected_finish']['compensation'][1]=0
    return value


def verify_configured(before,after,targets,wanted):
    require(group.exact(before['binding'],after['binding']),'Configuration changed route or tool')
    byid={r['operation_native_id']:r for r in targets}
    require(len(before['parameters'])==len(after['parameters'])==8,'Full protected4 plus deep4 parameters required')
    for old,new in zip(before['parameters'],after['parameters']):
        oid=old['operation_native_id']
        if oid not in byid:require(group.exact(old,new),'Protected shallow parameter changed');continue
        target=byid[oid]
        require(new['operation_native_id']==oid and new['read_complete']is True and group.exact(new['tool']['generic'],wanted),'Configured target/tool differs')
        require(group.exact(protected_selected(old),protected_selected(new)),'Unrequested selected parameter changed')
        require(group.exact(new['nc']['feeds_compensation'],target['reference_nc']),'Selected NC/feed differs from actual saved reference')
        require(group.exact(new['levels'],old['levels']),'Selected machining levels changed')
        for spec in config.ROUGH_FIELDS if target['operation_type']==0 else config.FINISH_FIELDS:
            require(group.exact(config.field_value(new,spec),target['fields'][spec[0]]),'Configured field differs: '+spec[0])


def read_current_binding(doc, *,read,typed):
    require(read(doc,'GetDocType')==1,'Current CAM part required')
    machine=typed(read(typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    require(read(machine,'MachType')==1,'Current MILL machine required')
    out=dict(features={},operation_setups=[],operations=[]);handles={}
    for si,raw_setup in enumerate(_items(read(machine,'IGetEnumOpSetups'),typed,read,3)):
        setup=typed(raw_setup,'ICWBaseOpSetup');sid=_object_id(doc,setup,read)
        operations=_items(read(setup,'IGetEnumOperations'),typed,read,17)
        out['operation_setups'].append(dict(index=si,native_id=sid,operation_count=len(operations)))
        for oi,raw in enumerate(operations):
            op=typed(raw,'ICWOperation');oid=_object_id(doc,op,read)
            require(oid not in handles,'Duplicate operation native ID');handles[oid]=raw
            mill=typed(raw,'ICWMillOperation');tool,_=read_generic_tool(raw,doc,read,typed)
            out['operations'].append(dict(setup_index=si,setup_native_id=sid,operation_index=oi,native_id=oid,
                mill_operation_type=read(mill,'OpernType'),base_operation_type=read(op,'OpernType'),
                suppressed=read(op,'Suppressed'),toolpath_generated=read(op,'GetIsToolpathGenerated'),
                linked_feature_ids=[_object_id(doc,v,read) for v in _items(read(op,'IGetAllFeatures'),typed,read,4)],
                toolpath_record_counts=[read(typed(v,'ICWToolpath'),'RecordCount') for v in _items(read(op,'IGetEnumToolpaths'),typed,read,4)],assigned_tool=tool))
    require(13<=len(out['operations'])<=17,'Only baseline thirteen plus at most four definitions allowed')
    for fid in (80,81,82,83):
        found=read(doc,'GetCWObjectFromID',1,fid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact guide lookup required')
        header,_=read_header(found[0],doc,read,typed,69);require(header['native_id']==fid,'Guide ID changed')
        out['features'][str(fid)]=header
    return out,handles


class NativeBackend(authority.ParameterBackend):
    refresh_dirty=group.NativeBackend.refresh_dirty
    save=group.NativeBackend.save
    saved_hash=group.NativeBackend.saved_hash
    target=config.NativeBackend.target
    typed_field=config.NativeBackend.typed_field
    owner=config.NativeBackend.owner
    set_field=config.NativeBackend.set_field
    outcome=generation.NativeBackend.outcome

    def __init__(self,*args):
        super().__init__(*args);self.learned=[]

    def batch(self,doc,progress,state,binding=None):
        stats=dict(binding_native_calls=0,binding_checks=0,binding_elapsed_seconds=0.)
        check=generation.fast.make_configuration_check(self,doc,stats)
        self.report.setdefault('configuration_checks',[]).append(stats)
        return reader.ParameterReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
          process_id=self.args['process_id'],expected_document=self.ctx.identity(),source_sha256=self.ctx.args['expected_source_sha256'],
          evidence_pins=self.loaded['pins'],verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,
          check_events=self.events,retained_objects=(doc,),verify_retained_binding=check,max_native_calls=4000,
          progress=progress,progress_state=state)

    def capture_snapshot(self,label,*,full=False,own=None):
        self.boundary()
        with self.ctx.guard()as g:
            self.doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3');self.save_app=g.typed(self.ctx.app,'ICWApp')
        out=dict(label=label,parameters=[]);self.report.setdefault('captures',[]).append(out);self.persist()
        batch=self.batch(self.doc,lambda:None,dict(member='',returned=False,read_index=0))
        try:
            with batch:
                before,handles=read_current_binding(self.doc,read=batch.read,typed=batch.typed)
                if full or own is not None:
                    rows={r['native_id']:r for r in before['operations']}
                    if full:
                        shallow=deepcopy(self.loaded['guide_parameters']['targets'])
                        for t in shallow:t['assigned_tool']=deepcopy(rows[t['operation_native_id']]['assigned_tool'])
                        old={};reader.read_parameters(self.doc,handles,shallow,batch,old,lambda:None)
                        out['parameters']=[config.parameter_projection(x)for x in old['parameters']]
                    targets=deepcopy(self.learned if own is None else[own])
                    for t in targets:t['assigned_tool']=deepcopy(rows[t['operation_native_id']]['assigned_tool'])
                    if targets:
                        selected={};fields.read_parameter_groups(self.doc,handles,targets,batch,selected,lambda:None,learned=self.learned)
                        out['parameters'] += [config.parameter_projection(x)for x in selected['parameters']]
                after,_=read_current_binding(self.doc,read=batch.read,typed=batch.typed)
                require(group.exact(before,after),'Route changed during snapshot');out['binding']=after
            batch.require_complete()
        finally:out['read_batch']=batch.summary();self.persist()
        return dict(binding=deepcopy(out['binding']),parameters=deepcopy(out['parameters']))

    def capture_binding(self,label):return self.capture_snapshot(label)['binding']

    def insert(self,row,anchor,pending,returned):
        raw=definitions.insert_selected_once(self.ctx,self.doc,row,anchor,self.loaded['deep_headers'][str(row['feature_native_id'])],pending)
        returned(raw);self.refresh_dirty()
        with self.ctx.guard()as g:oid=_object_id(self.doc,raw,g.read)
        require(type(oid)is int and 0<oid<2**31 and oid not in set(inspect.ORDER)|{69,93,273,80,81,82,83},'Returned actual new operation ID invalid')
        return oid

    def assign(self,target,pending):
        from comtypes.automation import IDispatch
        with self.ctx.guard()as g:
            raw,_=self.target(g,target);part=g.typed(self.doc,'ICWPartDoc');machine=g.typed(g.read(part,'IGetMachine'),'ICWMachine')
            crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4');tools=_items(g.read(crib,'GetAllTools'),g.typed,g.read,64)
            ids=[_object_id(self.doc,t,g.read)for t in tools];require(ids.count(273)==1 and len(ids)==len(set(ids)),'Exact unique existing tool273 required')
            if 'tool_catalogue_ids'in self.report:require(ids==self.report['tool_catalogue_ids'],'Local tool catalogue changed')
            else:self.report['tool_catalogue_ids']=ids;self.persist()
            tool=g.typed(tools[ids.index(273)],'ICWTool');wanted=self.loaded['configuration_tool']
            require(g.read(tool,'ToolType')==wanted['tool_type_raw']and g.read(tool,'CutDiameter')==wanted['cut_diameter_native']
                and group.exact(g.read(tool,'Protrusion'),wanted['protrusion_native']),'Assigned tool273 dimensions changed')
            dispatch=g.read(tool,'QueryInterface',IDispatch);mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'SetTool',dispatch),persist_pending=pending)

    def field(self,target,spec):
        return fields.read_field_values(self,target,targets=self.learned,field_names=[spec[0]])['field_values'][spec[0]]

    def nc_owner(self,g,target):
        require(any(group.exact(target,t)for t in self.learned),'NC target outside actual learned4')
        raw,_=self.target(g,target);tool,_=read_generic_tool(raw,self.doc,g.read,g.typed)
        require(group.exact(tool,self.loaded['configuration_tool']),'NC target tool changed')
        op=g.typed(raw,'ICWOperation');require(g.read(op,'GetIsToolpathGenerated')is False and _items(g.read(op,'IGetEnumToolpaths'),g.typed,g.read,1)==[],'Only new ungenerated target allowed')
        owner=g.read(g.typed(raw,'ICWMillOperation'),'IGetNCParam');base=g.typed(owner,'ICWNCParam')
        ext=g._observe(lambda:nc.query_face_interface(owner,'ICWNCParam2',self.typelib_path,generated_pin=self.loaded['generated_pin']))
        return base,ext

    def read_nc(self,target):
        with self.ctx.guard()as g:return nc._values(g,*self.nc_owner(g,target))

    def set_nc(self,target,expected,pending):
        require(expected['GetCNCComp']==1 and expected['GetTlpComp']==1,'Only explicit existing1 to0 CNC correction allowed')
        with self.ctx.guard()as g:
            base,ext=self.nc_owner(g,target);require(group.exact(nc._values(g,base,ext),expected),'NC changed before setter')
            return g.dispatch_once(lambda:_member(base,'SetCNCComp',0),persist_pending=pending)

    def generate(self,target,pending):
        require(group.exact(self.read_nc(target),target['reference_nc']),'Exact CNC0/Tlp1 and actual inherited feed required beforeGTP')
        state=self.outcome(target);generation.status_contract(state,target,False)
        with self.ctx.guard()as g:
            raw,_=self.target(g,target);mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)

    def export(self,label,binding):
        diagnostic={};self.report.setdefault('cl_exports',{})[label]=diagnostic;self.persist()
        return cl.export_current_cl(self,label,binding,self.args[label+'_cl_path'],diagnostic)


class Journal(group.GroupJournal):
    def pending(self,name):
        if name.startswith('insert:'):self.report['operation_creation_attempted']=True
        elif name.startswith('SetTool:'):self.report['SetTool_attempted']=True
        elif name.startswith('GTP:'):self.report['GTP_attempted']=True
        elif name=='SaveActiveDocument':self.report['save_attempted']=True
        else:self.report['setter_attempted']=True
        return super().pending(name)
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],receipt_path=str(self.receipt),
          phase=r['phase'],status=r['status'],actions=deepcopy(r['actions']),actual_new_ids=r.get('actual_new_ids',[]),
          native_dispatch_pending=r.get('native_dispatch_pending',False),automatic_replay=False)


def run_backend(backend,journal,loaded):
    r=journal.report
    r.update(status='error',phase='preflight',actions={},actual_new_ids=[],mutation_attempted=False,native_call_attempted=False,
      native_call_returned=False,native_dispatch_pending=False,operation_creation_attempted=False,SetTool_attempted=False,
      setter_attempted=False,GTP_attempted=False,save_attempted=False,model_saved=False,readback_verified=False,
      automatic_retry=False,automatic_rollback=False,production_qualified=False,geometry_accepted=False,
      persistence_after_reopen_verified=False,continuation_ready=False)
    try:
        journal.create();backend.start();r['before']=backend.capture_snapshot('before',full=True)
        baseline=projected_baseline(loaded);require(group.exact(r['before'],baseline),'Fresh protected13/10 snapshot differs')
        r['before_cl']=backend.export('before',r['before']['binding']);current=r['before']['binding'];anchor=328
        for recipe in loaded['deep_plan']['rows']:
            label='insert:'+recipe['key'];entry=journal.entry(label)
            def returned(raw):
                require(entry['attempted']is True and entry.get('native_dispatch_pending')is True and entry['returned']is False,'Insertion bypassed durable pending')
                entry.update(returned=True,status='returned',native_dispatch_pending=False,returned_interface_pointer=True)
                r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist()
            oid=backend.insert(recipe,anchor,lambda:journal.pending(label),returned)
            entry['actual_native_id']=oid;r['actual_new_ids'].append(oid);journal.persist()
            after=backend.capture_binding('after_'+recipe['key']);definition=definitions.verify_one_addition(current,after,recipe,oid,anchor)
            target=dict(deepcopy(recipe),operation_native_id=oid,assigned_tool=deepcopy(definition['assigned_tool']))
            backend.learned.append(target);journal.verified(label,definition);current=after;anchor=oid
        fields.learned_targets(backend.learned);r['definitions']=backend.capture_snapshot('definitions',full=True)
        protected_binding(baseline['binding'],r['definitions']['binding']);before_own={x['operation_native_id']:x for x in r['definitions']['parameters']}
        for target in backend.learned:require(group.exact(before_own[target['operation_native_id']]['levels'],target['expected_levels']),'Native deep machining depth/setup differs from exact feature-derived4.4')
        for target in backend.learned:
            oid=target['operation_native_id'];label='SetTool:'+str(oid)
            journal.execute(label,lambda pending:backend.assign(target,pending));backend.refresh_dirty()
            target['assigned_tool']=deepcopy(loaded['configuration_tool'])
            own=backend.capture_snapshot('after_tool_'+str(oid),own=target);protected_binding(baseline['binding'],own['binding'])
            actual=own['parameters'][0];require(group.exact(actual['tool'],target['reference_tool_dimensions']),'Actual assigned tool dimensions differ')
            config.verify_automatic_target(before_own[oid],actual)
            expected=deepcopy(target['reference_nc']);expected['GetCNCComp']=actual['nc']['feeds_compensation']['GetCNCComp']
            require(expected['GetCNCComp']in(0,1)and group.exact(actual['nc']['feeds_compensation'],expected),'SetTool changed inherited feed/Tlp/retract; explicit new decision required')
            r.setdefault('after_tool_parameters',{})[str(oid)]=deepcopy(actual);journal.verified(label,actual)
        r['after_tools']=backend.capture_snapshot('after_tools',full=True);protected_binding(baseline['binding'],r['after_tools']['binding'])
        require(group.exact(r['after_tools']['parameters'][:4],baseline['parameters']),'Protected shallow parameters changed during tool assignment')
        for actual in r['after_tools']['parameters'][4:]:require(group.exact(actual,r['after_tool_parameters'][str(actual['operation_native_id'])]),'Another SetTool changed a previously observed selected target')
        for target in backend.learned:
            oid=target['operation_native_id']
            for spec in config.ROUGH_FIELDS if target['operation_type']==0 else config.FINISH_FIELDS:
                value=target['fields'][spec[0]];label=str(oid)+':'+spec[0];old=backend.field(target,spec)
                if group.exact(old,value):journal.entry(label);journal.verified(label,dict(already_satisfied=True,value=old));continue
                journal.execute(label,lambda pending,spec=spec,value=value:backend.set_field(target,spec,value,pending));backend.refresh_dirty()
                actual=backend.field(target,spec);require(group.exact(actual,value),'Selected field immediate readback differs');journal.verified(label,actual)
            current_nc=backend.read_nc(target);expected=target['reference_nc']
            if not group.exact(current_nc,expected):
                require(group.exact(dict(current_nc,GetCNCComp=0),expected),'Only CNC correction permitted')
                label='CNC0:'+str(oid);journal.execute(label,lambda pending:backend.set_nc(target,current_nc,pending));backend.refresh_dirty()
                actual=backend.read_nc(target);require(group.exact(actual,expected),'Exact CNC0/Tlp1 readback required');journal.verified(label,actual)
        r['configured']=backend.capture_snapshot('configured',full=True);verify_configured(r['after_tools'],r['configured'],backend.learned,loaded['configuration_tool'])
        protected_binding(baseline['binding'],r['configured']['binding']);counts={}
        for target in backend.learned:
            label='GTP:'+str(target['operation_native_id']);journal.execute(label,lambda pending:backend.generate(target,pending));backend.refresh_dirty()
            outcome=backend.outcome(target);generation.status_contract(outcome,target,True)
            counts[target['operation_native_id']]=deepcopy(outcome['record_counts']);journal.verified(label,outcome)
        r['generated']=backend.capture_snapshot('generated',full=True);verify_generated(r['configured'],r['generated'],counts,backend.learned)
        r['generated_cl']=backend.export('generated',r['generated']['binding']);r['protected_cl']=cl.verify_protected(r['before_cl'],r['generated_cl'])
        r['new_cutcom_review']=cl.verify_no_new_cutcom(r['generated_cl']);r['save_stage']={};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['generated'])
            r['saved']=backend.capture_snapshot('saved',full=True);return r['saved']
        def verify(v):require(group.exact(v,r['generated']),'Save changed complete protected/deep snapshot')
        def save():
            value=backend.save();entry=r['actions']['SaveActiveDocument'];require(entry['attempted']is True,'Save bypassed pending')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value))
            r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved source did not change')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
          claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding']);r['saved_cl_comparison']=cl.verify_all(r['generated_cl'],r['saved_cl'])
        backend.finish();r['learned_targets']=deepcopy(backend.learned)
        parsed=cl._verified(r['saved_cl'])
        signatures=[group._digest(cl.review.block_signature(parsed,i))for i in range(14)]
        r['saved_checkpoint_context']=dict(source_backup_pin=deepcopy(loaded['source_backup_pin']),
          learned_targets=deepcopy(backend.learned),post_assignment_parameters=deepcopy(r['after_tool_parameters']),
          saved_snapshot=deepcopy(r['saved']),saved_cl_pin=deepcopy(r['saved_cl']['output']),saved_CL_block_signature_sha256=signatures,
          live_pins=deepcopy(loaded['pins']),checkpoint_pins=deepcopy(loaded['checkpoint_pins']),
          process_id=r['request']['process_id'],ownership=deepcopy(r['ownership']),
          document=deepcopy(r['source_transition']['document']),configuration=deepcopy(loaded['guide_parameters']['configuration']),
          source_sha256=r['saved_source_sha256'],prior_source_sha256=r['source_sha256'],snapshot_key='saved',
          snapshot_sha256=group._digest(r['saved']),prior_inspect_receipt_pin=r['inspect_receipt_pin'],
          operation_order=[x['native_id']for x in r['saved']['binding']['operations']],generated_ids=list(inspect.GENERATED)+r['actual_new_ids'],
          persistence_after_reopen_verified=False)
        r.update(status='saved_deep_guides_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        try:journal.persist()
        except Exception as exc:r['receipt_write_error']=_error(exc);r['continuation_ready']=False
    return r



def verify_zero_attempt(r,p,loaded,archived_writer,archived_request):
    require(r.get('scope')==SCOPE and r.get('status')=='error'and r.get('phase')=='finished'and r.get('failed_phase')=='preflight',
      'Only the exact preflight failure can continue')
    require(r.get('actions')=={} and r.get('actual_new_ids')==[] and not any(k in r for k in ('captures','before','before_cl','cl_exports','generated_cl','saved_cl','source_transition','saved_checkpoint_context','receipt_write_error','cleanup_issue')),
      'Any observed action/capture or uncertain cleanup forbids this continuation')
    for key in ('mutation_attempted','native_call_attempted','native_call_returned','native_dispatch_pending','operation_creation_attempted',
      'SetTool_attempted','setter_attempted','GTP_attempted','save_attempted','model_saved','readback_verified','continuation_ready','automatic_retry','automatic_rollback'):
        require(r.get(key)is False,'Zero-attempt proof missing: '+key)
    clean_events(r);require(r.get('cleanup_session_active')is False,'Prior subscription cleanup must be complete')
    expected_issue=dict(type='TypeError',hresult=None,actual_return_type=None,
      locations=[dict(file='sw_cam_deep_guide_group.py',function='run_backend',line=237)])
    require(group.exact(r.get('issue'),expected_issue),'Only known capture-module collision is covered')
    require(r['module_pin']['sha256']==archived_writer['sha256']==r['request']['module_sha256']
      and archived_writer['sha256']=='66ab12b39be05bcdc695733d3c1c55b89089a8a7b4007e0451e4e133dd89ea51'
      and p['module_sha256']!=archived_writer['sha256']and common._key(archived_writer['path'])!=common._key(r['module_pin']['path']),
      'Exact independently archived failed writer and changed correction required')
    require(archived_request.get('action')=='apply_deep_guide_group'and type(archived_request.get('params'))is dict,'Exact original sealed action required')
    expected_request=deepcopy(r['request']);expected_request.pop('expected_configuration')
    require(group.exact(archived_request['params'],expected_request),'Archived sealed request differs from executed request')
    require(group.exact(r['ownership'],loaded['ownership'])and r['ownership']['process_id']==p['process_id'],'Failed attempt owner differs')
    require(r['source_sha256']==p['expected_source_sha256']and common._key(r['source_path'])==common._key(p['expected_document_path']),
      'Failed attempt source differs')
    for key in ('process_id','expected_source_sha256','inspect_receipt_sha256','source_backup_sha256','choices','acknowledgement'):
        require(group.exact(r['request'][key],p[key]),'Continuation changes requested work: '+key)
    for key in ('expected_document_path','inspect_receipt_path','source_backup_path'):
        require(common._key(r['request'][key])==common._key(p[key]),'Continuation changes source authority: '+key)
    require(group.exact(r['plan'],loaded['deep_plan']),'Continuation changes inspected recipe')
    # Only the replaced failed writer becomes a historical archive pin. All other
    # previous code/data dependencies remain live and must still match exactly.
    retired=[];others=[]
    for pin in r['checkpoint_pins']:
        if common._key(pin['path'])==common._key(r['module_pin']['path']):
            require(pin['sha256']==archived_writer['sha256'],'Failed writer pin mismatch');retired.append(pin)
        else:others.append(pin)
    require(len(retired)==1 and not any(common._key(x['path'])==common._key(r['module_pin']['path'])for x in r['live_pins']),
      'Exactly one failed-writer historical pin may be replaced')
    common._check(r['live_pins']);common._check(others)
    return common._merge(others,[archived_writer])


def load_zero_attempt(p,loaded):
    failure,fp=read_pin(p['zero_attempt_receipt_path'],p['zero_attempt_receipt_sha256'])
    archived_writer=common._pin(p['failed_writer_archive_path'])
    require(archived_writer['sha256']==p['failed_writer_archive_sha256'],'Failed writer archive changed')
    archived_request,rp=read_pin(p['failed_request_archive_path'],p['failed_request_archive_sha256'])
    canonical,cp=read_pin(failure['request']['receipt_path'],p['zero_attempt_receipt_sha256'])
    require(group.exact(canonical,failure)and common._key(fp['path'])!=common._key(cp['path']),'Independent archive and untouched canonical failure required')
    pins=verify_zero_attempt(failure,p,loaded,archived_writer,archived_request)
    return common._merge(pins,[fp,cp,rp]),dict(receipt_pin=fp,canonical_receipt_pin=cp,failed_writer_pin=archived_writer,
      failed_request_pin=rp,recognized_failure_type='TypeError',recognized_failure_location='run_backend:237',
      original_mutation_attempted=False,original_actions_empty=True,original_session_closed=True,source_unchanged=True,
      correction='Rename capture method to capture_snapshot; retain inherited capture module unchanged')

def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='apply_deep_guide_group','Exact deep packet action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact bounded packet fields required')
    require(p['acknowledgement']=='create4_configure4_generate4_save1_preserve13_10_no_replay','Explicit whole packet scope required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict exact owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Deep packet module changed')
    require(p['source_backup_sha256']==p['expected_source_sha256']and common._key(p['source_backup_path'])!=common._key(p['expected_document_path']),'Independent source8c backup required')
    backup=common._pin(p['source_backup_path']);require(backup['sha256']==p['expected_source_sha256']and Path(p['source_backup_path']).suffix.lower()=='.sldprt','Pinned native source backup differs')
    observed,observed_pin=read_pin(p['inspect_receipt_path'],p['inspect_receipt_sha256'])
    require(observed.get('module_pin')==common._pin(inspect.__file__),'Exact installed inspector proof required')
    require(observed['request']['process_id']==p['process_id']==observed['ownership']['process_id']
      and observed['request']['expected_source_sha256']==p['expected_source_sha256']
      and common._key(observed['request']['expected_document_path'])==common._key(p['expected_document_path']),'Inspector owner/source differs')
    clean_events(observed);plan=inspect.compile_definition_plan(observed,p['choices'])
    for row in plan['rows']:
        require(row['default_operation_name']=='Default'and row['default_operation_id']==(79 if row['operation_type']==0 else 87),'Only selected observed Default79/87 supported')
    selector={k:observed['request'][k]for k in ('process_id','expected_document_path','expected_source_sha256','corrected_receipt_path','corrected_receipt_sha256')}
    loaded,registration,typelib,abi,pin=authority.load_checkpoint(selector)
    p['expected_configuration']=selector['expected_configuration']
    require(group.exact(observed['before'],loaded['guide_parameters']['expected_parameters'])
      and group.exact(observed['before_document'],loaded['guide_parameters']['document'])
      and group.exact(observed['after_document'],loaded['guide_parameters']['document']),'Inspector baseline/document differs from corrected source')
    geometry,gpin=read_pin(observed['request']['geometry_path'],observed['request']['geometry_sha256'])
    hp=geometry['source_pins'][1];historical,_=read_pin(hp['path'],hp['sha256']);headers,shapes=inspect.geometry_contract(geometry,historical)
    require(group.exact(headers,observed['deep_headers_before'])and group.exact(inspect.recipe_preflight(loaded,shapes),observed['preflight']),'Inspector recipe/geometry provenance differs')
    loaded['source_backup_pin']=backup
    loaded['deep_plan']=plan;loaded['deep_headers']=headers;loaded['configuration_tool']=deepcopy(loaded['guide_parameters']['targets'][0]['assigned_tool'])
    source_params=loaded['guide_parameters']['expected_parameters']['parameters']
    for target in plan['rows']:
        ref=next(x for x in source_params if x['operation_native_id']==target['reference_operation_native_id'])
        levels=deepcopy(ref['levels']);levels['levels']['machining_depth_native']=4.4;target['expected_levels']=levels
    predecessor_pins,predecessor=load_zero_attempt(p,loaded)
    loaded['zero_attempt_predecessor']=predecessor
    extra=[common._pin(x)for x in (__file__,fields.__file__,cl.__file__,inspect.__file__,definitions.__file__,config.__file__,nc.__file__)]
    extra+=cl.dependency_pins()+[observed_pin,gpin,backup]+geometry['source_pins']
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],observed['checkpoint_pins'],extra,predecessor_pins)
    require(len(loaded['pins'])<=64 and len(loaded['checkpoint_pins'])<=60,'Bounded packet code/proof closure required')
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    abi.update(configuration=config.audit(typelib,loaded['generated_pin']),compensation=nc.audit(typelib,loaded['generated_pin']),insertion=definitions.audit_insert(typelib,loaded['generated_pin']))
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path'])
    marker=common.local_evidence_root()/('deep_guide_group_'+group._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    outputs=[receipt,progress,marker]+[Path(x)for x in cl.validate_outputs(p)]
    protected={common._key(v['path'])for v in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(x)for x in outputs})==len(outputs),'Separate packet outputs required')
    for path in outputs:require(not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Prior packet or aliased output; no automatic replay')
    for path in (receipt,progress,marker):require(path.parent.is_dir(),'Existing diagnostics directory required')
    return p,loaded,registration,typelib,abi,receipt,marker,observed_pin


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,pin=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE,source_sha256=p['expected_source_sha256'],
      live_pin_count=len(loaded['pins']),checkpoint_pin_count=len(loaded['checkpoint_pins']),plan=loaded['deep_plan'],
      marker_path=str(marker),zero_attempt_predecessor=loaded['zero_attempt_predecessor'],interface_audit=abi,expected_final_definitions=17,expected_final_generated=14)
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=authority.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
          ownership=deepcopy(loaded['ownership']),zero_attempt_predecessor=deepcopy(loaded['zero_attempt_predecessor']),inspect_receipt_pin=pin,plan=deepcopy(loaded['deep_plan']),interface_audit=abi,
          live_pins=deepcopy(loaded['pins']),checkpoint_pins=deepcopy(loaded['checkpoint_pins']))
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_backend(backend,journal,loaded)
