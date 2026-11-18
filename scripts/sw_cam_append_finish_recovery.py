"""Inspect one returned append, then continue only its missing wall definition."""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_append_finish_definitions as base
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
require=base.require
SCOPE='SAVED_CIRCULAR_APPEND_FINISH_RECOVERY_V1'
MODES=('recovery_inspect','recovery_continue')
EXTRA={'mode','failure_receipt_path','failure_receipt_sha256','failure_marker_path','failure_marker_sha256'}
INSPECT={'inspection_receipt_path','inspection_receipt_sha256'}

def recover_floor(before,observed,recipe):
    old=before['operations'];rows=observed['operations']
    require(len(rows)==len(old)+1,'Recovery requires exactly one appended operation; no insertion admitted on ambiguity')
    row=deepcopy(rows[-1]);base.verify_compact(before,observed,[row],recipe['definitions'][0],row['native_id'])
    require(row['native_id'] not in {x['geometry']['native_id'] for x in before['features']}|{x['native_id']for x in before['operation_setups']+before['feature_setups']},'Recovered ID collides with a feature or setup')
    return row

def validate_failure(r,marker,v):
    require(type(r)is dict and r.get('scope')==base.SCOPE and r.get('status')=='uncertain' and r.get('phase')=='finished' and r.get('failed_phase')=='InsertOperation:floor','Exact interrupted floor attempt required')
    require(r.get('reason')=='Dispatch scope is closed, invalid or already claimed' and r.get('issue',{}).get('type')=='ValueError','Only observed consumed-guard failure may be recovered')
    require(set(r.get('actions',{}))=={'InsertOperation:floor'},'Only first insertion may have been attempted')
    action=r['actions']['InsertOperation:floor']
    require(action.get('attempted')is True and action.get('returned')is True and action.get('native_dispatch_pending')is False and action.get('native_return_type')=='POINTER(ICWFinishMillOp3)' and action.get('native_return_value')is None and 'actual_operation_native_id'not in action,'Returned pointer with no observed ID required')
    for k in ('GTP_attempted','GOP_attempted','AFR_attempted','save_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','CL_export_attempted','model_saved','automatic_replay','automatic_rollback'):
        require(r.get(k)is False,'Prior attempt contains another action')
    require(r.get('new_operations')==[] and r.get('marker_created')is True and r.get('native_dispatch_pending')is False and not r.get('runtime_error') and not r.get('cleanup_error'),'Prior failure shape differs')
    clean_events(r)
    require(marker.get('scope')==base.SCOPE and marker.get('status')=='uncertain' and marker.get('automatic_replay')is False and marker.get('receipt_sha256')==v['failure_receipt_sha256'] and Path(marker['receipt_path']).resolve()==Path(v['failure_receipt_path']).resolve(),'Original consumed marker differs')
    require(Path(r['dispatch_marker_path']).resolve()==Path(v['failure_marker_path']).resolve(),'Failure marker path differs')
    request={k:v[k]for k in base.KEYS};prior=deepcopy(r['request']);request.pop('receipt_path');prior.pop('receipt_path')
    require(request==prior,'Recovery owner, source and complete original request must remain exact')
    require(r['source_before_sha256']==v['expected_source_sha256'],'Original source changed')
    require(r.get('mutation_attempted')is True and r.get('operation_creation_attempted')is True,'Exact partial insertion evidence required')
    return r

