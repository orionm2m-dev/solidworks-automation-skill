"""从明确已返回的首个插入继续；先独立只读核验，不重放旧变更。"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_mill_selected_insert as selected
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_append_evidence import attempt_marker
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_thread import _object_id

KEYS=('partial_receipt_path','partial_receipt_sha256','partial_attempt_marker_path','partial_attempt_marker_sha256','retained_operation_native_id')
PAIRS=(('partial_receipt_path','partial_receipt_sha256'),('partial_attempt_marker_path','partial_attempt_marker_sha256'))


def require(value,message):
    if not value:raise ValueError(message)


def enabled(v):return v.get('definition_mode')=='selected_continue'


def validate_fields(v):
    if not enabled(v):
        require(all(v.get(k) is None for k in KEYS),'Continuation fields forbidden outside explicit continuation mode')
        return
    require(type(v.get('retained_operation_native_id')) is int and 0<v['retained_operation_native_id']<2**31,'Explicit returned rough-operation identity required')


def load(v,original_binding,saved_state):
    """只承认两次已验证抑制和一次已返回插入，且本地 NC 类型门禁终止。"""
    partial,pin=read_pin(v['partial_receipt_path'],v['partial_receipt_sha256'])
    require(partial.get('scope')=='MILL_CURRENT_SAVED_APPEND_V1' and partial.get('status')=='uncertain' and partial.get('phase')=='finished' and partial.get('action')=='apply','Exact stopped selected-apply receipt required')
    require(partial.get('binding')==original_binding and original_binding.get('definition_mode')=='selected_insert','Immutable original selected binding required')
    for key in ('mutation_attempted','native_call_attempted','native_call_returned','receipt_created','marker_created','runtime_unchanged'):require(partial.get(key) is True,'Required partial boundary flag: '+key)
    for key in ('native_dispatch_pending','GOP_attempted','GTP_attempted','AFR_attempted','model_saved','save_attempted','save_call_returned','save_readback_verified','source_update_verified','readback_verified','operation_delta_verified'):require(partial.get(key) is False,'Unknown or later partial boundary rejected: '+key)
    require(not any(k in partial for k in ('runtime_error','receipt_write_error','after_insert_0','confirm_after_insert_0','after','saved','confirm_saved')),'No ambiguous later capture or persistence error allowed')
    issue=partial.get('issue',{});locations=issue.get('locations',[])
    require(partial.get('failed_phase')=='IGetNCParam' and issue.get('type')=='ValueError' and issue.get('hresult') is None and locations and locations[-1].get('file')=='sw_cam_comtypes.py' and locations[-1].get('function')=='_interface_class','Only the documented local NC interface admission failure may continue')
    clean_events(partial)
    before=partial.get('before');require(before==partial.get('confirm_before')==saved_state and partial.get('state_sha256')==_digest(before),'Original saved baseline and both fresh pre-mutation captures required')
    chosen=selected.plan(before,v);require(partial.get('selected_definition_plan')==chosen,'Original reviewed instructions changed')
    actions=partial.get('definition_actions');require(type(actions) is list and len(actions)==3 and partial.get('new_operations')==[],'Exactly two suppressions and one returned rough insertion required')
    state=before;labels=['before','confirm_before']
    for oid,action in zip(chosen['suppress_operation_native_ids'],actions[:2]):
        require(action.get('kind')=='suppress' and action.get('operation_native_id')==oid and action.get('requested_value') is True and action.get('attempted') is True and action.get('returned') is True and action.get('readback_verified') is True and action.get('native_dispatch_pending') is False,'Both exact suppression actions must have verified returned outcomes')
        label='after_suppress_'+str(oid);after=partial.get(label);require(type(after) is dict and after==partial.get('confirm_'+label),'Two complete prior suppression captures required')
        selected.verify_suppression(state,after,oid);state=after;labels.extend((label,'confirm_'+label))
    action=actions[-1]
    require(action.get('kind')=='insert' and action.get('choice')==chosen['insert_operations'][0] and action.get('anchor_native_id')==chosen['anchor_operation_native_id'] and action.get('attempted') is True and action.get('returned') is True and action.get('native_dispatch_pending') is False and action.get('readback_verified') is False and action.get('actual_native_id')==v['retained_operation_native_id'] and type(action.get('actual_native_id')) is int and 'own_nc' not in action,'One known returned rough ID without completed readback required')
    require(partial.get('captures')==labels and type(state['document']['needs_save']) is bool,'Exact stopped phase and observed host save flag required')
    marker,mpin=read_pin(v['partial_attempt_marker_path'],v['partial_attempt_marker_sha256'])
    require(Path(partial['receipt_path']).resolve()==Path(v['partial_receipt_path']).resolve() and Path(partial['dispatch_marker_path']).resolve()==Path(v['partial_attempt_marker_path']).resolve(),'Original receipt and marker paths must bind each other')
    require(marker.get('scope')==partial['scope'] and marker.get('status')=='uncertain' and marker.get('automatic_replay') is False and marker.get('receipt_sha256')==v['partial_receipt_sha256'] and Path(marker['receipt_path']).resolve()==Path(v['partial_receipt_path']).resolve(),'Original consumed marker must pin this exact immutable partial receipt')
    return dict(partial=partial,last_verified=deepcopy(state),chosen=chosen,pins=dict(partial=pin,old_marker=mpin))


def marker_path(v):
    base=attempt_marker(v['attempt_registry_path'],v['expected_document_path'],v['expected_source_sha256'],v['expected_feature_native_id'])
    key=_digest(dict(original_attempt=base.name,partial_sha256=v['partial_receipt_sha256'],old_marker_sha256=v['partial_attempt_marker_sha256']))
    return base.with_name('mill_continue_'+key+'.json')


def capture_nc(state,native,v,read,typed,persist):
    """实际 own NC 必须重新可读；未完成部分也保留在当前 capture 中。"""
    oid=v['retained_operation_native_id'];value=dict(operation_native_id=oid,read_complete=False);state['retained_operation_nc']=value;persist()
    found=read(native['doc'],'GetCWObjectFromID',3,oid)
    require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Retained operation lookup required')
    raw=typed(found[0],'ICWMillOperation');require(_object_id(native['doc'],raw,read)==oid,'Retained operation ID differs')
    value['nc']=selected.definitions.read_own_nc(raw,read=read,typed=typed);value['read_complete']=True;persist()


def verify_current(info,state,v):
    require(type(state['document']['needs_save']) is bool,'Actual host save flag must remain explicit; CAM delta proves unsaved definitions')
    nc=state.get('retained_operation_nc',{})
    require(nc.get('operation_native_id')==v['retained_operation_native_id'] and nc.get('read_complete') is True and nc.get('nc',{}).get('read_complete') is True,'Retained rough own NC must be readable before continuation')
    raw=deepcopy(state);raw.pop('retained_operation_nc')
    return selected.verify_insert(info['last_verified'],raw,info['chosen']['insert_operations'][0],v['retained_operation_native_id'],info['chosen']['anchor_operation_native_id'])
