"""Read one fresh-Finish recipe's twenty fields in a retained, bounded batch.

The original writer stays immutable. Use read_fields in a new snapshot adapter;
per-setter dispatch, Save, generation and owner-journal durability are unchanged.
"""
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from time import monotonic
import re
from importlib import import_module
from scripts import sw_cam_read_progress_journal as progress
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_rough_firstcut import require

SCOPE='FRESH_FINISH_TWENTY_FIELDS_READ_V1'
MAX_CALLS=64
INTERFACES=frozenset({'ICWOperation','ICWMillOperation','ICWDispatchCollection',
    'ICWFinishMillOp','ICWFinishMillOp2','ICWFinishMillOp3','ICWLeadInOut'})
GETTERS=frozenset({'SideAllow','FinalSideCutAmt','SpringPass','GetFirstDepthCut',
    'GetMaxDepthCut','FinalDepthCut','GetSideCutAmt','GetPreviousAllowance','OverridePrevAllow',
    'PerimeterPassType','LeadInOutApplyToAll','GetIsSameLeadinout','ArcAngle',
    'GetArcRadius2','GetLeadAmt2','GetLeadOverlap2'})|{
    'GetCWObjectFromID','GetCWObjectID','Suppressed','IGetAllFeatures',
    'OpernType','Count','Item','IGetLeadin','IGetLeadout'}
BOOL_KEYS=frozenset({'override_previous','apply_all','out_independent'})
INT_KEYS=frozenset({'spring_passes','perimeter'})


def _recipe():
    # The writer can import this helper before defining FIELDS. Resolve it only
    # while executing an already initialized, pinned reader/writer phase.
    return import_module('scripts.sw_cam_fresh_finish_recipe')


def raw_observation(value):
    """Preserve native scalars and short tuples without coercing invalid numbers."""
    if type(value) in (tuple,list) and len(value)<=4:
        items=[_recipe().group.return_observation(x) for x in value]
        complete=all(x['value_recorded'] for x in items)
        return dict(python_type=type(value).__name__,value_recorded=complete,items=items,
                    value=[x['value'] for x in items] if complete else None)
    return _recipe().group.return_observation(value)


def checked_value(spec,value):
    value=list(value) if type(value) is tuple else value
    finite=lambda v:type(v) is float and isfinite(v)
    if spec[4]=='depth_pair':
        good=type(value) is list and len(value)==2 and finite(value[0]) and type(value[1]) is bool
    elif spec[4]=='pair':
        good=type(value) is list and len(value)==3 and finite(value[0]) and type(value[1]) is bool and finite(value[2])
    elif spec[0] in BOOL_KEYS:good=type(value) is bool
    elif spec[0] in INT_KEYS:good=type(value) is int and -(2**31)<=value<2**31
    else:good=finite(value)
    require(good,'Native field scalar shape differs: '+spec[0])
    return value


class FreshFinishFieldBatch(ScopedCamReadBatch):
    def __init__(self,*args,generated_pin,progress_callback,progress_state,**kwargs):
        self.generated_pin=generated_pin;self.progress_callback=progress_callback
        self.progress_state=progress_state
        super().__init__(*args,**kwargs)

    def observed(self,obj,kind,name,invoke):
        try:
            self.progress_state.update(member=name,kind=kind,attempted=True,returned=False,
                native_call_count=self._read_calls+self._qi_calls)
            self.progress_state.pop('value',None)
            self.progress_callback()
            value=self._observe_read(obj,kind,invoke)
            self.progress_state.update(returned=True,native_call_count=self._read_calls+self._qi_calls)
            raw=raw_observation(value)
            if raw['value_recorded'] and (type(raw['value']) in (bool,int,float,type(None))
                or type(raw['value']) is list and len(raw['value'])<=4):
                self.progress_state['value']=raw['value']
            self.progress_callback()
            return value
        except BaseException:
            self._invalid=True;self._completed=False
            raise

    def read(self,obj,name,*args):
        try:
            require(name in GETTERS,'Getter outside twenty-field read scope')
            for value in args:
                require(type(value) is int or id(value) in self._known_objects,
                        'Argument outside retained target graph')
            return self.observed(obj,'getter',name,lambda:_member(obj,name,*args))
        except BaseException:
            self._invalid=True;self._completed=False
            raise

    def typed(self,obj,name):
        try:
            require(name in INTERFACES,'Interface outside twenty-field scope')
            cls=_recipe().finish.interface_class(name,self.typelib_path,self.generated_pin)
            def query():
                value=obj.QueryInterface(cls)
                require(value is not None and bool(value) and isinstance(value,cls),'Exact nonnull native interface required')
                return value
            return self.observed(obj,'qi',name,query)
        except BaseException:
            self._invalid=True;self._completed=False
            raise


