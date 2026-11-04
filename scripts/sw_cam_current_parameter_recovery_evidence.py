"""验证已完成参数写入、尚未保存且仅有已观察到底部余量别名的纯证据。

调用方负责读取并固定四份不可变文件。本模块不访问文件系统，不调用 CAD，
不检查当前源文件、不创建标记或执行修改，也不授予任何原生访问权限。
"""
from copy import deepcopy
import ntpath
import re
from scripts import sw_cam_current_saved_parameter_fields as fields
from scripts.sw_cam_mill_selected_plan_evidence import clean_events
from scripts.sw_cam_turn_tool import _digest

SCOPE='MILL_CURRENT_SAVED_PARAMETER_BATCH_V1'
PIN_KEYS={'partial','old_marker','original_request','original_prepare'}
require=fields.require

def path_key(value):
    require(type(value) is str and value and ntpath.isabs(value),'Explicit absolute evidence path required')
    return ntpath.normcase(ntpath.normpath(value))

def complete_state(state):
    require(type(state) is dict and all(state.get(k) is True for k in ('capture_complete','parameter_capture_complete')) and state.get('parameter_batch',{}).get('read_complete') is True,'Complete captured parameter state required')
    require(type(state.get('document',{}).get('needs_save')) is bool,'Actual host Boolean flag required')

def no_save(data):
    for key in ('GOP_attempted','GTP_attempted','AFR_attempted','save_attempted','save_call_returned','save_readback_verified','model_saved','source_update_verified','automatic_replay','automatic_rollback'):
        require(data.get(key) is False,'Historical action outside exact no-Save parameter case: '+key)
    require(data.get('save_hresult') is None and not any(k in data for k in ('saved','confirm_saved','source_after_sha256','saved_file_sha256')),'No historical Save outcome may be admitted')

