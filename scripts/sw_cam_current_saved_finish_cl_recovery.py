"""One CL export after a verified saved Finish whose previous export never began."""
from copy import deepcopy
from pathlib import Path
import json,math,re
from scripts import sw_cam_current_finish_generate as generation
from scripts import sw_cam_current_finish_generation_delta as delta
from scripts import sw_cam_saved_finish_configuration_history as history
from scripts import sw_cam_saved_finish_partial_boundary as partial
from scripts.sw_cam_current_saved_generation import Journal as BaseJournal
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
require=delta.require;exact=delta.exact
SCOPE='CURRENT_SAVED_CIRCULAR_FINISH_CL_RECOVERY_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','generation_receipt_path','generation_receipt_sha256','receipt_path','saved_cl_path','qualification_only','message_policy'}

def binding(v):return {k:deepcopy(x)for k,x in v.items()if k not in('receipt_path','saved_cl_path')}
def marker_path(v):return Path(v['expected_document_path']).parent/('export_saved_circle_finish_'+_digest(dict(scope=SCOPE,binding=binding(v)))+'.json')
def _same(a,b):return Path(a).resolve()==Path(b).resolve()

def _unused_original_export(receipt):
    old_output=Path(receipt['request']['saved_cl_path'])
    require(old_output.is_absolute()and old_output.suffix.lower()=='.cl'and not old_output.exists()and not old_output.is_symlink()and not old_output.parent.exists()and not old_output.parent.is_symlink(),'Original unattempted CL output and directory must remain absent')

def outputs(v,pins):
    from scripts.sw_cam_deep_guide_cl import _fresh_path
    out=Path(v['receipt_path']);marker=marker_path(v);cl=_fresh_path(v['saved_cl_path'])
    key=lambda p:str(Path(p).resolve()).casefold()
    protected={key(v['expected_document_path']),*(key(p['path'])for p in pins)}
    for p in(out,marker):require(p.is_absolute()and p.parent.is_dir()and p.suffix.lower()=='.json'and not p.exists()and not p.is_symlink()and key(p)not in protected,'Fresh recovery receipt and once marker required')
    require(len({key(out),key(marker),key(cl)})==3 and key(cl)not in protected,'Distinct recovery outputs required')
    return str(out),str(marker),str(cl)

def dependency_paths():
    from scripts import sw_cam_current_saved_finish_cl_context as native
    return (__file__,history.__file__,partial.__file__,native.__file__,*generation.dependency_paths())

