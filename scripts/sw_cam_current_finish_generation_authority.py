"""Completed single-circle configuration authority for exactly one generation attempt."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_current_circular_finish_configure as producer
from scripts import sw_cam_current_finish_configuration_delta as configured
from scripts import sw_cam_current_finish_generation_delta as delta
from scripts import sw_cam_completed_finish_after_sketch_authority as creation_authority
from scripts import sw_cam_current_finish_generation_cl as cl_compare
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
require=delta.require;exact=delta.exact

def terminal(r,pin,*,process_id,process_create_time,source_path,source_sha256):
    require(r.get('scope')==producer.SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished'and r.get('reason')=='ONE_ORDINARY_CIRCLE_FINISH_CONFIGURED_NO_GTP','Completed selected circle configuration required')
    require(not any(k in r for k in('issue','failed_phase','runtime_error','cleanup_error','receipt_write_error')),'Unresolved configuration failure')
    for k in('receipt_created','marker_created','mutation_attempted','save_attempted','parameter_setter_attempted','tool_assignment_attempted','configuration_saved','parameters_configured','parameters_readback_verified','readback_verified','runtime_unchanged','model_saved','save_returned_zero','save_readback_verified','source_update_verified'):require(r.get(k)is True,'Missing completed configuration fact: '+k)
    for k in('native_dispatch_pending','GTP_attempted','GOP_attempted','AFR_attempted','operation_creation_attempted','reference_geometry_creation_attempted','tool_edit_attempted','CL_export_attempted','automatic_replay','automatic_rollback','production_qualified','machining_eligible','reopen_persistence_verified'):require(r.get(k)is False,'Unexpected action or qualification: '+k)
    clean_events(r);v=r['request'];require(type(v)is dict and set(v)==producer.KEYS and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact configuration request required')
    require(type(process_id)is int and type(v['process_id'])is int and process_id==v['process_id']and type(process_create_time)is type(v['expected_process_create_time'])and process_create_time==v['expected_process_create_time'],'Exact configuration owner required')
    same=creation_authority.history.common.same_path
    require(same(source_path,v['expected_document_path'])and same(pin['path'],v['receipt_path'])and same(pin['path'],r['receipt_path']),'Configuration paths differ')
    require(exact(r['binding'],producer.binding(v))and v['expected_source_sha256']==r['source_before_sha256']and r['source_after_sha256']==r['saved_file_sha256']==source_sha256,'Honest configuration source transition required')
    source=Path(source_path);require(source.is_file()and not source.is_symlink()and _file_hash(source)==source_sha256,'Current physical saved source differs')
    return v

def load_completed(path,sha,*,process_id,process_create_time,source_path,source_sha256):
    r,pin=read_pin(path,sha);v=terminal(r,pin,process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=source_sha256)
    created,created_pin=read_pin(v['creation_receipt_path'],v['creation_receipt_sha256']);require(created.get('scope')==creation_authority.producer.SCOPE,'Explicit reviewed creation producer required')
    a=creation_authority._load_completed(created_pin['path'],created_pin['sha256'],process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=v['expected_source_sha256'],physical_source_sha256=source_sha256)
    require(exact(a['pin'],r['authority_pin']),'Exact creation authority pin required');recipe,rp=read_pin(v['recipe_path'],v['recipe_sha256']);require(exact(rp,r['recipe_pin'])and exact(recipe,r['recipe']),'Exact configuration recipe required')
    configured.validate_recipe(recipe,a['state'],a['operation_id'],a['feature_id']);require(configured.circular.circular_state_equal(r['before'],a['state']),'Fresh before differs from saved creation')
    names=producer.action_names(recipe);require(list(r['actions'])==names and exact(r['allowed_actions'],names),'Exact ordered bounded configuration actions required')
    for name,action in r['actions'].items():require(creation_authority.history.producer.completed(action),'Every setter/assignment/Save must have strict durable int0 return: '+name)
    stage=r['save_stage'];require(stage.get('native_call_returned')is True and stage.get('save_pending')is False and stage.get('native_return_type')=='int'and type(stage.get('native_return_value'))is int and stage['native_return_value']==0,'Durable saved stage required')
    proof=configured.verify_full(r['before'],r['saved'],recipe,saved_source=source_sha256);require(exact(proof,r['saved_configuration_proof']),'Configuration full proof differs')
    planes=r['plane_observations'];require(exact(planes['before'],planes['saved']),'Saved setup planes changed');compact=r['compact_before_save'];cp=configured.verify_compact(r['before'],compact,recipe,planes['before']);require(exact(cp,r['compact_configuration_proof'])and exact(compact['new_circle'],r['saved'][delta.EXTRA])and exact(compact['inventory']['operations'],r['saved']['operations']),'Compact/saved selected target changed')
    captures=r['captures'];require(type(captures)is list and [x['label']for x in captures]==['before','saved']and all(x.get('capture_complete')is True and exact(x['state'],r[x['label']])for x in captures),'Two actual full configuration captures required')
    assignment=r['assignment_observation'];require(exact(producer.setters.verify_assignment(assignment['before'],assignment['after'],recipe['row']),assignment['proof']),'Raw assignment proof differs')
    markerpath=producer.marker_path(v);require(creation_authority.history.common.same_path(markerpath,r['dispatch_marker_path']),'Exact consumed configuration marker path required');marker,mp=read_pin(str(markerpath),_file_hash(markerpath));expected=dict(scope=producer.SCOPE,status='review_required',phase='finished',binding=r['binding'],authority_pin=r['authority_pin'],recipe_pin=r['recipe_pin'],receipt_path=pin['path'],receipt_sha256=pin['sha256'],automatic_replay=False)
    actual=deepcopy(marker);require(creation_authority.history.common.same_path(actual['receipt_path'],pin['path']),'Marker receipt path differs');actual['receipt_path']=pin['path'];require(exact(actual,expected),'Consumed configuration marker differs')
    from scripts import sw_cam_current_finish_configuration_context as native
    for module in(producer.__file__,configured.__file__,native.__file__,native.complete_guard.__file__):require(any(creation_authority.history.common.same_path(p['path'],module)and p['sha256']==_file_hash(module)for p in r['evidence_pins']),'Exact completed configuration code required')
    pins=list(a['pins'])+[pin,rp,mp,dict(path=__file__,sha256=_file_hash(__file__))]
    for p in r['evidence_pins']:
        if creation_authority.history.common.same_path(p['path'],source_path):require(p['sha256']==r['source_before_sha256'],'Historical config source pin differs');continue
        creation_authority.history.common.direct(p);pins.append(p)
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting generation evidence');unique[key]=creation_authority.history._full_pin(p)
    pins=list(unique.values());delta.select(r['saved'],a['operation_id'],a['feature_id'])
    prior=a['original_data'];reconciled=prior['reconciliation_receipt'];rawpin=creation_authority.history._full_pin(reconciled['post_CL_pin']);oldpin=creation_authority.history._full_pin(reconciled['pre_CL_pin']);rawsave=prior['receipt'];oldrows=rawsave['postCL']['expected_generated_operations']
    failure,failurepin=creation_authority.history._pin_record(reconciled['failed_generation_receipt_pin']);historical_rows=failure['preCL']['expected_generated_operations'];baseline_rows=delta.positive_rows(r['saved']);require(exact(oldrows,baseline_rows)and exact(reconciled['positive_operation_mapping'],baseline_rows),'Exact protected20 paths required')
    cl_compare.project_verified_baseline(Path(rawpin['path']).read_bytes(),Path(oldpin['path']).read_bytes(),historical_rows,baseline_rows,baseline_proof=reconciled['comparison_proof'])
    cl=dict(raw_pin=rawpin,historical_raw_pin=oldpin,historical_rows=historical_rows,rows=baseline_rows,proof=reconciled['comparison_proof'])
    configuration_data=dict(authority=a,state=deepcopy(r['saved']),recipe=recipe,recipe_pin=rp,candidate=deepcopy(r['saved']['parameter_batch']['candidate_tool']),pins=deepcopy(pins),addin_clsid=a['addin_clsid'],definition_mode=a['definition_mode'])
    require(_file_hash(source_path)==source_sha256 and read_pin(path,sha)[1]==pin,'Completed configuration changed during binding')
    return dict(receipt=r,pin=pin,state=deepcopy(r['saved']),configuration_request=deepcopy(v),configuration_data=configuration_data,operation_id=a['operation_id'],feature_id=a['feature_id'],planes=deepcopy(planes['saved']),CL_baseline=cl,pins=pins,source_sha256=source_sha256,addin_clsid=a['addin_clsid'],definition_mode=a['definition_mode'])