def validate(v):
    require(type(v)is dict and v.get('mode')in MODES,'Explicit recovery mode required')
    expected=base.KEYS|EXTRA|(INSPECT if v['mode']=='recovery_continue'else set())
    require(set(v)==expected,'Exact recovery request fields required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact owned process required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Explicit qualification scope required')
    for k,val in v.items():
        if k.endswith('_sha256'):require(type(val)is str and re.fullmatch('[0-9a-f]{64}',val),'Exact SHA required')
        if k.endswith('_path'):require(type(val)is str and Path(val).is_absolute(),'Absolute path required')
    source=Path(v['expected_document_path']);require(source.suffix.lower()=='.sldprt' and source.is_file() and not source.is_symlink() and _file_hash(source)==v['expected_source_sha256'],'Exact unchanged saved source required')
    failure,fp=read_pin(v['failure_receipt_path'],v['failure_receipt_sha256']);marker,mp=read_pin(v['failure_marker_path'],v['failure_marker_sha256']);validate_failure(failure,marker,v)
    r,rp=read_pin(v['revision_receipt_path'],v['revision_receipt_sha256']);recipe,p=read_pin(v['recipe_path'],v['recipe_sha256']);oid=r['operation_native_id'];generated=r['postCL']['expected_generated_operations']
    bound=base.binding.bind_completed_revision(rp,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=str(source),source_sha256=v['expected_source_sha256'],selected_operation_ids=[oid],protected_operation_ids=[x['operation_native_id']for x in generated if x['operation_native_id']!=oid],expected_generated_operations=generated,marker_pin=dict(path=v['revision_marker_path'],sha256=v['revision_marker_sha256']),writer_pin=dict(path=base.writer.__file__,sha256=_file_hash(base.writer.__file__)))
    require(recipe==failure['recipe'] and recipe['producer_operation_native_id']==oid,'Original recipe changed');base.validate_recipe(recipe,bound['snapshot'])
    require(base.writer.same(failure['before'],bound['snapshot']),'Original before state differs from saved authority')
    lineage=base.lineage.load_context_lineage(r,bound)
    pins=deepcopy(bound['pins'])+[p,fp,mp]+[dict(path=x,sha256=_file_hash(x))for x in (__file__,base.__file__,base.lineage.__file__,base.defaults.__file__)]
    data=dict(state=deepcopy(bound['snapshot']),recipe=recipe,recipe_pin=p,lineage=lineage,writer_receipt=r,bound=bound,pins=pins,failure=failure,failure_pin=fp,failure_marker_pin=mp)
    if v['mode']=='recovery_continue':
        inspection,ip=read_pin(v['inspection_receipt_path'],v['inspection_receipt_sha256']);validate_inspection(inspection,data,v);data.update(inspection=inspection,inspection_pin=ip);pins.append(ip)
    key=_digest(dict(scope=SCOPE,failure_sha=fp['sha256'],source=str(source.resolve()).casefold(),source_sha=v['expected_source_sha256']))
    data['marker']=source.parent/('recover_append_finish_'+key+'.json');out=Path(v['receipt_path'])
    protected={str(Path(x['path']).resolve()).casefold()for x in pins}|{str(source.resolve()).casefold(),str(data['marker'].resolve()).casefold()}
    require(out.parent.is_dir() and out.suffix.lower()=='.json' and not out.exists() and not out.is_symlink() and str(out.resolve()).casefold()not in protected,'Fresh distinct receipt required')
    require(not data['marker'].exists() and not data['marker'].is_symlink(),'Recovery was already attempted; no replay')
    return data

def validate_observation_inspection(r,data,v):
    require(r.get('scope')==SCOPE and r.get('mode')=='recovery_inspect' and r.get('status')=='review_required' and r.get('phase')=='finished','Completed explicit read-only inspection required')
    for k in ('inspection_verified','readback_verified','runtime_unchanged'):require(r.get(k)is True,'Inspection lacks verification')
    for k in ('mutation_attempted','native_call_attempted','save_attempted','marker_created','GTP_attempted','operation_creation_attempted'):require(r.get(k)is False,'Inspection performed a mutation')
    require(r.get('failure_pin')==data['failure_pin'] and r.get('failure_marker_pin')==data['failure_marker_pin'] and r.get('recipe')==data['recipe'],'Inspection authority differs')
    a=deepcopy(r['request']);b=deepcopy(v)
    for x in (a,b):
        for k in ('mode','receipt_path',*INSPECT):x.pop(k,None)
    require(a==b,'Inspection owner/source/request differs')
    clean_events(r);require(base.writer.same(r['observed'],r['confirm_observed']),'Inspection captures differ')
    require(len(r['new_operations'])==1 and r['new_operations'][0]['native_id']==r['recovered_floor_id'],'Exactly one observed floor required')
    base.verify_appended(data['state'],r['observed'],r['new_operations'])

