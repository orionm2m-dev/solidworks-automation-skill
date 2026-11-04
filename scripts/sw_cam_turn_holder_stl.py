"""限定现有车削镗杆的 STL 定义更新；不建刀、不生成轨迹、不保存。"""
from copy import deepcopy
from ctypes import HRESULT, POINTER, c_int
from pathlib import Path
import math
import os
from comtypes import BSTR
from scripts import sw_cam_turn_tool as single
from scripts import sw_cam_turn_feature_regenerate as policy
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_comtypes import _interface_class, _INTERFACES
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_operation_profile import _read_tool
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_cam_checkpoint_exports import local_evidence_root
from scripts.sw_operation_guard import check_document_target

SCOPE = 'TURN_EXISTING_BORING_HOLDER_STL_QUALIFICATION_V1'
require = policy.require
REF_KEYS = {'setup_index','operation_index','expected_operation_type','operation_native_id','linked_feature_ids'}

def _int(v, low=0, high=2**31-1):
    require(type(v) is int and low <= v <= high, 'Strict bounded native integer required')
    return v

def validate_request(c, action, digest, receipt_path, qualification_only, message_policy):
    """校验完整源文件、共享操作和 STL 配方；参数非法时抛出异常。"""
    _int(c['process_id'],1,2**32-1)
    require(type(c['expected_process_create_time']) in (int,float) and math.isfinite(c['expected_process_create_time'])
        and c['expected_process_create_time']>0, 'Exact finite process lifetime required')
    require(action in ('prepare','apply') and qualification_only is True and message_policy=='vendor_default', 'Explicit qualification-only action/policy required')
    for name,suffix in [('expected_document_path','.sldprt'),('holder_stl_path','.stl')]:
        p=Path(c[name]);require(type(c[name]) is str and p.is_absolute() and p.suffix.lower()==suffix, 'Exact absolute source/STL path required')
    for name in ('expected_source_sha256','holder_stl_sha256'):require(policy.sha(c[name]), 'Exact file SHA256 required')
    require(policy.key(c['expected_document_path'])!=policy.key(c['holder_stl_path']), 'Source and STL must differ')
    _int(c['expected_tool_native_id'],1,2**32-1);_int(c['expected_operation_native_id'],1,2**32-1)
    _int(c['expected_holder_id'],0);require(type(c['holder_file_unit_raw']) is int and c['holder_file_unit_raw']==2, 'Only explicit pilot metre raw value 2 supported')
    require(type(c['expected_holder_shape_raw']) is int and c['expected_holder_shape_raw']==0, 'Only observed standard shape 0 to STL qualification supported')
    require(type(c['expected_holder_orientation_raw']) is int and c['expected_holder_orientation_raw']==5, 'Only LEFT_UP boring orientation supported')
    selected=single._reference({k:c[k] for k in ('setup_index','operation_index','expected_operation_type')})
    require(selected['expected_operation_type']==6, 'Only existing finish-bore operations supported')
    refs=c['affected_operations'];require(type(refs) is list and 1<=len(refs)<=64, 'Explicit complete bounded affected references required')
    keys=[];ids=[]
    for ref in refs:
        require(type(ref) is dict and set(ref)==REF_KEYS, 'Exact affected reference keys required')
        base=single._reference({k:ref[k] for k in ('setup_index','operation_index','expected_operation_type')})
        require(base['expected_operation_type']==6, 'Every affected operation must be finish-bore')
        _int(ref['operation_native_id'],1,2**32-1);ids.append(ref['operation_native_id']);keys.append(single._ref_key(base))
        fs=ref['linked_feature_ids'];require(type(fs) is list and 1<=len(fs)<=64, 'Exact linked feature IDs required')
        for fid in fs:_int(fid,1,2**32-1)
        require(len(set(fs))==len(fs), 'Duplicate feature ID')
    require(len(set(keys))==len(keys) and len(set(ids))==len(ids), 'Duplicate affected operation')
    require(any(single._ref_key(ref)==single._ref_key(selected) and ref['operation_native_id']==c['expected_operation_native_id'] for ref in refs), 'Selected native operation must be explicitly affected')
    if action=='prepare':require(digest is None and receipt_path is None, 'Prepare accepts no apply digest or receipt')
    else:
        require(policy.sha(digest) and type(receipt_path) is str, 'Exact prepared digest and fresh receipt required')
        p=Path(receipt_path);require(p.is_absolute() and p.suffix.lower()=='.json' and p.parent.is_dir() and not p.exists() and not p.is_symlink(), 'Fresh absolute JSON receipt required')
        require(policy.key(p) not in {policy.key(c['expected_document_path']),policy.key(c['holder_stl_path'])}, 'Receipt aliases input')

