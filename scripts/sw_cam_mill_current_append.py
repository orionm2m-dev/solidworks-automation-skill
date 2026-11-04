"""既有 MILL append 入口的当前保存模式；只追加一个已观察复合特征的定义。"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_mill_current_compound_read as current
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_append_evidence import attempt_marker
from scripts.sw_cam_mill_append_operations import exact_target
from scripts.sw_cam_mill_append_delta import verify_added_plan
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_guide_group_reader import read_catalogues
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import absolute_document_path, check_document_target, solidworks_operation_lock

SCOPE='MILL_CURRENT_SAVED_APPEND_V1'
READ_KEYS=('process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
    'expected_feature_native_id','expected_feature_setup_native_id','expected_operation_setup_native_id',
    'expected_operation_native_ids','expected_generated_operation_count','expected_total_record_count',
    'read_mode','observation','qualification_only','message_policy')
PIN_PAIRS=(('current_read_request_path','current_read_request_sha256'),('current_read_receipt_path','current_read_receipt_sha256'))


def require(value,message):
    if not value:raise ValueError(message)


def qualified_read(v,clsid=None):
    """固定真实 request/result 两文件；旧结果不补造缺失的身份字段。"""
    request,rpin=read_pin(v['current_read_request_path'],v['current_read_request_sha256'])
    result,dpin=read_pin(v['current_read_receipt_path'],v['current_read_receipt_sha256'])
    rows=[x for x in request.get('requests',[]) if x.get('name')=='solidworks_cam_inspect_current_saved_compound']
    require(len(rows)==1,'Exactly one pinned current-read request required')
    args=rows[0]['arguments']['params']
    require(all(args.get(k)==v[k] and type(args.get(k)) is type(v[k]) for k in READ_KEYS),'Pinned read request identity/scope differs')
    if clsid is not None:require(args.get('addin_clsid')==clsid,'Pinned read add-in differs')
    rows=[x for x in result.get('results',[]) if x.get('name')=='solidworks_cam_inspect_current_saved_compound']
    require(len(rows)==1 and rows[0]['result'].get('isError') is False,'Exactly one successful native result required')
    blocks=[x['parsed_json'] for x in rows[0]['result'].get('content',[]) if type(x.get('parsed_json')) is dict]
    require(len(blocks)==1,'One complete parsed current-read result required')
    data=blocks[0]
    require(data.get('scope')=='MILL_CURRENT_SAVED_COMPOUND_READ_V1' and data.get('status')=='review_required' and data.get('phase')=='finished','Completed current-read scope required')
    for k in ('read_only','readback_verified','observation_verified','guards_verified','runtime_unchanged'):require(data.get(k) is True,'Verified read flag required: '+k)
    for k in ('mutation_attempted','GOP_attempted','GTP_attempted','AFR_attempted','model_saved','post_cleanup_cam_read_performed'):require(data.get(k) is False,'Unexpected read flag: '+k)
    require(not any(k in data for k in ('issue','failed_phase','runtime_error','receipt_write_error')),'Failed read cannot authorize planning')
    clean_events(data)
    state=data.get('before');require(type(state) is dict and state==data.get('after') and state.get('capture_complete') is True,'Two complete equal prior captures required')
    require(data.get('observation')=='three_step_profile' and state.get('number_of_steps_raw')==3 and state.get('profile',{}).get('complete_step_coverage') is True,'Complete three-step proof required')
    require(state['target_header']['native_id']==v['expected_feature_native_id'] and state['selected_operation_setup']==dict(native_id=v['expected_operation_setup_native_id'],feature_setup_native_id=v['expected_feature_setup_native_id'],operation_count=0),'Exact target and empty operation setup required')
    check_document_target(data['document']['path'],data['document']['title'],expected_path=v['expected_document_path'],required=True)
    require(data['document'].get('needs_save') is False,'Saved read must be clean')
    return deepcopy(state),dict(request=rpin,result=dpin)


def binding(v):
    return {k:deepcopy(v[k]) for k in READ_KEYS+tuple(x for pair in PIN_PAIRS for x in pair)}


def validate(v):
    """校验 prepare/apply、真实双文件证据与独立独占 dispatch marker。"""
    current.validate(v)
    require(v['planning_mode']=='current_saved' and v['action'] in ('prepare','apply') and v['observation']=='three_step_profile','Explicit current-saved three-step append mode required')
    require(type(v['save_after_verified']) is bool and v['acknowledge_disposable_copy'] is True,'Strict save choice and qualification acknowledgement required')
    require(v['action']=='apply' or v['save_after_verified'] is False,'Prepare is read-only and cannot request Save')
    receipt=Path(v['receipt_path'])
    require(type(v['receipt_path']) is str and absolute_document_path(v['receipt_path']) and receipt.suffix.casefold()=='.json' and receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),'Unique output JSON required')
    state,pins=qualified_read(v)
    marker=attempt_marker(v['attempt_registry_path'],v['expected_document_path'],v['expected_source_sha256'],v['expected_feature_native_id'])
    require(not marker.exists() and not marker.is_symlink(),'Prior attempt exists; inspect outcome, never replay')
    paths=[Path(v[k]).resolve() for k,_ in PIN_PAIRS]+[receipt.resolve(),marker.resolve()]
    require(len(paths)==len(set(paths)),'Distinct input/output/marker paths required')
    if v['action']=='prepare':
        require(v['prepare_receipt_path'] is None and v['prepare_receipt_sha256'] is None,'Prepare cannot consume another prepare')
    else:
        require(type(v['expected_strategy_id']) is int and -(2**31)<=v['expected_strategy_id']<2**31 and type(v['expected_strategy_name']) is str and 1<=len(v['expected_strategy_name'])<=4096,'Apply requires reviewed actual strategy ID/name')
        prep,_=read_pin(v['prepare_receipt_path'],v['prepare_receipt_sha256'])
        require(Path(v['prepare_receipt_path']).resolve() not in paths,'Prepare must remain immutable')
        require(prep.get('scope')==SCOPE and prep.get('action')=='prepare' and prep.get('status')=='review_required' and prep.get('readback_verified') is True and prep.get('runtime_unchanged') is True and prep.get('mutation_attempted') is False and prep.get('binding')==binding(v),'Exact successful prepared current binding required')
        require(prep.get('before')==prep.get('confirm_before') and prep.get('state_sha256')==_digest(prep['before']),'Stable prepared state required')
        clean_events(prep)
    return marker,state,pins


def gop_abi(tlb):
    """检查 HRESULT-only GenerateOpPlan(IN LONG)；None 不解释为布尔失败。"""
    from ctypes import HRESULT,c_long
    cls=current._interface_class('ICWFeature',tlb)
    rows=[m for m in cls._methods_ if m.name=='GenerateOpPlan']
    require(str(cls._iid_).upper()=='{682686E4-3685-11D6-A9AA-00062999E55F}' and len(rows)==1,'Exact feature interface required')
    method=rows[0]
    require(method.restype is HRESULT and method.idlflags[0]==3 and method.argtypes==(c_long,) and tuple(p[0] for p in method.paramflags)==(1,) and not any(x in method.idlflags for x in ('propget','propput','propputref')),'Exact HRESULT-only GOP ABI required')


def save_abi(tlb):
    """固定 ICWApp.SaveActiveDocument 的无参数 HRESULT ABI；保留已验证的 int0 返回契约。"""
    from ctypes import HRESULT
    cls=current._interface_class('ICWApp',tlb)
    rows=[m for m in cls._methods_ if m.name=='SaveActiveDocument']
    require(str(cls._iid_).upper()=='{6015E884-0B0D-11D6-A982-00062999E55F}' and len(rows)==1,'Exact Save interface required')
    method=rows[0]
    require(method.restype is HRESULT and method.idlflags[0]==12 and method.argtypes==() and method.paramflags==() and not any(x in method.idlflags for x in ('propget','propput','propputref')),'Exact no-argument HRESULT-only Save ABI required')


def runtime_drift(report,error):
    """撤销成功并持久保存已返回结果；不再读取 CAM 或隐式回滚。"""
    report.update(status='uncertain' if report.get('mutation_attempted') else 'error',readback_verified=False,operation_delta_verified=False,may_apply=False,runtime_unchanged=False,save_readback_verified=False,model_saved=False,source_update_verified=False,reason='RUNTIME_CHANGED_AFTER_CALL',runtime_error=str(error))
    try:
        if report.get('receipt_created') is True:_write_receipt(Path(report['receipt_path']),report)
        if report.get('marker_created') is True:_write_receipt(Path(report['dispatch_marker_path']),dict(scope=SCOPE,status=report['status'],receipt_path=report['receipt_path'],receipt_sha256=_file_hash(report['receipt_path']),automatic_replay=False))
    except Exception as exc:report['receipt_write_error']=_error(exc)
    return report


def run_current_saved_append(sw,clsid,typelib_path,*,runtime_check,**v):
    """只准备或执行一次 RETAIN GOP；可在完整增量验证后保存，不生成轨迹。"""
    report=dict(scope=SCOPE,status='error',phase='validation',action=v['action'],binding=binding(v),
        mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
        GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,model_saved=False,save_attempted=False,
        save_after_verified=v['save_after_verified'],save_call_returned=False,save_readback_verified=False,
        save_hresult=None,source_update_verified=False,reopen_persistence_verified=False,
        source_before_sha256=v['expected_source_sha256'],
        strategy_assignment_attempted=False,tool_assignment_attempted=False,automatic_replay=False,automatic_rollback=False,
        readback_verified=False,operation_delta_verified=False,may_apply=False,production_qualified=False,
        full_hidden_geometry_preservation_verified=False,cl_coordinates_compared=False,world_geometry_verified=False,
        receipt_created=False,marker_created=False,runtime_unchanged=False,receipt_path=v['receipt_path'],captures=[],step_getter_diagnostics=[])
    session=None;marker=None;current_source=v['expected_source_sha256']
    def persist():
        if report['receipt_created']:_write_receipt(Path(v['receipt_path']),report)
    try:
        marker,reference,pins=validate(v);qualified_read(v,clsid);current._abi(typelib_path);gop_abi(typelib_path)
        if v['save_after_verified']:save_abi(typelib_path)
        report.update(dispatch_marker_path=str(marker),qualified_read_pins=pins)
        _write_receipt(Path(v['receipt_path']),report,create=True);report['receipt_created']=True;persist()
        def identity(*,verify_source=True):
            process=_process_identity(v['process_id'])
            require(process.get('alive') is True and process.get('process_id')==v['process_id'] and process.get('create_time')==v['expected_process_create_time'] and Path(process.get('executable','')).name.casefold()=='sldworks.exe','Exact process lifetime changed')
            pid=_member(sw,'GetProcessID');require(type(pid) is int and pid==v['process_id'],'PID changed')
            doc=document_snapshot(sw);require(type(doc) is dict and type(doc.get('type')) is int and doc['type']==1 and type(doc.get('needs_save')) is bool,'Saved part required')
            check_document_target(doc['path'],doc['title'],expected_path=v['expected_document_path'],required=True)
            if verify_source:require(_file_hash(v['expected_document_path'])==current_source,'Source file changed')
            for (pathkey,shakey),expected in zip(PIN_PAIRS,(pins['request'],pins['result'])):require(read_pin(v[pathkey],v[shakey])[1]==expected,'Pinned read evidence changed')
            return doc
        with solidworks_operation_lock(timeout_seconds=1,process_id=v['process_id']):
            initial=identity();require(initial['needs_save'] is False,'Prepare/apply must start from clean saved source')
            addin=_member(sw,'GetAddInObject',clsid);require(addin is not None,'CAM must already be loaded')
            app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path);require(identity()==initial,'Bootstrap identity changed')
            session=CamMessageSession(app,typelib_path)
            def check():
                s=session.summary();report['messages']=s
                require(s.get('active') is True and s.get('subscribed') is True and not any(s.get(k) for k in current._EVENT_ERRORS),'CAM event transport requires stop')
            reads=0
            def read(obj,name,*args):
                nonlocal reads
                check();reads+=1;require(reads<=10000,'Bounded read budget exceeded');report['phase']=name
                diagnostic=None
                if name in current._STEP_GETTERS:
                    diagnostic=dict(method=name,arguments=list(args),returned=False);report['step_getter_diagnostics'].append(diagnostic)
                raw=_member(obj,name,*args)
                if diagnostic is not None:diagnostic.update(returned=True,converted_output_shape=current._converted_shape(raw))
                check();return raw
            def typed(raw,name):
                check();result=_typed(raw,name,typelib_path);check();require(result is not None,'Declared interface missing');return result
            def capture(label,after=False):
                check();report['phase']=label;state={};report[label]=state;report['captures'].append(label);persist()
                start=identity()
                if not after:require(start==initial,'Pre-dispatch document changed')
                def boundary():
                    check();require(identity()==start,'Identity changed during capture');check()
                native=current._capture(app,typelib_path,read,typed,state,v,boundary,verify_operation_pins=not after)
                if not after:require(state==reference,'Current captured state differs from qualified read')
                state['document']=deepcopy(start)
                strategy_state=deepcopy(state)
                for row in strategy_state['features']:
                    if row['geometry']['native_id']==v['expected_feature_native_id']:row['geometry']=deepcopy(state['target_header'])
                details={};state['strategy_diagnostics']=details
                read_compound_strategy(strategy_state,native,read,typed,details,feature_id=v['expected_feature_native_id'],owner_id=v['expected_feature_setup_native_id'],step_count=3,expected_header=state['target_header'],boundary=boundary,observation='strategy')
                state['default_operation_catalogues']=read_catalogues(native['selected_feature'],read=read,typed=typed)
                boundary();persist();return state,native
            with session:
                before,native=capture('before');confirm,native=capture('confirm_before')
                require(before==confirm,'Two complete prepare captures differ')
                require(len(before['operations'])<32 and before['selected_operation_setup']['operation_count']==0 and not any(v['expected_feature_native_id'] in row['linked_feature_ids'] for row in before['operations']),'Target must be unplanned in empty setup with capacity')
                report['state_sha256']=_digest(before)
                strategy=before['strategy_diagnostics']['compound_strategy'];report['selected_strategy']=deepcopy(strategy);report['default_operation_catalogues']=deepcopy(before['default_operation_catalogues']);persist()
                final=confirm
                if v['action']=='apply':
                    prep,ppin=read_pin(v['prepare_receipt_path'],v['prepare_receipt_sha256']);require(prep['before']==before,'Fresh state differs from reviewed prepare')
                    require(strategy['attribute_id']==v['expected_strategy_id'] and strategy['attribute_name']==v['expected_strategy_name'],'Reviewed strategy differs')
                    feature=exact_target(native,{'header':before['target_header']},v['expected_feature_native_id'],v['expected_feature_setup_native_id'],read,typed)
                    check();require(identity()==initial,'Identity changed before claim');runtime_check();require(read_pin(v['prepare_receipt_path'],v['prepare_receipt_sha256'])[1]==ppin,'Prepare pin changed')
                    _write_receipt(marker,dict(scope=SCOPE,status='claimed_no_replay',binding=binding(v),receipt_path=v['receipt_path'],automatic_replay=False),create=True);report['marker_created']=True;persist()
                    check();require(identity()==initial,'Identity changed after exclusive claim');runtime_check()
                    report.update(phase='GenerateOpPlan',mutation_attempted=True,GOP_attempted=True,native_call_attempted=True,native_dispatch_pending=True);persist()
                    returned=_member(feature,'GenerateOpPlan',1)
                    report.update(native_call_returned=True,native_dispatch_pending=False,native_return_type=type(returned).__name__,native_hresult=returned if type(returned) is int else None);persist();check()
                    require(returned is None or (type(returned) is int and returned==0),'Unexpected HRESULT-only return; no replay')
                    after,_=capture('after',True);report['new_operations']=verify_added_plan(before,after,v['expected_feature_native_id'],v['expected_operation_setup_native_id'],current_saved=True);persist()
                    final,_=capture('confirm_after',True);require(final==after,'Two post-plan captures differ');verify_added_plan(before,final,v['expected_feature_native_id'],v['expected_operation_setup_native_id'],current_saved=True)
                    report['operation_delta_verified']=True
                    if v['save_after_verified']:
                        check();runtime_check();require(identity()==final['document'],'Identity changed before verified Save')
                        target_app=typed(app,'ICWApp')
                        report.update(phase='SaveActiveDocument',save_attempted=True,native_dispatch_pending=True,
                            observed_needs_save_before=final['document']['needs_save']);persist()
                        check();require(identity()==final['document'],'Identity changed immediately before Save');runtime_check()
                        returned=_member(target_app,'SaveActiveDocument')
                        report.update(save_call_returned=True,native_dispatch_pending=False,
                            save_return_type=type(returned).__name__,save_hresult=returned if type(returned) is int else None,
                            save_return_value=returned if type(returned) in (int,bool,str,float,type(None)) else None);persist()
                        check();runtime_check()
                        require(type(returned) is int and returned==0,'Unexpected Save return; outcome unknown, no replay')
                        observed_source=_file_hash(v['expected_document_path'])
                        report['source_after_sha256']=observed_source;persist()
                        identity(verify_source=False);check()
                        require(_file_hash(v['expected_document_path'])==observed_source,'Source changed during Save boundary')
                        current_source=observed_source
                        saved,_=capture('saved',True)
                        report['observed_needs_save_after']=saved['document']['needs_save'];persist()
                        expected_saved=deepcopy(final);expected_saved['document']['needs_save']=False
                        require(saved==expected_saved,'Save changed captured CAM state')
                        require(saved['document']['needs_save'] is False,'Save left document dirty')
                        confirm_saved,_=capture('confirm_saved',True)
                        require(confirm_saved==saved,'Two saved captures differ')
                        final=confirm_saved
                        report.update(save_readback_verified=True,model_saved=True,source_update_verified=True,
                            saved_file_sha256=current_source,source_hash_changed=current_source!=v['expected_source_sha256']);persist()
                check()
            clean_events(dict(messages=session.summary()));require(identity()==final['document'],'Identity changed after cleanup')
            report.update(status='review_required',phase='finished',readback_verified=True,may_apply=v['action']=='prepare',reason='CAPTURED_DEFINITIONS_SAVED_NO_GTP_NO_MACHINING_QUALIFICATION' if report['model_saved'] else 'CAPTURED_ONLY_DEFINITIONS_NO_GTP_NO_SAVE_NO_MACHINING_QUALIFICATION')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,operation_delta_verified=False,may_apply=False,save_readback_verified=False,model_saved=False,source_update_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:
            persist()
            if report['marker_created']:_write_receipt(marker,dict(scope=SCOPE,status=report['status'],receipt_path=v['receipt_path'],receipt_sha256=_file_hash(v['receipt_path']),automatic_replay=False))
        except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',receipt_write_error=_error(exc),readback_verified=False,operation_delta_verified=False,may_apply=False,save_readback_verified=False,model_saved=False,source_update_verified=False)
    return report


def runtime_complete(report):
    """包装器校验代码未变后才固定该标志；未完成包装器校验的 prepare 不可 apply。"""
    report['runtime_unchanged']=True
    try:
        if report.get('receipt_created') is True:_write_receipt(Path(report['receipt_path']),report)
        if report.get('marker_created') is True:_write_receipt(Path(report['dispatch_marker_path']),dict(scope=SCOPE,status=report['status'],receipt_path=report['receipt_path'],receipt_sha256=_file_hash(report['receipt_path']),automatic_replay=False))
    except Exception as exc:
        report.update(status='uncertain' if report.get('mutation_attempted') else 'error',receipt_write_error=_error(exc),readback_verified=False,operation_delta_verified=False,may_apply=False,save_readback_verified=False,model_saved=False,source_update_verified=False)
    return report
