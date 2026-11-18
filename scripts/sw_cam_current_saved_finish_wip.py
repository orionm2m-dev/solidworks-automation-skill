"""One guarded WIP export from a verified saved partial-terminal Finish boundary.

Raw predecessor terminal status remains uncertain. This endpoint has no model
writer, simulation, reset, regeneration, Save, CL or NC action. WIP cache age and
material removal require independent subsequent mesh evidence.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_current_saved_finish_read_authority as authority
from scripts import sw_cam_current_route_wip_comparison as comparison
from scripts import sw_cam_current_saved_finish_cl_context as existing
from scripts import sw_cam_reconfigured_circular_wip as inherited
from scripts import sw_cam_completed_gtp_wip as core
from scripts import sw_cam_wip_complete_dispatch_guard as bounded_guard
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _member,_error
require=authority.require
SCOPE='CURRENT_SAVED_PARTIAL_FINISH_WIP_EXPORT_V1'
KEYS=authority.KEYS|{'project_root','output_dir','receipt_path','module_sha256','acknowledge_machine_scope','declared_empty_operation_ids'}

def pin(path):
    p=Path(path);return dict(path=str(p),sha256=_file_hash(p),bytes=p.stat().st_size)

def marker_path(v):
    key=_digest(dict(scope=SCOPE,source=str(Path(v['expected_document_path']).resolve()).casefold(),source_sha256=v['expected_source_sha256'],generation_receipt_sha256=v['generation_receipt_sha256']))
    return Path(v['expected_document_path']).parent/('current_saved_finish_wip_'+key+'.json')

def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact saved-boundary WIP request required')
    require(v['acknowledge_machine_scope']is True,'Explicit all-machine WIP acknowledgement required')
    require(type(v['module_sha256'])is str and v['module_sha256']==_file_hash(__file__),'Exact WIP adapter code required')
    for k in('project_root','output_dir','receipt_path'):require(type(v[k])is str and Path(v[k]).is_absolute(),'Absolute WIP output paths required')
    data=authority.load_saved_boundary({k:deepcopy(v[k])for k in authority.KEYS})
    state=data['recovery_saved_state']
    contract=comparison.comparison_contract(state,process_id=v['process_id'],source_sha256=v['expected_source_sha256'],declared_empty_ids=v['declared_empty_operation_ids'],positive_operation_rows=data['saved_boundary_proof']['positive_rows'])
    deps=[pin(x)for x in(__file__,comparison.__file__,existing.__file__,inherited.__file__,core.__file__,bounded_guard.__file__,bounded_guard.base.__file__)]
    data['pins']=_unique_pins(data['pins']+deps)
    data['configuration_data']['pins']=deepcopy(data['pins'])
    directory,canonical=core.output_plan(v['output_dir'],v['project_root'],v['receipt_path'],v['expected_document_path'],data['pins'],marker_path(v))
    return dict(data=data,contract=contract,directory=str(directory),canonical=str(canonical),marker=str(marker_path(v)))

def _unique_pins(pins):
    out={}
    for p in pins:
        observed=authority.generation.creation.partial._observed_pin(p);key=str(Path(p['path']).resolve()).casefold()
        require(key not in out or out[key]['sha256']==observed['sha256'],'Conflicting WIP evidence');out[key]=observed
    return list(out.values())

_ISSUER=object()
class _Prepared:
    def __init__(self,v,plan):self.issuer=_ISSUER;self.v=deepcopy(v);self.plan=deepcopy(plan);self.used=False;self.digest=_digest(dict(v=self.v,plan=self.plan))

def _prepare_invocation(v,*,runtime_check):
    runtime_check();plan=validate(v);runtime_check();return _Prepared(v,plan)

def consume(bundle,v,runtime_check):
    require(type(bundle)is _Prepared and bundle.issuer is _ISSUER and bundle.used is False,'Private unused WIP bundle required');bundle.used=True
    require(authority.exact(bundle.v,v)and _digest(dict(v=bundle.v,plan=bundle.plan))==bundle.digest,'Prepared WIP request or state changed')
    runtime_check();plan=bundle.plan
    for p in plan['data']['pins']:authority.generation.creation.partial._observed_pin(p)
    directory,canonical=core.output_plan(v['output_dir'],v['project_root'],v['receipt_path'],v['expected_document_path'],plan['data']['pins'],Path(plan['marker']))
    require((str(directory),str(canonical))==(plan['directory'],plan['canonical']),'Prepared output locations changed');runtime_check();return plan

def forbidden(*a,**k):raise ValueError('Saved-boundary WIP permits only one guarded CreateSTLOfWIPs2')

class ReadContext(existing.Context):
    export_cl=generate=save=adopt_saved_source=assign=set_change=create_sketch=create_feature=insert_finish=forbidden
    def __init__(self,sw,clsid,tlb,v,plan,report,persist,runtime_check):
        require(plan['data']['addin_clsid'].casefold()==clsid.casefold(),'Exact recorded CAM add-in required')
        super().__init__(sw,clsid,tlb,v,plan['data'],report,persist,runtime_check)
        self.wip_plan=plan
        # Pure constructor validation of the actual inherited+current pin union.
        # The saved document is comparison metadata, never a new native capture.
        probe=self._new_guard(plan['contract']['document'])
        report['guard_pin_preflight']=dict(probe._wip_pin_preflight,phase='constructor_before_start',document_basis='saved_reference_only')
    def guard_pins(self):
        generated=existing.generated
        pins=generated.configuration.continuation.unique_pins(list(self.pins)+list(self.settings['pins'])+[self.revision['cl_pin']])
        return generated.current_source_pins(pins,self.v['expected_document_path'],self.source,self.generation_request['expected_source_sha256'],self.report)
    def _new_guard(self,expected):
        return bounded_guard.WipCompleteDispatchGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=deepcopy(expected),source_sha256=self.source,evidence_pins=self.guard_pins(),verify_evidence=self.verify_files,verify_owned_process=self.verify_owned_identity_only,check_events=self.check)
    def guard(self):
        require(not getattr(self,'_capture_pin_scope',False),'Dispatch forbidden inside readonly capture')
        expected=self.boundary();self._guard_expected_document=deepcopy(expected)
        return self._new_guard(expected)
    def capture_existing(self,label):
        partial={};state=self.capture('wip_'+label,partial)
        require(authority.exact(self.report['plane_observations']['wip_'+label],self.wip_plan['data']['planes']),'Protected current setup planes changed')
        with self.guard()as guard:
            doc=guard.typed(self.native['doc'],'ICWDoc3');part=guard.typed(self.native['doc'],'ICWPartDoc')
            machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine')
            require(type(guard.read(doc,'GetDocType'))is int and guard.read(doc,'GetDocType')==1,'Current MILL document required')
            require(type(guard.read(machine,'MachType'))is int and guard.read(machine,'MachType')==1,'Current MILL machine required')
        return self.identity(),state,dict(machine=machine)

def new_report(v,plan,abi):
    data=plan['data'];return dict(scope=SCOPE,status='prepared',phase='prepared',request=deepcopy(v),authority_scope=data['authority_scope'],original_terminal_status=data['original_terminal_status'],original_runtime_unchanged=data['original_runtime_unchanged'],completed_producer_claimed=False,generation_receipt_pin=data['generation_receipt_pin'],generation_marker_pin=data['generation_marker_pin'],configuration_receipt_pin=data['pin'],comparison_contract=deepcopy(plan['contract']),source_before_sha256=v['expected_source_sha256'],source_after_sha256=v['expected_source_sha256'],receipt_path=v['receipt_path'],marker_path=plan['marker'],evidence_pins=deepcopy(data['pins']),abi=abi,native_scope='all_wip_parts_all_setups',single_operation_scope_claimed=False,native_method='ICWMachine5.CreateSTLOfWIPs2',native_parameters=[str(plan['directory']).rstrip('/\\')+'\\','wip.stl','',0,0],native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,native_call_count=0,mutation_attempted=False,readback_verified=False,export_files_verified=False,files=[],captures=[],plane_observations={},target_observations={},draft_observations={},native_read_count=0,receipt_created=False,marker_created=False,cleanup_verified=False,source_unchanged=False,runtime_unchanged=False,outer_cleanup_still_required=True,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,model_saved=False,save_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,NC_export_attempted=False,simulation_attempted=False,reference_geometry_creation_attempted=False,operation_creation_attempted=False,automatic_replay=False,automatic_retry=False,cache_freshness_verified=False,material_removal_verified=False,production_qualified=False,machining_eligible=False,reopen_persistence_verified=False)

def revoke(r,error,key='issue'):
    r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r['phase'],phase='finished',readback_verified=False,export_files_verified=False,comparison_readback_verified=False,outer_cleanup_still_required=True,runtime_unchanged=False,cleanup_verified=False,production_qualified=False);r[key]=_error(error)

def run_backend(ctx,v,plan,r,persist,runtime_check):
    directory,canonical=Path(plan['directory']),Path(plan['canonical']);claimed=False
    def claim():
        nonlocal claimed
        require(not claimed and directory.resolve(strict=True)==canonical and not any(directory.iterdir()),'Fresh empty WIP directory required')
        _write_receipt(plan['marker'],dict(scope=SCOPE,status='claimed_no_replay',source_sha256=v['expected_source_sha256'],generation_receipt_pin=plan['data']['generation_receipt_pin'],receipt_path=v['receipt_path'],automatic_replay=False),create=True)
        claimed=True;r['marker_created']=True;persist()
    def invoke(machine):
        value=_member(machine,'CreateSTLOfWIPs2',*r['native_parameters'])
        r.update(native_call_returned=True,native_dispatch_pending=False,native_return_type=type(value).__name__,native_return_value=value if type(value)in(bool,int,float,str)or value is None else None)
        persist();return value
    try:
        runtime_check();ctx.start();directory.mkdir();require(directory.resolve(strict=True)==canonical,'WIP output directory changed')
        comparison.run_existing_core(plan['contract'],r,capture_existing=ctx.capture_existing,guard_factory=ctx.guard,persist=persist,claim=claim,invoke=invoke,collect=lambda:core.collect_wip_files(directory,canonical))
        ctx.finish();ctx.close();require(ctx.closed is True,'Owned context cleanup incomplete');comparison.common.clean_events(r)
        require(ctx.identity()==plan['contract']['document'],'Clean source changed after cleanup')
        require(core.collect_wip_files(directory,canonical)==r['files'],'WIP bytes changed during cleanup')
        for p in plan['data']['pins']:authority.generation.creation.partial._observed_pin(p)
        runtime_check()
        r.update(status='review_required',phase='finished',runtime_unchanged=True,outer_cleanup_still_required=False,outer_authority_cleanup_still_required=False,source_unchanged=True,cleanup_verified=True,reason='SAVED_PARTIAL_BOUNDARY_WIP_EXPORTED_REQUIRES_INDEPENDENT_MESH_REVIEW')
    except Exception as error:revoke(r,error)
    finally:
        try:ctx.close()
        except Exception as error:revoke(r,error,'cleanup_error')
        if getattr(ctx,'session',None)is not None:r['messages']=ctx.session.summary()
        try:
            persist()
            if claimed:_write_receipt(plan['marker'],dict(scope=SCOPE,status=r['status'],phase=r['phase'],receipt_path=v['receipt_path'],receipt_sha256=_file_hash(v['receipt_path']),source_sha256=v['expected_source_sha256'],native_call_attempted=r['native_call_attempted'],native_call_returned=r['native_call_returned'],native_dispatch_pending=r['native_dispatch_pending'],automatic_replay=False))
        except Exception as error:
            revoke(r,error,'receipt_write_error')
            try:persist()
            except Exception:pass
    return r

def _dispatch_prepared(sw,clsid,tlb,v,bundle,*,runtime_check,_context_factory=ReadContext):
    plan=consume(bundle,v,runtime_check);abi=existing.preflight(tlb,plan['data']['definition_mode']);abi.pop('setup_plane_class',None);abi['wip']=inherited.preflight(tlb)
    r=new_report(v,plan,abi);runtime_check();_write_receipt(v['receipt_path'],r,create=True);r['receipt_created']=True
    persist=lambda:_write_receipt(v['receipt_path'],r)
    try:ctx=_context_factory(sw,clsid,tlb,v,plan,r,persist,runtime_check)
    except Exception as error:revoke(r,error);persist();return r
    return run_backend(ctx,v,plan,r,persist,runtime_check)

def revoke_runtime(r,error):
    revoke(r,error,'runtime_error');_write_receipt(r['receipt_path'],r)
    if r.get('marker_created'):_write_receipt(r['marker_path'],dict(scope=SCOPE,status=r['status'],receipt_path=r['receipt_path'],receipt_sha256=_file_hash(r['receipt_path']),automatic_replay=False))
    return r
def verify_export_receipt(receipt):
    """Offline proof gate: immutable saved lineage, raw captures and output bytes.

    Reuses no cached native capture as a fresh observation. A successful result
    binds evidence only; it intentionally does not certify WIP cache freshness,
    material removal, mesh precision, collision clearance or production.
    """
    r=receipt;require(type(r)is dict and r.get('scope')==SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished','Completed WIP adapter receipt required')
    require(not any(k in r for k in('issue','failed_phase','runtime_error','cleanup_error','receipt_write_error')),'WIP receipt has unresolved failure')
    for k in('readback_verified','export_files_verified','comparison_readback_verified','source_unchanged','cleanup_verified','runtime_unchanged','native_call_attempted','native_call_returned','receipt_created','marker_created','raw_empty_rows_preserved'):require(r.get(k)is True,'Completed WIP fact absent: '+k)
    for k in('native_dispatch_pending','outer_cleanup_still_required','outer_authority_cleanup_still_required','GTP_attempted','GOP_attempted','AFR_attempted','model_saved','save_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','CL_export_attempted','NC_export_attempted','simulation_attempted','reference_geometry_creation_attempted','operation_creation_attempted','automatic_replay','automatic_retry','cache_freshness_verified','material_removal_verified','production_qualified','machining_eligible','reopen_persistence_verified','completed_producer_claimed'):require(r.get(k)is False,'Unexpected WIP action/qualification: '+k)
    require(type(r.get('native_call_count'))is int and r['native_call_count']==1 and r.get('native_return_type')=='bool'and r.get('native_return_value')is True,'One strict successful WIP return required')
    require(r.get('native_scope')=='all_wip_parts_all_setups'and r.get('single_operation_scope_claimed')is False,'Honest whole-machine WIP scope required')
    comparison.common.clean_events(r);v=r['request'];require(set(v)==KEYS,'Exact original WIP request required')
    require(_file_hash(__file__)==v['module_sha256'],'Exact WIP implementation differs')
    data=authority.load_saved_boundary({k:v[k]for k in authority.KEYS})
    require(r['authority_scope']==data['authority_scope']and r['original_terminal_status']==data['original_terminal_status']=='uncertain'and r['original_runtime_unchanged']is False,'Original uncertain terminal must remain visible')
    require(authority.exact(r['generation_receipt_pin'],data['generation_receipt_pin'])and authority.exact(r['generation_marker_pin'],data['generation_marker_pin'])and authority.exact(r['configuration_receipt_pin'],data['pin']),'Exact saved ancestry pins required')
    source=data['source_sha256'];require(r['source_before_sha256']==r['source_after_sha256']==v['expected_source_sha256']==source,'WIP source binding differs')
    contract=comparison.comparison_contract(data['recovery_saved_state'],process_id=v['process_id'],source_sha256=source,declared_empty_ids=v['declared_empty_operation_ids'],positive_operation_rows=data['saved_boundary_proof']['positive_rows'])
    require(authority.exact(contract,r['comparison_contract']),'Stored WIP comparison authority differs')
    raw=r['raw_captures'];require(type(raw)is list and [x['label']for x in raw]==['before','after'],'Two actual raw WIP observations required')
    proofs=[]
    for capture in raw:
        proof=comparison.validate_capture(contract,capture['document'],capture['snapshot']);proofs.append(proof)
        require(authority.exact(proof,r[capture['label']]),'Stored normalized capture differs from raw observation')
        require(authority.exact(r['plane_observations']['wip_'+capture['label']],data['planes']),'Current operation/setup planes changed')
    require(authority.exact(proofs[0],proofs[1]),'Protected native WIP observations differ')
    for p in r['evidence_pins']:authority.generation.creation.partial._observed_pin(p)
    expected_pins={(str(Path(p['path']).resolve()).casefold(),p['sha256'])for p in data['pins']}
    actual_pins={(str(Path(p['path']).resolve()).casefold(),p['sha256'])for p in r['evidence_pins']}
    require(expected_pins<=actual_pins,'WIP omitted immutable authority pins')
    root=Path(v['project_root']).resolve();directory=Path(v['output_dir']);canonical=directory.resolve(strict=True)
    require(root.is_dir()and canonical.is_relative_to(root)and canonical!=root,'WIP files outside project root')
    files=core.collect_wip_files(directory,canonical);require(files and authority.exact(files,r['files'])and all(x['stl_extension']and x['bytes']>0 for x in files),'Exact nonempty WIP file set required')
    path=Path(v['receipt_path']);require(path.resolve()==Path(r['receipt_path']).resolve()and authority.exact(authority.read_pin(str(path),_file_hash(path))[0],r),'Durable WIP receipt differs')
    marker=marker_path(v);require(marker.resolve()==Path(r['marker_path']).resolve(),'Exact consumed WIP marker path required')
    marked,_=authority.read_pin(str(marker),_file_hash(marker));expected=dict(scope=SCOPE,status=r['status'],phase=r['phase'],receipt_path=v['receipt_path'],receipt_sha256=_file_hash(path),source_sha256=source,native_call_attempted=True,native_call_returned=True,native_dispatch_pending=False,automatic_replay=False)
    require(authority.exact(marked,expected),'Consumed WIP marker differs')
    return dict(verified=True,source_sha256=source,files=deepcopy(files),comparison_contract=contract,original_terminal_status='uncertain',cache_freshness_verified=False,material_removal_verified=False,native_calls=0)