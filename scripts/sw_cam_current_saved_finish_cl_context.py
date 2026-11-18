"""Read and export the already saved Finish; every model mutation is forbidden."""
from copy import deepcopy
from scripts import sw_cam_current_finish_generation_context as generated
require=generated.require
preflight=generated.preflight

class Context(generated.Context):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        super().__init__(sw,clsid,tlb,v,data,report,persist,runtime_check)
        require(data['saved_boundary_proof']['operation_id']==self.wall_operation_id,'Exact saved Finish identity required')
        # The inherited reader uses the prior durable GTP attempt to admit its
        # positive path. This is historical evidence, never a new GTP action.
        self.finish_attempted=[self.wall_operation_id]
        self.expected_route=deepcopy(data['recovery_saved_state'])
        self.actual_route=deepcopy(self.expected_route['operations'])
        self.settings['state']=deepcopy(self.expected_route)
        self.data['recovery']={'expected_state':deepcopy(self.expected_route)}
        self.append_plan=dict(self.config,state=self.expected_route)
        self._native_read_limit=18000
        report['historical_generation_operation_ids']=list(self.finish_attempted)
    def generate(self,*a,**k):raise ValueError('Export recovery cannot generate')
    def save(self,*a,**k):raise ValueError('Export recovery cannot save the model')
    def adopt_saved_source(self,*a,**k):raise ValueError('Export recovery cannot advance saved source')
    def assign(self,*a,**k):raise ValueError('Export recovery cannot assign tools')
    def set_change(self,*a,**k):raise ValueError('Export recovery cannot set parameters')
    def create_sketch(self,*a,**k):raise ValueError('Export recovery cannot create sketches')
    def create_feature(self,*a,**k):raise ValueError('Export recovery cannot create features')
    def insert_finish(self,*a,**k):raise ValueError('Export recovery cannot create operations')
