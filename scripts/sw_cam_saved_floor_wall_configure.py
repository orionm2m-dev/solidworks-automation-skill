"""Configure only a source-bound Rough-floor/Finish-wall pair; no generation."""
from copy import deepcopy
from scripts import sw_cam_floor_wall_configuration_recipe as recipe_core
from scripts import sw_cam_current_circular_authority as circular
require=recipe_core.require
exact=recipe_core.exact
SCOPE='SAVED_FLOOR_WALL_CONFIGURATION_V1'


def expected_configuration_state(before,recipe,candidate,after_targets):
    out=deepcopy(before);rows=recipe['rows'];ids=[r['operation_native_id']for r in rows]
    require(len(ids)==2 and len(set(ids))==2 and len(after_targets)==2,'Exactly two selected operation identities required')
    cid=candidate['generic']['native_id'];pb=out['parameter_batch'];require(exact(pb['candidate_tool'],candidate),'Current shared candidate profile differs')
    for request,target in zip(rows,after_targets):
        matches=[r for r in out['operations']if r['native_id']==request['operation_native_id']];require(len(matches)==1 and target['operation_native_id']==request['operation_native_id']and target['tool_native_id']==cid,'Exact selected route membership required');row=matches[0]
        require(row['mill_operation_type']==request['operation_kind']and row['linked_feature_ids']==[request['feature_native_id']]and row['assigned_tool']['native_id']==request['expected_tool_native_id']and request['existing_tool_native_id']==cid,'Original selected binding differs')
        row['assigned_tool']=deepcopy(candidate['generic'])
    consumers=[r['native_id']for r in out['operations']if r['assigned_tool']['native_id']==cid]
    require(set(pb['candidate_consumer_ids'])<=set(consumers)and set(consumers)-set(pb['candidate_consumer_ids'])<=set(ids),'Only selected candidate consumers may grow')
    pb['candidate_consumer_ids']=consumers
    for target in after_targets:
        oid=target['operation_native_id'];nc=target['modes']['nc']
        pb['candidate_consumers'][str(oid)]=dict(operation_native_id=oid,assigned_tool_native_id=cid,read_complete=True,feeds_compensation={k:deepcopy(nc[k])for k in('GetSpndlSpeed','XYFeed','GetCNCComp','GetTlpComp')},physical_units_qualified=False,cutting_conditions_qualified=False,tool_defaults_read=False,full_parameters_read=False)
    require(set(pb['candidate_consumers'])=={str(x)for x in consumers},'Exact candidate consumer map required')
    return out


def verify_full_configuration(before,after,recipe,candidate,before_targets,after_targets,before_draft,after_draft):
    selected=[next(r for r in before['operations']if r['native_id']==row['operation_native_id'])for row in recipe['rows']]
    recipe_core.validate_recipe(recipe,before_targets,selected,candidate)
    require(len(after_targets)==2,'Two actual after target observations required')
    for a,b,row in zip(before_targets,after_targets,recipe['rows']):recipe_core.verify_observation_delta(a,b,row)
    require(exact(before_draft,after_draft)and before_draft['operation_native_id']not in{r['operation_native_id']for r in recipe['rows']},'Retained draft witness must remain exact and unselected')
    expected=expected_configuration_state(before,recipe,candidate,after_targets);observed=deepcopy(after)
    for state in(expected,observed):
        for key in('document','sketch_state'):require(type(state[key]['needs_save'])is bool,'Strict dirty state required');state[key]['needs_save']=False
    require(circular.circular_state_equal(expected,observed),'Configuration changed a protected operation, path, feature, tool, NC or geometry')
    return dict(selected_operation_ids=[r['operation_native_id']for r in recipe['rows']],protected_operation_count=len(before['operations'])-2,protected_generated_operation_count=sum(r['toolpath_generated']for r in before['operations']),protected_native_records=sum(sum(r['toolpath_record_counts'])for r in before['operations']),shared_candidate_unchanged=True,retained_draft_unchanged=True,full_captured_configuration_verified=True,geometry_qualified=False,production_qualified=False)

