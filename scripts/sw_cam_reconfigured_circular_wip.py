"""One guarded whole-machine WIP export after a saved circular revision.

No generation, Save, setter, simulation control or document switch is allowed.
"""
from copy import deepcopy
from pathlib import Path
from ctypes import HRESULT,POINTER,c_long
from ctypes.wintypes import VARIANT_BOOL
from comtypes import BSTR
import json,math
from scripts import sw_cam_reconfigured_circular_wip_binding as binding
from scripts import sw_cam_completed_gtp_wip as core
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_comtypes import _interface_class
common,writer,require=binding.common,binding.writer,binding.require
SCOPE='SAVED_RECONFIGURED_CIRCULAR_WIP_EXPORT_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
      'saved_writer_receipt_path','saved_writer_receipt_sha256','consumed_writer_marker_sha256',
      'writer_module_sha256','module_sha256','operation_native_id','project_root','output_dir','receipt_path',
      'acknowledge_machine_scope','qualification_only','message_policy'}


def pin(path):
    p=Path(path);return dict(path=str(p),sha256=_file_hash(p),bytes=p.stat().st_size)


def preflight(tlb):
    cls=_interface_class('ICWMachine5',tlb);rows=[m for m in cls._methods_ if m.name=='CreateSTLOfWIPs2']
    require(len(rows)==1,'One exact existing WIP method required');m=rows[0]
    require(m.restype is HRESULT and m.idlflags[0]==49
        and m.argtypes==(BSTR,BSTR,BSTR,c_long,c_long,POINTER(VARIANT_BOOL))
        and tuple(x[0]for x in m.paramflags)==(1,1,1,1,1,10),'Existing WIP ABI differs')
    return dict(interface='ICWMachine5',method='CreateSTLOfWIPs2',dispid=49,native_calls=0)


def load_context_lineage(receipt,bound):
    """Read immutable ancestry for existing capture layout, never old source bytes."""
    pins=[]
    def read(path,sha):
        value,observed=writer.read_pin(path,sha);pins.append(observed);return value
    req=receipt['request'];nc=read(req['nc_receipt_path'],req['nc_receipt_sha256'])
    review=read(nc['request']['reconciliation_path'],nc['request']['reconciliation_sha256'])
    sp=review['pins']['save_receipt'];saved=read(sp['path'],sp['sha256'])
    gp=saved['historical_generation_pin'];history=read(gp['path'],gp['sha256']);args=history['request']['params']
    loaded=writer.engine.load_completed_configuration(args['configuration_receipt_path'],args['configuration_receipt_sha256'],
        process_id=bound['process_id'],source_path=bound['source_path'],source_sha256=args['expected_source_sha256'],
        selected_ids=bound['selected_operation_ids'])
    require(loaded.get('mode')=='current_saved_circular','Established circular context required')
    writer_hashes={p['sha256']for p in bound['pins']if common.same_path(p['path'],writer.__file__)}
    require(len(writer_hashes)==1,'Exact bound writer module pin required')
    require(read(bound['receipt_pin']['path'],bound['receipt_pin']['sha256'])==receipt,
        'Bound writer receipt content differs')
    return dict(args=deepcopy(args),loaded=loaded,recipe=deepcopy(receipt['recipe']),state=deepcopy(bound['snapshot']),
        pins=pins,cl_pin=deepcopy(bound['saved_CL']),module_sha256=next(iter(writer_hashes)))


