"""Same-owner persistence check for a saved mixed-tool deep guide checkpoint.

The existing close/open engine and seventeen/eight/fourteen reader are reused.
This adapter changes only the saved receipt authority and current source binding.
There are no parameter writes, tool assignments, toolpath generation or Save.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_deep_guide_reopen as existing
from scripts import sw_cam_deep_long_tool_replace as replacement
from scripts import sw_cam_deep_long_tool_completed_save as saved_producer
from scripts import sw_cam_long_cut_reconciliation as reconciliation
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash
common,group,cl=existing.common,existing.group,existing.cl
SCOPE='SAVED_LONG_CUT_DEEP_GUIDE_REOPEN_V1'
ACTION='verify_saved_long_cut_guides_reopen'
PARAMS=(existing.PARAMS-{'deep_receipt_path','deep_receipt_sha256'})|{'saved_receipt_path','saved_receipt_sha256'}
NativeBackend=existing.NativeBackend

class Journal(existing.Journal):
    def _marker_state(self):
        state=super()._marker_state();state['scope']=SCOPE;return state

def project_saved(loaded,receipt,p):
    """Project verified Save-only state; preserve mixed-tool shallow/deep groups."""
    c=receipt['replacement_checkpoint_context'];state=c['saved_snapshot']
    require(receipt['saved_source_sha256']==c['source_sha256']==p['expected_source_sha256'],'Exact new saved source required')
    require(receipt['request']['process_id']==p['process_id']==c['process_id']and group.exact(receipt['ownership'],loaded['ownership'])and group.exact(c['ownership'],loaded['ownership']),'Exact saved process lifetime required')
    require(common._key(c['document']['path'])==common._key(p['expected_document_path'])==common._key(receipt['source_path'])and c['document']['type']==1 and c['document']['needs_save']is False,'Exact clean saved part required')
    require(group.exact(c['configuration'],loaded['guide_parameters']['configuration']),'Saved CAM/SW configuration differs')
    require(c['operation_order']==list(replacement.OLD+replacement.IDS)and c['generated_ids']==list(cl.OLD)+list(replacement.IDS),'Exact seventeen/fourteen route required')
    require([r['operation_native_id']for r in state['parameters']]==[322,324,326,328,*replacement.IDS],'Exact eight parameter order required')
    require(group.exact(c['tool_dimensions'],loaded['replacement_tool_dimensions']),'Actual created tool profile differs')
    out=deepcopy(loaded);out['guide_parameters'].update(document=deepcopy(c['document']),baseline=deepcopy(state['binding']),expected_parameters=deepcopy(state))
    out['deep_targets']=deepcopy(c['learned_targets']);out['configuration_tool']=deepcopy(c['tool_dimensions']['generic'])
    out['replacement_tool_dimensions']=deepcopy(c['tool_dimensions']);out['tool_catalogue_ids']=deepcopy(c['tool_catalogue_ids'])
    out['generated']={'saved_cl':deepcopy(c['saved_cl'])};out['source_sha256']=c['source_sha256']
    # Avoid embedding the whole older creation context a second time. Its exact
    # authority and original receipts remain in the immutable proof closure.
    out.pop('tool_creation_context',None)
    return out

def load_checkpoint(p):
    receipt,pin=reconciliation.read_pin(p['saved_receipt_path'],p['saved_receipt_sha256'])
    require(receipt.get('scope')==saved_producer.SCOPE and receipt.get('module_pin')==common._pin(saved_producer.__file__),'Exact installed Save-only producer required')
    cp=receipt['tool_creation_pin'];creation,initial,authority_pin,authority=reconciliation.verified_terminal(cp['path'],cp['sha256'],check_current=False)
    loaded=replacement.projection_from_creation(creation['checkpoint']['context'])
    generated,gp=reconciliation.read_pin(receipt['adopted_generated_receipt_pin']['path'],receipt['adopted_generated_receipt_pin']['sha256'])
    saved_producer.completed_gtp_contract(generated,loaded,receipt['request'])
    saved_producer.validate_completed_save(receipt,generated)
    loaded=project_saved(loaded,receipt,p)
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current saved source changed')
    # Preserve the existing native reader closure and add this adapter.
    # Save-only producer and historical authority are checked as immutable proof.
    loaded['pins']=common._merge(loaded['pins'],[common._pin(__file__)])
    require(1<=len(loaded['pins'])<=64,'Bounded native reader closure required')
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],receipt['checkpoint_pins'],receipt['live_pins'],
        [pin,gp,authority_pin,receipt['saved_cl']['output'],common._pin(__file__),common._pin(existing.__file__),common._pin(saved_producer.__file__),common._pin(reconciliation.__file__)])
    require(len(loaded['checkpoint_pins'])<=320,'Bounded saved reopen proof closure required')
    loaded['configuration_pins']=deepcopy(loaded['checkpoint_pins'])
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,creation['checkpoint']['context']['long_cut_tool_checkpoint']['registration']['clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb');require(common._pin(typelib)in loaded['pins'],'Actual interface library changed')
    abi=replacement.audit_interfaces(typelib,loaded['generated_pin']);p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['native_guard_preflight']=replacement.guard_constructor_preflight(p,loaded,typelib)
    return loaded,registration,typelib,abi,pin

def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact saved long-cut reopen action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact saved reopen parameter set required')
    require(p['acknowledgement']=='immediate_saved_continuation_no_intervening_cam_or_user_changes','Immediate saved continuation required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned process ID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Explicit absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
    require(p['module_sha256']==_file_hash(__file__),'Saved reopen adapter changed')
    loaded,registration,typelib,abi,pin=load_checkpoint(p)
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);output=cl._fresh_path(p['reopened_cl_path'])
    marker=common.local_evidence_root()/('saved_long_cut_reopen_'+group._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.once.json')
    paths=(receipt,progress,marker,output);protected={common._key(v['path'])for v in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in paths})==len(paths),'Separate reopen outputs required')
    for path in paths:require(not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Fresh nonaliased output required; no replay')
    for path in(receipt,progress,marker):require(path.parent.is_dir(),'Existing diagnostic parent required')
    return p,loaded,registration,typelib,abi,receipt,marker,pin

def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,pin=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,source_sha256=p['expected_source_sha256'],live_pin_count=len(loaded['pins']),checkpoint_pin_count=len(loaded['checkpoint_pins']),expected_generated_paths=14,native_guard_preflight=loaded['native_guard_preflight'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=existing.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=deepcopy(loaded['ownership']),deep_checkpoint_pin=pin,interface_audit=abi,cl_persistence_verified=False,model_saved=False,saved_cl_reference={k:deepcopy(loaded['generated']['saved_cl'][k])for k in('output','expected_generated_operations','source_sha256')})
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return existing.reopen.run_backend(backend,journal,loaded)
