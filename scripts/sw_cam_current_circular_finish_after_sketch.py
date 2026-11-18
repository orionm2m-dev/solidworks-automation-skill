"""Continue one returned D18 sketch without repeating sketch creation."""
from copy import deepcopy
from pathlib import Path
import json,math,re
from scripts import sw_cam_current_circular_finish as base
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
from scripts.sw_cam_mill_units_qualification import _circle_sketch
require=base.require;exact=base.exact;delta=base.delta
SCOPE='CURRENT_CIRCULAR_FINISH_AFTER_SKETCH_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','partial_receipt_path','partial_receipt_sha256','receipt_path','qualification_only','message_policy'}


def binding(v):return{k:deepcopy(x)for k,x in v.items()if k!='receipt_path'}
def marker_path(v):return Path(v['expected_document_path']).parent/('continue_finish_after_sketch_'+_digest(dict(scope=SCOPE,binding=binding(v)))+'.json')
def outputs(v,pins):
    out=Path(v['receipt_path']);marker=marker_path(v);protected={Path(v['expected_document_path']).resolve(),*(Path(x['path']).resolve()for x in pins)}
    for p in(out,marker):require(p.is_absolute()and p.parent.is_dir()and p.suffix.lower()=='.json'and not p.exists()and not p.is_symlink()and p.resolve()not in protected,'Fresh distinct continuation output/marker required')
    require(out.resolve()!=marker.resolve(),'Output aliases marker');return str(out),str(marker)


