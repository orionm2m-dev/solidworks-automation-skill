"""current_saved generation 的类型化桥接；复用配置会话、读取器和 SaveCLFile。"""
from copy import deepcopy
from pathlib import Path
import hashlib
from scripts import sw_cam_current_saved_parameter_batch as batch
from scripts import sw_cam_current_saved_generation_delta as delta
from scripts import sw_cam_current_saved_generation as engine
from scripts import sw_cam_mill_current_compound_read as current
from scripts import sw_cam_current_parameter_capture as captures
from scripts import sw_cam_mill_current_parameters as parameters
from scripts import sw_cam_mill_current_append as append
from scripts.sw_cam import _member
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_guide_group_reader import read_catalogues
from scripts.sw_cam_guide_group_definitions import read_own_nc
from scripts.sw_cam_deep_guide_cl import _fresh_path
from scripts.sw_cam_thread_postprocess import _controller
from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes

require=engine.require


class NativeGenerationContext(batch.NativeBatchContext):
    """保持配置会话门禁，显式观察已尝试目标的 generated/count；默认读取器不变。"""
    def __init__(self,sw,clsid,tlb,args,loaded,report,persist,runtime_check):
        v=deepcopy(loaded['binding']);v['expected_source_sha256']=args['expected_source_sha256']
        authority=parameters.load_authority(loaded['binding'])
        data=dict(pins={k:deepcopy(loaded['pins'][k]) for k in ('request','result','authority','recipe')},authority=authority)
        super().__init__(sw,clsid,tlb,v,data,report,persist,runtime_check)
        self.args=args;self.loaded=loaded;self.attempted=[];self.last_document=None;self.entered=False;self.closed=False
        self.consumer_ids=deepcopy(loaded['state']['parameter_batch']['candidate_consumer_ids'])
        self.report.setdefault('native_read_count',0)
    def verify_files(self):
        super().verify_files()
        _,pin=read_pin(self.loaded['pin']['path'],self.loaded['pin']['sha256'])
        require(pin==self.loaded['pin'],'Completed configuration authority changed')
        for p in self.loaded.get('recovery_pins',{}).values():require(read_pin(p['path'],p['sha256'])[1]==p,'Recovery authority history changed')
    def guard(self):
        expected=self.boundary()
        return ScopedCamDispatchGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=expected,source_sha256=self.source,evidence_pins=list(self.data['pins'].values())+[self.loaded['pin']]+list(self.loaded.get('recovery_pins',{}).values()),verify_evidence=self.verify_files,verify_owned_process=lambda:self.boundary(),check_events=self.check)
    def start(self):
        self.__enter__();self.entered=True
    def capture(self,label,partial):
        state=partial;state.clear();self.report['phase']=label;self.persist();start=self.boundary()
        def boundary():require(self.boundary()==start,'Identity changed during generation capture')
        try:
            self.native=current._capture(self.app,self.tlb,self.read,self.typed,state,self.v,boundary,verify_operation_pins=False)
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
            observations={}
            for row in targets:
                if row['toolpath_generated']:
                    require(row['native_id'] in self.attempted,'An unattempted parameter target became generated')
                    require(len(row['toolpath_record_counts'])==1 and type(row['toolpath_record_counts'][0]) is int and 0<row['toolpath_record_counts'][0]<=delta.MAX_RECORDS,'Bounded positive observed generated count required')
                    observations[row['native_id']]=deepcopy(row['toolpath_record_counts'])
            captures.capture_parameter_batch(state,self.native,targets,feature_id=self.v['expected_feature_native_id'],candidate_tool_native_id=self.v['candidate_tool_native_id'],expected_candidate_consumer_ids=self.consumer_ids,read=self.read,typed=self.typed,boundary=boundary,generation_observations=observations)
            boundary();self.last_document=deepcopy(start);return state
        finally:self.persist()
    def generate(self,oid,state,*,pending,returned):
        row=next(x for x in state['operations']if x['native_id']==oid)
        require(oid in self.loaded['selected_ids'] and oid not in self.attempted,'Only a unique requested operation may generate')
        with self.guard() as guard:
            raw=captures.own_operation(row,self.native,guard.read,guard.typed)
            require(row['suppressed'] is False and row['toolpath_generated'] is False and row['toolpath_record_counts']==[] and row['mill_operation_type']==0,'Only explicit ungenerated own Rough may generate')
            generic,tool=captures.read_generic_tool(raw,self.native['doc'],guard.read,guard.typed)
            parameter=next(p for p in state['operation_parameters']if p['operation_native_id']==oid)
            require(delta.equal(captures.read_tool_dimensions(tool,generic,guard),parameter['tool']),'Immediate selected full tool dimensions changed')
            mill=guard.typed(raw,'ICWMillOperation')
            require(type(guard.read(self.app,'IsBackgroundProcessForGTPOver')) is bool,'Background diagnostic must be Boolean; it is not an idle permission')
            def claim():pending();self.attempted.append(oid)
            def invoke():
                value=_member(mill,'GenerateToolpath');returned(value);return value
            guard.dispatch_once(invoke,persist_pending=claim)
    def save(self,*,returned):
        seen=[]
        def observe(value):seen.append(value);returned(value)
        super().save(lambda:require(self.report['actions']['SaveActiveDocument']['native_dispatch_pending'] is True,'Save pending must already be durable'),observe)
        require(len(seen)==1,'One actual Save return required');return seen[0]
    def adopt_saved_source(self,report):
        require(report.get('native_return_type')=='int' and type(report.get('native_return_value')) is int and report['native_return_value']==0,'No source transition before strict Save return')
        doc=self.boundary();require(doc['needs_save'] is False and self.source==_file_hash(self.v['expected_document_path']),'Exact clean saved source required')
        return self.source
    def export_cl(self,label,state,rows,diagnostic,*,pending,returned):
        path=self.args['before_cl_path'if label=='preCL'else'saved_cl_path'];output=_fresh_path(path);canonical=str(output.resolve())
        source=self.source;document=self.boundary();diagnostic.update(source_sha256=source,document=deepcopy(document),output_path=str(output),native_dispatch_pending=False,native_call_returned=False)
        before={};diagnostic['before']=before;self.persist();self.capture(label+'_before',before)
        require(delta.equal(before,state),'CL pre-capture differs from exact expected current state')
        with self.guard() as guard:
            part=guard.typed(self.native['doc'],'ICWPartDoc');machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine')
            require(guard.read(machine,'MachType')==1,'Current MILL machine required')
            target=guard.typed(machine,'ICWMachine5');controller=_controller(guard.read(target,'GetController2'));diagnostic['controller']=controller;self.persist()
            output.parent.mkdir();require(not output.parent.is_symlink() and str(output.resolve())==canonical and not output.exists(),'Exclusive CL output identity changed')
            diagnostic['output_directory_created']=True;self.persist()
            def claim():diagnostic['native_dispatch_pending']=True;pending()
            def invoke():
                value=_member(target,'SaveCLFile',str(output));diagnostic.update(native_call_returned=True,native_dispatch_pending=False);returned(value);return value
            result=guard.dispatch_once(invoke,persist_pending=claim)
        require(type(result) is int and result==0,'Exact SaveCLFile int0 required')
        after={};diagnostic['after']=after;self.persist();self.capture(label+'_after',after)
        require(delta.equal(before,after),'CL export changed full captured configuration')
        with self.guard() as guard:
            machine=guard.typed(self.native['machine'],'ICWMachine5');controller_after=_controller(guard.read(machine,'GetController2'))
        require(controller_after==controller and self.boundary()==document and self.source==source,'CL export changed controller/source/document')
        require(output.is_file() and not output.is_symlink() and not output.parent.is_symlink() and str(output.resolve())==canonical and 0<output.stat().st_size<=64*1024*1024 and sorted(x.name for x in output.parent.iterdir())==[output.name],'Bounded unique CL output required')
        raw=output.read_bytes();sha=hashlib.sha256(raw).hexdigest();parsed=parse_generic_cl_bytes(raw,expected_block_record_counts=[r['toolpath_record_counts'][0]for r in rows])
        require(parsed['parse_complete'] is True and parsed['native_count_matches'] is True and parsed['declared_units']==['MM'],'Complete metric native-count-matched CL required')
        require(_file_hash(output)==sha,'CL file changed while parsing')
        diagnostic.update(output=dict(path=str(output),sha256=sha,bytes=len(raw)),expected_generated_operations=deepcopy(rows),output_verified=True,readback_verified=True,parse_summary=dict(parse_complete=True,native_count_matches=True,blocks=len(parsed['operation_blocks']),declared_units=parsed['declared_units']))
        self.boundary();self.persist();return diagnostic
    def parse_cl(self,result):
        p=Path(result['output']['path']);require(p.is_file() and not p.is_symlink() and p.stat().st_size==result['output']['bytes'] and _file_hash(p)==result['output']['sha256'],'Pinned exported CL changed')
        raw=p.read_bytes();require(hashlib.sha256(raw).hexdigest()==result['output']['sha256'],'CL changed during read')
        return parse_generic_cl_bytes(raw,expected_block_record_counts=[r['toolpath_record_counts'][0]for r in result['expected_generated_operations']])
    def may_capture_failure(self):
        try:self.boundary();return self.entered and not self.closed
        except Exception:return False
    def finish(self):
        require(self.last_document==self.boundary(),'Final document changed')
    def close(self):
        if not self.entered or self.closed:return
        try:self.__exit__(None,None,None)
        finally:self.closed=True
        clean_events(dict(messages=self.session.summary()));self.report['messages']=self.session.summary()
        self.runtime_check();doc=self.identity()
        if self.report.get('readback_verified') is True:require(doc==self.last_document,'Document changed after cleanup')
