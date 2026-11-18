"""Completed ordinary-circle creation authority for later selected configuration.
Prior receipts retain their historical source; only physical source pins advance.
No COM, mutation, output or guessed future receipt acceptance.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_current_circular_finish as creation
from scripts import sw_cam_current_circular_finish_authority as prior
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes
from scripts.sw_cam_turn_tool import _digest
producer=prior.producer;mixed=prior.mixed;legacy=prior.legacy;common=prior.common
require=prior.require;exact=prior.exact;CONTINUATION_SCOPE=prior.CONTINUATION_SCOPE
_pin_record=prior._pin_record;_full_pin=prior._full_pin;_parse_export=prior._parse_export
_load_historical_configuration=prior._load_historical_configuration

def _load_prior_saved_native(r,pin,*,process_id,process_create_time,source_path,source_sha256,reconciliation=None,reconciliation_pin=None,physical_source_sha256):
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
    source=Path(source_path);require(source.is_absolute()and source.is_file()and not source.is_symlink()and _file_hash(source)==physical_source_sha256,'Exact current saved physical source required')
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
    loaded=_load_historical_configuration(cfg,cp,process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=r['source_before_sha256'],selected_ids=ids,current_source_sha256=physical_source_sha256)
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
        source_pin=deepcopy(reconcile['source_after']);require(common.same_path(source_pin['path'],source_path)and source_pin['sha256']==source_sha256,'Reconciled actual saved source differs')
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
    pins.extend(dict(path=str(p),sha256=_file_hash(p))for p in modules);pins.append(dict(path=str(source),sha256=physical_source_sha256))
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold()
        if common.same_path(p['path'],source_path):require(p['sha256']in(r['source_before_sha256'],source_sha256,physical_source_sha256),'Unexpected source lineage pin');p=dict(path=str(source),sha256=physical_source_sha256)
        require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting immutable next-step pins');unique[key]=_full_pin(p)
    pins=list(unique.values());require(_file_hash(source)==physical_source_sha256 and read_pin(pin['path'],pin['sha256'])[1]==pin,'Authority/source changed while binding')
    data['loaded']['pins']=deepcopy(pins);data['loaded']['context_data']['pins']=deepcopy(pins);data['pins']=deepcopy(pins)
    return dict(receipt=r,pin=pin,authority_pin=reconciliation_pin if reconciled else pin,reconciliation_receipt=reconciliation,reconciliation_pin=reconciliation_pin,state=deepcopy(r['saved']),pins=pins,addin_clsid=loaded['addin_clsid'],recovery_data=data,definition_mode=definition_mode,source_sha256=source_sha256,positive_generated_operations=rows,CL_preservation=proof,wall_generation_succeeded=False,production_qualified=False)

def _load_prior(v,physical_sha):
    proof,pp=read_pin(v['saved_result_receipt_path'],v['saved_result_receipt_sha256'])
    if proof.get('scope')=='SAVED_PARTIAL_CURRENT_OWNER_CONTINUATION_V1':
        from scripts import sw_cam_current_finish_configuration_owner as owner_adapter
        return owner_adapter.load_prior(v,proof,pp,physical_sha)
    require(proof.get('scope')=='PARTIAL_FLOOR_CL_FILE_RECONCILIATION_V1'and proof.get('status')=='PASS_SCOPED_RECONCILIATION','Explicit prior scoped reconciliation required')
    r,rp=_pin_record(proof['raw_partial_save_receipt_pin'])
    return _load_prior_saved_native(r,rp,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'],reconciliation=proof,reconciliation_pin=pp,physical_source_sha256=physical_sha)

def _terminal(r,pin,process_id,process_create_time,source_path,source_sha256):
    require(r.get('scope')==creation.SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished'and r.get('action')=='apply','Completed actual ordinary-circle creation Save required')
    require(not any(k in r for k in('issue','failed_phase','runtime_error','cleanup_error','receipt_write_error')),'Unresolved creation failure')
    for k in('definition_saved_verified','geometry_delta_verified','operation_delta_verified','readback_verified','runtime_unchanged','model_saved','save_readback_verified','source_update_verified','receipt_created','marker_created','save_returned_zero','reference_geometry_creation_attempted','operation_creation_attempted','save_attempted','mutation_attempted'):
        require(r.get(k)is True,'Missing completed creation fact: '+k)
    for k in('native_dispatch_pending','GTP_attempted','GOP_attempted','AFR_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','CL_export_attempted','automatic_replay','automatic_rollback','production_qualified','machining_eligible'):
        require(r.get(k)is False,'Unexpected creation action or qualification: '+k)
    clean_events(r);v=r['request'];require(type(v)is dict and set(v)==creation.KEYS and v['action']=='apply'and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact completed creation request required')
    require(type(process_id)is int and type(v['process_id'])is int and process_id==v['process_id']and type(process_create_time)is type(v['expected_process_create_time'])and process_create_time==v['expected_process_create_time'],'Current owner differs')
    require(common.same_path(source_path,v['expected_document_path'])and common.same_path(pin['path'],v['receipt_path'])and common.same_path(pin['path'],r['receipt_path']),'Creation source/receipt path differs')
    require(exact(r['binding'],creation.binding(v))and v['expected_source_sha256']==r['source_before_sha256']and r['source_after_sha256']==r['saved_file_sha256']==source_sha256,'Honest completed creation source transition required')
    source=Path(source_path);require(source.is_file()and not source.is_symlink()and _file_hash(source)==source_sha256,'Current saved physical source differs')
    names=['CreateSketch','CreateMillFeature2','InsertOperation','SaveActiveDocument'];require(list(r['actions'])==names,'Exactly one sketch, feature, Finish and Save required')
    for name,a in r['actions'].items():require(a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False,'Unfinished creation action: '+name)
    for name in('CreateMillFeature2','InsertOperation'):require(r['actions'][name].get('native_observation',{}).get('nonnull')is True,'Missing actual returned object: '+name)
    require(producer.completed(r['actions']['SaveActiveDocument']),'Durable Save int0 required')
    stage=r['save_stage'];require(stage.get('native_call_returned')is True and stage.get('save_pending')is False and stage.get('native_return_type')=='int'and type(stage.get('native_return_value'))is int and stage['native_return_value']==0,'Durable Save stage differs')
    return v

def load_completed(path,sha,*,process_id,process_create_time,source_path,source_sha256):
    r,pin=read_pin(path,sha)
    if r.get('scope')=='CURRENT_CIRCULAR_FINISH_AFTER_SKETCH_V1':
        from scripts import sw_cam_completed_finish_after_sketch_authority as continuation
        return continuation.load_completed(path,sha,process_id=process_id,process_create_time=process_create_time,source_path=source_path,source_sha256=source_sha256)
    v=_terminal(r,pin,process_id,process_create_time,source_path,source_sha256)
    original=_load_prior(v,source_sha256);recipe,rp=read_pin(v['recipe_path'],v['recipe_sha256']);spec=creation.validate_recipe(recipe,original['state'])
    require(exact(rp,r['recipe_pin'])and exact(original['authority_pin'],r['authority_pin'])and exact(original['pin'],r['raw_saved_result_pin']),'Exact prior authority and recipe pins required')
    before=deepcopy(r['before']);extra=before.pop(creation.delta.EXTRA);require(exact(extra,{})and mixed.same(before,original['state']),'Fresh actual creation baseline differs from prior saved29')
    fid=r['new_feature_native_id'];oid=r['new_operation_native_id'];names=r['created_names'];require(type(fid)is int and type(oid)is int and fid>0 and oid>0,'Actual returned new IDs required')
    compact=r['compact_before_save'];cp=creation.verify_compact(r['before'],compact,spec,fid,oid,names)
    final=creation.verify_final(r['before'],r['saved'],spec,fid,oid,names,source_sha256,compact)
    require(exact(cp,r['compact_proof'])and exact(final,r['saved_full_proof']),'Recomputed compact/final saved proof differs')
    captures=r['captures'];require(type(captures)is list and [x['label']for x in captures]==['before','saved']and all(x.get('capture_complete')is True and exact(x['state'],r[x['label']])for x in captures),'Actual before and saved full captures required')
    prep,pp=read_pin(v['prepare_receipt_path'],v['prepare_receipt_sha256']);require(prep.get('scope')==creation.SCOPE and prep.get('action')=='prepare'and prep.get('status')=='review_required'and prep.get('phase')=='finished'and prep.get('mutation_attempted')is False and prep.get('native_observation_performed')is False and all(prep.get(k)is True for k in('readback_verified','runtime_unchanged','may_apply'))and not any(k in prep for k in('issue','runtime_error','cleanup_error')),'Exact completed file-only prepare required')
    require(exact(prep['binding'],r['binding'])and exact(prep['authority_pin'],r['authority_pin'])and exact(prep['recipe_pin'],rp)and mixed.same(prep['before'],original['state']),'Completed prepare lineage differs')
    if original.get('current_owner')is not None:
        from scripts import sw_cam_current_finish_configuration_owner as owner_adapter
        owner_adapter.verify_completed_transition(r,prep,original,v)
    marker_path=creation.marker_path(v);require(common.same_path(marker_path,r['dispatch_marker_path']),'Exact creation marker path required');marker,mp=read_pin(str(marker_path),_file_hash(marker_path))
    expected=dict(scope=creation.SCOPE,status='review_required',phase='finished',binding=r['binding'],authority_pin=r['authority_pin'],receipt_path=pin['path'],receipt_sha256=pin['sha256'],automatic_replay=False)
    require(common.same_path(marker['receipt_path'],pin['path']),'Marker receipt path differs');observed=deepcopy(marker);observed['receipt_path']=pin['path'];require(exact(observed,expected),'Exact consumed creation marker required')
    modules=[creation.__file__,creation.delta.__file__,prior.__file__,Path(creation.__file__).with_name('sw_cam_current_circular_finish_context.py')]
    for module in modules:require(any(common.same_path(p['path'],module)and p['sha256']==_file_hash(module)for p in r['evidence_pins']),'Exact completed creation module pin required')
    pins=list(original['pins'])+[pin,rp,pp,mp,dict(path=__file__,sha256=_file_hash(__file__))]
    for p in r['evidence_pins']:
        if common.same_path(p['path'],source_path):require(p['sha256']==r['source_before_sha256'],'Historical creation source pin differs');continue
        common.direct(p);pins.append(p)
    unique={}
    for p in pins:
        key=str(Path(p['path']).resolve()).casefold()
        if common.same_path(p['path'],source_path):require(p['sha256']==source_sha256,'Current physical source pin differs')
        require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting immutable configuration authority pins');unique[key]=_full_pin(p)
    pins=list(unique.values());require(_file_hash(source_path)==source_sha256 and read_pin(path,sha)[1]==pin,'Source or creation receipt changed while binding')
    original.update(pins=deepcopy(pins),spec=deepcopy(spec),recipe=deepcopy(recipe),recipe_pin=rp,prepared_receipt=prep)
    return dict(receipt=r,pin=pin,authority_pin=pin,state=deepcopy(r['saved']),original_data=original,spec=spec,operation_id=oid,feature_id=fid,new_observation=deepcopy(r['saved'][creation.delta.EXTRA]['operation_observation']),pins=pins,addin_clsid=original['addin_clsid'],definition_mode=original['definition_mode'],source_sha256=source_sha256,creation_recipe_pin=rp,creation_marker_pin=mp)
