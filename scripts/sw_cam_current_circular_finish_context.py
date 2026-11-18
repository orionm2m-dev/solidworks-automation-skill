"""Saved partial-result circle Finish adapter. Existing factory/readers reused."""
from copy import deepcopy
from pathlib import Path
from contextlib import contextmanager
from comtypes.automation import IDispatch
from scripts import sw_cam_partial_floor_wall_generation_context as recovery_context
from scripts import sw_cam_saved_floor_wall_generation_context as generation_context
from scripts.sw_cam_saved_floor_wall_generation_context import(config,delta,batch,fields,read_catalogues,parameter_capture,retained_generation_counts,_snapshot,_read_sketch,_circle_sketch,read_header,_circle_feature,_object_id,_items,_member,require,exact)
from scripts import sw_cam_current_circular_finish_delta as finish_delta
from scripts.sw_cam_current_circular_context import NativeCircularContext,preflight
from scripts.sw_cam_profile_sketch import _select_plane,_create
from scripts import sw_cam_guide_group_definitions as definitions

def deduplicate_json_pins(pins):
    unique={};normalized={}
    for pin in pins:
        key=str(Path(pin['path']).resolve()).casefold();value=deepcopy(pin)
        for field in('path','canonical_path'):
            if field in value:value[field]=str(Path(value[field]).resolve()).casefold()
        require(key not in normalized or exact(normalized[key],value),'Conflicting context authority pin metadata')
        normalized.setdefault(key,value);unique.setdefault(key,pin)
    return list(unique.values())

