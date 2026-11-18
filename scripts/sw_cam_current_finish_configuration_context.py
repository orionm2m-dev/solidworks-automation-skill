"""Configure one created Finish using existing context, setters, guarded Save and two full reads."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import math
from ctypes import HRESULT,POINTER,c_long,c_double
from scripts import sw_cam_current_circular_finish_context as creation
from scripts import sw_cam_saved_floor_wall_configure as setters
from scripts import sw_cam_partial_mill_pair_continuation as continuation
from scripts import sw_cam_current_finish_configuration_delta as delta
from scripts import sw_cam_chamfer_clearance_read as planes
from scripts import sw_cam_circular_nc_read as nc_reader
from scripts.sw_cam_comtypes import _load_type_library
from scripts import sw_cam_complete_dispatch_guard as complete_guard
ScopedCamDispatchGuard=complete_guard.CompleteCamDispatchGuard
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_inventory import _items
require=delta.require;exact=delta.exact

def preflight(tlb,definition_mode):
    creation.preflight(tlb,definition_mode);setters.preflight(tlb);nc_reader.preflight(tlb)
    cls=getattr(_load_type_library(tlb),'ICWOpSetup3');require(str(cls._iid_).upper()==planes.SETUP_IID,'Exact setup-plane interface required')
    for name,(kind,dispid)in planes.SETUP_FIELDS.items():
        matches=[m for m in cls._methods_ if m.name=='_get_'+name];require(len(matches)==1,'Exact setup getter required');m=matches[0]
        require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==(POINTER(c_long if kind=='long'else c_double),),'Setup getter ABI differs')
    return dict(native_calls=0,existing_setters=True,owned_plane_outputs=True,setup_plane_class=cls)

class Context(creation.Context):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        args=deepcopy(data['authority'].get('context_request',data['authority']['receipt']['request']));args.update(data['authority']['spec']);args.update(expected_source_sha256=v['expected_source_sha256'],receipt_path=v['receipt_path'])
        old=deepcopy(data['authority']['original_data']);old['pins']=deepcopy(data['pins'])
        super().__init__(sw,clsid,tlb,args,old,report,persist,runtime_check)
        self.settings=data;self.configuration_request=v;self.expected_route=deepcopy(data['state']);self.actual_route=deepcopy(data['state']['operations']);self.data['recovery']={'expected_state':deepcopy(data['state'])}
        self.wall_feature_id=data['authority']['feature_id'];self.wall_operation_id=data['authority']['operation_id'];self.wall_created_names=list(data['authority']['receipt']['created_names']);self.wall_own_tool=deepcopy(data['state']['operations'][-1]['assigned_tool'])
        self.config['pins']=deepcopy(data['pins']);self.append_plan=dict(self.config,state=self.expected_route);self._native_read_limit=24000
    def create_sketch(self,*a,**k):raise ValueError('Configuration cannot create sketches')
    def create_feature(self,*a,**k):raise ValueError('Configuration cannot create features')
    def insert_finish(self,*a,**k):raise ValueError('Configuration cannot insert')
    verify_owned_identity_only=continuation.Context.verify_owned_identity_only
    def guard(self):
        require(not getattr(self,'_capture_pin_scope',False),'Dispatch forbidden inside readonly capture');expected=self.boundary();self._guard_expected_document=deepcopy(expected)
        pins=continuation.unique_pins(list(self.pins)+list(self.settings['pins'])+[self.revision['cl_pin']]);require(1<=len(pins)<=128,'Complete immutable guard evidence exceeds bounded capacity')
        return ScopedCamDispatchGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=expected,source_sha256=self.source,evidence_pins=pins,verify_evidence=self.verify_files,verify_owned_process=self.verify_owned_identity_only,check_events=self.check)
    def capture(self,label,partial):
        self.append_plan=dict(self.config,state=self.expected_route);ids=[x['native_id']for x in self.expected_route['operations']if x['assigned_tool']['native_id']==self.v['candidate_tool_native_id']]
        try:
            state=creation.NativeCircularContext.capture(self,label,ids);self.last_document=deepcopy(state['document'])
            with self.selected_snapshot('planes_'+label):self.report.setdefault('plane_observations',{})[label]=self.read_planes()
            self.persist();return state
        finally:partial.clear();partial.update(deepcopy(self.report.get(label,{})));self.persist()
    def typed(self,raw,name):
        if name=='ICWOpSetup3':return self.read(raw,'QueryInterface',getattr(_load_type_library(self.tlb),name))
        return super().typed(raw,name)
    def read_planes(self):
        doc=self.native['doc'];setups=_items(self.read(self.native['machine'],'IGetEnumOpSetups'),self.typed,self.read,8);out=[]
        for oid in(366,self.wall_operation_id):
            row=next(x for x in self.expected_route['operations']if x['native_id']==oid);found=self.read(doc,'GetCWObjectFromID',3,oid);require(found[1]is True and _object_id(doc,found[0],self.read)==oid,'Exact floor/Finish plane owner required')
            owners=[x for x in setups if _object_id(doc,x,self.read)==row['setup_native_id']];require(len(owners)==1,'Exact plane setup required');diagnostic={}
            def pointer(owner,name,item):
                proxy=SimpleNamespace(**{name:lambda:planes.pointer_value(owner,name,item)})
                return self.read(proxy,name)
            values=planes.read_plane_parameters(found[0],owners[0],read=self.read,typed=self.typed,pointer_read=pointer,diagnostic=diagnostic,persist=self.persist)
            out.append(dict(operation_native_id=oid,feature_native_ids=deepcopy(row['linked_feature_ids']),setup_native_id=row['setup_native_id'],values=values))
        return out
    def compact_before_save(self):
        if self.settings['authority'].get('continuation_scope')=='CURRENT_CIRCULAR_FINISH_AFTER_SKETCH_V1':
            from scripts.sw_cam_current_circular_finish_after_sketch_context import Context as ContinuedSketchContext
            out=ContinuedSketchContext.compact_before_save(self)
        else:out=super().compact_before_save()
        with self.selected_snapshot('planes_presave'):out['plane_observations']=self.read_planes()
        self.report['compact_before_save']=deepcopy(out);self.persist();return out
    def target(self,row,read,typed):
        if row.get('operation_native_id')!=self.wall_operation_id:
            return super().target(row,read,typed)
        require(type(row.get('operation_native_id'))is int and type(row.get('feature_native_id'))is int and row['feature_native_id']==self.wall_feature_id and type(row.get('operation_kind'))is int and row['operation_kind']==1 and exact(row,self.settings['recipe']['row']),'Only the actual saved configured new Finish target allowed')
        return setters.Context.target(self,row,read,typed)
    def assign(self,row,*,pending,returned):
        setters.Context.assign(self,row,pending=pending,returned=returned);self.wall_own_tool=deepcopy(self.settings['candidate']['generic'])
    def set_change(self,row,change,*,pending,returned):
        require(exact(row,self.settings['recipe']['row'])and change['field']in delta.NOMINALS and exact(change['new'],delta.NOMINALS[change['field']]),'Only sealed new Finish fields supported')
        with self.guard()as g:
            owner,feature,interface,setter,mode,actual=self.field(row,change['field'],g.read,lambda raw,name:self.guarded_typed(g,raw,name),g._observe)
            if change['field']=='xy_feed':require(type(actual)is float and math.isfinite(actual)and actual>0,'Positive observed spindle-coupled XY feed required');self.report.setdefault('coupled_xy_before_write',{})[str(row['operation_native_id'])]=actual;self.persist()
            else:require(exact(actual,change['expected']),'Immediate expected field changed')
            new=change['new']
            def invoke():
                if mode=='property':value=getattr(owner,'_'+interface+'__com__set_'+setter)(new)
                elif mode=='absolute_feed':value=getattr(owner,'_ICWNCParam__com_SetLeadinFeedrate')(new['value_native'],False)
                else:value=_member(owner,setter,*((feature,new)if mode=='feature'else tuple(new)if mode in('pair','depth_pair')else(new,)))
                returned(value);return value
            value=g.dispatch_once(invoke,persist_pending=pending)
        require(type(value)is int and value==0,'Exact setter0 required; no replay')
        with self.guard()as g:observed=self.field(row,change['field'],g.read,lambda raw,name:self.guarded_typed(g,raw,name),g._observe)[-1]
        name='field:'+str(row['operation_native_id'])+':'+change['field'];self.report['actions'][name]['raw_immediate_readback']=deepcopy(observed);self.persist()
        if change['field']in delta.NUMERIC:
            if change['field']in('first_depth','max_depth'):delta.fields.checked(delta.fields.FIELDS[change['field']],observed);delta.numeric.fixed_double(observed[0],new[0])
            else:delta.numeric.fixed_double(observed,new)
        else:require(exact(observed,new),'Immediate field readback differs')
        return observed