def holder_abi(typelib):
    """按类型库核对刀柄文件写入和回读签名；不激活 CAD。"""
    specs={'ICWTurnTool': [('SetTurnHolderSTLFile',5,(BSTR,),(1,),None),('SetTurnHolderSTLFileUnit',6,(c_int,),(1,),None)],
           'ICWTurnToolHolder':[('HolderShape',11,(POINTER(c_int),),(10,),'propget'),('HolderShapeFilePath',25,(POINTER(BSTR),),(10,),'propget'),('HolderShapeFileUnit',26,(POINTER(c_int),),(10,),'propget')]}
    for interface,rows in specs.items():
        cls=_interface_class(interface,typelib);require(str(cls._iid_).upper()==_INTERFACES[interface], 'Unexpected TURN interface IID')
        for name,dispid,args,flags,prop in rows:
            ms=[m for m in cls._methods_ if m.name==('_get_'+name if prop else name) and (prop in m.idlflags if prop else not any(x in m.idlflags for x in ('propget','propput','propputref')))]
            require(len(ms)==1, 'Unique declared holder ABI required');m=ms[0]
            require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==args and tuple(f[0] for f in m.paramflags)==flags, 'Unexpected holder ABI')

def _holder_file(holder, read, result=None):
    result={} if result is None else result
    path=read(holder,'HolderShapeFilePath');result['path_raw']=path
    require(path is None or type(path) is str and len(path)<=32767 and '\0' not in path, 'Invalid native holder file path')
    result['shape_raw']=_int(read(holder,'HolderShape'),-2**31)
    result['unit_raw']=_int(read(holder,'HolderShapeFileUnit'),-2**31)
    return result