def validate_partial(r,marker,v,data):
    require(r.get('scope')==base.SCOPE and r.get('status')=='uncertain'and r.get('phase')=='finished'and r.get('action')=='apply'and r.get('failed_phase')=='GetSpecificFeature2','Exact returned-sketch partial boundary required')
    require(r.get('reason')=='Unrequested SW document metadata changed'and r.get('issue',{}).get('type')=='CircularGuardError'and r['issue'].get('code')=='CURRENT_CIRCULAR_GUARD_REJECTED','Only recorded request-spec metadata failure supported')
    require(not any(k in r for k in('runtime_error','cleanup_error','receipt_write_error','source_after_sha256','new_feature_native_id','new_operation_native_id')),'No other failure, feature, operation or saved source allowed')
    for k in('receipt_created','marker_created','mutation_attempted','reference_geometry_creation_attempted','owner_transition_verified_before_mutation'):require(r.get(k)is True,'Missing returned partial fact: '+k)
    for k in('native_dispatch_pending','operation_creation_attempted','save_attempted','model_saved','save_readback_verified','source_update_verified','definition_saved_verified','GTP_attempted','GOP_attempted','AFR_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','CL_export_attempted','automatic_replay','automatic_rollback','production_qualified','machining_eligible'):require(r.get(k)is False,'Unexpected partial side effect: '+k)
    clean_events(r);old=r['request'];require(type(old)is dict and set(old)==base.KEYS and old['action']=='apply'and exact(r['binding'],base.binding(old)),'Exact original apply binding required')
    for k in('process_id','expected_process_create_time','expected_document_path','expected_source_sha256','qualification_only','message_policy'):require(exact(old[k],v[k]),'Continuation changes original owner/source: '+k)
    require(Path(old['receipt_path']).resolve()==Path(v['partial_receipt_path']).resolve()==Path(r['receipt_path']).resolve()and r['source_before_sha256']==v['expected_source_sha256'],'Partial receipt/source differs')
    names=r.get('created_names');spec=data['spec'];require(names==[spec['sketch_spec']['sketch_name']],'Exactly one recorded D18 sketch required')
    actions=r.get('actions');require(type(actions)is dict and list(actions)==['CreateSketch'],'No other historical native action allowed');a=actions['CreateSketch']
    require(a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False and a.get('native_return_type')=='dict'and a.get('native_return_value')is None and exact(a.get('native_observation'),dict(created_names=names)),'Durable returned sketch evidence required')
    require(r.get('sketch_creation',{}).get('sketch_edit_exited')is True,'Sketch editor must have exited')
    expected=dict(scope=base.SCOPE,status='uncertain',phase='finished',binding=r['binding'],authority_pin=r['authority_pin'],receipt_path=r['receipt_path'],receipt_sha256=v['partial_receipt_sha256'],automatic_replay=False)
    require(exact(marker,expected)and Path(r['dispatch_marker_path']).resolve()==base.marker_path(old).resolve(),'Original consumed marker differs')
    before=r['before'];capt=r['captures'];require(type(capt)is list and len(capt)==1 and capt[0]['label']=='before'and capt[0]['capture_complete']is True and exact(capt[0]['state'],before),'Complete actual original before capture required')
    for k in('capture_complete','extended_capture_complete','parameter_capture_complete'):require(before.get(k)is True,'Original full baseline incomplete')
    pure=deepcopy(before);require(exact(pure.pop(delta.EXTRA),{})and delta.mixed.same(pure,data['state']),'Original full baseline differs from saved authority')
    require(exact(r['authority_pin'],data['authority_pin'])and exact(r['raw_saved_result_pin'],data['pin'])and exact(r['recipe_pin'],data['recipe_pin']),'Original lineage differs')
    proof=base.owner_authority.verify_projection(data,old);require(exact(r.get('owner_comparison_projection'),proof),'Original owner projection differs')
    observed=r['targeted_observations']['after_sketch'];require(set(observed)=={'sketch_state','new_circle'}and observed['sketch_state']['needs_save']is True and observed['sketch_state']['saved_file_sha256']==v['expected_source_sha256'],'Exact unsaved returned sketch snapshot required')
    require(exact(observed['sketch_state']['spec'],spec['sketch_spec']),'Recorded snapshot must echo actual wall request')
    projected=deepcopy(observed['sketch_state']);projected['spec']=deepcopy(before['sketch_state']['spec'])
    delta.circle.verify_sw(before,dict(before,sketch_state=projected),names)
    circle=observed['new_circle'];require(set(circle)=={'measured_sketch','measured_circle'},'No unrecorded CAM feature may exist')
    require(exact(circle['measured_sketch'],r['sketch_creation'].get('sketch_readback'))and exact(_circle_sketch(circle['measured_sketch'],spec['sketch_spec']),circle['measured_circle']),'Independent returned sketch measurements differ')
    measured=circle['measured_circle'];require(delta.circle.vector(measured.get('normal_model'),[0.,0.,1.]),'Measured sketch normal differs');require(type(measured['radius_m'])is float and delta.circle.close(measured['radius_m']*1000.,9.)and delta.circle.vector([x*1000. for x in measured['center_model_m']],[0.,0.,-12.6]),'Actual D18 radius/center required')
    return dict(reference_before=deepcopy(before),projected_sketch_state=projected,created_names=deepcopy(names),measured_new_circle=deepcopy(circle),comparison_projection=dict(changed_paths=['/sketch_state/spec'],native_observation_performed=False,request_echo_only=True,raw_partial_modified=False))


