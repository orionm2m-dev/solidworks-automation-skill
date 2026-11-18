"""Append one floor Rough and one wall Finish after an inspected empty draft."""
from copy import deepcopy
from pathlib import Path
from comtypes.automation import IDispatch
from scripts import sw_cam_append_finish_definitions as base
from scripts import sw_cam_append_finish_recovery as recovery
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_comtypes import _is_comtypes_pointer
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts import sw_cam_mill_current_parameters as parameters
require=base.require
writer=base.writer
fields=base.fields
SCOPE='SAVED_CIRCULAR_FLOOR_WALL_APPEND_V1'
MODE='recovery_append_floor_wall'
KEYS=base.KEYS|recovery.EXTRA|recovery.INSPECT|{'continuation_recipe_path','continuation_recipe_sha256'}
ROW_KEYS=base.ROW_KEYS|{'operation_kind'}

def project_pair(before,after,added_rows):
    out=deepcopy(after);old=before['operations'];ids=[r['native_id'] for r in added_rows]
    require(len(ids)<=2 and len(set(ids))==len(ids) and not(set(ids)&{r['native_id'] for r in old}),'Fresh bounded added IDs required')
    require([r['native_id'] for r in out['operations']]==[r['native_id'] for r in old]+ids,'Only exact ordered suffix may be added')
    require(fields.equal(out['operations'][-len(ids):],added_rows) if ids else fields.equal(out['operations'],old),'Actual addition rows differ')
    anchor=old[-1]
    for i,row in enumerate(added_rows):
        require(type(row['native_id'])is int and row['native_id']>0 and row['mill_operation_type']==(0,1)[i] and type(row['mill_operation_type'])is int and row['suppressed']is False and row['toolpath_generated']is False and row['toolpath_record_counts']==[],'New suffix must remain empty Rough then Finish')
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

def verify_pair(before,after,added_rows):
    out=project_pair(before,after,added_rows);reference=deepcopy(before)
    for state in (out,reference):
        for key in ('document','sketch_state'):
            require(type(state[key]['needs_save'])is bool,'Strict dirty flags required');state[key]['needs_save']=False
    require(writer.same(reference,out),'Insertion changed a protected state, tool, feature, parameter or path')
    return dict(existing_operation_count=len(before['operations']),new_operation_ids=[r['native_id']for r in added_rows],generated_operations_preserved=True,tool_catalogue_preserved=True,feature_geometry_preserved=True,protected_parameters_preserved=True)

def validate_recipe(recipe,state,draft):
    require(type(recipe)is dict and set(recipe)=={'scope','anchor_operation_native_id','protected_draft_native_id','definitions'},'Exact floor/wall recipe required')
    require(recipe['scope']==SCOPE and type(recipe['anchor_operation_native_id'])is int and recipe['anchor_operation_native_id']==recipe['protected_draft_native_id']==draft['native_id']==state['operations'][-1]['native_id'],'Exact inspected draft anchor required')
    require(draft['mill_operation_type']==1 and draft['toolpath_generated']is False and draft['toolpath_record_counts']==[],'Protected draft must remain empty Finish')
    rows=recipe['definitions'];require(type(rows)is list and len(rows)==2 and [r.get('role')for r in rows]==['floor','wall'],'Exactly floor then wall required')
    require(len(state['operations'])+2<=32,'Bounded route required')
    for i,row in enumerate(rows):
        require(type(row)is dict and set(row)==ROW_KEYS,'Exact definition fields required')
        require(type(row['operation_kind'])is int and row['operation_kind']==(0,1)[i],'Fixed Rough then Finish kinds required')
        for k in ('feature_native_id','feature_owner_setup_native_id','operation_setup_native_id','default_operation_id'):require(type(row[k])is int and row[k]>0,'Strict positive native identity required')
        require(type(row['default_operation_name'])is str and 0<len(row['default_operation_name'])<=128,'Explicit native default name required')
        require(row['expected_bottom_finish']is(None if i==0 else False),'Rough has no Finish bottom mode; wall must have bottom disabled')
        target=state['target_header']if i==0 else state['reference_header'];require(row['feature_native_id']==target['native_id'] and target['suppressed']is False,'Exact existing feature required')
        found=[x for x in state['features']if x['geometry']['native_id']==row['feature_native_id']];require(len(found)==1 and found[0]['setup_native_id']==row['feature_owner_setup_native_id']==state['selected_operation_setup']['feature_setup_native_id'],'Exact owner setup required')
        require(row['operation_setup_native_id']==draft['setup_native_id'],'Append must remain in same setup')
        catalog=state['target_catalogues']if i==0 else state['default_operation_catalogues'];entries=[x for c in catalog if c['operation_type']==row['operation_kind']for x in c['entries']if x['name']==row['default_operation_name']and x['default_operation_id']==row['default_operation_id']];require(len(entries)==1,'Actual catalogue lacks selected exact kind/default')
    return deepcopy(recipe)

