"""当前保存 MILL 定义的两次显式插入；仅抑制指定无轨迹旧定义。"""
from copy import deepcopy
from contextlib import contextmanager
from scripts import sw_cam_mill_current_compound_read as current
from scripts import sw_cam_guide_group_definitions as definitions
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_append_delta import _inventory
from scripts.sw_cam_thread import _object_id
from scripts.sw_operation_guard import check_document_target

KEYS=('saved_authority_receipt_path','saved_authority_receipt_sha256','anchor_operation_native_id',
      'insert_operations','suppress_operation_native_ids')
PAIRS=(('saved_authority_receipt_path','saved_authority_receipt_sha256'),)


def require(value,message):
    if not value:raise ValueError(message)


def selected(v):return v.get('definition_mode','retain_plan')=='selected_insert'


def validate_choices(v):
    require(v.get('definition_mode','retain_plan') in ('retain_plan','selected_insert'),'Explicit supported definition mode required')
    if not selected(v):
        require(all(v.get(k) is None for k in KEYS),'Selected insert fields forbidden for RETAIN mode')
        return
    require(all(v.get(k) is None for k in ('current_read_request_path','current_read_request_sha256','current_read_receipt_path','current_read_receipt_sha256')),'Selected mode consumes actual saved authority, not fabricated read evidence')
    rows=v.get('insert_operations')
    require(type(rows) is list and len(rows)==2,'Exactly two explicit rough/finish choices required')
    for kind,row in enumerate(rows):
        require(type(row) is dict and set(row)=={'operation_type','default_operation_name','default_operation_id'},'Exact selected definition fields required')
        require(type(row['operation_type']) is int and row['operation_type']==kind,'Ordered Rough0 then Finish1 required')
        require(type(row['default_operation_id']) is int and 0<row['default_operation_id']<2**31,'Strict positive catalogue ID required')
        require(type(row['default_operation_name']) is str and 0<len(row['default_operation_name'])<=1000 and '\x00' not in row['default_operation_name'],'Exact bounded catalogue name required')
    ids=v.get('suppress_operation_native_ids')
    require(type(ids) is list and len(ids)==2 and all(type(x) is int and 0<x<2**31 for x in ids) and len(set(ids))==2,'Two explicit unique suppression IDs required')
    anchor=v.get('anchor_operation_native_id')
    require(type(anchor) is int and 0<anchor<2**31 and anchor==ids[-1],'Exact last suppressed anchor required')


def authority(v):
    """先前保存结果只提供固定基准；当前 PID/源文件与新鲜双读取独立校验。"""
    data,pin=read_pin(v['saved_authority_receipt_path'],v['saved_authority_receipt_sha256'])
    require(data.get('scope')=='MILL_CURRENT_SAVED_APPEND_V1' and data.get('status')=='review_required' and data.get('phase')=='finished' and data.get('action')=='apply','Completed actual saved append required')
    for key in ('readback_verified','runtime_unchanged','operation_delta_verified','save_readback_verified','model_saved','source_update_verified','save_call_returned'):
        require(data.get(key) is True,'Verified saved authority flag required: '+key)
    require(data.get('GTP_attempted') is False and data.get('native_dispatch_pending') is False and type(data.get('save_hresult')) is int and data['save_hresult']==0,'Finished definition-only Save required')
    require(not any(k in data for k in ('issue','failed_phase','runtime_error','receipt_write_error')),'Failed saved authority rejected')
    clean_events(data)
    require(data.get('saved_file_sha256')==data.get('source_after_sha256')==v['expected_source_sha256'],'Exact saved source transition required')
    old=data['binding']
    for key in ('process_id','expected_process_create_time','expected_document_path','expected_feature_native_id','expected_feature_setup_native_id','expected_operation_setup_native_id'):
        require(type(old.get(key)) is type(v[key]) and old[key]==v[key],'Saved authority identity differs: '+key)
    state=data.get('saved')
    require(type(state) is dict and state==data.get('confirm_saved') and state.get('capture_complete') is True,'Two complete equal saved captures required')
    require(state['document']['needs_save'] is False,'Saved authority must be clean')
    check_document_target(state['document']['path'],state['document']['title'],expected_path=v['expected_document_path'],required=True)
    rows,_=_inventory(state)
    require([x['native_id'] for x in rows]==v['expected_operation_native_ids'],'Saved authority operation order differs')
    require(sum(x['toolpath_generated'] is True for x in rows)==v['expected_generated_operation_count'] and sum(sum(x['toolpath_record_counts']) for x in rows)==v['expected_total_record_count'],'Saved path counts differ')
    require(state['target_header']['native_id']==v['expected_feature_native_id'] and state['number_of_steps_raw']==3 and state['profile']['complete_step_coverage'] is True,'Exact three-step target required')
    require(state['selected_operation_setup']['native_id']==v['expected_operation_setup_native_id'] and state['selected_operation_setup']['feature_setup_native_id']==v['expected_feature_setup_native_id'],'Exact setup ownership required')
    plan(state,v)
    raw=deepcopy(state)
    for key in ('document','strategy_diagnostics','default_operation_catalogues'):raw.pop(key)
    return raw,dict(authority=pin),deepcopy(state)


