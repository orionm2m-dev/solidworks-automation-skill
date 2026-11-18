"""Append one explicit ordinary circular Finish to a saved partial-result baseline."""
from copy import deepcopy
from pathlib import Path
import math,re,json
from scripts import sw_cam_current_circular_finish_delta as delta
from scripts import sw_cam_current_circular_finish_owner as owner_authority
from scripts import sw_cam_current_saved_generation as engine
from scripts import sw_cam_partial_floor_wall_generation_save as partial
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _error
require=delta.require;exact=delta.exact
SCOPE='CURRENT_SAVED_ORDINARY_CIRCULAR_FINISH_DEFINITION_V1'
RECIPE_SCOPE='LOWER_D18_DEPTH71_ORDINARY_FINISH_DEFINITION_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','saved_result_receipt_path','saved_result_receipt_sha256','recipe_path','recipe_sha256','receipt_path','action','prepare_receipt_path','prepare_receipt_sha256','qualification_only','message_policy'}
SPEC_KEYS={'sketch_spec','depth_native','expected_setup_axis','reverse_direction','owner_setup_native_id','operation_setup_native_id','insert_after_operation_native_id','candidate_tool_native_id','finish_definition','expected_default_tool'}

def binding(v):return{k:deepcopy(x)for k,x in v.items()if k not in('action','receipt_path','prepare_receipt_path','prepare_receipt_sha256')}
def marker_path(v):return Path(v['expected_document_path']).parent/('circular_finish_'+_digest(dict(scope=SCOPE,binding=binding(v)))+'.json')

def validate_recipe(recipe,state):
    require(type(recipe)is dict and set(recipe)=={'scope','spec'}and recipe['scope']==RECIPE_SCOPE,'Exact one-circle Finish recipe required');v=recipe['spec'];require(type(v)is dict and set(v)==SPEC_KEYS,'Exact bounded geometry/Finish specification required');delta.geometry_spec(v)
    for k in('owner_setup_native_id','operation_setup_native_id','insert_after_operation_native_id','candidate_tool_native_id'):require(type(v[k])is int and 0<v[k]<2**31,'Strict explicit native identity required')
    require(v['owner_setup_native_id']==71 and v['operation_setup_native_id']==94 and v['insert_after_operation_native_id']==state['operations'][-1]['native_id']==368 and v['candidate_tool_native_id']==249,'Exact lower owner/setup, retained tail and shared candidate required')
    owner=next(x for x in state['feature_setups']if x['native_id']==v['owner_setup_native_id']);require(delta.circle.vector(owner['axis_native'],v['expected_setup_axis']),'Saved lower setup direction differs')
    choice=v['finish_definition'];require(type(choice)is dict and set(choice)=={'default_operation_name','default_operation_id'}and type(choice['default_operation_name'])is str and 0<len(choice['default_operation_name'])<=1000 and '\x00'not in choice['default_operation_name']and type(choice['default_operation_id'])is int and choice['default_operation_id']>0,'Explicit actual catalogue expectation required')
    tool=v['expected_default_tool'];require(type(tool)is dict and set(tool)=={'tool_type_raw','cut_diameter_native','protrusion_native'}and type(tool['tool_type_raw'])is int and tool['tool_type_raw']>=0,'Explicit default tool expectation required')
    for k in('cut_diameter_native','protrusion_native'):require(type(tool[k])is float and math.isfinite(tool[k])and 0<tool[k]<=1000,'Positive native default-tool dimensions required')
    return deepcopy(v)

def outputs(v,pins):
    out=Path(v['receipt_path']);marker=marker_path(v);protected={Path(v['expected_document_path']).resolve(),*(Path(p['path']).resolve()for p in pins)}
    for p in(out,marker):require(p.is_absolute()and p.parent.is_dir()and p.suffix.lower()=='.json'and not p.exists()and not p.is_symlink()and p.resolve()not in protected,'Fresh distinct result/marker required')
    require(out.resolve()!=marker.resolve(),'Receipt aliases marker');return out,marker

