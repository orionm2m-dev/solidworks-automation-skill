"""Read fixed guide recipe scalar fields in one existing guarded read batch.

No setter or dispatch is exposed. The caller has established backend.doc in a
fresh full capture. Same owner/document/source guards are retained; configuration
binding is checked inside the outer batch boundary without nesting more guards.
"""
from copy import deepcopy
import math
from time import perf_counter
from scripts import sw_cam_guide_group_configuration as config
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_rough_firstcut import require

reader, guide, group = config.reader, config.guide, config.group
TARGETS = ((322,82,0),(324,82,1),(326,83,0),(328,83,1))
MAX_CALLS = 256
GETTERS = reader.GETTERS | {s[2] for s in config.ROUGH_FIELDS+config.FINISH_FIELDS}


def select_fields(target,names=None):
    require(type(target) is dict and all(type(target.get(k)) is int for k in ('operation_native_id','feature_native_id','operation_type'))
        and tuple(target.get(k) for k in ('operation_native_id','feature_native_id','operation_type')) in TARGETS,
        'Exact current guide target required')
    specs = config.ROUGH_FIELDS if target['operation_type']==0 else config.FINISH_FIELDS
    keys = [s[0] for s in specs]
    if names is None:return specs
    require(type(names) is list and 1<=len(names)<=len(keys) and all(type(v) is str and v in keys for v in names)
        and len(set(names))==len(names), 'Unique bounded fixed getter names required')
    return tuple(next(s for s in specs if s[0]==name) for name in names)


def normalized(value):
    if type(value) in (list,tuple):
        require(len(value)<=4,'Bounded scalar tuple required')
        return [normalized(v) for v in value]
    require(type(value) in (bool,int,float) and (type(value) is bool or math.isfinite(value)), 'Finite native scalar required')
    return value


class FieldReadBatch(reader.ParameterReadBatch):
    def read(self,obj,name,*args):
        self.reject(name in GETTERS, 'Getter outside fixed field read scope')
        for arg in args:self.reject(type(arg) is int or id(arg) in self._known_objects,'Argument outside retained graph')
        return self.observed(obj,'getter',name,lambda:_member(obj,name,*args))


def make_batch(backend,doc,progress,state,binding):
    return FieldReadBatch(backend.sw,backend.typelib_path,generated_pin=backend.loaded['generated_pin'],
        process_id=backend.args['process_id'],expected_document=backend.ctx.identity(),
        source_sha256=backend.ctx.args['expected_source_sha256'],evidence_pins=backend.loaded['pins'],
        verify_evidence=backend.ctx.files,verify_owned_process=backend.ctx.owned,check_events=backend.events,
        retained_objects=(doc,),verify_retained_binding=binding,max_native_calls=MAX_CALLS,
        progress=progress,progress_state=state)


def make_configuration_check(backend,doc,stats):
    cb=guide.configuration_binding
    cls=cb._verify_generated_class(getattr(cb._load_type_library(backend.typelib_path),'ICWConfiguration'),
        cb.EXTRA_INTERFACES['ICWConfiguration'],backend.loaded['generated_pin'])
    expected=backend.loaded['guide_parameters']['configuration']
    def read(obj,name,*args):
        require(name in {'ActiveDoc','ConfigurationManager','ActiveConfiguration','Name','GetActiveConfigurationName',
            'GetActiveConfiguration','ConfigurationName','SWConfigurationName'} and not args,'Fixed binding getter required')
        stats['binding_native_calls']+=1;require(stats['binding_native_calls']<=64,'Bounded configuration callbacks required')
        backend.events();value=_member(obj,name);backend.events();return value
    def typed(obj,name):
        require(name=='ICWConfiguration','Only configuration QI allowed')
        stats['binding_native_calls']+=1;require(stats['binding_native_calls']<=64,'Bounded configuration callbacks required')
        backend.events();value=obj.QueryInterface(cls);backend.events()
        require(value is not None and bool(value) and isinstance(value,cls),'Exact configuration pointer required');return value
    def check():
        started=perf_counter();stats['binding_checks']+=1
        try:
            name=read(read(read(read(backend.sw,'ActiveDoc'),'ConfigurationManager'),'ActiveConfiguration'),'Name')
            require(name==backend.args['expected_configuration'],'Current SW configuration changed')
            observed=cb.config_binding(doc,name,read=read,typed=typed);cb.require_binding(observed)
            require(group.exact(observed,expected),'Current CAM configuration binding changed')
        finally:stats['binding_elapsed_seconds']+=perf_counter()-started
    return check


