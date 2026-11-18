"""Append two ungenerated Finish definitions to a pinned saved circular route."""
from copy import deepcopy
from pathlib import Path
import math,re
from ctypes import HRESULT,POINTER,c_int
from comtypes.automation import IDispatch
from scripts import sw_cam_circular_reconfigure as writer
from scripts import sw_cam_reconfigured_circular_wip as lineage
from scripts import sw_cam_reconfigured_circular_wip_binding as binding
from scripts import sw_cam_current_circular_context as circular
from scripts import sw_cam_chamfer_defaults as defaults
from scripts import sw_cam_mill_current_append as append
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_comtypes import _interface_class,_is_comtypes_pointer
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_mill_current_append import read_catalogues
from scripts.sw_cam_profile_sketch import _snapshot,_read_sketch
from scripts.sw_cam_mill_units_qualification import _circle_feature,_circle_sketch
batch=circular.batch
parameter_capture=circular.parameter_capture
fields=writer.fields
require=writer.require
SCOPE='SAVED_CIRCULAR_APPEND_FINISH_DEFINITIONS_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','revision_receipt_path','revision_receipt_sha256','revision_marker_path','revision_marker_sha256','recipe_path','recipe_sha256','receipt_path','qualification_only','message_policy'}
ROW_KEYS={'role','feature_native_id','feature_owner_setup_native_id','operation_setup_native_id','default_operation_id','default_operation_name','expected_bottom_finish'}
BASE_KEYS=('capture_complete','features','feature_setups','operation_counts','selected_operation_setup','operation_setups','operation_setup_count','operations','operation_count','operation_inventory_scope')


def retained_generation_counts(state,operation_id):
    rows=[row for row in state['operations']if row['native_id']==operation_id]
    require(len(rows)==1,'Exact retained generation operation required')
    return deepcopy(rows[0]['toolpath_record_counts'])


def feature_header(state,fid):
    rows=[state[k] for k in ('target_header','reference_header') if state[k]['native_id']==fid]
    require(len(rows)==1,'Definition feature must be one of two fully observed current features');return deepcopy(rows[0])


def validate_recipe(recipe,state):
    require(type(recipe)is dict and set(recipe)=={'scope','producer_operation_native_id','anchor_operation_native_id','definitions'},'Exact append recipe required')
    require(recipe['scope']==SCOPE and type(recipe['producer_operation_native_id'])is int and recipe['producer_operation_native_id']>0,'Explicit producer identity required')
    aid=recipe['anchor_operation_native_id'];require(type(aid)is int and aid==recipe['producer_operation_native_id'] and state['operations'][-1]['native_id']==aid,'Producer must be final current operation')
    require(state['operations'][-1]['toolpath_generated']is True,'Saved generated anchor required')
    rows=recipe['definitions'];require(type(rows)is list and len(rows)==2,'Exactly two Finish definitions required')
    require([r.get('role') for r in rows]==['floor','wall'],'Explicit floor then wall order required')
    require(len({r['feature_native_id'] for r in rows})==2,'Two distinct existing features required')
    require(len(state['operations'])+2<=32,'Bounded operation table required')
    for row in rows:
        require(set(row)==ROW_KEYS,'Exact definition fields required')
        for key in ('feature_native_id','feature_owner_setup_native_id','operation_setup_native_id','default_operation_id'):require(type(row[key])is int and row[key]>0,'Strict positive native identity required')
        require(type(row['default_operation_name'])is str and 0<len(row['default_operation_name'])<=128,'Explicit native default name required')
        require(type(row['expected_bottom_finish'])is bool and row['expected_bottom_finish']is(row['role']=='floor'),'Explicit bottom mode required')
        header=feature_header(state,row['feature_native_id']);require(header['suppressed']is False,'Unsuppressed existing feature required')
        member=[x for x in state['features'] if x['geometry']['native_id']==row['feature_native_id']]
        require(len(member)==1 and member[0]['setup_native_id']==row['feature_owner_setup_native_id'],'Exact feature setup required')
        require(row['operation_setup_native_id']==state['operations'][-1]['setup_native_id'] and row['feature_owner_setup_native_id']==state['selected_operation_setup']['feature_setup_native_id'],'Both definitions must append to same observed setup')
        catalog=state['target_catalogues'] if row['feature_native_id']==state['target_header']['native_id'] else state['default_operation_catalogues']
        entries=[e for c in catalog if c['operation_type']==1 for e in c['entries'] if e['name']==row['default_operation_name'] and e['default_operation_id']==row['default_operation_id']]
        require(len(entries)==1,'Exact requested default absent from feature catalogue')
    return deepcopy(recipe)


