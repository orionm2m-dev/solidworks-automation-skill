"""Replace the tool of four existing deep guides, regenerate four paths, save once.

The preceding tool-creation receipt supplies the actual new tool identity and
complete saved seventeen-operation baseline. No operation or tool is created
here. Every native action is claimed once before dispatch and never replayed.
"""
from copy import deepcopy
from pathlib import Path
import json, math, re
from scripts import sw_cam_deep_guide_checkpoint as authority
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam import _member, _error
from scripts.sw_cam_rough_firstcut import require

writer=authority.writer
config,group,common,cl=writer.config,writer.group,writer.common,writer.cl
generation=writer.generation
SCOPE='EXISTING_DEEP_GUIDE_LONG_TOOL_REPLACEMENT_V1'
IDS=(330,332,334,336)
PAIRS=((80,0),(80,1),(81,0),(81,1))
OLD=tuple(cl.ORDER)


def baseline_contract(loaded):
    snapshot=loaded['guide_parameters']['expected_parameters'];targets=loaded['deep_targets']
    writer.fields.learned_targets(targets)
    require([t['operation_native_id']for t in loaded['guide_parameters']['targets']]==[322,324,326,328], 'Exact protected shallow reader targets required')
    require(tuple(t['operation_native_id']for t in targets)==IDS,'Exact saved four deep operations required')
    require(tuple((t['feature_native_id'],t['operation_type'])for t in targets)==PAIRS,'Exact deep feature/type mapping required')
    require(tuple(r['native_id']for r in snapshot['binding']['operations'])==OLD+IDS,'Exact saved seventeen-definition route required')
    require([r['operation_native_id']for r in snapshot['parameters']]==[322,324,326,328,*IDS],'Full protected4 plus deep4 parameter groups required')
    cl.contract(snapshot['binding'])
    tool=loaded['configuration_tool'];require(type(tool['native_id'])is int and tool['native_id']>0 and tool['native_id']not in set(OLD+IDS+(273,69,93,80,81,82,83)), 'Unique actually created new tool required')
    require(tool['is_mill_tool']is True and tool['native_read_complete']is True and tool['tool_type_raw']==1 and tool['cut_diameter_native']==2.,'Actual new flat D2 mill tool required')
    dims=loaded['replacement_tool_dimensions'];require(group.exact(dims['generic'],tool),'Exact new native tool projection required')
    for key,value in [('MillToolType',1),('MillToolSubType',3),('EffCutlength',6.),('ShankDia',4.),('OverallLen',40.),('EndRadius',0.)]:
        require(dims['mill'][key]['recorded']is True and type(dims['mill'][key]['raw']) in (int,float) and math.isclose(dims['mill'][key]['raw'],value,rel_tol=0.,abs_tol=1e-8),'OSG3130520 observed field differs: '+key)
    catalogue=loaded['tool_catalogue_ids'];require(len(catalogue)==len(set(catalogue))and catalogue.count(tool['native_id'])==1,'Unique created tool in unchanged catalogue required')
    for t in targets:
        row=next(x for x in snapshot['parameters']if x['operation_native_id']==t['operation_native_id'])
        require(row['nc']['feeds_compensation']=={'GetSpndlSpeed':4000.,'GetTlpComp':1,'GetCNCComp':0,'GetRetractType':0,'XYFeed':500.},'Exact inherited geometry-only NC/feed settings required')
    return snapshot


def verify_route(before,after,wanted,changed,generated=None):
    require(set(changed)<=set(IDS),'Assignment outside deep four')
    require(tuple(r['native_id']for r in before['operations'])==tuple(r['native_id']for r in after['operations'])==OLD+IDS,'Definition order/count changed')
    require(group.exact(before['features'],after['features'])and group.exact(before['operation_setups'],after['operation_setups']),'Feature or setup changed')
    for old,new in zip(before['operations'],after['operations']):
        oid=old['native_id'];expected=deepcopy(old)
        if oid in changed:
            expected['assigned_tool']=deepcopy(wanted)
            if generated is not None and oid in generated:
                require(new['toolpath_generated']is True and new['toolpath_record_counts']==generated[oid],'Explicit regenerated path differs')
            else:
                require((new['toolpath_generated']is True and new['toolpath_record_counts']==old['toolpath_record_counts'])or(new['toolpath_generated']is False and new['toolpath_record_counts']==[]),'SetTool may retain or invalidate its old path only')
            expected['toolpath_generated']=new['toolpath_generated'];expected['toolpath_record_counts']=deepcopy(new['toolpath_record_counts'])
        require(group.exact(expected,new),'Protected operation metadata or tool changed: '+str(oid))


