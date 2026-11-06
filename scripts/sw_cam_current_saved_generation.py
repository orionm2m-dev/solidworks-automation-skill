"""既有 generation 入口的 current_saved 顺序；只执行固定原语，无通用事务框架。"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_current_saved_generation_delta as delta
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam import _error
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events

SCOPE='MILL_CURRENT_SAVED_SELECTED_GENERATION_V1'
CONFIG_SCOPE='MILL_CURRENT_SAVED_PARAMETER_BATCH_V1'
CONFIG_FLAGS=('readback_verified','parameter_delta_verified','save_readback_verified','model_saved','source_update_verified','runtime_unchanged')


def require(value,message):
    delta.require(value,message)


def load_completed_configuration(path,sha,*,process_id,source_path,source_sha256,selected_ids):
    """读取实际完成的配置/Save，绑定摘要不冒充外部 JSON 文件哈希。"""
    d,pin=read_pin(path,sha)
    if d.get('binding',{}).get('configuration_mode')=='current_saved_circular':
        from scripts.sw_cam_current_circular_authority import load_configured
        return load_configured(path,sha,process_id=process_id,source_path=source_path,source_sha256=source_sha256,selected_ids=selected_ids)
    require(d.get('scope')==CONFIG_SCOPE and d.get('action') in ('apply','recover_save') and d.get('status')=='review_required' and d.get('phase')=='finished','Completed current-saved configuration receipt required')
    require(all(d.get(k) is True for k in CONFIG_FLAGS),'Configuration/Save/runtime verification incomplete')
    require(d.get('save_call_returned') is True and type(d.get('save_hresult')) is int and d['save_hresult']==0,'Exact actual successful configuration Save return required')
    require(d.get('GTP_attempted') is False and d.get('GOP_attempted') is False and d.get('native_dispatch_pending') is False,'Configuration must contain no GTP/GOP or pending native outcome')
    require(not any(k in d for k in ('issue','failed_phase','runtime_error','receipt_write_error','cleanup_error')),'Failed or uncertain configuration is not generation authority')
    clean_events(d)
    binding=d.get('binding');require(type(binding) is dict,'Complete configuration binding required')
    require(type(binding.get('process_id')) is int and binding['process_id']==process_id,'Configuration process differs')
    require(Path(binding.get('expected_document_path','')).resolve()==Path(source_path).resolve(),'Configuration source path differs')
    require(d.get('source_after_sha256')==d.get('saved_file_sha256')==source_sha256,'Configuration post-Save source SHA differs')
    request_pin=d.get('request_pin');require(type(request_pin) is dict and request_pin.get('kind')=='canonical_binding' and request_pin.get('sha256')==_digest(binding),'Exact canonical binding digest required')
    saved=d.get('saved');require(type(saved) is dict and delta.equal(saved,d.get('confirm_saved')) and saved.get('document',{}).get('needs_save') is False,'Two exact complete clean postconfiguration captures required')
    delta.select(saved,selected_ids)
    recipe=d.get('recipe');require(type(recipe) is dict and type(recipe.get('rows')) is list,'Actual immutable configured recipe required')
    from scripts import sw_cam_current_saved_parameter_fields as fields
    fields.validate_recipe(recipe)
    for row in recipe['rows']:
        actual=fields.parameter_row(saved,row['operation_native_id'])
        require(actual['operation_type']==row['operation_type'] and actual['feature_native_id']==row['feature_native_id'],'Configured recipe target binding differs')
        for change in row['fields']:require(fields.equal(fields.field_value(actual,change['field']),change['new']),'Completed configuration actual value differs from recipe')
        wanted=row['existing_tool_native_id'] if row['existing_tool_native_id'] is not None else row['expected_tool_native_id']
        require(actual['tool']['generic']['native_id']==wanted,'Completed configuration tool differs from recipe')
    recipe_ids=[r.get('operation_native_id') for r in recipe['rows']]
    require(set(selected_ids)<=set(recipe_ids),'Selected generation must belong to the completed configured recipe')
    pins=d.get('qualified_read_pins');require(type(pins) is dict and set(pins)=={'request','result','authority','recipe'},'Exact immutable request/result/saved-authority/recipe pins required')
    for value in pins.values():
        require(type(value) is dict and type(value.get('path')) is str and type(value.get('sha256')) is str,'Concrete immutable file pin required')
        _,actual=read_pin(value['path'],value['sha256']);require(actual['sha256']==value['sha256'],'Evidence file changed')
    actual_recipe,_=read_pin(pins['recipe']['path'],pins['recipe']['sha256']);require(delta.equal(actual_recipe,recipe),'Recipe content differs from immutable file')
    actual_request,_=read_pin(pins['request']['path'],pins['request']['sha256'])
    addin_clsid=_configuration_addin_clsid(actual_request,pins['request'],binding)
    recovery_pins={}
    if d['action']=='recover_save':recovery_pins=_load_recovery_history(d,binding,pins)
    else:require(not any(k in d for k in ('recovery_mode','recovery_verified','recovery_pins','original_action_receipt_pin')),'Ordinary apply cannot masquerade as recovery')
    return dict(receipt=deepcopy(d),pin=pin,state=deepcopy(saved),binding=deepcopy(binding),recipe=deepcopy(recipe),pins=deepcopy(pins),recovery_pins=deepcopy(recovery_pins),addin_clsid=addin_clsid,selected_ids=list(selected_ids),source_sha256=source_sha256)


def _configuration_addin_clsid(request,pin,binding):
    """从已固定的真实参数读取请求取得显式 CLSID；不使用版本默认值。"""
    import re
    require(type(request) is dict and type(request.get('requests')) is list and all(type(x) is dict for x in request['requests']),'Exact pinned parameter request batch required')
    rows=[x for x in request['requests'] if x.get('name')=='solidworks_cam_inspect_current_saved_compound']
    require(len(rows)==1,'One exact pinned current parameter tool call required')
    args=rows[0].get('arguments');require(type(args) is dict and type(args.get('params')) is dict,'Pinned parameter tool arguments required');v=args['params']
    for key in ('process_id','expected_process_create_time','expected_document_path','expected_source_sha256'):
        require(key in binding and type(v.get(key)) is type(binding[key]) and v[key]==binding[key],'Pinned add-in request binding differs: '+key)
    require(v.get('read_mode')=='current_saved' and v.get('observation')=='operation_parameters','Original current parameter observation required')
    require(type(binding.get('current_read_request_path')) is str and Path(binding['current_read_request_path']).resolve()==Path(pin['path']).resolve() and binding.get('current_read_request_sha256')==pin['sha256'],'Original request file pin differs from configuration binding')
    clsid=v.get('addin_clsid');require(type(clsid) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',clsid) is not None,'Explicit pinned CAM add-in GUID required')
    return clsid


def _load_recovery_history(d,binding,pins):
    """仅接受显式 Save-only 完成结果；完整历史证据由共用纯验证器检查。"""
    from scripts import sw_cam_current_saved_parameter_batch as batch
    from scripts.sw_cam_current_parameter_recovery_evidence import validate_history
    require(d.get('recovery_verified') is True and d.get('recovery_mode')=='recover_save' and d.get('setters_replayed') is False,'Explicit verified Save-only recovery required')
    recovery=d.get('recovery_pins');require(type(recovery) is dict and set(recovery)=={'partial','old_marker','original_request','original_prepare'},'Four immutable recovery history pins required')
    records={};actual_pins={}
    for key,p in recovery.items():
        require(type(p) is dict and type(p.get('path')) is str and type(p.get('sha256')) is str,'Concrete recovery history file pin required')
        records[key],actual_pins[key]=read_pin(p['path'],p['sha256']);require(delta.equal(p,actual_pins[key]),'Recovery history file identity changed')
    data=batch.load_inputs(binding)
    require(delta.equal(data['pins'],pins) and delta.equal(data['plan'],d['recipe']),'Recovery original read/recipe authority differs')
    verified=validate_history(records['partial'],records['original_prepare'],records['original_request'],records['old_marker'],base_binding=binding,plan=data['plan'],baseline=data['baseline'],pins=actual_pins)
    require(delta.equal(d.get('original_action_receipt_pin'),verified['original_action_receipt_pin']) and delta.equal(d.get('historical_before'),verified['historical_before']),'Recovery original action/before linkage differs')
    require(d.get('source_before_sha256')==binding.get('expected_source_sha256')==records['partial'].get('source_before_sha256'),'Recovery original source differs')
    expected=verified['expected_state']
    for key in ('before','confirm_before','after','confirm_after'):require(delta.equal(d.get(key),expected),'Save-only recovery changed or omitted the exact historical final state')
    delta.verify_saved(expected,d['saved'])
    actions=d.get('actions');require(type(actions) is list and len(actions)==1,'Recovery must contain exactly one new Save action')
    a=actions[0];require(type(a) is dict and a.get('kind')=='SaveActiveDocument' and a.get('operation_native_id') is None and a.get('change') is None,'Recovery must not contain new setters or operation targets')
    require(all(a.get(k) is True for k in ('attempted','returned','readback_verified')) and a.get('native_dispatch_pending') is False and a.get('return_type')=='int' and type(a.get('return_value')) is int and a['return_value']==0,'Exact completed recovery Save action required')
    return actual_pins


class Journal:
    """一个明确 packet 的已有文件型 once 记录；不允许自动续跑或覆盖旧 marker。"""
    def __init__(self,receipt,marker,report):
        self.receipt=Path(receipt);self.marker=Path(marker);self.report=report;self.created=False;self.claimed=False
    def create(self):
        require(not self.created and not self.claimed and not self.receipt.exists() and not self.marker.exists(),'Fresh receipt and unused generation marker required')
        _write_receipt(self.receipt,self.report,create=True);self.created=True;self.report['receipt_created']=True;self.persist()
    def persist(self):
        if self.created:
            _write_receipt(self.receipt,self.report)
            if self.claimed:_write_receipt(self.marker,self.marker_state())
    def marker_state(self):
        return dict(scope=SCOPE,receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),configuration_receipt_pin=deepcopy(self.report['configuration_receipt_pin']),selected_operation_native_ids=list(self.report['selected_operation_native_ids']),status=self.report['status'],phase=self.report['phase'],automatic_replay=False)
    def claim(self):
        require(self.created and not self.claimed,'Only one initial generation packet claim allowed')
        _write_receipt(self.marker,self.marker_state(),create=True);self.claimed=True;self.report['marker_created']=True;self.persist()
    def action(self,name):
        require(name not in self.report['actions'],'Action already observed; no replay')
        self.report['actions'][name]=dict(attempted=False,returned=False,native_dispatch_pending=False)
        self.persist();return self.report['actions'][name]
    def pending(self,name):
        row=self.report['actions'][name];require(row['attempted'] is False,'Native action already attempted')
        require(self.claimed,'Durable once claim required before dispatch')
        row.update(attempted=True,native_dispatch_pending=True);self.report.update(phase=name,native_dispatch_pending=True,native_call_attempted=True)
        if name.startswith('GTP:'):self.report.update(GTP_attempted=True,mutation_attempted=True)
        if name=='SaveActiveDocument':self.report.update(save_attempted=True,mutation_attempted=True)
        if name.endswith('CL'):self.report['CL_export_attempted']=True
        self.persist()
    def returned(self,name,value):
        row=self.report['actions'][name];require(row['attempted'] is True and row['returned'] is False,'Return without unique pending action')
        row.update(returned=True,native_dispatch_pending=False,native_return_type=type(value).__name__,native_return_value=value if value is None or type(value) in(bool,int,float,str) else None)
        self.report.update(native_call_returned=True,native_dispatch_pending=False);self.persist()


def run_once(backend,journal,loaded):
    """preCL→明确目标 GTP→checked Save→postCL；所有失败保留实际结果而不重试。"""
    r=journal.report;reference=loaded['state'];ids=loaded['selected_ids'];completed=[]
    proof=delta
    circular=loaded.get('mode')=='current_saved_circular'
    if circular:
        from scripts.sw_cam_current_circular_continuation import CircularGenerationProof
        proof=CircularGenerationProof(backend,reference=reference)
    r.update(scope=SCOPE,status='error',phase='preflight',configuration_receipt_pin=deepcopy(loaded['pin']),selected_operation_native_ids=list(ids),actions={},captures=[],receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,save_attempted=False,CL_export_attempted=False,model_saved=False,save_readback_verified=False,readback_verified=False,source_update_verified=False,operation_creation_attempted=False,tool_assignment_attempted=False,parameter_setter_attempted=False,automatic_replay=False,automatic_rollback=False,world_geometry_verified=False,production_qualified=False,reopen_persistence_verified=False,runtime_unchanged=False,source_before_sha256=loaded['source_sha256'])
    def observe(label):
        row=dict(label=label,capture_complete=False,state={});r['captures'].append(row);r['phase']=label;journal.persist()
        value=backend.capture(label,row['state']);row['state']=deepcopy(value);row['capture_complete']=value.get('capture_complete') is True and value.get('parameter_capture_complete') is True and value.get('parameter_batch',{}).get('read_complete') is True;r[label]=deepcopy(value);journal.persist();return value
    def one_export(label,state):
        action=journal.action(label)
        expected=proof.cl_rows(reference,state,ids,completed_ids=completed or None)
        detail=dict(expected_generated_operations=deepcopy(expected),output_verified=False);r[label]=detail;journal.persist()
        value=backend.export_cl(label,state,expected,detail,pending=lambda:journal.pending(label),returned=lambda x:journal.returned(label,x))
        require(action['attempted'] is True and action['returned'] is True and action['native_return_type']=='int' and type(action['native_return_value']) is int and action['native_return_value']==0,'Exact completed SaveCLFile int0 required')
        r[label]=deepcopy(value);journal.persist();require(value.get('output_verified') is True and value.get('readback_verified') is True,'Verified native CL output required')
        return value
    try:
        delta.select(reference,ids);journal.create();backend.start();backend.boundary()
        before=observe('before');confirm=observe('confirm_before')
        require(proof.equal(before,reference) and proof.equal(before,confirm),'Fresh complete current state differs from completed configuration')
        backend.boundary();journal.claim();backend.boundary()
        pre=one_export('preCL',before)
        current=observe('after_preCL');require(proof.equal(current,before),'preCL changed current configuration')
        for oid in ids:
            fresh=observe('before_GTP_'+str(oid));require(proof.equal(fresh,current),'State changed immediately before selected GTP')
            name='GTP:'+str(oid);a=journal.action(name);backend.boundary()
            backend.generate(oid,fresh,pending=lambda:journal.pending(name),returned=lambda x:journal.returned(name,x))
            require(a['attempted'] is True and a['returned'] is True and a['native_return_type']=='int' and type(a['native_return_value']) is int and a['native_return_value']==0,'Exact GenerateToolpath int0 required; no replay')
            completed.append(oid)
            actual=observe('after_GTP_'+str(oid));r['generation_verification']=proof.verify_generation(reference,actual,ids,completed);journal.persist()
            confirm=observe('confirm_GTP_'+str(oid));require(proof.equal(actual,confirm),'Two complete postgeneration captures differ');current=confirm
        r['generated']=deepcopy(current);r['save_stage']={};journal.action('SaveActiveDocument')
        def save_capture(label):
            actual=observe('before_save'if label=='before'else'saved')
            if label=='before':require(proof.equal(actual,current),'Current CAM parameters changed before Save')
            else:proof.verify_saved(current,actual)
            normalized=deepcopy(actual);normalized['document']['needs_save']=False
            return proof.save_comparison_state(actual) if circular else normalized
        expected=deepcopy(current);expected['document']['needs_save']=False
        if circular:expected=proof.save_comparison_state(current)
        def verify(value):require(proof.equal(value,expected),'Save altered captured CAM context')
        def save_returned(value):
            journal.returned('SaveActiveDocument',value)
            r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if value is None or type(value) in(bool,int,float,str)else None);journal.persist()
        def native_save():return backend.save(returned=save_returned)
        def saved_hash():
            value=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=value,saved_file_sha256=value);journal.persist();return value
        run_one_existing_save(r['save_stage'],capture=save_capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=native_save,saved_hash=saved_hash)
        confirm_saved=observe('confirm_saved');proof.verify_saved(current,confirm_saved);require(proof.equal(confirm_saved,r['saved']),'Two complete saved captures differ')
        r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);journal.persist()
        post=one_export('postCL',confirm_saved)
        r['CL_preservation']=delta.compare_cl(backend.parse_cl(pre),backend.parse_cl(post),pre['expected_generated_operations'],post['expected_generated_operations'],ids);journal.persist()
        last=observe('after_postCL');require(proof.equal(last,confirm_saved),'Post-save CL export changed captured current state')
        backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True)
    except Exception as exc:
        r.update(status='uncertain'if r['mutation_attempted']or r['CL_export_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),reason=str(exc)if type(exc) is ValueError else 'NATIVE_OR_CAPTURE_FAILURE',readback_verified=False,model_saved=False,save_readback_verified=False,source_update_verified=False,runtime_unchanged=False)
        try:
            if r['mutation_attempted'] and backend.may_capture_failure():observe('failure_actual')
        except Exception as capture_error:r['failure_capture_issue']=_error(capture_error)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']or r['CL_export_attempted']else'error',cleanup_error=_error(exc),readback_verified=False,runtime_unchanged=False,model_saved=False,save_readback_verified=False,source_update_verified=False)
        r['phase']='finished'
        try:journal.persist()
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']or r['CL_export_attempted']else'error',receipt_write_error=_error(exc),readback_verified=False,runtime_unchanged=False,model_saved=False,save_readback_verified=False,source_update_verified=False)
    return r


PARAMS={'generation_mode','process_id','expected_process_create_time','expected_document_path','expected_source_sha256','configuration_receipt_path','configuration_receipt_sha256','selected_operation_native_ids','module_sha256','receipt_path','progress_path','attempt_registry_path','before_cl_path','saved_cl_path','acknowledgement'}
ACK='generate_explicit_current_saved_subset_once_save_once_compare_machine_CL'

def prepare_request(request):
    """现有 sealed packet 的显式分支；仅做文件/参数验证，不连接 CAM。"""
    import math,re
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='generate_configured_local_group','Exact existing generation packet action required')
    v=deepcopy(request['params']);require(type(v) is dict and set(v)==PARAMS,'Exact current-saved generation packet fields required')
    require(v['generation_mode'] in ('current_saved','current_saved_circular') and v['acknowledgement']==ACK,'Explicit selected generation/Save/CL acknowledgement required')
    require(type(v['process_id']) is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time']) in(int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Strict process lifetime required')
    require(type(v['expected_source_sha256']) is str and re.fullmatch('[0-9a-f]{64}',v['expected_source_sha256']),'Exact saved source SHA required')
    source=Path(v['expected_document_path']);require(source.is_absolute() and source.suffix.casefold()=='.sldprt' and source.is_file() and not source.is_symlink() and _file_hash(source)==v['expected_source_sha256'],'Exact current saved source file required')
    require(type(v['module_sha256']) is str and v['module_sha256']==_file_hash(__file__),'Installed current generation implementation differs')
    loaded=load_completed_configuration(v['configuration_receipt_path'],v['configuration_receipt_sha256'],process_id=v['process_id'],source_path=str(source),source_sha256=v['expected_source_sha256'],selected_ids=v['selected_operation_native_ids'])
    require((v['generation_mode']=='current_saved_circular') is (loaded.get('mode')=='current_saved_circular'),'Generation mode must match actual configuration authority')
    require(type(loaded['binding'].get('expected_process_create_time')) is type(v['expected_process_create_time']) and loaded['binding']['expected_process_create_time']==v['expected_process_create_time'],'Completed configuration lifetime differs')
    from scripts.sw_cam_deep_guide_cl import _fresh_path
    before=_fresh_path(v['before_cl_path']);after=_fresh_path(v['saved_cl_path'])
    directory=Path(v['attempt_registry_path']);require(directory.is_absolute() and directory.is_dir() and not directory.is_symlink(),'Existing absolute attempt registry required')
    marker=directory/('current_saved_gtp_'+_digest(dict(scope=SCOPE,source=str(source.resolve()).casefold(),source_sha256=v['expected_source_sha256'],selected_ids=v['selected_operation_native_ids']))+'.json')
    require(not marker.exists() and not marker.is_symlink(),'Prior selected source attempt exists; no replay')
    outputs=[Path(v[k]) for k in ('receipt_path','progress_path')]
    for output in outputs:require(output.is_absolute() and output.suffix.casefold()=='.json' and output.parent.is_dir() and not output.exists() and not output.is_symlink(),'Unique absolute JSON output required')
    protected={source.resolve(),Path(__file__).resolve(),Path(loaded['pin']['path']).resolve()}|{Path(p['path']).resolve()for p in [*loaded['pins'].values(),*loaded.get('recovery_pins',{}).values()]}
    all_outputs=[*outputs,marker,before,after]
    require(len({p.resolve()for p in all_outputs})==len(all_outputs) and not protected.intersection(p.resolve()for p in all_outputs),'Output/marker aliases source or evidence')
    require(before.parent.resolve()!=after.parent.resolve(),'Distinct new pre/post CL directories required')
    return v,loaded,marker


def preflight(tlb):
    """复用已知 ABI：typed MILL GTP9、Machine4 SaveCLFile14 和既有 Save12。"""
    from ctypes import HRESULT
    from comtypes import BSTR
    from scripts.sw_cam_comtypes import _interface_class,_INTERFACES
    from scripts import sw_cam_mill_current_append as append
    append.save_abi(tlb)
    for owner,name,dispid,args,flags in [('ICWMillOperation','GenerateToolpath',9,(),()),('ICWMachine4','SaveCLFile',14,(BSTR,),(1,))]:
        cls=_interface_class(owner,tlb);require(str(cls._iid_).upper()==_INTERFACES[owner].upper(),'Exact declared interface required')
        found=[m for m in cls._methods_ if m.name==name];require(len(found)==1,'Unique declared native method required');m=found[0]
        require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==args and tuple(p[0]for p in m.paramflags)==flags and not any(x in m.idlflags for x in ('propget','propput','propputref')),'Exact HRESULT-only GTP/CL ABI required')


def dispatch_current_saved(sw,clsid,tlb,request,*,runtime_check,_backend_factory=None):
    """复用既有 endpoint 的 one-shot 批次；禁止在旧配置上生成。"""
    v,loaded,marker=prepare_request(request);preflight(tlb)
    from scripts import sw_cam_mill_current_compound_read as current
    current._abi(tlb)
    from scripts import sw_cam_mill_current_parameters as parameters
    from scripts import sw_cam_current_parameter_capture as captures
    from scripts.sw_cam_comtypes import _interface_class
    parameters.preflight(tlb,'selected_continue')
    for name in captures.PREFLIGHT_INTERFACES:_interface_class(name,tlb)
    if _backend_factory is None:
        from scripts.sw_cam_current_generation_native import NativeGenerationContext
        _backend_factory=NativeGenerationContext
        if loaded.get('mode')=='current_saved_circular':
            from scripts.sw_cam_current_circular_continuation import CircularGenerationContext
            _backend_factory=CircularGenerationContext
    r=dict(receipt_path=v['receipt_path'],dispatch_marker_path=str(marker),request=deepcopy(request),request_sha256=_digest(request),runtime_unchanged=False)
    class ProgressJournal(Journal):
        progress_created=False
        def persist(self):
            super().persist()
            if self.created:
                _write_receipt(Path(v['progress_path']),dict(scope=SCOPE,status=self.report.get('status'),phase=self.report.get('phase'),receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),native_dispatch_pending=self.report.get('native_dispatch_pending',False)),create=not self.progress_created)
                self.progress_created=True
    journal=ProgressJournal(v['receipt_path'],marker,r)
    backend=_backend_factory(sw,clsid,tlb,v,loaded,r,journal.persist,runtime_check)
    runtime_check();result=run_once(backend,journal,loaded)
    try:runtime_check()
    except Exception as exc:return revoke_runtime(result,exc)
    return result


def revoke_runtime(report,error):
    """保留已返回 native evidence，撤销最终成功；只重写本次创建的回执。"""
    report.update(status='uncertain'if report.get('mutation_attempted')or report.get('CL_export_attempted')else'error',runtime_unchanged=False,readback_verified=False,model_saved=False,save_readback_verified=False,source_update_verified=False,runtime_error=_error(error),reason='RUNTIME_CHANGED_AFTER_CALL')
    try:
        path=Path(report['receipt_path'])
        if report.get('receipt_created') is True:
            import json
            current=json.loads(path.read_text(encoding='utf-8'))
            require(current.get('scope')==SCOPE and current.get('request_sha256')==report.get('request_sha256') and current.get('dispatch_marker_path')==report.get('dispatch_marker_path'),'Only invocation-owned generation receipt may be rewritten')
            _write_receipt(path,report)
            if report.get('marker_created') is True:
                marker=Path(report['dispatch_marker_path']);prior=json.loads(marker.read_text(encoding='utf-8'))
                require(prior.get('scope')==SCOPE and Path(prior.get('receipt_path','')).resolve()==path.resolve(),'Only invocation-owned marker may be updated')
                prior.update(status=report['status'],receipt_sha256=_file_hash(path));_write_receipt(marker,prior)
    except Exception as exc:report['runtime_receipt_update_error']=_error(exc)
    return report