def validate_file_only_prepare(prep,v,data,rp,pins):
    require(prep.get('scope')==SCOPE and prep.get('action')=='prepare'and prep.get('phase')=='finished'and prep.get('status')=='review_required','Completed file-only prepare required')
    require(all(prep.get(k)is True for k in('receipt_created','readback_verified','runtime_unchanged','may_apply')),'Successful persisted prepare required')
    false_fields=('marker_created','mutation_attempted','native_observation_performed','native_dispatch_pending','native_call_attempted','native_call_returned','GTP_attempted','GOP_attempted','AFR_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','CL_export_attempted','reference_geometry_creation_attempted','operation_creation_attempted','save_attempted','model_saved','save_readback_verified','source_update_verified','definition_saved_verified','automatic_replay','automatic_rollback','production_qualified','machining_eligible','reopen_persistence_verified')
    require(all(prep.get(k)is False for k in false_fields),'Prepare must contain no native activity or release claims')
    require(type(prep.get('native_read_count'))is int and prep['native_read_count']==0 and all(exact(prep.get(k),{})for k in('actions','target_observations','draft_observations'))and exact(prep.get('captures'),[]),'Prepare must contain no native observations')
    require(prep.get('before_provenance')==owner_authority.prepare_provenance(data)and prep.get('reason')=='FILE_ONLY_SAVED_RESULT_PREPARE_APPLY_REQUIRES_FRESH_FULL_RAM_READ'and not any(k in prep for k in('issue','runtime_error','cleanup_error','messages')),'Exact file-only provenance without native event session required')
    require(exact(prep.get('binding'),binding(v))and exact(prep.get('recipe_pin'),rp)and exact(prep.get('authority_pin'),data.get('authority_pin',data['pin']))and exact(prep.get('raw_saved_result_pin'),data['pin']),'Prepare authority/recipe/request differs')
    request=prep.get('request');require(type(request)is dict and set(request)==KEYS and request.get('action')=='prepare'and request.get('prepare_receipt_path')is None and request.get('prepare_receipt_sha256')is None and exact(binding(request),binding(v)),'Exact original prepare request required')
    require(prep.get('source_before_sha256')==v['expected_source_sha256']and Path(prep['receipt_path']).resolve()==Path(v['prepare_receipt_path']).resolve()and request['receipt_path']==prep['receipt_path'],'Prepare source/output differs')
    def pin_map(items):
        require(type(items)is list,'Complete prepare evidence pins required');result={}
        for p in items:
            key=str(Path(p['path']).resolve()).casefold();require(key not in result or result[key]==p['sha256'],'Conflicting prepare pins');result[key]=p['sha256']
        return result
    require(exact(pin_map(prep.get('evidence_pins')),pin_map(pins)),'Prepare evidence/runtime pins changed')
    from scripts import sw_cam_current_circular_finish_owner as owner
    require(exact(prep.get('owner_comparison_projection'),owner.prepare_projection(data)),'Prepare owner projection differs');owner.verify_projection(data,v)
    require(delta.mixed.same(prep['before'],data['state']),'Prepare saved baseline differs')

