"""Configure four verified MILL guide definitions in one owned session.

Explicit settings only; no toolpath generation. Reuse the existing field ABI,
readers, journal and one-save protocol. A partial native attempt is not replayed.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import math, re
from scripts import sw_cam_guide_group_parameters as reader
from scripts import sw_cam_fresh_finish_recipe as finish
from scripts import sw_cam_pocket_rough_apply as rough
from scripts import sw_cam_ud14_save as save_core
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_rough_firstcut import require

definitions, guide, group, common = reader.definitions, reader.guide, reader.group, reader.common
SCOPE = 'VERIFIED_GUIDE_FOUR_CONFIGURATION_ONLY_V1'
PARAMS = reader.PARAMS | {'parameters_receipt_path','parameters_receipt_sha256','recipe_path','recipe_sha256'}
ROUGH_FIELDS = tuple((s[0],s[1],s[2],s[3],s[4]) for s in rough.FIELDS[:5]) + (
    ('side_allowance','ICWRghMillOp','SideAllow','SideAllow','property'),
    ('floor_allowance','ICWRghMillOp','GetZAllowance','SetZAllowance','scalar'),
    ('side_step','ICWRghMillOp','GetStepOver','SetStepover','pair'))
FINISH_FIELDS = finish.FIELDS + finish.SCOPE_FIELDS + (
    ('bottom_finish','ICWFinishMillOp','BottomFinOpt','BottomFinOpt','property'),)
FIXED_PAIRS = [(82,0),(82,1),(83,0),(83,1)]


def parameter_projection(row):
    return {k:deepcopy(v) for k,v in row.items() if k not in {
        'rough_diagnostic','startpoint_diagnostic','nc_diagnostic','finish_field_diagnostic',
        'protected_raw','tool_dimensions_reused'}}


def resolve_capture_reference(report,reference):
    require(type(reference) is dict and set(reference)=={'capture_index','capture_label','snapshot_sha256','operation_native_id'},
        'Exact compact capture reference required')
    index=reference['capture_index'];captures=report.get('captures',[])
    require(type(index) is int and 0<=index<len(captures),'Valid preserved capture index required')
    capture=captures[index]
    require(capture.get('label')==reference['capture_label'],'Preserved capture label changed')
    snapshot=dict(binding=deepcopy(capture['binding']),parameters=[parameter_projection(x) for x in capture['parameters']])
    require(group._digest(capture)==reference['snapshot_sha256'],'Preserved full snapshot digest changed')
    require(type(reference['operation_native_id']) is int and sum(x['operation_native_id']==reference['operation_native_id']
        for x in snapshot['parameters'])==1,'Referenced selected operation differs')
    return snapshot


def capture_reference(report,label,snapshot,oid):
    matches=[i for i,x in enumerate(report.get('captures',[])) if x.get('label')==label]
    require(len(matches)==1,'One preserved full snapshot required before verification')
    ref=dict(capture_index=matches[0],capture_label=label,snapshot_sha256=group._digest(report['captures'][matches[0]]),operation_native_id=oid)
    require(group.exact(resolve_capture_reference(report,ref),snapshot),'Stored snapshot differs from returned snapshot')
    return ref


def verify_capture_links(report):
    names=[str(oid)+':SetTool' for oid in report['configured_operation_ids']]
    require(len(names)==4,'Four configured tool captures required')
    for name in names:
        action=report['actions'][name]
        require(action.get('status')=='verified' and action.get('readback_verified') is True,'Tool action must be verified')
        oid=int(name.split(':')[0])
        require(action['observed']['operation_native_id']==oid
            and action['observed']['capture_label']=='after_tool_'+str(oid),'Tool action capture rebound')
        resolve_capture_reference(report,action['observed'])


def validate_recipe(recipe, selected):
    require(type(recipe) is dict and set(recipe)=={'schema_version','tool_native_id','rows'}
        and type(recipe['schema_version']) is int and recipe['schema_version']==1,
        'Exact explicit configuration recipe required')
    require(type(recipe['tool_native_id']) is int and recipe['tool_native_id']==273,
        'This qualified guide recipe uses existing tool273 only')
    require(type(recipe['rows']) is list and len(recipe['rows'])==4,'Exactly four recipe rows required')
    for wanted, target in zip(recipe['rows'],selected['targets']):
        require(type(wanted) is dict and set(wanted)=={'operation_native_id','feature_native_id','operation_type','fields'},
            'Exact configuration row keys required')
        for k in ('operation_native_id','feature_native_id','operation_type'):
            require(type(wanted[k]) is int and wanted[k]==target[k],'Explicit current target differs: '+k)
        specs=ROUGH_FIELDS if wanted['operation_type']==0 else FINISH_FIELDS
        require(type(wanted['fields']) is dict and set(wanted['fields'])=={s[0] for s in specs},
            'Explicit complete selected field values required')
        for spec in specs:
            value=wanted['fields'][spec[0]]
            if wanted['operation_type']==1 and spec in finish.FIELDS:
                reader.fields.checked_value(spec,value)
            elif spec[0] in {'gouge_check','bottom_finish'}: require(type(value) is bool,'Strict flag required')
            elif spec[0] in {'entry_type','lead_in_type','lead_out_type'}:
                require(type(value) is int and 0<=value<=4,'Bounded explicit enum value required')
            elif spec[4]=='pair':
                require(type(value) is list and len(value)==2 and type(value[0]) is bool
                    and type(value[1]) is float and math.isfinite(value[1]) and 0<=value[1]<=10,
                    'Rough pair is [bool, finite nonnegative double]')
            else: require(type(value) is float and math.isfinite(value) and 0<=value<=10,'Finite bounded scalar required')
        require(wanted['fields']['side_allowance']>=0,'Nonnegative side allowance required')
    return deepcopy(recipe)


def completed_parameters(observed, selected):
    require(observed.get('scope')==reader.SCOPE and observed.get('status')=='observed'
        and observed.get('phase')=='finished' and observed.get('readback_verified') is True
        and observed.get('parameter_read_complete') is True,'Complete actual parameter receipt required')
    require(not any(k in observed for k in ('issue','failed_phase','cleanup_issue','pin_issue')),
        'Partial read cannot authorize configuration')
    clean_events(observed)
    for k in ('mutation_attempted','save_attempted','GTP_attempted','automatic_retry'):
        require(observed.get(k) is False,'Read receipt contains a side effect')
    require(group.exact(observed['before'],selected['baseline'])
        and group.exact(observed['after'],observed['before']),'Actual binding changed')
    require(group.exact(observed['before_document'],selected['document'])
        and group.exact(observed['after_document'],selected['document']),'Actual document differs')
    require(group.exact(observed['configuration_before'],selected['configuration'])
        and group.exact(observed['configuration_after'],selected['configuration']),'Actual configuration differs')
    require(len(observed['parameters'])==4,'Four complete parameter rows required')
    for actual,target in zip(observed['parameters'],selected['targets']):
        require(actual.get('read_complete') is True and actual['operation_native_id']==target['operation_native_id']
            and actual['feature_native_id']==target['feature_native_id'],'Actual parameter target differs')
    return dict(binding=deepcopy(observed['before']),parameters=[parameter_projection(v) for v in observed['parameters']])


def verify_binding(initial,current,wanted_tool,changed):
    require(set(current)==set(initial),'Binding keys changed')
    require(group.exact(current['features'],initial['features'])
        and group.exact(current['operation_setups'],initial['operation_setups']),'Feature/setup changed')
    require(len(initial['operations'])==len(current['operations'])==13,'Exactly13 ordered definitions required')
    for old,new in zip(initial['operations'],current['operations']):
        expected=deepcopy(old)
        if old['native_id'] in changed: expected['assigned_tool']=deepcopy(wanted_tool)
        require(group.exact(expected,new),'Protected route or assignment changed: '+str(old['native_id']))


def verify_nc_levels(before,after):
    for name in ('nc','levels'):
        require(group.exact(before[name],after[name]),'Unrequested '+name+' change')


def verify_automatic_target(before,after):
    require(group.exact(before['levels'],after['levels']),'SetTool changed selected machining levels')
    if 'startpoints' in before:
        old,new=deepcopy(before['startpoints']),deepcopy(after['startpoints'])
        old.pop('entry_type');new.pop('entry_type')
        require(group.exact(old,new),'SetTool changed selected start point list or coordinates')


def field_value(row,spec):
    key=spec[0]
    if 'rough' in row:
        area={'entry_type':'entry','spiral_radius':'entry','spiral_pitch':'entry',
              'first_depth':'depth','subsequent_depth':'depth'}.get(key,'boundary')
        return row['rough'][area][spec[2]]['raw']
    if key in row['finish_fields']: return row['finish_fields'][key]
    if key=='gouge_check': return row['protected_finish']['gouge_check']
    if key=='lead_in_type': return row['protected_finish']['lead_types'][0]
    if key=='lead_out_type': return row['protected_finish']['lead_types'][1]
    if key=='bottom_finish': return row['finish']['BottomFinOpt']['raw']
    raise ValueError('Unmapped configured field')


def protected_parameters(row):
    """Remove only reviewed setter fields and their established reader aliases."""
    result=deepcopy(row)
    if 'rough' in result:
        for spec in ROUGH_FIELDS:
            area={'entry_type':'entry','spiral_radius':'entry','spiral_pitch':'entry',
                'first_depth':'depth','subsequent_depth':'depth'}.get(spec[0],'boundary')
            result['rough'][area].pop(spec[2])
        for name in ('FirstDepthAmt','SbsqDepthAmt'):result['rough']['depth'].pop(name)
        result['startpoints'].pop('entry_type')
    else:
        result.pop('finish_fields')
        for name in ('SideAllow','SideCutAmt','FinalSideCutAmt','SpringPass','FirstDepthCut','MaxDepthCut',
                'FinalDepthCut','OverridePrevAllow','GetPreviousAllowance','PerimeterPassType','BottomFinOpt'):
            result['finish'].pop(name)
        result['protected_finish'].pop('gouge_check');result['protected_finish'].pop('lead_types')
        for side in ('lead_in','lead_out'):
            for name in ('LeadType','ArcAngle','GetArcRadius2','GetLeadOverlap2','GetLeadAmt2','GetIsSameLeadinout'):
                result['leads'][side].pop(name)
    return result


def verify_configured(initial,actual,recipe,wanted_tool):
    ids={r['operation_native_id'] for r in recipe['rows']}
    verify_binding(initial['binding'],actual['binding'],wanted_tool,ids)
    require(len(actual['parameters'])==4,'Four full parameter rows required')
    for before,after,target in zip(initial['parameters'],actual['parameters'],recipe['rows']):
        require(after['operation_native_id']==target['operation_native_id'] and after['read_complete'] is True,
            'Configured target readback differs')
        verify_nc_levels(before,after)
        require(group.exact(after['tool']['generic'],wanted_tool),'Final tool identity differs')
        for spec in ROUGH_FIELDS if target['operation_type']==0 else FINISH_FIELDS:
            require(group.exact(field_value(after,spec),target['fields'][spec[0]]),
                'Full configuration readback differs: '+spec[0])


class ConfigurationContext(group.GroupContext):
    def files(self):
        super().files()
        require(1<=len(self.loaded['configuration_pins'])<=4,'Bounded configuration authority required')
        common._check(self.loaded['configuration_pins'])


class ConfigurationJournal(group.GroupJournal):
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],
            recipe_sha256=r['recipe_sha256'],receipt_path=str(self.receipt),status=r['status'],
            phase=r['phase'],actions=deepcopy(r['actions']),
            native_dispatch_pending=r.get('native_dispatch_pending',False),automatic_replay=False)


class NativeBackend(reader.NativeBackend):
    def __init__(self,loaded,args,sw,clsid,typelib_path,report,persist):
        super().__init__(loaded,args,sw,clsid,typelib_path,report,persist)
        self.ctx=ConfigurationContext(loaded,dict(args,**loaded['ids']),sw,typelib_path,None,self.events,loaded['state'])
        self.ctx.expected_document=deepcopy(loaded['guide_parameters']['document'])
        self.doc=None

    def batch(self,doc,progress,state,binding):
        return reader.ParameterReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
            process_id=self.args['process_id'],expected_document=self.ctx.identity(),
            source_sha256=self.ctx.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events,
            retained_objects=(doc,),verify_retained_binding=binding,max_native_calls=reader.MAX_CALLS,
            progress=progress,progress_state=state)

    def capture_parameters(self,label):
        self.boundary()
        with self.ctx.guard() as g:
            self.doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3')
            self.save_app=g.typed(self.ctx.app,'ICWApp')
        expected=self.loaded['guide_parameters']['configuration']
        def binding(): require(group.exact(self.configuration(self.doc),expected),'CAM configuration changed')
        binding();state=dict(member='',returned=False,read_index=0)
        out=dict(label=label,phase=label)
        self.report.setdefault('captures',[]).append(out);self.persist()
        progress_path=str(Path(self.args['progress_path']).with_name(Path(self.args['progress_path']).stem+'.'+label+'.json'))
        protected=[self.args['expected_document_path'],self.args['receipt_path']]+[p['path'] for p in self.loaded['pins']+self.loaded['configuration_pins']]
        with reader.pocket.journal.ReadProgressJournal(full_persist=self.persist,progress_path=progress_path,
                describe=lambda:dict(state,phase=out['phase']),max_updates=4096,protected_paths=protected) as progress:
            batch=self.batch(self.doc,progress.read,state,binding)
            try:
                with batch:
                    before,handles=definitions.read_current_binding(self.doc,read=batch.read,typed=batch.typed)
                    targets=deepcopy(self.loaded['guide_parameters']['targets'])
                    byid={r['native_id']:r for r in before['operations']}
                    for target in targets: target['assigned_tool']=deepcopy(byid[target['operation_native_id']]['assigned_tool'])
                    reader.read_parameters(self.doc,handles,targets,batch,out,progress.read)
                    after,_=definitions.read_current_binding(self.doc,read=batch.read,typed=batch.typed)
                    require(group.exact(before,after),'Route changed during full readback')
                    out['binding']=after
                batch.require_complete();progress.complete()
            finally:out['read_batch']=batch.summary();self.persist()
        binding()
        return dict(binding=deepcopy(out['binding']),parameters=[parameter_projection(x) for x in out['parameters']])

    def target(self,g,row):
        oid,fid=row['operation_native_id'],row['feature_native_id']
        found=g.read(self.doc,'GetCWObjectFromID',3,oid)
        require(type(found) in (list,tuple) and len(found)==2 and found[1] is True,'Exact target lookup required')
        raw=found[0];op=g.typed(raw,'ICWOperation');mill=g.typed(raw,'ICWMillOperation')
        require(_object_id(self.doc,op,g.read)==oid and g.read(op,'Suppressed') is False
            and g.read(mill,'OpernType')==row['operation_type'],'Target identity/type changed')
        links=[_object_id(self.doc,x,g.read) for x in _items(g.read(op,'IGetAllFeatures'),g.typed,g.read,2)]
        require(links==[fid],'Target feature changed')
        found=g.read(self.doc,'GetCWObjectFromID',1,fid)
        require(type(found) in (list,tuple) and len(found)==2 and found[1] is True,'Exact feature lookup required')
        return raw,found[0]

    def typed_field(self,g,obj,name):
        cls=finish.finish.interface_class(name,self.typelib_path,self.loaded['generated_pin'])
        value=g.read(obj,'QueryInterface',cls)
        require(value is not None and bool(value) and isinstance(value,cls),'Exact field interface required')
        return value

    def owner(self,g,row,spec):
        raw,feature=self.target(g,row);name=spec[1]
        if name in ('lead_in','lead_out'):
            owner=self.typed_field(g,raw,'ICWFinishMillOp')
            raw=g.read(owner,'IGetLeadin' if name=='lead_in' else 'IGetLeadout',feature)
            require(raw is not None and bool(raw),'Nonnull feature lead required');name='ICWLeadInOut'
        return self.typed_field(g,raw,name),feature,name

    def field(self,row,spec):
        with self.ctx.guard() as g:
            owner,feature,_=self.owner(g,row,spec)
            value=g.read(owner,spec[2],*([feature] if spec[4]=='feature' else []))
        return list(value) if type(value) is tuple else value

    def set_field(self,row,spec,value,pending):
        require(spec in (ROUGH_FIELDS if row['operation_type']==0 else FINISH_FIELDS),'Setter outside explicit recipe')
        with self.ctx.guard() as g:
            owner,feature,name=self.owner(g,row,spec)
            if spec[4]=='property':
                raw=getattr(owner,'_'+name+'__com__set_'+spec[3]);call=lambda:raw(value)
            else:
                args=[feature,value] if spec[4]=='feature' else list(value) if spec[4] in ('pair','depth_pair') else [value]
                call=lambda:_member(owner,spec[3],*args)
            return g.dispatch_once(call,persist_pending=pending)

    def assign(self,row,pending):
        from comtypes.automation import IDispatch
        with self.ctx.guard() as g:
            raw,_=self.target(g,row)
            part=g.typed(self.doc,'ICWPartDoc');machine=g.typed(g.read(part,'IGetMachine'),'ICWMachine')
            crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4')
            tools=_items(g.read(crib,'GetAllTools'),g.typed,g.read,64)
            ids=[_object_id(self.doc,x,g.read) for x in tools]
            require(ids==[x['native_id'] for x in self.loaded['neck_tool_checkpoint']['catalogue']]
                and ids.count(273)==1,'Qualified saved catalogue changed')
            tool=g.typed(tools[ids.index(273)],'ICWTool');wanted=self.loaded['configuration_tool']
            require(g.read(tool,'ToolType')==wanted['tool_type_raw']
                and g.read(tool,'CutDiameter')==wanted['cut_diameter_native']
                and group.exact(g.read(tool,'Protrusion'),wanted['protrusion_native']),'Qualified tool changed')
            dispatch=g.read(tool,'QueryInterface',IDispatch);mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'SetTool',dispatch),persist_pending=pending)


def audit(typelib,generated):
    from ctypes import POINTER,c_double
    from ctypes.wintypes import VARIANT_BOOL
    out=dict(rough=rough.audit_recipe(typelib,generated),finish=finish.audit(typelib,generated),extra=[])
    cls=rough.interface_class('ICWRghMillOp',typelib,generated)
    for name,ident,args,flags in (('_get_SideAllow',19,(POINTER(c_double),),(10,)),
        ('_set_SideAllow',19,(c_double,),(1,)),('GetStepOver',20,(POINTER(VARIANT_BOOL),POINTER(c_double)),(2,2)),
        ('SetStepover',21,(VARIANT_BOOL,c_double),(1,1)),('GetZAllowance',51,(POINTER(c_double),),(10,)),
        ('SetZAllowance',52,(c_double,),(1,))):
        rows=[v for v in cls._methods_ if v.name==name];require(len(rows)==1,'Exact rough declaration required')
        rough.require_abi(rows[0],ident,args,flags);out['extra'].append(dict(interface='ICWRghMillOp',member=name,dispid=ident))
    require(hasattr(POINTER(cls),'_ICWRghMillOp__com__set_SideAllow'),'Raw HRESULT setter required')
    return out


def run_backend(backend,journal,loaded):
    require(not journal.created and not journal.claimed,'Group cannot be reentered; preserve original evidence')
    r=journal.report;recipe=loaded['configuration_recipe'];initial=loaded['configuration_initial'];wanted=loaded['configuration_tool']
    r.update(status='error',phase='preflight',actions={},mutation_attempted=False,native_dispatch_pending=False,
        native_call_attempted=False,native_call_returned=False,readback_verified=False,
        GTP_attempted=False,save_attempted=False,model_saved=False,automatic_retry=False,production_qualified=False,
        physical_cutting_conditions_qualified=False,toolpath_bytes_compared=False,configured_operation_ids=[],
        persistence_after_reopen_verified=False,continuation_ready=False)
    try:
        journal.create();backend.start();r['before']=backend.capture_parameters('before')
        require(group.exact(r['before'],initial),'Fresh actual parameters differ from pinned baseline');journal.persist()
        changed=set();previous=deepcopy(r['before'])
        # Assign every tool first. Each automatic default update is observed before
        # any explicit field configuration; nonselected rows must remain exact.
        for target in recipe['rows']:
            oid=target['operation_native_id'];label=str(oid)+':SetTool'
            journal.execute(label,lambda pending:backend.assign(target,pending))
            backend.refresh_dirty();changed.add(oid)
            aftertool=backend.capture_parameters('after_tool_'+str(oid))
            verify_binding(initial['binding'],aftertool['binding'],wanted,changed)
            for old,new in zip(previous['parameters'],aftertool['parameters']):
                if old['operation_native_id']!=oid:
                    require(group.exact(old,new),'SetTool changed a nonselected operation parameter')
                else:
                    verify_automatic_target(old,new)
                    r.setdefault('automatic_nc_changes',[]).append(dict(operation_native_id=oid,
                        before=deepcopy(old['nc']),after=deepcopy(new['nc']),
                        changed=not group.exact(old['nc'],new['nc']),production_qualified=False))
            journal.verified(label,capture_reference(r,'after_tool_'+str(oid),aftertool,oid));previous=aftertool
        r['after_tools']=deepcopy(previous);journal.persist()
        for target in recipe['rows']:
            oid=target['operation_native_id']
            # Read the actual current field before every explicit setter. Earlier
            # setters can legitimately update aliases within this selected operation.
            for spec in ROUGH_FIELDS if target['operation_type']==0 else FINISH_FIELDS:
                value=target['fields'][spec[0]];label=str(oid)+':'+spec[0]
                old=backend.field(target,spec)
                r.setdefault('fields_before',{})[label]=deepcopy(old);journal.persist()
                if group.exact(old,value):
                    journal.entry(label);journal.verified(label,dict(already_satisfied=True,value=old));continue
                journal.execute(label,lambda pending,spec=spec,value=value:backend.set_field(target,spec,value,pending))
                backend.refresh_dirty();actual=backend.field(target,spec)
                require(group.exact(actual,value),'Direct selected field readback differs');journal.verified(label,actual)
            r['configured_operation_ids'].append(oid);journal.persist()
        r['configured']=backend.capture_parameters('configured');verify_configured(r['after_tools'],r['configured'],recipe,wanted)
        for old,new in zip(r['after_tools']['parameters'],r['configured']['parameters']):
            require(group.exact(protected_parameters(old),protected_parameters(new)),
                'Explicit setters changed an unselected parameter')
        verify_capture_links(r)
        r['configuration_readback_verified']=True;journal.persist()
        r['save_stage']={};journal.entry('SaveActiveDocument');r['save_attempted']=True;journal.persist()
        expected=deepcopy(r['configured'])
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(expected)
            actual=backend.capture_parameters('saved');verify_configured(r['after_tools'],actual,recipe,wanted);r['saved']=actual;return actual
        def verify(value):require(group.exact(value,expected),'Save changed fully observed configuration')
        def save():
            value=backend.save();entry=r['actions']['SaveActiveDocument']
            require(entry['attempted'] is True and entry.get('native_dispatch_pending') is True,'Save bypassed durable pending')
            entry.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value))
            r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved bytes did not change')
            r['saved_source_sha256']=value;r['model_saved']=True;journal.persist();return value
        save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256']);verify_capture_links(r);backend.finish()
        r['saved_checkpoint_context']=dict(process_id=r['request']['process_id'],
            ownership=deepcopy(r['ownership']),document=deepcopy(r['source_transition']['document']),
            source_sha256=r['saved_source_sha256'],configuration=deepcopy(loaded['guide_parameters']['configuration']),
            snapshot_key='saved',snapshot_sha256=group._digest(r['saved']),
            prior_source_sha256=r['source_sha256'],prior_parameter_receipt_pin=deepcopy(loaded['configuration_pins'][0]),
            persistence_after_reopen_verified=False)
        r.update(status='saved_configuration_no_toolpath',phase='finished',readback_verified=True,model_saved=True,continuation_ready=True)
    except Exception as exc:
        r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:
            backend.close()
            if getattr(backend,'session',None) is not None:
                backend.events(False)
                r['cleanup_session_active']=backend.session_active
                require(backend.session_active is False,'CAM subscriber remained active after close')
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r


def prepare_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='configure_guide_definitions',
        'Exact group configuration action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact group parameter keys required')
    require(p['module_sha256']==_file_hash(__file__),'Configuration module changed')
    rp={k:v for k,v in p.items() if k in reader.PARAMS};rp['module_sha256']=_file_hash(reader.__file__)
    _,loaded,registration,typelib,reader_audit,receipt=reader.prepare_request(dict(action='read_guide_actual_parameters',params=rp))
    actual,pin=read_pin(p['parameters_receipt_path'],p['parameters_receipt_sha256'])
    require(actual['module_pin']==common._pin(reader.__file__),'Executed full reader changed')
    for key in reader.PARAMS-{'module_sha256','receipt_path','progress_path'}:
        require(group.exact(actual['request'][key],rp[key]),'Actual read lineage differs: '+key)
    require(group.exact(actual['ownership'],loaded['ownership']),'Actual read owner changed')
    loaded['configuration_initial']=completed_parameters(actual,loaded['guide_parameters'])
    recipe,recipe_pin=read_pin(p['recipe_path'],p['recipe_sha256'])
    loaded['configuration_recipe']=validate_recipe(recipe,loaded['guide_parameters'])
    tool=next((v['assigned_tool'] for v in loaded['state']['operations'] if v['native_id']==320),None)
    require(type(tool) is dict and tool['native_id']==273,'Saved qualified finish320 tool273 required')
    loaded['configuration_tool']=deepcopy(tool)
    require(loaded['configuration_tool']['cut_diameter_native']==2.0,'Exact qualified D2 tool required')
    loaded['configuration_pins']=[pin,recipe_pin,common._pin(save_core.__file__),common._pin(finish.finish.__file__)]
    loaded['pins']=common._merge(loaded['pins'],[common._pin(__file__)])
    require(len(loaded['pins'])<=64,'Bounded existing live closure exceeded')
    common._check(loaded['configuration_pins']);common._check(loaded['pins'])
    interface_audit=audit(typelib,loaded['generated_pin'])
    marker=common.local_evidence_root()/('guide_configuration_'+group._digest(dict(scope=SCOPE,
        source=common._key(p['expected_document_path']),sha256=p['expected_source_sha256']))+'.json')
    forbidden={common._key(x['path']) for x in loaded['configuration_pins']+loaded['pins']}
    require(not marker.exists() and not marker.is_symlink() and common._key(marker) not in forbidden
        and common._key(receipt) not in forbidden and common._key(marker)!=common._key(receipt),
        'Fresh nonaliased group output/marker required')
    return p,loaded,registration,typelib,interface_audit,receipt,marker


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,recipe=loaded['configuration_recipe'],
        live_pin_count=len(loaded['pins']),configuration_pin_count=len(loaded['configuration_pins']),interface_audit=abi)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['configuration_pins']);common._check(loaded['pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),ownership=loaded['ownership'],
            source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],recipe_sha256=p['recipe_sha256'],
            recipe=loaded['configuration_recipe'],live_pins=loaded['pins'],configuration_pins=loaded['configuration_pins'],interface_audit=abi)
        journal=ConfigurationJournal(report,receipt,marker)
        backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return run_backend(backend,journal,loaded)
