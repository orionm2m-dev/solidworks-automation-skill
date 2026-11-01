"""Verify corrected guide finish persistence with existing same-owner Close/Open.

No GTP, setter, model Save or application exit. Reuses the saved checkpoint;
compares thirteen bindings, four parameter groups and all ten complete CL streams.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_guide_finish_cnc_zero as correction
generation = correction.generation
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash

reopen,cl,group,common=generation.reopen,generation.cl,generation.group,generation.common
SCOPE='SAVED_CORRECTED_GUIDE_FINISH_REOPEN_V1'
MAX_PARENT_CHECKPOINT_PINS=36
MAX_CHECKPOINT_PINS=44
PARAMS={'process_id','expected_document_path','expected_source_sha256','corrected_receipt_path',
    'corrected_receipt_sha256','module_sha256','receipt_path','progress_path','reopened_cl_path','acknowledgement'}


def completed_corrected(r,p):
    require(r.get('scope')==correction.SCOPE and r.get('module_pin')==common._pin(correction.__file__)
        and r.get('status')=='saved_finish_cnc_candidate_review_required' and r.get('phase')=='finished',
        'Completed installed two-finish correction required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','receipt_write_error')),
        'Uncertain correction cannot authorize close')
    for key in ('readback_verified','generation_readback_verified','protected_cl_verified','saved_cl_verified','model_saved',
            'continuation_ready','GTP_attempted','save_attempted','setter_attempted','empirical_finish_cutcom_absence_verified'):
        require(r.get(key)is True,'Completed correction/save proof required: '+key)
    for key in ('native_dispatch_pending','automatic_retry','SetTool_attempted','operation_creation_attempted','persistence_after_reopen_verified'):
        require(r.get(key)is False,'Unexpected corrected checkpoint effect: '+key)
    clean_events(r)
    ids=list(correction.IDS)
    labels=[label+str(oid)for oid in ids for label in ('SetCNCComp:','GenerateToolpath:')]+['SaveActiveDocument']
    require(r['changed_operation_ids']==r['regenerated_operation_ids']==ids and list(r['actions'])==labels,
        'Exactly two selected NC changes, two generations and one Save required')
    for action in r['actions'].values():
        ret=action.get('native_return',{})
        require(action.get('status')=='verified' and action.get('attempted')is True and action.get('returned')is True
            and action.get('readback_verified')is True and action.get('native_dispatch_pending')is False
            and ret.get('python_type')=='int' and ret.get('value_recorded')is True and type(ret.get('value'))is int and ret['value']==0,
            'Native correction/generation/Save action not confirmed')
    parentpin=r['generated_checkpoint_pin'];parent,pin=read_pin(parentpin['path'],parentpin['sha256'])
    require(group.exact(pin,parentpin),'Historical generated pin differs')
    selector=dict(process_id=r['request']['process_id'],expected_document_path=r['source_path'],expected_source_sha256=r['source_sha256'])
    oldselected,addin=correction.saved_loader.completed_generated(parent,selector)
    require(group.exact(r['before'],parent['saved']) and group.exact(r['recipe'],oldselected['targets'])
        and group.exact(r['ownership'],parent['ownership']),'Correction historical baseline differs')
    warnings=correction.load_warnings(r['request'],r['ownership'])
    require(group.exact(warnings,r['warning_receipt_pins']),'Historical warning receipts differ')
    if r.get('zero_attempt_predecessor_pin')is not None:
        prior_loaded=dict(ownership=r['ownership'],generated_checkpoint_pin=parentpin,guide_parameters=oldselected,generated=parent)
        _,failure_pin,_,_=correction.load_zero_attempt(r['request'],prior_loaded)
        require(group.exact(failure_pin,r['zero_attempt_predecessor_pin']),'Zero-attempt predecessor differs')
    else:
        require(not any(k.startswith('zero_attempt_receipt_')for k in r['request']),'Missing zero-attempt predecessor pin')
    readbacks=r['candidate_readbacks']
    require(type(readbacks)is list and [v['operation_native_id']for v in readbacks]==ids,'Exact two candidate readbacks required')
    for item in readbacks:
        oid=item['operation_native_id'];before=correction.nc_row(r['before'],oid)['nc']['feeds_compensation']
        after=correction.nc_row(r['saved'],oid)['nc']['feeds_compensation']
        require(group.exact(item['before'],before) and group.exact(item['after'],after)
            and group.exact(item['proof'],correction.candidate.verify_candidate_readback(before,after)),
            'Candidate readback differs from saved NC parameters')
    regenerated={}
    for target in [v for v in oldselected['targets']if v['operation_native_id']in ids]:
        outcome=r['actions']['GenerateToolpath:'+str(target['operation_native_id'])]['observed']
        generation.status_contract(outcome,target,True);regenerated[target['operation_native_id']]=deepcopy(outcome['record_counts'])
    correction.verify_snapshot(r['before'],r['generated'],ids,regenerated)
    correction.verify_snapshot(r['before'],r['saved'],ids,regenerated)
    require(group.exact(r['generated'],r['saved']),'Saved corrected state differs')
    require(group.exact(r['before_cl'],parent['saved_cl']),'Correction reused CL differs from saved parent')
    correction.finish_cl.verify_protected_eight(r['before_cl'],r['generated_cl'])
    correction.finish_cl.verify_finish_without_cutcom(r['generated_cl'])
    cl.verify_all(r['generated_cl'],r['saved_cl'])
    checkpoint=r['saved_checkpoint_context'];document=checkpoint['document']
    require(type(p['process_id'])is int and p['process_id']==r['request']['process_id']==checkpoint['process_id']==r['ownership']['process_id']
        and group.exact(checkpoint['ownership'],r['ownership']),'Exact saved owner required')
    require(checkpoint['source_sha256']==r['saved_source_sha256']==p['expected_source_sha256']
        and checkpoint['prior_source_sha256']==r['source_sha256'] and checkpoint['source_sha256']!=checkpoint['prior_source_sha256'],
        'Exact new corrected Save source required')
    require(document.get('type')==1 and document.get('needs_save')is False
        and common._key(document['path'])==common._key(p['expected_document_path'])==common._key(r['source_path']),
        'Clean exact saved document required')
    require(checkpoint['snapshot_key']=='saved' and checkpoint['snapshot_sha256']==group._digest(r['saved'])
        and checkpoint['prior_generated_checkpoint_pin']==parentpin and checkpoint['persistence_after_reopen_verified']is False,
        'Exact saved snapshot lineage required')
    transition=r['source_transition']
    require(transition['strict_save_return']==0 and type(transition['strict_save_return'])is int
        and transition['source_before_sha256']==r['source_sha256'] and transition['source_after_sha256']==p['expected_source_sha256']
        and group.exact(transition['document'],document),'Native Save transition differs')
    require(group.exact(checkpoint['configuration'],oldselected['configuration']),'Saved configuration mapping differs')
    selected=dict(document=deepcopy(document),configuration=deepcopy(checkpoint['configuration']),baseline=deepcopy(r['saved']['binding']),
        expected_parameters=deepcopy(r['saved']),targets=deepcopy(oldselected['targets']))
    return selected,addin


# Preserve the already tested generated-route lifecycle and CL persistence reader.
# Only checkpoint authority differs after the two approved NC parameter changes.
ParameterBackend=correction.saved_loader.ParameterBackend
NativeBackend=correction.saved_loader.NativeBackend


class Journal(reopen.ReopenJournal):
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],receipt_path=str(self.receipt),
            corrected_checkpoint_pin=r['corrected_checkpoint_pin'],phase=r['phase'],status=r['status'],actions=deepcopy(r['actions']),
            native_dispatch_pending=r.get('native_dispatch_pending',False),reopened_cl=deepcopy(r.get('reopened_cl',{})),automatic_replay=False)


def load_checkpoint(p):
    r,pin=read_pin(p['corrected_receipt_path'],p['corrected_receipt_sha256']);selected,addin=completed_corrected(r,p)
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current corrected source changed')
    pins=deepcopy(r['live_pins']);require(1<=len(pins)<=64,'Bounded inherited read closure required')
    generated=[v for v in pins if Path(v['path']).name.startswith('_FE488661_0BD8_11D6_2012_2018CE99E55F_')and Path(v['path']).suffix=='.py']
    require(len(generated)==1,'Exact generated interface metadata pin required')
    output_pins=[r[key]['output']for key in ('before_cl','generated_cl','saved_cl')]
    loaded=dict(pins=pins,ownership=deepcopy(r['ownership']),guide_parameters=selected,generated_pin=generated[0],generated=r,
        configuration_pins=deepcopy(r['checkpoint_pins']),bootstrap_export_pins=[common._pin(reopen.installation.__file__)],
        checkpoint_pins=common._merge(r['checkpoint_pins'],output_pins,[pin]+[common._pin(v)for v in
            (__file__,correction.__file__,correction.saved_loader.__file__,generation.__file__,cl.__file__,reopen.__file__,reopen.lifecycle.__file__,reopen.sw_connect.__file__)]))
    require(len(r['checkpoint_pins'])<=MAX_PARENT_CHECKPOINT_PINS and len(loaded['checkpoint_pins'])<=MAX_CHECKPOINT_PINS,'Bounded corrected checkpoint authority required')
    common._check(pins);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,addin);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in pins,'Installed CAM metadata differs')
    abi=generation.audit(typelib,loaded['generated_pin'])
    p['expected_configuration']=selected['configuration']['sw_configuration_name']
    return loaded,registration,typelib,abi,pin


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='verify_corrected_guides_reopen','Exact generated reopen action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact generated reopen fields required')
    require(p['acknowledgement']=='immediate_saved_continuation_no_intervening_cam_or_user_changes','Immediate saved continuation required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
    require(p['module_sha256']==_file_hash(__file__),'Corrected reopen module changed')
    loaded,registration,typelib,abi,pin=load_checkpoint(p)
    pins=loaded['pins']
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);output=cl._fresh_path(p['reopened_cl_path'])
    marker=common.local_evidence_root()/('corrected_guide_reopen_'+group._digest(dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    paths=(receipt,progress,marker,output);protected={common._key(v['path'])for v in pins+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in paths})==len(paths),'Separate generated reopen outputs required')
    for path in paths:require(not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Fresh nonaliased output required')
    for path in (receipt,progress,marker):require(path.parent.is_dir(),'Existing diagnostic parent required')
    return p,loaded,registration,typelib,abi,receipt,marker,pin


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,pin=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,source_sha256=p['expected_source_sha256'],
        live_pin_count=len(loaded['pins']),checkpoint_pin_count=len(loaded['checkpoint_pins']),expected_generated_paths=10)
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
            ownership=loaded['ownership'],corrected_checkpoint_pin=pin,interface_audit=abi,cl_persistence_verified=False,model_saved=False,
            saved_cl_reference={k:deepcopy(loaded['generated']['saved_cl'][k])for k in ('output','expected_generated_operations','source_sha256')})
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return reopen.run_backend(backend,journal,loaded)
