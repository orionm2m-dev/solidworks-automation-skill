"""One configured Finish GTP adapter; existing full capture, generator and Save reused."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace,MethodType
import hashlib
from scripts import sw_cam_current_finish_configuration_context as configuration
from scripts import sw_cam_current_finish_generation_delta as generation_delta
from scripts import sw_cam_current_finish_generation_cl as comparison
from scripts import sw_cam_immutable_pin_decode_cache as pin_verifier
from scripts import sw_cam_current_generation_native as native_generation
from scripts import sw_cam_saved_floor_wall_generation_context as selected_generation
from scripts.sw_cam_current_circular_finish_context import (config,delta,batch,fields,read_catalogues,parameter_capture,retained_generation_counts,_snapshot,_read_sketch,_circle_sketch,read_header,_circle_feature,_object_id,_items,_member,require,exact,finish_delta)
from scripts.sw_cam_thread import _file_hash
preflight=configuration.preflight

def current_source_pins(pins,path,current_sha,original_sha,report):
    source=str(Path(path).resolve()).casefold();out=[]
    if current_sha!=original_sha:
        for key in('model_saved','save_returned_zero','save_readback_verified','source_update_verified'):require(report.get(key)is True,'Source guard transition requires verified Save: '+key)
        require(report.get('source_after_sha256')==report.get('saved_file_sha256')==current_sha,'Exact actual saved source required')
        action=report['actions']['SaveActiveDocument'];require(action.get('attempted')is True and action.get('returned')is True and action.get('native_dispatch_pending')is False and action.get('native_return_type')=='int'and type(action.get('native_return_value'))is int and action['native_return_value']==0,'Strict actual Save0 required for source pin transition')
    for pin in pins:
        if str(Path(pin['path']).resolve()).casefold()==source:
            require(pin['sha256']==original_sha,'Only original current source pin may advance');out.append(dict(path=str(Path(path)),sha256=current_sha))
        else:out.append(deepcopy(pin))
    return out

class Context(configuration.Context):
    verify_files=pin_verifier.verify_files
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        cv=deepcopy(data['configuration_request']);cv.update(expected_source_sha256=v['expected_source_sha256'],receipt_path=v['receipt_path'])
        super().__init__(sw,clsid,tlb,cv,data['configuration_data'],report,persist,runtime_check)
        self.generation_settings=data;self.generation_request=deepcopy(v);self.finish_attempted=[];self._native_read_limit=36000
    def guard(self):
        require(not getattr(self,'_capture_pin_scope',False),'Dispatch forbidden inside readonly capture');expected=self.boundary();self._guard_expected_document=deepcopy(expected)
        pins=configuration.continuation.unique_pins(list(self.pins)+list(self.settings['pins'])+[self.revision['cl_pin']]);pins=current_source_pins(pins,self.v['expected_document_path'],self.source,self.generation_request['expected_source_sha256'],self.report)
        return configuration.complete_guard.CompleteCamDispatchGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=expected,source_sha256=self.source,evidence_pins=pins,verify_evidence=self.verify_files,verify_owned_process=self.verify_owned_identity_only,check_events=self.check)
    def assign(self,*a,**k):raise ValueError('Generation cannot assign tools')
    def set_change(self,*a,**k):raise ValueError('Generation cannot set parameters')
    def generate(self,oid,state,*,pending,returned):
        require(oid==self.wall_operation_id and type(oid)is int and self.finish_attempted==[],'One actual new Finish may generate once')
        generation_delta.select(state,oid,self.wall_feature_id)
        row=deepcopy(self.settings['recipe']['row'])
        proxy=SimpleNamespace(generation_data={'selected_ids':[oid]},config={'recipe':{'rows':[row]},'candidate':deepcopy(self.settings['candidate'])},native=self.native,actual_route=deepcopy(self.actual_route),attempted=self.finish_attempted,guard=self.guard,app=self.app)
        proxy.target=MethodType(selected_generation.Context.target,proxy)
        return selected_generation.Context.generate(proxy,oid,state,pending=pending,returned=returned)

    def _capture_readonly(self,label,consumer_ids=None,generation_observations=None,attempted_generation_ids=()):
            # 新操作只在实际 GTP attempt 后接受当次 route 返回的正记录数。
            if consumer_ids is None:consumer_ids=list(self.reference_consumers)+([self.new_operation_ids[0]] if self.new_operation_ids and getattr(self,'new_own_tool_id',None)==self.v['candidate_tool_native_id'] else [])
            require(not attempted_generation_ids and generation_observations is None,'Mixed generation uses only its durable explicit attempt list')
            state={};self.report[label]=state
            if not getattr(self,'_capture_journal_managed',False):self.report['captures'].append(label)
            self.persist();start=self.boundary()
            def boundary():require(self.boundary()==start,'Identity changed during reference capture')
            try:
                self.native=batch.current._capture(self.app,self.tlb,self.read,self.typed,state,self.v,boundary,verify_operation_pins=False)
                state['document']=deepcopy(start)
                base=self.finish_data['state'];extra=[] if self.wall_operation_id is None else[self.wall_operation_id]
                require([x['native_id']for x in state['operations']]==[x['native_id']for x in base['operations']]+extra,'Exact saved29 and one explicitly returned Finish required')
                require(exact(state['operations'][:len(base['operations'])],base['operations']),'Saved29 route/tool/positive or empty paths changed')
                self.actual_route=deepcopy(state['operations'])
                generation_delta.observed_rows(self.generation_settings['state']['operations'],state['operations'],self.wall_operation_id,self.wall_feature_id,self.finish_attempted)
                generation_observations={self.oid:retained_generation_counts(base,self.oid)}
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
                self.boundary();sketch,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.request['sketch_spec']);state['sketch_state']=sketch;self._current_sw_model=model;self.boundary()
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
                state['cutting_context']=self.read_cutting()
                targets=[self.observe_target(row)for row in self.config['recipe']['rows']]
                draft=self.observe_draft();state[delta.PAIR_KEY]=dict(targets=targets,draft=draft)
                self.report.setdefault('target_observations',{})[label]=deepcopy(targets);self.report.setdefault('draft_observations',{})[label]=deepcopy(draft)
                state[finish_delta.EXTRA]=self.read_new_circle(state)
                self.boundary();state['extended_capture_complete']=True;return state
            finally:
                if state.get('extended_capture_complete') is not True:state['capture_complete']=False
                self.persist()

    def export_cl(self,label,state,rows,diagnostic,*,pending,returned):
        require(label=='postCL'and self.finish_attempted==[self.wall_operation_id],'Only saved newly generated Finish CL export permitted')
        generation_delta.select(state,self.wall_operation_id,self.wall_feature_id,generated=True)
        require(exact(rows,generation_delta.positive_rows(state)),'Exact positive-only export mapping required')
        output=native_generation._fresh_path(self.generation_request['saved_cl_path']);canonical=str(output.resolve());source=self.source;document=self.boundary()
        require(document['needs_save']is False and state['sketch_state']['saved_file_sha256']==source,'Saved clean CL source required')
        diagnostic.update(source_sha256=source,document=deepcopy(document),output_path=str(output),native_dispatch_pending=False,native_call_returned=False,capture_policy='full_saved_then_compact_export_boundaries')
        before=self.compact_before_save();diagnostic['before_compact']=deepcopy(before);diagnostic['before_proof']=generation_delta.verify_compact(state,before,self.generation_settings['planes']);self.persist()
        with self.guard()as guard:
            part=guard.typed(self.native['doc'],'ICWPartDoc');machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine');require(type(guard.read(machine,'MachType'))is int and guard.read(machine,'MachType')==1,'Current MILL machine required')
            target=guard.typed(machine,'ICWMachine5');controller=native_generation._controller(guard.read(target,'GetController2'));diagnostic['controller']=controller;self.persist()
            output.parent.mkdir();require(not output.parent.is_symlink()and str(output.resolve())==canonical and not output.exists(),'Exclusive CL output changed');diagnostic['output_directory_created']=True;self.persist()
            def claim():diagnostic['native_dispatch_pending']=True;pending()
            def invoke():
                value=_member(target,'SaveCLFile',str(output));diagnostic.update(native_call_returned=True,native_dispatch_pending=False);returned(value);return value
            result=guard.dispatch_once(invoke,persist_pending=claim)
        require(type(result)is int and result==0,'Exact SaveCLFile int0 required; no replay')
        after=self.compact_before_save();diagnostic['after_compact']=deepcopy(after);diagnostic['after_proof']=generation_delta.verify_compact(state,after,self.generation_settings['planes']);require(exact(before,after),'CL export changed compact current context')
        with self.guard()as guard:
            machine=guard.typed(self.native['machine'],'ICWMachine5');controller_after=native_generation._controller(guard.read(machine,'GetController2'))
        require(controller_after==controller and self.boundary()==document and self.source==source,'CL export changed source/controller/document')
        require(output.is_file()and not output.is_symlink()and not output.parent.is_symlink()and str(output.resolve())==canonical and 0<output.stat().st_size<=64*1024*1024 and sorted(x.name for x in output.parent.iterdir())==[output.name],'Bounded unique CL output required')
        raw=output.read_bytes();sha=hashlib.sha256(raw).hexdigest();cl=self.generation_settings['CL_baseline']
        proof,projected,observed=comparison.compare(raw,Path(cl['raw_pin']['path']).read_bytes(),Path(cl['historical_raw_pin']['path']).read_bytes(),cl['historical_rows'],cl['rows'],rows,baseline_proof=cl['proof'],added_native_id=self.wall_operation_id)
        require(_file_hash(output)==sha,'Exported CL changed during read');self.verify_files()
        diagnostic.update(output=dict(path=str(output),sha256=sha,bytes=len(raw)),expected_generated_operations=deepcopy(rows),output_verified=True,readback_verified=True,comparison_proof=proof,raw_parse_summary=dict(parse_complete=observed['parse_complete'],structure_issues=observed['structure_issues'],block_command_counts=observed['block_command_counts']),comparison_parse_summary=dict(parse_complete=projected['parse_complete'],native_count_matches=projected['native_count_matches'],positive_blocks=len(projected['operation_blocks'])),raw_CL_modified=False)
        self.boundary();self.persist();return diagnostic