def validate(v):
    require(type(v)is dict and set(v)==KEYS and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact qualification continuation request required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**32 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact owned process lifetime required')
    for k,x in v.items():
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA required')
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute explicit path required')
    source=Path(v['expected_document_path']);require(source.is_file()and not source.is_symlink()and source.suffix.lower()=='.sldprt'and _file_hash(source)==v['expected_source_sha256'],'Saved source changed')
    r,rpin=read_pin(v['partial_receipt_path'],v['partial_receipt_sha256']);old=r['request']
    data=base.owner_authority.load_completed(old['saved_result_receipt_path'],old['saved_result_receipt_sha256'],process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'])
    delta.validate_baseline(data['state']);recipe,rp=read_pin(old['recipe_path'],old['recipe_sha256']);spec=base.validate_recipe(recipe,data['state']);pins=list(data['pins'])+[rp]
    for path in(base.__file__,delta.__file__,base.owner_authority.__file__,Path(base.__file__).with_name('sw_cam_current_circular_finish_context.py')):pins.append(base.partial._filepin(path))
    data.update(recipe=recipe,recipe_pin=rp,spec=spec)
    prep,pp=read_pin(old['prepare_receipt_path'],old['prepare_receipt_sha256']);base.validate_file_only_prepare(prep,old,data,rp,pins);data['prepared_receipt']=prep
    marker,mp=read_pin(str(base.marker_path(old)),_file_hash(base.marker_path(old)));history=validate_partial(r,marker,v,data)
    from scripts import sw_cam_current_circular_finish_after_sketch_context as native
    pins+=list(r['evidence_pins'])+[pp,rpin,mp]+[base.partial._filepin(x)for x in(__file__,native.__file__)]
    unique={}
    for p in pins:
        p=base.partial._observed_pin(p);key=str(Path(p['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting continuation evidence');unique[key]=p
    data.update(pins=list(unique.values()),partial_receipt=r,partial_pin=rpin,partial_marker_pin=mp,history=history,original_request=deepcopy(old));data['output'],data['marker']=outputs(v,data['pins']);return data

_ISSUER=object()
class _Prepared(base._Prepared):pass

def _prepare_invocation(v,*,runtime_check):
    runtime_check();data=validate(v);pins=[base.partial._observed_pin(p)for p in data['pins']]+[base.partial._observed_pin(dict(path=v['expected_document_path'],sha256=v['expected_source_sha256']))];runtime_check();b=_Prepared(v,data,pins);b.issuer=_ISSUER;return b

def consume(bundle,v,runtime_check):
    require(type(bundle)is _Prepared and bundle.issuer is _ISSUER and bundle.used is False,'Private unused continuation bundle required');bundle.used=True;require(exact(bundle.v,v)and bundle.fingerprint()==bundle.digest,'Prepared continuation changed');runtime_check()
    for p in bundle.pins:base.partial._observed_pin(p)
    require(outputs(v,bundle.data['pins'])==(bundle.data['output'],bundle.data['marker']),'Continuation outputs changed');runtime_check();return bundle.data

class Journal(base.Journal):
    def marker_state(self):return dict(scope=SCOPE,status=self.report['status'],phase=self.report['phase'],binding=self.report['binding'],partial_receipt_pin=self.report['partial_receipt_pin'],receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),automatic_replay=False)
    def pending(self,name):require(name in('CreateMillFeature2','InsertOperation','SaveActiveDocument'),'Continuation cannot create another sketch');return super().pending(name)


def verify_current(before,data):
    history=data['history'];require(before['document']['needs_save']is True and before['sketch_state']['needs_save']is True,'Exact intentionally dirty existing-sketch state required')
    delta.verify_sketch(history['reference_before'],before,history['created_names'])
    require(delta.circle.circular_state_equal(dict(sketch_state=history['projected_sketch_state']),dict(sketch_state=before['sketch_state'])),'Fresh sketch metadata differs from scoped historical projection')
    require(exact(before[delta.EXTRA],history['measured_new_circle']),'Fresh D18 sketch differs from actual returned geometry')
    return dict(existing_sketch_verified=True,protected_operations=29,protected_positive_paths=20,protected_records=83961,new_sketch_created=False)


def run_once(backend,journal,data,v):
    r=journal.report;spec=data['spec'];reference=data['history']['reference_before'];names=data['history']['created_names']
    def capture(label):
        r['phase']=label;detail=dict(label=label,state={},capture_complete=False);r['captures'].append(detail);journal.persist();state=backend.capture(label,detail['state']);require(all(state.get(k)is True for k in('capture_complete','extended_capture_complete','parameter_capture_complete')),'Complete fresh full route required');detail.update(state=deepcopy(state),capture_complete=True);r[label]=deepcopy(state);journal.persist();return state
    def action(name,invoke):journal.action(name);return invoke(lambda:journal.pending(name),lambda x:journal.returned(name,x))
    try:
        journal.create();backend.start();before=capture('before');r['continuation_before_proof']=verify_current(before,data);r['existing_sketch_verified_before_mutation']=True;journal.persist();backend.boundary();journal.claim()
        fid=action('CreateMillFeature2',backend.create_feature);require(type(fid)is int and fid>0 and fid not in{r['geometry']['native_id']for r in reference['features']},'Actual unique new feature ID required');r['new_feature_native_id']=fid;journal.persist();feature=backend.observe_new('after_feature');view=dict(reference,sketch_state=feature['sketch_state']);view[delta.EXTRA]=feature['new_circle'];r['geometry_proof']=delta.verify_geometry(view,spec,fid);delta.verify_catalogue(view,spec);r['geometry_delta_verified']=True;journal.persist()
        oid=action('InsertOperation',lambda pending,returned:backend.insert_finish(view,pending,returned));require(type(oid)is int and oid>0 and oid not in{r['native_id']for r in reference['operations']},'Actual unique Finish ID required');r['new_operation_native_id']=oid;journal.persist();compact=backend.compact_before_save();r['compact_proof']=base.verify_compact(reference,compact,spec,fid,oid,names);r['operation_delta_verified']=True;journal.persist()
        journal.action('SaveActiveDocument');r['save_stage']={}
        def returned(value):journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if type(value)in(int,bool,float,str)or value is None else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha,save_returned_zero=True);journal.persist();saved=capture('saved');r['saved_full_proof']=base.verify_final(reference,saved,spec,fid,oid,names,sha,compact);r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);journal.persist()
        backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,definition_saved_verified=True,reason='EXISTING_SKETCH_COMPLETED_AS_ONE_CIRCULAR_FINISH_NO_GTP_NO_PARAMETERS')
    except Exception as exc:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r.get('phase'),phase='finished',issue=_error(exc),reason=str(exc),readback_verified=False,runtime_unchanged=False,definition_saved_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(exc),readback_verified=False,runtime_unchanged=False,definition_saved_verified=False)
        journal.persist()
    return r