def capture(sw,clsid,typelib,c,read,check,identity,diagnostic):
    """按请求采集当前文档和所有已分配刀具，返回状态及当前原生句柄。"""
    selected={k:c[k] for k in ('setup_index','operation_index','expected_operation_type')}
    state,native=single._snapshot(sw,clsid,typelib,selected,check=check,diagnostics=diagnostic,guarded_readers=True)
    assignment=next(x for x in state['operation_tools'] if x['operation']==selected)
    require(assignment['operation_native_id']==c['expected_operation_native_id'] and assignment['tool_native_id']==c['expected_tool_native_id'], 'Selected native operation/tool differs')
    require(state['selected_tool'].get('insert_type_raw')==1 and state['selected_tool'].get('turn_tool_type_raw')==1, 'Existing diamond insert and boring holder required')
    expected_refs=[{k:r[k] for k in selected} for r in c['affected_operations']]
    require(sorted(expected_refs,key=single._ref_key)==sorted(state['affected_operations'],key=single._ref_key), 'Exact complete shared tool membership differs')
    affected_keys={single._ref_key(r) for r in expected_refs}
    for row in state['inventory']['operations']:
        key=(row['setup_index'],row['operation_index'],row['turn_operation_type'])
        if key in affected_keys:require(row['toolpath_generated'] is False and row.get('toolpath_record_counts',[])==[], 'Affected operation already has a toolpath')
    _,doc,_,machine,_=_context(sw,clsid,typelib,read)
    doc=_typed(doc,'ICWDoc3',typelib)
    rows=[];target_holder=None
    diagnostic['extended_capture']=dict(complete=False,observed_operation_tools=rows)
    setups=_items(read(machine,'IGetEnumOpSetups'),typelib,read,limit=64)
    for si,raw_setup in enumerate(setups):
        setup=_typed(raw_setup,'ICWBaseOpSetup',typelib)
        for oi,raw in enumerate(_items(read(setup,'IGetEnumOperations'),typelib,read,limit=512-len(rows))):
            op=_typed(raw,'ICWOperation',typelib);oid=_object_id(doc,op,read)
            assigned=next(x for x in state['operation_tools'] if x['operation']['setup_index']==si and x['operation']['operation_index']==oi)
            require(assigned['operation_native_id']==oid, 'Repeated operation ID differs')
            linked=[_object_id(doc,f,read) for f in _items(read(op,'IGetAllFeatures'),typelib,read,limit=64)]
            tool=read(op,'IGetTool');tid=_object_id(doc,_typed(tool,'ICWTool',typelib),read)
            require(tid==assigned['tool_native_id'], 'Repeated own tool ID differs')
            observed={}
            row=dict(operation_native_id=oid,tool_native_id=tid,linked_feature_ids=linked,observed_tool=observed);rows.append(row)
            _read_tool(tool,op,typelib,read,observed,include_drill=True)
            if observed.get('turn_tool_type_raw')==1 and observed.get('holder',{}).get('holder_type_raw') in (1,2):
                turn=_typed(tool,'ICWTurnTool',typelib);holder=_typed(read(turn,'IGetTurnToolHolder'),'ICWTurnToolHolder',typelib)
                row['holder_file']={};_holder_file(holder,read,row['holder_file'])
                if tid==c['expected_tool_native_id']:
                    ref=next(r for r in c['affected_operations'] if r['operation_native_id']==oid)
                    require(linked==ref['linked_feature_ids'], 'Affected linked feature IDs differ')
                    hd=observed['holder'];require(hd['holder_type_raw']==2 and hd['holder_id_raw']==c['expected_holder_id'] and hd['orientation_for_operation_raw']==c['expected_holder_orientation_raw'], 'Affected own holder classification/orientation differs')
                    if oid==c['expected_operation_native_id']:target_holder=holder
    require(len(rows)==len(state['operation_tools']) and target_holder is not None, 'Complete own-tool traversal required')
    selected_rows=[r for r in rows if r['tool_native_id']==c['expected_tool_native_id']]
    require(len(selected_rows)==len(c['affected_operations']) and all(r['holder_file']==selected_rows[0]['holder_file'] for r in selected_rows), 'Shared own-tool holder file readbacks disagree')
    state['observed_operation_tools']=rows;state['selected_holder_file']=deepcopy(selected_rows[0]['holder_file'])
    require(identity()==state['document'] and _inventory(machine,typelib,read)==state['inventory'], 'Capture document/inventory changed')
    native['holder']=target_holder;diagnostic['extended_capture']['complete']=True
    return state,native

def verify_change(before,after,c,*,final):
    """比较写入前后完整采集，仅允许目标刀柄文件字段及派生显示变化。"""
    h=after['selected_holder_file'];require(type(h['path_raw']) is str and policy.key(h['path_raw'])==policy.key(c['holder_stl_path']), 'Holder path readback differs')
    require(h['shape_raw']>0 and h['shape_raw']!=c['expected_holder_shape_raw'], 'Documented STL shape switch not observed')
    if final:require(h['unit_raw']==c['holder_file_unit_raw'], 'Holder file unit readback differs')
    expected=deepcopy(before);expected['document']['needs_save']=after['document']['needs_save']
    expected['selected_holder_file']=deepcopy(h)
    expected['selected_tool']['info_raw']=after['selected_tool']['info_raw']
    expected['selected_tool']['holder']['shape_raw']=h['shape_raw']
    require(len(expected['observed_operation_tools'])==len(after['observed_operation_tools']), 'Operation count changed')
    for old,new in zip(expected['observed_operation_tools'],after['observed_operation_tools']):
        if old['tool_native_id']==c['expected_tool_native_id']:
            old['holder_file']=deepcopy(h);old['observed_tool']['holder']['shape_raw']=h['shape_raw']
            old['observed_tool']['info_raw']=new['observed_tool']['info_raw']
    require(expected==after, 'Unexpected delta outside target holder file/shape/unit and derived tool info')

def marker_path(identity,tool_id):
    """根据工作文件身份和刀具编号返回持久单次尝试标记路径。"""
    return local_evidence_root()/('turn_holder_stl_'+single._digest(dict(scope=SCOPE,file_identity=identity,tool_id=tool_id))+'.json')