def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact saved-revision WIP request required')
    require(v['acknowledge_machine_scope']is True and v['qualification_only']is True
        and v['message_policy']=='vendor_default','Explicit all-machine qualification scope required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31
        and type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time'])
        and v['expected_process_create_time']>0 and type(v['operation_native_id'])is int and v['operation_native_id']>0,
        'Explicit strict owner/operation required')
    for key,value in v.items():
        if key.endswith('_sha256'):common.strict_sha(value)
        if key.endswith('_path')or key in ('project_root','output_dir'):
            require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
    require(_file_hash(__file__)==v['module_sha256'],'Exact WIP endpoint module required')
    wp=pin(writer.__file__);require(wp['sha256']==v['writer_module_sha256'],'Frozen writer differs')
    rp=dict(path=v['saved_writer_receipt_path'],sha256=v['saved_writer_receipt_sha256']);r=json.loads(common.direct(rp))
    mp=dict(path=r['dispatch_marker_path'],sha256=v['consumed_writer_marker_sha256'])
    rows=deepcopy(r['postCL']['expected_generated_operations']);protected=[x['operation_native_id']for x in rows if x['operation_native_id']!=v['operation_native_id']]
    bound=binding.bind_completed_revision(rp,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],
        source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'],
        selected_operation_ids=[v['operation_native_id']],protected_operation_ids=protected,
        expected_generated_operations=rows,marker_pin=mp,writer_pin=wp)
    data=load_context_lineage(r,bound)
    key=common._digest(dict(scope=SCOPE,source=str(Path(bound['source_path']).resolve()).casefold(),
        source_sha256=bound['source_sha256'],operation_native_id=v['operation_native_id']))
    marker=Path(bound['source_path']).parent/('circular_revision_wip_'+key+'.json')
    deps=[pin(__file__),pin(binding.__file__),pin(common.__file__),pin(core.__file__),wp]
    directory,canonical=core.output_plan(v['output_dir'],v['project_root'],v['receipt_path'],bound['source_path'],bound['pins']+deps,marker)
    return dict(bound=bound,lineage=data,writer_receipt=r,marker=marker,directory=directory,canonical=canonical,dependencies=deps)


def forbidden(*args,**kwargs):raise ValueError('Only one guarded WIP export is permitted')


class ReadContext(writer.RevisionContext):
    set_change=generate=save=set_tool=set_field=create_sketch=create_feature=insert_rough=export_cl=adopt_saved_source=forbidden
    def __init__(self,sw,clsid,tlb,v,plan,report,persist,runtime_check):
        require(plan['lineage']['loaded']['addin_clsid'].casefold()==clsid.casefold(),'Exact recorded CAM add-in required')
        args=deepcopy(plan['writer_receipt']['request']);args.update(expected_source_sha256=v['expected_source_sha256'])
        super().__init__(sw,clsid,tlb,args,plan['lineage'],report,persist,runtime_check)
        self.wip_plan=plan
        require(self.source==v['expected_source_sha256'] and self.v['process_id']==v['process_id']
            and self.v['expected_process_create_time']==v['expected_process_create_time'],'Current owned source differs')
    def verify_files(self):
        super().verify_files()
        if getattr(self,'_capture_pin_scope',False):return
        if hasattr(self,'wip_plan'):
            for p in self.wip_plan['bound']['pins']+self.wip_plan['dependencies']:common.direct(p)
    def capture_existing(self,label):
        partial={};state=self.capture('wip_'+label,partial)
        with self.guard()as guard:
            doc=guard.typed(self.native['doc'],'ICWDoc3');part=guard.typed(self.native['doc'],'ICWPartDoc')
            machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine')
            require(guard.read(doc,'GetDocType')==1 and guard.read(machine,'MachType')==1,'Exact MILL document required')
        return self.identity(),state,dict(machine=machine)


def revoke(r,error,key='issue'):
    r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r['phase'],phase='finished',
        readback_verified=False,export_files_verified=False,binding_readback_verified=False,
        outer_cleanup_still_required=True,runtime_unchanged=False,production_qualified=False)
    r[key]=_error(error)


