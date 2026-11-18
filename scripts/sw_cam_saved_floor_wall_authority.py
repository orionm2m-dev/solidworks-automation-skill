"""File-only chain for completed mixed definition append, preserving historical source."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_append_floor_wall as producer
from scripts import sw_cam_reconfigured_circular_wip_binding as ancestry
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
require=producer.require
same=producer.writer.same
exact=producer.fields.equal


def validate_payload(r,original,inspection,source_sha):
    require(r.get('scope')==producer.SCOPE and r.get('mode')==producer.MODE and r.get('status')=='review_required'and r.get('phase')=='finished','Completed mixed definition append required')
    for key in('definitions_verified','definitions_saved','model_saved','save_readback_verified','source_update_verified','readback_verified','runtime_unchanged'):require(r.get(key)is True,'Missing successful saved definition fact: '+key)
    for key in('GTP_attempted','GOP_attempted','AFR_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','automatic_replay','automatic_rollback','parameters_configured','machining_eligible','generation_performed','production_qualified'):require(r.get(key)is False,'Definitions-only scope differs: '+key)
    require(not any(key in r for key in('issue','failed_phase','runtime_error','cleanup_error')),'Unresolved producer issue');clean_events(r)
    require(r['source_after_sha256']==r['saved_file_sha256']==source_sha,'Exact new saved source required')
    before=inspection['confirm_observed'];draft=inspection['new_operations'][0];producer.validate_recipe(r['recipe'],before,draft)
    require(same(r['before'],before),'Inspected 27-operation baseline differs')
    require(r['protected_draft_native_id']==draft['native_id']and r['future_machining_excluded_operation_ids']==[draft['native_id']],'Draft must remain explicitly excluded')
    added=r['new_operations'];require(type(added)is list and len(added)==2,'Exactly two actual selected definitions required');producer.verify_pair(before,r['inserted'],added)
    require(same(r['saved'],r['confirm_saved']),'Two completed saved states differ');producer.writer.authority.pocket.verify_saved(r['inserted'],r['saved'],source_sha)
    projected=deepcopy(r['saved']);projected['sketch_state']['saved_file_sha256']=before['sketch_state']['saved_file_sha256'];producer.verify_pair(before,projected,added)
    require(r['saved']['document']['needs_save']is False and r['saved']['sketch_state']['needs_save']is False and r['saved']['sketch_state']['saved_file_sha256']==source_sha,'Clean saved source snapshot required')
    witness=r['draft_before'];producer.base.defaults.validate_defaults(witness['defaults']);require(witness['operation_native_id']==draft['native_id']and exact(witness['defaults'],inspection['observed_defaults']),'Inspected draft defaults differ')
    require(witness['defaults']['finish']['BottomFinOpt']is False and witness['own_nc'].get('read_complete')is True,'Actual unconfigured draft observation required')
    for key in('draft_after_insert','draft_saved','draft_confirm'):require(exact(witness,r[key]),'Protected draft changed')
    observations=r['saved_observations'];require(len(observations)==len(r['inserted_observations'])==2 and exact(observations,r['inserted_observations']),'Two saved kind-specific observations required')
    for kind,(row,definition,observation)in enumerate(zip(added,r['recipe']['definitions'],observations)):
        require(type(row['mill_operation_type'])is int and row['mill_operation_type']==kind and row['linked_feature_ids']==[definition['feature_native_id']]and row['setup_native_id']==definition['operation_setup_native_id'],'Actual appended kind/link differs')
        require(type(observation['operation_kind'])is int and observation['operation_kind']==kind and observation['operation_native_id']==row['native_id']and observation['feature_native_id']==definition['feature_native_id'],'Observation identity differs')
        require(observation['own_nc']['operation_native_id']==row['native_id']and observation['own_nc'].get('read_complete')is True,'Completed own NC observation required')
        if kind==1:producer.base.defaults.validate_defaults(observation['defaults']);require(observation['defaults']['finish']['BottomFinOpt']is False,'Wall remains contour-only')
        else:
            parameters=observation['parameters'];require(parameters.get('read_complete')is True and parameters['operation_native_id']==row['native_id']and parameters['operation_type']==0 and parameters['feature_native_id']==definition['feature_native_id']and parameters['tool']['generic']==row['assigned_tool'],'Complete Rough own parameters required')
            require(parameters['rough'].get('parameter_reads_complete')is True and parameters['rough_diagnostic'].get('read_complete')is True,'Complete Rough decoder observation required')
    require(list(r['actions'])==['InsertOperation:floor','InsertOperation:wall','SaveActiveDocument'],'Exact two insertions then one Save required')
    for row,name in zip(added,('InsertOperation:floor','InsertOperation:wall')):
        a=r['actions'][name];require(a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False and a.get('native_return_type','').startswith('POINTER(')and a.get('native_return_value')is None and a.get('actual_operation_native_id')==row['native_id'],'Returned actual insertion required')
    a=r['actions']['SaveActiveDocument'];require(a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False and a.get('native_return_type')=='int'and type(a.get('native_return_value'))is int and a['native_return_value']==0,'Returned Save0 required')
    a=r['save_stage'];require(a.get('native_call_returned')is True and a.get('save_pending')is False and a.get('native_return_type')=='int'and type(a.get('native_return_value'))is int and a['native_return_value']==0,'Durable Save return required')
    return dict(payload_verified=True,producer_lineage_verified=False,mutation_authorized=False,operations=deepcopy(added),state=deepcopy(r['saved']),observations=deepcopy(observations))


def load_completed(v):
    pins=[]
    def read(path,sha):
        value,pin=read_pin(path,sha);pins.append(pin);return value,pin
    r,rp=read(v['definition_receipt_path'],v['definition_receipt_sha256']);marker,mp=read(v['definition_marker_path'],v['definition_marker_sha256']);req=r['request']
    require(r.get('scope')==producer.SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished','Completed mixed producer required')
    for key in('process_id','expected_process_create_time'):require(type(req[key])is type(v[key])and req[key]==v[key],'Exact producer owner/lifetime required')
    require(ancestry.common.same_path(req['expected_document_path'],v['expected_document_path'])and ancestry.common.same_path(r['receipt_path'],rp['path'])and ancestry.common.same_path(r['dispatch_marker_path'],mp['path']),'Producer path binding differs');require(req['expected_source_sha256']==r['source_before_sha256'],'Original source binding differs')
    prior,pp=read(req['revision_receipt_path'],req['revision_receipt_sha256']);require(r['authority_pin']==pp,'Pinned circular authority differs');oid=prior['operation_native_id'];rows=prior['postCL']['expected_generated_operations']
    bound=ancestry.bind_completed_revision(pp,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=r['source_before_sha256'],selected_operation_ids=[oid],protected_operation_ids=[x['operation_native_id']for x in rows if x['operation_native_id']!=oid],expected_generated_operations=rows,marker_pin=dict(path=req['revision_marker_path'],sha256=req['revision_marker_sha256']),writer_pin=dict(path=producer.writer.__file__,sha256=_file_hash(producer.writer.__file__)),verify_current_source=False)
    require(bound.get('physical_source_verified')is False,'Historical metadata-only mode must remain explicit');original=bound['snapshot']
    failure,fp=read(req['failure_receipt_path'],req['failure_receipt_sha256']);fm,fmp=read(req['failure_marker_path'],req['failure_marker_sha256']);producer.recovery.validate_failure(failure,fm,req)
    oldrecipe,oldrp=read(req['recipe_path'],req['recipe_sha256']);require(oldrecipe==r['failure_recipe']==failure['recipe']and same(failure['before'],original),'Original failed append ancestry differs');producer.base.validate_recipe(oldrecipe,original)
    inspection,ip=read(req['inspection_receipt_path'],req['inspection_receipt_sha256']);oldreq={k:req[k]for k in producer.base.KEYS|producer.recovery.EXTRA|producer.recovery.INSPECT};oldreq['mode']='recovery_continue';producer.recovery.validate_observation_inspection(inspection,dict(state=original,recipe=oldrecipe,failure_pin=fp,failure_marker_pin=fmp),oldreq)
    require(inspection.get('role_defaults_verified')is False and inspection.get('configuration_required')is True and inspection['observed_defaults']['finish']['BottomFinOpt']is False,'Explicit inspected unconfigured draft required')
    newrecipe,newrp=read(req['continuation_recipe_path'],req['continuation_recipe_sha256']);require(newrecipe==r['recipe']and newrp==r['recipe_pin'],'New append recipe pin differs')
    require(r['failure_pin']==fp and r['failure_marker_pin']==fmp and r['inspection_pin']==ip,'Exact failure/inspection pins required')
    payload=validate_payload(r,original,inspection,v['expected_source_sha256'])
    expected=dict(scope=producer.SCOPE,status='review_required',phase='finished',recipe_pin=r['recipe_pin'],source_before_sha256=r['source_before_sha256'],receipt_path=rp['path'],receipt_sha256=rp['sha256'],automatic_replay=False,inspection_pin=ip,failure_receipt_pin=fp)
    require(ancestry.common.same_path(marker['receipt_path'],rp['path']),'Consumed marker path differs');m=deepcopy(marker);m['receipt_path']=rp['path'];require(m==expected,'Exact consumed terminal marker required')
    require(_file_hash(producer.__file__)==v['producer_module_sha256']and any(ancestry.common.same_path(x['path'],producer.__file__)and x['sha256']==v['producer_module_sha256']for x in r['evidence_pins']),'Exact producing module required')
    for pin in bound['pins']+r['evidence_pins']:
        if ancestry.common.same_path(pin['path'],v['expected_document_path']):require(pin['sha256']==r['source_before_sha256'],'Historical source pin differs');continue
        ancestry.common.direct(pin);pins.append(pin)
    pins.extend(dict(path=p,sha256=_file_hash(p))for p in(__file__,producer.__file__,producer.recovery.__file__,producer.base.__file__,ancestry.__file__))
    unique={}
    for pin in pins:
        key=str(Path(pin['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==pin['sha256'],'Conflicting immutable evidence pins');unique[key]=pin
    return dict(receipt=r,payload=payload,state=r['saved'],pins=list(unique.values()),receipt_pin=rp,marker_pin=mp,original=original,producer_lineage_verified=True)
