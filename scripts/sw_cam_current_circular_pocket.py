"""当前保存配置上的单圆口袋与一项 Rough 定义；没有 GOP/GTP。"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_current_saved_generation import load_completed_configuration
from scripts.sw_cam_current_circular_context import NativeCircularContext,preflight
from scripts import sw_cam_current_circular_delta as delta
from scripts import sw_cam_current_saved_parameter_batch as batch
from scripts.sw_cam_profile_sketch import _select_plane
from scripts.sw_operation_guard import absolute_document_path

SCOPE='MILL_CURRENT_SAVED_CIRCULAR_POCKET_V1'
require=delta.require
IGNORED={'action','receipt_path','attempt_registry_path','prepare_receipt_path','prepare_receipt_sha256'}

def binding(v):
    from scripts.sw_cam_current_circular_resume_evidence import RESUME_KEYS
    excluded=IGNORED|(RESUME_KEYS if v.get('continuation_mode','none')=='none' else set())
    return {k:deepcopy(x) for k,x in v.items() if k not in excluded}

def load_inputs(v,clsid=None):
    loaded=load_completed_configuration(v['configuration_receipt_path'],v['configuration_receipt_sha256'],process_id=v['process_id'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'],selected_ids=[v['anchor_operation_native_id']])
    require(loaded['binding']['expected_process_create_time']==v['expected_process_create_time'],'Exact authority process lifetime required')
    if clsid is not None:require(loaded['addin_clsid'].casefold()==clsid.casefold(),'Pinned add-in differs')
    require(v['owner_setup_native_id']==loaded['binding']['expected_feature_setup_native_id'] and v['operation_setup_native_id']==loaded['binding']['expected_operation_setup_native_id'],'Explicit reference owner/setup required')
    state=loaded['state'];require(len(state['features'])<64 and len(state['operations'])<32,'One-feature/one-operation capacity exceeded')
    require(state['operations'][-1]['native_id']==v['insert_after_operation_native_id'] and state['operations'][-1]['setup_native_id']==v['operation_setup_native_id'],'Exact tail anchor in selected setup required')
    require(v['candidate_tool_native_id']==loaded['binding']['candidate_tool_native_id'] and v['expected_candidate_consumer_ids']==state['parameter_batch']['candidate_consumer_ids'],'Pinned existing candidate and all current consumers required')
    return loaded

def validate(v,clsid=None):
    require(v['mode']=='current_saved' and v['action'] in ('prepare','apply') and v['qualification_only'] is True and v['message_policy']=='vendor_default' and v['save_after_verified'] is True,'Explicit current-saved qualification workflow required')
    for key in ('process_id','anchor_operation_native_id','owner_setup_native_id','operation_setup_native_id','insert_after_operation_native_id','candidate_tool_native_id'):
        require(type(v[key]) is int and 0<v[key]<2**31,'Strict positive native identity required: '+key)
    require(type(v['expected_process_create_time']) in (int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Finite exact lifetime required')
    require(absolute_document_path(v['expected_document_path']) and Path(v['expected_document_path']).suffix.lower()=='.sldprt','Absolute saved part required')
    for key in ('expected_source_sha256','configuration_receipt_sha256'):require(type(v[key]) is str and re.fullmatch('[0-9a-f]{64}',v[key]),'Exact SHA required')
    delta.geometry_spec(v)
    ids=v['expected_candidate_consumer_ids'];require(type(ids) is list and len(ids)<=32 and all(type(x) is int and 0<x<2**31 for x in ids) and len(ids)==len(set(ids)),'Explicit ordered consumer IDs required')
    choice=v['rough_definition'];require(type(choice) is dict and set(choice)=={'default_operation_name','default_operation_id'} and type(choice['default_operation_name']) is str and 0<len(choice['default_operation_name'])<=1000 and '\x00' not in choice['default_operation_name'] and type(choice['default_operation_id']) is int and 0<choice['default_operation_id']<2**31,'One explicit rough catalogue choice required')
    tool=v['expected_default_tool'];require(type(tool) is dict and set(tool)=={'tool_type_raw','cut_diameter_native','protrusion_native'} and type(tool['tool_type_raw']) is int and tool['tool_type_raw']>=0,'Explicit default tool type/dimensions required')
    for key in ('cut_diameter_native','protrusion_native'):require(type(tool[key]) is float and math.isfinite(tool[key]) and 0<tool[key]<=1000,'Finite positive tool dimensions required')
    loaded=load_inputs(v,clsid)
    from scripts.sw_cam_current_circular_resume_evidence import load_history,RESUME_KEYS
    continuation=v.get('continuation_mode','none');require(continuation in ('none','after_feature'),'Explicit supported continuation mode required')
    if continuation=='after_feature':loaded['_feature_resume']=load_history(v,loaded)
    else:require(all(v.get(k) is None for k in RESUME_KEYS-{'continuation_mode'}),'Ordinary creation rejects continuation history')
    out=Path(v['receipt_path']);registry=Path(v['attempt_registry_path'])
    require(out.is_absolute() and out.suffix.lower()=='.json' and out.parent.is_dir() and not out.exists() and not out.is_symlink(),'New immutable output required')
    require(registry.is_absolute() and registry.is_dir() and not registry.is_symlink(),'Existing attempt registry directory required')
    marker=registry/('current_circle_'+_digest(binding(v))+'.json')
    require(not marker.exists() and not marker.is_symlink(),'Prior attempt exists; no replay')
    protected={Path(v['expected_document_path']).resolve(),*(Path(p['path']).resolve() for p in [loaded['pin'],*loaded['pins'].values(),*loaded.get('recovery_pins',{}).values()])}
    if '_feature_resume' in loaded:protected.update(Path(p['path']).resolve() for p in loaded['_feature_resume']['pins'].values())
    require(out.resolve() not in protected and marker.resolve() not in protected and out.resolve()!=marker.resolve(),'Output/marker aliases source or evidence')
    prep=None
    if v['action']=='apply':
        prep,ppin=read_pin(v['prepare_receipt_path'],v['prepare_receipt_sha256'])
        if '_feature_resume' in loaded:
            require(ppin==loaded['_feature_resume']['pins']['original_prepare'],'Feature continuation consumes only the immutable original prepare')
        else:
            require(prep.get('scope')==SCOPE and prep.get('action')=='prepare' and prep.get('status')=='review_required' and prep.get('phase')=='finished' and prep.get('may_apply') is True and prep.get('readback_verified') is True and prep.get('runtime_unchanged') is True and prep.get('mutation_attempted') is False and prep.get('binding')==binding(v),'Exact completed reviewed prepare required')
            require(delta.circular_state_equal(prep['before'],prep['confirm_before']) and out.resolve()!=Path(ppin['path']).resolve(),'Stable prepare and distinct output required')
    else:require(v.get('prepare_receipt_path') is None and v.get('prepare_receipt_sha256') is None,'Prepare rejects prior prepare inputs')
    return loaded,marker,prep

def reference_baseline(state):
    value=deepcopy(state);value['reference_header']=value.pop('target_header');value['reference_profile']=value.pop('profile');value['reference_number_of_steps_raw']=value.pop('number_of_steps_raw')
    value['reference_parameter_observation']={k:value.pop(k) for k in ('operation_parameters','parameter_capture_complete','parameter_batch','retained_operation_nc') if k in value}
    value['extended_capture_complete']=True
    return value

def verify_rough_choice(state,v):
    choice=v['rough_definition'];catalogues=[x for x in state['target_catalogues'] if x['operation_type']==0]
    require(len(catalogues)==1 and sum(x['name']==choice['default_operation_name'] and x['default_operation_id']==choice['default_operation_id'] for x in catalogues[0]['entries'])==1,'Explicit rough choice absent from actual new pocket catalogue')


def run_current_circular_pocket(sw,clsid,typelib_path,*,runtime_check,context_factory=NativeCircularContext,**v):
    """一个独占、不可重放的多阶段动作；失败保留部分结果而不回滚。"""
    resuming=v.get('continuation_mode','none')=='after_feature'
    report=dict(scope=SCOPE,status='running',phase='validation',action='resume_after_feature' if resuming and v['action']=='apply' else v['action'],binding=binding(v),request_pin=dict(kind='canonical_binding',sha256=_digest(binding(v))),addin_clsid=clsid,
        mutation_attempted=False,native_dispatch_pending=False,readback_verified=False,geometry_delta_verified=False,operation_delta_verified=False,save_readback_verified=False,source_update_verified=False,model_saved=False,
        GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,automatic_rollback=False,automatic_replay=False,runtime_unchanged=False,may_apply=False,production_qualified=False,full_hidden_geometry_preservation_verified=False,physical_depth_verified=False,
        source_before_sha256=v['expected_source_sha256'],actions=[],captures=[],native_read_count=0,receipt_created=False,marker_created=False,new_operations=[],created_names=[])
    ctx=None;marker=None
    def persist():
        if report['receipt_created']:_write_receipt(Path(v['receipt_path']),report)
    try:
        loaded,marker,prep=validate(v,clsid);data=batch.load_inputs(loaded['binding'],clsid);report['ABI']=preflight(typelib_path,data['authority']['definition_mode']);runtime_check()
        report.update(authority_pin=deepcopy(loaded['pin']),dispatch_marker_path=str(marker));_write_receipt(Path(v['receipt_path']),report,create=True);report['receipt_created']=True;persist()
        history=loaded.get('_feature_resume');context_options={}
        if history is not None:
            context_options=dict(restore=history['restore'],continuation_pins=list(history['pins'].values()))
            report.update(continuation_stage='after_feature',continuation_verified=False,creation_replayed=False,continuation_pins=deepcopy(history['pins']),historical_before=deepcopy(history['historical_before']),historical_after_sketch=deepcopy(history['historical_after_sketch']),historical_after_feature=deepcopy(history['expected_state']),historical_capture_keys=deepcopy(history['historical_capture_keys']),new_feature_native_id=history['new_feature_native_id'],created_names=deepcopy(history['created_names']))
            persist()
        ctx=context_factory(sw,clsid,typelib_path,v,loaded,report,persist,runtime_check,**context_options)
        with ctx:
            before=ctx.capture('before');confirm=ctx.capture('confirm_before');require(delta.circular_state_equal(before,confirm),'Two current prepare captures differ')
            if history is not None:
                require(delta.circular_state_equal(before,history['expected_state']),'Fresh created-feature state differs from immutable partial')
                for state in (before,confirm):
                    require(state.get('capture_complete') is True and state.get('extended_capture_complete') is True,'Complete fresh feature-stage capture required')
                    delta.verify_feature(history['historical_after_sketch'],state,history['original_binding'],history['new_feature_native_id'])
                verify_rough_choice(confirm,v);report.update(geometry_proof=delta.verify_geometry(confirm,v,history['new_feature_native_id']),geometry_delta_verified=True,continuation_verified=True)
            else:
                require(delta.cam_view(before)==reference_baseline(loaded['state']),'Current protected route/parameters differ from saved authority')
                names={v['sketch_spec']['sketch_name'],v['sketch_spec']['plane_name']};require(not any(x['name'] in names for x in before['sketch_state']['features']),'Requested sketch/plane already exists; no duplicate')
                plane,newplane=_select_plane(before['sketch_state']);report['planned_reference_plane']=deepcopy(plane);report['new_reference_plane_required']=newplane
            owner=next(x for x in before['feature_setups'] if x['native_id']==v['owner_setup_native_id']);require(delta.vector(owner['axis_native'],v['expected_setup_axis']),'Actual setup direction differs')
            report['rough_definition']=deepcopy(v['rough_definition']);report['default_tool_expectation']=deepcopy(v['expected_default_tool']);persist()
            if v['action']=='prepare':report['may_apply']=True
            else:
                if history is None:require(delta.circular_state_equal(prep['before'],before),'Fresh state differs from reviewed prepare')
                ctx.boundary();runtime_check()
                _write_receipt(marker,dict(scope=SCOPE,status='claimed_no_replay',binding=binding(v),receipt_path=v['receipt_path']),create=True);report['marker_created']=True;persist();ctx.boundary()
                def start(kind):
                    entry=dict(kind=kind,attempted=False,returned=False,readback_verified=False,native_dispatch_pending=False);report['actions'].append(entry);persist()
                    def pending():entry.update(attempted=True,native_dispatch_pending=True);report.update(mutation_attempted=True,native_dispatch_pending=True,phase=kind);persist()
                    def returned(value):
                        entry.update(returned=True,native_dispatch_pending=False,native_result=deepcopy(value));report['native_dispatch_pending']=False;persist()
                    return entry,pending,returned
                def observe(label,verify,entry):
                    first=ctx.capture(label);second=ctx.capture('confirm_'+label);require(delta.circular_state_equal(first,second),'Two complete stage captures differ');require(first.get('extended_capture_complete') is True and first.get('capture_complete') is True,'Complete extended capture required');verify(first);entry['readback_verified']=True;persist();return second
                if history is None:
                    entry,pending,returned=start('CreateSketch');ctx.create_sketch(before,pending,returned);report['created_names']=list(ctx.created_names);persist()
                    sketch=observe('after_sketch',lambda x:delta.verify_sketch(before,x,report['created_names']),entry)
                    entry,pending,returned=start('CreateMillFeature2');fid=ctx.create_feature(pending,returned);require(type(fid) is int and fid>0 and fid not in {x['geometry']['native_id'] for x in before['features']},'Actual new pocket ID required');report['new_feature_native_id']=fid;persist()
                    feature=observe('after_feature',lambda x:delta.verify_feature(sketch,x,v,fid),entry);report['geometry_proof']=delta.verify_geometry(feature,v,fid);report['geometry_delta_verified']=True;persist()
                else:feature=confirm;fid=history['new_feature_native_id']
                verify_rough_choice(feature,v)
                entry,pending,returned=start('InsertOperation');oid=ctx.insert_rough(feature,pending,returned);require(type(oid) is int and oid>0 and oid not in {x['native_id'] for x in before['operations']},'Actual new rough ID required');report['new_operation_native_id']=oid;persist()
                after=observe('after_insert',lambda x:delta.verify_insert(feature,x,v,oid,fid),entry);report['new_operations']=[deepcopy(after['operations'][-1])];report['operation_delta_verified']=True;persist()
                entry,pending,returned=start('SaveActiveDocument')
                def saved_return(value):
                    returned(dict(return_type=type(value).__name__,hresult=value if type(value) is int else None))
                ctx.save(pending,saved_return)
                saved=observe('saved',lambda x:delta.verify_saved(after,x,ctx.source),entry)
                report.update(save_hresult=entry['native_result']['hresult'],save_readback_verified=True,source_update_verified=True,model_saved=True,saved_file_sha256=ctx.source,source_after_sha256=ctx.source);persist()
            ctx.boundary()
        clean_events(dict(messages=ctx.session.summary()));ctx.identity();runtime_check()
        report.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,reason='CURRENT_CIRCULAR_DEFINITION_ONLY_NO_GOP_GTP')
    except Exception as exc:
        if isinstance(exc,delta.CircularGuardError):report['guard_failure']=dict(code=exc.code,reason=exc.guard_reason)
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,geometry_delta_verified=False,operation_delta_verified=False,save_readback_verified=False,source_update_verified=False,model_saved=False,may_apply=False,runtime_unchanged=False)
    finally:
        if ctx is not None and ctx.session is not None:report['messages']=ctx.session.summary()
        try:
            persist()
            if report['marker_created']:_write_receipt(marker,dict(scope=SCOPE,status=report['status'],receipt_path=v['receipt_path'],receipt_sha256=_file_hash(v['receipt_path']),automatic_replay=False))
        except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',receipt_write_error=_error(exc),readback_verified=False,may_apply=False,save_readback_verified=False,model_saved=False,runtime_unchanged=False)
    return report