def _dispatch_prepared(sw,clsid,tlb,v,bundle,*,runtime_check,_context_factory=None):
    data=consume(bundle,v,runtime_check);require(data['addin_clsid'].casefold()==clsid.casefold(),'Exact CAM registration required')
    from scripts.sw_cam_current_circular_finish_after_sketch_context import Context,preflight,config
    preflight(tlb,data['definition_mode']);config.reader.preflight(tlb)
    r=dict(scope=SCOPE,status='error',phase='preflight',binding=binding(v),request=deepcopy(v),original_request=deepcopy(data['original_request']),partial_receipt_pin=data['partial_pin'],partial_marker_pin=data['partial_marker_pin'],recipe_pin=data['recipe_pin'],authority_pin=data['authority_pin'],raw_saved_result_pin=data['pin'],evidence_pins=data['pins'],receipt_path=v['receipt_path'],dispatch_marker_path=data['marker'],source_before_sha256=v['expected_source_sha256'],reference_before=deepcopy(data['history']['reference_before']),historical_spec_comparison_projection=deepcopy(data['history']['comparison_projection']),created_names=deepcopy(data['history']['created_names']),sketch_reused=True,sketch_creation_attempted=False,actions={},captures=[],target_observations={},draft_observations={},native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,reference_geometry_creation_attempted=False,operation_creation_attempted=False,save_attempted=False,model_saved=False,save_readback_verified=False,source_update_verified=False,definition_saved_verified=False,existing_sketch_verified_before_mutation=False,readback_verified=False,runtime_unchanged=False,automatic_replay=False,automatic_rollback=False,production_qualified=False,machining_eligible=False,reopen_persistence_verified=False)
    j=Journal(data['output'],data['marker'],r);b=(_context_factory or Context)(sw,clsid,tlb,v,data,r,j.persist,runtime_check);result=run_once(b,j,data,v)
    try:runtime_check()
    except Exception as exc:return revoke_runtime(result,exc)
    return result


def revoke_runtime(r,error):
    r.update(status='uncertain'if r.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,definition_saved_verified=False)
    if r.get('receipt_created')is True:
        p=Path(r['receipt_path']);old=json.loads(p.read_text(encoding='utf8'));require(old.get('scope')==SCOPE and exact(old.get('binding'),r['binding']),'Only own continuation receipt may be revoked');_write_receipt(p,r)
        if r.get('marker_created')is True:
            m=Path(r['dispatch_marker_path']);value=json.loads(m.read_text(encoding='utf8'));require(value.get('scope')==SCOPE and exact(value.get('binding'),r['binding']),'Only own continuation marker may be updated');value.update(status=r['status'],phase=r['phase'],receipt_sha256=_file_hash(p));_write_receipt(m,value)
    return r
