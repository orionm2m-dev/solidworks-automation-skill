"""限定读取 TURN 机器 post 参数数量及索引零；不推断 Preset 或索引基准。"""
from __future__ import annotations
import math
import re
from pathlib import Path
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_cam_qualification_context import _converted_shape
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import absolute_document_path, check_document_target, solidworks_operation_lock

_IID = "{3767818E-318E-4F18-BBD2-572DB04B45F0}"
_MAX_PARAMETERS = 512
_EVENT_ERRORS = ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')


def validate(values):
    """校验包含进程、文档、哈希和计数的 values 字典；无返回值，不连接应用。"""
    for key,lo,hi in [('process_id',1,2**32-1),('expected_operation_count',0,512),
                     ('expected_generated_operation_count',0,512),('expected_total_record_count',0,1000000)]:
        value=values[key]
        if type(value) is not int or not lo<=value<=hi: raise ValueError('Invalid strict selector: '+key)
    time=values['expected_process_create_time']
    if type(time) not in (int,float) or not math.isfinite(time) or time<=0: raise ValueError('Exact process lifetime required')
    path=values['expected_document_path']
    if type(path) is not str or not absolute_document_path(path) or Path(path).suffix.casefold()!='.sldprt': raise ValueError('Exact absolute saved part required')
    digest=values['expected_source_sha256']
    if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}',digest): raise ValueError('Exact saved source SHA required')
    if values['expected_generated_operation_count']>values['expected_operation_count']: raise ValueError('Generated count exceeds operation count')
    if values['action']!='probe_index_zero' or values['qualification_only'] is not True or values['message_policy']!='vendor_default':
        raise ValueError('Only explicit qualification probe_index_zero and vendor_default allowed')


def _abi(typelib_path):
    """验证两个 getter 的精确 IID、DISPID、方向与类型；不进行 QI。"""
    from ctypes import HRESULT, POINTER, c_int
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes import BSTR
    interface=_interface_class('ICWMachine5',typelib_path)
    if str(interface._iid_).upper()!=_IID: raise ValueError('Exact machine interface IID differs')
    for name,disp,args,flags in [('GetNumPostParam',27,(POINTER(c_int),),(10,)),
        ('GetPostParam',28,(c_int,POINTER(BSTR),POINTER(BSTR),POINTER(VARIANT_BOOL)),(1,2,2,10))]:
        methods=[m for m in interface._methods_ if m.name==name]
        if len(methods)!=1: raise ValueError('Unique exact method required: '+name)
        m=methods[0]
        if m.restype is not HRESULT or m.idlflags[0]!=disp or any(x in m.idlflags for x in ('propget','propput','propputref')) or m.argtypes!=args or tuple(x[0] for x in m.paramflags)!=flags:
            raise ValueError('Exact getter ABI differs: '+name)
    return dict(interface='ICWMachine5',iid=_IID,getter_count=2,native_calls=0)


def _decode_zero(raw,result):
    """仅解释声明的三元输出；False 的 OUT 值保留为诊断，不作为参数。"""
    if type(raw) not in (tuple,list) or len(raw)!=3 or type(raw[2]) is not bool:
        raise ValueError('GetPostParam requires two BSTR OUTs and strict Boolean retval')
    result['index_zero_found_native']=raw[2]
    if not raw[2]: return False
    if any(type(x) is not str or len(x)>1000 for x in raw[:2]):
        raise ValueError('Found parameter requires two bounded BSTR values')
    result['entry_raw']={'index':0,'name':raw[0],'value':raw[1]}
    return True