def validate_inspection(r,data,v):
    validate_observation_inspection(r,data,v)
    require(r['observed_defaults']['finish']['BottomFinOpt']is True,'Observed floor mode missing')

class RecoveryContext(base.AppendContext):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        super().__init__(sw,clsid,tlb,v,data,report,persist,runtime_check)
        self.recovery_mode=v['mode']
    def start(self):
        actual=self.identity();expected=deepcopy(self.append_plan['state']['document'])
        require(type(actual.get('needs_save'))is bool,'Actual strict dirty flag required')
        expected['needs_save']=actual['needs_save'];require(base.fields.equal(actual,expected),'Recovery document identity changed')
        state=deepcopy(self.append_plan['state']);state['document']=deepcopy(actual);self.data['recovery']={'expected_state':state}
        self.report['recovery_initial_document']=deepcopy(actual);self.persist()
        return super().start()
    def operation_defaults(self,oid,row,label):
        if self.recovery_mode=='recovery_inspect':return self.read_operation_defaults(oid,row,label)
        return super().operation_defaults(oid,row,label)
    def insert(self,*a,**k):
        require(self.recovery_mode=='recovery_continue','Read-only inspection forbids insertion')
        require(a[0]['role']=='wall','Recovery can insert only missing wall')
        return super().insert(*a,**k)
    def save(self,**k):
        require(self.recovery_mode=='recovery_continue','Read-only inspection forbids Save');return super().save(**k)
    def generate(self,*a,**k):raise ValueError('Recovery never generates toolpaths')

class Journal(base.Journal):
    def marker_state(self):
        r=super().marker_state();r.update(scope=SCOPE,failure_receipt_pin=self.report['failure_pin']);return r
    def pending(self,name):
        require(self.report['mode']=='recovery_continue' and name in ('InsertOperation:wall','SaveActiveDocument'),'Only missing wall and one Save allowed')
        super().pending(name)

def run_once(backend,journal,data,v):
    r=journal.report
    def observe(label):
        detail=dict(label=label,capture_complete=False,state={});r['captures'].append(detail);r['phase']=label;journal.persist()
        state=backend.capture(label,detail['state']);require(all(state.get(k)is True for k in ('capture_complete','parameter_capture_complete','extended_capture_complete')),'Complete full capture required');detail.update(capture_complete=True,state=deepcopy(state));r[label]=deepcopy(state);journal.persist();return state
    try:
        journal.create();backend.start();r['phase']='read_existing_floor';journal.persist()
        compact=backend.compact('recovery_route');floor=recover_floor(data['state'],compact,data['recipe']);r.update(recovered_floor_id=floor['native_id'],new_operations=[floor]);journal.persist();backend.added_rows=[floor]
        value=backend.operation_defaults(floor['native_id'],data['recipe']['definitions'][0],'recovered_floor');base.defaults.validate_defaults(value)
        role_verified=value['finish']['BottomFinOpt']is True
        r.update(observed_defaults=deepcopy(value),role_defaults_verified=role_verified,configuration_required=not role_verified);journal.persist()
        if v['mode']=='recovery_continue':require(role_verified,'Existing floor default differs; observations do not authorize continuation')
        observed=observe('observed');base.verify_appended(data['state'],observed,[floor])
        if v['mode']=='recovery_inspect':
            confirm=observe('confirm_observed');require(base.writer.same(observed,confirm),'Read-only inspection state changed');backend.finish();r.update(status='review_required',phase='finished',inspection_verified=True,readback_verified=True,runtime_unchanged=True,reason='ONE_EXISTING_FLOOR_INSPECTED_NO_MUTATION')
        else:
            old=data['inspection'];require(base.writer.same(observed,old['confirm_observed']) and base.fields.equal(value,old['observed_defaults']) and floor==old['new_operations'][0],'Actual recovery state differs from pinned inspection')
            backend.boundary();journal.claim();definition=data['recipe']['definitions'][1];name='InsertOperation:wall';journal.action(name)
            oid=backend.insert(definition,floor['native_id'],pending=lambda:journal.pending(name),returned=lambda x:journal.returned(name,x));r['actions'][name]['actual_operation_native_id']=oid;journal.persist()
            compact=backend.compact('after_wall_route');rows=[x for x in compact['operations']if x['native_id']==oid];require(len(rows)==1,'Unique actual wall required');added=[floor,deepcopy(rows[0])];base.verify_compact(data['state'],compact,added,definition,oid)
            wall=backend.operation_defaults(oid,definition,'after_wall');base.defaults.validate_defaults(wall);require(wall['finish']['BottomFinOpt']is False,'Wall default differs');backend.added_rows=added;r.update(new_operations=deepcopy(added),inserted_defaults=[deepcopy(value),deepcopy(wall)]);journal.persist()
            inserted=observe('inserted');r['append_proof']=base.verify_appended(data['state'],inserted,added);backend.boundary();journal.action('SaveActiveDocument');r['save_stage']={'before_state_reused_from':'inserted','save_pending':False};journal.persist()
            def returned(x):
                journal.returned('SaveActiveDocument',x);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(x).__name__,native_return_value=x if type(x)in(int,bool,float,str)or x is None else None);journal.persist()
            journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha);journal.persist()
            saved=observe('saved');base.writer.CircularGenerationProof(backend,reference=data['state']).verify_saved(inserted,saved)
            values=[]
            for row,definition in zip(added,data['recipe']['definitions']):
                val=backend.operation_defaults(row['native_id'],definition,'saved_'+definition['role']);require(base.fields.equal(val,r['inserted_defaults'][len(values)]),'Defaults changed during Save');values.append(val)
            r['saved_defaults']=values;journal.persist();confirm=observe('confirm_saved');require(base.writer.same(saved,confirm),'Two complete saved captures differ');r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,definitions_verified=True,reason='EXISTING_FLOOR_AND_NEW_WALL_SAVED_WITH_PROTECTED_ROUTE',generation_performed=False,parameters_configured=False)
    except Exception as e:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r['phase'],phase='finished',issue=_error(e),reason=str(e),readback_verified=False,runtime_unchanged=False,definitions_verified=False,inspection_verified=False)
    finally:
        try:backend.close()
        except Exception as e:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(e),readback_verified=False,runtime_unchanged=False,definitions_verified=False,inspection_verified=False)
        journal.persist()
    return r

