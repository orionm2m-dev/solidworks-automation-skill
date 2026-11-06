"""已创建口袋阶段的不可变证据；只验证文件记录，不连接 CAM。"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_current_circular_delta as delta
from scripts.sw_cam_current_saved_parameter_fields import equal
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_turn_tool import _digest

SCOPE='MILL_CURRENT_SAVED_CIRCULAR_POCKET_V1'
PIN_FIELDS={'partial':'partial_receipt','old_marker':'old_marker','original_request':'original_apply_request','original_prepare':'original_prepare_receipt'}
RESUME_KEYS={'continuation_mode',*(prefix+suffix for prefix in PIN_FIELDS.values() for suffix in ('_path','_sha256'))}
HISTORICAL_KEYS={'before':'before','after_sketch':'confirm_after_sketch','after_feature':'confirm_after_feature'}
require=delta.require


def original_values(v):return {k:deepcopy(x) for k,x in v.items() if k not in RESUME_KEYS}


def _pair(report,name):
    value=report.get(name);other=report.get('confirm_'+name)
    require(type(value) is dict and type(other) is dict and delta.circular_state_equal(value,other),'Two complete historical circular captures required: '+name)
    for state in (value,other):require(state.get('capture_complete') is True and state.get('extended_capture_complete') is True,'Historical capture incomplete')
    return value,other


def validate_history(partial,prepare,request,old_marker,*,pins,loaded):
    """只承认返回了一个新特征、尚未插入任何操作的已知停止边界。"""
    from scripts.sw_cam_current_circular_pocket import binding,reference_baseline
    require(set(pins)==set(PIN_FIELDS),'Four exact historical pins required')
    require(partial.get('scope')==SCOPE and partial.get('action')=='apply' and partial.get('status')=='uncertain' and partial.get('phase')=='finished','Exact partial circular apply required')
    require(partial.get('guard_failure')=={'code':'CURRENT_CIRCULAR_GUARD_REJECTED','reason':'Pocket axis/start/radius/depth readback differs'},'Only the observed historical bounds guard boundary is supported')
    require(partial.get('mutation_attempted') is True and partial.get('marker_created') is True and partial.get('native_dispatch_pending') is False,'Historical attempt outcome must be returned and consumed')
    for key in ('readback_verified','model_saved','save_readback_verified','source_update_verified','GOP_attempted','GTP_attempted','AFR_attempted','automatic_rollback','automatic_replay'):require(partial.get(key) is False,'Unexpected historical side effect or completion: '+key)
    require(partial.get('source_after_sha256') is None and partial.get('new_operations')==[],'Historical feature stage must contain no new operation or Save')
    require(not any(k in partial for k in ('runtime_error','receipt_write_error','cleanup_error')),'Unsafe historical runtime/receipt/cleanup failure')
    clean_events(partial);clean_events(prepare)
    old=partial.get('binding');require(type(old) is dict and not any(k in old for k in RESUME_KEYS),'Original creation binding required')
    require(partial.get('request_pin')==dict(kind='canonical_binding',sha256=_digest(old)) and partial.get('source_before_sha256')==old['expected_source_sha256'],'Original canonical binding/source differs')
    require(equal(partial.get('authority_pin'),loaded['pin']) and old['configuration_receipt_sha256']==loaded['pin']['sha256'],'Original completed configuration differs')
    require(Path(old['configuration_receipt_path']).resolve()==Path(loaded['pin']['path']).resolve(),'Original configuration path differs')
    require(partial.get('addin_clsid')==loaded['addin_clsid'] and old['expected_process_create_time']==loaded['binding']['expected_process_create_time'],'Historical owned add-in/lifetime differs')
    rows=request.get('requests');require(type(rows) is list,'Actual original request batch required')
    calls=[r for r in rows if type(r) is dict and r.get('name')=='solidworks_cam_add_circular_pocket_plan'];require(len(calls)==1,'One actual original pocket apply invocation required')
    values=calls[0].get('arguments',{}).get('params');require(type(values) is dict and values.get('action')=='apply' and values.get('addin_clsid')==partial['addin_clsid'],'Actual original apply/add-in required')
    stripped={k:deepcopy(v) for k,v in values.items() if k not in ('addin_clsid','expected_document_title','response_format')};require(equal(binding(stripped),old),'Actual original request does not match immutable binding')
    require(Path(values['receipt_path']).resolve()==Path(pins['partial']['path']).resolve() and Path(values['prepare_receipt_path']).resolve()==Path(pins['original_prepare']['path']).resolve() and values['prepare_receipt_sha256']==pins['original_prepare']['sha256'],'Actual request receipt/prepare pins differ')
    require(old_marker.get('scope')==SCOPE and old_marker.get('status')=='uncertain' and old_marker.get('automatic_replay') is False and old_marker.get('receipt_sha256')==pins['partial']['sha256'] and Path(old_marker.get('receipt_path','')).resolve()==Path(pins['partial']['path']).resolve(),'Consumed original marker differs')
    expected_marker=Path(values['attempt_registry_path'])/('current_circle_'+_digest(old)+'.json')
    require(expected_marker.resolve()==Path(pins['old_marker']['path']).resolve()==Path(partial['dispatch_marker_path']).resolve(),'Original exclusive marker path differs')
    require(prepare.get('scope')==SCOPE and prepare.get('action')=='prepare' and prepare.get('status')=='review_required' and prepare.get('phase')=='finished' and all(prepare.get(k) is True for k in ('may_apply','readback_verified','runtime_unchanged')) and prepare.get('mutation_attempted') is False and equal(prepare.get('binding'),old),'Original verified prepare required')
    actions=partial.get('actions');require(type(actions) is list and len(actions)==2 and [a.get('kind') for a in actions]==['CreateSketch','CreateMillFeature2'],'Exactly two historical creation actions required')
    for a in actions:require(a.get('attempted') is True and a.get('returned') is True and a.get('native_dispatch_pending') is False,'Historical native action outcome incomplete')
    require(actions[0].get('readback_verified') is True and actions[1].get('readback_verified') is False and actions[1].get('native_result',{}).get('nonnull') is True,'Exact original verified sketch and returned feature boundary required')
    names=partial.get('created_names');fid=partial.get('new_feature_native_id')
    require(type(fid) is int and fid>0 and type(names) is list and 1<=len(names)<=2 and len(set(names))==len(names) and actions[0].get('native_result',{}).get('created_names')==names,'Actual original created feature/sketch identities required')
    initial,_=_pair(partial,'before');prepared,_=_pair(prepare,'before');sketch,sketch_confirm=_pair(partial,'after_sketch');feature,feature_confirm=_pair(partial,'after_feature')
    require(delta.circular_state_equal(initial,prepared) and equal(delta.cam_view(initial),reference_baseline(loaded['state'])),'Historical original state differs from prepared/completed authority')
    delta.verify_sketch(initial,sketch,names);delta.verify_feature(sketch_confirm,feature,old,fid);delta.verify_feature(sketch_confirm,feature_confirm,old,fid)
    require(feature['operations']==initial['operations'],'Any operation creation or change forbids this continuation')
    return dict(pins=deepcopy(pins),original_binding=deepcopy(old),historical_before=deepcopy(initial),historical_after_sketch=deepcopy(sketch_confirm),expected_state=deepcopy(feature_confirm),historical_capture_keys=deepcopy(HISTORICAL_KEYS),new_feature_native_id=fid,created_names=deepcopy(names),restore=dict(new_feature_native_id=fid,new_operations=[],created_names=deepcopy(names)))


def load_history(v,loaded):
    """文件固定历史；当前内存及源文件由外层 fresh captures/guard 另行确认。"""
    records={};pins={}
    for key,prefix in PIN_FIELDS.items():records[key],pins[key]=read_pin(v[prefix+'_path'],v[prefix+'_sha256'])
    history=validate_history(records['partial'],records['original_prepare'],records['original_request'],records['old_marker'],pins=pins,loaded=loaded)
    from scripts.sw_cam_current_circular_pocket import binding
    require(equal(binding(original_values(v)),history['original_binding']),'Continuation request changes the original creation recipe')
    return history
