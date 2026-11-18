"""Native selected-pair context; reuses existing capture, Save and CL primitives."""
from copy import deepcopy
from scripts import sw_cam_saved_floor_wall_configure as config
from scripts import sw_cam_saved_floor_wall_generation_delta as delta
from scripts.sw_cam_current_generation_native import NativeGenerationContext
from scripts.sw_cam_append_finish_definitions import (batch,fields,read_catalogues,parameter_capture,
    retained_generation_counts,_snapshot,_read_sketch,_circle_sketch,read_header,_circle_feature)
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam import _member
require=config.require;exact=config.exact

class Context(config.Context):
    _captured_state_equal=staticmethod(delta.same)
    def __init__(self,sw,clsid,tlb,v,loaded,report,persist,runtime_check):
        args=deepcopy(loaded['binding']);args['expected_source_sha256']=v['expected_source_sha256']
        super().__init__(sw,clsid,tlb,args,loaded['context_data'],report,persist,runtime_check)
        self.generation_data=loaded;self.args=v;self.attempted=[];self.actual_route=deepcopy(loaded['context_data']['state']['operations']);self._native_read_limit=48000
    def assign(self,*a,**k):raise ValueError('Generation cannot assign tools')
    def set_change(self,*a,**k):raise ValueError('Generation cannot set parameters')
    def set_rough(self,*a,**k):raise ValueError('Generation cannot set Rough parameters')
    def set_nc(self,*a,**k):raise ValueError('Generation cannot set NC parameters')
    def create_sketch(self,*a,**k):raise ValueError('Generation cannot create geometry')
    def create_feature(self,*a,**k):raise ValueError('Generation cannot create features')
    def insert_rough(self,*a,**k):raise ValueError('Generation cannot insert operations')
    def target(self,row,read,typed):
        oid=row['operation_native_id'];require(oid in self.generation_data['selected_ids'],'Only configured selected target allowed')
        doc=self.native['doc'];found=read(doc,'GetCWObjectFromID',3,oid);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact selected lookup required');raw=found[0];op=typed(raw,'ICWOperation');mill=typed(raw,'ICWMillOperation')
        kind=read(mill,'OpernType');require(_object_id(doc,op,read)==oid and read(op,'Suppressed')is False and type(kind)is int and kind==row['operation_kind'],'Exact selected kind required')
        expected=next(r for r in self.actual_route if r['native_id']==oid)
        generated=read(op,'GetIsToolpathGenerated');paths=_items(read(op,'IGetEnumToolpaths'),typed,read,1)
        counts=[read(typed(p,'ICWToolpath'),'RecordCount')for p in paths]
        require(type(generated)is bool and generated is expected['toolpath_generated']and exact(counts,expected['toolpath_record_counts']),'Immediate selected generation/count differs')
        require(generated is(oid in self.attempted),'Unattempted or incomplete selected generation')
        require([_object_id(doc,x,read)for x in _items(read(op,'IGetAllFeatures'),typed,read,2)]==[row['feature_native_id']],'Exact feature link required')
        generic,_=config.writer.captures.read_generic_tool(op,doc,read,typed);require(exact(generic,expected['assigned_tool']),'Selected current tool changed')
        found=read(doc,'GetCWObjectFromID',1,row['feature_native_id']);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True and _object_id(doc,found[0],read)==row['feature_native_id'],'Exact feature required');return raw,found[0],mill
    def generate(self,oid,state,*,pending,returned):
        ids=self.generation_data['selected_ids'];require(self.attempted==ids[:len(self.attempted)]and len(self.attempted)<2 and oid==ids[len(self.attempted)],'Only next selected operation may generate once')
        row=next(r for r in self.config['recipe']['rows']if r['operation_native_id']==oid)
        with self.guard()as guard:
            raw,feature,mill=self.target(row,guard.read,guard.typed)
            generic,tool=config.writer.captures.read_generic_tool(raw,self.native['doc'],guard.read,guard.typed)
            require(exact(config.writer.captures.read_tool_dimensions(tool,generic,guard),self.config['candidate']),'Immediate full selected cutter profile differs')
            require(type(guard.read(self.app,'IsBackgroundProcessForGTPOver'))is bool,'Background diagnostic must be Boolean; not an idle permission')
            def claim():pending();self.attempted.append(oid)
            def invoke():value=_member(mill,'GenerateToolpath');returned(value);return value
            return guard.dispatch_once(invoke,persist_pending=claim)
    export_cl=NativeGenerationContext.export_cl
    parse_cl=NativeGenerationContext.parse_cl

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
            base=self.append_plan['state'];expected=[x['native_id']for x in base['operations']]+[x['native_id']for x in self.added_rows]
            require([x['native_id']for x in state['operations']]==expected,'Exact retained prefix and appended IDs required')
            delta.observed_rows(base['operations'],state['operations'],self.generation_data['selected_ids'],self.attempted)
            self.actual_route=deepcopy(state['operations'])
            for row in state['operations'][len(base['operations']):]:require(row['toolpath_generated']is False and row['toolpath_record_counts']==[],'Appended Finish unexpectedly generated')
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
            state['cutting_context']=self.read_cutting()
            targets=[self.observe_target(row)for row in self.config['recipe']['rows']]
            draft=self.observe_draft();state[delta.PAIR_KEY]=dict(targets=targets,draft=draft)
            self.report.setdefault('target_observations',{})[label]=deepcopy(targets);self.report.setdefault('draft_observations',{})[label]=deepcopy(draft)
            self.boundary();state['extended_capture_complete']=True;return state
        finally:
            if state.get('extended_capture_complete') is not True:state['capture_complete']=False
            self.persist()