def project_appended(before,after,added_rows):
    out=deepcopy(after);old=before['operations'];ids=[r['native_id'] for r in added_rows]
    require(len(ids)<=2 and len(set(ids))==len(ids) and not(set(ids)&{r['native_id'] for r in old}),'Fresh bounded added IDs required')
    require([r['native_id'] for r in out['operations']]==[r['native_id'] for r in old]+ids,'Only exact ordered suffix may be added')
    require(fields.equal(out['operations'][-len(ids):],added_rows) if ids else fields.equal(out['operations'],old),'Actual addition rows differ')
    anchor=old[-1]
    for i,row in enumerate(added_rows):
        require(type(row['native_id'])is int and row['native_id']>0 and row['mill_operation_type']==1 and type(row['mill_operation_type'])is int and row['suppressed']is False and row['toolpath_generated']is False and row['toolpath_record_counts']==[],'New definition must remain empty Finish')
        require(row['setup_native_id']==anchor['setup_native_id'] and row['setup_index']==anchor['setup_index'] and row['operation_index']==anchor['operation_index']+i+1,'Exact same-setup append positions required')
    out['operations']=out['operations'][:len(old)]
    si=anchor['setup_index'];n=len(ids)
    for row in (out['operation_setups'][si],out['selected_operation_setup']):row['operation_count']-=n
    out['operation_counts'][si]-=n;out['operation_count']-=n
    if 'parameter_batch' in out:
        pb=out['parameter_batch'];oldpb=before['parameter_batch'];candidate=oldpb['candidate_tool']['generic']['native_id']
        extra=[r['native_id']for r in added_rows if r['assigned_tool']['native_id']==candidate]
        require(pb['candidate_consumer_ids']==oldpb['candidate_consumer_ids']+extra,'Only actual added tool consumers may grow')
        require(set(pb['candidate_consumers'])==set(oldpb['candidate_consumers'])|{str(i)for i in extra},'Exact added consumer keys required')
        for oid in extra:
            value=pb['candidate_consumers'][str(oid)];require(value['operation_native_id']==oid and value['assigned_tool_native_id']==candidate and value['read_complete']is True,'Complete actual added consumer observation required')
            del pb['candidate_consumers'][str(oid)]
        pb['candidate_consumer_ids']=deepcopy(oldpb['candidate_consumer_ids'])
    return out


def verify_appended(before,after,added_rows):
    out=project_appended(before,after,added_rows);reference=deepcopy(before)
    for state in (out,reference):
        for key in ('document','sketch_state'):
            require(type(state[key]['needs_save'])is bool,'Strict dirty flags required');state[key]['needs_save']=False
    require(writer.same(reference,out),'Insertion changed a protected state, tool, feature, parameter or path')
    return dict(existing_operation_count=len(before['operations']),new_operation_ids=[r['native_id']for r in added_rows],generated_operations_preserved=True,tool_catalogue_preserved=True,feature_geometry_preserved=True,protected_parameters_preserved=True)