def verify_restorable(old,new,wanted):
    require(new['read_complete']is True and group.exact(new['tool'],wanted),'Immediate complete new-tool projection differs')
    a=writer.protected_selected(old);b=writer.protected_selected(new)
    a.pop('tool');b.pop('tool')
    require(group.exact(a,b),'SetTool changed unrequested levels, start coordinates, feed, or protected field')
    before=old['nc']['feeds_compensation'];after=new['nc']['feeds_compensation']
    require(after['GetCNCComp']in(0,1)and group.exact(dict(after,GetCNCComp=0),before),'Only CNC compensation0/1 may differ after SetTool')


def verify_parameters(before,after,wanted):
    require(len(before)==len(after)==8,'Full eight parameter groups required')
    for old,new in zip(before,after):
        expected=deepcopy(old)
        if old['operation_native_id']in IDS:expected['tool']=deepcopy(wanted)
        require(group.exact(expected,new),'Selected recipe or protected parameter changed')


def verify_protected_cl(before,after):
    a=cl._verified(before);b=cl._verified(after);cl._shared(a,b)
    aa=before['expected_generated_operations'];bb=after['expected_generated_operations']
    require([x['operation_native_id']for x in aa]==[x['operation_native_id']for x in bb]==list(cl.OLD)+list(IDS),'Exact fourteen-stream identity/order required')
    require(aa[:10]==bb[:10],'Protected native counts changed')
    for i in range(10):require(cl.review.block_signature(a,i)==cl.review.block_signature(b,i),'Protected complete CL stream changed')
    return dict(protected_ten_complete_streams_verified=True,unchanged_native_ids=list(cl.OLD),geometry_verified=False)


