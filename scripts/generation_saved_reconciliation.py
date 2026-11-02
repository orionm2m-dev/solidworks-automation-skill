"""Offline reconciliation of a completed Save stopped by the old CL count cap.

The original uncertain receipt and flags remain unchanged. Native actions are
never exposed here. This contract accepts only the exact parser-limit boundary.
"""
from copy import deepcopy

def require(v,message):
    if not v:raise ValueError(message)

ISSUE={'type':'ValueError','hresult':None,'actual_return_type':None,'locations':[
 {'file':'sw_cam_deep_guide_cl.py','function':'_parse','line':58},
 {'file':'sw_cam_generic_cl_reader.py','function':'parse_generic_cl_bytes','line':124},
 {'file':'sw_cam_rough_firstcut.py','function':'require','line':38}]}

def native_completion(r,loaded,p):
    """Repeat frozen terminal native facts, retaining the actual failure status."""
    group=p.group;prior=p.prior;configured=p.configured;engine=p.engine
    c=loaded['configuration_generation'];targets=c['targets'];ids=engine.ids(targets,'operation_native_id')
    require(r['scope']==p.SCOPE and r['status']=='uncertain' and r['phase']=='finished' and r['failed_phase']=='SaveActiveDocument','Exact completed parser-stop scope required')
    require(group.exact(r['issue'],ISSUE),'Only the archived count-cap failure can be reconciled')
    require(not any(r.get(k) for k in ('cleanup_issue','terminal_issue','nc_restore_candidate')),'Additional issue cannot be reconciled')
    require(not any(k in r for k in ('saved_cl','saved_cl_verification','saved_checkpoint','terminal_verification')),'Unexpected completed terminal fields')
    for key in ('model_saved','GTP_attempted','native_call_attempted','native_call_returned','mutation_attempted'):
        require(r[key]is True,'Actual completed generation and Save required: '+key)
    for key in ('native_dispatch_pending','readback_verified','continuation_ready','cleanup_session_active','automatic_retry','automatic_rollback','operation_creation_attempted','tool_assignment_attempted','parameter_setter_attempted','physical_cutting_conditions_qualified','production_qualified','geometry_accepted','persistence_after_reopen_verified'):
        require(r[key]is False,'Original fail-closed state or scope differs: '+key)
    prior.clean_events(r)
    require(group.exact(r['configuration_receipt_pin'],loaded['configuration_receipt_pin']) and group.exact(r['learned_targets'],targets) and r['actual_new_ids']==ids,'Exact saved authority and learned IDs required')
    require(group.exact(r['before'],c['snapshot']) and group.exact(r['configured'],r['before']),'Exact saved configuration adoption required')
    require(list(r['actions'])==['GTP:'+str(i)for i in ids]+['SaveActiveDocument'],'Exactly four once GTP calls followed by one Save required')
    counts={int(k):v for k,v in r['completed_gtp_counts'].items()};require(set(counts)==set(ids),'All four native outcomes required')
    for t in targets:
        a=r['actions']['GTP:'+str(t['operation_native_id'])];configured.verified_action(a)
        require(a['attempted']is True and a['returned']is True,'Completed vendor call required')
        p.generation.status_contract(a['observed'],t,True)
        require(group.exact(a['observed']['record_counts'],counts[t['operation_native_id']]),'Native outcome count differs')
    policy={t['key']:[]for t in targets};require(group.exact(r['feed_policy'],policy),'No feed transition permitted')
    proof=engine.verify_generation(r['configured'],r['generated'],targets,counts,policy)
    require(group.exact(proof,r['generation_verification']) and group.exact(r['saved'],r['generated']),'Saved generation differs')
    a=r['actions']['SaveActiveDocument'];configured.verified_action(a);new=prior._sha(r['saved_source_sha256'])
    require(a['attempted']is True and a['observed']==new and new!=r['source_sha256'],'Actual changed-source Save required')
    transition=r['source_transition'];require(transition['source_before_sha256']==r['source_sha256'] and transition['source_after_sha256']==new and type(transition['strict_save_return'])is int and transition['strict_save_return']==0 and transition['document']['needs_save']is False,'Strict Save and clean document required')
    require(group.exact(r['current_document'],transition['document']),'Current clean document echo differs')
    stage=r['save_stage'];require(stage['phase']=='after_capture' and stage['save_pending']is False and stage['save_readback_verified']is True and stage['saved_file_sha256']==new and stage['native_return_type']=='int' and type(stage['native_return_value'])is int and stage['native_return_value']==0,'Complete Save stage required')
    require(group.exact(stage['before'],r['generated']) and group.exact(stage['after'],r['saved']),'Save stage snapshots contradict saved evidence')
    require([v['phase']for v in r['phase_proof_checks']]==['before_native_start','before_save'] and all(v['verified']is True for v in r['phase_proof_checks']),'Only the reached phase checks may be recorded')
    return dict(status='saved_generation_native_facts_reconciled_offline',operations=21,parameters=12,paths=18,new_generated_paths=4,protected_old_paths=14,source_sha256=new,original_status=r['status'],original_readback_verified=False,original_receipt_modified=False,geometry_accepted=False,production_qualified=False)