def validate(v):
    require(type(v)is dict and set(v)==KEYS and v['mode']==MODE,'Exact explicit floor/wall continuation required')
    values={k:v[k]for k in base.KEYS|recovery.EXTRA};values['mode']='recovery_inspect';data=recovery.validate(values)
    inspection,ip=read_pin(v['inspection_receipt_path'],v['inspection_receipt_sha256']);prior_request={k:v[k]for k in base.KEYS|recovery.EXTRA|recovery.INSPECT};prior_request['mode']='recovery_continue';recovery.validate_observation_inspection(inspection,data,prior_request)
    require(inspection.get('role_defaults_verified')is False and inspection.get('configuration_required')is True and inspection['observed_defaults']['finish']['BottomFinOpt']is False,'Explicit inspected unconfigured draft required')
    state=deepcopy(inspection['confirm_observed']);draft=deepcopy(inspection['new_operations'][0]);recipe,rp=read_pin(v['continuation_recipe_path'],v['continuation_recipe_sha256']);validate_recipe(recipe,state,draft)
    data.update(original_state=deepcopy(data['state']),state=state,failure_recipe=deepcopy(data['recipe']),recipe=recipe,recipe_pin=rp,inspection=inspection,inspection_pin=ip,draft=draft)
    data['pins'].extend([ip,rp,dict(path=__file__,sha256=_file_hash(__file__)),dict(path=recovery.__file__,sha256=_file_hash(recovery.__file__))])
    key=_digest(dict(scope=SCOPE,original_failure_sha=data['failure_pin']['sha256'],source=v['expected_source_sha256']));data['marker']=Path(v['expected_document_path']).parent/('append_floor_wall_'+key+'.json')
    require(not data['marker'].exists() and not data['marker'].is_symlink(),'Floor/wall continuation already attempted; no replay')
    out=Path(v['receipt_path']);require(out.resolve()!=data['marker'].resolve() and all(out.resolve()!=Path(x['path']).resolve()for x in data['pins']),'Output aliases evidence')
    return data

