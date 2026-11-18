"""Explicit saved existing-operation revision adapter for the existing WIP core.
Pure file validation; native once/export/cleanup remain the existing outer lifecycle.
"""
from copy import deepcopy
import json, math
from scripts import sw_cam_circular_reconfigure as writer
from scripts import sw_cam_current_circular_wip_binding as common
require=common.require
same=common.authority.circular_state_equal


def strict_mapping(rows):
    require(type(rows)is list and 1<=len(rows)<=common.delta.MAX_OPERATIONS
        and all(type(x)is dict and set(x)=={'operation_native_id','toolpath_record_counts'}
            and type(x['operation_native_id'])is int and x['operation_native_id']>0
            and type(x['toolpath_record_counts'])is list and len(x['toolpath_record_counts'])==1
            and type(x['toolpath_record_counts'][0])is int and 0<x['toolpath_record_counts'][0]<=common.delta.MAX_RECORDS
            for x in rows),'Strict bounded generated mapping required')
    ids=[x['operation_native_id']for x in rows]
    require(len(set(ids))==len(ids),'Unique generated IDs required')
    return ids


def bind_completed_revision(receipt_pin,*,process_id,process_create_time,source_path,source_sha256,
                            selected_operation_ids,protected_operation_ids,expected_generated_operations,
                            marker_pin,writer_pin,read_pin=common.direct,parser=common.parse_generic_cl_bytes,verify_current_source=True):
    """Accept only this writer's saved replacement, never a boolean claim."""
    require(type(verify_current_source)is bool,'Strict source verification policy required')
    r=json.loads(read_pin(receipt_pin));common.strict_sha(source_sha256)
    require(type(process_id)is int and process_id>0 and type(process_create_time)in(int,float)
        and math.isfinite(process_create_time) and process_create_time>0,'Explicit owner/lifetime required')
    require(type(selected_operation_ids)is list and len(selected_operation_ids)==1
        and type(selected_operation_ids[0])is int and selected_operation_ids[0]>0,'One explicit existing target required')
    oid=selected_operation_ids[0];new_ids=strict_mapping(expected_generated_operations)
    require(type(protected_operation_ids)is list and all(type(x)is int for x in protected_operation_ids)
        and protected_operation_ids==[x for x in new_ids if x!=oid]
        and new_ids.count(oid)==1,'Exact protected generated mapping required')
    require(r.get('scope')==writer.SCOPE and r.get('status')=='review_required' and r.get('phase')=='finished'
        and r.get('reason')=='ONE_SELECTED_RECONFIGURATION_GTP_SAVE_AND_PROTECTED_CL_VERIFIED',
        'Successful existing-operation writer terminal required')
    require(not any(k in r for k in ('issue','runtime_error','cleanup_error','receipt_write_error','failure_capture_issue','failed_phase')),
        'Unresolved writer failure')
    common.clean_events(r)
    for key in ('continuation_verified','readback_verified','runtime_unchanged','model_saved','save_readback_verified',
                'source_update_verified','GTP_attempted','save_attempted','CL_export_attempted','parameter_setter_attempted',
                'receipt_created','marker_created','mutation_attempted','native_call_attempted','native_call_returned'):
        require(r.get(key)is True,'Missing writer terminal fact: '+key)
    for key in ('native_dispatch_pending','GOP_attempted','AFR_attempted','operation_creation_attempted',
                'tool_assignment_attempted','automatic_replay','automatic_rollback','selected_cached_path_is_stale'):
        require(r.get(key)is False,'Unexpected writer terminal action: '+key)
    req=r['request'];require(set(req)==writer.KEYS and req['qualification_only']is True
        and req['message_policy']=='vendor_default','Exact writer request required')
    require(type(req['process_id'])is int and req['process_id']==process_id
        and type(req['expected_process_create_time'])is type(process_create_time)
        and req['expected_process_create_time']==process_create_time,'Writer owner/lifetime differs')
    require(common.same_path(req['expected_document_path'],source_path)
        and r['source_after_sha256']==r['saved_file_sha256']==source_sha256
        and req['expected_source_sha256']==r['source_before_sha256'],'Source transition differs')
    require(common.same_path(req['receipt_path'],receipt_pin['path'])
        and common.same_path(r['receipt_path'],receipt_pin['path'])
        and common.same_path(r['dispatch_marker_path'],marker_pin['path']),'Receipt/marker path differs')
    recipe=json.loads(read_pin(r['recipe_pin']))
    require(recipe==r['recipe'] and recipe['operation_native_id']==r['operation_native_id']==oid
        and common.same_path(r['recipe_pin']['path'],req['recipe_path'])
        and r['recipe_pin']['sha256']==req['recipe_sha256'],'Pinned recipe differs')
    before,configured,generated,saved=(r[k]for k in ('before','configured','generated','saved'))
    old=common.complete_state(before,process_id,r['source_before_sha256'])
    for state in (configured,generated):common.complete_state(state,process_id,r['source_before_sha256'])
    new=common.complete_state(saved,process_id,source_sha256)
    for state in (before,saved):
        require(state['document']['needs_save']is False and state['sketch_state']['needs_save']is False
            and common.same_path(state['document']['path'],source_path),'Exact clean saved document required')
    require(strict_mapping(old['generated'])==new_ids and new['generated']==expected_generated_operations,
        'Existing ordered generated inventory/counts differ')
    writer.validate_recipe(recipe,before)
    require(writer.verify_configuration(before,configured,recipe)==r['configuration_proof'],'Configuration proof differs')
    require(writer.verify_generation(configured,generated,oid)==r['generation_proof'],'Generation proof differs')
    common.authority.pocket.verify_saved(generated,saved,source_sha256)
    require(same(saved,r['confirm_saved']),'Complete saved confirmation differs')
    labels=['before','configured','generated','saved','confirm_saved']
    require([x['label']for x in r['captures']]==labels
        and all(x.get('capture_complete')is True and same(x['state'],r[x['label']])for x in r['captures']),
        'Actual complete writer capture journal differs')
    changes=[('nc:'+x['field'],x)for x in recipe['nc']]+[('rough:'+x['field'],x)for x in recipe['rough']]
    expected_actions=[x[0]for x in changes]+['GTP:'+str(oid),'SaveActiveDocument','postCL']
    require(list(r['actions'])==expected_actions,'Exact setter/GTP/Save/CL action sequence required')
    for name,change in changes:
        action=deepcopy(r['actions'][name]);observed=action.pop('immediate_readback')
        require(common.completed_action(action) and writer.fields.equal(observed,change['new']),
            'Setter return or immediate readback differs')
    require(all(common.completed_action(r['actions'][k])for k in expected_actions[-3:]),'Completed GTP/Save/CL required')
    stage=r['save_stage'];require(stage.get('native_call_returned')is True and stage.get('save_pending')is False
        and stage.get('native_return_type')=='int' and type(stage.get('native_return_value'))is int
        and stage['native_return_value']==0,'Durable Save return required')
    marker=json.loads(read_pin(marker_pin))
    expected_marker=dict(scope=writer.SCOPE,receipt_path=receipt_pin['path'],receipt_sha256=receipt_pin['sha256'],
        source_before_sha256=r['source_before_sha256'],recipe_pin=r['recipe_pin'],status='review_required',phase='finished',automatic_replay=False)
    require(set(marker)==set(expected_marker) and common.same_path(marker['receipt_path'],receipt_pin['path']),
        'Consumed revision marker fields/path differ')
    marker['receipt_path']=expected_marker['receipt_path'];require(marker==expected_marker,'Consumed revision marker differs')
    post=r['postCL'];require(post.get('output_verified')is True and post.get('readback_verified')is True
        and post['source_sha256']==source_sha256 and post['expected_generated_operations']==new['generated']
        and common.same_path(post['output']['path'],req['saved_cl_path'])
        and same(post['before'],saved) and same(post['after'],saved),'Saved CL context/readback differs')
    parsed=[]
    for pin,rows in ((r['historical_CL_pin'],old['generated']),(post['output'],new['generated'])):
        parsed.append(parser(read_pin(pin),expected_block_record_counts=[x['toolpath_record_counts'][0]for x in rows]))
    preservation=writer.compare_replacement_cl(*parsed,old['generated'],new['generated'],oid)
    require(preservation==r['CL_preservation'] and preservation['protected_operation_native_ids']==protected_operation_ids,
        'Protected complete CL stream proof differs')
    evidence=r['evidence_pins'];require(type(evidence)is list and 1<=len(evidence)<=32,'Bounded evidence pins required')
    for pin in (writer_pin,dict(path=req['nc_receipt_path'],sha256=req['nc_receipt_sha256']),r['recipe_pin']):
        require(any(common.same_path(x['path'],pin['path']) and x['sha256']==pin['sha256']for x in evidence),
            'Required writer/NC/recipe evidence pin absent')
    require(common.same_path(writer_pin['path'],writer.__file__),'Loaded writer path differs')
    pins=[deepcopy(x)for x in [receipt_pin,marker_pin,writer_pin,*evidence,r['historical_CL_pin'],post['output'],
                              dict(path=source_path,sha256=source_sha256)]]
    for pin in pins:
        if not verify_current_source and common.same_path(pin['path'],source_path):
            require(pin['sha256']==source_sha256,'Historical source pin differs');continue
        read_pin(pin)
    result=dict(scope=common.SCOPE,producer_scope=writer.SCOPE,process_id=process_id,process_create_time=process_create_time,
        source_path=source_path,source_sha256=source_sha256,receipt_pin=deepcopy(receipt_pin),pins=pins,
        document=deepcopy(saved['document']),snapshot=deepcopy(saved),selected_operation_ids=deepcopy(selected_operation_ids),
        protected_operation_ids=deepcopy(protected_operation_ids),expected_generated_operations=deepcopy(new['generated']),
        total_native_records=new['total_record_count'],operation_count=len(new['rows']),protected_complete_streams=preservation,
        saved_CL=deepcopy(post['output']),producer_terminal_revalidated=True,request_sha256=common._digest(req))
    if not verify_current_source:result.update(physical_source_verified=False,source_verification_scope='historical_metadata_only')
    result['binding_sha256']=common.digest(result)
    return result