def completed_export_observation(r,p):
    group=p.group;d=r['cl_exports']['saved']
    require(set(r['cl_exports'])=={'saved'} and d['label']=='saved' and d['status']=='pending','Exact interrupted single export required')
    for k in ('native_call_attempted','native_call_returned','output_directory_created','output_absent_before_dispatch'):
        require(d[k]is True,'Completed native export required: '+k)
    for k in ('native_dispatch_pending','output_verified','readback_verified','parent_session_preserved','GTP_attempted','model_saved','production_qualified'):
        require(d[k]is False,'Original export flags differ: '+k)
    require(group.exact(d['native_return'],{'python_type':'int','value_recorded':True,'value':0}),'Exact SaveCLFile return0 required')
    require(p.common._key(d['output_path'])==p.common._key(r['request']['saved_cl_path']) and d['source_sha256']==r['saved_source_sha256'] and group.exact(d['document'],r['source_transition']['document']),'Export source/document/path differs')
    captures=r['captures'];labels=[v['label']for v in captures]
    require(labels==['saved_configuration_before_gtp','generated_four','saved_generated_four','saved_before_cl','saved_after_cl'],'Exact captured milestones required')
    require(all(v['read_batch']['read_scope_complete']is True and v['read_batch']['active']is False and v['read_batch']['invalid']is False for v in captures),'All actual read batches must complete')
    for capture,key in zip(captures[:3],['before','generated','saved']):
        require(group.exact({k:capture[k]for k in ['binding','parameters']},r[key]),'Actual full capture contradicts snapshot: '+key)
    for v in captures[-2:]:
        require(group.exact(v['binding'],r['saved']['binding']) and v['parameters']==[],'Complete protected export binding differs')
    rows=[dict(operation_native_id=v['native_id'],toolpath_record_counts=deepcopy(v['toolpath_record_counts']))for v in r['saved']['binding']['operations']if v['toolpath_generated']is True]
    require(group.exact(rows,d['expected_generated_operations']) and len(rows)==18,'Export native order/counts differ')
    total=sum(v['toolpath_record_counts'][0]for v in rows)
    require(100000<total<=200000 and all(type(v['toolpath_record_counts'][0])is int and 0<v['toolpath_record_counts'][0]<=100000 for v in rows),'Only the known bounded aggregate cap may be exceeded')
    return deepcopy(d)

def cl_protection(prior,current,oldrows,newrows,targets,signature,bind_prefix):
    proof=bind_prefix(prior,current,oldrows,newrows,targets,signature)
    require(prior['declared_units']==current['declared_units']==['MM'],'Exact metric CL required')
    require([v['raw']for v in prior['commands']if v['name']=='BOX']==[v['raw']for v in current['commands']if v['name']=='BOX'],'Stock declaration differs')
    blocks=set(range(14,18));motions=[v for v in current['motions']if v['block']in blocks]
    require({v['block']for v in motions}==blocks,'Every new stream must contain motion')
    require(not any(v.get('block')in blocks for v in current['cutcom_records']),'New CUTCOM declaration forbidden')
    require(all(v.get('cutcom_state',{}).get('status')=='not_declared'for v in motions),'New compensation state differs')
    return proof