def qualify_turn_holder_stl(sw,clsid,typelib_path,*,process_id,expected_process_create_time,expected_document_path,
        expected_source_sha256,setup_index,operation_index,expected_operation_type,expected_operation_native_id,
        expected_tool_native_id,expected_holder_id,expected_holder_shape_raw,expected_holder_orientation_raw,
        affected_operations,holder_stl_path,holder_stl_sha256,holder_file_unit_raw,qualification_only,message_policy,
        action='prepare',expected_state_sha256=None,receipt_path=None):
    """准备或执行限定刀柄 STL 配方，返回持久证据；不生成、不保存、不自动回滚。"""
    c={k:v for k,v in locals().copy().items() if k not in ('sw','clsid','typelib_path','qualification_only','message_policy','action','expected_state_sha256','receipt_path')}
    report=dict(scope=SCOPE,status='error',phase='preflight',action=action,mutation_attempted=False,
        native_dispatch_pending=False,native_calls_returned_count=0,readback_verified=False,apply_eligible=False,
        geometry_scale_verified=False,coordinate_frame_verified=False,native_units_semantics_verified=False,
        holder_shape_enum_mapping_verified=False,toolpath_coordinates_preserved=False,physical_holder_qualified=False,
        production_qualified=False,may_continue=False,model_saved=False,GTP_attempted=False,GOP_attempted=False,
        TechDB_write_attempted=False,tool_creation_attempted=False,insert_change_attempted=False,
        automatic_retry=False,automatic_rollback=False,receipt_created=False,receipt_path=None,setters=[],captures=[],guards=[],
        preservation_scope='all_operation_ids_links_observed_own_tool_scalars_holder_file_fields_and_path_record_counts')
    created=False;session=None;marker=None;claimed=False;receipt=None
    def persist():
        if created:_write_receipt(receipt,report)
    def files():
        pins=[]
        for path,digest in [(expected_document_path,expected_source_sha256),(holder_stl_path,holder_stl_sha256)]:
            p=Path(path);require(p.is_file() and not p.is_symlink() and _file_hash(p)==digest, 'Pinned source/STL changed')
            stat=p.stat();require(stat.st_ino!=0,'Stable file identity required')
            if p.suffix.lower()=='.stl':require(84<=stat.st_size<=100_000_000,'Bounded STL file size required')
            pins.append(dict(path=policy.key(p),device=stat.st_dev,inode=stat.st_ino,bytes=stat.st_size,sha256=digest))
        require(not os.path.samefile(expected_document_path,holder_stl_path),'Source aliases STL')
        return pins
    try:
        validate_request(c,action,expected_state_sha256,receipt_path,qualification_only,message_policy);holder_abi(typelib_path)
        pins=files();identity_pin={k:pins[0][k] for k in ('path','device','inode')};marker=marker_path(identity_pin,expected_tool_native_id)
        require(not marker.exists() and not marker.is_symlink(),'Prior holder assignment attempt exists; no replay')
        report.update(request=deepcopy(c),file_pins=pins,marker_path=str(marker),unit_mapping_status='pilot_raw_2_requires_independent_geometry_scale_check')
        if action=='apply':
            receipt=Path(receipt_path);require(policy.key(receipt)!=policy.key(marker),'Receipt aliases marker')
            _write_receipt(receipt,report,create=True);created=True;report.update(receipt_created=True,receipt_path=str(receipt))
        policy.isolated(sw,c,lambda:None)
        session=CamMessageSession(_bootstrap(sw,clsid,typelib_path,expected_document_path),typelib_path)
        def check():
            data=session.summary();report['messages']=data
            require(data.get('active') is True and data.get('subscribed') is True and not any(data.get(k) for k in policy.EVENT_ERRORS), 'CAM event requires stop')
        def read(obj,name,*args):
            check();value=_member(obj,name,*args);check();return value
        def identity():
            check();policy.isolated(sw,c,check);require(files()==pins,'Source/STL identity changed')
            doc=document_snapshot(sw);require(doc is not None and doc.get('type')==1 and type(doc.get('needs_save')) is bool,'Active saved part required')
            check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True);return doc
        def observe(label):
            report['phase']=label;diagnostic={}
            entry=dict(label=label,diagnostic=diagnostic,capture_complete=False);report['captures'].append(entry)
            try:
                state,native=capture(sw,clsid,typelib_path,c,read,check,identity,diagnostic)
                entry.update(state=deepcopy(state),capture_complete=True)
                return state,native
            finally:persist()
        with session:
            before,_=observe('before');require(before['document']['needs_save'] is False,'Initially clean saved qualification part required')
            require(before['selected_holder_file']['shape_raw']==expected_holder_shape_raw,'Expected initial standard holder shape differs')
            confirm,native=observe('confirm_before');require(confirm==before,'Two initial captures must agree')
            report['before']=before;current=before
            digest=single._digest(dict(scope=SCOPE,request=c,file_pins=pins,state=before));report['state_sha256']=digest
            if action=='apply':
                require(digest==expected_state_sha256,'Prepared source/recipe/state changed')
                for method,value in [('SetTurnHolderSTLFile',holder_stl_path),('SetTurnHolderSTLFileUnit',holder_file_unit_raw)]:
                    require(identity()==current['document'],'Document changed before setter')
                    step=dict(method=method,argument=value,intent_persisted=False,returned=False);report['setters'].append(step)
                    def pending():
                        nonlocal claimed,native
                        if not claimed:
                            _write_receipt(marker,dict(scope=SCOPE,status='claimed_no_replay',file_identity=identity_pin,tool_native_id=expected_tool_native_id,state_sha256=digest,receipt_path=str(receipt)),create=True);claimed=True
                        report.update(phase=method,mutation_attempted=True,native_dispatch_pending=True);step['intent_persisted']=True;persist()
                        fresh,native=observe('dispatch_guard_'+method);require(fresh==current,'Complete state changed after durable intent')
                        require(_object_id(native['native_doc'],native['operation'],read)==expected_operation_native_id and _object_id(native['native_doc'],native['tool'],read)==expected_tool_native_id,'Fresh retained identity changed')
                    dispatch=ScopedCamDispatchGuard(sw,typelib_path,process_id=process_id,expected_document=current['document'],source_sha256=expected_source_sha256,
                            evidence_pins=[dict(path=holder_stl_path,sha256=holder_stl_sha256)],verify_evidence=lambda:require(files()==pins,'Pinned files changed'),
                            verify_owned_process=lambda:policy.isolated(sw,c,check),check_events=check)
                    try:
                        with dispatch:
                            returned=dispatch.dispatch_once(lambda:_member(native['turn_tool'],method,value),persist_pending=pending)
                    finally:report['guards'].append(dispatch.summary())
                    step.update(returned=True,return_type=type(returned).__name__);report.update(native_dispatch_pending=False,native_calls_returned_count=report['native_calls_returned_count']+1);persist();check()
                    # HRESULT-only 方法没有布尔 OUT；正常返回 None 只证明调用已返回，不证明几何正确。
                    current,native=observe('after_'+method);verify_change(before,current,c,final=method=='SetTurnHolderSTLFileUnit')
                    step['file_fields_readback_verified']=True;persist()
                confirm,_=observe('confirm_after');require(confirm==current,'Two final captures must agree');verify_change(before,confirm,c,final=True);current=confirm
            report['after']=current;require(identity()==current['document'],'Final identity changed');check()
        messages=session.summary();report['messages']=messages
        require(messages.get('subscribed') is True and messages.get('disconnected') is True and messages.get('active') is False and not any(messages.get(k) for k in policy.EVENT_ERRORS),'Event cleanup uncertain')
        require(document_snapshot(sw)==current['document'] and files()==pins,'Post-cleanup document/files changed');policy.isolated(sw,c,lambda:None)
        report.update(status='prepared' if action=='prepare' else 'review_required',phase='finished',apply_eligible=action=='prepare',readback_verified=action=='apply',
            final_state_sha256=single._digest(current),reason='HOLDER_FILE_DEFINITION_ONLY_GEOMETRY_SCALE_FRAME_AND_PERSISTENCE_REQUIRE_SEPARATE_QUALIFICATION')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',readback_verified=False,apply_eligible=False,issue=_error(exc))
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',readback_verified=False,apply_eligible=False,receipt_write_error=_error(exc))
    return report