def probe_turn_post_parameter(sw,clsid,typelib_path,*,process_id,expected_process_create_time,
        expected_document_path,expected_source_sha256,expected_operation_count,
        expected_generated_operation_count,expected_total_record_count,
        action='probe_index_zero',qualification_only=True,message_policy='vendor_default'):
    """限定读取一次机器参数数量及可选索引零。

    参数为已绑定的 SOLIDWORKS 对象、加载项和 TLB，以及精确进程生命周期、
    文档路径、保存文件哈希、操作/生成/记录计数。只接受 qualification_only。
    返回包含原始转换诊断、前后身份快照和验证标志的字典；不遍历或写入。
    """
    values=locals().copy()
    report=dict(status='error',phase='validation',action=action,may_continue=False,
        mutation_attempted=False,model_saved=False,GTP_attempted=False,GOP_attempted=False,
        controller_parameters_read=False,preset_values_verified=False,units_verified=False,
        coordinate_frame_verified=False,production_qualified=False,catalog_complete=False,
        zero_based_catalog_verified=False,readback_verified=False,observation_verified=False,
        guards_verified=False,index_zero_acceptance_verified=False,automatic_retry_permitted=False,
        index_sequence_requested=[0],native_parameter_call_count=0,native_variant_metadata_preserved=False,
        bootstrap_scope='GetAddInObject/GetCWApp only before message subscription',
        full_cam_snapshot_scope='before_event_disconnect',post_cleanup_cam_read_performed=False,
        scope='Machine5 count once; positive bounded count permits GetPostParam(0) once; no further index')
    session=None
    try:
        validate(values);report['getter_abi']=_abi(typelib_path)
        def identity():
            state=_process_identity(process_id)
            if state.get('alive') is not True or state.get('process_id')!=process_id or state.get('create_time')!=expected_process_create_time or Path(state.get('executable','')).name.casefold()!='sldworks.exe':
                raise ValueError('Exact SOLIDWORKS process lifetime changed')
            pid=_member(sw,'GetProcessID')
            if type(pid) is not int or pid!=process_id: raise ValueError('Exact PID mismatch')
            doc=document_snapshot(sw)
            if not isinstance(doc,dict) or doc.get('type')!=1 or type(doc.get('needs_save')) is not bool or not doc.get('path'): raise ValueError('Saved part required')
            check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True)
            if _file_hash(doc['path'])!=expected_source_sha256: raise ValueError('Saved source SHA changed')
            return doc
        with solidworks_operation_lock(timeout_seconds=1,process_id=process_id):
            initial=identity();report['unsaved_memory_present']=initial['needs_save']
            addin=_member(sw,'GetAddInObject',clsid)
            if addin is None: raise ValueError('CAM must already be loaded')
            app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)
            session=CamMessageSession(app,typelib_path)
            def check():
                state=session.summary();report['messages']=state
                if not state.get('active') or not state.get('subscribed') or any(state.get(k) for k in _EVENT_ERRORS):
                    raise ValueError('CAM event transport requires review; no further CAM getters')
            def read(obj,name,*args):
                report['phase']=name;check();raw=_member(obj,name,*args);check();return raw
            def probe_read(target,name,*args):
                report['phase']=name;check()
                entry=dict(attempted=True,returned=False,arguments=list(args));report[name]=entry
                report['native_parameter_call_count']+=1
                try: raw=_member(target,name,*args)
                except Exception as error:
                    entry['issue']=_error(error);raise
                entry.update(returned=True,converted_output_shape=_converted_shape(raw))
                check();return raw
            def capture(result):
                result['capture_complete']=False;check()
                current=identity();result['document']=current
                if current!=initial: raise ValueError('Document state changed')
                context_doc,doc,_,machine,_=_context(sw,clsid,typelib_path,read)
                if context_doc!=initial: raise ValueError('Document changed during context binding')
                inventory=_inventory(machine,typelib_path,read);result['inventory']=inventory
                if inventory.get('machine_type')!=3: raise ValueError('Exact TURN machine required')
                ops=inventory['operations']
                if len(ops)!=expected_operation_count or inventory['operation_count']!=expected_operation_count or sum(x['toolpath_generated'] is True for x in ops)!=expected_generated_operation_count or sum(sum(x['toolpath_record_counts']) for x in ops)!=expected_total_record_count:
                    raise ValueError('Exact operation/generated/record counts differ')
                ids=[];result['operation_identities']=ids
                for si,setup in enumerate(_items(read(machine,'IGetEnumOpSetups'),typelib_path,read,limit=512)):
                    base=_typed(setup,'ICWBaseOpSetup',typelib_path)
                    for oi,raw in enumerate(_items(read(base,'IGetEnumOperations'),typelib_path,read,limit=512-len(ids))):
                        operation=_typed(raw,'ICWOperation',typelib_path)
                        ids.append(dict(setup_index=si,operation_index=oi,native_id=_object_id(doc,operation,read)))
                if len(ids)!=len(ops) or len({x['native_id'] for x in ids})!=len(ids) or [(x['setup_index'],x['operation_index']) for x in ids]!=[(x['setup_index'],x['operation_index']) for x in ops]:
                    raise ValueError('Operation identity traversal differs from inventory')
                if identity()!=initial: raise ValueError('Document changed during capture')
                check();result['capture_complete']=True
                return _typed(machine,'ICWMachine5',typelib_path)
            with session:
                report['before']={};target=capture(report['before'])
                count=probe_read(target,'GetNumPostParam')
                if type(count) is not int or not 0<=count<=_MAX_PARAMETERS: raise ValueError('Post parameter count must be strict LONG 0..512')
                report['parameter_count_native']=count
                if identity()!=initial: raise ValueError('Document changed after count read')
                found=False
                if count:
                    raw=probe_read(target,'GetPostParam',0)
                    found=_decode_zero(raw,report)
                    reason='INDEX_ZERO_OBSERVED' if found else 'INDEX_ZERO_NOT_FOUND'
                else: reason='NATIVE_POST_PARAMETER_COUNT_ZERO'
                report['after']={};capture(report['after'])
                if report['before']!=report['after']: raise ValueError('Document or collected CAM inventory/IDs changed')
                check()
            summary=session.summary();report['messages']=summary
            if summary.get('disconnected') is not True or summary.get('active') or any(summary.get(k) for k in _EVENT_ERRORS): raise ValueError('CAM event cleanup not confirmed')
            if identity()!=initial: raise ValueError('Document changed after event cleanup')
            report.update(status='review_required',phase='finished',reason=reason,
                guards_verified=True,observation_verified=True,index_zero_acceptance_verified=found,
                post_cleanup_document_file_verified=True)
    except Exception as error:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(error),
                      guards_verified=False,observation_verified=False,index_zero_acceptance_verified=False)
    finally:
        if session is not None: report['messages']=session.summary()
    return report