def target_binding(doc,target,batch,wanted):
    oid,fid,kind=(target[k] for k in ('operation_native_id','feature_native_id','operation_type'))
    found=batch.read(doc,'GetCWObjectFromID',3,oid)
    require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact operation lookup required')
    raw=found[0];op=batch.typed(raw,'ICWOperation');mill=batch.typed(raw,'ICWMillOperation')
    observed=dict(operation_native_id=_object_id(doc,op,batch.read),operation_type=batch.read(mill,'OpernType'),
        suppressed=batch.read(op,'Suppressed'),generated=batch.read(op,'GetIsToolpathGenerated'))
    observed['feature_ids']=[_object_id(doc,v,batch.read) for v in _items(batch.read(op,'IGetAllFeatures'),batch.typed,batch.read,2)]
    observed['record_counts']=[batch.read(batch.typed(v,'ICWToolpath'),'RecordCount') for v in _items(batch.read(op,'IGetEnumToolpaths'),batch.typed,batch.read,1)]
    observed['assigned_tool'],_=read_generic_tool(raw,doc,batch.read,batch.typed)
    require(observed['operation_native_id']==oid and observed['operation_type']==kind
        and observed['suppressed'] is False and observed['generated'] is False and observed['record_counts']==[]
        and observed['feature_ids']==[fid] and group.exact(observed['assigned_tool'],wanted),'Exact ungenerated assigned guide required')
    found=batch.read(doc,'GetCWObjectFromID',1,fid)
    require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact feature lookup required')
    feature=batch.feature_dispatch(found[0]);require(_object_id(doc,feature,batch.read)==fid,'Retained feature identity changed')
    return observed,raw,feature


def read_field_values(backend,target,*,field_names=None,progress=lambda:None,diagnostic=None):
    """Fixed fields as plain values; suitable for operation baseline or readback.

The caller pins this module in its existing evidence callback, and must not use
this helper across a Save/reopen. It must retain backend.doc from a fresh full
capture in the same guarded source context.
"""
    specs=select_fields(target,field_names);doc=backend.doc
    require(doc is not None,'Fresh full-capture CAM document required')
    wanted=backend.loaded['configuration_tool'];require(wanted['native_id']==273 and wanted['cut_diameter_native']==2.,'Existing qualified D2 tool required')
    require(diagnostic is None or (type(diagnostic) is dict and not diagnostic), 'Fresh optional diagnostic mapping required')
    result = {} if diagnostic is None else diagnostic
    result.update(operation_native_id=target['operation_native_id'],feature_native_id=target['feature_native_id'],
        field_values={},read_complete=False,binding_native_calls=0,binding_checks=0,binding_elapsed_seconds=0.)
    state=dict(member='',returned=False,read_index=0)
    binding=make_configuration_check(backend,doc,result)
    batch=make_batch(backend,doc,progress,state,binding);started=perf_counter()
    try:
        with batch:
            result['before'],raw,feature=target_binding(doc,target,batch,wanted)
            owners={}
            for spec in specs:
                key,name,getter,_,mode=spec
                if name not in owners:
                    if name in ('lead_in','lead_out'):
                        if 'ICWFinishMillOp' not in owners:owners['ICWFinishMillOp']=batch.typed(raw,'ICWFinishMillOp')
                        finish=owners['ICWFinishMillOp']
                        lead=batch.read(finish,'IGetLeadin' if name=='lead_in' else 'IGetLeadout',feature)
                        owners[name]=batch.typed(lead,'ICWLeadInOut')
                    else:owners[name]=batch.typed(raw,name)
                result['field_values'][key]=normalized(batch.read(owners[name],getter,*([feature] if mode=='feature' else [])))
            result['after'],_,_=target_binding(doc,target,batch,wanted)
            require(group.exact(result['before'],result['after']),'Selected binding changed during scalar reading')
        batch.require_complete();result['read_complete']=True
    finally:
        result['read_batch']=batch.summary();result['elapsed_seconds']=perf_counter()-started
    return result