from pathlib import Path
from contextlib import contextmanager
import math,re
from ctypes import HRESULT,POINTER,c_double,c_long
from ctypes.wintypes import VARIANT_BOOL
from comtypes.automation import IDispatch
from scripts import sw_cam_saved_finish_pair_read as reader
from scripts import sw_cam_append_finish_definitions as base
from scripts import sw_cam_append_floor_wall as mixed_producer
from scripts import sw_cam_fresh_finish_recipe as finish_setters
from scripts import sw_cam_chamfer_generate as depth_setters
from scripts.sw_cam_current_circular_context import NativeCircularContext
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _member,_error
from scripts.sw_cam_mill_inventory import _items
writer=base.writer
KEYS=reader.KEYS|{'read_receipt_path','read_receipt_sha256','recipe_path','recipe_sha256'}


def load_read_authority(v):
    require(type(v)is dict and set(v)==KEYS,'Exact mixed configuration request required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Qualification only required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact owner required')
    for k,value in v.items():
        if k.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
        if k.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute paths required')
    source=Path(v['expected_document_path']);require(source.is_file()and not source.is_symlink()and source.suffix.lower()=='.sldprt'and _file_hash(source)==v['expected_source_sha256'],'Exact clean source file required')
    observed,op=read_pin(v['read_receipt_path'],v['read_receipt_sha256'])
    require(observed.get('scope')==reader.SCOPE and observed.get('status')=='review_required'and observed.get('phase')=='finished','Completed selected read required')
    for k in('readback_verified','source_unchanged','runtime_unchanged','read_only'):require(observed.get(k)is True,'Missing completed read fact: '+k)
    for k in('mutation_attempted','save_attempted','GTP_attempted','GOP_attempted','parameter_setter_attempted'):require(observed.get(k)is False,'Read authority mutated state')
    require(not any(k in observed for k in('issue','failed_phase','runtime_error','cleanup_error')),'Unresolved read failure');clean_events(observed)
    require(exact(observed['before'],observed['after'])and observed['before'].get('capture_complete')is True,'Two complete equal missing-field captures required')
    for k in reader.KEYS-{'receipt_path'}:require(exact(observed['request'][k],v[k]),'Read/current binding differs: '+k)
    require(reader.ancestry.common.same_path(observed['receipt_path'],op['path']),'Read receipt path differs')
    data=reader.load_completed(v);require(observed['authority_pin']==data['receipt_pin'],'Completed append pin differs')
    for pin in observed['evidence_pins']:reader.ancestry.common.direct(pin)
    require(observed['before']['inventory']==reader.finish.inventory_projection(data['state']),'Read operation table differs')
    targets=[recipe_core.compact_target(t)for t in observed['before']['targets']]
    require([t['operation_native_id']for t in targets]==[r['native_id']for r in data['receipt']['new_operations']],'Read selected pair differs')
    recipe,rp=read_pin(v['recipe_path'],v['recipe_sha256']);candidate=data['state']['parameter_batch']['candidate_tool'];recipe_core.validate_recipe(recipe,targets,data['receipt']['new_operations'],candidate)
    for row in recipe['rows']:
        changes={c['field']:c for c in row['changes']}
        require(set(('link_to_tool','spindle','xy_feed','leadin_feed'))<=set(changes),'Explicit independent NC writes required')
        require(changes['link_to_tool']['expected']is True and changes['link_to_tool']['new']is False,'Unlink before tool assignment required')
        require(row['expected_tool_native_id']!=row['existing_tool_native_id'],'Explicit distinct existing tool assignment required')
    req=data['receipt']['request'];prior,pp=read_pin(req['revision_receipt_path'],req['revision_receipt_sha256']);oid=prior['operation_native_id'];rows=prior['postCL']['expected_generated_operations']
    bound=base.binding.bind_completed_revision(pp,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=data['receipt']['source_before_sha256'],selected_operation_ids=[oid],protected_operation_ids=[r['operation_native_id']for r in rows if r['operation_native_id']!=oid],expected_generated_operations=rows,marker_pin=dict(path=req['revision_marker_path'],sha256=req['revision_marker_sha256']),writer_pin=dict(path=writer.__file__,sha256=_file_hash(writer.__file__)),verify_current_source=False)
    lineage=base.lineage.load_context_lineage(prior,bound);lineage['state']=deepcopy(data['state'])
    pins=data['pins']+[op,rp]+observed['evidence_pins']+[dict(path=p,sha256=_file_hash(p))for p in(__file__,recipe_core.__file__,recipe_core.finish.__file__,reader.__file__,base.lineage.__file__,finish_setters.__file__,depth_setters.__file__)]
    unique={}
    for pin in pins:
        key=str(Path(pin['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==pin['sha256'],'Conflicting immutable evidence');unique[key]=pin
    return dict(state=deepcopy(data['state']),authority=data,read_receipt=observed,read_pin=op,targets=targets,recipe=recipe,recipe_pin=rp,candidate=deepcopy(candidate),draft=deepcopy(data['receipt']['draft_saved']),writer_receipt=prior,lineage=lineage,pins=list(unique.values()))


def validate(v):
    data=load_read_authority(v);out=Path(v['receipt_path']);source=Path(v['expected_document_path'])
    marker=source.parent/('configure_mill_pair_'+_digest(dict(scope=SCOPE,source=str(source.resolve()).casefold(),sha=v['expected_source_sha256'],recipe_sha256=v['recipe_sha256']))+'.json')
    protected={source.resolve(),*(Path(p['path']).resolve()for p in data['pins'])}
    require(out.parent.is_dir()and out.suffix.lower()=='.json'and not out.exists()and not out.is_symlink()and not marker.exists()and not marker.is_symlink(),'Fresh receipt and unused exact configuration marker required')
    require(out.resolve()!=marker.resolve()and out.resolve()not in protected and marker.resolve()not in protected,'Output/evidence alias forbidden');data.update(marker=marker,output=out);return data


def verify_assignment(before,after,row):
    """Tool assignment may refresh only three explicitly rewritten feed scalars."""
    expected=deepcopy(before);expected['tool_native_id']=row['existing_tool_native_id'];expected['modes']['tool_native_id']=row['existing_tool_native_id']
    for key in('GetSpndlSpeed','XYFeed'):
        value=after['modes']['nc'][key];require(type(value)is float and math.isfinite(value)and value>0,'Positive refreshed feed required');expected['modes']['nc'][key]=value
    value=after['modes']['nc']['leadin_feed'];recipe_core.finish.checked(recipe_core.finish.FIELDS['leadin_feed'],value);expected['modes']['nc']['leadin_feed']=deepcopy(value)
    require(after['modes']['nc']['LinkToTool']is False and exact(expected,after),'Tool assignment changed an unsupported parameter or NC mode')
    return dict(observed_feed_refresh={k:deepcopy(after['modes']['nc'][k])for k in('GetSpndlSpeed','XYFeed','leadin_feed')},supported_assignment_delta_verified=True)


def preflight(tlb):
    writer._abi(tlb);base.append.save_abi(tlb);reader.preflight(tlb)
    # Finish setter contracts are reused without any lead-object invocation.
    classes={}
    for name in ('ICWFinishMillOp','ICWFinishMillOp2','ICWFinishMillOp3','ICWMillOperation3'):
        classes[name]=base._interface_class(name,tlb)
    from scripts.sw_cam_saved_finish_pair_recipe import FIELDS
    used=set(FIELDS)-{'bottom_finish','link_to_tool','spindle','xy_feed','leadin_feed'}
    for key in used:
        spec=FIELDS[key];cls=classes[spec.interface];name=('_set_'+spec.setter)if spec.mode=='property'else spec.setter
        methods=[m for m in cls._methods_ if m.name==name];require(len(methods)==1 and methods[0].restype is HRESULT,'Exact HRESULT setter required: '+key)
        m=methods[0];value_type=VARIANT_BOOL if spec.kind=='bool'else c_long if spec.kind in('enum','count')else c_double
        args=(POINTER(IDispatch),value_type)if spec.mode=='feature'else(c_double,VARIANT_BOOL)if spec.mode=='depth_pair'else(value_type,)
        require(m.argtypes==args,'Typed setter arguments differ: '+key)
    return dict(fixed_registry_verified=True,native_calls=0,lead_objects_used=False)


class Context(base.AppendContext):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        super().__init__(sw,clsid,tlb,v,data,report,persist,runtime_check)
        self.config=data;self.expected_route=deepcopy(data['state']);self._native_read_limit=20000
        self.data['recovery']={'expected_state':deepcopy(data['state'])}
    def typed(self,raw,name):
        if name=='ICWNCParam4':return self._typed_nc4(raw)
        return super().typed(raw,name)
    def guarded_typed(self,guard,raw,name):
        if name=='ICWNCParam4':return self._typed_nc4(raw,guard)
        return guard.typed(raw,name)
    def generate(self,*a,**k):raise ValueError('Configuration never generates')
    def insert(self,*a,**k):raise ValueError('Configuration never inserts')
    def capture(self,label,partial):
        self.append_plan=dict(self.config,state=self.expected_route)
        ids=[r['native_id']for r in self.expected_route['operations']if r['assigned_tool']['native_id']==self.v['candidate_tool_native_id']]
        try:
            state=NativeCircularContext.capture(self,label,ids);self.last_document=deepcopy(state['document']);return state
        finally:partial.clear();partial.update(deepcopy(self.report.get(label,{})));self.persist()
    def _capture_readonly(self,label,*args,**kwargs):
        state=super()._capture_readonly(label,*args,**kwargs)
        state['cutting_context']=self.read_cutting()
        targets=[self.observe_target(row)for row in self.config['recipe']['rows']]
        draft=self.observe_draft();self.report.setdefault('target_observations',{})[label]=targets;self.report.setdefault('draft_observations',{})[label]=draft;self.persist();return state
    @contextmanager
    def selected_snapshot(self,label):
        require(not getattr(self,'_capture_pin_scope',False),'No nested selected snapshot')
        self.boundary();episode=dict(label=label,entry_verified=True,exit_verified=False,nested_checks_deferred=0);self.report.setdefault('capture_pin_checks',[]).append(episode);self._capture_pin_episode=episode;self._capture_pin_scope=True
        try:yield
        finally:self._capture_pin_scope=False;self._capture_pin_episode=None;self.boundary();episode['exit_verified']=True;self.persist()
    def target(self,row,read,typed):
        doc=self.native['doc'];found=read(doc,'GetCWObjectFromID',3,row['operation_native_id']);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact selected lookup required');raw=found[0];op=typed(raw,'ICWOperation');mill=typed(raw,'ICWMillOperation')
        require(_object_id(doc,op,read)==row['operation_native_id']and read(op,'Suppressed')is False and type(read(mill,'OpernType'))is int and read(mill,'OpernType')==row['operation_kind'],'Exact empty selected kind required')
        require(read(op,'GetIsToolpathGenerated')is False and not _items(read(op,'IGetEnumToolpaths'),typed,read,1),'Selected operation must stay empty')
        require([_object_id(doc,x,read)for x in _items(read(op,'IGetAllFeatures'),typed,read,2)]==[row['feature_native_id']],'Exact feature link required')
        generic,_=writer.captures.read_generic_tool(op,doc,read,typed);expected=next(r for r in self.expected_route['operations']if r['native_id']==row['operation_native_id'])['assigned_tool'];require(exact(generic,expected),'Selected current tool changed')
        found=read(doc,'GetCWObjectFromID',1,row['feature_native_id']);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True and _object_id(doc,found[0],read)==row['feature_native_id'],'Exact feature required');return raw,found[0],mill
    def observe_target(self,row):
        raw,feature,_=self.target(row,self.read,self.typed);out={}
        def typed(obj,name):return self.read(obj,'QueryInterface',IDispatch)if name=='IDispatch'else self.typed(obj,name)
        identity=dict(operation_kind=row['operation_kind'],operation_native_id=row['operation_native_id'],feature_native_id=row['feature_native_id'],tool_native_id=next(r for r in self.expected_route['operations']if r['native_id']==row['operation_native_id'])['assigned_tool']['native_id'])
        reader.read_target(raw,feature,identity,self.read,typed,lambda n,d:reader.finish.nc.lead_pointer_value(n,d),self.persist,out)
        return recipe_core.compact_target(out)
    def observe_draft(self):
        draft=self.config['draft'];oid=draft['operation_native_id'];row=next(r for r in self.config['state']['operations']if r['native_id']==oid);found=self.read(self.native['doc'],'GetCWObjectFromID',3,oid);require(found[1]is True and _object_id(self.native['doc'],found[0],self.read)==oid,'Retained draft absent');raw=found[0];feature=self.read(self.native['doc'],'GetCWObjectFromID',1,row['linked_feature_ids'][0]);require(feature[1]is True,'Draft feature absent')
        def typed(obj,name):return self.read(obj,'QueryInterface',IDispatch)if name=='IDispatch'else self.typed(obj,name)
        default=base.defaults.read_defaults(raw,feature[0],read=self.read,typed=typed,persist=self.persist,diagnostic={});nc=dict(operation_native_id=oid);base.parameter_capture.read_own_nc(raw,nc,read=self.read,typed=self.typed,boundary=self.boundary);return dict(operation_native_id=oid,defaults=default,own_nc=nc)
    def assign(self,row,*,pending,returned):
        with self.guard()as g:
            raw,_,mill=self.target(row,g.read,g.typed);candidate=self.config['candidate']
            machine=g.typed(g.read(g.typed(self.native['doc'],'ICWPartDoc'),'IGetMachine'),'ICWMachine');crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4');tools=_items(g.read(crib,'GetAllTools'),g.typed,g.read,64)
            found=[x for x in tools if _object_id(self.native['doc'],x,g.read)==candidate['generic']['native_id']];require(len(found)==1,'One existing candidate in current crib required')
            generic,tool=writer.captures.tool_generic(found[0],self.native['doc'],g.read,g.typed);require(exact(writer.captures.read_tool_dimensions(tool,generic,g),candidate),'Full shared candidate changed');dispatch=g.read(tool,'QueryInterface',IDispatch)
            def invoke():value=_member(mill,'SetTool',dispatch);returned(value);return value
            value=g.dispatch_once(invoke,persist_pending=pending)
        require(type(value)is int and value==0,'Exact SetTool HRESULT0 required; no replay')
        next(r for r in self.expected_route['operations']if r['native_id']==row['operation_native_id'])['assigned_tool']=deepcopy(candidate['generic'])
    def field_spec(self,row,key):
        if row['operation_kind']==0 and key not in recipe_core.ROUGH_COMMON:
            s=writer.fields.FIELDS[key];return 'ICWRghMillOp',s.getter,s.setter,s.mode
        s=(recipe_core.ROUGH_COMMON if row['operation_kind']==0 else recipe_core.finish.FIELDS)[key];return s.interface,s.getter,s.setter,s.mode
    def field(self,row,key,read,typed,observe):
        raw,feature,mill=self.target(row,read,typed);interface,getter,setter,mode=self.field_spec(row,key)
        if interface.startswith('ICWNCParam'):raw=read(mill,'IGetNCParam')
        owner=typed(raw,interface);dispatch=read(feature,'QueryInterface',IDispatch)
        actual=observe(lambda:reader.finish.nc.lead_pointer_value(owner,{}))if mode=='absolute_feed'else read(owner,getter,*((dispatch,)if mode=='feature'else()))
        return owner,dispatch,interface,setter,mode,list(actual)if type(actual)is tuple else actual
    def set_change(self,row,change,*,pending,returned):
        with self.guard()as g:
            owner,feature,interface,setter,mode,actual=self.field(row,change['field'],g.read,lambda raw,name:self.guarded_typed(g,raw,name),g._observe)
            if change['field']=='xy_feed':require(type(actual)is float and math.isfinite(actual)and actual>0,'Positive observed spindle-coupled XY feed required');self.report.setdefault('coupled_xy_before_write',{})[str(row['operation_native_id'])]=actual;self.persist()
            else:require(exact(actual,change['expected']),'Immediate expected field changed')
            new=change['new']
            def invoke():
                if mode=='property':value=getattr(owner,'_'+interface+'__com__set_'+setter)(new)
                elif mode=='absolute_feed':value=getattr(owner,'_ICWNCParam__com_SetLeadinFeedrate')(new['value_native'],False)
                else:value=_member(owner,setter,*((feature,new)if mode=='feature'else tuple(new)if mode in('pair','depth_pair')else(new,)))
                returned(value);return value
            value=g.dispatch_once(invoke,persist_pending=pending)
        require(type(value)is int and value==0,'Exact field HRESULT0 required; no replay')
        with self.guard()as g:observed=self.field(row,change['field'],g.read,lambda raw,name:self.guarded_typed(g,raw,name),g._observe)[-1]
        require(exact(observed,new),'Immediate field readback differs');return observed


class Journal(writer.engine.Journal):
    def marker_state(self):
        r=self.report;return dict(scope=SCOPE,status=r['status'],phase=r['phase'],recipe_pin=r['recipe_pin'],read_authority_pin=r['read_authority_pin'],source_before_sha256=r['source_before_sha256'],receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),automatic_replay=False)
    def pending(self,name):
        allowed=set(self.report['allowed_actions']);require(name in allowed,'Action outside explicit configuration packet')
        if name!='SaveActiveDocument':
            self.report['mutation_attempted']=True
            self.report['tool_assignment_attempted'if name.startswith('SetTool:')else'parameter_setter_attempted']=True
        super().pending(name)


def action_names(recipe):
    out=[]
    for row in recipe['rows']:
        oid=str(row['operation_native_id']);out+=['field:'+oid+':link_to_tool','SetTool:'+oid]
        out+=['field:'+oid+':'+c['field']for c in row['changes']if c['field']!='link_to_tool']
    return out+['SaveActiveDocument']


def run_once(backend,journal,data,v):
    r=journal.report
    def observe(label):
        detail=dict(label=label,capture_complete=False,state={});r['captures'].append(detail);r['phase']=label;journal.persist();actual=backend.capture(label,detail['state']);require(all(actual.get(k)is True for k in('capture_complete','parameter_capture_complete','extended_capture_complete')),'Complete full route snapshot required');detail.update(capture_complete=True,state=deepcopy(actual));r[label]=deepcopy(actual);journal.persist();return actual
    def targets(label):return r['target_observations'][label]
    def draft(label):return r['draft_observations'][label]
    def set_one(row,change):
        name='field:'+str(row['operation_native_id'])+':'+change['field'];journal.action(name)
        observed=backend.set_change(row,change,pending=lambda:journal.pending(name),returned=lambda value:journal.returned(name,value));r['actions'][name]['immediate_readback']=deepcopy(observed);journal.persist()
    try:
        journal.create();backend.start();before=observe('before');require(writer.same(before,data['state']),'Actual full saved route differs')
        require(exact(targets('before'),data['targets'])and exact(draft('before'),data['draft']),'Actual selected scalars or retained draft differ')
        recipe_core.validate_recipe(data['recipe'],targets('before'),data['authority']['receipt']['new_operations'],data['candidate']);backend.boundary();journal.claim()
        r['assignment_observations']=[]
        for index,row in enumerate(data['recipe']['rows']):
            changes={c['field']:c for c in row['changes']};set_one(row,changes['link_to_tool'])
            expected_unlinked=deepcopy(data['targets'][index]);expected_unlinked['modes']['nc']['LinkToTool']=False
            with backend.selected_snapshot('unlinked_'+str(row['operation_native_id'])):actual=backend.observe_target(row)
            require(exact(expected_unlinked,actual),'Unlink changed unrelated selected parameters')
            name='SetTool:'+str(row['operation_native_id']);journal.action(name);backend.assign(row,pending=lambda:journal.pending(name),returned=lambda value:journal.returned(name,value))
            with backend.selected_snapshot('assigned_'+str(row['operation_native_id'])):assigned=backend.observe_target(row)
            proof=verify_assignment(expected_unlinked,assigned,row);r['assignment_observations'].append(dict(operation_native_id=row['operation_native_id'],before=actual,after=assigned,proof=proof));journal.persist()
            for original in row['changes']:
                if original['field']=='link_to_tool':continue
                change=deepcopy(original)
                if change['field']in('spindle','xy_feed','leadin_feed'):
                    key={'spindle':'GetSpndlSpeed','xy_feed':'XYFeed','leadin_feed':'leadin_feed'}[change['field']];change['expected']=deepcopy(assigned['modes']['nc'][key])
                set_one(row,change)
        configured=observe('configured');r['configuration_proof']=verify_full_configuration(before,configured,data['recipe'],data['candidate'],targets('before'),targets('configured'),draft('before'),draft('configured'));r['parameters_readback_verified']=True;journal.persist()
        backend.boundary();journal.action('SaveActiveDocument');r['save_stage']=dict(before_state_reused_from='configured',save_pending=False);journal.persist()
        def returned(value):
            journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if type(value)in(int,bool,float,str)or value is None else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha);journal.persist()
        saved=observe('saved');writer.CircularGenerationProof(backend,reference=before).verify_saved(configured,saved)
        require(exact(targets('configured'),targets('saved'))and exact(draft('before'),draft('saved')),'Selected configuration or draft changed during Save')
        confirm=observe('confirm_saved');require(writer.same(saved,confirm)and exact(targets('saved'),targets('confirm_saved'))and exact(draft('saved'),draft('confirm_saved')),'Two complete saved states differ')
        r.update(model_saved=True,save_readback_verified=True,source_update_verified=True,saved_observations=deepcopy(targets('saved')),saved_draft_witness=deepcopy(draft('saved')));backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,parameters_configured=True,configuration_saved=True,reason='TWO_EMPTY_SELECTED_OPERATIONS_CONFIGURED_AND_SAVED_NO_GTP')
    except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),readback_verified=False,runtime_unchanged=False,parameters_configured=False,configuration_saved=False)
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(error),readback_verified=False,runtime_unchanged=False,parameters_configured=False,configuration_saved=False)
        journal.persist()
    return r


