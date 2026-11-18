"""Bind a completed saved mixed configuration without rewriting its history."""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_saved_floor_wall_configure as config
from scripts import sw_cam_saved_floor_wall_generation_delta as delta
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
require=config.require;exact=config.exact;KEYS=config.KEYS
reader=config.reader;base=config.base;writer=config.writer;recipe_core=config.recipe_core
finish_setters=config.finish_setters;depth_setters=config.depth_setters

def load_historical_read_authority(v,current_source_sha256):
    require(type(v)is dict and set(v)==KEYS,'Exact mixed configuration request required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Qualification only required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact owner required')
    for k,value in v.items():
        if k.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
        if k.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute paths required')
    source=Path(v['expected_document_path']);require(source.is_file()and not source.is_symlink()and source.suffix.lower()=='.sldprt'and _file_hash(source)==current_source_sha256,'Exact current postconfiguration source file required')
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
    pins=data['pins']+[op,rp]+observed['evidence_pins']+[dict(path=p,sha256=_file_hash(p))for p in(__file__,config.__file__,recipe_core.__file__,recipe_core.finish.__file__,reader.__file__,base.lineage.__file__,finish_setters.__file__,depth_setters.__file__)]
    unique={}
    for pin in pins:
        key=str(Path(pin['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==pin['sha256'],'Conflicting immutable evidence');unique[key]=pin
    return dict(state=deepcopy(data['state']),authority=data,read_receipt=observed,read_pin=op,targets=targets,recipe=recipe,recipe_pin=rp,candidate=deepcopy(candidate),draft=deepcopy(data['receipt']['draft_saved']),writer_receipt=prior,lineage=lineage,pins=list(unique.values()))

def load_completed(path,sha,*,process_id,process_create_time,source_path,source_sha256,selected_ids):
    r,pin=read_pin(path,sha)
    require(r.get('scope')==config.SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished','Exact completed mixed configuration required')
    require(not any(k in r for k in('issue','failed_phase','runtime_error','cleanup_error','receipt_write_error')),'Unresolved configuration result')
    for k in('configuration_saved','parameters_configured','parameters_readback_verified','model_saved','save_readback_verified','source_update_verified','readback_verified','runtime_unchanged','marker_created'):
        require(r.get(k)is True,'Missing completed configuration fact: '+k)
    for k in('GTP_attempted','GOP_attempted','AFR_attempted','operation_creation_attempted','tool_edit_attempted','CL_export_attempted','automatic_replay','automatic_rollback','production_qualified'):
        require(r.get(k)is False,'Unexpected configuration action or release: '+k)
    require(r.get('native_dispatch_pending')is False,'No pending native action allowed');clean_events(r)
    old=r['request'];require(type(old['process_id'])is int and old['process_id']==process_id and type(old['expected_process_create_time'])is type(process_create_time)and old['expected_process_create_time']==process_create_time,'Exact producer process lifetime required')
    common=reader.ancestry.common
    require(common.same_path(old['expected_document_path'],source_path)and common.same_path(r['receipt_path'],pin['path']),'Exact producer source and receipt paths required')
    require(old['expected_source_sha256']==r['source_before_sha256']and r['source_after_sha256']==r['saved_file_sha256']==source_sha256,'Exact actual saved source transition required')
    data=load_historical_read_authority(old,source_sha256)
    require(r['recipe']==data['recipe']and r['recipe_pin']==data['recipe_pin']and r['read_authority_pin']==data['read_pin']and r['authority_pin']==data['authority']['receipt_pin'],'Actual configuration authority pins differ')
    require(writer.same(r['before'],data['state']),'Original full configuration baseline differs')
    targets=r['target_observations'];drafts=r['draft_observations']
    require(all(k in targets and k in drafts for k in('before','configured','saved','confirm_saved')),'All complete selected/draft stages required')
    require(exact(targets['before'],data['targets'])and exact(drafts['before'],data['draft']),'Recorded initial selected fields differ')
    proof=config.verify_full_configuration(r['before'],r['configured'],data['recipe'],data['candidate'],targets['before'],targets['configured'],drafts['before'],drafts['configured'])
    require(exact(proof,r['configuration_proof']),'Configuration delta proof differs')
    config.circular.pocket.verify_saved(r['configured'],r['saved'],source_sha256)
    require(writer.same(r['saved'],r['confirm_saved'])and r['saved']['document']['needs_save']is False and r['saved']['sketch_state']['needs_save']is False,'Two complete clean saved captures required')
    require(all(exact(targets['configured'],targets[k])and exact(drafts['before'],drafts[k])for k in('saved','confirm_saved')),'Selected parameters or draft changed after Save')
    if 'saved_observations'in r:require(exact(r['saved_observations'],targets['saved']),'Saved observations alias differs')
    if 'saved_draft_witness'in r:require(exact(r['saved_draft_witness'],drafts['saved']),'Saved draft alias differs')
    ids=[row['operation_native_id']for row in r['recipe']['rows']]
    require(type(selected_ids)is list and exact(selected_ids,ids)and exact(r['selected_operation_native_ids'],ids),'Exactly the completed configured pair in order required')
    require(r['protected_draft_native_id']==drafts['saved']['operation_native_id']and r['future_machining_excluded_operation_ids']==[drafts['saved']['operation_native_id']],'Explicit unselected draft exclusion required')
    expected_actions=config.action_names(data['recipe']);require(list(r['actions'])==expected_actions and r['allowed_actions']==expected_actions,'Exact configured actions required')
    for name,action in r['actions'].items():
        require(action.get('attempted')is True and action.get('returned')is True and action.get('native_dispatch_pending')is False and action.get('native_return_type')=='int'and type(action.get('native_return_value'))is int and action['native_return_value']==0,'Exact successful native action return required: '+name)
    stage=r['save_stage'];require(stage.get('native_call_returned')is True and stage.get('save_pending')is False and stage.get('native_return_type')=='int'and type(stage.get('native_return_value'))is int and stage['native_return_value']==0,'Durable returned Save0 required')
    marker_path=Path(source_path).parent/('configure_mill_pair_'+_digest(dict(scope=config.SCOPE,source=str(Path(source_path).resolve()).casefold(),sha=old['expected_source_sha256'],recipe_sha256=old['recipe_sha256']))+'.json')
    require(common.same_path(r['dispatch_marker_path'],marker_path),'Exact derived configuration marker required')
    marker,mp=read_pin(str(marker_path),_file_hash(marker_path))
    expected=dict(scope=config.SCOPE,status='review_required',phase='finished',recipe_pin=r['recipe_pin'],read_authority_pin=r['read_authority_pin'],source_before_sha256=r['source_before_sha256'],receipt_path=pin['path'],receipt_sha256=pin['sha256'],automatic_replay=False)
    require(common.same_path(marker['receipt_path'],pin['path']),'Marker receipt path differs');normalized=deepcopy(marker);normalized['receipt_path']=pin['path'];require(exact(normalized,expected),'Exact terminal consumed marker required')
    pins=data['pins']+[pin,mp]
    require(any(common.same_path(p['path'],config.__file__)and p['sha256']==_file_hash(config.__file__)for p in r['evidence_pins']),'Exact installed producer code must be pinned')
    for p in r['evidence_pins']:
        if common.same_path(p['path'],source_path):require(p['sha256']==r['source_before_sha256'],'Historical physical source pin differs');continue
        common.direct(p);pins.append(p)
    for p in(__file__,delta.__file__,config.__file__):pins.append(dict(path=p,sha256=_file_hash(p)))
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting immutable generation pins');unique[key]=p
    state=deepcopy(r['saved']);state[delta.PAIR_KEY]=dict(targets=deepcopy(targets['saved']),draft=deepcopy(drafts['saved']));delta.select(state,ids)
    context=deepcopy(data);context.update(state=deepcopy(r['saved']),targets=deepcopy(targets['saved']),draft=deepcopy(drafts['saved']),pins=list(unique.values()))
    context['lineage']['state']=deepcopy(r['saved'])
    return dict(receipt=r,pin=pin,state=state,selected_ids=ids,source_sha256=source_sha256,context_data=context,targets=targets['saved'],draft=drafts['saved'],recipe=data['recipe'],candidate=data['candidate'],addin_clsid=data['lineage']['loaded']['addin_clsid'],pins=list(unique.values()),binding=deepcopy(old))
