"""有界读取操作自己的 toolpath feature 参数；仅观察声明输出，不猜测曲线接口。"""
from copy import deepcopy
from ctypes import POINTER, byref, c_double, c_short
from ctypes.wintypes import VARIANT_BOOL
from pathlib import Path
import math,re
from comtypes import COMError
from comtypes.automation import IDispatch
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_comtypes import _interface_class,CamComBridgeError
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_route_operations,integer
from scripts.sw_cam_current_saved_generation import load_completed_configuration
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import absolute_document_path,check_document_target,solidworks_operation_lock

SCOPE='MILL_OPERATION_TP_GEOMETRY_READ_V1'
EVENT_ERRORS=('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')
RAW_BASE='_ICWMillOperation3__com_GetTpBaseFeature'
RAW_PARAMS='_ICWTpBaseFeature__com_GetTpFeatParameters'
BOOL_SENTINEL=12345
MAX_READS=2048
INTERFACES=('ICWApp4','ICWDoc3','ICWPartDoc','ICWMachine','ICWBaseSetup','ICWBaseOpSetup',
    'ICWDispatchCollection','ICWFeature','ICWOperation','ICWMillOperation','ICWMillOperation3',
    'ICWToolpath','ICWTool','ICWTpBaseFeature')


def require(condition,message):
    if not condition:raise ValueError(message)


def preflight(tlb):
    """只解析注册表与精确 ABI；raw OUT 避免自动 GetBestInterface 查询。"""
    from ctypes import HRESULT
    classes={name:_interface_class(name,tlb) for name in INTERFACES}
    specs=[('ICWMillOperation3','{20DEC8D6-8B4F-4876-90CB-F2A8D87A9D78}','GetTpBaseFeature',25,
        (POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,10),RAW_BASE),
        ('ICWTpBaseFeature','{87B34A84-9E8B-404B-ACC6-85456C7C8E2A}','GetTpFeatParameters',1,
        (POINTER(c_double),POINTER(c_double),POINTER(c_double),POINTER(VARIANT_BOOL),
         POINTER(POINTER(IDispatch)),POINTER(POINTER(IDispatch)),POINTER(POINTER(IDispatch))),(2,)*7,RAW_PARAMS)]
    for owner,iid,name,disp,args,flags,raw in specs:
        cls=classes[owner];methods=[m for m in cls._methods_ if m.name==name]
        require(str(cls._iid_).upper()==iid and len(methods)==1,'Exact declared interface/member required')
        m=methods[0]
        require(m.restype is HRESULT and m.argtypes==args and tuple(x[0] for x in m.paramflags)==flags
            and m.idlflags[0]==disp and not any(x in m.idlflags for x in ('propget','propput','propputref'))
            and callable(getattr(cls,raw,None)),'Exact raw getter ABI required: '+name)
    return dict(native_calls=0,registered_interfaces=list(INTERFACES),raw_owned_OUT_buffers=True,automatic_interface_discovery=False)


def projection(state):
    """只比较本读取范围的身份、顺序、链接、工具标量和轨迹计数。"""
    return dict(feature_setups=[{k:deepcopy(r[k]) for k in ('index','native_id','feature_ids')} for r in state['feature_setups']],
        operation_setups=deepcopy(state['operation_setups']),operations=deepcopy(state['operations']),operation_count=state['operation_count'])