class NativeBackend(authority.ParameterBackend):
    refresh_dirty=group.NativeBackend.refresh_dirty
    save=group.NativeBackend.save
    saved_hash=group.NativeBackend.saved_hash
    target=config.NativeBackend.target
    typed_field=config.NativeBackend.typed_field
    owner=config.NativeBackend.owner
    field=config.NativeBackend.field
    set_field=config.NativeBackend.set_field
    outcome=generation.NativeBackend.outcome
    export=writer.NativeBackend.export

    def assign(self,target,pending):
        from comtypes.automation import IDispatch
        require(any(group.exact(target,t)for t in self.learned),'Target outside actual deep group')
        wanted=self.loaded['configuration_tool']
        with self.ctx.guard()as g:
            raw,_=self.target(g,target);machine=g.typed(g.read(g.typed(self.doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4');tools=_items(g.read(crib,'GetAllTools'),g.typed,g.read,64)
            ids=[_object_id(self.doc,t,g.read)for t in tools];require(ids==self.loaded['tool_catalogue_ids'],'Tool catalogue changed after verified creation')
            tool=g.typed(tools[ids.index(wanted['native_id'])],'ICWTool')
            require(g.read(tool,'ToolType')==wanted['tool_type_raw']and g.read(tool,'CutDiameter')==wanted['cut_diameter_native']and group.exact(g.read(tool,'Protrusion'),wanted['protrusion_native']),'Created tool identity/dimensions changed')
            dispatch=g.read(tool,'QueryInterface',IDispatch);mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'SetTool',dispatch),persist_pending=pending)

    def nc_owner(self,g,target):
        require(any(group.exact(target,t)for t in self.learned),'NC target outside exact deep four')
        raw,_=self.target(g,target);tool,_=read_generic_tool(raw,self.doc,g.read,g.typed)
        require(group.exact(tool,self.loaded['configuration_tool']),'Selected tool changed before NC/GTP')
        owner=g.read(g.typed(raw,'ICWMillOperation'),'IGetNCParam');base=g.typed(owner,'ICWNCParam')
        ext=g._observe(lambda:writer.nc.query_face_interface(owner,'ICWNCParam2',self.typelib_path,generated_pin=self.loaded['generated_pin']))
        return base,ext

    def read_nc(self,target):
        with self.ctx.guard()as g:return writer.nc._values(g,*self.nc_owner(g,target))

    def set_nc(self,target,expected,pending):
        require(expected['GetCNCComp']==1 and expected['GetTlpComp']==1,'Only observed CNC1 to0 restoration allowed')
        with self.ctx.guard()as g:
            base,ext=self.nc_owner(g,target);require(group.exact(writer.nc._values(g,base,ext),expected),'NC changed before restoration')
            return g.dispatch_once(lambda:_member(base,'SetCNCComp',0),persist_pending=pending)

    def generate(self,target,pending):
        require(group.exact(self.read_nc(target),target['reference_nc']),'Exact restored NC/feed required before GTP')
        value=self.outcome(target);generation.status_contract(value,target,None)
        require(value['background_over_before']is True and value['background_over_after']is True,'Background generation not idle')
        with self.ctx.guard()as g:
            raw,_=self.target(g,target);tool,_=read_generic_tool(raw,self.doc,g.read,g.typed)
            require(group.exact(tool,self.loaded['configuration_tool']),'New tool changed before GTP')
            return g.dispatch_once(lambda:_member(g.typed(raw,'ICWMillOperation'),'GenerateToolpath'),persist_pending=pending)


class Journal(writer.Journal):
    def _marker_state(self):
        value=super()._marker_state();value.update(scope=SCOPE,tool_creation_pin=deepcopy(self.report['tool_creation_pin']),operation_creation_attempted=False)
        return value


def run_backend(backend,journal,loaded):
    require(not journal.created and not journal.claimed,'A prior or partial replacement attempt must never replay')
    r=journal.report
    r.update(status='error',phase='preflight',actions={},mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
      SetTool_attempted=False,setter_attempted=False,GTP_attempted=False,save_attempted=False,model_saved=False,readback_verified=False,continuation_ready=False,
      operation_creation_attempted=False,tool_creation_attempted=False,automatic_retry=False,automatic_rollback=False,physical_cutting_conditions_qualified=False,
      geometry_acceptance_complete=False,production_qualified=False,persistence_after_reopen_verified=False)
    try:
        baseline=baseline_contract(loaded);journal.create();backend.start();r['before']=backend.capture_snapshot('before',full=True)
        require(group.exact(r['before'],baseline),'Current saved17/14 snapshot changed after tool creation')
        r['before_cl_reference']=deepcopy(loaded['created_saved_cl']);cl._verified(r['before_cl_reference'])
        wanted=loaded['replacement_tool_dimensions'];assigned=[]
        oldrows={x['operation_native_id']:x for x in baseline['parameters']}
        for target in backend.learned:
            oid=target['operation_native_id'];name='SetTool:'+str(oid)
            journal.execute(name,lambda pending:backend.assign(target,pending));backend.refresh_dirty()
            actual=backend.capture_snapshot('assigned_'+str(oid),own=target);assigned.append(oid)
            verify_route(baseline['binding'],actual['binding'],loaded['configuration_tool'],assigned)
            require(len(actual['parameters'])==1 and actual['parameters'][0]['operation_native_id']==oid,'Immediate own-target readback required')
            own=actual['parameters'][0];verify_restorable(oldrows[oid],own,wanted);journal.verified(name,own)
            # Restore only actual automatic recipe changes, never silently accept them.
            for spec in config.ROUGH_FIELDS if target['operation_type']==0 else config.FINISH_FIELDS:
                expected=config.field_value(oldrows[oid],spec);current=config.field_value(own,spec)
                if group.exact(current,expected):continue
                name='Restore:'+str(oid)+':'+spec[0]
                journal.execute(name,lambda pending,spec=spec,expected=expected:backend.set_field(target,spec,expected,pending));backend.refresh_dirty()
                observed=backend.field(target,spec);require(group.exact(observed,expected),'Restored recipe immediate readback differs');journal.verified(name,observed)
            actual_nc=backend.read_nc(target);expected_nc=oldrows[oid]['nc']['feeds_compensation']
            if not group.exact(actual_nc,expected_nc):
                require(group.exact(dict(actual_nc,GetCNCComp=0),expected_nc),'Unrequested NC/feed change')
                name='CNC0:'+str(oid);journal.execute(name,lambda pending:backend.set_nc(target,actual_nc,pending));backend.refresh_dirty()
                observed=backend.read_nc(target);require(group.exact(observed,expected_nc),'NC restoration immediate readback differs');journal.verified(name,observed)
        r['configured']=backend.capture_snapshot('configured',full=True)
        verify_route(baseline['binding'],r['configured']['binding'],loaded['configuration_tool'],IDS)
        verify_parameters(baseline['parameters'],r['configured']['parameters'],wanted);counts={}
        for target in backend.learned:
            oid=target['operation_native_id'];name='GTP:'+str(oid)
            journal.execute(name,lambda pending:backend.generate(target,pending));backend.refresh_dirty()
            observed=backend.outcome(target);generation.status_contract(observed,target,True)
            counts[oid]=deepcopy(observed['record_counts']);journal.verified(name,observed)
        r['generated']=backend.capture_snapshot('generated',full=True)
        verify_route(baseline['binding'],r['generated']['binding'],loaded['configuration_tool'],IDS,counts)
        verify_parameters(baseline['parameters'],r['generated']['parameters'],wanted)
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
        r['saved_cl']=backend.export('saved',r['saved']['binding']);r['protected_cl']=verify_protected_cl(r['before_cl_reference'],r['saved_cl']);r['cutcom_review']=cl.verify_no_new_cutcom(r['saved_cl']);r['saved_actual_four_paths_exported']=True;backend.finish()
        r['replacement_checkpoint_context']=dict(source_sha256=r['saved_source_sha256'],prior_source_sha256=r['source_sha256'],tool_creation_pin=deepcopy(r['tool_creation_pin']),
          document=deepcopy(r['source_transition']['document']),configuration=deepcopy(loaded['guide_parameters']['configuration']),saved_snapshot=deepcopy(r['saved']),
          saved_cl=deepcopy(r['saved_cl']),learned_targets=deepcopy(backend.learned),tool_dimensions=deepcopy(wanted),tool_catalogue_ids=deepcopy(loaded['tool_catalogue_ids']),
          operation_order=list(OLD+IDS),generated_ids=list(cl.OLD)+list(IDS),process_id=r['request']['process_id'],ownership=deepcopy(r['ownership']),persistence_after_reopen_verified=False)
        r.update(status='saved_replacement_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        try:journal.persist()
        except Exception as exc:r['receipt_write_error']=_error(exc);r['continuation_ready']=False
    return r


MILL_MAP={'MillToolType':'type_raw','MillToolSubType':'subtype_raw','EffCutlength':'effective_cutting_length_native','ShankDia':'shank_diameter_native',
 'OverallLen':'overall_length_native','EndRadius':'end_radius_native','NoOfFlutes':'flute_count_raw','ShoulderLength':'shoulder_length_native',
 'MillToolShankType':'shank_type_raw','ShoulderDia':'shoulder_diameter_native','ShankLength':'shank_length_native'}
HOLDER_MAP={'GetHolderShape':'shape','GetHolderId':'holder_id_raw','GetHolderNumber':'number','GetName':'name','GetHolderTopDia':'top_diameter_native',
 'GetHolderBottomDia':'bottom_diameter_native','GetHolderOverallLength':'overall_length_native','GetHolderBottomLength':'bottom_length_native',
 'GetProtrusion':'holder_protrusion_native'}


FACTORY_ONLY_NATIVE_PHASE={
    'sw_cam_long_cut_tool_definition.py',
    'sw_cam_neck_tool_candidate.py',
    'sw_cam_taper_tool_candidate.py',
}


def partition_native_pins(pins, checkpoint_pins):
    retired=[v for v in pins if Path(v['path']).name in FACTORY_ONLY_NATIVE_PHASE]
    names=[Path(v['path']).name for v in retired]
    require(len(names)==len(set(names)) and set(names)==FACTORY_ONLY_NATIVE_PHASE,
        'Exact three completed factory-only dependency roles required')
    live=[v for v in pins if Path(v['path']).name not in FACTORY_ONLY_NATIVE_PHASE]
    require(1<=len(live)<=64,'Native dispatch guard supports at most64 active evidence pins')
    proof=common._merge(checkpoint_pins,retired)
    require(len(proof)<=320,'Bounded full historical proof closure required')
    return live,proof,dict(scope='DEEP_REPLACEMENT_NATIVE_PHASE_DEPENDENCY_PARTITION_V1',
        input_count=len(pins),live_count=len(live),proof_count=len(proof),
        shared_guard_maximum=64,shared_guard_modified=False,
        proof_checks='full content hashes before and after native phase',retired=deepcopy(retired))


def guard_constructor_preflight(p,loaded,typelib):
    from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
    expected=deepcopy(loaded['guide_parameters']['document'])
    require(common._key(expected['path'])==common._key(p['expected_document_path']),
        'Offline guard document must match the exact request')
    guard=ScopedCamDispatchGuard(None,typelib,process_id=p['process_id'],
        expected_document=expected,source_sha256=p['expected_source_sha256'],
        evidence_pins=loaded['pins'],verify_evidence=lambda:None,
        verify_owned_process=lambda:None,check_events=lambda:None)
    result=dict(scope='REAL_SHARED_GUARD_CONSTRUCTOR_PREFLIGHT_V1',
        guard_type=type(guard).__name__,native_calls=0,entered=False,
        live_pin_count=len(loaded['pins']),source_and_unique_files=len(guard._rows),
        constructor_verified=True)
    guard.__exit__(None,None,None)
    return result


def projection_from_creation(context):
    loaded=deepcopy(context['deep_loaded']);candidate=context['long_cut_tool_candidate'];checkpoint=context['long_cut_tool_checkpoint'];body=candidate['full_tool']
    require(body['geometry_read_complete']is True and body['profile_complete']is True,'Observed complete created tool body required')
    baseline=loaded['guide_parameters']['expected_parameters'];template=deepcopy(next(x['tool']for x in baseline['parameters']if x['operation_native_id']==330))
    generic=deepcopy(template['generic']);generic.update(deepcopy(checkpoint['generic']))
    for key,native in [('tool_type_raw','tool_type_raw'),('cut_diameter_native','cut_diameter_native'),('protrusion_native','tool_protrusion_native')]:
        require(type(body[native]) in (int,float) and math.isclose(body[native],generic[key],rel_tol=0.,abs_tol=1e-8),'Created observed generic field differs from qualified recipe')
        generic[key]=body[native]
    require(generic['native_id']==candidate['native_id']==body['tool_native_id'],'Created native tool ID mismatch')
    require(set(template['mill'])==set(MILL_MAP)and set(template['holder'])==set(HOLDER_MAP),'Exact native dimensions reader fields required')
    observe=writer.reader.pocket.rough.bounded_raw_observation
    template['generic']=generic;template['mill']={k:observe(body['mill_tool'][v])for k,v in MILL_MAP.items()};template['holder']={k:observe(body['holder'][v])for k,v in HOLDER_MAP.items()}
    loaded['configuration_tool']=generic;loaded['replacement_tool_dimensions']=template
    loaded['tool_catalogue_ids']=[row['native_id']for row in checkpoint['catalogue']]
    require(loaded['generated']['saved_cl']==checkpoint['saved_cl'],'Creation CL reference differs')
    pins=common._merge(context['pins'],[common._pin(__file__)])
    proof=common._merge(loaded['checkpoint_pins'],context['offline_export_proof_pins'])
    loaded['pins'],loaded['checkpoint_pins'],loaded['native_pin_partition']=partition_native_pins(pins,proof)
    for target in loaded['deep_targets']:
        target.update(tool_native_id=generic['native_id'],assigned_tool=deepcopy(generic),reference_tool_dimensions=deepcopy(template))
    loaded['created_saved_cl']=deepcopy(checkpoint['saved_cl'])
    loaded['tool_creation_context']=context
    return loaded


PARAMS={'process_id','expected_document_path','expected_source_sha256','tool_creation_receipt_path','tool_creation_receipt_sha256',
 'module_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}


def audit_interfaces(typelib,generated_pin):
    from ctypes import HRESULT, POINTER
    from comtypes.automation import IDispatch
    result=generation.audit(typelib,generated_pin)
    result.update(configuration=config.audit(typelib,generated_pin),compensation=writer.nc.audit(typelib,generated_pin))
    cls=config.rough.interface_class('ICWMillOperation',typelib,generated_pin)
    members=[x for x in cls._methods_ if x.name=='SetTool']
    require(len(members)==1,'One exact typed SetTool declaration required')
    member=members[0]
    require(member.restype is HRESULT and member.argtypes==(POINTER(IDispatch),) and len(member.paramflags)==1 and member.paramflags[0][0]==1,'Exact SetTool(IDispatch*) HRESULT ABI required')
    result['assignment']=dict(interface='ICWMillOperation',member='SetTool',dispid=int(member.idlflags[0]),native_calls=0)
    return result


def marker_path(p):
    return common.local_evidence_root()/('deep_long_tool_replace_'+group._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')


def prepare_request(request,*,creation_loader=None):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='replace_existing_deep_guide_tool','Exact replacement action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact replacement parameters required')
    require(p['acknowledgement']=='assign_existing_four_only_geometric_feeds_not_production_qualified','Explicit bounded replacement scope required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned process ID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute explicit path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
    require(p['module_sha256']==_file_hash(__file__),'Replacement module changed')
    if creation_loader is None:
        from scripts import sw_cam_long_cut_reconciliation as created
        creation_loader=created.load_completed
    context=creation_loader(p['tool_creation_receipt_path'],p['tool_creation_receipt_sha256'],process_id=p['process_id'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    loaded=projection_from_creation(context);baseline_contract(loaded)
    receipt_data,receipt_pin=authority.read_pin(p['tool_creation_receipt_path'],p['tool_creation_receipt_sha256'])
    require(receipt_data['saved_source_sha256']==p['expected_source_sha256']and receipt_data['process_id']==p['process_id'],'Creation source or owned process differs')
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current saved source changed')
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],[receipt_pin,common._pin(__file__)])
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,context['long_cut_tool_checkpoint']['registration']['clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in loaded['pins'],'Actual CAM typelib changed')
    abi=audit_interfaces(typelib,loaded['generated_pin']);p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['native_guard_preflight']=guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path'])
    marker=marker_path(p)
    outputs=[receipt,progress,marker,cl._fresh_path(p['saved_cl_path'])]
    protected={common._key(x['path'])for x in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(x)for x in outputs})==len(outputs),'Distinct replacement outputs required')
    for out in outputs:require(not out.exists()and not out.is_symlink()and common._key(out)not in protected,'Fresh nonaliased output and once marker required')
    for out in (receipt,progress,marker):require(out.parent.is_dir(),'Existing diagnostic parent required')
    return p,loaded,registration,typelib,abi,receipt,marker,receipt_pin


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,pin=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,tool_native_id=loaded['configuration_tool']['native_id'],existing_target_ids=list(IDS),protected_definitions=13,protected_paths=10,maximum_SetTool=4,maximum_GTP=4,maximum_Save=1,physical_cutting_conditions_qualified=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=authority.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=deepcopy(loaded['ownership']),
          tool_creation_pin=pin,interface_audit=abi,live_pins=deepcopy(loaded['pins']),checkpoint_pins=deepcopy(loaded['checkpoint_pins']),replacement_tool=deepcopy(loaded['replacement_tool_dimensions']))
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_backend(backend,journal,loaded)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args(argv)
    result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:result.get(k)for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified')is True or result.get('status')=='validated_offline'else 1


if __name__=='__main__':raise SystemExit(main())