def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact append request required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact owner lifetime required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Explicit definition-only qualification required')
    for k,val in v.items():
        if k.endswith('_sha256'):require(type(val)is str and re.fullmatch('[0-9a-f]{64}',val),'Exact SHA required')
        if k.endswith('_path'):require(type(val)is str and Path(val).is_absolute(),'Absolute paths required')
    source=Path(v['expected_document_path']);require(source.suffix.lower()=='.sldprt' and source.is_file() and not source.is_symlink() and _file_hash(source)==v['expected_source_sha256'],'Exact saved source required')
    r,rp=read_pin(v['revision_receipt_path'],v['revision_receipt_sha256']);recipe,p=read_pin(v['recipe_path'],v['recipe_sha256']);oid=r['operation_native_id'];generated=r['postCL']['expected_generated_operations']
    bound=binding.bind_completed_revision(rp,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=str(source),source_sha256=v['expected_source_sha256'],selected_operation_ids=[oid],protected_operation_ids=[x['operation_native_id']for x in generated if x['operation_native_id']!=oid],expected_generated_operations=generated,marker_pin=dict(path=v['revision_marker_path'],sha256=v['revision_marker_sha256']),writer_pin=dict(path=writer.__file__,sha256=_file_hash(writer.__file__)))
    require(recipe['producer_operation_native_id']==oid,'Recipe must follow the bound producer');validate_recipe(recipe,bound['snapshot'])
    data=lineage.load_context_lineage(r,bound);key=_digest(dict(scope=SCOPE,source=str(source.resolve()).casefold(),sha=v['expected_source_sha256'],recipe=recipe));marker=source.parent/('append_finish_'+key+'.json');out=Path(v['receipt_path'])
    pins=deepcopy(bound['pins'])+[p]+[dict(path=x,sha256=_file_hash(x))for x in (__file__,lineage.__file__,defaults.__file__)]
    protected={str(Path(x['path']).resolve()).casefold()for x in pins}|{str(source.resolve()).casefold()}
    require(out.parent.is_dir() and out.suffix.lower()=='.json' and not out.exists() and not out.is_symlink() and not marker.exists() and not marker.is_symlink(),'Fresh receipt and one-shot marker required')
    require(str(out.resolve()).casefold()not in protected and out.resolve()!=marker.resolve(),'Receipt/evidence alias forbidden')
    return dict(state=deepcopy(bound['snapshot']),recipe=recipe,recipe_pin=p,lineage=data,writer_receipt=r,bound=bound,pins=pins,marker=marker)


def preflight(tlb):
    cls=_interface_class('ICWMillFeature',tlb);m=[x for x in cls._methods_ if x.name=='InsertOperation'];require(len(m)==1,'Unique native insertion required');m=m[0]
    require(m.restype is HRESULT and m.idlflags[0]==44 and m.argtypes==(c_int,c_int,POINTER(IDispatch),POINTER(POINTER(IDispatch))) and tuple(x[0]for x in m.paramflags)==(1,1,1,10),'Exact InsertOperation ABI required')
    append.save_abi(tlb);return dict(insert_discriminator=1,native_calls=0)


