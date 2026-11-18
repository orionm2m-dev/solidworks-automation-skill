"""Read three native path-length scalars twice after the qualified saved-pair read.
The parent's genuine report scope is retained. This module adds one named,
subordinate read-only observation and no Save, GTP, setters, export or replay.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import math
from scripts import sw_cam_qualify_recovered_pocket_read as parent
from scripts import sw_cam_finish_lengths as lengths
from scripts import sw_cam_read_batch_guard as batch_source
from scripts import sw_cam_pocket_rough_apply as abi_source
from scripts import sw_cam_rough_firstcut as require_source
from scripts import sw_cam_mill_inventory as inventory_source

require=parent.require
KEYS=parent.KEYS
SCOPE='RECOVERED_GENERATED_ROUGH_LENGTH_OBSERVATION_V1'
OBSERVATION='native_length_observation'
FLAGS=('reads_verified','binding_unchanged','repeat_equal','parent_terminal_verified','readback_verified')
MAX_READS=128


def selection(bundle):
    generated=bundle['protected_generated']
    require(type(generated)is dict and len(generated)==1,'Exactly one protected generated operation required')
    oid=next(iter(generated));counts=generated[oid]
    require(type(oid)is int and oid>0 and type(counts)is list and len(counts)==1
        and type(counts[0])is int and 0<counts[0]<=100000,'Strict generated identity/count required')
    fid=bundle['state']['selected_feature']['native_id']
    rows=[x for x in bundle['state']['operations']if x['native_id']==oid]
    require(len(rows)==1,'Unique generated operation required');row=rows[0]
    require(type(row['mill_operation_type'])is int and row['mill_operation_type']==0
        and row['suppressed']is False and row['toolpath_generated']is True
        and row['linked_feature_ids']==[fid] and row['toolpath_record_counts']==counts
        and type(row['assigned_tool']['native_id'])is int and row['assigned_tool']['native_id']>0,
        'Exact saved generated Rough/feature/tool binding required')
    return dict(operation_native_id=oid,feature_native_id=fid,tool_native_id=row['assigned_tool']['native_id'],record_counts=deepcopy(counts))


def prepare(v):
    data=parent.prepare(v);selection(data['bundle'])
    paths=(__file__,lengths.__file__,lengths.protected.__file__,lengths.protected.group.__file__,
        lengths.finish.__file__,batch_source.__file__,abi_source.__file__,require_source.__file__,inventory_source.__file__)
    bundle=data['bundle'];d=bundle['context']
    d['pins']=parent.current.pin_union(d['pins'],[dict(path=str(p),sha256=parent._file_hash(p))for p in paths])
    bundle['pins']=deepcopy(d['pins'])
    parent.admission.verify_files(bundle);parent.reader.definition.verify_files(d)
    require(all(not parent.reader.definition.creator.same_path(str(data['receipt']),p['path'])for p in d['pins']),
        'Length receipt aliases newly pinned dependency')
    return data


def initial_observation(bundle):
    return dict(scope=SCOPE,selected=selection(bundle),phase='pending',scalar_observations=[],
        readonly=True,scalar_getter_limit=6,scalar_getters_returned=0,automatic_retry=False,
        native_dispatch_pending=False,native_units_verified=False,native_precision_verified=False,
        native_length_scope_matches_CL_verified=False,full_turn_semantics_verified=False,
        production_qualified=False,**{k:False for k in FLAGS})


def observe_lengths(batch,doc,state,target,report,persist):
    """Use existing retained operation binding and the existing three getters."""
    report['phase']='binding_before';persist()
    report['binding_before'],op,_=lengths.protected.binding(doc,state,target['operation_native_id'],
        target['feature_native_id'],read=batch.read,typed=batch.typed);persist()
    captures=[]
    for index in range(2):
        report['phase']='lengths_'+str(index+1);persist()
        def record(key,value):
            row=dict(capture=index+1,key=key,returned_type=type(value).__name__)
            if type(value)is float and math.isfinite(value):row['value']=value
            elif value is None or type(value)in(bool,int,str):row['value']=value
            else:row['unsupported_or_nonfinite_shape']=True
            report['scalar_observations'].append(row);report['scalar_getters_returned']+=1;persist()
            require(type(value)is float and math.isfinite(value)and value>=0,
                'Strict finite nonnegative DOUBLE length required')
        observed=lengths.read_lengths(op,read=batch.read,record=record)
        captures.append(observed);report['captures']=deepcopy(captures);persist()
    require(lengths.group.exact(captures[0],captures[1]),'Repeated native lengths differ')
    report['phase']='binding_after'
    report['binding_after'],_,_=lengths.protected.binding(doc,state,target['operation_native_id'],
        target['feature_native_id'],read=batch.read,typed=batch.typed);persist()
    require(lengths.group.exact(report['binding_before'],report['binding_after']),
        'Native length target binding changed')
    require(report['scalar_getters_returned']==6 and len(report['scalar_observations'])==6,
        'Exactly six length getter returns required')
    values=captures[0]
    delta=math.fsum([values['total_length_native'],-values['feed_length_native'],-values['rapid_length_native']])
    require(math.isfinite(delta),'Finite length consistency diagnostic required')
    report.update(lengths=deepcopy(values),total_minus_feed_minus_rapid_native=delta,
        additivity_semantics_verified=False,binding_unchanged=True,repeat_equal=True,phase='read_complete')
    persist()


class Context(parent.Context):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.r[OBSERVATION]=initial_observation(self.bundle);self.persist()

    def observe(self,state,native):
        super().observe(state,native)
        report=self.r[OBSERVATION];report['phase']='abi';self.persist()
        report['abi']=lengths.audit(self.tlb,self.abi['generated_pin']);self.persist()
        require(report['abi']['abi_verified']is True,'Length ABI audit required')
        target=selection(self.bundle);calls=[0];batch=None;started=perf_counter()
        def owned():
            self.runtime_check();require(self.identity()==self.expected,'Saved context changed during lengths')
        def read_binding(obj,name,*args):
            calls[0]+=1;require(calls[0]<=32 and name in('GetDocType','MachType','GetCWObjectID'),
                'Bounded fixed retained length root binding required')
            self.events();value=parent._member(obj,name,*args);self.events();return value
        def binding():
            doc=read_binding(native['doc'],'GetDocType');machine=read_binding(native['machine'],'MachType')
            require(type(doc)is int and doc==1 and type(machine)is int and machine==1,'Retained MILL roots changed')
            require(parent._object_id(native['doc'],native['selected_feature'],read_binding)==target['feature_native_id'],
                'Retained length feature changed')
        def progress(name,returned):
            report.update(current_member=name,native_dispatch_pending=not returned);self.persist()
        try:
            batch=lengths.ReadBatch(self.sw,self.tlb,generated_pin=self.abi['generated_pin'],progress=progress,
                process_id=self.v['process_id'],expected_document=self.expected['document'],
                source_sha256=self.v['expected_source_sha256'],evidence_pins=self.d['pins'],
                verify_evidence=lambda:parent.reader.definition.verify_files(self.d),verify_owned_process=owned,
                check_events=self.events,retained_objects=(native['doc'],native['machine'],native['selected_feature']),
                verify_retained_binding=binding,max_native_calls=MAX_READS,evidence_pin_limit=128)
            with batch:observe_lengths(batch,native['doc'],state,target,report,self.persist)
            batch.require_complete();report['reads_verified']=True
        finally:
            report['elapsed_seconds']=perf_counter()-started;report['root_binding_native_calls']=calls[0]
            if batch is not None:report['batch']=batch.summary()
            self.persist()


def finalize(r):
    report=r.get(OBSERVATION)
    if report is None:return r
    valid=(r.get('scope')==parent.SCOPE and r.get('status')=='observed'and r.get('phase')=='finished'
        and all(r.get(k)is True for k in parent.FLAGS)
        and all(report.get(k)is True for k in('reads_verified','binding_unchanged','repeat_equal'))
        and report.get('scalar_getters_returned')==6 and report.get('native_dispatch_pending')is False)
    report['parent_terminal_verified']=valid;report['readback_verified']=valid
    report['phase']='finished'if valid else'parent_or_length_read_failed'
    return r


def run_read(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_context_factory=Context):
    data=prepare(v)if prepared is None else prepared
    r=parent.run_read(sw,clsid,tlb,v,prepared=data,runtime_check=runtime_check,_context_factory=_context_factory)
    finalize(r)
    try:parent.reader._write_receipt(Path(r['receipt_path']),r)
    except Exception as error:
        revoke(r,error);raise
    return r


def revoke(r,error):
    if OBSERVATION in r:
        r[OBSERVATION].update(parent_terminal_verified=False,readback_verified=False,phase='revoked')
    return parent.revoke(r,error)
