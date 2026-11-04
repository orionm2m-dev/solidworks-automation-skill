"""读取当前已保存 MILL 多台阶特征；独立身份门禁，不改写历史证据。"""
from copy import deepcopy
import math
import re
from pathlib import Path
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_qualification import _vector
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_mill_route_context import read_route_operations, integer
from scripts.sw_cam_compound_step_probe import read_three_step_profile
from scripts.sw_cam_qualification_context import _converted_shape
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import absolute_document_path, check_document_target, solidworks_operation_lock

_EVENT_ERRORS=('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')
_STEP_GETTERS={'GetNumOfSteps','GetTypeAtStep','GetCylParams','GetConeParams','GetCoordinates'}


def validate(v):
    """校验独立当前保存文件读取契约；不加载历史计划或连接应用。"""
    for key in ('process_id','expected_feature_native_id','expected_feature_setup_native_id','expected_operation_setup_native_id'):
        integer(v[key],key,1)
    lifetime=v['expected_process_create_time']
    if type(lifetime) not in (int,float) or not math.isfinite(lifetime) or lifetime<=0:
        raise ValueError('Exact process lifetime required')
    path=v['expected_document_path']
    if type(path) is not str or not absolute_document_path(path) or Path(path).suffix.casefold()!='.sldprt':
        raise ValueError('Exact absolute saved part required')
    if type(v['expected_source_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',v['expected_source_sha256']):
        raise ValueError('Exact current source SHA required')
    ids=v['expected_operation_native_ids']
    if type(ids) is not list or not 0<=len(ids)<=32 or any(type(x) is not int or not 0<x<2**32 for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Explicit unique ordered operation IDs required')
    integer(v['expected_generated_operation_count'],'generated operation count',0,32)
    integer(v['expected_total_record_count'],'record count',0,100000)
    if v['expected_generated_operation_count']>len(ids):raise ValueError('Generated count exceeds operation count')
    if v['read_mode']!='current_saved' or v['observation'] not in ('header_and_count','three_step_profile') or v['qualification_only'] is not True or v['message_policy']!='vendor_default':
        raise ValueError('Explicit current-saved read-only qualification required')


def _abi(path):
    """只检查声明的 getter 元数据；不做 COM 调用或猜测接口。"""
    from ctypes import HRESULT,POINTER,c_long,c_double
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    dispatch=POINTER(POINTER(IDispatch))
    specs=[('ICWMultiStepFeature','{B18F74D1-3CCE-11D6-A9B1-00062999E55F}',[
        ('GetNumOfSteps',4,(POINTER(c_long),),(10,)),
        ('GetTypeAtStep',9,(c_long,POINTER(c_long)),(1,10)),
        ('GetCylParams',10,(c_long,POINTER(c_double),POINTER(c_double),dispatch),(1,2,2,2)),
        ('GetConeParams',11,(c_long,POINTER(c_double),POINTER(c_double),POINTER(c_double),POINTER(c_double),dispatch,POINTER(VARIANT_BOOL),POINTER(c_double)),(1,2,2,2,2,2,2,2))]),
        ('ICWBaseOpSetup','{FB4CC0E1-2AA4-11D6-A99F-00062999E55F}',[('GetSetup',30,(dispatch,),(10,))])]
    for name,iid,methods in specs:
        cls=_interface_class(name,path)
        if str(cls._iid_).upper()!=iid:raise ValueError('Exact getter interface IID differs')
        for method,disp,args,flags in methods:
            found=[m for m in cls._methods_ if m.name==method]
            if len(found)!=1:raise ValueError('Unique declared getter required')
            m=found[0]
            if m.restype is not HRESULT or m.idlflags[0]!=disp or any(x in m.idlflags for x in ('propget','propput','propputref')) or m.argtypes!=args or tuple(x[0] for x in m.paramflags)!=flags:
                raise ValueError('Exact getter ABI differs: '+method)
    return dict(declared_getters_verified=5,native_calls=0)


def _capture(app,tlb,read,typed,state,v,boundary,*,verify_operation_pins=True):
    """使用现有 header、collection、operation 和三台阶读取函数采集原始状态。"""
    state.update(capture_complete=False,features=[],feature_setups=[],operation_counts=[])
    boundary()
    active=read(app,'IGetActiveDoc');doc=typed(active,'ICWDoc3')
    if integer(read(doc,'GetDocType'),'CAM document type')!=1:raise ValueError('Exact CAM part required')
    machine=typed(read(typed(active,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    if integer(read(machine,'MachType'),'machine type')!=1:raise ValueError('MILL machine required')
    native=dict(doc=doc,machine=machine);target=None;seen=set()
    for si,raw in enumerate(_items(read(machine,'IGetEnumSetups'),typed,read,8)):
        setup=typed(raw,'ICWBaseSetup');sid=_object_id(doc,setup,read)
        if sid in seen:raise ValueError('Duplicate setup identity')
        seen.add(sid);mill=typed(raw,'ICWSetup')
        members=_items(read(setup,'IGetEnumFeatures'),typed,read,64-len(state['features']))
        row=dict(index=si,native_id=sid,axis_native=_vector(read(setup,'Axis')),origin_native=_vector(read(mill,'GetReferencePosition')),feature_ids=[])
        state['feature_setups'].append(row)
        for item in members:
            base=typed(item,'ICWFeature');fid=_object_id(doc,base,read)
            if fid in seen:raise ValueError('Duplicate or cross-kind feature identity')
            seen.add(fid);row['feature_ids'].append(fid)
            state['features'].append(dict(setup_native_id=sid,geometry=dict(native_id=fid)))
            if fid==v['expected_feature_native_id']:
                if sid!=v['expected_feature_setup_native_id']:raise ValueError('Target membership differs')
                target=item
        boundary()
    if target is None:raise ValueError('Exact target feature missing')
    op_setups=_items(read(machine,'IGetEnumOpSetups'),typed,read,8);selected=None
    for raw in op_setups:
        setup=typed(raw,'ICWBaseOpSetup');sid=_object_id(doc,setup,read)
        members=_items(read(setup,'IGetEnumOperations'),typed,read,32)
        state['operation_counts'].append(len(members))
        if sid==v['expected_operation_setup_native_id']:
            if selected is not None:raise ValueError('Duplicate target operation setup')
            selected=dict(native_id=sid,feature_setup_native_id=_object_id(doc,read(setup,'GetSetup'),read),operation_count=len(members))
            state['selected_operation_setup']=selected
            if selected['feature_setup_native_id']!=v['expected_feature_setup_native_id']:
                raise ValueError('Operation setup belongs to another feature setup')
    if selected is None:raise ValueError('Exact operation setup missing')
    read_route_operations(state,native,read,typed)
    operations=state['operations']
    if verify_operation_pins and ([r['native_id'] for r in operations]!=v['expected_operation_native_ids'] or sum(r['toolpath_generated'] for r in operations)!=v['expected_generated_operation_count'] or sum(sum(r['toolpath_record_counts']) for r in operations)!=v['expected_total_record_count']):
        raise ValueError('Expected operation order or path counts differ')
    boundary()
    raw=read(doc,'GetCWObjectFromID',1,v['expected_feature_native_id'])
    if not isinstance(raw,(tuple,list)) or len(raw)!=2 or raw[1] is not True or raw[0] is None:
        raise ValueError('Exact target lookup failed')
    header,base=read_header(raw[0],doc,read,typed,v['expected_feature_setup_native_id'])
    state['target_header']=header
    if header['native_id']!=v['expected_feature_native_id'] or header['volume_type']!=11 or header['suppressed'] is not False:
        raise ValueError('Exact unsuppressed compound feature required')
    repeated,_=read_header(target,doc,read,typed,v['expected_feature_setup_native_id'])
    if repeated!=header:raise ValueError('Lookup and enumerated feature differ')
    compound=typed(raw[0],'ICWMultiStepFeature')
    count=read(compound,'GetNumOfSteps');state['number_of_steps_raw']=count
    integer(count,'step count',1,64)
    if v['observation']=='three_step_profile':
        state['profile']=read_three_step_profile(compound,count=count,read=read,typed=typed)
    after_count=read(compound,'GetNumOfSteps')
    integer(after_count,'repeated step count',1,64)
    repeated,_=read_header(target,doc,read,typed,v['expected_feature_setup_native_id'])
    if after_count!=count or repeated!=header:raise ValueError('Compound changed during capture')
    boundary();state['capture_complete']=True
    return dict(doc=doc,machine=machine,selected_feature=base)


def inspect_current_saved_compound(sw,clsid,typelib_path,*,process_id,expected_process_create_time,
        expected_document_path,expected_source_sha256,expected_feature_native_id,
        expected_feature_setup_native_id,expected_operation_setup_native_id,expected_operation_native_ids,
        expected_generated_operation_count,expected_total_record_count,read_mode='current_saved',
        observation='header_and_count',qualification_only=True,message_policy='vendor_default'):
    """读取当前保存模型中的精确复合特征；返回两次原始状态，不生成、保存或改写。

    输入包含 PID/创建时间、路径/SHA、特征和两类 setup ID、完整有序操作 ID 与路径计数。
    三台阶模式只在实际计数等于三时调用已有的索引0..2读取器；其他计数不猜测。
    """
    v=locals().copy();session=None
    report=dict(scope='MILL_CURRENT_SAVED_COMPOUND_READ_V1',status='error',phase='validation',
        read_mode=read_mode,observation=observation,read_only=True,mutation_attempted=False,
        GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,model_saved=False,
        observation_verified=False,readback_verified=False,guards_verified=False,may_continue=False,
        units_verified=False,coordinate_frame_verified=False,production_qualified=False,
        full_hidden_geometry_preservation_verified=False,cl_coordinates_compared=False,
        historical_receipt_loaded=False,automatic_retry_permitted=False,native_read_count=0,
        post_cleanup_cam_read_performed=False,step_getter_diagnostics=[])
    try:
        validate(v);report['getter_abi']=_abi(typelib_path)
        def identity():
            p=_process_identity(process_id)
            if p.get('alive') is not True or p.get('process_id')!=process_id or p.get('create_time')!=expected_process_create_time or Path(p.get('executable','')).name.casefold()!='sldworks.exe':raise ValueError('Exact process lifetime changed')
            pid=_member(sw,'GetProcessID')
            if type(pid) is not int or pid!=process_id:raise ValueError('Exact PID changed')
            doc=document_snapshot(sw)
            if type(doc) is not dict or type(doc.get('type')) is not int or doc['type']!=1 or doc.get('needs_save') is not False:raise ValueError('Clean current saved part required')
            check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True)
            if _file_hash(expected_document_path)!=expected_source_sha256:raise ValueError('Current saved source SHA changed')
            return doc
        with solidworks_operation_lock(timeout_seconds=1,process_id=process_id):
            initial=identity();report['document']=deepcopy(initial)
            addin=_member(sw,'GetAddInObject',clsid)
            if addin is None:raise ValueError('CAM must already be loaded')
            app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)
            if identity()!=initial:raise ValueError('Identity changed during bootstrap')
            session=CamMessageSession(app,typelib_path)
            def check():
                s=session.summary();report['messages']=s
                if s.get('active') is not True or s.get('subscribed') is not True or any(s.get(k) for k in _EVENT_ERRORS):raise ValueError('CAM event transport requires stop')
            def boundary():
                check()
                if identity()!=initial:raise ValueError('Document state changed')
                check()
            def read(obj,name,*args):
                check();report['phase']=name
                if report['native_read_count']>=4096:raise ValueError('Bounded read budget exceeded')
                report['native_read_count']+=1
                diag=None
                if name in _STEP_GETTERS:
                    diag=dict(method=name,arguments=list(args),capture=report['capture_phase'],attempted=True,returned=False)
                    report['step_getter_diagnostics'].append(diag)
                raw=_member(obj,name,*args)
                if diag is not None:diag.update(returned=True,converted_output_shape=_converted_shape(raw))
                check();return raw
            def typed(raw,name):
                check();result=_typed(raw,name,typelib_path);check()
                if result is None:raise ValueError('Missing declared interface: '+name)
                return result
            with session:
                for phase in ('before','after'):
                    report['capture_phase']=phase;state={};report[phase]=state
                    _capture(app,typelib_path,read,typed,state,v,boundary)
                if report['before']!=report['after']:raise ValueError('Two complete observations differ')
                boundary()
            s=session.summary();report['messages']=s
            if s.get('active') is not False or s.get('disconnected') is not True or s.get('subscribed') is not True or any(s.get(k) for k in _EVENT_ERRORS):raise ValueError('Event cleanup not confirmed')
            if identity()!=initial:raise ValueError('Document changed after cleanup')
            report.update(status='review_required',phase='finished',observation_verified=True,
                readback_verified=True,guards_verified=True,reason='STABLE_RAW_CURRENT_SAVED_COMPOUND_NO_MACHINING_QUALIFICATION')
    except Exception as error:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(error),
                      readback_verified=False,observation_verified=False,guards_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
    return report
