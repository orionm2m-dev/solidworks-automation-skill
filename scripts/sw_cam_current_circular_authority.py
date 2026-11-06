"""真实已保存圆形口袋及后续配置的纯证据加载；不连接 CAM。"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_current_saved_parameter_fields as fields
from scripts import sw_cam_current_circular_delta as pocket
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_current_append import attempt_marker

MODE='current_saved_circular'
POCKET_SCOPE='MILL_CURRENT_SAVED_CIRCULAR_POCKET_V1'
KEYS=('configuration_mode','process_id','expected_process_create_time','expected_document_path','expected_source_sha256','pocket_receipt_path','pocket_receipt_sha256','expected_feature_native_id','parameter_operation_native_ids','candidate_tool_native_id','expected_candidate_consumer_ids','recipe_path','recipe_sha256','dependent_readbacks')
FLAGS=('readback_verified','geometry_delta_verified','operation_delta_verified','save_readback_verified','model_saved','source_update_verified','runtime_unchanged')
require=pocket.require
circular_state_equal=pocket.circular_state_equal
align_circular_mass=pocket.align_circular_mass


def binding(v):return {k:deepcopy(v[k]) for k in KEYS}


def normalized(state):
    """仅将两个严格布尔 dirty 观察归一化；其他几何及文件身份保持不变。"""
    out=deepcopy(state)
    require(type(out['document']['needs_save']) is bool and type(out['sketch_state']['needs_save']) is bool,'Strict circular document/sketch dirty flags required')
    out['sketch_state']['needs_save']=False
    return out


def verify_assignment_delta(before,after,row,candidate):
    fields.verify_assignment_delta(normalized(before),normalized(align_circular_mass(before,after)),row,candidate)


def dependencies(before,plan,declared):
    """只接受调用者显式声明的单个实际 DepthAllow 预期；不是通用 API 别名。"""
    require(type(declared) is list and len(declared)<=1,'At most one explicit dependent observation required')
    if not declared:return False
    item=declared[0]
    require(type(item) is dict and set(item)=={'operation_native_id','member','expected','new'} and item['member']=='DepthAllow' and type(item['operation_native_id']) is int,'Exact fixed dependent observation required')
    require(type(item['expected']) is float and type(item['new']) is float and math.isfinite(item['expected']) and math.isfinite(item['new']),'Strict finite dependent scalar values required')
    require(len(plan['rows'])==1 and plan['rows'][0]['operation_native_id']==item['operation_native_id'],'Dependent readback must address the unique requested rough')
    changes=[x for x in plan['rows'][0]['fields'] if x['field']=='floor_allowance']
    require(len(changes)==1 and changes[0]['expected']==item['expected'] and changes[0]['new']==item['new'],'Dependent expected/new must exactly match the declared floor change')
    actual=fields.parameter_row(before,item['operation_native_id'])['rough']['depth']['DepthAllow']['raw']
    require(type(actual) is float and actual==item['expected'],'Actual own DepthAllow differs from explicit dependent expectation')
    return True


class CircularParameterProof:
    pocket=pocket
    equal=staticmethod(circular_state_equal)
    verify_assignment_delta=staticmethod(verify_assignment_delta)
    def __init__(self,declared):self.declared=deepcopy(declared)
    def verify_final(self,before,after,plan,candidates):
        admitted=dependencies(before,plan,self.declared)
        fields.verify_final(normalized(before),normalized(align_circular_mass(before,after)),plan,candidates,observed_floor_alias=admitted)


def verify_final(before,after,plan,candidates):
    CircularParameterProof([]).verify_final(before,after,plan,candidates)


def _completed(d,scope):
    require(d.get('scope')==scope and d.get('action')=='apply' and d.get('status')=='review_required' and d.get('phase')=='finished','Exact completed circular apply receipt required')
    require(not any(k in d for k in ('issue','failed_phase','runtime_error','receipt_write_error','cleanup_error')),'Partial or failed circular receipt rejected')
    for key in ('GOP_attempted','GTP_attempted','AFR_attempted','native_dispatch_pending'):require(d.get(key) is False,'Unexpected circular side effect or pending outcome: '+key)
    clean_events(d)
    b=d.get('binding');require(type(b) is dict and d.get('request_pin')==dict(kind='canonical_binding',sha256=_digest(b)),'Exact canonical circular binding required')
    require(type(d.get('save_hresult')) is int and d['save_hresult']==0,'One strict successful native Save return required')
    if scope!=POCKET_SCOPE:require(d.get('save_call_returned') is True,'Actual configuration Save return required')
    return b


def _identity(d,b,process_id,source_path,source_sha256):
    require(type(b.get('process_id')) is int and b['process_id']==process_id,'Circular authority process differs')
    require(Path(b.get('expected_document_path','')).resolve()==Path(source_path).resolve(),'Circular authority source path differs')
    require(d.get('source_after_sha256')==d.get('saved_file_sha256')==source_sha256,'Circular authority saved source differs')
    require(type(b.get('expected_process_create_time')) in (int,float) and math.isfinite(b['expected_process_create_time']) and b['expected_process_create_time']>0,'Exact circular authority lifetime required')


def _pair(d,name):
    state=d.get(name)
    require(type(state) is dict and circular_state_equal(state,d.get('confirm_'+name)) and state.get('capture_complete') is True,'Two complete equal circular captures required: '+name)
    return state


def _actions(d,kinds):
    rows=d.get('actions');require(type(rows) is list and [x.get('kind') for x in rows]==kinds,'Exact circular action chain required')
    for row in rows:
        require(all(row.get(k) is True for k in ('attempted','returned','readback_verified')) and row.get('native_dispatch_pending') is False,'Incomplete circular native action')
    return rows


def load_pocket(path,sha,*,process_id,source_path,source_sha256):
    """从原始 completed 配置到 sketch/feature/rough/Save 的逐步证据，不伪造旧类型。"""
    from scripts import sw_cam_current_saved_generation as generation
    d,pin=read_pin(path,sha);b=_completed(d,POCKET_SCOPE);_identity(d,b,process_id,source_path,source_sha256)
    require(all(d.get(k) is True for k in FLAGS),'Circular creation/Save/runtime flags incomplete')
    actions=_actions(d,['CreateSketch','CreateMillFeature2','InsertOperation','SaveActiveDocument'])
    require(actions[-1].get('native_result')==dict(return_type='int',hresult=0),'Exact circular Save action result required')
    for row in actions[1:3]:require(row.get('native_result',{}).get('nonnull') is True,'Actual nonnull factory/insert return required')
    ap=d.get('authority_pin');require(type(ap) is dict,'Original completed configuration pin required')
    original,actual=read_pin(ap['path'],ap['sha256']);require(actual==ap,'Original configuration pin differs')
    require(Path(b.get('configuration_receipt_path','')).resolve()==Path(ap['path']).resolve() and b.get('configuration_receipt_sha256')==ap['sha256'],'Original configuration binding/pin differs')
    ids=[b['anchor_operation_native_id']]
    loaded=generation.load_completed_configuration(ap['path'],ap['sha256'],process_id=process_id,source_path=source_path,source_sha256=d['source_before_sha256'],selected_ids=ids)
    require(b['expected_source_sha256']==d['source_before_sha256'] and type(b['expected_process_create_time']) is type(loaded['binding']['expected_process_create_time']) and b['expected_process_create_time']==loaded['binding']['expected_process_create_time'],'Original circular source/lifetime differs')
    fid=d.get('new_feature_native_id');ops=d.get('new_operations');names=d.get('created_names')
    require(type(fid) is int and fid>0 and type(ops) is list and len(ops)==1 and type(names) is list and 1<=len(names)<=2 and all(type(x) is str and x for x in names) and len(set(names))==len(names),'Exact created pocket/rough/sketch IDs required')
    oid=ops[0]['native_id'];require(type(oid) is int and oid>0,'Strict new operation ID required')
    before=_pair(d,'before');sketch=_pair(d,'after_sketch');feature=_pair(d,'after_feature');insert=_pair(d,'after_insert');saved=_pair(d,'saved')
    pocket.verify_sketch(before,sketch,names);pocket.verify_feature(sketch,feature,b,fid);actual_op=pocket.verify_insert(feature,insert,b,oid,fid)
    require(fields.equal(ops,[actual_op]),'Recorded new operation differs from complete insertion capture')
    pocket.verify_saved(insert,saved,source_sha256)
    require(saved['document']['needs_save'] is False and saved['sketch_state']['needs_save'] is False,'Circular saved state must be clean')
    require(saved['parameter_capture_complete'] is True and saved['parameter_batch']['read_complete'] is True,'Complete circular own parameters required')
    # 原始保护基准直接还原；只去掉新捕获层，不删去任何原始字段。
    base=deepcopy(before);base.pop('sketch_state');require(base.pop('extended_capture_complete',None) is True,'Complete extended circular capture required')
    base['target_header']=base.pop('reference_header');base['profile']=base.pop('reference_profile');base['number_of_steps_raw']=base.pop('reference_number_of_steps_raw')
    base.update(base.pop('reference_parameter_observation'))
    require(fields.equal(base,loaded['state']),'Circular initial capture differs from original completed configuration')
    return dict(receipt=d,pin=pin,state=deepcopy(saved),binding=deepcopy(b),original=loaded,restore=dict(new_feature_native_id=fid,new_operations=deepcopy(ops),created_names=deepcopy(names)),addin_clsid=loaded['addin_clsid'],source_sha256=source_sha256,
        pins=dict(pocket=pin,original=ap,**{'original_'+k:p for k,p in loaded['pins'].items()},**{'history_'+k:p for k,p in loaded.get('recovery_pins',{}).items()}))


def load_inputs(v,clsid=None):
    loaded=load_pocket(v['pocket_receipt_path'],v['pocket_receipt_sha256'],process_id=v['process_id'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'])
    if clsid is not None:require(clsid==loaded['addin_clsid'],'Explicit circular CAM add-in differs')
    require(type(v['expected_process_create_time']) is type(loaded['binding']['expected_process_create_time']) and v['expected_process_create_time']==loaded['binding']['expected_process_create_time'],'Circular continuation lifetime differs')
    restore=loaded['restore'];ids=[r['native_id'] for r in restore['new_operations']]
    require(v['expected_feature_native_id']==restore['new_feature_native_id'] and v['parameter_operation_native_ids']==ids,'Only the actual new pocket rough may be configured')
    baseline=loaded['state'];candidate=baseline['parameter_batch']['candidate_tool']['generic']['native_id']
    require(v['candidate_tool_native_id']==candidate and v['expected_candidate_consumer_ids']==baseline['parameter_batch']['candidate_consumer_ids'],'Exact circular candidate/consumer observation required')
    recipe,pin=read_pin(v['recipe_path'],v['recipe_sha256']);plan=fields.compile_plan(baseline,recipe);dependencies(baseline,plan,v['dependent_readbacks'])
    require([r['operation_native_id'] for r in plan['rows']]==ids and all(r['feature_native_id']==v['expected_feature_native_id'] and r['existing_tool_native_id'] in (None,candidate) for r in plan['rows']),'Circular recipe must address the unique actual new rough and existing candidate')
    from scripts.sw_cam_current_saved_parameter_batch import load_inputs as load_original_inputs
    original_inputs=load_original_inputs(loaded['original']['binding'],clsid)
    return dict(baseline=deepcopy(baseline),authority=deepcopy(original_inputs['authority']),circular=loaded,plan=plan,pins=dict(pocket=loaded['pin'],recipe=pin),protected_pins=deepcopy(loaded['pins']))


def validate(v,clsid=None):
    require(v.get('configuration_mode')==MODE and v.get('action') in ('prepare','apply'),'Explicit circular prepare/apply required')
    require(type(v['process_id']) is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time']) in (int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Strict owned circular lifetime required')
    require(type(v['expected_source_sha256']) is str and re.fullmatch('[0-9a-f]{64}',v['expected_source_sha256']),'Strict circular source digest required')
    source=Path(v['expected_document_path']);require(source.is_absolute() and source.suffix.lower()=='.sldprt' and source.is_file() and not source.is_symlink() and _file_hash(source)==v['expected_source_sha256'],'Exact current circular source file required')
    require(type(v['save_after_verified']) is bool and (v['action']=='apply' or not v['save_after_verified']) and v['acknowledge_qualification_only'] is True,'Explicit circular Save/qualification choice required')
    for key in ('expected_feature_native_id','candidate_tool_native_id'):require(type(v[key]) is int and 0<v[key]<2**32,'Strict native ID required')
    for key,bound in (('parameter_operation_native_ids',1),('expected_candidate_consumer_ids',32)):
        ids=v[key];require(type(ids) is list and len(ids)<=bound and all(type(x) is int and 0<x<2**32 for x in ids) and len(ids)==len(set(ids)),'Strict bounded IDs required')
    out=Path(v['receipt_path']);require(out.is_absolute() and out.suffix.lower()=='.json' and out.parent.is_dir() and not out.exists() and not out.is_symlink(),'Unique circular receipt required')
    data=load_inputs(v,clsid);marker=attempt_marker(v['attempt_registry_path'],v['expected_document_path'],v['expected_source_sha256'],v['expected_feature_native_id'])
    require(not marker.exists() and not marker.is_symlink(),'Prior source/feature attempt exists; never replay')
    protected={Path(p['path']).resolve() for p in [*data['pins'].values(),*data['protected_pins'].values()]}
    require(source.resolve() not in protected and out.resolve() not in protected and marker.resolve() not in protected and len({source.resolve(),out.resolve(),marker.resolve()})==3,'Circular output aliases immutable evidence/source')
    if v['action']=='prepare':require(v['prepare_receipt_path'] is None and v['prepare_receipt_sha256'] is None,'Prepare cannot consume prepare')
    else:
        prep,pin=read_pin(v['prepare_receipt_path'],v['prepare_receipt_sha256'])
        require(Path(pin['path']).resolve() not in protected|{source.resolve(),out.resolve(),marker.resolve()},'Prepare must remain immutable')
        require(prep.get('scope')=='MILL_CURRENT_SAVED_PARAMETER_BATCH_V1' and prep.get('action')=='prepare' and prep.get('status')=='review_required' and prep.get('phase')=='finished' and prep.get('readback_verified') is True and prep.get('runtime_unchanged') is True and prep.get('mutation_attempted') is False and fields.equal(prep.get('binding'),binding(v)),'Exact completed circular prepare required')
        require(circular_state_equal(prep.get('before'),prep.get('confirm_before')) and prep.get('state_sha256')==_digest(prep['before']),'Stable circular prepare required');clean_events(prep);data.update(prepare=prep,prepare_pin=pin)
    return marker,data


def load_configured(path,sha,*,process_id,source_path,source_sha256,selected_ids):
    from scripts import sw_cam_current_saved_generation as generation
    d,pin=read_pin(path,sha);b=_completed(d,generation.CONFIG_SCOPE);_identity(d,b,process_id,source_path,source_sha256)
    require(b.get('configuration_mode')==MODE and all(d.get(k) is True for k in generation.CONFIG_FLAGS),'Explicit verified circular configuration required')
    data=load_inputs(b);require(fields.equal(d.get('qualified_read_pins'),data['pins']) and fields.equal(d.get('recipe'),data['plan']),'Circular configuration immutable recipe/authority differs')
    before=_pair(d,'before');after=_pair(d,'after');saved=_pair(d,'saved')
    require(circular_state_equal(before,data['baseline']),'Circular configuration before differs from actual saved pocket')
    candidate=before['parameter_batch']['candidate_tool'];CircularParameterProof(b['dependent_readbacks']).verify_final(before,after,data['plan'],{b['candidate_tool_native_id']:candidate});pocket.verify_saved(after,saved,source_sha256)
    expected=[];previous=before
    for row in data['plan']['rows']:
        if row['existing_tool_native_id'] is not None:
            expected.append(('SetTool',row['operation_native_id'],None))
            state=d['after_tool_'+str(row['operation_native_id'])];require(circular_state_equal(state,d['confirm_tool_'+str(row['operation_native_id'])]),'Two full SetTool captures required');verify_assignment_delta(previous,state,row,candidate);previous=state
        expected.extend(('field',row['operation_native_id'],x) for x in row['fields'] if not fields.equal(x['expected'],x['new']))
    expected.append(('SaveActiveDocument',None,None));actions=_actions(d,[x[0] for x in expected])
    for a,(kind,oid,change) in zip(actions,expected):
        require(a.get('operation_native_id')==oid and fields.equal(a.get('change'),change) and a.get('return_type')=='int' and type(a.get('return_value')) is int and a['return_value']==0,'Exact configured native action/result required')
        if kind=='field':
            observed=a.get('observed',{});raw=observed.get('raw',{})
            require(observed.get('returned') is True and type(raw) is dict and raw.get('recorded') is True and fields.equal(raw.get('raw'),change['new']),'Actual immediate circular field readback differs')
    ids=b['parameter_operation_native_ids'];require(selected_ids==ids,'Only the configured new rough may generate');generation.delta.select(saved,ids)
    pins=dict(data['pins']);pins.update(data['protected_pins'])
    return dict(receipt=d,pin=pin,state=deepcopy(saved),binding=deepcopy(b),recipe=deepcopy(data['plan']),pins=pins,recovery_pins={},addin_clsid=data['circular']['addin_clsid'],selected_ids=deepcopy(ids),source_sha256=source_sha256,circular=data['circular'],mode=MODE)
