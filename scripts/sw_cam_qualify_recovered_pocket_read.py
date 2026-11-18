"""One read-only retained capture against a genuine recovered saved pair.
No setters, generation, Save, export, document activation or marker creation.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from scripts import sw_cam_recovered_generated_context as admission
from scripts import sw_cam_pocket_definition_fast_v1 as fast
from scripts import sw_cam_current_pocket_pair_retained as retained
from scripts import sw_cam_current_pocket_context_v2 as current
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam import _member, _error

reader=retained.reader
require=reader.require
SCOPE='RECOVERED_POCKET_FAST_PAIR_READ_QUALIFICATION_V1'
KEYS=set(admission.KEYS)|{'receipt_path'}
FLAGS=('readback_verified','exact_saved_snapshot_verified','source_unchanged','runtime_unchanged','clean_message_scope_verified')


def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact recovered pair read-only request required')
    require(type(v['receipt_path'])is str and Path(v['receipt_path']).is_absolute(),'Explicit absolute output receipt required')
    ids=v['expected_operation_native_ids']
    require(type(ids)is list and len(ids)==2 and all(type(x)is int and 0<x<2**31 for x in ids)and len(set(ids))==2,'Two strict distinct operation identities required')


def prepare(v):
    shape(v);bundle=admission.load({k:deepcopy(x)for k,x in v.items()if k!='receipt_path'})
    expected=dict(inventory=deepcopy(bundle['state']),parameters=deepcopy(bundle['parameters']))
    retained.selection(expected,bundle['protected_generated'])
    require(bundle['context']['saved_plan_inventory']==bundle['state']and bundle['state']['document']['needs_save']is False,'Exact clean saved inventory binding required')
    paths=(__file__,admission.__file__,fast.__file__,fast.prebound.__file__,fast.prebound.parent.__file__,fast.parent.__file__,fast.retained.__file__,retained.__file__,retained.generation.__file__)
    d=bundle['context'];d['pins']=current.pin_union(d['pins'],[dict(path=str(p),sha256=_file_hash(p))for p in paths]);bundle['pins']=deepcopy(d['pins'])
    admission.verify_files(bundle);reader.definition.verify_files(d)
    output=Path(v['receipt_path'])
    require(output.suffix.lower()=='.json'and output.parent.is_dir()and not output.exists()and not output.is_symlink(),'Fresh read-only receipt required')
    require(all(not reader.definition.creator.same_path(str(output),p['path'])for p in d['pins']),'Output aliases protected evidence')
    return dict(bundle=bundle,expected=expected,request=deepcopy(v),receipt=output,consumed=False)


class Context(reader.Context):
    """Reuse only the existing read-only identity/event lifecycle."""
    def capture(self,label):
        self.r['phase']=label;diagnostic={};self.r[label+'_diagnostic']=diagnostic;self.persist();started=perf_counter()
        try:state,native=fast.capture(self.sw,self.clsid,self.tlb,self.d,self.events,diagnostic)
        finally:self.r['timing_seconds'][label]=perf_counter()-started;self.persist()
        require(state==self.bundle['state'],'Fresh full inventory differs from admitted saved state')
        self.r[label]=deepcopy(state);self.persist();return state,native
    def observe(self,state,native):
        self.r['phase']='retained_parameters';report={};self.r['parameter_observation']=report;self.persist();started=perf_counter();batch=None
        targets,fid=retained.selection(dict(inventory=state,parameters=self.bundle['parameters']),self.bundle['protected_generated'])
        def owned():
            self.runtime_check();require(self.identity()==self.expected,'Owned saved context changed during retained parameters')
        calls=[0]
        def read_binding(obj,name,*args):
            calls[0]+=1;require(calls[0]<=128 and name in('GetDocType','MachType','GetCWObjectID'),'Bounded fixed retained binding required')
            self.events();value=_member(obj,name,*args);self.events();return value
        def binding():
            doc=read_binding(native['doc'],'GetDocType');machine=read_binding(native['machine'],'MachType')
            require(type(doc)is int and doc==1 and type(machine)is int and machine==1,'Retained MILL document differs')
            require(_object_id(native['doc'],native['selected_feature'],read_binding)==fid,'Retained feature binding differs')
        try:
            batch=retained.RetainedPairReadBatch(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=self.expected['document'],source_sha256=self.v['expected_source_sha256'],evidence_pins=self.d['pins'],verify_evidence=lambda:reader.definition.verify_files(self.d),verify_owned_process=owned,check_events=self.events,retained_objects=(native['doc'],native['machine'],native['selected_feature']),verify_retained_binding=binding,max_native_calls=reader.MAX_CALLS,evidence_pin_limit=128,generated_pin=self.abi['generated_pin'],report=self.r)
            with batch:retained.generation.read_pair(deepcopy(state),native,targets,batch,report,self.persist,deepcopy(self.bundle['protected_generated']))
            batch.require_complete()
            require(report['parameters']==self.bundle['parameters'],'Complete retained parameters differ from admitted saved snapshot')
            self.r['parameters']=deepcopy(report['parameters']);self.persist()
        finally:
            self.r['timing_seconds']['retained_parameters']=perf_counter()-started;self.r['binding_native_calls']=calls[0]
            if batch is not None:self.r['parameter_guard']=batch.summary()
            self.persist()


def run_read(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_context_factory=Context):
    data=prepare(v)if prepared is None else prepared
    require(data.get('consumed')is False and data['request']==v,'Exact unused invocation-local preparation required');data['consumed']=True
    bundle=data['bundle'];d=bundle['context'];admission.verify_files(bundle);reader.definition.verify_files(d);runtime_check()
    abi=reader.preflight(tlb);d['pins']=current.pin_union(d['pins'],[abi['generated_pin'],dict(path=str(tlb),sha256=_file_hash(tlb))]);bundle['pins']=deepcopy(d['pins'])
    admission.verify_files(bundle);reader.definition.verify_files(d);runtime_check()
    r=dict(scope=SCOPE,status='running',phase='prepared',request=deepcopy(v),receipt_path=str(data['receipt']),authority_receipt_pin=deepcopy(bundle['receipt_pin']),evidence_pins=deepcopy(d['pins']),protected_generated=deepcopy(bundle['protected_generated']),protected_cl_pin=deepcopy(bundle['protected_cl']['pin']),abi=abi,timing_seconds={},read_only=True,mutation_attempted=False,Save_attempted=False,GOP_attempted=False,GTP_attempted=False,CL_export_attempted=False,Import_attempted=False,tool_creation_attempted=False,tool_assignment_attempted=False,automatic_replay=False,atomic_snapshot=False,transient_active_document_excursion_excluded=False,write_lease=False,reusable_for_mutation=False,performance_improvement_verified=False,production_qualified=False,physical_tool_qualified=False,cutting_conditions_qualified=False,native_units_verified=False,source_before_sha256=v['expected_source_sha256'],**{k:False for k in FLAGS})
    def persist():reader._write_receipt(data['receipt'],r)
    reader._write_receipt(data['receipt'],r,create=True);ctx=None;started=perf_counter()
    try:
        runtime_check();ctx=_context_factory(sw,clsid,tlb,v,bundle,r,persist,runtime_check,abi);ctx.start()
        before,native=ctx.capture('before_definition');ctx.observe(before,native);after,_=ctx.capture('after_definition')
        require(before==after==data['expected']['inventory']and r['parameters']==data['expected']['parameters'],'Complete observed payload differs from immutable saved snapshot')
        ctx.close();runtime_check();r['after_cleanup_identity']=ctx.identity()
        require(r['after_cleanup_identity']==ctx.expected,'Identity changed during read-only cleanup')
        require(reader.shared.event_health(r['messages'],active=False)==0,'Clean disconnected event scope required')
        admission.verify_files(bundle);reader.definition.verify_files(d);runtime_check()
        r.update(status='observed',phase='finished',source_after_sha256=v['expected_source_sha256'],**{k:True for k in FLAGS})
    except Exception as error:r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),**{k:False for k in FLAGS})
    finally:
        if ctx is not None:
            try:ctx.close()
            except Exception as error:r.update(status='error',cleanup_error=_error(error),**{k:False for k in FLAGS})
        r['phase']='finished';r['elapsed_seconds']=perf_counter()-started;persist()
    return r


def revoke(r,error):
    r.update(status='error',runtime_error=_error(error),**{k:False for k in FLAGS});reader._write_receipt(Path(r['receipt_path']),r);return r