def plan(state,v):
    _inventory(state);ops=state['operations'];ids=v['suppress_operation_native_ids']
    require(len(ops)+2<=32 and [x['native_id'] for x in ops[-2:]]==ids,'Two exact tail definitions required; capacity exceeded or wrong order')
    target=[x for x in ops if v['expected_feature_native_id'] in x['linked_feature_ids']]
    require([x['native_id'] for x in target]==ids and state['selected_operation_setup']['operation_count']==2,'Only the two selected prior definitions may own the target')
    for row in ops[-2:]:
        require(row['setup_native_id']==v['expected_operation_setup_native_id'] and row['linked_feature_ids']==[v['expected_feature_native_id']] and row['suppressed'] is False and row['toolpath_generated'] is False and row['toolpath_record_counts']==[],'Suppression requires exact ungenerated target definitions')
    out=[]
    for choice in v['insert_operations']:
        catalogs=[c for c in state['default_operation_catalogues'] if c['operation_type']==choice['operation_type']]
        require(len(catalogs)==1,'Unique current catalogue required')
        matches=[x for x in catalogs[0]['entries'] if x['name']==choice['default_operation_name'] and type(x['default_operation_id']) is int and x['default_operation_id']==choice['default_operation_id']]
        require(len(matches)==1,'Selected name/ID absent from actual catalogue')
        out.append(dict(choice,feature_native_id=v['expected_feature_native_id'],feature_owner_setup_native_id=v['expected_feature_setup_native_id'],operation_setup_native_id=v['expected_operation_setup_native_id']))
    return dict(suppress_operation_native_ids=deepcopy(ids),anchor_operation_native_id=v['anchor_operation_native_id'],insert_operations=out,
                maximum_suppression_setters=2,maximum_insert_calls=2,GOP_allowed=False,GTP_allowed=False)


def abi(tlb):
    from ctypes import HRESULT,c_long,POINTER
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    cls=current._interface_class('ICWOperation',tlb)
    require(str(cls._iid_).upper()=='{4EDDCA73-325A-11D6-A9A7-00062999E55F}','Exact operation interface required')
    for name,args,directions,flag in (('_get_Suppressed',(POINTER(VARIANT_BOOL),),(10,),'propget'),('_set_Suppressed',(VARIANT_BOOL,),(1,),'propput')):
        rows=[m for m in cls._methods_ if m.name==name];require(len(rows)==1,'Exact Suppressed property required');m=rows[0]
        require(m.restype is HRESULT and m.idlflags[0]==13 and flag in m.idlflags and m.argtypes==args and tuple(p[0] for p in m.paramflags)==directions,'Exact Suppressed property ABI required')
    cls=current._interface_class('ICWMillFeature',tlb);rows=[m for m in cls._methods_ if m.name=='InsertOperation']
    require(str(cls._iid_).upper()=='{682686E2-3685-11D6-A9AA-00062999E55F}' and len(rows)==1,'Exact MILL feature interface required');m=rows[0]
    require(m.restype is HRESULT and m.idlflags[0]==44 and m.argtypes==(c_long,c_long,POINTER(IDispatch),POINTER(POINTER(IDispatch))) and tuple(p[0] for p in m.paramflags)==(1,1,1,10) and not any(x in m.idlflags for x in ('propget','propput','propputref')),'Exact InsertOperation ABI required')