class AppendContext(writer.RevisionContext):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        args=deepcopy(data['writer_receipt']['request']);args['expected_source_sha256']=v['expected_source_sha256']
        super().__init__(sw,clsid,tlb,args,data['lineage'],report,persist,runtime_check)
        self.append_plan=data;self.added_rows=[];self.pins.extend(read_pin(p['path'],p['sha256'])[1] for p in data['pins']if Path(p['path']).suffix.lower()=='.json' and Path(p['path']).resolve()!=Path(v['expected_document_path']).resolve());self._native_read_limit=16000
        require(self.v['process_id']==v['process_id'] and self.v['expected_process_create_time']==v['expected_process_create_time'],'Current native owner differs')
    def verify_files(self):
        super().verify_files()
        if getattr(self,'_capture_pin_scope',False):return
        if hasattr(self,'append_plan'):
            for p in self.append_plan['pins']:
                if Path(p['path']).suffix.lower()!='.json' and Path(p['path']).resolve()!=Path(self.v['expected_document_path']).resolve():binding.common.direct(p)
    def capture(self,label,partial):
        self.consumer_ids=deepcopy(self.append_plan['state']['parameter_batch']['candidate_consumer_ids'])+[r['native_id']for r in self.added_rows if r['assigned_tool']['native_id']==self.v['candidate_tool_native_id']]
        return super().capture(label,partial)
    def compact(self,label):
        state={};self.report[label]=state;self.persist();start=self.boundary()
        def boundary():require(self.boundary()==start,'Identity changed during compact append read')
        self.native=batch.current._capture(self.app,self.tlb,self.read,self.typed,state,self.v,boundary,verify_operation_pins=False);state['document']=deepcopy(start);self.persist();return state
    def insert(self,row,anchor_id,*,pending,returned):
        with self.guard()as g:
            found=g.read(self.native['doc'],'GetCWObjectFromID',1,row['feature_native_id']);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Existing feature lookup failed')
            feature=g.typed(found[0],'ICWMillFeature');header,_=read_header(feature,self.native['doc'],g.read,g.typed,row['feature_owner_setup_native_id']);require(fields.equal(header,feature_header(self.append_plan['state'],row['feature_native_id'])),'Feature changed before insertion')
            found=g.read(self.native['doc'],'GetCWObjectFromID',3,anchor_id);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact anchor lookup failed');anchor=g.read(found[0],'QueryInterface',IDispatch);require(_object_id(self.native['doc'],anchor,g.read)==anchor_id,'Anchor dispatch differs')
            actual=g.read(feature,'GetTdbIdForDefaultOperation',1,row['default_operation_name']);require(type(actual)is int and actual==row['default_operation_id'],'Actual selected feature default differs')
            def invoke():
                value=_member(feature,'InsertOperation',1,actual,anchor);returned(value);return value
            raw=g.dispatch_once(invoke,persist_pending=pending)
        require(_is_comtypes_pointer(raw)and bool(raw),'Nonnull actual operation pointer required')
        with self.guard() as post:
            oid=_object_id(self.native['doc'],raw,post.read)
        forbidden={r['native_id']for r in self.append_plan['state']['operations']+self.added_rows}|{r['geometry']['native_id']for r in self.append_plan['state']['features']}|{r['native_id']for r in self.append_plan['state']['operation_setups']+self.append_plan['state']['feature_setups']}
        require(type(oid)is int and oid>0 and oid not in forbidden,'New actual operation identity collision');return oid
    def read_operation_defaults(self,oid,row,label):
        diagnostic={};self.report.setdefault('defaults_diagnostics',{})[label]=diagnostic;self.persist()
        with self.guard()as g:
            found=g.read(self.native['doc'],'GetCWObjectFromID',3,oid);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact new operation lookup required');raw=found[0]
            found=g.read(self.native['doc'],'GetCWObjectFromID',1,row['feature_native_id']);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact feature lookup required');feature=found[0]
            require(_object_id(self.native['doc'],raw,g.read)==oid,'Defaults operation differs')
            def typed(obj,name):return g.read(obj,'QueryInterface',IDispatch)if name=='IDispatch'else g.typed(obj,name)
            value=defaults.read_defaults(raw,feature,read=g.read,typed=typed,persist=self.persist,diagnostic=diagnostic)
        return value
    def operation_defaults(self,oid,row,label):
        value=self.read_operation_defaults(oid,row,label)
        require(value['finish']['BottomFinOpt']is row['expected_bottom_finish'],'Actual default bottom mode differs; no setter/replay');return value

    def _capture_readonly(self,label,consumer_ids=None,generation_observations=None,attempted_generation_ids=()):
        # 新操作只在实际 GTP attempt 后接受当次 route 返回的正记录数。
        if consumer_ids is None:consumer_ids=list(self.reference_consumers)+([self.new_operation_ids[0]] if self.new_operation_ids and getattr(self,'new_own_tool_id',None)==self.v['candidate_tool_native_id'] else [])
        require(all(type(x) is int for x in attempted_generation_ids) and set(attempted_generation_ids)<=set(self.new_operation_ids),'Generation scope outside actual new operations')
        state={};self.report[label]=state
        if not getattr(self,'_capture_journal_managed',False):self.report['captures'].append(label)
        self.persist();start=self.boundary()
        def boundary():require(self.boundary()==start,'Identity changed during reference capture')
        try:
            self.native=batch.current._capture(self.app,self.tlb,self.read,self.typed,state,self.v,boundary,verify_operation_pins=False)
            state['document']=deepcopy(start)
            base=self.append_plan['state'];expected=[x['native_id']for x in base['operations']]+[x['native_id']for x in self.added_rows]
            require([x['native_id']for x in state['operations']]==expected,'Exact retained prefix and appended IDs required')
            require(fields.equal(state['operations'][:len(base['operations'])],base['operations']),'An existing operation/tool/path changed')
            for row in state['operations'][len(base['operations']):]:require(row['toolpath_generated']is False and row['toolpath_record_counts']==[],'Appended Finish unexpectedly generated')
            generation_observations={self.oid:retained_generation_counts(base,self.oid)}
            strategy=deepcopy(state)
            for row in strategy['features']:
                if row['geometry']['native_id']==self.v['expected_feature_native_id']:row['geometry']=deepcopy(state['target_header'])
            state['strategy_diagnostics']={}
            batch.read_compound_strategy(strategy,self.native,self.read,self.typed,state['strategy_diagnostics'],feature_id=self.v['expected_feature_native_id'],owner_id=self.v['expected_feature_setup_native_id'],step_count=3,expected_header=state['target_header'],boundary=boundary,observation='strategy')
            state['default_operation_catalogues']=read_catalogues(self.native['selected_feature'],read=self.read,typed=self.typed)
            if self.data['authority']['definition_mode']=='selected_continue':
                oid=self.v['parameter_operation_native_ids'][0];state['retained_operation_nc']=dict(operation_native_id=oid,read_complete=False)
                state['retained_operation_nc']['nc']=batch.read_own_nc(self.native['operations'][oid],read=self.read,typed=self.typed);state['retained_operation_nc']['read_complete']=True
            targets=[next(x for x in state['operations'] if x['native_id']==oid) for oid in self.v['parameter_operation_native_ids']]
            parameter_capture.capture_parameter_batch(state,self.native,targets,feature_id=self.v['expected_feature_native_id'],candidate_tool_native_id=self.v['candidate_tool_native_id'],expected_candidate_consumer_ids=consumer_ids,read=self.read,typed=self.typed,boundary=boundary)
            boundary()
        except BaseException:
            state['capture_complete']=False;self.persist();raise
        self.report[label]=state;state['extended_capture_complete']=False
        try:
            state['reference_header']=state.pop('target_header');state['reference_profile']=state.pop('profile');state['reference_number_of_steps_raw']=state.pop('number_of_steps_raw')
            witness={k:state.pop(k) for k in ('operation_parameters','parameter_capture_complete','parameter_batch','retained_operation_nc') if k in state}
            observed=witness['parameter_batch'];allowed=set(self.reference_consumers)
            observed['candidate_consumer_ids']=[x for x in observed['candidate_consumer_ids'] if x in allowed]
            observed['candidate_consumers']={k:x for k,x in observed['candidate_consumers'].items() if int(k) in allowed}
            state['reference_parameter_observation']=witness
            self.boundary();sketch,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.request['sketch_spec']);state['sketch_state']=sketch;self.boundary()
            if self.created_names:
                raw=self.read(model,'FeatureByName',self.request['sketch_spec']['sketch_name']);require(raw is not None,'Exact created sketch missing')
                state['measured_sketch']=_read_sketch(self.sw,self.read(raw,'GetSpecificFeature2'),self.request['sketch_spec'])
                state['measured_circle']=_circle_sketch(state['measured_sketch'],self.request['sketch_spec']);self.boundary()
            if self.new_feature_id is not None:
                found=self.read(self.native['doc'],'GetCWObjectFromID',1,self.new_feature_id);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact new pocket lookup required')
                header,feature=read_header(found[0],self.native['doc'],self.read,self.typed,self.request['owner_setup_native_id'])
                state['target_header']=header;state['target_geometry']=_circle_feature(feature,self.native['doc'],self.tlb,self.read,self.typed)
                count=self.read(self.typed(feature,'ICWMillFeature'),'IGetIslandCount');state['target_geometry']['island_count']=count
                require(type(count) is int and count==0,'Closed circular pocket must contain no islands')
                state['target_catalogues']=read_catalogues(feature,read=self.read,typed=self.typed)
                if self.new_operation_ids:
                    targets=[next(x for x in state['operations'] if x['native_id']==oid) for oid in self.new_operation_ids]
                    native=dict(self.native,selected_feature=feature)
                    parameter_capture.capture_parameter_batch(state,native,targets,feature_id=self.new_feature_id,candidate_tool_native_id=self.v['candidate_tool_native_id'],expected_candidate_consumer_ids=consumer_ids,read=self.read,typed=self.typed,boundary=self.boundary,generation_observations=generation_observations,expected_operation_types=(0,))
            self.boundary();state['extended_capture_complete']=True;return state
        finally:
            if state.get('extended_capture_complete') is not True:state['capture_complete']=False
            self.persist()


