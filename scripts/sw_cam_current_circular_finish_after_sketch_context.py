"""Reuse a returned D18 sketch; reference metadata always uses the original spec."""
from copy import deepcopy
from scripts import sw_cam_current_circular_finish_context as base
from scripts.sw_cam_current_circular_finish_context import preflight,config,batch,_snapshot,require,exact

class Context(base.Context):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        args=deepcopy(data['original_request']);args.update(data['spec']);args['receipt_path']=v['receipt_path']
        super().__init__(sw,clsid,tlb,args,data,report,persist,runtime_check)
        self.wall_created_names=list(data['history']['created_names'])
        self.data['recovery']['expected_state']['document']['needs_save']=True
        self.continuation_request=deepcopy(v)
    def create_sketch(self,*a,**k):raise ValueError('Existing sketch must never be recreated')

    def observe_new(self,label):
        with self.selected_snapshot(label):
            sketch,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.request['sketch_spec']);self._current_sw_model=model
            out=dict(sketch_state=sketch,new_circle=self.read_new_circle(self.finish_data['state']))
            self.report.setdefault('targeted_observations',{})[label]=deepcopy(out);self.persist();return out
    def compact_before_save(self):
        with self.selected_snapshot('compact_before_save'):
            actual={};start=self.boundary()
            def boundary():require(self.boundary()==start,'Identity changed during compact read')
            self.native=batch.current._capture(self.app,self.tlb,self.read,self.typed,actual,self.v,boundary,verify_operation_pins=False);self.actual_route=deepcopy(actual['operations'])
            sketch,model,refs=_snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.request['sketch_spec']);self._current_sw_model=model
            circle=self.read_new_circle(actual)
            targets=[self.observe_target(row)for row in self.config['recipe']['rows']];draft=self.observe_draft()
            selected=self.config['recipe']['rows'][0];raw,feature,mill=self.target(selected,self.read,self.typed);generic,tool=config.writer.captures.read_generic_tool(raw,self.native['doc'],self.read,self.typed)
            class ReadCallbacks:
                read=staticmethod(self.read);typed=staticmethod(self.typed)
            candidate=config.writer.captures.read_tool_dimensions(tool,generic,ReadCallbacks())
            out=dict(scope='CIRCULAR_FINISH_COMPACT_PRE_SAVE_V1',inventory=actual,sketch_state=sketch,new_circle=circle,selected_targets=targets,retained_draft=draft,shared_candidate=candidate,full_parameter_capture=False)
            self.report['compact_before_save']=deepcopy(out);self.persist();return out
