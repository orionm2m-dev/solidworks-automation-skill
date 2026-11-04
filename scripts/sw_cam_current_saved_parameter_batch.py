"""当前保存的 MILL 参数批次；复用已验证读取、固定 setter、一次调度和保存。"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_current_saved_parameter_fields as fields
from scripts import sw_cam_current_parameter_capture as capture_core
from scripts import sw_cam_mill_current_compound_read as current
from scripts import sw_cam_mill_current_parameters as parameters
from scripts import sw_cam_mill_current_append as append
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_append_evidence import attempt_marker
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_guide_group_reader import read_catalogues
from scripts.sw_cam_guide_group_definitions import read_own_nc
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import absolute_document_path, check_document_target, solidworks_operation_lock

SCOPE='MILL_CURRENT_SAVED_PARAMETER_BATCH_V1'
READ_KEYS=append.READ_KEYS+parameters.FIELDS
EXTRA=('candidate_tool_native_id','expected_candidate_consumer_ids','current_read_request_path','current_read_request_sha256','current_read_receipt_path','current_read_receipt_sha256','recipe_path','recipe_sha256')
PAIRS=(('current_read_request_path','current_read_request_sha256'),('current_read_receipt_path','current_read_receipt_sha256'),('parameters_authority_receipt_path','parameters_authority_receipt_sha256'),('recipe_path','recipe_sha256'))
RECOVERY_KEYS=('partial_receipt_path','partial_receipt_sha256','partial_attempt_marker_path','partial_attempt_marker_sha256','original_apply_request_path','original_apply_request_sha256')
RECOVERY_ACTIONS=('prepare_recover_save','recover_save')
require=fields.require

def binding(v):
    return {k:deepcopy(v[k]) for k in READ_KEYS+EXTRA}

def load_inputs(v,clsid=None):
    """绑定真实参数读取 request/result 和完成保存的定义证据；不伪造历史。"""
    request,rpin=read_pin(v['current_read_request_path'],v['current_read_request_sha256'])
    result,dpin=read_pin(v['current_read_receipt_path'],v['current_read_receipt_sha256'])
    rows=[x for x in request.get('requests',[]) if x.get('name')=='solidworks_cam_inspect_current_saved_compound']
    require(len(rows)==1,'One pinned parameter request required');args=rows[0]['arguments']['params']
    require(all(fields.equal(args.get(k),v[k]) for k in READ_KEYS),'Pinned parameter request binding differs')
    if clsid is not None:require(args.get('addin_clsid')==clsid,'Pinned add-in differs')
    rows=[x for x in result.get('results',[]) if x.get('name')=='solidworks_cam_inspect_current_saved_compound']
    require(len(rows)==1 and rows[0]['result'].get('isError') is False,'One successful actual parameter result required')
    blocks=[x['parsed_json'] for x in rows[0]['result'].get('content',[]) if type(x.get('parsed_json')) is dict]
    require(len(blocks)==1,'One complete parsed parameter result required');d=blocks[0]
    require(d.get('scope')=='MILL_CURRENT_SAVED_COMPOUND_READ_V1' and d.get('status')=='review_required' and d.get('phase')=='finished' and d.get('observation')=='operation_parameters','Completed parameter observation required')
    for key in ('read_only','readback_verified','observation_verified','guards_verified','runtime_unchanged','parameter_observations_verified'):require(d.get(key) is True,'Unverified parameter read: '+key)
    for key in ('mutation_attempted','GOP_attempted','GTP_attempted','AFR_attempted','model_saved','post_cleanup_cam_read_performed'):require(d.get(key) is False,'Unexpected read side effect: '+key)
    require(not any(k in d for k in ('issue','failed_phase','runtime_error','receipt_write_error')),'Failed parameter read rejected');clean_events(d)
    baseline=d.get('before');require(type(baseline) is dict and fields.equal(baseline,d.get('after')) and baseline.get('capture_complete') is True and baseline.get('parameter_capture_complete') is True,'Two equal complete parameter states required')
    authority=parameters.load_authority(v)
    projected=deepcopy(baseline)
    projected.pop('operation_parameters');projected.pop('parameter_capture_complete')
    require(fields.equal(projected,authority['state']),'Parameter read differs from actual saved definition authority')
    recipe,recipepin=read_pin(v['recipe_path'],v['recipe_sha256']);plan=fields.compile_plan(baseline,recipe)
    require(all(r['operation_native_id'] in v['parameter_operation_native_ids'] and r['feature_native_id']==v['expected_feature_native_id'] for r in plan['rows']),'Recipe outside observed feature pair')
    require(all(r['existing_tool_native_id'] in (None,v['candidate_tool_native_id']) for r in plan['rows']),'Only the explicit existing candidate is permitted')
    usage=[r['native_id'] for r in baseline['operations'] if r['assigned_tool']['native_id']==v['candidate_tool_native_id']]
    require(fields.equal(usage,v['expected_candidate_consumer_ids']),'Pinned candidate usage differs')
    return dict(baseline=deepcopy(baseline),authority=authority,plan=plan,pins=dict(request=rpin,result=dpin,authority=authority['pin'],recipe=recipepin))


def recovery_binding(v):
    return {k:deepcopy(v[k]) for k in RECOVERY_KEYS}

def load_recovery(v,data):
    """固定原始 partial、已消费 marker、实际 apply 请求与其 prepare；不改写旧证据。"""
    from scripts.sw_cam_current_parameter_recovery_evidence import validate_history
    partial,ppin=read_pin(v['partial_receipt_path'],v['partial_receipt_sha256'])
    old_marker,mpin=read_pin(v['partial_attempt_marker_path'],v['partial_attempt_marker_sha256'])
    request,rpin=read_pin(v['original_apply_request_path'],v['original_apply_request_sha256'])
    rows=[x for x in request.get('requests',[]) if x.get('name')=='solidworks_cam_configure_guide_definitions']
    require(len(rows)==1,'One immutable original apply request required');args=rows[0]['arguments']['params']
    original_prepare,prep_pin=read_pin(args['prepare_receipt_path'],args['prepare_receipt_sha256'])
    pins=dict(partial=ppin,old_marker=mpin,original_request=rpin,original_prepare=prep_pin)
    info=validate_history(partial,original_prepare,request,old_marker,base_binding=binding(v),plan=data['plan'],baseline=data['baseline'],pins=pins)
    directory=Path(v['attempt_registry_path'])
    require(directory.is_dir() and not directory.is_symlink() and directory.resolve()==Path(mpin['path']).parent.resolve(),'Recovery must retain the original attempt registry')
    marker=directory/('parameter_recover_save_'+_digest(dict(scope=SCOPE,document=str(Path(v['expected_document_path']).resolve()).casefold(),source_sha256=v['expected_source_sha256'],feature_id=v['expected_feature_native_id'],partial_sha256=ppin['sha256']))+'.json')
    return marker,info,pins

def validate(v,clsid=None):
    current.validate(v)
    require(v['configuration_mode']=='current_saved' and v['observation']=='operation_parameters' and v['action'] in ('prepare','apply',*RECOVERY_ACTIONS),'Explicit current-saved parameter mode required')
    require(type(v['candidate_tool_native_id']) is int and 0<v['candidate_tool_native_id']<2**32,'Strict existing candidate ID required')
    ids=v['expected_candidate_consumer_ids'];require(type(ids) is list and len(ids)<=32 and all(type(i) is int and 0<i<2**32 for i in ids) and len(set(ids))==len(ids),'Strict ordered candidate consumers required')
    recovering=v['action'] in RECOVERY_ACTIONS
    if not recovering:require(all(v.get(k) is None for k in RECOVERY_KEYS),'Recovery pins require explicit recovery action')
    else:require(all(type(v.get(k)) is str and v[k] for k in RECOVERY_KEYS) and v['save_after_verified'] is (v['action']=='recover_save'),'Explicit Save-only recovery choice and pins required')
    require(type(v['save_after_verified']) is bool and (v['action'] in ('apply','recover_save') or not v['save_after_verified']) and v['acknowledge_qualification_only'] is True,'Explicit qualification/Save choice required')
    path=Path(v['receipt_path']);require(absolute_document_path(str(path)) and path.suffix.casefold()=='.json' and path.parent.is_dir() and not path.exists() and not path.is_symlink(),'Unique absolute output receipt required')
    data=load_inputs(v,clsid)
    if recovering:
        marker,info,pins=load_recovery(v,data);data.update(recovery=info,recovery_pins=pins)
    else:marker=attempt_marker(v['attempt_registry_path'],v['expected_document_path'],v['expected_source_sha256'],v['expected_feature_native_id'])
    require(not marker.exists() and not marker.is_symlink(),'Prior source/feature attempt exists; inspect, never replay')
    paths=[Path(v[k]).resolve() for k,_ in PAIRS]+[path.resolve(),marker.resolve(),Path(v['expected_document_path']).resolve()]+[Path(pin['path']).resolve() for pin in data.get('recovery_pins',{}).values()]
    require(len(paths)==len(set(paths)),'Distinct immutable input/output/source paths required')
    if v['action'] in ('prepare','prepare_recover_save'):require(v['prepare_receipt_path'] is None and v['prepare_receipt_sha256'] is None,'Prepare cannot consume a prepare')
    else:
        prep,pin=read_pin(v['prepare_receipt_path'],v['prepare_receipt_sha256'])
        require(Path(v['prepare_receipt_path']).resolve() not in paths,'Prepare must remain immutable')
        require(prep.get('scope')==SCOPE and prep.get('action')==('prepare_recover_save' if recovering else 'prepare') and prep.get('status')=='review_required' and prep.get('phase')=='finished' and prep.get('readback_verified') is True and prep.get('runtime_unchanged') is True and prep.get('mutation_attempted') is False and fields.equal(prep.get('binding'),binding(v)),'Exact completed reviewed prepare required')
        require(fields.equal(prep['before'],prep['confirm_before']) and prep['state_sha256']==_digest(prep['before']),'Stable prepare required');clean_events(prep)
        if recovering:require(prep.get('recovery_verified') is True and fields.equal(prep.get('recovery_binding'),recovery_binding(v)),'Exact reviewed recovery preparation required')
        data.update(prepare=prep,prepare_pin=pin)
    return marker,data

class NativeBatchContext:
    """同一 mutex/event 生命周期中的有界读取；对象句柄不跨会话保存。"""
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        self.sw,self.clsid,self.tlb,self.v,self.data,self.report,self.persist,self.runtime_check=sw,clsid,tlb,v,data,report,persist,runtime_check
        self.source=v['expected_source_sha256'];self.session=None;self.native=None;self.initial=None
    def verify_files(self):
        for (pathkey,shakey),pin in zip(PAIRS,self.data['pins'].values()):require(read_pin(self.v[pathkey],self.v[shakey])[1]==pin,'Immutable parameter evidence changed')
        for pin in self.data.get('recovery_pins',{}).values():require(read_pin(pin['path'],pin['sha256'])[1]==pin,'Immutable recovery history changed')
        if 'prepare_pin' in self.data:require(read_pin(self.v['prepare_receipt_path'],self.v['prepare_receipt_sha256'])[1]==self.data['prepare_pin'],'Prepare evidence changed')
    def identity(self,verify_source=True):
        v=self.v;p=_process_identity(v['process_id'])
        require(p.get('alive') is True and p.get('process_id')==v['process_id'] and p.get('create_time')==v['expected_process_create_time'] and Path(p.get('executable','')).name.casefold()=='sldworks.exe','Exact process lifetime changed')
        pid=_member(self.sw,'GetProcessID');require(type(pid) is int and pid==v['process_id'],'PID changed')
        d=document_snapshot(self.sw);require(type(d) is dict and type(d.get('type')) is int and d['type']==1 and type(d.get('needs_save')) is bool,'Strict current part identity required')
        check_document_target(d['path'],d['title'],expected_path=v['expected_document_path'],required=True)
        if verify_source:require(_file_hash(v['expected_document_path'])==self.source,'Saved source changed')
        self.verify_files();return d
    def check(self):
        s=self.session.summary();self.report['messages']=s
        require(s.get('active') is True and s.get('subscribed') is True and not any(s.get(k) for k in current._EVENT_ERRORS),'CAM event requires stop')
    def boundary(self):
        self.check();d=self.identity();self.runtime_check();self.check();return d
    def read(self,obj,name,*args):
        self.check();self.report['phase']=name;self.report['native_read_count']+=1
        require(self.report['native_read_count']<=24000,'Bounded read budget exceeded')
        value=_member(obj,name,*args)
        last=dict(method=name,returned=True,converted_output_shape=current._converted_shape(value))
        try:last['raw']=parameters.pocket.rough.bounded_raw_observation(value)
        except ValueError:pass
        self.report['last_returned_read']=last
        diag=self.report.get('active_field_read')
        if diag is not None:
            diag.update(returned=True,converted_output_shape=current._converted_shape(value))
            try:diag['raw']=parameters.pocket.rough.bounded_raw_observation(value)
            except ValueError:pass
            self.persist()
        self.check();return value
    def typed(self,raw,name):
        self.check();value=_typed(raw,name,self.tlb);self.check();require(value is not None,'Declared interface missing');return value
    def __enter__(self):
        self.lock=solidworks_operation_lock(timeout_seconds=1,process_id=self.v['process_id']);self.lock.__enter__()
        try:
            self.initial=self.identity()
            if 'recovery' in self.data:require(fields.equal(self.initial,self.data['recovery']['expected_state']['document']),'Recovery document differs from exact recorded CAM delta')
            else:require(self.initial['needs_save'] is False,'Clean saved initial source required')
            addin=_member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM must already be loaded')
            self.app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.tlb)
            require(self.identity()==self.initial,'Identity changed during bootstrap')
            self.session=CamMessageSession(self.app,self.tlb);self.session.__enter__();return self
        except BaseException:
            failure=__import__('sys').exc_info()
            try:
                if self.session is not None:self.session.__exit__(*failure)
            finally:self.lock.__exit__(*failure)
            raise
    def __exit__(self,*exc):
        try:
            if self.session is not None:self.session.__exit__(*exc)
        finally:self.lock.__exit__(*exc)
    def capture(self,label,consumer_ids):
        state={};self.report[label]=state;self.report['captures'].append(label);self.persist();start=self.boundary()
        def boundary():require(self.boundary()==start,'Identity changed during full capture')
        try:
            self.native=current._capture(self.app,self.tlb,self.read,self.typed,state,self.v,boundary)
            state['document']=deepcopy(start);strategy=deepcopy(state)
            for row in strategy['features']:
                if row['geometry']['native_id']==self.v['expected_feature_native_id']:row['geometry']=deepcopy(state['target_header'])
            details={};state['strategy_diagnostics']=details
            read_compound_strategy(strategy,self.native,self.read,self.typed,details,feature_id=self.v['expected_feature_native_id'],owner_id=self.v['expected_feature_setup_native_id'],step_count=3,expected_header=state['target_header'],boundary=boundary,observation='strategy')
            state['default_operation_catalogues']=read_catalogues(self.native['selected_feature'],read=self.read,typed=self.typed)
            if self.data['authority']['definition_mode']=='selected_continue':
                oid=self.v['parameter_operation_native_ids'][0];out=dict(operation_native_id=oid,read_complete=False);state['retained_operation_nc']=out
                out['nc']=read_own_nc(self.native['operations'][oid],read=self.read,typed=self.typed);out['read_complete']=True
            targets=[next(r for r in state['operations'] if r['native_id']==oid) for oid in self.v['parameter_operation_native_ids']]
            capture_core.capture_parameter_batch(state,self.native,targets,feature_id=self.v['expected_feature_native_id'],candidate_tool_native_id=self.v['candidate_tool_native_id'],expected_candidate_consumer_ids=consumer_ids,read=self.read,typed=self.typed,boundary=boundary)
            boundary();return state
        finally:self.persist()
    def guard(self):
        expected=self.boundary()
        return ScopedCamDispatchGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=expected,source_sha256=self.source,evidence_pins=list(self.data['pins'].values())+list(self.data.get('recovery_pins',{}).values())+([self.data['prepare_pin']] if 'prepare_pin' in self.data else []),verify_evidence=self.verify_files,verify_owned_process=lambda:self.boundary(),check_events=self.check)
    def set_tool(self,row,candidate,pending,returned):
        from comtypes.automation import IDispatch
        with self.guard() as guard:
            op,_=fields.target(guard,self.native['doc'],row)
            old,_=capture_core.read_generic_tool(op,self.native['doc'],guard.read,guard.typed)
            require(old['native_id']==row['expected_tool_native_id'],'Immediate source tool changed')
            machine=guard.typed(guard.read(guard.typed(self.native['doc'],'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            crib=guard.typed(guard.read(machine,'IGetToolcrib'),'ICWToolcrib4')
            tools=capture_core._items(guard.read(crib,'GetAllTools'),guard.typed,guard.read,64)
            found=[x for x in tools if _object_id(self.native['doc'],x,guard.read)==candidate['generic']['native_id']]
            require(len(found)==1,'Exact existing candidate in bounded toolcrib required')
            generic,tool=capture_core.tool_generic(found[0],self.native['doc'],guard.read,guard.typed)
            require(fields.equal(capture_core.read_tool_dimensions(tool,generic,guard),candidate),'Candidate full dimensions changed')
            dispatch=guard.read(tool,'QueryInterface',IDispatch);mill=guard.typed(op,'ICWMillOperation')
            def invoke():
                value=_member(mill,'SetTool',dispatch);returned(value);require(type(value) is int and value==0,'Unexpected SetTool HRESULT; no replay');return value
            return guard.dispatch_once(invoke,persist_pending=pending)
    def set_field(self,row,change,pending,returned):
        return fields.write_field_once(self,self.native['doc'],row,change,pending=pending,returned=returned)
    def read_field(self,row,change,diagnostic):
        self.boundary();spec=fields.FIELDS[change['field']]
        op,feature=fields.target(self,self.native['doc'],row);owner=self.typed(op,'ICWRghMillOp');args=[]
        if spec.mode=='feature':
            from comtypes.automation import IDispatch
            args=[self.read(feature,'QueryInterface',IDispatch)]
        self.report['active_field_read']=diagnostic
        try:
            value=self.read(owner,spec.getter,*args);value=list(value) if type(value) is tuple else value
            fields.checked_value(spec,value);self.boundary();return value
        finally:self.report.pop('active_field_read',None);self.persist()
    def save(self,pending,returned):
        self.boundary();target=self.typed(self.app,'ICWApp');pending();self.boundary()
        value=_member(target,'SaveActiveDocument');returned(value);self.check();self.runtime_check()
        require(type(value) is int and value==0,'Unexpected Save HRESULT; no replay')
        observed=_file_hash(self.v['expected_document_path']);self.report['source_after_sha256']=observed;self.persist()
        self.identity(False);require(_file_hash(self.v['expected_document_path'])==observed,'Source changed at Save boundary');self.source=observed


def _revoke(report):
    report.update(status='uncertain' if report.get('mutation_attempted') else 'error',readback_verified=False,parameter_delta_verified=False,save_readback_verified=False,model_saved=False,source_update_verified=False,may_apply=False)

def runtime_finish(report,error=None):
    if error is not None:_revoke(report);report.update(runtime_unchanged=False,runtime_error=str(error))
    else:report['runtime_unchanged']=True
    try:
        if report.get('receipt_created'):_write_receipt(Path(report['receipt_path']),report)
        if report.get('marker_created'):_write_receipt(Path(report['dispatch_marker_path']),dict(scope=SCOPE,status=report['status'],receipt_path=report['receipt_path'],receipt_sha256=_file_hash(report['receipt_path']),automatic_replay=False))
    except Exception as exc:_revoke(report);report['receipt_write_error']=_error(exc)
    return report


def run_current_saved_configuration(sw,clsid,typelib_path,*,runtime_check,_context_factory=NativeBatchContext,**v):
    """显式参数批次：只准备，或工具屏障、逐字段回读、两次完整检查、一次保存。"""
    report=dict(scope=SCOPE,status='error',phase='validation',action=v['action'],binding=binding(v),request_pin=dict(kind='canonical_binding',sha256=_digest(binding(v))),recipe=None,
        mutation_attempted=False,native_dispatch_pending=False,GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,automatic_replay=False,automatic_rollback=False,
        readback_verified=False,parameter_delta_verified=False,model_saved=False,save_attempted=False,save_call_returned=False,save_hresult=None,save_readback_verified=False,source_update_verified=False,runtime_unchanged=False,may_apply=False,
        production_qualified=False,cutting_conditions_qualified=False,physical_tool_qualified=False,full_hidden_geometry_preservation_verified=False,cl_coordinates_compared=False,
        source_before_sha256=v['expected_source_sha256'],receipt_path=v['receipt_path'],receipt_created=False,marker_created=False,actions=[],captures=[],native_read_count=0)
    marker=None;ctx=None
    def persist():
        if report['receipt_created']:_write_receipt(Path(v['receipt_path']),report)
    def action(kind,row=None,change=None):
        out=dict(kind=kind,operation_native_id=row['operation_native_id'] if row else None,change=deepcopy(change),attempted=False,returned=False,native_dispatch_pending=False,readback_verified=False)
        report['actions'].append(out);persist()
        def pending():
            ctx.boundary();out.update(attempted=True,native_dispatch_pending=True);report.update(mutation_attempted=True,native_dispatch_pending=True,phase=kind);persist()
        def returned(value):
            out.update(returned=True,native_dispatch_pending=False,return_type=type(value).__name__,return_value=value if type(value) in (int,float,bool,str,type(None)) else None)
            report['native_dispatch_pending']=False;persist()
        return out,pending,returned
    try:
        marker,data=validate(v,clsid);report.update(dispatch_marker_path=str(marker),qualified_read_pins=data['pins'],recipe=deepcopy(data['plan']))
        recovering='recovery' in data
        if recovering:report.update(recovery_mode='recover_save',recovery_binding=recovery_binding(v),recovery_pins=deepcopy(data['recovery_pins']),original_action_receipt_pin=deepcopy(data['recovery_pins']['partial']),historical_before=deepcopy(data['recovery']['historical_before']),recovery_verified=False,setters_replayed=False)
        current._abi(typelib_path);parameters.preflight(typelib_path,data['authority']['definition_mode']);fields.preflight(typelib_path);append.save_abi(typelib_path)
        _write_receipt(Path(v['receipt_path']),report,create=True);report['receipt_created']=True;persist()
        ctx=_context_factory(sw,clsid,typelib_path,v,data,report,persist,runtime_check)
        with ctx:
            consumers=list(data['recovery']['consumer_ids'] if recovering else v['expected_candidate_consumer_ids']);before=ctx.capture('before',consumers);confirm=ctx.capture('confirm_before',consumers)
            require(fields.equal(before,confirm),'Two full prepare captures differ')
            if recovering:
                require(fields.equal(before,data['recovery']['expected_state']),'Fresh complete state differs from verified historical setter outcomes')
                fields.verify_final(data['recovery']['historical_before'],before,data['plan'],{v['candidate_tool_native_id']:before['parameter_batch']['candidate_tool']},observed_floor_alias=True)
                report['recovery_verified']=True
            else:
                reference=deepcopy(before);reference.pop('parameter_batch');require(fields.equal(reference,data['baseline']),'Fresh parameters differ from pinned actual read')
                fields.compile_plan(before,data['plan'])
            report['state_sha256']=_digest(before);persist();final=confirm
            candidate=deepcopy(before['parameter_batch']['candidate_tool']);candidates={v['candidate_tool_native_id']:candidate}
            if v['action'] in ('apply','recover_save'):
                require(fields.equal(data['prepare']['before'],before),'Fresh state differs from reviewed prepare')
                ctx.boundary();runtime_check();_write_receipt(marker,dict(scope=SCOPE,status='claimed_no_replay',binding=binding(v),receipt_path=v['receipt_path'],automatic_replay=False),create=True);report['marker_created']=True;persist();ctx.boundary();runtime_check()
                if recovering:
                    report['after']=deepcopy(before);report['confirm_after']=deepcopy(confirm);report['after_capture_references']=['before','confirm_before']
                else:
                    for row in data['plan']['rows']:
                        if row['existing_tool_native_id'] is not None:
                            out,pending,returned=action('SetTool',row)
                            ctx.set_tool(row,candidate,pending,returned)
                            consumers=[r['native_id'] for r in final['operations'] if r['assigned_tool']['native_id']==v['candidate_tool_native_id'] or r['native_id']==row['operation_native_id']]
                            observed=ctx.capture('after_tool_'+str(row['operation_native_id']),consumers)
                            fields.verify_assignment_delta(final,observed,row,candidate)
                            confirmed=ctx.capture('confirm_tool_'+str(row['operation_native_id']),consumers);require(fields.equal(observed,confirmed),'Two SetTool barrier captures differ')
                            out['readback_verified']=True;out['capture']='after_tool_'+str(row['operation_native_id']);persist();final=confirmed
                        for change in row['fields']:
                            if fields.equal(change['expected'],change['new']):continue
                            out,pending,returned=action('field',row,change)
                            ctx.set_field(row,change,pending,returned)
                            observed=ctx.read_field(row,change,out.setdefault('observed',{}))
                            require(fields.equal(observed,change['new']),'Immediate field readback differs')
                            out['readback_verified']=True;persist()
                    after=ctx.capture('after',consumers);fields.verify_final(before,after,data['plan'],candidates)
                    final=ctx.capture('confirm_after',consumers);require(fields.equal(after,final),'Two final captures differ');fields.verify_final(before,final,data['plan'],candidates)
                report['parameter_delta_verified']=True;persist()
                if v['save_after_verified']:
                    out,pending,returned=action('SaveActiveDocument')
                    def save_pending():report['save_attempted']=True;pending()
                    def save_returned(value):
                        report.update(save_call_returned=True,save_hresult=value if type(value) is int else None);returned(value)
                    ctx.save(save_pending,save_returned)
                    saved=ctx.capture('saved',consumers);expected=deepcopy(final);expected['document']['needs_save']=False
                    require(fields.equal(saved,expected),'Save changed protected captured state')
                    confirm_saved=ctx.capture('confirm_saved',consumers);require(fields.equal(saved,confirm_saved),'Two saved captures differ')
                    final=confirm_saved;out['readback_verified']=True;report.update(save_readback_verified=True,model_saved=True,source_update_verified=True,saved_file_sha256=ctx.source);persist()
                ctx.boundary()
            ctx.boundary()
        clean_events(dict(messages=ctx.session.summary()));require(ctx.identity()==final['document'],'Identity changed after cleanup');runtime_check()
        report.update(status='review_required',phase='finished',readback_verified=True,may_apply=v['action'] in ('prepare','prepare_recover_save'),reason='CAPTURED_PARAMETERS_ONLY_NO_GTP_NO_MACHINING_QUALIFICATION')
    except Exception as exc:
        report.update(failed_phase=report['phase'],phase='finished',issue=_error(exc));_revoke(report)
    finally:
        if ctx is not None and ctx.session is not None:report['messages']=ctx.session.summary()
        try:
            persist()
            if report['marker_created']:_write_receipt(marker,dict(scope=SCOPE,status=report['status'],receipt_path=v['receipt_path'],receipt_sha256=_file_hash(v['receipt_path']),automatic_replay=False))
        except Exception as exc:_revoke(report);report['receipt_write_error']=_error(exc)
    return report
