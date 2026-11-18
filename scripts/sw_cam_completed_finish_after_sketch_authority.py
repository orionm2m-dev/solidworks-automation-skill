"""Consume an honest completed after-sketch continuation without forging creation history."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_current_circular_finish_after_sketch as producer
from scripts import sw_cam_current_circular_finish_configuration_authority as history
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
require=producer.require;exact=producer.exact;creation=producer.base

def terminal(r,pin,*,process_id,process_create_time,source_path,source_sha256,physical_source_sha256):
    require(r.get('scope')==producer.SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished'and r.get('reason')=='EXISTING_SKETCH_COMPLETED_AS_ONE_CIRCULAR_FINISH_NO_GTP_NO_PARAMETERS','Completed actual after-sketch continuation required')
    require(not any(k in r for k in('issue','failed_phase','runtime_error','runtime_receipt_update_error','cleanup_error','receipt_write_error')),'Unresolved continuation failure')
    for k in('receipt_created','marker_created','mutation_attempted','reference_geometry_creation_attempted','operation_creation_attempted','save_attempted','definition_saved_verified','geometry_delta_verified','operation_delta_verified','existing_sketch_verified_before_mutation','sketch_reused','readback_verified','runtime_unchanged','model_saved','save_returned_zero','save_readback_verified','source_update_verified'):require(r.get(k)is True,'Missing completed fact: '+k)
    for k in('sketch_creation_attempted','native_dispatch_pending','GTP_attempted','GOP_attempted','AFR_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','CL_export_attempted','automatic_replay','automatic_rollback','production_qualified','machining_eligible','reopen_persistence_verified'):require(r.get(k)is False,'Unexpected continuation action or qualification: '+k)
    clean_events(r);v=r['request'];require(type(v)is dict and set(v)==producer.KEYS and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact actual continuation request required')
    require(type(process_id)is int and type(v['process_id'])is int and process_id==v['process_id']and type(process_create_time)is type(v['expected_process_create_time'])and process_create_time==v['expected_process_create_time'],'Exact current owner required')
    require(history.common.same_path(source_path,v['expected_document_path'])and history.common.same_path(pin['path'],v['receipt_path'])and history.common.same_path(pin['path'],r['receipt_path']),'Continuation source/receipt path differs')
    require(exact(r['binding'],producer.binding(v))and v['expected_source_sha256']==r['source_before_sha256']and r['source_after_sha256']==r['saved_file_sha256']==source_sha256,'Honest saved source transition required')
    source=Path(source_path);require(source.is_file()and not source.is_symlink()and _file_hash(source)==physical_source_sha256,'Exact physical saved source required')
    require(list(r['actions'])==['CreateMillFeature2','InsertOperation','SaveActiveDocument'],'Only missing feature, Finish and Save may run')
    for name,a in r['actions'].items():require(a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False,'Unfinished action: '+name)
    for name in('CreateMillFeature2','InsertOperation'):require(r['actions'][name].get('native_observation',{}).get('nonnull')is True,'Missing actual object return: '+name)
    require(history.producer.completed(r['actions']['SaveActiveDocument']),'Strict completed Save0 required')
    stage=r['save_stage'];require(stage.get('native_call_returned')is True and stage.get('save_pending')is False and stage.get('native_return_type')=='int'and type(stage.get('native_return_value'))is int and stage['native_return_value']==0,'Durable returned Save0 required')
    return v

def load_completed(path,sha,*,process_id,process_create_time,source_path,source_sha256):
    return _load_completed(path,sha,process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=source_sha256,physical_source_sha256=source_sha256)

def _load_completed(path,sha,*,process_id,process_create_time,source_path,source_sha256,physical_source_sha256):
    r,pin=read_pin(path,sha);v=terminal(r,pin,process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=source_sha256,physical_source_sha256=physical_source_sha256)
    partial,pp=read_pin(v['partial_receipt_path'],v['partial_receipt_sha256']);require(exact(pp,r['partial_receipt_pin']),'Exact immutable partial receipt required');old=partial['request'];require(exact(old,r['original_request']),'Original14 request must remain honest')
    original=history._load_prior(old,physical_source_sha256);recipe,rp=read_pin(old['recipe_path'],old['recipe_sha256']);spec=creation.validate_recipe(recipe,original['state']);original.update(recipe=recipe,recipe_pin=rp,spec=spec)
    require(exact(original['authority_pin'],r['authority_pin'])and exact(original['pin'],r['raw_saved_result_pin'])and exact(rp,r['recipe_pin']),'Historical authority/recipe differs')
    prep,prep_pin=read_pin(old['prepare_receipt_path'],old['prepare_receipt_sha256']);creation.validate_file_only_prepare(prep,old,original,rp,prep['evidence_pins']);original['prepared_receipt']=prep
    pmap={str(Path(p['path']).resolve()).casefold():p['sha256']for p in partial['evidence_pins']}
    for p in prep['evidence_pins']:
        key=str(Path(p['path']).resolve()).casefold();require(pmap.get(key)==p['sha256'],'Prepare runtime evidence not retained by actual partial')
    marker,mp=read_pin(str(creation.marker_path(old)),_file_hash(creation.marker_path(old)));require(exact(mp,r['partial_marker_pin']),'Historical consumed partial marker differs')
    verified=producer.validate_partial(partial,marker,v,original);original.update(history=verified,original_request=deepcopy(old),partial_receipt=partial,partial_pin=pp,partial_marker_pin=mp)
    require(exact(verified['reference_before'],r['reference_before'])and exact(verified['created_names'],r['created_names'])and exact(verified['comparison_projection'],r['historical_spec_comparison_projection']),'Raw historical reference/projection/names changed')
    proof=producer.verify_current(r['before'],original);require(exact(proof,r['continuation_before_proof']),'Fresh existing sketch proof differs')
    fid=r['new_feature_native_id'];oid=r['new_operation_native_id'];names=r['created_names'];require(type(fid)is int and type(oid)is int and fid>0 and oid>0,'Actual returned new IDs required')
    compact=r['compact_before_save'];cp=creation.verify_compact(r['reference_before'],compact,spec,fid,oid,names);final=creation.verify_final(r['reference_before'],r['saved'],spec,fid,oid,names,source_sha256,compact)
    require(exact(cp,r['compact_proof'])and exact(final,r['saved_full_proof']),'Recomputed compact/final proof differs')
    captures=r['captures'];require(type(captures)is list and [x['label']for x in captures]==['before','saved']and all(x.get('capture_complete')is True and exact(x['state'],r[x['label']])for x in captures),'Raw full before and saved captures required')
    marker_path=producer.marker_path(v);require(history.common.same_path(marker_path,r['dispatch_marker_path']),'Continuation marker path differs');terminal_marker,tm=read_pin(str(marker_path),_file_hash(marker_path));expected=dict(scope=producer.SCOPE,status='review_required',phase='finished',binding=r['binding'],partial_receipt_pin=pp,receipt_path=pin['path'],receipt_sha256=pin['sha256'],automatic_replay=False)
    actual=deepcopy(terminal_marker);require(history.common.same_path(actual['receipt_path'],pin['path']),'Terminal marker receipt path differs');actual['receipt_path']=pin['path'];require(exact(actual,expected),'Exact consumed continuation marker required')
    from scripts import sw_cam_current_circular_finish_after_sketch_context as native
    for module in(producer.__file__,native.__file__,creation.__file__,creation.delta.__file__,creation.owner_authority.__file__):require(any(history.common.same_path(p['path'],module)and p['sha256']==_file_hash(module)for p in r['evidence_pins']),'Pinned completed continuation dependency differs')
    pins=list(original['pins'])+[pin,pp,prep_pin,mp,tm,rp,dict(path=__file__,sha256=_file_hash(__file__))]
    for witness in(prep,partial,r):
        for p in witness['evidence_pins']:
            if history.common.same_path(p['path'],source_path):require(p['sha256']==r['source_before_sha256'],'Historical source pin differs');continue
            history.common.direct(p);pins.append(p)
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold()
        if history.common.same_path(p['path'],source_path):require(p['sha256']==physical_source_sha256,'Current physical source pin differs')
        require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting immutable continuation lineage');unique[key]=history._full_pin(p)
    pins=list(unique.values());require(_file_hash(source_path)==physical_source_sha256 and read_pin(path,sha)[1]==pin,'Continuation evidence changed during load');original['pins']=deepcopy(pins)
    return dict(receipt=r,pin=pin,authority_pin=pin,state=deepcopy(r['saved']),original_data=original,spec=spec,operation_id=oid,feature_id=fid,new_observation=deepcopy(r['saved'][creation.delta.EXTRA]['operation_observation']),pins=pins,addin_clsid=original['addin_clsid'],definition_mode=original['definition_mode'],source_sha256=source_sha256,creation_recipe_pin=rp,creation_marker_pin=tm,continuation_scope=producer.SCOPE,context_request=deepcopy(old))
