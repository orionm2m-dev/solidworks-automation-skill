"""Verify generated guide persistence with existing same-owner Close/Open.

No GTP, setter, model Save or application exit. Reuses the saved checkpoint;
compares thirteen bindings, four parameter groups and all ten complete CL streams.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_guide_group_generation as generation
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash

reopen,cl,group,common=generation.reopen,generation.cl,generation.group,generation.common
SCOPE='SAVED_GENERATED_GUIDE_FOUR_REOPEN_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','generated_receipt_path',
    'generated_receipt_sha256','module_sha256','receipt_path','progress_path','reopened_cl_path','acknowledgement'}


def completed_generated(r,p):
    require(r.get('scope')==generation.SCOPE and r.get('module_pin')==common._pin(generation.__file__)
        and r.get('status')=='saved_generated_review_required' and r.get('phase')=='finished','Completed installed selected generation required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','receipt_write_error')),'Uncertain generation cannot authorize close')
    for key in ('readback_verified','generation_readback_verified','protected_cl_verified','saved_cl_verified','model_saved','continuation_ready','GTP_attempted','save_attempted'):
        require(r.get(key)is True,'Completed generation/save proof required: '+key)
    for key in ('native_dispatch_pending','automatic_retry','SetTool_attempted','setter_attempted','operation_creation_attempted','persistence_after_reopen_verified'):
        require(r.get(key)is False,'Unexpected generated checkpoint effect: '+key)
    clean_events(r)
    ids=[v[0]for v in generation.TARGETS]
    require(r['generated_operation_ids']==ids and list(r['actions'])==['GenerateToolpath:'+str(v)for v in ids]+['SaveActiveDocument'],
        'Exactly four selected generations and one Save required')
    for action in r['actions'].values():
        ret=action.get('native_return',{})
        require(action.get('status')=='verified' and action.get('attempted')is True and action.get('returned')is True
            and action.get('readback_verified')is True and action.get('native_dispatch_pending')is False
            and ret.get('python_type')=='int' and ret.get('value_recorded')is True and type(ret.get('value'))is int and ret['value']==0,
            'Native generation/Save action not confirmed')
    parentpin=r['reopen_receipt_pin'];parent,pin=read_pin(parentpin['path'],parentpin['sha256'])
    require(group.exact(pin,parentpin),'Historical reopen pin differs')
    selector=dict(process_id=r['request']['process_id'],expected_document_path=r['source_path'],expected_source_sha256=r['source_sha256'])
    prior,priorpin,oldselected=generation.completed_reopen(parent,selector)
    require(group.exact(r['before'],parent['reopened']) and group.exact(r['recipe'],oldselected['targets'])
        and group.exact(r['ownership'],parent['ownership']),'Generation historical baseline differs')
    generated={}
    for target in oldselected['targets']:
        outcome=r['actions']['GenerateToolpath:'+str(target['operation_native_id'])]['observed']
        generation.status_contract(outcome,target,True);generated[target['operation_native_id']]=deepcopy(outcome['record_counts'])
    generation.verify_snapshot(r['before'],r['generated'],generated);generation.verify_snapshot(r['before'],r['saved'],generated)
    require(group.exact(r['generated'],r['saved']),'Saved generated state differs')
    cl.verify_protected(r['before_cl'],r['generated_cl']);cl.verify_all(r['generated_cl'],r['saved_cl'])
    checkpoint=r['saved_checkpoint_context'];document=checkpoint['document']
    require(type(p['process_id'])is int and p['process_id']==r['request']['process_id']==checkpoint['process_id']==r['ownership']['process_id']
        and group.exact(checkpoint['ownership'],r['ownership']),'Exact saved owner required')
    require(checkpoint['source_sha256']==r['saved_source_sha256']==p['expected_source_sha256']
        and checkpoint['prior_source_sha256']==r['source_sha256'] and checkpoint['source_sha256']!=checkpoint['prior_source_sha256'],
        'Exact new generated Save source required')
    require(document.get('type')==1 and document.get('needs_save')is False
        and common._key(document['path'])==common._key(p['expected_document_path'])==common._key(r['source_path']),
        'Clean exact saved document required')
    require(checkpoint['snapshot_key']=='saved' and checkpoint['snapshot_sha256']==group._digest(r['saved'])
        and checkpoint['prior_reopen_receipt_pin']==parentpin and checkpoint['persistence_after_reopen_verified']is False,
        'Exact saved snapshot lineage required')
    transition=r['source_transition']
    require(transition['strict_save_return']==0 and type(transition['strict_save_return'])is int
        and transition['source_before_sha256']==r['source_sha256'] and transition['source_after_sha256']==p['expected_source_sha256']
        and group.exact(transition['document'],document),'Native Save transition differs')
    require(group.exact(checkpoint['configuration'],oldselected['configuration']),'Saved configuration mapping differs')
    selected=dict(document=deepcopy(document),configuration=deepcopy(checkpoint['configuration']),baseline=deepcopy(r['saved']['binding']),
        expected_parameters=deepcopy(r['saved']),targets=deepcopy(oldselected['targets']))
    return selected,prior['request']['addin_clsid']


class ParameterBackend(reopen.ParameterBackend):
    batch=generation.NativeBackend.batch
    capture_binding=generation.NativeBackend.capture_binding


class NativeBackend(reopen.NativeBackend):
    def start(self):
        require(self.parameter_reader is None,'Fresh parameter reader required')
        self.parameter_reader=ParameterBackend(self.loaded,self.args,self.sw,self.clsid,self.typelib_path,self.report,self.persist)
        self.parameter_reader.start()

    def finish(self):
        reader=self.parameter_reader
        require(group.exact(self.report['reopened'],self.loaded['guide_parameters']['expected_parameters']),
            'Full reopened state must match before CL export')
        diagnostic={};self.report['reopened_cl']=diagnostic;self.persist()
        try:
            cl.export_current_cl(reader,'reopened',self.report['reopened']['binding'],self.args['reopened_cl_path'],diagnostic)
            self.report['cl_persistence_comparison']=cl.verify_all(self.loaded['generated']['saved_cl'],diagnostic)
            self.report['cl_persistence_verified']=True
        finally:self.persist()
        return super().finish()


class Journal(reopen.ReopenJournal):
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],receipt_path=str(self.receipt),
            generated_checkpoint_pin=r['generated_checkpoint_pin'],phase=r['phase'],status=r['status'],actions=deepcopy(r['actions']),
            native_dispatch_pending=r.get('native_dispatch_pending',False),reopened_cl=deepcopy(r.get('reopened_cl',{})),automatic_replay=False)


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='verify_generated_guides_reopen','Exact generated reopen action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact generated reopen fields required')
    require(p['acknowledgement']=='immediate_saved_continuation_no_intervening_cam_or_user_changes','Immediate saved continuation required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
    require(p['module_sha256']==_file_hash(__file__),'Generated reopen module changed')
    r,pin=read_pin(p['generated_receipt_path'],p['generated_receipt_sha256']);selected,addin=completed_generated(r,p)
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current generated source changed')
    pins=deepcopy(r['live_pins']);require(1<=len(pins)<=64,'Bounded inherited read closure required')
    generated=[v for v in pins if Path(v['path']).name.startswith('_FE488661_0BD8_11D6_2012_2018CE99E55F_')and Path(v['path']).suffix=='.py']
    require(len(generated)==1,'Exact generated interface metadata pin required')
    output_pins=[r[key]['output']for key in ('before_cl','generated_cl','saved_cl')]
    loaded=dict(pins=pins,ownership=deepcopy(r['ownership']),guide_parameters=selected,generated_pin=generated[0],generated=r,
        configuration_pins=deepcopy(r['checkpoint_pins']),bootstrap_export_pins=[common._pin(reopen.installation.__file__)],
        checkpoint_pins=common._merge(r['checkpoint_pins'],output_pins,[pin]+[common._pin(v)for v in
            (__file__,generation.__file__,cl.__file__,reopen.__file__,reopen.lifecycle.__file__,reopen.sw_connect.__file__)]))
    require(len(loaded['checkpoint_pins'])<=32,'Bounded generated checkpoint authority required')
    common._check(pins);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,addin);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in pins,'Installed CAM metadata differs')
    abi=generation.audit(typelib,loaded['generated_pin'])
    p['expected_configuration']=selected['configuration']['sw_configuration_name']
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);output=cl._fresh_path(p['reopened_cl_path'])
    marker=common.local_evidence_root()/('generated_guide_reopen_'+group._digest(dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
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
            ownership=loaded['ownership'],generated_checkpoint_pin=pin,interface_audit=abi,cl_persistence_verified=False,model_saved=False,
            saved_cl_reference={k:deepcopy(loaded['generated']['saved_cl'][k])for k in ('output','expected_generated_operations','source_sha256')})
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return reopen.run_backend(backend,journal,loaded)