class Journal(writer.engine.Journal):
    def marker_state(self):return dict(scope=SCOPE,status=self.report['status'],phase=self.report['phase'],recipe_pin=self.report['recipe_pin'],source_before_sha256=self.report['source_before_sha256'],receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),automatic_replay=False)
    def pending(self,name):
        require(name in ('InsertOperation:floor','InsertOperation:wall','SaveActiveDocument'),'Only two inserts and one Save admitted')
        if name.startswith('InsertOperation:'):self.report.update(mutation_attempted=True,operation_creation_attempted=True)
        super().pending(name)


def verify_compact(before,observed,added_rows,definition,oid):
    expected=deepcopy(before);actual={k:deepcopy(observed[k])for k in BASE_KEYS}
    base={k:deepcopy(expected[k])for k in BASE_KEYS};projected=project_appended(base,actual,added_rows)
    require(fields.equal(base,projected),'Compact route has unexpected changes')
    require(fields.equal(observed['target_header'],before['reference_header']) and fields.equal(observed['profile'],before['reference_profile']),'Compound feature changed during append')
    row=added_rows[-1];require(row['native_id']==oid and row['linked_feature_ids']==[definition['feature_native_id']] and row['setup_native_id']==definition['operation_setup_native_id'],'Exact new definition feature/setup link required')
    return deepcopy(row)