def run_backend(ctx,v,plan,r,persist,runtime_check):
    directory,canonical=plan['directory'],plan['canonical'];claimed=False
    def claim():
        nonlocal claimed
        require(not claimed and directory.resolve(strict=True)==canonical and not any(directory.iterdir()),'Fresh empty WIP directory required')
        _write_receipt(plan['marker'],dict(scope=SCOPE,status='claimed_no_replay',source_sha256=v['expected_source_sha256'],
            saved_writer_pin=plan['bound']['receipt_pin'],receipt_path=v['receipt_path'],automatic_replay=False),create=True)
        claimed=True;r['marker_created']=True;persist()
    def invoke(machine):
        value=_member(machine,'CreateSTLOfWIPs2',*r['native_parameters'])
        # Persist return before guard cleanup can raise; never retry this action.
        r.update(native_call_returned=True,native_dispatch_pending=False,native_return_type=type(value).__name__,
            native_return_value=value if type(value)in(bool,int,float,str)or value is None else None)
        persist();return value
    try:
        runtime_check();ctx.start();directory.mkdir();require(directory.resolve(strict=True)==canonical,'WIP output directory changed')
        common.run_existing_core(core,plan['bound'],r,capture_existing=ctx.capture_existing,guard_factory=ctx.guard,
            persist=persist,claim=claim,invoke=invoke,collect=lambda:core.collect_wip_files(directory,canonical))
        ctx.finish();ctx.close()
        require(ctx.closed is True,'Owned context cleanup incomplete')
        common.clean_events(r)
        require(ctx.identity()==plan['bound']['document'],'Clean source changed after cleanup')
        require(core.collect_wip_files(directory,canonical)==r['files'],'WIP bytes changed during cleanup')
        for p in plan['bound']['pins']+plan['dependencies']:common.direct(p)
        runtime_check()
        r.update(status='review_required',phase='finished',runtime_unchanged=True,outer_cleanup_still_required=False,
            source_unchanged=True,cleanup_verified=True,reason='WHOLE_MACHINE_WIP_EXPORT_REQUIRES_LOCAL_GEOMETRY_REVIEW')
    except Exception as error:revoke(r,error)
    finally:
        try:ctx.close()
        except Exception as error:revoke(r,error,'cleanup_error')
        if getattr(ctx,'session',None)is not None:r['messages']=ctx.session.summary()
        try:
            persist()
            if claimed:_write_receipt(plan['marker'],dict(scope=SCOPE,status=r['status'],phase=r['phase'],
                receipt_path=v['receipt_path'],receipt_sha256=_file_hash(v['receipt_path']),source_sha256=v['expected_source_sha256'],
                native_call_attempted=r['native_call_attempted'],native_call_returned=r['native_call_returned'],
                native_dispatch_pending=r['native_dispatch_pending'],automatic_replay=False))
        except Exception as error:
            revoke(r,error,'receipt_write_error')
            try:persist()
            except Exception:pass
    return r


def dispatch(sw,clsid,tlb,*,runtime_check,_context_factory=ReadContext,**v):
    plan=validate(v);abi=preflight(tlb)
    r=common.new_report(plan['bound'],output_dir=plan['directory'],implementation_pin=pin(__file__))
    r.update(adapter_scope=SCOPE,request=deepcopy(v),receipt_path=v['receipt_path'],marker_path=str(plan['marker']),
        captures=[],native_read_count=0,receipt_created=False,marker_created=False,runtime_unchanged=False,
        cleanup_verified=False,source_unchanged=False,outer_cleanup_still_required=True,
        evidence_pins=deepcopy(plan['bound']['pins']),dependencies=deepcopy(plan['dependencies']),abi=abi)
    runtime_check();_write_receipt(v['receipt_path'],r,create=True);r['receipt_created']=True
    persist=lambda:_write_receipt(v['receipt_path'],r)
    try:ctx=_context_factory(sw,clsid,tlb,v,plan,r,persist,runtime_check)
    except Exception as error:revoke(r,error);persist();return r
    return run_backend(ctx,v,plan,r,persist,runtime_check)


def finalize_runtime_failure(r,error):
    revoke(r,error,'runtime_error');_write_receipt(r['receipt_path'],r)
    if r.get('marker_created'):_write_receipt(r['marker_path'],dict(scope=SCOPE,status=r['status'],
        receipt_path=r['receipt_path'],receipt_sha256=_file_hash(r['receipt_path']),automatic_replay=False))
    return r
