"""Versioned read-only scheduling for one explicit Rough/Contour pair.

The existing complete payload readers remain unchanged. Retained document roots
replace per-getter active-document/file metadata observations with strong
boundaries and per-getter events. This is a separately qualified non-atomic read
contract, never a replacement mutation guard or a write lease.
"""
from copy import deepcopy
from time import perf_counter
from scripts import sw_cam_current_pocket_generate_v2 as generation
from scripts import sw_cam_pocket_definition_capture_v2 as definition_capture
from scripts import sw_cam_read_batch_guard as retained
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam import _member

reader=generation.reader
require=reader.require
SCOPE='CURRENT_POCKET_PAIR_RETAINED_READ_V1'
PIN_LIMIT=128


class RetainedPairReadBatch(retained.ScopedCamReadBatch):
    """Same fixed typed parameter getters; only observation scheduling changes."""
    def __init__(self,*args,generated_pin,report,**kwargs):
        self.generated_pin=generated_pin;self.report=report;self.calls=0
        super().__init__(*args,**kwargs)
    def reject(self,condition,message):
        if not condition:
            self._invalid=True;self._completed=False
            raise ValueError(message)
    def observed(self,obj,kind,name,invoke):
        self.calls+=1
        self.reject(self.calls<=reader.MAX_CALLS,'Selected pair native-read budget exceeded')
        self.report['last_native_read']=dict(kind=kind,member=name,returned=False,index=self.calls)
        value=self._observe_read(obj,'qi' if kind=='qi' else 'getter',invoke)
        self.report['last_native_read']['returned']=True
        self.report['parameter_native_read_count']=self.calls
        return value
    def read(self,obj,name,*args):
        self.reject(name!='IGetActiveDoc','Global CAM document reacquisition is outside the retained graph')
        if name!='QueryInterface':
            for arg in args:
                self.reject(type(arg)is int or id(arg)in self._known_objects,'Argument outside retained pair graph')
        return reader.ReadGuard.read(self,obj,name,*args)
    typed=reader.ReadGuard.typed
    plane=reader.ReadGuard.plane
    def summary(self):
        result=super().summary()
        result.update(scope=SCOPE,per_getter_active_document_checks=False,
            per_getter_file_metadata_checks=False,full_payload_native_parity_qualified=False)
        return result


def selection(expected_snapshot,generation_observations):
    require(type(expected_snapshot)is dict and set(expected_snapshot)=={'inventory','parameters'},'Exact full pair snapshot required')
    state=expected_snapshot['inventory'];rows=state['operations']
    require(type(rows)is list and len(rows)==2 and all(type(r['mill_operation_type'])is int for r in rows)and [r['mill_operation_type']for r in rows]==[0,1],'One ordered Rough/Contour pair required')
    ids=[r['native_id']for r in rows]
    require(all(type(i)is int and 0<i<2**31 for i in ids)and len(set(ids))==2,'Distinct strict operation identities required')
    require(len(state['operation_setups'])==1 and all(type(r['setup_native_id'])is int and r['setup_native_id']>0 for r in rows)and len({r['setup_native_id']for r in rows})==1 and rows[0]['setup_native_id']==state['operation_setups'][0]['native_id'],'One shared operation setup required')
    links=[r['linked_feature_ids']for r in rows]
    require(links[0]==links[1]and type(links[0])is list and len(links[0])==1 and type(links[0][0])is int and links[0][0]>0,'One explicit common feature required')
    require(type(generation_observations)is dict and all(type(k)is int for k in generation_observations)and set(generation_observations)<={ids[0]},'Only the explicit first Rough may be generated')
    for row in rows:
        wanted=generation_observations.get(row['native_id'],[])
        require(type(wanted)is list and len(wanted)==(1 if row['native_id']in generation_observations else 0) and all(type(n)is int and 0<n<=100000 for n in wanted),'Bounded explicit generated record count required')
        require(row['suppressed']is False and row['toolpath_generated']is bool(wanted)and row['toolpath_record_counts']==wanted,'Actual expected generation state differs')
    parameters=expected_snapshot['parameters']
    require(type(parameters)is list and len(parameters)==2 and [r['operation_native_id']for r in parameters]==ids and all(r['read_complete']is True for r in parameters),'Two complete matching parameter rows required')
    return deepcopy(rows),links[0][0]


