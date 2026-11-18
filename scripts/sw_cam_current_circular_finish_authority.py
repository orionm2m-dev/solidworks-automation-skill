"""Completed partial Save/CL authority for later independent circular definitions.
Historical configuration proofs retain their recorded source hash. Only the
physical source check receives the newer, separately verified Save SHA.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_saved_floor_wall_generation_continuation_authority as history
from scripts import sw_cam_partial_floor_wall_generation_save as producer
from scripts import sw_cam_saved_floor_wall_generation_delta as mixed
from scripts import sw_cam_current_saved_generation_delta as legacy
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes
original=history.original;projection=history.projection;depth_reader=history.depth_reader
config=history.config;writer=history.writer;common=history.common;delta=history.delta
require=history.require;exact=history.exact;CONTINUATION_SCOPE=history.CONTINUATION_SCOPE
_pin_record=history._pin_record;_owner=history._owner;_depth_proof=history._depth_proof

def _load_historical_configuration(r,pin,*,process_id,process_create_time,source_path,source_sha256,selected_ids,current_source_sha256):
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
    data=original.load_historical_read_authority(old,current_source_sha256)
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

def _full_pin(p):
    return producer._observed_pin(p)


def _parse_export(detail):
    require(detail.get('output_verified')is True and detail.get('readback_verified')is True,'Verified saved CL export required')
    pin=_full_pin(detail['output']);raw=Path(pin['path']).read_bytes()
    parsed=parse_generic_cl_bytes(raw,expected_block_record_counts=[r['toolpath_record_counts'][0]for r in detail['expected_generated_operations']])
    require(parsed.get('parse_complete')is True and parsed.get('native_count_matches')is True and parsed.get('declared_units')==['MM'],'Complete metric native-count-matched CL required')
    return parsed,pin


def _load_saved_native(r,pin,*,process_id,process_create_time,source_path,source_sha256,reconciliation=None,reconciliation_pin=None):
    reconciled=reconciliation is not None
    require(r.get('scope')==producer.SCOPE and r.get('phase')=='finished','Exact finished partial-generation Save producer required')
    require(not any(k in r for k in('runtime_error','runtime_receipt_update_error','cleanup_error','receipt_write_error')),'Unresolved native/runtime/cleanup failure')
    if reconciled:
        require(r.get('status')=='uncertain'and r.get('reason')=='Complete metric native-count-matched CL required'and r.get('issue',{}).get('type')=='ValueError','Only the exact completed CL parser rejection may be reconciled')
        locations=r['issue'].get('locations',[]);require(any(x.get('file')=='sw_cam_current_generation_native.py'and x.get('function')=='export_cl'for x in locations),'Exact native CL parser rejection location required')
        require(all(r.get(k)is False for k in('readback_verified','runtime_unchanged','partial_result_saved_verified')),'Original rejected verification flags must be retained')
    else:
        require(r.get('status')=='review_required'and not any(k in r for k in('issue','failed_phase')),'Completed native verification required')
        require(all(r.get(k)is True for k in('readback_verified','runtime_unchanged','partial_result_saved_verified')),'Completed native verification flags required')
    for k in('model_saved','save_readback_verified','source_update_verified','marker_created','save_returned_zero'):
        require(r.get(k)is True,'Missing saved partial result fact: '+k)
    for k in('native_dispatch_pending','GTP_attempted','GTP_replayed','GOP_attempted','AFR_attempted','parameter_setter_attempted','tool_assignment_attempted','operation_creation_attempted','automatic_replay','automatic_rollback','production_qualified'):
        require(r.get(k)is False,'Unexpected partial result authority: '+k)
    require(r.get('wall_generation_succeeded')is False or (reconciled and 'wall_generation_succeeded'not in r),'Unqualified wall success cannot be admitted')
    clean_events(r);request=r['request'];require(set(request)=={'action','params'}and request['action']==producer.ACTION,'Exact partial-save action required');v=request['params']
    require(set(v)==producer.PARAMS and v['acknowledgement']==producer.ACK,'Exact bounded producer request required')
    require(type(process_id)is int and type(v['process_id'])is int and v['process_id']==process_id and type(process_create_time)is type(v['expected_process_create_time'])and process_create_time==v['expected_process_create_time'],'Exact producer PID/lifetime required')
    require(common.same_path(v['expected_document_path'],source_path)and common.same_path(v['receipt_path'],pin['path'])and common.same_path(r['receipt_path'],pin['path']),'Source/receipt identity differs')
    source=Path(source_path);require(source.is_absolute()and source.is_file()and not source.is_symlink()and _file_hash(source)==source_sha256,'Exact current saved physical source required')
    require(v['expected_source_sha256']==r['source_before_sha256']and r['source_after_sha256']==r['saved_file_sha256']==source_sha256,'Honest new source transition required')
    require(v['module_sha256']==_file_hash(producer.__file__),'Exact completed producer code required')
    require(list(r['actions'])==['SaveActiveDocument','postCL']and all(producer.completed(a)for a in r['actions'].values()),'Exactly one returned Save0 and CL0, no GTP allowed')
    s=r['save_stage'];require(s.get('native_call_returned')is True and s.get('save_pending')is False and s.get('native_return_type')=='int'and type(s.get('native_return_value'))is int and s['native_return_value']==0,'Durable returned Save0 required')
    failure,fp=_pin_record(r['failure_receipt_pin']);require(common.same_path(fp['path'],v['failure_receipt_path'])and fp['sha256']==v['failure_receipt_sha256'],'Exact original failure required')
    require(failure.get('scope')==producer.generation.SCOPE and failure.get('status')=='uncertain'and failure.get('phase')=='finished'and failure.get('reason')=='Positive bounded actual generated count required','Exact empty-wall failure required')
    require(not any(k in failure for k in('runtime_error','cleanup_error','receipt_write_error'))and failure.get('native_dispatch_pending')is False,'Unresolved historical failure dispatch');clean_events(failure)
    for k in('save_attempted','model_saved','parameter_setter_attempted','tool_assignment_attempted','operation_creation_attempted','GOP_attempted','AFR_attempted','automatic_replay','automatic_rollback'):require(failure.get(k)is False,'Unexpected historical action: '+k)
    require(failure.get('GTP_attempted')is True and failure.get('marker_created')is True,'Original attempt evidence required')
    old=failure['request'];args=old['params'];require(old['action']=='generate_configured_local_group'and _digest(old)==failure['request_sha256'],'Sealed generation history changed')
    for k in('process_id','expected_process_create_time','expected_source_sha256'):require(exact(v[k],args[k]),'Historical generation owner/source differs')
    require(common.same_path(args['expected_document_path'],source_path)and failure['source_before_sha256']==r['source_before_sha256'],'Historical generation source changed')
    ids=args['selected_operation_native_ids'];require(exact(ids,failure['selected_operation_native_ids'])and exact(ids,r['selected_operation_native_ids']),'Selected pair changed')
    require(list(failure['actions'])==['preCL','GTP:'+str(ids[0]),'GTP:'+str(ids[1])]and all(producer.completed(a)for a in failure['actions'].values()),'Exact returned preCL and two GTP history required')
    cfg,cp=read_pin(args['configuration_receipt_path'],args['configuration_receipt_sha256']);require(cfg.get('scope')==CONTINUATION_SCOPE,'Established saved continuation ancestry required')
    loaded=_load_historical_configuration(cfg,cp,process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=r['source_before_sha256'],selected_ids=ids,current_source_sha256=source_sha256)
    require(exact(cp,failure['configuration_receipt_pin'])and exact(cp,r['configuration_receipt_pin']),'Historical configuration pin differs')
    reference=failure['before_GTP_'+str(ids[1])];mixed.verify_generation(loaded['state'],reference,ids,[ids[0]])
    for key in('after_GTP_'+str(ids[0]),'confirm_GTP_'+str(ids[0])):require(mixed.same(reference,failure[key]),'Confirmed floor history differs')
    info=legacy.inventory(loaded['state']);count=next(x['toolpath_record_counts'][0]for x in reference['operations']if x['native_id']==ids[0])
    data=dict(selected_ids=deepcopy(ids),floor_count=count,old_generated_count=len(info['generated']),old_record_count=info['total_record_count'],configured_state=deepcopy(loaded['state']),reference_state=deepcopy(reference),expected_state=deepcopy(r['saved']),failed_request=deepcopy(args),loaded=loaded)
    for key in('after_GTP_'+str(ids[1]),'failure_actual'):producer.verify_raw_rows(loaded['state']['operations'],failure[key]['operations'],data)
    require(exact(failure['after_GTP_'+str(ids[1])]['operations'],failure['failure_actual']['operations']),'Original zero-data wall observations differ')
    marker,mp=_pin_record(r['historical_marker_pin']);require(common.same_path(mp['path'],failure['dispatch_marker_path']),'Original attempt marker path differs')
    want=dict(scope=producer.generation.SCOPE,receipt_path=fp['path'],receipt_sha256=fp['sha256'],configuration_receipt_pin=loaded['pin'],selected_operation_native_ids=ids,status='uncertain',phase='finished',automatic_replay=False);observed=deepcopy(marker);require(common.same_path(observed['receipt_path'],fp['path']),'Historical marker receipt differs');observed['receipt_path']=fp['path'];require(exact(observed,want),'Historical consumed marker changed')
    require(exact(r['positive_generated_operation_native_ids'],[ids[0]])and r['failed_empty_operation_native_id']==ids[1],'Partial success/empty identities differ')
    require(common.same_path(r['dispatch_marker_path'],producer.marker_path(v)),'Exact new-scope marker path required')
    terminal,tm=read_pin(r['dispatch_marker_path'],_file_hash(r['dispatch_marker_path']));want=dict(scope=producer.SCOPE,receipt_path=pin['path'],receipt_sha256=pin['sha256'],failure_receipt_pin=fp,status=r['status'],phase='finished',automatic_replay=False);actual=deepcopy(terminal);require(common.same_path(actual['receipt_path'],pin['path']),'Terminal marker receipt differs');actual['receipt_path']=pin['path'];require(exact(actual,want),'Terminal consumed partial-save marker differs')
    before=producer.verify_full_state(data,r['before_save'],r['source_before_sha256']);after=producer.verify_full_state(data,r['saved'],source_sha256,allow_cleanup=True)
    require(exact(before,r['before_proof'])and exact(after,r['after_proof']),'Recomputed saved proof differs')
    require(r['saved']['document']['needs_save']is False and r['saved']['sketch_state']['needs_save']is False,'Actual clean saved snapshot required')
    post=r['postCL']
    if not reconciled:require(r['final_capture_source']=='postCL.after','Exact final actual observation source required')
    for key in('before','after'):
        producer.verify_full_state(data,post[key],source_sha256,allow_cleanup=True);require(mixed.same(post[key],r['saved']),'Saved raw state changed during CL export')
    pre=failure['preCL'];require(exact(pre['expected_generated_operations'],info['generated'])and mixed.same(pre['before'],loaded['state'])and mixed.same(pre['after'],loaded['state']),'Original protected preCL authority differs')
    pre_parsed,prepin=_parse_export(pre)
    rows=legacy.inventory(producer.project_empty_wall(r['saved'],data,allow_cleanup=True))['generated'];require(exact(rows,post['expected_generated_operations']),'Positive-only CL inventory differs')
    extra_pins=[]
    if reconciled:
        from scripts import sw_cam_empty_cl_comparison as comparison
        reconcile=reconciliation
        require(exact(_pin_record(reconcile['raw_partial_save_receipt_pin'])[1],pin)and exact(_pin_record(reconcile['failed_generation_receipt_pin'])[1],fp),'Reconciliation raw receipt pins differ')
        source_pin=_full_pin(reconcile['source_after']);require(common.same_path(source_pin['path'],source_path)and source_pin['sha256']==source_sha256,'Reconciled actual saved source differs')
        postpin=_full_pin(reconcile['post_CL_pin']);require(common.same_path(postpin['path'],v['saved_cl_path'])and 0<postpin['bytes']<=64*1024*1024,'Exact bounded raw native CL output required')
        before_pin=_full_pin(reconcile['pre_CL_pin']);require(common.same_path(before_pin['path'],prepin['path'])and before_pin['sha256']==prepin['sha256'],'Reconciled old CL differs')
        helperpin=_full_pin(reconcile['comparison_helper_pin']);require(helperpin['sha256']==_file_hash(comparison.__file__),'Exact reviewed comparison helper required')
        parserpin=_full_pin(reconcile['parser_pin']);require(parserpin['sha256']==_file_hash(__import__('inspect').getsourcefile(parse_generic_cl_bytes)),'Exact parser implementation required')
        actual_proof,post_parsed,raw_parsed=comparison.reconcile(Path(postpin['path']).read_bytes(),Path(prepin['path']).read_bytes(),pre['expected_generated_operations'],rows,empty_native_id=ids[1],added_native_id=ids[0],expected_empty_label=reconcile['comparison_proof']['empty_block']['label'])
        require(exact(actual_proof,reconcile['comparison_proof']),'Independent empty-block byte projection differs')
        require(reconcile.get('old19_complete_streams_verified')is True and reconcile.get('saved_states_verified')is True,'Independent saved states and protected CL verification required')
        require(type(reconcile['machining_path_count'])is int and reconcile['machining_path_count']==len(rows)and type(reconcile['native_collection_count'])is int and reconcile['native_collection_count']==len(rows)+1 and type(reconcile['total_records'])is int and reconcile['total_records']==sum(x['toolpath_record_counts'][0]for x in rows),'Reconciled positive/native counts differ')
        preserved={k:r[k]for k in('status','phase','readback_verified','runtime_unchanged','partial_result_saved_verified','model_saved','save_readback_verified','source_update_verified')};require(exact(reconcile['preserved_raw_flags'],preserved),'Raw native flags were reinterpreted')
        require(reconcile.get('file_only_reconciliation')is True and reconcile.get('raw_receipt_modified')is False and reconcile.get('raw_CL_modified')is False and reconcile.get('runtime_modified')is False and type(reconcile.get('native_calls'))is int and reconcile['native_calls']==0,'File-only immutable reconciliation required')
        require(exact(reconcile['positive_operation_mapping'],rows),'Explicit positive mapping differs')
        require(exact(reconcile['raw_parse_summary'],{k:raw_parsed[k]for k in reconcile['raw_parse_summary']}),'Raw parser observations differ')
        extra_pins=[reconciliation_pin,source_pin,helperpin,parserpin,dict(path=comparison.__file__,sha256=_file_hash(comparison.__file__))]
    else:post_parsed,postpin=_parse_export(post)
    proof=legacy.compare_cl(pre_parsed,post_parsed,pre['expected_generated_operations'],rows,[ids[0]])
    require(exact(proof,reconciliation['comparison_proof']['CL_preservation']if reconciled else r['CL_preservation']),'Full protected CL preservation differs')
    wall=lambda state:next(x['toolpath_record_counts']for x in state['operations']if x['native_id']==ids[1])
    require(exact(r['wall_postSave_transition'],dict(before=wall(r['before_save']),after=wall(r['saved']),raw_preserved=True)),'Raw empty-wall transition differs')
    from scripts import sw_cam_mill_current_parameters as parameters
    native_authority=parameters.load_authority(loaded['context_data']['lineage']['loaded']['circular']['original']['binding']);definition_mode=native_authority['definition_mode']
    pins=list(loaded['pins'])+[pin,fp,mp,tm,prepin,postpin,native_authority['pin']]+extra_pins
    modules=(__file__,producer.__file__,Path(producer.__file__).with_name('sw_cam_partial_floor_wall_generation_context.py'))
    for module in modules[1:]:require(any(common.same_path(p['path'],module)and p['sha256']==_file_hash(module)for p in r['evidence_pins']),'Pinned completed recovery producer/helper required')
    for witness in(failure,r):
        for p in witness['evidence_pins']:
            if common.same_path(p['path'],source_path):require(p['sha256']==r['source_before_sha256'],'Historical physical source pin differs');continue
            common.direct(p);pins.append(p)
    pins.extend(dict(path=str(p),sha256=_file_hash(p))for p in modules);pins.append(dict(path=str(source),sha256=source_sha256))
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold()
        if common.same_path(p['path'],source_path):require(p['sha256']in(r['source_before_sha256'],source_sha256),'Unexpected source lineage pin');p=dict(path=str(source),sha256=source_sha256)
        require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting immutable next-step pins');unique[key]=_full_pin(p)
    pins=list(unique.values());require(_file_hash(source)==source_sha256 and read_pin(pin['path'],pin['sha256'])[1]==pin,'Authority/source changed while binding')
    data['loaded']['pins']=deepcopy(pins);data['loaded']['context_data']['pins']=deepcopy(pins);data['pins']=deepcopy(pins)
    return dict(receipt=r,pin=pin,authority_pin=reconciliation_pin if reconciled else pin,reconciliation_receipt=reconciliation,reconciliation_pin=reconciliation_pin,state=deepcopy(r['saved']),pins=pins,addin_clsid=loaded['addin_clsid'],recovery_data=data,definition_mode=definition_mode,source_sha256=source_sha256,positive_generated_operations=rows,CL_preservation=proof,wall_generation_succeeded=False,production_qualified=False)


def load_completed(path,sha,*,process_id,process_create_time,source_path,source_sha256):
    outer,pin=read_pin(path,sha)
    kwargs=dict(process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=source_sha256)
    if outer.get('scope')=='PARTIAL_FLOOR_CL_FILE_RECONCILIATION_V1':
        require(outer.get('status')=='PASS_SCOPED_RECONCILIATION','Completed independent scoped reconciliation required')
        r,rp=_pin_record(outer['raw_partial_save_receipt_pin'])
        return _load_saved_native(r,rp,reconciliation=outer,reconciliation_pin=pin,**kwargs)
    return _load_saved_native(outer,pin,**kwargs)