class Context(recovery_context.Context):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        rd=data['recovery_data'];args=deepcopy(rd['failed_request']);args.update(expected_source_sha256=v['expected_source_sha256'],receipt_path=v['receipt_path'])
        generation_context.Context.__init__(self,sw,clsid,tlb,args,rd['loaded'],report,persist,runtime_check)
        self.partial_data=rd;self.saved_phase=True;self.finish_data=data;self.wall_request=v
        self.expected_route=deepcopy(data['state']);self.actual_route=deepcopy(data['state']['operations']);self.data['recovery']={'expected_state':deepcopy(data['state'])}
        self.wall_feature_id=None;self.wall_operation_id=None;self.wall_created_names=[];self.wall_own_tool=None
        self.config=deepcopy(self.config);self.config['pins']=deepcopy(data['pins']);self.pins.extend(p for p in data['pins']if Path(p['path']).suffix.lower()=='.json'and p not in self.pins)
        self.append_plan=dict(self.config,state=self.expected_route)
        self.pins=deduplicate_json_pins(self.pins);self._native_read_limit=48000
        from scripts.sw_cam_current_circular_finish_owner import apply_live_owner
        apply_live_owner(self,v,data)
    def generate(self,*a,**k):raise ValueError('Definition-only circle adapter cannot generate')
    def export_cl(self,*a,**k):raise ValueError('Definition-only circle adapter cannot export CL')
    def capture(self,label,partial):
        self.append_plan=dict(self.config,state=self.expected_route)
        ids=list(self.expected_route['parameter_batch']['candidate_consumer_ids'])
        if self.wall_operation_id is not None and self.wall_own_tool['native_id']==self.v['candidate_tool_native_id']:ids.append(self.wall_operation_id)
        try:
            state=NativeCircularContext.capture(self,label,ids);self.last_document=deepcopy(state['document']);return state
        finally:partial.clear();partial.update(deepcopy(self.report.get(label,{})));self.persist()
    def create_sketch(self,pending,returned):
        spec=self.wall_request['sketch_spec'];state,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],spec);_select_plane(state)
        self.report['sketch_creation']={}
        with self.guard()as g:
            def invoke():
                names=_create(self.sw,model,state,refs,self.boundary,self.report['sketch_creation']);self.wall_created_names=list(names);returned(dict(created_names=list(names)));return names
            return g.dispatch_once(invoke,persist_pending=pending)
    def create_feature(self,pending,returned):
        v=self.wall_request
        with self.guard()as g:
            setups=_items(g.read(self.native['machine'],'IGetEnumSetups'),g.typed,g.read,8);matches=[x for x in setups if _object_id(self.native['doc'],x,g.read)==v['owner_setup_native_id']]
            require(len(matches)==1,'Exact owner setup required');owner=g.typed(matches[0],'ICWSetup')
            def invoke():
                raw=_member(owner,'CreateMillFeature2',0,v['sketch_spec']['sketch_name'],False,v['depth_native'],False,False,False,False,0.,-1,False,0,0);returned(dict(return_type=type(raw).__name__,nonnull=bool(raw)));return raw
            raw=g.dispatch_once(invoke,persist_pending=pending)
        require(raw is not None and bool(raw),'No feature returned; no replay')
        with self.guard()as g:self.wall_feature_id=_object_id(self.native['doc'],raw,g.read)
        return self.wall_feature_id
    def insert_finish(self,state,pending,returned):
        v=self.wall_request;choice=v['finish_definition'];row=dict(operation_type=1,default_operation_name=choice['default_operation_name'],default_operation_id=choice['default_operation_id'],feature_native_id=self.wall_feature_id,feature_owner_setup_native_id=v['owner_setup_native_id'],operation_setup_native_id=v['operation_setup_native_id'])
        # Persist the primitive return inside the dispatch, before exit guard checks.
        outer=self
        class Adapter:
            @contextmanager
            def guard(self):
                with outer.guard()as guard:
                    class Proxy:
                        read=staticmethod(guard.read);typed=staticmethod(guard.typed)
                        def dispatch_once(self,call,persist_pending):
                            def invoke():
                                raw=call();returned(dict(return_type=type(raw).__name__,nonnull=bool(raw)));return raw
                            return guard.dispatch_once(invoke,persist_pending=persist_pending)
                    yield Proxy()
        raw=definitions.insert_selected_once(Adapter(),self.native['doc'],row,v['insert_after_operation_native_id'],state[finish_delta.EXTRA]['target_header'],pending)
        with self.guard()as g:
            self.wall_operation_id=_object_id(self.native['doc'],raw,g.read);self.wall_own_tool,_=parameter_capture.read_generic_tool(raw,self.native['doc'],g.read,g.typed)
        self.report['actual_insert_own_tool']=deepcopy(self.wall_own_tool);self.persist();return self.wall_operation_id
    def read_new_circle(self,state):
        out={};spec=self.wall_request['sketch_spec'];doc=self.native['doc']
        if self.wall_created_names:
            model=self._current_sw_model;raw=self.read(model,'FeatureByName',spec['sketch_name']);require(raw is not None,'Actual new sketch missing');out['measured_sketch']=_read_sketch(self.sw,self.read(raw,'GetSpecificFeature2'),spec);out['measured_circle']=_circle_sketch(out['measured_sketch'],spec)
        if self.wall_feature_id is not None:
            found=self.read(doc,'GetCWObjectFromID',1,self.wall_feature_id);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact newly created feature required')
            header,feature=read_header(found[0],doc,self.read,self.typed,self.wall_request['owner_setup_native_id']);out['target_header']=header;out['target_geometry']=_circle_feature(feature,doc,self.tlb,self.read,self.typed);count=self.read(self.typed(feature,'ICWMillFeature'),'IGetIslandCount');require(type(count)is int and count==0,'No new circle islands allowed');out['target_geometry']['island_count']=count;out['target_catalogues']=read_catalogues(feature,read=self.read,typed=self.typed)
            if self.wall_operation_id is not None:
                row=next(r for r in state['operations']if r['native_id']==self.wall_operation_id);found=self.read(doc,'GetCWObjectFromID',3,self.wall_operation_id);require(found[1]is True and _object_id(doc,found[0],self.read)==self.wall_operation_id,'Exact new operation required')
                def typed(raw,name):return self.read(raw,'QueryInterface',IDispatch)if name=='IDispatch'else self.typed(raw,name)
                identity=dict(operation_kind=1,operation_native_id=self.wall_operation_id,feature_native_id=self.wall_feature_id,tool_native_id=row['assigned_tool']['native_id']);observed={};config.reader.read_target(found[0],feature,identity,self.read,typed,lambda n,d:config.reader.finish.nc.lead_pointer_value(n,d),self.persist,observed);out['operation_observation']=config.recipe_core.compact_target(observed)
        return out

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
                for row in state['operations'][len(base['operations']):]:require(row['mill_operation_type']==1 and row['suppressed']is False and row['toolpath_generated']is False and exact(row['toolpath_record_counts'],[])and row['linked_feature_ids']==[self.wall_feature_id],'Only actual ungenerated new circle Finish allowed')
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

    def observe_new(self,label):
        with self.selected_snapshot(label):
            sketch,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.wall_request['sketch_spec']);self._current_sw_model=model
            out=dict(sketch_state=sketch,new_circle=self.read_new_circle(self.finish_data['state']))
            self.report.setdefault('targeted_observations',{})[label]=deepcopy(out);self.persist();return out
    def compact_before_save(self):
        with self.selected_snapshot('compact_before_save'):
            actual={};start=self.boundary()
            def boundary():require(self.boundary()==start,'Identity changed during compact read')
            self.native=batch.current._capture(self.app,self.tlb,self.read,self.typed,actual,self.v,boundary,verify_operation_pins=False);self.actual_route=deepcopy(actual['operations'])
            sketch,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.wall_request['sketch_spec']);self._current_sw_model=model
            circle=self.read_new_circle(actual)
            targets=[self.observe_target(row)for row in self.config['recipe']['rows']];draft=self.observe_draft()
            selected=self.config['recipe']['rows'][0];raw,feature,mill=self.target(selected,self.read,self.typed);generic,tool=config.writer.captures.read_generic_tool(raw,self.native['doc'],self.read,self.typed)
            class ReadCallbacks:
                read=staticmethod(self.read);typed=staticmethod(self.typed)
            candidate=config.writer.captures.read_tool_dimensions(tool,generic,ReadCallbacks())
            out=dict(scope='CIRCULAR_FINISH_COMPACT_PRE_SAVE_V1',inventory=actual,sketch_state=sketch,new_circle=circle,selected_targets=targets,retained_draft=draft,shared_candidate=candidate,full_parameter_capture=False)
            self.report['compact_before_save']=deepcopy(out);self.persist();return out