def validate(v,clsid=None):
    integer(v['process_id'],'PID',1,2**31-1);integer(v['anchor_operation_native_id'],'anchor ID',1)
    tm=v['expected_process_create_time'];require(type(tm) in (int,float) and math.isfinite(tm) and tm>0,'Exact process lifetime required')
    require(type(v['expected_document_path']) is str and absolute_document_path(v['expected_document_path']) and Path(v['expected_document_path']).suffix.casefold()=='.sldprt','Absolute saved part required')
    for key in ('expected_source_sha256','configuration_receipt_sha256'):require(type(v[key]) is str and re.fullmatch('[0-9a-f]{64}',v[key]),'Exact SHA required')
    require(v['qualification_only'] is True and v['message_policy']=='vendor_default','Qualification read only required')
    targets=v['targets'];require(type(targets) is list and 1<=len(targets)<=4,'One to four explicit operation/feature targets required')
    keys={'operation_native_id','feature_native_id','feature_setup_native_id','operation_setup_native_id','mill_operation_type'}
    for target in targets:
        require(type(target) is dict and set(target)==keys,'Exact target fields required')
        for key,value in target.items():integer(value,key,0 if key=='mill_operation_type' else 1)
    require(len({t['operation_native_id'] for t in targets})==len(targets),'Unique target operations required')
    loaded=load_completed_configuration(v['configuration_receipt_path'],v['configuration_receipt_sha256'],process_id=v['process_id'],
        source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'],selected_ids=[v['anchor_operation_native_id']])
    require(loaded['binding']['expected_process_create_time']==tm,'Saved authority lifetime differs')
    if clsid is not None:require(loaded['addin_clsid'].casefold()==clsid.casefold(),'Explicit add-in differs from pinned request')
    state=loaded['state']
    for t in targets:
        rows=[x for x in state['operations'] if x['native_id']==t['operation_native_id']]
        require(len(rows)==1 and rows[0]['linked_feature_ids']==[t['feature_native_id']] and rows[0]['setup_native_id']==t['operation_setup_native_id']
            and rows[0]['mill_operation_type']==t['mill_operation_type'] and rows[0]['suppressed'] is False,'Saved target operation binding differs')
        require(sum(t['feature_native_id'] in x['feature_ids'] and x['native_id']==t['feature_setup_native_id'] for x in state['feature_setups'])==1,'Saved feature membership differs')
    loaded['all_pins']=[loaded['pin']]+list(loaded['pins'].values())+list(loaded.get('recovery_pins',{}).values())
    return loaded


def dispatch_presence(value):
    """只读取调用方拥有的 IDispatch 指针是否为零，不解引用或试探接口。"""
    require(isinstance(value,IDispatch),'Exact owned IDispatch output storage required')
    return dict(declared_interface='IDispatch',present=bool(value),address_recorded=False,interface_traversed=False)


def double_observation(value):
    return dict(raw=value if math.isfinite(value) else None,finite=math.isfinite(value),untouched_or_nonfinite=not math.isfinite(value))


def _com_failure(exc):
    # 仅原生 COM 异常可作为该 getter 的诊断；所有本地契约错误都终止。
    try:
        from pywintypes import com_error
        return isinstance(exc,(COMError,com_error))
    except ImportError:return isinstance(exc,COMError)


def read_geometry(operation,feature,*,typed,raw_call,row,boundary):
    """两个固定 raw getter；即使返回异常也保留已写入 OUT 缓冲。"""
    row.update(parameters_complete=False,base_call={},parameter_call=None)
    base=POINTER(IDispatch)();owner=typed(operation,'ICWMillOperation3')
    try:status=raw_call(owner,RAW_BASE,(feature,byref(base)),row['base_call'],lambda:dict(base_feature=dispatch_presence(base)))
    except Exception as exc:
        if not _com_failure(exc):raise
        boundary();row['outcome']='base_getter_COM_failure';return
    if type(status) is int and status==1 and not bool(base):
        row['outcome']='base_getter_status1_null';boundary();return
    require(type(status) is int and status==0,'Strict base getter HRESULT S_OK required')
    if not bool(base):row['outcome']='null_base_feature';boundary();return
    row['base_interface_call']=dict(interface='ICWTpBaseFeature',attempted=True,returned=False)
    try:tp=typed(base,'ICWTpBaseFeature')
    except Exception as exc:
        row['base_interface_call']['issue']=_error(exc)
        native_missing=type(getattr(exc,'hresult',None)) is int and exc.hresult==-2147467262 and (
            _com_failure(exc) or (isinstance(exc,CamComBridgeError) and exc.code=='CAM_COM_NATIVE_QI_FAILED'
            and exc.bridge_stage=='native_query_interface' and exc.error_type in ('COMError','com_error')
            and exc.input_type==type(base).__name__ and exc.source_type==type(base).__name__))
        if not native_missing:raise
        boundary();row['outcome']='declared_base_interface_unsupported';return
    row['base_interface_call']['returned']=True
    values=[c_double(float('nan')) for _ in range(3)];flag=VARIANT_BOOL();c_short.from_buffer(flag).value=BOOL_SENTINEL
    pointers=[POINTER(IDispatch)() for _ in range(3)]
    def outputs():
        return dict(**{k:double_observation(x.value) for k,x in zip(('machining_depth_native','feature_depth_native','start_Z_native'),values)},
            pattern_boolean_short=c_short.from_buffer(flag).value,**{k:dispatch_presence(x) for k,x in zip(('start_position','island_list','segment_chain'),pointers)})
    row['parameter_call']={}
    try:status=raw_call(tp,RAW_PARAMS,tuple(byref(x) for x in [*values,flag,*pointers]),row['parameter_call'],outputs)
    except Exception as exc:
        if not _com_failure(exc):raise
        boundary();row['outcome']='parameter_getter_COM_failure';return
    if type(status) is int and status==1:
        row['outcome']='parameter_getter_status1';boundary();return
    require(type(status) is int and status==0,'Strict parameter getter HRESULT S_OK required')
    observed=outputs();require(all(math.isfinite(x.value) for x in values),'All three DOUBLE outputs must be populated and finite')
    require(observed['pattern_boolean_short'] in (0,-1),'VARIANT_BOOL output must be populated with 0 or -1')
    row.update(parameters_complete=True,outcome='typed_parameters_observed',parameters=dict(
        **{k:x.value for k,x in zip(('machining_depth_native','feature_depth_native','start_Z_native'),values)},
        is_pattern_feature=observed['pattern_boolean_short']==-1,
        **{k:observed[k] for k in ('start_position','island_list','segment_chain')}))
    boundary()


def capture(app,loaded,v,*,read,typed,raw_call,boundary,state):
    """复用有界路由清单；不重读所有操作参数、特征轮廓或刀具完整几何。"""
    state.update(capture_complete=False,features=[],feature_setups=[],selected=[])
    boundary();active=read(app,'IGetActiveDoc');doc=typed(active,'ICWDoc3')
    require(integer(read(doc,'GetDocType'),'document type')==1,'CAM part required')
    machine=typed(read(typed(active,'ICWPartDoc'),'IGetMachine'),'ICWMachine');require(integer(read(machine,'MachType'),'machine type')==1,'MILL machine required')
    raw_features={};seen=set()
    for index,raw in enumerate(_items(read(machine,'IGetEnumSetups'),typed,read,8)):
        setup=typed(raw,'ICWBaseSetup');sid=_object_id(doc,setup,read);require(sid not in seen,'Unique setup ID required');seen.add(sid)
        row=dict(index=index,native_id=sid,feature_ids=[]);state['feature_setups'].append(row)
        for feat in _items(read(setup,'IGetEnumFeatures'),typed,read,64-len(raw_features)):
            base=typed(feat,'ICWFeature');fid=_object_id(doc,base,read);require(fid not in seen,'Unique feature ID required');seen.add(fid)
            row['feature_ids'].append(fid);raw_features[fid]=base;state['features'].append(dict(setup_native_id=sid,geometry=dict(native_id=fid)))
    state['operation_counts']=[];setup_owners={}
    for raw in _items(read(machine,'IGetEnumOpSetups'),typed,read,8):
        setup=typed(raw,'ICWBaseOpSetup');sid=_object_id(doc,setup,read)
        require(sid not in setup_owners,'Unique operation setup ID required')
        setup_owners[sid]=_object_id(doc,read(setup,'GetSetup'),read)
        state['operation_counts'].append(len(_items(read(setup,'IGetEnumOperations'),typed,read,32)))
    native=dict(doc=doc,machine=machine);read_route_operations(state,native,read,typed)
    require(projection(state)==projection(loaded['state']),'Current observed inventory differs from saved anchor')
    boundary()
    for target in v['targets']:
        oid=target['operation_native_id'];fid=target['feature_native_id'];sid=target['feature_setup_native_id']
        require(setup_owners[target['operation_setup_native_id']]==sid,'Operation setup feature owner differs')
        lookup=read(doc,'GetCWObjectFromID',1,fid)
        require(type(lookup) in (tuple,list) and len(lookup)==2 and lookup[1] is True,'Exact feature lookup required')
        feature=typed(lookup[0],'ICWFeature');enumerated=raw_features[fid]
        for item in (feature,enumerated):
            require(_object_id(doc,item,read)==fid and _object_id(doc,read(item,'GetOwner'),read)==sid and read(item,'Suppressed') is False,'Selected feature identity or owner differs')
        operation=typed(native['operations'][oid],'ICWOperation')
        require(_object_id(doc,operation,read)==oid,'Selected own operation ID differs')
        row=dict(target=deepcopy(target));state['selected'].append(row)
        boundary();read_geometry(operation,feature,typed=typed,raw_call=raw_call,row=row,boundary=boundary)
    boundary();state['capture_complete']=True


def inspect_operation_geometry(sw,clsid,typelib_path,*,process_id,expected_process_create_time,expected_document_path,
        expected_source_sha256,configuration_receipt_path,configuration_receipt_sha256,anchor_operation_native_id,
        targets,qualification_only=True,message_policy='vendor_default',runtime_check=None):
    """返回两次有界原始观察；空指针或 getter COM 失败不等于空刀路原因。"""
    v=locals().copy();session=None;runtime_check=runtime_check or (lambda:None)
    report=dict(scope=SCOPE,status='running',phase='validation',read_pending=True,read_only=True,mutation_attempted=False,GTP_attempted=False,
        GOP_attempted=False,AFR_attempted=False,save_attempted=False,model_saved=False,automatic_retry_permitted=False,
        observation_verified=False,readback_verified=False,guards_verified=False,may_continue=False,parameters_complete=False,
        units_verified=False,coordinate_frame_verified=False,full_contours_read=False,pointer_interfaces_traversed=False,
        empty_toolpath_cause_proven=False,production_qualified=False,native_read_count=0,raw_getter_attempts=0,
        post_cleanup_cam_read_performed=False,targets=deepcopy(targets))
    try:
        loaded=validate(v,clsid);report['authority_pin']=deepcopy(loaded['pin']);report['getter_abi']=preflight(typelib_path);runtime_check()
        def identity():
            runtime_check()
            process=_process_identity(process_id)
            require(process.get('alive') is True and process.get('process_id')==process_id and process.get('create_time')==expected_process_create_time
                and Path(process.get('executable','')).name.casefold()=='sldworks.exe','Exact process lifetime changed')
            pid=_member(sw,'GetProcessID');require(type(pid) is int and pid==process_id,'Owned process differs')
            current=document_snapshot(sw);require(type(current) is dict and current.get('type')==1 and current.get('needs_save') is False,'Clean current saved part required')
            check_document_target(current['path'],current['title'],expected_path=expected_document_path,required=True)
            require(_file_hash(expected_document_path)==expected_source_sha256,'Saved source changed')
            for pin in loaded['all_pins']:require(_file_hash(pin['path'])==pin['sha256'],'Immutable authority changed')
            return current
        with solidworks_operation_lock(timeout_seconds=1,process_id=process_id):
            initial=identity();require(initial==loaded['state']['document'],'Saved document identity differs');report['document']=deepcopy(initial)
            addin=_member(sw,'GetAddInObject',clsid);require(addin is not None,'CAM must already be loaded')
            app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path);require(identity()==initial,'Identity changed during bootstrap')
            session=CamMessageSession(app,typelib_path)
            def check():
                summary=session.summary();report['messages']=summary
                require(summary.get('active') is True and summary.get('subscribed') is True and not any(summary.get(k) for k in EVENT_ERRORS),'CAM event requires stop')
            def boundary():
                check();require(identity()==initial,'Current document changed');check()
            def admission(name):
                check();report['phase']=name;require(report['native_read_count']<MAX_READS,'Bounded read budget exceeded');report['native_read_count']+=1
            def read(obj,name,*args):
                admission(name);value=_member(obj,name,*args);check();return value
            def typed(obj,name):
                require(name in INTERFACES,'Interface outside fixed read scope');admission('QI '+name);value=_typed(obj,name,typelib_path);check();return value
            def raw_call(obj,name,args,entry,observe):
                require(name in (RAW_BASE,RAW_PARAMS),'Only two fixed raw getters allowed');admission(name)
                entry.update(attempted=True,returned=False,owned_output_storage=True,automatic_retry=False)
                report['raw_getter_attempts']+=1
                try:
                    result=_member(obj,name,*args);entry.update(returned=True,hresult_type=type(result).__name__,hresult=result if type(result) is int else None)
                except Exception as exc:
                    entry['issue']=_error(exc);raise
                finally:entry['outputs']=observe();check()
                return result
            with session:
                for phase in ('before','after'):
                    report['capture_phase']=phase;report[phase]={}
                    capture(app,loaded,v,read=read,typed=typed,raw_call=raw_call,boundary=boundary,state=report[phase])
                require(report['before']==report['after'],'Two complete bounded observations differ');boundary()
            summary=session.summary();report['messages']=summary
            require(summary.get('active') is False and summary.get('subscribed') is True and summary.get('disconnected') is True
                and not any(summary.get(k) for k in EVENT_ERRORS),'Event cleanup not confirmed')
            require(identity()==initial,'Identity changed after cleanup')
            report.update(status='review_required',phase='finished',read_pending=False,
                observed_target_outcomes=[x['outcome'] for x in report['after']['selected']],
                observation_result='complete_declared_parameters' if all(x['parameters_complete'] for x in report['after']['selected']) else 'stable_null_or_unsupported_or_COM_diagnostics',
                observation_verified=True,readback_verified=True,guards_verified=True,
                parameters_complete=all(x['parameters_complete'] for x in report['after']['selected']),reason='STABLE_DECLARED_OUTPUT_DIAGNOSTICS_NO_CAUSE_OR_MACHINING_CLAIM')
    except Exception as exc:
        report.update(status='error',failed_phase=report['phase'],phase='finished',read_pending=False,issue=_error(exc),observation_verified=False,readback_verified=False,guards_verified=False,parameters_complete=False)
    finally:
        if session is not None:report['messages']=session.summary()
    return report