def verify_suppression(before,after,oid):
    _inventory(before);_inventory(after);expected=deepcopy(before)
    rows=[x for x in expected['operations'] if x['native_id']==oid]
    require(len(rows)==1 and rows[0]['suppressed'] is False and rows[0]['toolpath_generated'] is False and rows[0]['toolpath_record_counts']==[],'Exact unsuppressed ungenerated old definition required')
    rows[0]['suppressed']=True;expected['document']['needs_save']=after['document']['needs_save']
    require(expected==after,'Unexpected captured change after Suppressed=True')


def verify_insert(before,after,row,oid,anchor):
    _inventory(before);_inventory(after)
    project=lambda s:{k:deepcopy(s[k]) for k in ('features','operation_setups','operations')}
    result=definitions.verify_one_addition(project(before),project(after),row,oid,anchor)
    expected=deepcopy(before);expected['operations'].append(deepcopy(result));si=result['setup_index']
    expected['operation_setups'][si]['operation_count']+=1;expected['operation_counts'][si]+=1;expected['operation_count']+=1
    expected['selected_operation_setup']['operation_count']+=1;expected['document']['needs_save']=after['document']['needs_save']
    require(expected==after,'Unexpected captured change after selected insertion')
    return result


def execute(v,report,before,native,*,read,typed,capture,check,identity,runtime_check,persist):
    """小型适配器复用已限定 InsertOperation；每步双读取验证后才进行下一步。"""
    chosen=plan(before,v);state=before;doc=native['doc'];report['definition_actions']=[];report['new_operations']=[]
    def boundary():
        check();require(identity()==state['document'],'Document changed before selected dispatch');runtime_check()
    class Adapter:
        @contextmanager
        def guard(self):
            boundary();yield self
        def read(self,*args):return read(*args)
        def typed(self,*args):return typed(*args)
        def dispatch_once(self,call,persist_pending):
            boundary();persist_pending();boundary();result=call()
            action.update(returned=True,native_dispatch_pending=False,return_type=type(result).__name__)
            report.update(native_call_returned=True,native_dispatch_pending=False);persist();check();return result
    adapter=Adapter()
    def pending():
        action.update(attempted=True,native_dispatch_pending=True)
        report.update(mutation_attempted=True,native_call_attempted=True,native_dispatch_pending=True);persist()
    def observe(label,verify):
        after,_=capture(label,True);verify(after)
        confirm,_=capture('confirm_'+label,True);require(confirm==after,'Two selected-step captures differ');verify(confirm)
        action.update(readback_verified=True);persist();return confirm
    for oid in chosen['suppress_operation_native_ids']:
        action=dict(kind='suppress',operation_native_id=oid,requested_value=True,attempted=False,returned=False,readback_verified=False)
        report['definition_actions'].append(action);persist();boundary()
        found=read(doc,'GetCWObjectFromID',3,oid);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact suppression operation lookup required')
        op=typed(found[0],'ICWOperation');require(_object_id(doc,op,read)==oid and read(op,'Suppressed') is False and read(op,'GetIsToolpathGenerated') is False,'Suppression operation changed')
        adapter.dispatch_once(lambda:setattr(op,'Suppressed',True),pending)
        state=observe('after_suppress_'+str(oid),lambda after:verify_suppression(state,after,oid))
    anchor=chosen['anchor_operation_native_id']
    for index,row in enumerate(chosen['insert_operations']):
        action=dict(kind='insert',choice=deepcopy(row),anchor_native_id=anchor,attempted=False,returned=False,readback_verified=False)
        report['definition_actions'].append(action);persist()
        raw=definitions.insert_selected_once(adapter,doc,row,anchor,before['target_header'],pending)
        oid=_object_id(doc,raw,read);action['actual_native_id']=oid;persist()
        forbidden={x['native_id'] for x in state['operations']+state['operation_setups']+state['feature_setups']}
        forbidden|={x['geometry']['native_id'] for x in state['features']}|{x['assigned_tool']['native_id'] for x in state['operations']}
        require(type(oid) is int and 0<oid<2**31 and oid not in forbidden,'New positive non-colliding native operation ID required')
        action['own_nc']=definitions.read_own_nc(raw,read=read,typed=typed);persist()
        state=observe('after_insert_'+str(index),lambda after:verify_insert(state,after,row,oid,anchor))
        report['new_operations'].append(deepcopy(state['operations'][-1]));anchor=oid;persist()
    report['after']=deepcopy(state);report['confirm_after']=deepcopy(state);report['operation_delta_verified']=True;persist()
    return state
