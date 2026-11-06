"""复用当前参数生命周期的有界圆形口袋上下文；不仿造旧证据。"""
from copy import deepcopy
from contextlib import contextmanager
from ctypes import HRESULT,POINTER,c_long,c_double
from ctypes.wintypes import VARIANT_BOOL
from comtypes import BSTR
from comtypes.automation import IDispatch
from scripts import sw_cam_current_saved_parameter_batch as batch
from scripts import sw_cam_current_parameter_capture as parameter_capture
from scripts import sw_cam_mill_current_parameters as parameters
from scripts import sw_cam_current_saved_parameter_fields as fields
from scripts import sw_cam_mill_current_append as append
from scripts import sw_cam_mill_selected_insert as selected
from scripts import sw_cam_guide_group_definitions as definitions
from scripts import sw_cam_current_circular_delta as delta
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_mill_current_append import read_catalogues
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam import _member
from scripts.sw_cam_profile_sketch import _snapshot,_select_plane,_create,_read_sketch
from scripts.sw_cam_mill_units_qualification import _circle_feature,_circle_sketch

require=delta.require


def preflight(tlb,definition_mode):
    """先验证所有复用接口及唯一口袋工厂，再允许创建动作。"""
    batch.current._abi(tlb);parameters.preflight(tlb,definition_mode);fields.preflight(tlb);selected.abi(tlb);selected.nc_abi(tlb);append.save_abi(tlb)
    for name in ('ICWSetup','ICWSegChain','ICWCurve','ICWCircle','ICWArc','ICWPosition','ICWUnitVector'):_interface_class(name,tlb)
    cls=_interface_class('ICWSetup',tlb);methods=[m for m in cls._methods_ if m.name=='CreateMillFeature2'];require(len(methods)==1,'Exact CreateMillFeature2 required');m=methods[0]
    args=(c_long,BSTR,VARIANT_BOOL,c_double,VARIANT_BOOL,VARIANT_BOOL,VARIANT_BOOL,VARIANT_BOOL,c_double,c_long,VARIANT_BOOL,c_long,c_long,POINTER(POINTER(IDispatch)))
    require(m.restype is HRESULT and m.idlflags[0]==8 and m.argtypes==args and tuple(x[0] for x in m.paramflags)==(1,)*13+(10,) and not any(x in m.idlflags for x in ('propget','propput','propputref')),'Exact closed-pocket factory ABI required')
    cls=_interface_class('ICWMillFeature',tlb);methods=[m for m in cls._methods_ if m.name=='IGetIslandCount'];require(len(methods)==1,'Exact IGetIslandCount required');m=methods[0]
    require(m.restype is HRESULT and m.idlflags[0]==26 and m.argtypes==(POINTER(c_long),) and tuple(x[0] for x in m.paramflags)==(10,) and not any(x in m.idlflags for x in ('propget','propput','propputref')),'Exact island-count ABI required')
    return dict(native_calls=0,closed_pocket_type=0,reverse_direction=False,depth_direction='explicit_owner_setup',automatic_GOP=False)