def validate(v):
    require(type(v)is dict and set(v)==KEYS and v['action']in('prepare','apply')and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact qualification-only prepare/apply request required')
    require(type(v['process_id'])is int and v['process_id']>0 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact owner lifetime required')
    for k,x in v.items():
        if k.endswith('_sha256')and x is not None:require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact lowercase digest required')
        if k.endswith('_path')and x is not None:require(type(x)is str and Path(x).is_absolute(),'Explicit absolute path required')
    source=Path(v['expected_document_path']);require(source.is_file()and not source.is_symlink()and source.suffix.lower()=='.sldprt'and _file_hash(source)==v['expected_source_sha256'],'Exact saved native source required')
    from scripts import sw_cam_current_circular_finish_owner as authority
    data=authority.load_completed(v['saved_result_receipt_path'],v['saved_result_receipt_sha256'],process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'])
    delta.validate_baseline(data['state']);recipe,rp=read_pin(v['recipe_path'],v['recipe_sha256']);spec=validate_recipe(recipe,data['state']);pins=list(data['pins'])+[rp]
    for path in(__file__,delta.__file__,authority.__file__,Path(__file__).with_name('sw_cam_current_circular_finish_context.py')):pins.append(partial._filepin(path))
    data.update(recipe=recipe,recipe_pin=rp,spec=spec,prepared_receipt=None)
    if v['action']=='apply':
        require(type(v['prepare_receipt_path'])is str and type(v['prepare_receipt_sha256'])is str,'Exact completed prepare pin required');prep,pp=read_pin(v['prepare_receipt_path'],v['prepare_receipt_sha256'])
        validate_file_only_prepare(prep,v,data,rp,pins);data['prepared_receipt']=prep;pins.append(pp)
    else:require(v['prepare_receipt_path']is None and v['prepare_receipt_sha256']is None,'Prepare rejects previous prepare pins')
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting evidence pins');unique[key]=partial._observed_pin(p)
    data['pins']=list(unique.values());data['output'],data['marker']=(str(p)for p in outputs(v,data['pins']));return data

_ISSUER=object()
class _Prepared:
    def __init__(self,v,data,pins):self.issuer=_ISSUER;self.v=deepcopy(v);self.data=deepcopy(data);self.pins=deepcopy(pins);self.used=False;self.digest=self.fingerprint()
    def fingerprint(self):return _digest(dict(v=self.v,data=self.data,pins=self.pins))
def _prepare_invocation(v,*,runtime_check):
    runtime_check();data=validate(v);pins=[partial._observed_pin(p)for p in data['pins']]+[partial._observed_pin(dict(path=v['expected_document_path'],sha256=v['expected_source_sha256']))];runtime_check();return _Prepared(v,data,pins)
def consume(bundle,v,runtime_check):
    require(type(bundle)is _Prepared and bundle.issuer is _ISSUER and bundle.used is False,'Private unused preparation required');bundle.used=True;require(exact(bundle.v,v)and bundle.fingerprint()==bundle.digest,'Prepared request or authority changed');runtime_check()
    for p in bundle.pins:partial._observed_pin(p)
    require(outputs(v,bundle.data['pins'])==(Path(bundle.data['output']),Path(bundle.data['marker'])),'Outputs changed');runtime_check();return bundle.data

class Journal(engine.Journal):
    def marker_state(self):return dict(scope=SCOPE,status=self.report['status'],phase=self.report['phase'],binding=self.report['binding'],authority_pin=self.report['authority_pin'],receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),automatic_replay=False)
    def pending(self,name):
        require(name in('CreateSketch','CreateMillFeature2','InsertOperation','SaveActiveDocument'),'Only explicit definition actions permitted');self.report['mutation_attempted']=True
        if name in('CreateSketch','CreateMillFeature2'):self.report['reference_geometry_creation_attempted']=True
        if name=='InsertOperation':self.report['operation_creation_attempted']=True
        super().pending(name)
    def returned(self,name,value):
        super().returned(name,value)
        if type(value)is dict:self.report['actions'][name]['native_observation']=deepcopy(value);self.persist()

def verify_compact(before,observed,spec,fid,oid,names):
    require(observed.get('scope')=='CIRCULAR_FINISH_COMPACT_PRE_SAVE_V1'and observed.get('full_parameter_capture')is False,'Explicit compact observation required')
    raw=observed['inventory'];rows=raw['operations'];require(len(rows)==len(before['operations'])+1 and exact(rows[:-1],before['operations']),'All29 retained operation rows must remain exact')
    row=rows[-1];require(row['native_id']==oid and type(row['mill_operation_type'])is int and row['mill_operation_type']==1 and row['linked_feature_ids']==[fid]and row['setup_native_id']==spec['operation_setup_native_id']and row['suppressed']is False and row['toolpath_generated']is False and exact(row['toolpath_record_counts'],[]),'Only actual empty new circle Finish required')
    require(all(exact(row['assigned_tool'].get(k),v)for k,v in spec['expected_default_tool'].items()),'New default tool differs')
    keys=('features','feature_setups','operation_counts','selected_operation_setup','operation_setups','operation_setup_count','operation_count','operation_inventory_scope')
    actual={k:deepcopy(raw[k])for k in keys};expected={k:deepcopy(before[k])for k in keys}
    added=[r for r in actual['features']if r['geometry']['native_id']==fid];require(len(added)==1 and added[0]['setup_native_id']==spec['owner_setup_native_id'],'One new feature in owner required');actual['features']=[r for r in actual['features']if r['geometry']['native_id']!=fid]
    owner=next(r for r in actual['feature_setups']if r['native_id']==spec['owner_setup_native_id']);require(owner['feature_ids'].count(fid)==1,'One feature membership required');owner['feature_ids'].remove(fid)
    si=row['setup_index'];require(type(si)is int and 0<=si<len(actual['operation_setups'])and actual['operation_setups'][si]['native_id']==spec['operation_setup_native_id']and row['operation_index']==expected['operation_setups'][si]['operation_count'],'Exact setup tail required')
    actual['operation_setups'][si]['operation_count']-=1;actual['operation_counts'][si]-=1;actual['operation_count']-=1;actual['selected_operation_setup']['operation_count']-=1;require(exact(actual,expected),'Compact route/feature/setup delta differs')
    for key,target in(('target_header','reference_header'),('profile','reference_profile'),('number_of_steps_raw','reference_number_of_steps_raw')):require(exact(raw[key],before[target]),'Reference compound geometry changed')
    witness=before[delta.mixed.PAIR_KEY];require(exact(observed['selected_targets'],witness['targets'])and exact(observed['retained_draft'],witness['draft']),'Old selected pair or draft changed beforeSave')
    require(exact(observed['shared_candidate'],before['parameter_batch']['candidate_tool']),'Shared tool249 dimensions changed')
    sw=deepcopy(before);sw['sketch_state']=observed['sketch_state'];delta.circle.verify_sw(before,sw,names)
    view=deepcopy(sw);view[delta.EXTRA]=deepcopy(observed['new_circle']);delta.verify_geometry(view,spec,fid);delta.verify_catalogue(view,spec)
    own=observed['new_circle']['operation_observation'];require(own['operation_native_id']==oid and own['feature_native_id']==fid and own['tool_native_id']==row['assigned_tool']['native_id']and own['modes']['operation_kind']==1 and own['modes']['capture_complete']is True and own['defaults']['complete']is True,'Complete new own Finish readback required')
    return dict(compact_preSave_verified=True,retained_operation_count=29,protected_paths=20,protected_records=83961,new_finish_ungenerated=True,old_full_parameters_re_read=False)

def verify_final(before,saved,spec,fid,oid,names,source,compact):
    require(saved['document']['needs_save']is False and saved['sketch_state']['needs_save']is False and saved['sketch_state']['saved_file_sha256']==source,'Clean actual saved full snapshot and new source required')
    require(exact(compact['inventory']['operations'],saved['operations'])and exact(compact['new_circle'],saved[delta.EXTRA]),'Save changed compact actual route or new definition')
    # These are comparison views only, never persisted as native captures.
    sketch=deepcopy(before);sketch['sketch_state']=deepcopy(saved['sketch_state']);sketch[delta.EXTRA]={k:deepcopy(saved[delta.EXTRA][k])for k in('measured_sketch','measured_circle')};delta.verify_sketch(before,sketch,names)
    feature=deepcopy(sketch);feature['features']=deepcopy(saved['features']);feature['feature_setups']=deepcopy(saved['feature_setups']);feature[delta.EXTRA]={k:deepcopy(v)for k,v in saved[delta.EXTRA].items()if k!='operation_observation'}
    delta.verify_feature(sketch,feature,spec,fid);row=delta.verify_insert(feature,saved,spec,oid,fid)
    return dict(full_saved_state_verified=True,comparison_views_only=True,synthetic_views_not_native_captures=True,new_operation=row,protected_old_operation_count=29,protected_positive_paths=20,protected_records=83961,production_qualified=False)

def run_once(backend,journal,data,v):
    r=journal.report;spec=data['spec']
    def capture(label):
        r['phase']=label;detail=dict(label=label,state={},capture_complete=False);r['captures'].append(detail);journal.persist();state=backend.capture(label,detail['state']);require(all(state.get(k)is True for k in('capture_complete','extended_capture_complete','parameter_capture_complete')),'Complete fresh full route required');detail.update(state=deepcopy(state),capture_complete=True);r[label]=deepcopy(state);journal.persist();return state
    def action(name,invoke):
        journal.action(name);return invoke(lambda:journal.pending(name),lambda x:journal.returned(name,x))
    try:
        require(v['action']=='apply','Native creation runs only explicit apply');journal.create();backend.start();before=capture('before');base=deepcopy(before);extra=base.pop(delta.EXTRA);require(exact(extra,{})and delta.mixed.same(base,data['state']),'Fresh saved baseline changed')
        names={spec['sketch_spec']['sketch_name'],spec['sketch_spec']['plane_name']};require(not any(x['name']in names for x in before['sketch_state']['features']),'New circle name already exists')
        require(delta.mixed.same(base,data['prepared_receipt']['before']),'Fresh state differs from file-verified saved prepare')
        if data.get('current_owner')is not None:
            from scripts import sw_cam_current_circular_finish_owner as owner
            r['owner_comparison_projection']=owner.verify_projection(data,v);r['owner_transition_verified_before_mutation']=True;journal.persist()
        backend.boundary();journal.claim()
        created=action('CreateSketch',backend.create_sketch);r['created_names']=list(created);journal.persist();sketch=backend.observe_new('after_sketch');delta.circle.verify_sw(before,dict(before,sketch_state=sketch['sketch_state']),created)
        fid=action('CreateMillFeature2',backend.create_feature);require(type(fid)is int and fid>0 and fid not in{r['geometry']['native_id']for r in before['features']},'Actual unique new feature ID required');r['new_feature_native_id']=fid;journal.persist();feature=backend.observe_new('after_feature');view=dict(before,sketch_state=feature['sketch_state']);view[delta.EXTRA]=feature['new_circle'];r['geometry_proof']=delta.verify_geometry(view,spec,fid);delta.verify_catalogue(view,spec);r['geometry_delta_verified']=True;journal.persist()
        oid=action('InsertOperation',lambda pending,returned:backend.insert_finish(view,pending,returned));require(type(oid)is int and oid>0 and oid not in{r['native_id']for r in before['operations']},'Actual unique Finish ID required');r['new_operation_native_id']=oid;journal.persist();compact=backend.compact_before_save();r['compact_proof']=verify_compact(before,compact,spec,fid,oid,created);r['operation_delta_verified']=True;journal.persist()
        journal.action('SaveActiveDocument');r['save_stage']={}
        def returned(value):journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if type(value)in(int,bool,float,str)or value is None else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha,save_returned_zero=True);journal.persist();saved=capture('saved');r['saved_full_proof']=verify_final(before,saved,spec,fid,oid,created,sha,compact);r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);journal.persist()
        backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,definition_saved_verified=True,reason='ONE_ORDINARY_CIRCULAR_FINISH_DEFINITION_NO_GTP_NO_PARAMETERS')
    except Exception as exc:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r.get('phase'),phase='finished',issue=_error(exc),reason=str(exc),readback_verified=False,runtime_unchanged=False,may_apply=False,definition_saved_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(exc),readback_verified=False,runtime_unchanged=False,may_apply=False,definition_saved_verified=False)
        journal.persist()
    return r