class Context(base.AppendContext):
    def start(self):
        actual=self.identity();expected=deepcopy(self.append_plan['state']['document'])
        require(type(actual.get('needs_save'))is bool,'Actual strict dirty flag required')
        expected['needs_save']=actual['needs_save'];require(base.fields.equal(actual,expected),'Recovery document identity changed')
        state=deepcopy(self.append_plan['state']);state['document']=deepcopy(actual);self.data['recovery']={'expected_state':state}
        self.report['recovery_initial_document']=deepcopy(actual);self.persist()
        return super().start()
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        super().__init__(sw,clsid,tlb,v,data,report,persist,runtime_check)
        self._native_read_limit=20000
    def generate(self,*a,**k):raise ValueError('Definition continuation never generates')
    def insert(self,row,anchor_id,*,pending,returned):
        kind=row['operation_kind'];require(type(kind)is int and kind in(0,1),'Explicit fixed operation kind required')
        with self.guard()as g:
            found=g.read(self.native['doc'],'GetCWObjectFromID',1,row['feature_native_id']);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Existing feature lookup failed');feature=g.typed(found[0],'ICWMillFeature');header,_=read_header(feature,self.native['doc'],g.read,g.typed,row['feature_owner_setup_native_id']);require(fields.equal(header,base.feature_header(self.append_plan['state'],row['feature_native_id'])),'Feature changed before insertion')
            found=g.read(self.native['doc'],'GetCWObjectFromID',3,anchor_id);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact anchor lookup failed');anchor=g.read(found[0],'QueryInterface',IDispatch);require(_object_id(self.native['doc'],anchor,g.read)==anchor_id,'Anchor differs')
            actual=g.read(feature,'GetTdbIdForDefaultOperation',kind,row['default_operation_name']);require(type(actual)is int and actual==row['default_operation_id'],'Actual selected kind/default differs')
            def invoke():
                value=_member(feature,'InsertOperation',kind,actual,anchor);returned(value);return value
            raw=g.dispatch_once(invoke,persist_pending=pending)
        require(_is_comtypes_pointer(raw)and bool(raw),'Nonnull actual pointer required')
        with self.guard()as post:oid=_object_id(self.native['doc'],raw,post.read)
        forbidden={r['native_id']for r in self.append_plan['state']['operations']+self.added_rows}|{r['geometry']['native_id']for r in self.append_plan['state']['features']}|{r['native_id']for r in self.append_plan['state']['operation_setups']+self.append_plan['state']['feature_setups']}
        require(type(oid)is int and oid>0 and oid not in forbidden,'New ID collision');return oid
    def own_nc(self,oid):
        out={'operation_native_id':oid}
        with self.guard()as g:
            found=g.read(self.native['doc'],'GetCWObjectFromID',3,oid);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True and _object_id(self.native['doc'],found[0],g.read)==oid,'Exact own NC target required')
            base.parameter_capture.read_own_nc(found[0],out,read=g.read,typed=g.typed,boundary=self.boundary)
        return out
    def draft_witness(self,label):
        draft=self.append_plan['draft'];definition=self.append_plan['failure_recipe']['definitions'][0]
        out={'operation_native_id':draft['native_id'],'defaults':self.read_operation_defaults(draft['native_id'],definition,label),'own_nc':self.own_nc(draft['native_id'])};base.defaults.validate_defaults(out['defaults']);self.report[label]=deepcopy(out);self.persist();return out
    def operation_observation(self,row,definition,label):
        out=dict(operation_native_id=row['native_id'],operation_kind=definition['operation_kind'],feature_native_id=definition['feature_native_id'])
        if definition['operation_kind']==1:out['defaults']=self.operation_defaults(row['native_id'],definition,label);base.defaults.validate_defaults(out['defaults'])
        else:
            state={}
            with self.guard()as g:
                found=g.read(self.native['doc'],'GetCWObjectFromID',1,definition['feature_native_id']);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True and _object_id(self.native['doc'],found[0],g.read)==definition['feature_native_id'],'Exact Rough feature required')
                parameters.capture_rows(state,dict(self.native,selected_feature=found[0]),[row],feature_id=definition['feature_native_id'],read=g.read,typed=g.typed,boundary=self.boundary,expected_operation_types=(0,))
            require(state.get('parameter_capture_complete')is True and len(state['operation_parameters'])==1,'Complete Rough parameter observation required');out['parameters']=state['operation_parameters'][0]
        out['own_nc']=self.own_nc(row['native_id']);self.report.setdefault('operation_observations',{})[label]=deepcopy(out);self.persist();return out

class Journal(base.Journal):
    def marker_state(self):
        r=super().marker_state();r.update(scope=SCOPE,inspection_pin=self.report['inspection_pin'],failure_receipt_pin=self.report['failure_pin']);return r

def verify_compact(before,observed,added,definition,oid):
    baseline={k:deepcopy(before[k])for k in base.BASE_KEYS};actual={k:deepcopy(observed[k])for k in base.BASE_KEYS};require(fields.equal(baseline,project_pair(baseline,actual,added)),'Compact route changed outside exact suffix')
    require(fields.equal(observed['target_header'],before['reference_header'])and fields.equal(observed['profile'],before['reference_profile']),'Compound reference feature changed')
    row=added[-1];require(row['native_id']==oid and row['linked_feature_ids']==[definition['feature_native_id']]and row['setup_native_id']==definition['operation_setup_native_id'],'Actual feature/setup link differs')