def dispatch(sw,clsid,tlb,values,*,runtime_check,_context_factory=Context):
    require(callable(runtime_check),'Runtime guard required');v=values;data=validate(v);require(data['lineage']['loaded']['addin_clsid'].casefold()==clsid.casefold(),'Add-in differs');abi=preflight(tlb)
    r=dict(scope=SCOPE,status='error',phase='preflight',request=deepcopy(v),recipe=deepcopy(data['recipe']),recipe_pin=data['recipe_pin'],receipt_path=v['receipt_path'],dispatch_marker_path=str(data['marker']),source_before_sha256=v['expected_source_sha256'],authority_pin=data['authority']['receipt_pin'],read_authority_pin=data['read_pin'],historical_CL_pin=data['lineage']['cl_pin'],evidence_pins=deepcopy(data['pins']),protected_draft_native_id=data['draft']['operation_native_id'],selected_operation_native_ids=[x['operation_native_id']for x in data['recipe']['rows']],future_machining_excluded_operation_ids=[data['draft']['operation_native_id']],abi=abi,allowed_actions=action_names(data['recipe']),actions={},captures=[],target_observations={},draft_observations={},native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,operation_creation_attempted=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,save_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,automatic_replay=False,automatic_rollback=False,model_saved=False,save_readback_verified=False,source_update_verified=False,readback_verified=False,runtime_unchanged=False,parameters_configured=False,parameters_readback_verified=False,configuration_saved=False,machining_eligible=False,production_qualified=False,reopen_persistence_verified=False,CL_streams_reexported=False)
    journal=Journal(v['receipt_path'],data['marker'],r);backend=_context_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check);return run_once(backend,journal,data,v)


def finalize_runtime_failure(result,error):
    result.update(status='uncertain'if result.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,configuration_saved=False,parameters_configured=False,machining_eligible=False,production_qualified=False);_write_receipt(Path(result['receipt_path']),result)
    if result.get('marker_created'):_write_receipt(Path(result['dispatch_marker_path']),dict(scope=SCOPE,status=result['status'],phase=result['phase'],recipe_pin=result['recipe_pin'],read_authority_pin=result['read_authority_pin'],source_before_sha256=result['source_before_sha256'],receipt_path=result['receipt_path'],receipt_sha256=_file_hash(result['receipt_path']),automatic_replay=False))
    return result