def validate(v):
    require(type(v)is dict and set(v)==KEYS and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact export-only request required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**32 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact current owner lifetime required')
    for k,x in v.items():
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact lowercase file SHA required')
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute exact file path required')
    source=Path(v['expected_document_path']);sha=v['expected_source_sha256']
    require(source.is_file()and not source.is_symlink()and source.suffix.lower()=='.sldprt'and _file_hash(source)==sha,'Exact current saved source required')
    r,rp=read_pin(v['generation_receipt_path'],v['generation_receipt_sha256'])
    require(_same(r['request']['expected_document_path'],source)and _same(r['request']['receipt_path'],rp['path'])and _same(r['receipt_path'],rp['path']),'Exact partial source and receipt required')
    require(exact(r['binding'],generation.binding(r['request']))and set(r['request'])==generation.KEYS,'Exact raw generation binding required')
    cf,cp=read_pin(r['configuration_receipt_pin']['path'],r['configuration_receipt_pin']['sha256'])
    require(exact(cp,r['configuration_receipt_pin']),'Original configuration pin changed')
    boundary=partial.verify_partial(r,cf,source_sha256=sha,process_id=v['process_id'],process_create_time=v['expected_process_create_time'])
    _unused_original_export(r)
    old_marker=generation.marker_path(r['request']);require(_same(old_marker,r['dispatch_marker_path']),'Original consumed GTP marker differs')
    mark,mp=read_pin(str(old_marker),_file_hash(old_marker))
    expected=dict(scope=generation.SCOPE,receipt_path=rp['path'],receipt_sha256=rp['sha256'],configuration_receipt_pin=cp,selected_operation_native_ids=[boundary['operation_id']],status='uncertain',phase='finished',automatic_replay=False)
    require(_same(mark['receipt_path'],rp['path']),'Old marker receipt path differs');marked=deepcopy(mark);marked['receipt_path']=rp['path'];require(exact(marked,expected),'Exact consumed uncertain generation marker required')
    # Revalidate the original configured lineage once, separating its historical
    # saved SHA from the later Save proven above. Raw historical records stay intact.
    data=history.load_history(cp['path'],cp['sha256'],process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=str(source),source_sha256=r['source_before_sha256'],physical_source_sha256=sha)
    require(exact(data['pin'],cp)and delta.configuration.circular.circular_state_equal(data['state'],r['before']),'Exact configured ancestor required')
    pins=list(data['pins'])+[rp,mp]
    for p in r['evidence_pins']:
        if _same(p['path'],source):require(p['sha256']==r['source_before_sha256'],'Only original generation source pin may advance');continue
        generation.creation.partial._observed_pin(p);pins.append(p)
    pins += [generation.creation.partial._filepin(p)for p in dependency_paths()]
    pins.append(dict(path=str(source),sha256=sha));unique={}
    for p in pins:
        observed=generation.creation.partial._observed_pin(p);key=str(Path(p['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==observed['sha256'],'Conflicting recovery pin');unique[key]=observed
    data.update(pins=list(unique.values()),generation_receipt=deepcopy(r),generation_receipt_pin=rp,generation_marker_pin=mp,saved_boundary_proof=boundary,recovery_saved_state=deepcopy(boundary['state']),source_sha256=sha)
    data['configuration_data']['state']=deepcopy(boundary['state'])
    data['configuration_data']['pins']=deepcopy(data['pins'])
    data['output'],data['marker'],data['saved_cl_path']=outputs(v,data['pins'])
    require(_file_hash(source)==sha and read_pin(rp['path'],rp['sha256'])[1]==rp,'Recovery inputs changed during preparation')
    return data

_ISSUER=object()
class _Prepared:
    def __init__(self,v,data,pins):self.issuer=_ISSUER;self.v=deepcopy(v);self.data=deepcopy(data);self.pins=deepcopy(pins);self.used=False;self.digest=self.fingerprint()
    def fingerprint(self):return _digest(dict(v=self.v,data=self.data,pins=self.pins))
def _prepare_invocation(v,*,runtime_check):
    runtime_check();data=validate(v);pins=[generation.creation.partial._observed_pin(p)for p in data['pins']];runtime_check();return _Prepared(v,data,pins)
def consume(bundle,v,runtime_check):
    require(type(bundle)is _Prepared and bundle.issuer is _ISSUER and bundle.used is False,'Private unused recovery bundle required');bundle.used=True
    require(exact(bundle.v,v)and bundle.fingerprint()==bundle.digest,'Prepared recovery changed');runtime_check()
    for p in bundle.pins:generation.creation.partial._observed_pin(p)
    _unused_original_export(bundle.data['generation_receipt'])
    require(outputs(v,bundle.data['pins'])==(bundle.data['output'],bundle.data['marker'],bundle.data['saved_cl_path']),'Recovery outputs changed');runtime_check();return bundle.data

class Journal(BaseJournal):
    def marker_state(self):return dict(scope=SCOPE,receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),generation_receipt_pin=deepcopy(self.report['generation_receipt_pin']),selected_operation_native_ids=list(self.report['selected_operation_native_ids']),status=self.report['status'],phase=self.report['phase'],automatic_replay=False)
def completed(a):return a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False and a.get('native_return_type')=='int'and type(a.get('native_return_value'))is int and a['native_return_value']==0

def run_once(backend,journal,data):
    r=journal.report;reference=data['recovery_saved_state']
    try:
        journal.create();backend.start();detail=dict(label='before',state={},capture_complete=False);r['captures'].append(detail);r['phase']='before';journal.persist()
        before=backend.capture('before',detail['state']);require(all(before.get(k)is True for k in('capture_complete','extended_capture_complete','parameter_capture_complete')),'One complete fresh saved observation required')
        detail.update(state=deepcopy(before),capture_complete=True);r['before']=deepcopy(before);journal.persist()
        require(delta.configuration.circular.circular_state_equal(before,reference),'Fresh saved boundary differs; no export allowed')
        delta.select(before,data['operation_id'],data['feature_id'],generated=True);require(exact(r['plane_observations']['before'],data['planes']),'Saved plane metadata differs');r['fresh_saved_boundary_verified']=True;backend.boundary();_unused_original_export(data['generation_receipt']);journal.claim()
        action=journal.action('postCL');diagnostic={};r['postCL']=diagnostic;journal.persist()
        result=backend.export_cl('postCL',before,delta.positive_rows(before),diagnostic,pending=lambda:journal.pending('postCL'),returned=lambda value:journal.returned('postCL',value))
        require(completed(action)and result.get('output_verified')is True and result.get('readback_verified')is True,'One verified SaveCLFile required')
        r['postCL']=deepcopy(result);r['CL_preservation']=deepcopy(result['comparison_proof']['CL_preservation']);r['source_after_sha256']=data['source_sha256'];journal.persist();backend.finish()
        r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,CL_verified=True,source_unchanged_verified=True,export_recovery_verified=True,reason='SAVED_CIRCULAR_FINISH_CL_EXPORTED_WITHOUT_MODEL_MUTATION')
    except Exception as exc:r.update(status='uncertain'if r.get('CL_export_attempted')else'error',failed_phase=r.get('phase'),phase='finished',issue=_error(exc),reason=str(exc),readback_verified=False,runtime_unchanged=False,export_recovery_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain'if r.get('CL_export_attempted')else'error',cleanup_error=_error(exc),readback_verified=False,runtime_unchanged=False,export_recovery_verified=False)
        journal.persist()
    return r

def _dispatch_prepared(sw,clsid,tlb,v,bundle,*,runtime_check,_context_factory=None):
    data=consume(bundle,v,runtime_check);require(data['addin_clsid'].casefold()==clsid.casefold(),'Exact registered CAM required')
    from scripts.sw_cam_current_saved_finish_cl_context import Context,preflight
    abi=preflight(tlb,data['definition_mode']);abi.pop('setup_plane_class',None)
    r=dict(scope=SCOPE,status='error',phase='preflight',binding=binding(v),request=deepcopy(v),generation_receipt_pin=data['generation_receipt_pin'],generation_marker_pin=data['generation_marker_pin'],configuration_receipt_pin=data['pin'],evidence_pins=data['pins'],receipt_path=v['receipt_path'],dispatch_marker_path=data['marker'],source_before_sha256=v['expected_source_sha256'],selected_operation_native_ids=[data['operation_id']],selected_feature_native_id=data['feature_id'],saved_boundary_proof=deepcopy(data['saved_boundary_proof']),prior_terminal_status_preserved=data['generation_receipt']['status'],prior_runtime_unchanged=data['generation_receipt']['runtime_unchanged'],prior_saved_source_verified=True,abi=abi,allowed_actions=['postCL'],actions={},captures=[],plane_observations={},target_observations={},draft_observations={},native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,reference_geometry_creation_attempted=False,operation_creation_attempted=False,save_attempted=False,model_saved=False,readback_verified=False,runtime_unchanged=False,export_recovery_verified=False,automatic_replay=False,automatic_rollback=False,production_qualified=False,machining_eligible=False,reopen_persistence_verified=False)
    journal=Journal(data['output'],data['marker'],r);backend=(_context_factory or Context)(sw,clsid,tlb,v,data,r,journal.persist,runtime_check);result=run_once(backend,journal,data)
    try:runtime_check()
    except Exception as exc:return revoke_runtime(result,exc)
    return result

def revoke_runtime(r,error):
    r.update(status='uncertain'if r.get('CL_export_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,export_recovery_verified=False)
    if r.get('receipt_created')is True:
        p=Path(r['receipt_path']);old=json.loads(p.read_text(encoding='utf8'));require(old.get('scope')==SCOPE and exact(old.get('binding'),r['binding']),'Only own export receipt may be revoked');_write_receipt(p,r)
        if r.get('marker_created')is True:
            m=Path(r['dispatch_marker_path']);value=json.loads(m.read_text(encoding='utf8'));require(value.get('scope')==SCOPE and exact(value.get('generation_receipt_pin'),r['generation_receipt_pin'])and _same(value['receipt_path'],p),'Only own export marker may be updated');value.update(status=r['status'],phase=r['phase'],receipt_sha256=_file_hash(p));_write_receipt(m,value)
    return r