def run_once(backend,journal,data,v):
    r=journal.report;added=[];observations=[]
    def observe(label):
        detail=dict(label=label,capture_complete=False,state={});r['captures'].append(detail);r['phase']=label;journal.persist();state=backend.capture(label,detail['state']);require(all(state.get(k)is True for k in ('capture_complete','parameter_capture_complete','extended_capture_complete')),'Complete full capture required');detail.update(capture_complete=True,state=deepcopy(state));r[label]=deepcopy(state);journal.persist();return state
    try:
        journal.create();backend.start();before=observe('before');require(writer.same(before,data['state']),'Actual 27-operation RAM state differs from inspection');validate_recipe(data['recipe'],before,data['draft'])
        draft=backend.draft_witness('draft_before');require(fields.equal(draft['defaults'],data['inspection']['observed_defaults']),'Draft defaults changed since inspection');r['draft_before']=deepcopy(draft);backend.boundary();journal.claim();anchor=data['draft']['native_id']
        for definition in data['recipe']['definitions']:
            name='InsertOperation:'+definition['role'];journal.action(name);oid=backend.insert(definition,anchor,pending=lambda n=name:journal.pending(n),returned=lambda value,n=name:journal.returned(n,value));r['actions'][name]['actual_operation_native_id']=oid;journal.persist()
            compact=backend.compact('after_'+definition['role']+'_route');found=[x for x in compact['operations']if x['native_id']==oid];require(len(found)==1,'Unique actual appended ID required');candidate=added+[deepcopy(found[0])];verify_compact(before,compact,candidate,definition,oid)
            value=backend.operation_observation(found[0],definition,'after_'+definition['role']);added=candidate;observations.append(value);backend.added_rows=deepcopy(added);r.update(new_operations=deepcopy(added),inserted_observations=deepcopy(observations));journal.persist();anchor=oid
        inserted=observe('inserted');r['append_proof']=verify_pair(before,inserted,added);require(fields.equal(backend.draft_witness('draft_after_insert'),draft),'Draft defaults or NC changed during append')
        backend.boundary();journal.action('SaveActiveDocument');r['save_stage']={'before_state_reused_from':'inserted','save_pending':False};journal.persist()
        def returned(x):
            journal.returned('SaveActiveDocument',x);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(x).__name__,native_return_value=x if type(x)in(int,bool,float,str)or x is None else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha);journal.persist();saved=observe('saved');writer.CircularGenerationProof(backend,reference=before).verify_saved(inserted,saved)
        saved_values=[]
        for row,definition,value in zip(added,data['recipe']['definitions'],observations):
            actual=backend.operation_observation(row,definition,'saved_'+definition['role']);require(fields.equal(actual,value),'New operation parameters changed during Save');saved_values.append(actual)
        r['saved_observations']=saved_values;require(fields.equal(backend.draft_witness('draft_saved'),draft),'Protected draft changed during Save');journal.persist();confirm=observe('confirm_saved');require(writer.same(saved,confirm),'Two saved full states differ');require(fields.equal(backend.draft_witness('draft_confirm'),draft),'Protected draft changed after Save');r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);backend.boundary();backend.finish();r.update(status='review_required',phase='finished',definitions_verified=True,definitions_saved=True,readback_verified=True,runtime_unchanged=True,parameters_configured=False,machining_eligible=False,generation_performed=False,reason='ROUGH_FLOOR_AND_FINISH_WALL_DEFINITIONS_SAVED_DRAFT_PRESERVED')
    except Exception as e:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r['phase'],phase='finished',issue=_error(e),reason=str(e),definitions_verified=False,definitions_saved=False,readback_verified=False,runtime_unchanged=False)
    finally:
        try:backend.close()
        except Exception as e:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(e),definitions_verified=False,definitions_saved=False,readback_verified=False,runtime_unchanged=False)
        journal.persist()
    return r

def dispatch(sw,clsid,tlb,values,*,runtime_check=None,_context_factory=Context):
    require(callable(runtime_check),'Runtime guard required');v=values;data=validate(v);require(data['lineage']['loaded']['addin_clsid'].casefold()==clsid.casefold(),'Add-in differs');abi=base.preflight(tlb)
    r=dict(scope=SCOPE,mode=MODE,status='error',phase='preflight',request=deepcopy(v),recipe=deepcopy(data['recipe']),failure_recipe=deepcopy(data['failure_recipe']),recipe_pin=data['recipe_pin'],receipt_path=v['receipt_path'],dispatch_marker_path=str(data['marker']),source_before_sha256=v['expected_source_sha256'],authority_pin=data['bound']['receipt_pin'],historical_CL_pin=data['lineage']['cl_pin'],failure_pin=data['failure_pin'],failure_marker_pin=data['failure_marker_pin'],inspection_pin=data['inspection_pin'],evidence_pins=deepcopy(data['pins']),protected_draft_native_id=data['draft']['native_id'],future_machining_excluded_operation_ids=[data['draft']['native_id']],abi=abi,actions={},captures=[],new_operations=[],native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,operation_creation_attempted=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,save_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,automatic_replay=False,automatic_rollback=False,model_saved=False,save_readback_verified=False,source_update_verified=False,readback_verified=False,definitions_verified=False,definitions_saved=False,runtime_unchanged=False,parameters_configured=False,machining_eligible=False,production_qualified=False,reopen_persistence_verified=False,CL_streams_reexported=False)
    journal=Journal(v['receipt_path'],data['marker'],r);backend=_context_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check);return run_once(backend,journal,data,v)

def finalize_runtime_failure(result,error):
    result.update(status='uncertain'if result.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,definitions_verified=False,definitions_saved=False,machining_eligible=False,production_qualified=False);_write_receipt(Path(result['receipt_path']),result)
    if result.get('marker_created'):_write_receipt(Path(result['dispatch_marker_path']),dict(scope=SCOPE,status=result['status'],receipt_path=result['receipt_path'],receipt_sha256=_file_hash(result['receipt_path']),automatic_replay=False))
    return result