class NativeCircularContext(batch.NativeBatchContext):
    """原始配置仅固定保护基准；新口袋始终使用真实 ID 与单独观察。"""
    def __init__(self,sw,clsid,tlb,request,loaded,report,persist,runtime_check,*,restore=None,continuation_pins=()):
        self.request=request;self.loaded=loaded;self._native_read_limit=48000
        original=batch.load_inputs(loaded['binding'],clsid)
        if '_feature_resume' in loaded:
            original=deepcopy(original);original['recovery']={'expected_state':deepcopy(loaded['_feature_resume']['expected_state'])}
        v=deepcopy(loaded['binding']);v['expected_source_sha256']=request['expected_source_sha256']
        v['expected_candidate_consumer_ids']=deepcopy(loaded['state']['parameter_batch']['candidate_consumer_ids'])
        super().__init__(sw,clsid,tlb,v,original,report,persist,runtime_check)
        self.pins=[loaded['pin']]+list(loaded['pins'].values())+list(loaded.get('recovery_pins',{}).values())
        self.new_feature_id=None;self.new_operation_ids=[];self.created_names=[]
        self.reference_consumers=deepcopy(loaded['state']['parameter_batch']['candidate_consumer_ids'])
        self.pins.extend(deepcopy(list(continuation_pins)))
        if restore is not None:
            self.new_feature_id=restore['new_feature_native_id'];self.new_operation_ids=[r['native_id'] for r in restore['new_operations']];self.created_names=list(restore['created_names']);self.new_own_tool_id=restore['new_operations'][0]['assigned_tool']['native_id'] if restore['new_operations'] else None
    def verify_files(self):
        if getattr(self,'_capture_pin_scope',False) is True:
            self._capture_pin_episode['nested_checks_deferred']+=1
            return
        # 仅重试文件传输异常；不重放原生调用，也不放宽哈希或完整 identity。
        from time import sleep
        def checked(path,sha,expected=None):
            episode=None
            for attempt in range(1,4):
                try:observed=read_pin(path,sha)[1]
                except Exception as exc:
                    cause=exc.__cause__
                    retryable=type(exc) is ValueError and isinstance(cause,OSError)
                    if not retryable:
                        if episode is not None:
                            episode.update(outcome='non_retryable_error',completed_attempt=attempt);self.persist()
                        raise
                    if episode is None:
                        journal=self.report.setdefault('file_pin_read_retries',[])
                        if len(journal)>=64:
                            self.report['file_pin_retry_journal_limit_reached']=True;self.persist();raise
                        episode=dict(path=path,sha256=sha,failures=[],outcome='retry_pending')
                        journal.append(episode)
                    episode['failures'].append(dict(attempt=attempt,errno=cause.errno if type(cause.errno) is int else None,winerror=getattr(cause,'winerror',None) if type(getattr(cause,'winerror',None)) is int else None))
                    episode.update(outcome='retry_budget_exhausted' if attempt==3 else 'retry_pending',completed_attempt=attempt)
                    self.persist()
                    if attempt==3:raise
                    sleep(0.05);continue
                matches=expected is None or observed==expected
                if episode is not None:
                    episode.update(outcome='verified_after_retry' if matches else 'pin_mismatch',completed_attempt=attempt);self.persist()
                require(matches,'Immutable circular authority changed')
                return observed
        for pin in self.pins:checked(pin['path'],pin['sha256'],pin)
        if self.request.get('prepare_receipt_path'):checked(self.request['prepare_receipt_path'],self.request['prepare_receipt_sha256'])
    def guard(self):
        require(getattr(self,'_capture_pin_scope',False) is False,'Native dispatch forbidden inside read-only capture')
        from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
        expected=self.boundary()
        return ScopedCamDispatchGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=expected,source_sha256=self.source,evidence_pins=self.pins,verify_evidence=self.verify_files,verify_owned_process=lambda:self.boundary(),check_events=self.check)
    def save(self,pending,returned):
        require(getattr(self,'_capture_pin_scope',False) is False,'Save forbidden inside read-only capture')
        return super().save(pending,returned)
    def capture(self,label,consumer_ids=None,generation_observations=None,attempted_generation_ids=()):
        # 只在一个只读捕获内合并历史文件检查；身份、源文件、runtime、事件边界不变。
        require(getattr(self,'_capture_pin_scope',False) is False,'Nested circular capture forbidden')
        episode=dict(label=label,entry_verified=False,exit_verified=False,nested_checks_deferred=0)
        self.report.setdefault('capture_pin_checks',[]).append(episode)
        self.boundary();episode['entry_verified']=True
        self._capture_pin_episode=episode;self._capture_pin_scope=True
        failed=True
        try:
            value=self._capture_readonly(label,consumer_ids,generation_observations,attempted_generation_ids)
            failed=False
            return value
        except BaseException as error:
            episode['capture_error_type']=type(error).__name__
            raise
        finally:
            self._capture_pin_scope=False;self._capture_pin_episode=None
            try:
                self.boundary();episode['exit_verified']=True
            except BaseException as error:
                failed=True;episode['exit_error_type']=type(error).__name__
                raise
            finally:
                state=self.report.get(label)
                if failed and type(state) is dict:
                    state['capture_complete']=False;state['extended_capture_complete']=False
                self.persist()
    def _capture_readonly(self,label,consumer_ids=None,generation_observations=None,attempted_generation_ids=()):
        # 新操作只在实际 GTP attempt 后接受当次 route 返回的正记录数。
        if consumer_ids is None:consumer_ids=list(self.reference_consumers)+([self.new_operation_ids[0]] if self.new_operation_ids and getattr(self,'new_own_tool_id',None)==self.v['candidate_tool_native_id'] else [])
        require(all(type(x) is int for x in attempted_generation_ids) and set(attempted_generation_ids)<=set(self.new_operation_ids),'Generation scope outside actual new operations')
        state={};self.report[label]=state
        if not getattr(self,'_capture_journal_managed',False):self.report['captures'].append(label)
        self.persist();start=self.boundary()
        def boundary():require(self.boundary()==start,'Identity changed during reference capture')
        try:
            self.native=batch.current._capture(self.app,self.tlb,self.read,self.typed,state,self.v,boundary,verify_operation_pins=False)
            state['document']=deepcopy(start)
            require([x['native_id'] for x in state['operations']]==list(self.loaded['binding']['expected_operation_native_ids'])+list(self.new_operation_ids),'Exact retained and new operation order required')
            old=[x for x in state['operations'] if x['native_id'] not in self.new_operation_ids]
            require(fields.equal(old,self.loaded['state']['operations']),'An original operation/tool/path changed')
            observed={}
            for row in state['operations']:
                if row['native_id'] not in self.new_operation_ids:continue
                if row['native_id'] in attempted_generation_ids:
                    counts=row['toolpath_record_counts'];require(row['toolpath_generated'] is True and type(counts) is list and len(counts)==1 and type(counts[0]) is int and 0<counts[0]<=100000,'Attempted new generation must have one positive bounded path')
                    observed[row['native_id']]=deepcopy(counts)
                else:require(row['toolpath_generated'] is False and row['toolpath_record_counts']==[],'Unexpected generation of new operation')
            if generation_observations is not None:require(fields.equal(generation_observations,observed),'Explicit generation observations differ')
            generation_observations=observed
            strategy=deepcopy(state)
            for row in strategy['features']:
                if row['geometry']['native_id']==self.v['expected_feature_native_id']:row['geometry']=deepcopy(state['target_header'])
            state['strategy_diagnostics']={}
            batch.read_compound_strategy(strategy,self.native,self.read,self.typed,state['strategy_diagnostics'],feature_id=self.v['expected_feature_native_id'],owner_id=self.v['expected_feature_setup_native_id'],step_count=3,expected_header=state['target_header'],boundary=boundary,observation='strategy')
            state['default_operation_catalogues']=read_catalogues(self.native['selected_feature'],read=self.read,typed=self.typed)
            if self.data['authority']['definition_mode']=='selected_continue':
                oid=self.v['parameter_operation_native_ids'][0];state['retained_operation_nc']=dict(operation_native_id=oid,read_complete=False)
                state['retained_operation_nc']['nc']=batch.read_own_nc(self.native['operations'][oid],read=self.read,typed=self.typed);state['retained_operation_nc']['read_complete']=True
            targets=[next(x for x in state['operations'] if x['native_id']==oid) for oid in self.v['parameter_operation_native_ids']]
            parameter_capture.capture_parameter_batch(state,self.native,targets,feature_id=self.v['expected_feature_native_id'],candidate_tool_native_id=self.v['candidate_tool_native_id'],expected_candidate_consumer_ids=consumer_ids,read=self.read,typed=self.typed,boundary=boundary)
            boundary()
        except BaseException:
            state['capture_complete']=False;self.persist();raise
        self.report[label]=state;state['extended_capture_complete']=False
        try:
            state['reference_header']=state.pop('target_header');state['reference_profile']=state.pop('profile');state['reference_number_of_steps_raw']=state.pop('number_of_steps_raw')
            witness={k:state.pop(k) for k in ('operation_parameters','parameter_capture_complete','parameter_batch','retained_operation_nc') if k in state}
            observed=witness['parameter_batch'];allowed=set(self.reference_consumers)
            observed['candidate_consumer_ids']=[x for x in observed['candidate_consumer_ids'] if x in allowed]
            observed['candidate_consumers']={k:x for k,x in observed['candidate_consumers'].items() if int(k) in allowed}
            state['reference_parameter_observation']=witness
            self.boundary();sketch,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.request['sketch_spec']);state['sketch_state']=sketch;self.boundary()
            if self.created_names:
                raw=self.read(model,'FeatureByName',self.request['sketch_spec']['sketch_name']);require(raw is not None,'Exact created sketch missing')
                state['measured_sketch']=_read_sketch(self.sw,self.read(raw,'GetSpecificFeature2'),self.request['sketch_spec'])
                state['measured_circle']=_circle_sketch(state['measured_sketch'],self.request['sketch_spec']);self.boundary()
            if self.new_feature_id is not None:
                found=self.read(self.native['doc'],'GetCWObjectFromID',1,self.new_feature_id);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact new pocket lookup required')
                header,feature=read_header(found[0],self.native['doc'],self.read,self.typed,self.request['owner_setup_native_id'])
                state['target_header']=header;state['target_geometry']=_circle_feature(feature,self.native['doc'],self.tlb,self.read,self.typed)
                count=self.read(self.typed(feature,'ICWMillFeature'),'IGetIslandCount');state['target_geometry']['island_count']=count
                require(type(count) is int and count==0,'Closed circular pocket must contain no islands')
                state['target_catalogues']=read_catalogues(feature,read=self.read,typed=self.typed)
                if self.new_operation_ids:
                    targets=[next(x for x in state['operations'] if x['native_id']==oid) for oid in self.new_operation_ids]
                    native=dict(self.native,selected_feature=feature)
                    parameter_capture.capture_parameter_batch(state,native,targets,feature_id=self.new_feature_id,candidate_tool_native_id=self.v['candidate_tool_native_id'],expected_candidate_consumer_ids=consumer_ids,read=self.read,typed=self.typed,boundary=self.boundary,generation_observations=generation_observations,expected_operation_types=(0,))
            self.boundary();state['extended_capture_complete']=True;return state
        finally:
            if state.get('extended_capture_complete') is not True:state['capture_complete']=False
            self.persist()
    def create_sketch(self,before,pending,returned):
        state,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.request['sketch_spec'])
        require(delta.circular_state_equal({'sketch_state':state},{'sketch_state':before['sketch_state']}),'SW snapshot changed before sketch dispatch');_select_plane(state)
        self.report['sketch_creation']={}
        with self.guard() as g:
            def invoke():
                names=_create(self.sw,model,state,refs,self.boundary,self.report['sketch_creation']);self.created_names=list(names);returned(dict(created_names=list(names)));return names
            return g.dispatch_once(invoke,persist_pending=pending)
    def create_feature(self,pending,returned):
        with self.guard() as g:
            setups=_items(g.read(self.native['machine'],'IGetEnumSetups'),g.typed,g.read,8)
            matches=[x for x in setups if _object_id(self.native['doc'],x,g.read)==self.request['owner_setup_native_id']]
            require(len(matches)==1,'Exact owner setup required');setup=g.typed(matches[0],'ICWSetup')
            def invoke():
                value=_member(setup,'CreateMillFeature2',0,self.request['sketch_spec']['sketch_name'],False,self.request['depth_native'],False,False,False,False,0.,-1,False,0,0)
                returned(dict(return_type=type(value).__name__,nonnull=bool(value)));return value
            raw=g.dispatch_once(invoke,persist_pending=pending)
        require(raw is not None and bool(raw),'Factory returned no pocket; no replay');self.new_feature_id=_object_id(self.native['doc'],raw,self.read);return self.new_feature_id
    def insert_rough(self,state,pending,returned):
        choice=self.request['rough_definition'];row=dict(operation_type=0,default_operation_name=choice['default_operation_name'],default_operation_id=choice['default_operation_id'],feature_native_id=self.new_feature_id,feature_owner_setup_native_id=self.request['owner_setup_native_id'],operation_setup_native_id=self.request['operation_setup_native_id'])
        outer=self
        class Adapter:
            @contextmanager
            def guard(self):
                with outer.guard() as guard:
                    class Proxy:
                        read=staticmethod(guard.read);typed=staticmethod(guard.typed)
                        def dispatch_once(self,call,persist_pending):
                            def invoke():
                                value=call();returned(dict(return_type=type(value).__name__,nonnull=bool(value)));return value
                            return guard.dispatch_once(invoke,persist_pending=persist_pending)
                    yield Proxy()
        raw=definitions.insert_selected_once(Adapter(),self.native['doc'],row,self.request['insert_after_operation_native_id'],state['target_header'],pending)
        ident=_object_id(self.native['doc'],raw,self.read);self.new_operation_ids=[ident]
        self.boundary();generic,_=parameter_capture.read_generic_tool(raw,self.native['doc'],self.read,self.typed);self.new_own_tool_id=generic['native_id'];self.report['insert_own_tool_observation']=deepcopy(generic);self.persist();self.boundary();return ident