def run_once(backend,journal,data,v):
    r=journal.report;added=[];default_values=[];proof=writer.CircularGenerationProof(backend,reference=data['state'])
    def observe(label):
        detail=dict(label=label,capture_complete=False,state={});r['captures'].append(detail);r['phase']=label;journal.persist()
        state=backend.capture(label,detail['state']);require(all(state.get(k)is True for k in ('capture_complete','parameter_capture_complete','extended_capture_complete')),'Complete full capture required')
        detail.update(capture_complete=True,state=deepcopy(state));r[label]=deepcopy(state);journal.persist();return state
    try:
        journal.create();backend.start();before=observe('before');require(writer.same(before,data['state']),'Fresh full state differs from current saved authority');validate_recipe(data['recipe'],before);backend.boundary();journal.claim()
        anchor=data['recipe']['anchor_operation_native_id']
        for definition in data['recipe']['definitions']:
            name='InsertOperation:'+definition['role'];journal.action(name)
            oid=backend.insert(definition,anchor,pending=lambda n=name:journal.pending(n),returned=lambda value,n=name:journal.returned(n,value))
            r['actions'][name]['actual_operation_native_id']=oid;journal.persist()
            compact=backend.compact('after_'+definition['role']+'_route');found=[x for x in compact['operations']if x['native_id']==oid];require(len(found)==1,'Unique actual new operation required')
            candidate=added+[deepcopy(found[0])];verify_compact(before,compact,candidate,definition,oid)
            value=backend.operation_defaults(oid,definition,'after_'+definition['role']);defaults.validate_defaults(value);require(value['finish']['BottomFinOpt']is definition['expected_bottom_finish'],'Actual bottom mode must match definition role')
            added=candidate;default_values.append(value);backend.added_rows=deepcopy(added);r.update(new_operations=deepcopy(added),inserted_defaults=deepcopy(default_values));journal.persist();anchor=oid
        inserted=observe('inserted');r['append_proof']=verify_appended(before,inserted,added);backend.boundary();journal.action('SaveActiveDocument');r['save_stage']={'before_state_reused_from':'inserted','save_pending':False};journal.persist()
        def returned(value):
            journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if type(value)in(int,bool,float,str)or value is None else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha);journal.persist()
        saved=observe('saved');proof.verify_saved(inserted,saved)
        observed=[]
        for row,definition in zip(added,data['recipe']['definitions']):
            value=backend.operation_defaults(row['native_id'],definition,'saved_'+definition['role']);require(fields.equal(value,default_values[len(observed)]),'New defaults changed during Save');observed.append(value)
        r['saved_defaults']=observed;journal.persist();confirm=observe('confirm_saved');require(writer.same(saved,confirm),'Two complete saved captures differ')
        r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,definitions_verified=True,reason='TWO_EMPTY_FINISH_DEFINITIONS_SAVED_WITH_PROTECTED_ROUTE',generation_performed=False,parameters_configured=False)
    except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),readback_verified=False,runtime_unchanged=False,definitions_verified=False)
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(error),readback_verified=False,runtime_unchanged=False,definitions_verified=False)
        journal.persist()
    return r


