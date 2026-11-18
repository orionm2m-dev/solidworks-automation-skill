"""Explicit saved-continuation authority; original successful-writer loader is unchanged."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_saved_floor_wall_generation_authority as original
from scripts import sw_cam_partial_mill_pair_projection as projection
from scripts import sw_cam_failed_configuration_depth_read as depth_reader
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
config=original.config;delta=original.delta;reader=original.reader;writer=original.writer
require=config.require;exact=config.exact;common=reader.ancestry.common
CONTINUATION_SCOPE='SAVED_FLOOR_WALL_CONFIGURATION_CONTINUATION_V1'


def _pin_record(record):
    require(type(record)is dict and type(record.get('path'))is str and type(record.get('sha256'))is str,'Explicit immutable pin required')
    value,pin=read_pin(record['path'],record['sha256'])
    require(all(k in pin and pin[k]==v for k,v in record.items()),'Recorded evidence identity changed')
    return value,pin


def _owner(request,*,process_id,process_create_time,source_path,source_sha256):
    require(type(request['process_id'])is int and request['process_id']==process_id and type(request['expected_process_create_time'])is type(process_create_time)and request['expected_process_create_time']==process_create_time,'Exact producer process lifetime required')
    require(common.same_path(request['expected_document_path'],source_path)and request['expected_source_sha256']==source_sha256,'Exact historical source identity required')


def _depth_proof(observed,observed_pin,failure_pin,marker_pin,target,old):
    require(observed.get('scope')==depth_reader.SCOPE and observed.get('status')=='review_required'and observed.get('phase')=='finished','Completed raw depth observation required')
    for key in('read_only','readback_verified','source_unchanged','runtime_unchanged'):require(observed.get(key)is True,'Missing depth observation fact: '+key)
    for key in('mutation_attempted','save_attempted','GTP_attempted','parameter_setter_attempted','marker_created','continuation_authorized','full_configuration_reconciled','production_qualified'):require(observed.get(key)is False,'Unexpected depth observation authority: '+key)
    require(not any(k in observed for k in('issue','failed_phase','runtime_error','cleanup_error','receipt_write_error')),'Unresolved depth read failure');clean_events(observed)
    req=observed['request'];_owner(req,process_id=old['process_id'],process_create_time=old['expected_process_create_time'],source_path=old['expected_document_path'],source_sha256=old['expected_source_sha256'])
    require(common.same_path(req['failure_receipt_path'],failure_pin['path'])and req['failure_receipt_sha256']==failure_pin['sha256']and common.same_path(req['failure_marker_path'],marker_pin['path'])and req['failure_marker_sha256']==marker_pin['sha256'],'Depth observation belongs to another failure')
    require(exact(observed['failure_pin'],failure_pin)and exact(observed['failure_marker_pin'],marker_pin)and exact(observed['target'],target),'Depth observation pinned target differs')
    require(common.same_path(observed['receipt_path'],observed_pin['path'])and observed['source_sha256']==old['expected_source_sha256'],'Depth receipt/source binding differs')
    require(exact(observed['before'],observed['after'])and observed['before'].get('complete')is True and exact(observed['before']['target'],target),'Two complete raw depth triples required')
    values=observed['before']['values'];require(values.get('complete')is True,'Incomplete raw depth triple')
    import math
    nominal=target['requested_depth'];require(type(nominal)is float and nominal==7.1,'Only established nominal depth supported');adjacent=math.nextafter(nominal,math.inf)
    for name in('GetMachiningDepth','GetMachiningDepthValue'):
        require(exact(values[name],dict(value=adjacent,python_type='float',float_hex=adjacent.hex())),'Exact observed positive adjacent stored/effective depth required')
    require(exact(values['GetOverrideMachiningDepth'],dict(value=True,python_type='bool',float_hex=None)),'Observed override must remain true')
    require(exact(observed['document_before'],observed['document_after']),'Depth read changed document identity')


def load_completed(path,sha,*,process_id,process_create_time,source_path,source_sha256,selected_ids):
    r,pin=read_pin(path,sha)
    kwargs=dict(process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=source_sha256,selected_ids=selected_ids)
    if r.get('scope')==config.SCOPE:return original.load_completed(path,sha,**kwargs)
    require(r.get('scope')==CONTINUATION_SCOPE,'Only explicit original or continuation producer scopes supported')
    return _load_continuation(r,pin,**kwargs)


def _load_continuation(r,pin,*,process_id,process_create_time,source_path,source_sha256,selected_ids):
    require(r.get('status')=='review_required'and r.get('phase')=='finished','Completed saved continuation required')
    require(not any(k in r for k in('issue','failed_phase','runtime_error','cleanup_error','receipt_write_error')),'Unresolved continuation result')
    for key in('configuration_saved','parameters_configured','parameters_readback_verified','model_saved','save_readback_verified','source_update_verified','readback_verified','runtime_unchanged','marker_created'):
        require(r.get(key)is True,'Missing completed continuation fact: '+key)
    for key in('native_dispatch_pending','GTP_attempted','GOP_attempted','AFR_attempted','operation_creation_attempted','tool_assignment_attempted','tool_edit_attempted','CL_export_attempted','automatic_replay','automatic_rollback','production_qualified'):
        require(r.get(key)is False,'Unexpected continuation action or release: '+key)
    req=r['request'];require(type(req)is dict and set(req)==depth_reader.KEYS|{'depth_read_receipt_path','depth_read_receipt_sha256'}and req['qualification_only']is True and req['message_policy']=='vendor_default','Exact qualification-only continuation request required')
    require(common.same_path(req['receipt_path'],pin['path']),'Continuation request output differs')
    clean_events(r)
    failure,fp=_pin_record(r['original_failure_pin']);marker,mp=_pin_record(r['original_failure_marker_pin']);depth,dp=_pin_record(r['depth_read_pin'])
    old=failure['request'];require(exact(r['original_request'],old),'Original request must remain immutable')
    _owner(old,process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=r['source_before_sha256'])
    _owner(r['request'],process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=r['source_before_sha256'])
    require(common.same_path(r['receipt_path'],pin['path'])and r['source_after_sha256']==r['saved_file_sha256']==source_sha256,'Actual continuation source transition differs')
    req=r['request'];require(common.same_path(req['failure_receipt_path'],fp['path'])and req['failure_receipt_sha256']==fp['sha256']and common.same_path(req['failure_marker_path'],mp['path'])and req['failure_marker_sha256']==mp['sha256'],'Continuation failure pins differ')
    require(common.same_path(req['depth_read_receipt_path'],dp['path'])and req['depth_read_receipt_sha256']==dp['sha256'],'Continuation raw-depth pin differs')
    failure_target=depth_reader.validate_failure(failure,marker,req)
    _depth_proof(depth,dp,fp,mp,failure_target,old)
    data=original.load_historical_read_authority(old,source_sha256)
    require(exact(r['recipe'],data['recipe'])and exact(r['recipe_pin'],data['recipe_pin']),'Original sealed recipe differs')
    require(exact(failure['recipe'],data['recipe'])and writer.same(failure['before'],data['state']),'Original failed baseline differs from saved authority')
    require(exact(failure['target_observations']['before'],data['targets'])and exact(failure['draft_observations']['before'],data['draft']),'Original raw selected baseline differs')
    require(list(failure['actions'])==projection.prefix_actions(data['recipe']),'Exact original setter prefix required')
    targets=r['target_observations'];drafts=r['draft_observations']
    require(all(k in targets and k in drafts for k in('before','configured','saved','confirm_saved')),'Complete continuation selected/draft snapshots required')
    prefix=projection.verify_checkpoint(data['state'],r['before'],data['recipe'],data['candidate'],data['targets'],targets['before'],data['draft'],drafts['before'],'prefix')
    final=projection.verify_checkpoint(data['state'],r['configured'],data['recipe'],data['candidate'],data['targets'],targets['configured'],data['draft'],drafts['configured'],'final')
    require(exact(prefix,r['prefix_proof'])and exact(final,r['final_configuration_proof']),'Recomputed continuation proof differs')
    config.circular.pocket.verify_saved(r['configured'],r['saved'],source_sha256)
    require(writer.same(r['saved'],r['confirm_saved'])and r['saved']['document']['needs_save']is False and r['saved']['sketch_state']['needs_save']is False,'Two complete clean saved captures required')
    require(all(exact(targets['configured'],targets[k])and exact(data['draft'],drafts[k])for k in('saved','confirm_saved')),'Raw selected parameters or draft changed across Save')
    if 'saved_observations'in r:require(exact(r['saved_observations'],targets['saved']),'Saved target alias differs')
    if 'saved_draft_witness'in r:require(exact(r['saved_draft_witness'],drafts['saved']),'Saved draft alias differs')
    ids=[row['operation_native_id']for row in data['recipe']['rows']]
    require(type(selected_ids)is list and exact(selected_ids,ids)and exact(r['selected_operation_native_ids'],ids),'Exactly the completed configured pair required')
    require(r['protected_draft_native_id']==data['draft']['operation_native_id']and r['future_machining_excluded_operation_ids']==[data['draft']['operation_native_id']],'Explicit retained draft exclusion required')
    remaining=projection.remaining_changes(data['recipe']);names=['field:'+str(remaining['operation_native_id'])+':'+c['field']for c in remaining['changes']]+['SaveActiveDocument']
    require(list(r['actions'])==names and exact(r['allowed_actions'],names),'Only ten remaining setters and one Save allowed')
    for name,action in r['actions'].items():
        require(action.get('attempted')is True and action.get('returned')is True and action.get('native_dispatch_pending')is False and action.get('native_return_type')=='int'and type(action.get('native_return_value'))is int and action['native_return_value']==0,'Exact returned native action required: '+name)
    stage=r['save_stage'];require(stage.get('native_call_returned')is True and stage.get('save_pending')is False and stage.get('native_return_type')=='int'and type(stage.get('native_return_value'))is int and stage['native_return_value']==0,'Durable returned Save0 required')
    from scripts import sw_cam_partial_mill_pair_continuation as producer
    marker_path=producer.marker_path(req);require(common.same_path(r['dispatch_marker_path'],marker_path),'Exact derived continuation marker required')
    continuation_marker,cmp=read_pin(str(marker_path),_file_hash(marker_path))
    require(exact(continuation_marker,producer.completed_marker(r,pin)),'Exact terminal consumed continuation marker required')
    require(producer.SCOPE==CONTINUATION_SCOPE,'Exact continuation producer scope required')
    pins=data['pins']+[pin,fp,mp,dp,cmp]
    producer_modules=(producer.__file__,projection.__file__,depth_reader.__file__,config.__file__)
    for module in producer_modules:
        require(any(common.same_path(p['path'],module)and p['sha256']==_file_hash(module)for p in r['evidence_pins']),'Exact continuation producer/helper must be pinned')
    for witness in(failure,depth,r):
        for p in witness['evidence_pins']:
            if common.same_path(p['path'],source_path):
                require(p['sha256']==r['source_before_sha256'],'Historical source pin differs');continue
            common.direct(p);pins.append(p)
    pins.extend(dict(path=m,sha256=_file_hash(m))for m in(__file__,original.__file__,delta.__file__,*producer_modules))
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting immutable generation pins');unique[key]=p
    state=deepcopy(r['saved']);state[delta.PAIR_KEY]=dict(targets=deepcopy(targets['saved']),draft=deepcopy(drafts['saved']));delta.select(state,ids)
    context=deepcopy(data);context.update(state=deepcopy(r['saved']),targets=deepcopy(targets['saved']),draft=deepcopy(drafts['saved']),pins=list(unique.values()));context['lineage']['state']=deepcopy(r['saved'])
    return dict(receipt=r,pin=pin,state=state,selected_ids=ids,source_sha256=source_sha256,context_data=context,targets=deepcopy(targets['saved']),draft=deepcopy(drafts['saved']),recipe=data['recipe'],candidate=data['candidate'],addin_clsid=data['lineage']['loaded']['addin_clsid'],pins=list(unique.values()),binding=deepcopy(old),configuration_authority_kind='explicit_saved_continuation',original_failure_pin=fp,depth_read_pin=dp)