def capture_pair(sw,clsid,tlb,context,*,expected_snapshot,generation_observations,
                 check_events,runtime_check,abi,diagnostic,persist):
    """Read only against an already verified saved or explicitly dirty context.

    The caller admits genuine receipt authority and pins this module together
    with all unchanged parents. No receipt loader, mutation, Save, retry, or
    automatic promotion is provided here. The result is usable only on return.
    """
    require(type(diagnostic)is dict and not diagnostic,'Fresh diagnostic mapping required')
    targets,fid=selection(expected_snapshot,generation_observations)
    require(all(callable(x)for x in (check_events,runtime_check,persist)),'Explicit boundary callbacks required')
    require(type(context)is dict and type(context.get('pins'))is list and 1<=len(context['pins'])<=PIN_LIMIT,'Complete bounded authority pins required')
    for path in (__file__,generation.__file__,definition_capture.__file__,retained.__file__):
        rows=[p for p in context['pins']if reader.definition.creator.same_path(p['path'],path)]
        require(len(rows)==1 and rows[0]['sha256']==_file_hash(path),'Exact reader dependency pin required')
    expected=deepcopy(expected_snapshot);observations=deepcopy(generation_observations)
    diagnostic.update(scope=SCOPE,read_only=True,read_complete=False,native_parity_qualified=False,
        mutation_attempted=False,Save_attempted=False,GOP_attempted=False,GTP_attempted=False,
        automatic_retry=False,atomic_snapshot=False,transient_active_document_excursion_excluded=False)
    started=perf_counter();batch=None
    diagnostic['timing_seconds']={}
    def timed(label,invoke):
        phase_start=perf_counter()
        try:return invoke()
        finally:diagnostic['timing_seconds'][label]=perf_counter()-phase_start
    try:
        runtime_check();reader.definition.verify_files(context);check_events()
        before,native=timed('before_definition',lambda:definition_capture.capture(sw,clsid,tlb,context,check_events,diagnostic.setdefault('before',{})))
        require(before==expected['inventory'],'Fresh complete inventory differs from admitted pair')
        document=deepcopy(before['document']);v=context['request'];report={}
        def owned():
            runtime_check()
            require(reader.definition.identity(sw,context)['document']==document,'Exact owned document or dirty state changed')
        diagnostic['binding_native_calls']=0
        def binding_read(obj,name,*args):
            require(name in ('GetDocType','MachType','GetCWObjectID'),'Fixed retained binding getter required')
            diagnostic['binding_native_calls']+=1
            require(diagnostic['binding_native_calls']<=128,'Retained binding call budget exceeded')
            check_events();value=_member(obj,name,*args);check_events();return value
        def binding():
            doc_kind=binding_read(native['doc'],'GetDocType');machine_kind=binding_read(native['machine'],'MachType')
            require(type(doc_kind)is int and doc_kind==1,'Retained CAM part differs')
            require(type(machine_kind)is int and machine_kind==1,'Retained MILL machine differs')
            require(_object_id(native['doc'],native['selected_feature'],binding_read)==fid,'Retained document feature identity differs')
            check_events()
        batch=RetainedPairReadBatch(sw,tlb,process_id=v['process_id'],expected_document=document,
            source_sha256=context['expected_source_sha256'],evidence_pins=context['pins'],
            verify_evidence=lambda:reader.definition.verify_files(context),verify_owned_process=owned,
            check_events=check_events,retained_objects=(native['doc'],native['machine'],native['selected_feature']),
            verify_retained_binding=binding,max_native_calls=reader.MAX_CALLS,evidence_pin_limit=PIN_LIMIT,
            generated_pin=abi['generated_pin'],report=diagnostic)
        parameter_started=perf_counter()
        try:
            with batch:
                generation.read_pair(deepcopy(before),native,targets,batch,report,persist,observations)
            batch.require_complete()
        finally:
            diagnostic['timing_seconds']['parameters']=perf_counter()-parameter_started
        runtime_check();check_events()
        after,_=timed('after_definition',lambda:definition_capture.capture(sw,clsid,tlb,context,check_events,diagnostic.setdefault('after',{})))
        require(before==after==expected['inventory'],'Full inventory/body/sketch context changed across retained reads')
        require(report['parameters']==expected['parameters'],'Complete retained parameter payload differs from admitted snapshot')
        reader.definition.verify_files(context);owned();check_events();runtime_check()
        result=dict(inventory=deepcopy(after),parameters=deepcopy(report['parameters']))
        diagnostic.update(read_complete=True,payload_matches_admitted_snapshot=True,
            full_inventory_unchanged=True,full_body_and_sketch_checks_reused=True)
        return result
    finally:
        if batch is not None:diagnostic['read_batch']=batch.summary()
        diagnostic['elapsed_seconds']=perf_counter()-started
        persist()