def finalize_runtime_failure(result,error):
    result.update(status='uncertain'if result.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,definitions_verified=False,production_qualified=False)
    _write_receipt(Path(result['receipt_path']),result)
    if result.get('marker_created'):_write_receipt(Path(result['dispatch_marker_path']),dict(scope=SCOPE,status=result['status'],receipt_path=result['receipt_path'],receipt_sha256=_file_hash(result['receipt_path']),automatic_replay=False))
    return result


def dispatch(sw,clsid,tlb,values,*,runtime_check=None,_context_factory=AppendContext):
    require(callable(runtime_check),'Runtime guard required');v=values;data=validate(v);require(data['lineage']['loaded']['addin_clsid'].casefold()==clsid.casefold(),'Bound add-in differs');abi=preflight(tlb)
    r=dict(scope=SCOPE,status='error',phase='preflight',request=deepcopy(v),recipe=deepcopy(data['recipe']),recipe_pin=data['recipe_pin'],receipt_path=v['receipt_path'],dispatch_marker_path=str(data['marker']),source_before_sha256=v['expected_source_sha256'],authority_pin=data['bound']['receipt_pin'],historical_CL_pin=data['lineage']['cl_pin'],evidence_pins=deepcopy(data['pins']),abi=abi,actions={},captures=[],new_operations=[],native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,operation_creation_attempted=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,save_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,automatic_replay=False,automatic_rollback=False,model_saved=False,save_readback_verified=False,source_update_verified=False,readback_verified=False,definitions_verified=False,runtime_unchanged=False,production_qualified=False,reopen_persistence_verified=False,CL_streams_reexported=False)
    journal=Journal(v['receipt_path'],data['marker'],r);backend=_context_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check)
    return run_once(backend,journal,data,v)
