"""One saved circular Finish generation through a private validated request."""
from copy import deepcopy
from pathlib import Path
import json, math, re
from scripts import sw_cam_current_circular_finish as creation
from scripts import sw_cam_current_finish_generation_flow as flow
from scripts import sw_cam_current_finish_generation_delta as delta
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
require=delta.require
exact=delta.exact
SCOPE=flow.SCOPE
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','configuration_receipt_path','configuration_receipt_sha256','receipt_path','saved_cl_path','qualification_only','message_policy'}


def binding(v):
    return {k:deepcopy(x) for k,x in v.items() if k not in ('receipt_path','saved_cl_path')}


def marker_path(v):
    return Path(v['expected_document_path']).parent/('generate_circle_finish_'+_digest(dict(scope=SCOPE,binding=binding(v)))+'.json')


def outputs(v,pins):
    from scripts.sw_cam_deep_guide_cl import _fresh_path
    out=Path(v['receipt_path']); marker=marker_path(v); cl=_fresh_path(v['saved_cl_path'])
    key=lambda p:str(Path(p).resolve()).casefold()
    protected={key(v['expected_document_path']),*(key(p['path']) for p in pins)}
    for p in (out,marker):
        require(p.is_absolute() and p.parent.is_dir() and p.suffix.lower()=='.json' and not p.exists() and not p.is_symlink() and key(p) not in protected,'Fresh distinct generation receipt/marker required')
    require(len({key(out),key(marker),key(cl)})==3 and key(cl) not in protected,'Generation outputs alias authority')
    return str(out),str(marker),str(cl)


def dependency_paths():
    from scripts import sw_cam_current_finish_generation_authority as authority
    from scripts import sw_cam_current_finish_generation_context as native
    from scripts import sw_cam_deep_guide_cl as fresh
    from scripts import sw_cam_current_saved_generation as journal
    return (__file__,flow.__file__,journal.__file__,delta.__file__,authority.__file__,native.__file__,native.comparison.__file__,native.pin_verifier.__file__,native.native_generation.__file__,native.selected_generation.__file__,native.configuration.complete_guard.__file__,fresh.__file__)


def validate(v):
    require(type(v)is dict and set(v)==KEYS and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact qualification-only generation request required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**32 and type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact owned process lifetime required')
    for k,x in v.items():
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact lowercase SHA required')
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Explicit absolute path required')
    source=Path(v['expected_document_path'])
    require(source.is_file() and not source.is_symlink() and source.suffix.lower()=='.sldprt' and _file_hash(source)==v['expected_source_sha256'],'Current saved source differs')
    from scripts import sw_cam_current_finish_generation_authority as authority
    data=authority.load_completed(v['configuration_receipt_path'],v['configuration_receipt_sha256'],process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'])
    delta.select(data['state'],data['operation_id'],data['feature_id'])
    pins=list(data['pins'])+[dict(path=str(source),sha256=v['expected_source_sha256'])]
    pins += [creation.partial._filepin(p) for p in dependency_paths()]
    unique={}
    for p in pins:
        p=creation.partial._observed_pin(p); key=str(Path(p['path']).resolve()).casefold()
        require(key not in unique or unique[key]['sha256']==p['sha256'],'Conflicting immutable generation evidence'); unique[key]=p
    data['pins']=list(unique.values())
    data['configuration_data']['pins']=deepcopy(data['pins'])
    data['output'],data['marker'],data['saved_cl_path']=outputs(v,data['pins'])
    return data


_ISSUER=object()
class _Prepared:
    def __init__(self,v,data,pins):
        self.issuer=_ISSUER; self.v=deepcopy(v); self.data=deepcopy(data); self.pins=deepcopy(pins); self.used=False; self.digest=self.fingerprint()
    def fingerprint(self):return _digest(dict(v=self.v,data=self.data,pins=self.pins))


def _prepare_invocation(v,*,runtime_check):
    runtime_check(); data=validate(v)
    pins=[creation.partial._observed_pin(p) for p in data['pins']]
    runtime_check(); return _Prepared(v,data,pins)


def consume(bundle,v,runtime_check):
    require(type(bundle)is _Prepared and bundle.issuer is _ISSUER and bundle.used is False,'Private unused generation bundle required')
    bundle.used=True
    require(exact(bundle.v,v) and bundle.fingerprint()==bundle.digest,'Prepared generation input changed')
    runtime_check()
    for p in bundle.pins:creation.partial._observed_pin(p)
    require(outputs(v,bundle.data['pins'])==(bundle.data['output'],bundle.data['marker'],bundle.data['saved_cl_path']),'Generation outputs changed')
    runtime_check(); return bundle.data


def _dispatch_prepared(sw,clsid,tlb,v,bundle,*,runtime_check,_context_factory=None):
    data=consume(bundle,v,runtime_check)
    require(data['addin_clsid'].casefold()==clsid.casefold(),'Exact CAM registration required')
    from scripts.sw_cam_current_finish_generation_context import Context,preflight
    abi=preflight(tlb,data['definition_mode']); abi.pop('setup_plane_class',None)
    oid=data['operation_id']; fid=data['feature_id']
    r=dict(scope=SCOPE,status='error',phase='preflight',binding=binding(v),request=deepcopy(v),configuration_receipt_pin=data['pin'],evidence_pins=data['pins'],receipt_path=v['receipt_path'],dispatch_marker_path=data['marker'],source_before_sha256=v['expected_source_sha256'],selected_operation_native_ids=[oid],selected_feature_native_id=fid,abi=abi,allowed_actions=['GTP:'+str(oid),'SaveActiveDocument','postCL'],actions={},captures=[],plane_observations={},target_observations={},draft_observations={},native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,reference_geometry_creation_attempted=False,operation_creation_attempted=False,save_attempted=False,model_saved=False,save_readback_verified=False,source_update_verified=False,generation_verified=False,generation_saved=False,readback_verified=False,runtime_unchanged=False,automatic_replay=False,automatic_rollback=False,production_qualified=False,machining_eligible=False,reopen_persistence_verified=False)
    journal=flow.Journal(data['output'],data['marker'],r)
    backend=(_context_factory or Context)(sw,clsid,tlb,v,data,r,journal.persist,runtime_check)
    result=flow.run_once(backend,journal,data)
    try:runtime_check()
    except Exception as exc:return revoke_runtime(result,exc)
    return result


def revoke_runtime(r,error):
    r.update(status='uncertain' if r.get('mutation_attempted') else 'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,generation_saved=False)
    if r.get('receipt_created')is True:
        p=Path(r['receipt_path']); old=json.loads(p.read_text(encoding='utf8'))
        require(old.get('scope')==SCOPE and exact(old.get('binding'),r['binding']),'Only own generation receipt may be revoked')
        _write_receipt(p,r)
        if r.get('marker_created')is True:
            m=Path(r['dispatch_marker_path']); value=json.loads(m.read_text(encoding='utf8'))
            require(value.get('scope')==SCOPE and exact(value.get('configuration_receipt_pin'),r['configuration_receipt_pin']) and exact(value.get('selected_operation_native_ids'),r['selected_operation_native_ids']) and Path(value['receipt_path']).resolve()==p.resolve(),'Only own generation marker may be updated')
            value.update(status=r['status'],phase=r['phase'],receipt_sha256=_file_hash(p)); _write_receipt(m,value)
    return r