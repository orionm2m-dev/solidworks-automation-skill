"""Verify deep guide persistence with existing same-owner Close/Open.

No GTP, setter, model Save or application exit. Reuses the saved checkpoint;
compares seventeen bindings, eight parameter groups and all fourteen complete CL streams.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_deep_guide_checkpoint as authority
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash

reopen,cl,group,common=authority.reopen,authority.cl,authority.group,authority.common
SCOPE='SAVED_DEEP_GUIDE_REOPEN_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','deep_receipt_path',
    'deep_receipt_sha256','module_sha256','receipt_path','progress_path','reopened_cl_path','acknowledgement'}
ParameterBackend=authority.ParameterBackend


class NativeBackend(reopen.NativeBackend):
    def start(self):
        require(self.parameter_reader is None,'Fresh parameter reader required')
        self.parameter_reader=ParameterBackend(self.loaded,self.args,self.sw,self.clsid,self.typelib_path,self.report,self.persist)
        self.parameter_reader.start()

    def capture_binding(self):
        return self.parameter_reader.capture_binding('before_close_binding')

    def finish(self):
        require(group.exact(self.report['reopened'],self.loaded['guide_parameters']['expected_parameters']),
            'Full reopened state must match before fourteen-stream CL export')
        diagnostic={};self.report['reopened_cl']=diagnostic;self.persist()
        try:
            cl.export_current_cl(self.parameter_reader,'reopened',self.report['reopened']['binding'],self.args['reopened_cl_path'],diagnostic)
            self.report['cl_persistence_comparison']=cl.verify_all(self.loaded['generated']['saved_cl'],diagnostic)
            self.report['cl_persistence_verified']=True
        finally:self.persist()
        return super().finish()


class Journal(reopen.ReopenJournal):
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],receipt_path=str(self.receipt),
            deep_checkpoint_pin=r['deep_checkpoint_pin'],phase=r['phase'],status=r['status'],actions=deepcopy(r['actions']),
            native_dispatch_pending=r.get('native_dispatch_pending',False),reopened_cl=deepcopy(r.get('reopened_cl',{})),automatic_replay=False)


def load_checkpoint(p):
    loaded,registration,typelib,abi,pin=authority.load_checkpoint(p)
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],[common._pin(__file__)])
    require(len(loaded['checkpoint_pins'])<=authority.MAX_CHECKPOINT_PINS+1,'Bounded reopen proof closure required')
    common._check(loaded['checkpoint_pins'])
    return loaded,registration,typelib,abi,pin


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='verify_deep_guides_reopen','Exact generated reopen action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact generated reopen fields required')
    require(p['acknowledgement']=='immediate_saved_continuation_no_intervening_cam_or_user_changes','Immediate saved continuation required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
    require(p['module_sha256']==_file_hash(__file__),'Deep reopen module changed')
    loaded,registration,typelib,abi,pin=load_checkpoint(p)
    pins=loaded['pins']
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);output=cl._fresh_path(p['reopened_cl_path'])
    marker=common.local_evidence_root()/('deep_guide_reopen_'+group._digest(dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    paths=(receipt,progress,marker,output);protected={common._key(v['path'])for v in pins+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in paths})==len(paths),'Separate generated reopen outputs required')
    for path in paths:require(not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Fresh nonaliased output required')
    for path in (receipt,progress,marker):require(path.parent.is_dir(),'Existing diagnostic parent required')
    return p,loaded,registration,typelib,abi,receipt,marker,pin


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,pin=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,source_sha256=p['expected_source_sha256'],
        live_pin_count=len(loaded['pins']),checkpoint_pin_count=len(loaded['checkpoint_pins']),expected_generated_paths=14)
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
            ownership=loaded['ownership'],deep_checkpoint_pin=pin,interface_audit=abi,cl_persistence_verified=False,model_saved=False,
            saved_cl_reference={k:deepcopy(loaded['generated']['saved_cl'][k])for k in ('output','expected_generated_operations','source_sha256')})
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        return reopen.run_backend(backend,journal,loaded)