def read_cached_fields(batch,operation,feature,diagnostic):
    owners={name:batch.typed(operation,name) for name in
            ('ICWFinishMillOp','ICWFinishMillOp2','ICWFinishMillOp3')}
    for side,getter in (('lead_in','IGetLeadin'),('lead_out','IGetLeadout')):
        raw=batch.read(owners['ICWFinishMillOp'],getter,feature)
        require(raw is not None and bool(raw),'Nonnull feature-specific lead required')
        owners[side]=batch.typed(raw,'ICWLeadInOut')
    fields={}
    for spec in _recipe().FIELDS:
        value=batch.read(owners[spec[1]],spec[2],*([feature] if spec[4]=='feature' else []))
        # Keep actual return evidence before a shape or downstream recipe check.
        diagnostic.setdefault('raw_fields',{})[spec[0]]=raw_observation(value)
        fields[spec[0]]=checked_value(spec,value)
    require(len(fields)==20,'Exact twenty-field recipe required')
    return fields


def read_fields(backend,label):
    """Return only after the same target/feature and both batch boundaries pass."""
    require(type(label) is str and re.fullmatch('[A-Za-z0-9_]{1,48}',label),'Bounded phase label required')
    common=_recipe().common
    for file in (__file__,progress.__file__):
        require(common._pin(file) in backend.loaded['pins'],'Reader and progress helper must be live pinned')
    # One established ordinary target guard, replacing twenty separate guards.
    with backend.ctx.guard() as guard:
        operation,feature=backend.target(guard)
    oid,fid=backend.args['operation_native_id'],backend.args['feature_native_id']
    doc=backend.native['doc'];started=monotonic()
    diagnostic=dict(scope=SCOPE,label=label,complete=False,operation_native_id=oid,
        feature_native_id=fid,started_utc=datetime.now(timezone.utc).isoformat(),raw_fields={})
    backend.report.setdefault('fresh_finish_field_batches',[]).append(diagnostic)
    receipt=Path(backend.args['receipt_path'])
    path=receipt.with_name(receipt.stem+'.fields.'+label+'.'+str(oid)+'.json')
    protected=[backend.args['expected_document_path'],receipt]+[x['path'] for x in backend.loaded['pins']]
    owner=getattr(backend.persist,'__self__',None)
    if owner is not None and hasattr(owner,'marker'):protected.append(owner.marker)
    state=dict(phase=label,operation_native_id=oid,member='',returned=False,native_call_count=0)
    batch=None
    def describe():
        return dict(state,observed_utc=datetime.now(timezone.utc).isoformat(),elapsed_seconds=monotonic()-started)
    def binding():
        backend.target(batch)
        require(_object_id(doc,operation,batch.read)==oid and _object_id(doc,feature,batch.read)==fid,
                'Retained target/feature identity changed')
    with progress.ReadProgressJournal(full_persist=backend.persist,progress_path=path,
            describe=describe,max_updates=MAX_CALLS*2+4,protected_paths=protected) as journal:
        try:
            batch=FreshFinishFieldBatch(backend.sw,backend.typelib_path,
                generated_pin=backend.loaded['generated_pin'],progress_callback=journal.read,progress_state=state,
                process_id=backend.args['process_id'],expected_document=backend.ctx.identity(),
                source_sha256=backend.ctx.args['expected_source_sha256'],evidence_pins=backend.loaded['pins'],
                verify_evidence=backend.ctx.files,verify_owned_process=backend.ctx.owned,
                check_events=backend.events,retained_objects=(doc,operation,feature),
                verify_retained_binding=binding,max_native_calls=MAX_CALLS)
            with batch:
                fields=read_cached_fields(batch,operation,feature,diagnostic)
            batch.require_complete();diagnostic.update(complete=True,field_count=len(fields))
        finally:
            if batch is not None:diagnostic['batch']=batch.summary()
            diagnostic.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                              elapsed_seconds=monotonic()-started)
        journal.complete()
    return fields


class BatchedFinishFieldsMixin:
    def snapshot_fields(self,label):
        return read_fields(self,label)