def validate_history(partial,original_prepare,original_request,old_marker,*,base_binding,plan,baseline,pins):
    require(all(type(x) is dict for x in (partial,original_prepare,original_request,old_marker,base_binding,baseline)),'Decoded history objects required')
    require(type(pins) is dict and set(pins)==PIN_KEYS,'Exactly four immutable recovery pins required')
    paths=[]
    for pin in pins.values():
        require(type(pin) is dict and type(pin.get('sha256')) is str and re.fullmatch('[0-9a-f]{64}',pin['sha256']) is not None,'Exact SHA256 recovery pin required')
        paths.append(path_key(pin.get('path')))
    require(len(set(paths))==4,'Recovery evidence paths must be distinct')
    fields.validate_recipe(plan)
    require(len(plan['rows'])==1,'Observed recovery supports one rough operation only')
    row=plan['rows'][0];oid=row['operation_native_id'];changes=[c for c in row['fields'] if not fields.equal(c['expected'],c['new'])]
    require(row['existing_tool_native_id'] is not None and len(changes)==7,'Exact tool plus seven completed field changes required')
    require([c['field'] for c in changes]==['entry_type','spiral_radius','first_depth','subsequent_depth','side_allowance','floor_allowance','side_step'],'Observed field sequence required')
    floor=next(c for c in changes if c['field']=='floor_allowance')
    require(type(floor['expected']) is float and floor['expected']==1.0 and type(floor['new']) is float and floor['new']==0.2,'Observed floor1.0 to0.2 case only')
    require(type(base_binding.get('parameter_operation_native_ids')) is list and len(base_binding['parameter_operation_native_ids'])==2 and base_binding['parameter_operation_native_ids'][0]==oid,'Exact historical target binding required')
    request_pin=dict(kind='canonical_binding',sha256=_digest(base_binding))
    for data,action,status in ((partial,'apply','uncertain'),(original_prepare,'prepare','review_required')):
        require(data.get('scope')==SCOPE and data.get('action')==action and data.get('status')==status and data.get('phase')=='finished','Exact completed historical phase required')
        require(fields.equal(data.get('binding'),base_binding) and fields.equal(data.get('recipe'),plan) and fields.equal(data.get('request_pin'),request_pin),'Exact historical binding/recipe required')
        require(data.get('runtime_unchanged') is True and data.get('native_dispatch_pending') is False and data.get('source_before_sha256')==base_binding['expected_source_sha256'],'Historical runtime/source/dispatch differs')
        require(not any(k in data for k in ('runtime_error','receipt_write_error')),'Runtime or durable receipt failure rejected')
        clean_events(data);no_save(data)
    require(original_prepare.get('mutation_attempted') is False and original_prepare.get('readback_verified') is True and original_prepare.get('may_apply') is True and original_prepare.get('actions')==[] and original_prepare.get('marker_created') is False,'Unmutated successful prepare required')
    require(not any(k in original_prepare for k in ('issue','failed_phase')),'Failed prepare rejected')
    require(partial.get('mutation_attempted') is True and partial.get('readback_verified') is False and partial.get('parameter_delta_verified') is False and partial.get('receipt_created') is True and partial.get('marker_created') is True,'Exact stopped-after-setters partial required')
    issue=partial.get('issue',{})
    require(issue.get('type')=='ValueError' and issue.get('hresult') is None and issue.get('actual_return_type') is None,'Only observed local final-verification failure required')
    locations=issue.get('locations',[])
    require([(r.get('file'),r.get('function')) for r in locations]==[('sw_cam_current_saved_parameter_batch.py','run_current_saved_configuration'),('sw_cam_current_saved_parameter_fields.py','verify_final'),('sw_cam_current_saved_parameter_fields.py','require')],'Failure must be exact final delta verification, not a native call')
    before=partial.get('before');after=partial.get('after');complete_state(before);complete_state(after)
    require(fields.equal(before,partial.get('confirm_before')) and fields.equal(before,original_prepare.get('before')) and fields.equal(before,original_prepare.get('confirm_before')),'Historical prepare and initial captures differ')
    require(partial.get('state_sha256')==original_prepare.get('state_sha256')==_digest(before),'Historical initial state digest differs')
    projected=deepcopy(before);projected.pop('parameter_batch')
    require(fields.equal(projected,baseline),'Historical full parameter baseline differs')
    fields.compile_plan(before,plan)
    before_tool='after_tool_'+str(oid);confirm_tool='confirm_tool_'+str(oid)
    require(partial.get('captures')==['before','confirm_before',before_tool,confirm_tool,'after'] and 'confirm_after' not in partial,'Exact interrupted final-capture position required')
    complete_state(partial.get(before_tool));require(fields.equal(partial[before_tool],partial.get(confirm_tool)),'Two equal historical SetTool barrier captures required')
    candidate=before['parameter_batch']['candidate_tool'];fields.verify_assignment_delta(before,partial[before_tool],row,candidate)
    actions=partial.get('actions');require(type(actions) is list and len(actions)==8,'Exactly eight completed native actions required')
    for index,action in enumerate(actions):
        require(type(action.get('operation_native_id')) is int and action['operation_native_id']==oid and all(action.get(k) is True for k in ('attempted','returned','readback_verified')) and action.get('native_dispatch_pending') is False and action.get('return_type')=='int' and type(action.get('return_value')) is int and action['return_value']==0,'Every original native action must be completed and read back')
        if index==0:require(action.get('kind')=='SetTool' and action.get('change') is None and action.get('capture')==before_tool,'Exact original SetTool action required')
        else:
            change=changes[index-1];observed=action.get('observed',{})
            require(action.get('kind')=='field' and fields.equal(action.get('change'),change) and observed.get('returned') is True and observed.get('raw',{}).get('recorded') is True and fields.equal(observed['raw'].get('raw'),change['new']),'Original own-field readback/order differs')
    requests=original_request.get('requests',[])
    require(type(requests) is list and all(type(r) is dict for r in requests),'Exact original request batch required')
    matches=[r for r in requests if r.get('name')=='solidworks_cam_configure_guide_definitions']
    require(len(matches)==1,'One exact original configuration request required')
    args=matches[0]['arguments']['params']
    require(all(fields.equal(args.get(k),v) for k,v in base_binding.items()) and args.get('configuration_mode')=='current_saved' and args.get('action')=='apply' and args.get('save_after_verified') is True and args.get('acknowledge_qualification_only') is True,'Original applied request binding differs')
    require(path_key(args.get('prepare_receipt_path'))==path_key(pins['original_prepare']['path']) and args.get('prepare_receipt_sha256')==pins['original_prepare']['sha256'],'Original reviewed prepare pin differs')
    require(path_key(args.get('receipt_path'))==path_key(partial.get('receipt_path'))==path_key(pins['partial']['path']),'Original partial receipt path differs')
    require(path_key(partial.get('dispatch_marker_path'))==path_key(pins['old_marker']['path']) and path_key(ntpath.dirname(pins['old_marker']['path']))==path_key(args.get('attempt_registry_path')),'Original marker ownership/path differs')
    require(old_marker.get('scope')==SCOPE and old_marker.get('status')=='uncertain' and old_marker.get('automatic_replay') is False and path_key(old_marker.get('receipt_path'))==path_key(pins['partial']['path']) and old_marker.get('receipt_sha256')==pins['partial']['sha256'],'Immutable original marker does not identify this exact partial')
    # 只有完整证明已完成的调用链后，才允许已观察到的底部余量别名。
    # 其余所有已采集值仍必须精确匹配。
    fields.verify_final(before,after,plan,{candidate['generic']['native_id']:candidate},observed_floor_alias=True)
    return dict(expected_state=deepcopy(after),historical_before=deepcopy(before),consumer_ids=deepcopy(after['parameter_batch']['candidate_consumer_ids']),original_action_receipt_pin=deepcopy(pins['partial']),recovery_pins=deepcopy(pins))