def dispatch(sw,clsid,tlb,values,*,runtime_check=None,_context_factory=RecoveryContext):
    require(callable(runtime_check),'Runtime guard required');data=validate(values);v=values;require(data['lineage']['loaded']['addin_clsid'].casefold()==clsid.casefold(),'Bound add-in differs');abi=base.preflight(tlb)
    r=dict(scope=SCOPE,mode=v['mode'],status='error',phase='preflight',request=deepcopy(v),recipe=deepcopy(data['recipe']),recipe_pin=data['recipe_pin'],receipt_path=v['receipt_path'],dispatch_marker_path=str(data['marker']),source_before_sha256=v['expected_source_sha256'],authority_pin=data['bound']['receipt_pin'],historical_CL_pin=data['lineage']['cl_pin'],failure_pin=data['failure_pin'],failure_marker_pin=data['failure_marker_pin'],inspection_pin=data.get('inspection_pin'),evidence_pins=deepcopy(data['pins']),abi=abi,actions={},captures=[],new_operations=[],native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,operation_creation_attempted=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,save_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,automatic_replay=False,automatic_rollback=False,model_saved=False,save_readback_verified=False,source_update_verified=False,readback_verified=False,definitions_verified=False,inspection_verified=False,role_defaults_verified=False,configuration_required=True,runtime_unchanged=False,production_qualified=False,reopen_persistence_verified=False,CL_streams_reexported=False)
    journal=Journal(v['receipt_path'],data['marker'],r);backend=_context_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check);return run_once(backend,journal,data,v)

def finalize_runtime_failure(result,error):
    result.update(status='uncertain'if result.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,definitions_verified=False,inspection_verified=False,production_qualified=False);_write_receipt(Path(result['receipt_path']),result)
    if result.get('marker_created'):_write_receipt(Path(result['dispatch_marker_path']),dict(scope=SCOPE,status=result['status'],receipt_path=result['receipt_path'],receipt_sha256=_file_hash(result['receipt_path']),automatic_replay=False))
    return result