def _dispatch_prepared(sw,clsid,tlb,v,bundle,*,runtime_check,_context_factory=None):
    data=consume(bundle,v,runtime_check);require(data['addin_clsid'].casefold()==clsid.casefold(),'Exact current CAM registration required')
    from scripts.sw_cam_current_circular_finish_context import Context,preflight,config
    preflight(tlb,data['definition_mode']);config.reader.preflight(tlb)
    from scripts import sw_cam_current_circular_finish_owner as owner
    owner.verify_projection(data,v)
    r=dict(scope=SCOPE,status='error',phase='preflight',action=v['action'],binding=binding(v),request=deepcopy(v),recipe_pin=data['recipe_pin'],authority_pin=data.get('authority_pin',data['pin']),raw_saved_result_pin=data['pin'],evidence_pins=data['pins'],receipt_path=v['receipt_path'],dispatch_marker_path=str(data['marker']),source_before_sha256=v['expected_source_sha256'],actions={},captures=[],target_observations={},draft_observations={},native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,reference_geometry_creation_attempted=False,operation_creation_attempted=False,save_attempted=False,model_saved=False,save_readback_verified=False,source_update_verified=False,definition_saved_verified=False,readback_verified=False,runtime_unchanged=False,may_apply=False,automatic_replay=False,automatic_rollback=False,production_qualified=False,machining_eligible=False,reopen_persistence_verified=False)
    j=Journal(data['output'],data['marker'],r)
    if v['action']=='prepare':
        j.create();r.update(before=deepcopy(data['state']),before_provenance=owner.prepare_provenance(data),owner_comparison_projection=owner.prepare_projection(data),native_observation_performed=False,status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,may_apply=True,reason='FILE_ONLY_SAVED_RESULT_PREPARE_APPLY_REQUIRES_FRESH_FULL_RAM_READ');runtime_check();j.persist();return r
    b=(_context_factory or Context)(sw,clsid,tlb,{**v,**data['spec']},data,r,j.persist,runtime_check);result=run_once(b,j,data,v)
    try:runtime_check()
    except Exception as exc:return revoke_runtime(result,exc)
    return result

def revoke_runtime(r,error):
    r.update(status='uncertain'if r.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,may_apply=False,definition_saved_verified=False)
    if r.get('receipt_created')is True:
        p=Path(r['receipt_path']);old=json.loads(p.read_text(encoding='utf-8'));require(old.get('scope')==SCOPE and exact(old.get('binding'),r['binding']),'Only own receipt may be revoked');_write_receipt(p,r)
        if r.get('marker_created')is True:
            m=Path(r['dispatch_marker_path']);value=json.loads(m.read_text(encoding='utf-8'));require(value.get('scope')==SCOPE and exact(value.get('binding'),r['binding']),'Only own marker may be updated');value.update(status=r['status'],phase=r['phase'],receipt_sha256=_file_hash(p));_write_receipt(m,value)
    return r
