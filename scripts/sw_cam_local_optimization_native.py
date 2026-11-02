"""Existing-operation setters and generation; no insertion, assignment or NC writes."""
from copy import deepcopy
from scripts import sw_cam_local_generation as base
from scripts import sw_cam_local_optimization_fields as fields
from scripts import sw_cam_root_microtool_nc as micro
from scripts.sw_cam import _member
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_face_interfaces import query_face_interface
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_mill_inventory import _items

config=base.config;group=base.group;generation=base.generation

def forbidden_legacy_generation_hook(*args):
    raise ValueError('Only explicit existing-path NC/status generation route is permitted')


class NativeBackend(base.NativeBackend):
    def set_field(self,target,spec,value,pending):
        require(spec in fields.specs(target),'Only declared optimization setters allowed')
        plan=next(p for p in self.loaded['optimization_plan']['rows']if p['operation_native_id']==target['operation_native_id'])
        require(group.exact(value,fields.desired_values(plan)[spec[0]]),'Setter differs from sealed value')
        if spec!=fields.ROUGH_SPECS[2]:return config.NativeBackend.set_field(self,target,spec,value,pending)
        # FinCutAmt is declared ICWRghMillOp DISPID16, HRESULT(DOUBLE), no feature.
        with self.ctx.guard()as g:
            owner,feature,name=self.owner(g,target,spec)
            setter=getattr(owner,'_ICWRghMillOp__com__set_FinCutAmt')
            return g.dispatch_once(lambda:setter(value),persist_pending=pending)

    def _read_existing_nc(self,g,target):
        raw,_=self.target(g,target)
        tool,_=read_generic_tool(raw,self.doc,g.read,g.typed)
        require(group.exact(tool,target['assigned_tool']),'Assigned tool changed')
        op=g.typed(raw,'ICWOperation')
        expected=next(v for v in self.report['configured']['binding']['operations']if v['native_id']==target['operation_native_id'])
        generated=g.read(op,'GetIsToolpathGenerated')
        counts=[g.read(g.typed(v,'ICWToolpath'),'RecordCount')for v in _items(g.read(op,'IGetEnumToolpaths'),g.typed,g.read,1)]
        require(group.exact(generated,expected['toolpath_generated'])and group.exact(counts,expected['toolpath_record_counts']),'Selected retained/invalidation state changed before its explicit GTP')
        raw_nc=g.read(g.typed(raw,'ICWMillOperation'),'IGetNCParam')
        first=g.typed(raw_nc,'ICWNCParam')
        second=g._observe(lambda:query_face_interface(raw_nc,'ICWNCParam2',self.typelib_path,generated_pin=self.loaded['generated_pin']))
        return micro.values(micro.existing._values(g,first,second))

    def generate(self,target,pending):
        state=self.outcome(target);generation.status_contract(state,target,generated=None)
        with self.ctx.guard()as g:
            actual=self._read_existing_nc(g,target);micro.verify_final(actual)
            wanted=next(p for p in self.report['configured']['parameters']if p['operation_native_id']==target['operation_native_id'])['nc']['feeds_compensation']
            require(group.exact(actual,wanted),'NC changed after exact full configuration capture')
            raw,_=self.target(g,target);mill=g.typed(raw,'ICWMillOperation')
            require(type(g.read(self.ctx.app,'IsBackgroundProcessForGTPOver'))is bool,'Background diagnostic must remain Boolean, not an invented idle flag')
            # All reads/QI are complete before the irreversible dispatch claim.
            return g.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)


def audit_final_depth(typelib,pin):
    from ctypes import POINTER,c_double
    cls=config.finish.finish.interface_class('ICWRghMillOp',typelib,pin)
    member=[m for m in cls._methods_ if m.name=='_set_FinCutAmt']
    require(len(member)==1,'Exact FinCutAmt property setter required')
    config.finish.finish.prior.require_abi(member[0],16,(c_double,),(1,))
    require(hasattr(POINTER(cls),'_ICWRghMillOp__com__set_FinCutAmt'),'Raw strict-HRESULT property setter required')
    return dict(interface='ICWRghMillOp',member='FinCutAmt',dispid=16,feature_argument=False,native_called=False)
