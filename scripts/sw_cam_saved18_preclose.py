"""Close one verified clean saved21/12/18 part; no Save, exit, launch or GTP."""
from copy import deepcopy
from pathlib import Path
from decimal import Decimal
from scripts import sw_owned_process_recovery as process
import re
from scripts import sw_cam_saved18_checkpoint as checkpoint
from scripts import sw_cam_local_operation_native as native
from scripts import sw_cam_guide_group_reopen as reuse
from scripts.sw_cam import _error
require,common,group=reuse.require,reuse.common,reuse.group
SCOPE='SAVED_EIGHTEEN_CLOSE_FOR_OWNED_RESTART_V1'
ACTION='close_saved_eighteen_for_owned_restart'
PARAMS={'process_id','expected_document_path','expected_source_sha256','authority_path','authority_sha256','module_sha256','receipt_path','acknowledgement'}
ACK='close_one_clean_saved_part_no_save_no_gtp_no_exit_no_replay'

def forbidden(*args,**kwargs):raise ValueError('Mutation outside saved checkpoint close scope')

class ReadOnlyParameters(native.NativeBackend):
    insert=assign=set_field=set_nc=generate=save=forbidden
    def __init__(self,*args):
        super().__init__(*args,before_generate=forbidden,exporter=forbidden)
        self.learned=deepcopy(self.loaded['deep_targets'])
    def capture_snapshot(self,label,*,full=False,own=None):
        require(full is False and own is None,'Preclose must not repeat full parameter reads')
        return super().capture_snapshot(label,full=False)

class NativeBackend(reuse.NativeBackend):
    def __init__(self,*args):
        super().__init__(*args);self.process_api=None;self.process_handle=None
    def _owner_handle(self):
        actual=self.process_api.identity(self.process_handle);want=self.loaded['ownership']
        require(type(actual['process_id'])is int and actual['process_id']==want['process_id']and actual['alive']is True and common._key(actual['executable'])==common._key(want['executable']),'Retained live owned process required')
        epoch=Decimal(actual['creation_filetime']-process._EPOCH)/Decimal(10_000_000)
        require(abs(epoch-Decimal(str(want['create_time'])))<Decimal('.001'),'Owned creation FILETIME differs from saved lifetime')
        prior=self.report.get('owner_handle_before')
        if prior is not None:require(actual==prior,'Retained process identity changed')
        return actual
    def check_clean(self):
        reuse.NativeBackend.check_clean(self)
        actual=self._owner_handle();self.report['owner_handle_before_close']=actual
        docs=reuse._member(self.sw,'GetDocuments')
        require(type(docs)in(list,tuple)and len(docs)==1,'Exactly one owned document required before close')
        require(common._key(reuse._member(docs[0],'GetPathName'))==common._key(self.args['expected_document_path'])and reuse._member(docs[0],'GetSaveFlag')is False,'Single owned document must be the clean target')
        self.persist()
    def start(self):
        require(self.parameter_reader is None,'Fresh reader required')
        self.process_api=process.Win32ProcessAPI();self.process_handle=self.process_api.open(self.args['process_id'],terminate=False)
        self.report['owner_handle_before']=self._owner_handle();self.persist()
        self.parameter_reader=ReadOnlyParameters(self.loaded,self.args,self.sw,self.clsid,self.typelib_path,self.report,self.persist)
        self.parameter_reader.start()
    def capture_binding(self):return self.parameter_reader.capture_binding('preclose')
    open_target=forbidden
    def close(self):
        try:super().close()
        finally:
            if self.process_handle is not None:
                self.process_api.close(self.process_handle);self.process_handle=None

class Journal(reuse.ReopenJournal):
    def _marker_state(self):
        value=super()._marker_state();value['scope']=SCOPE;return value

def run_backend(backend,journal,loaded):
    require(not journal.created and not journal.claimed,'Existing close attempt cannot replay')
    r=journal.report;r.update(status='prepared',phase='prepared',actions={},mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        native_dispatch_pending=False,save_attempted=False,GTP_attempted=False,exit_attempted=False,launch_attempted=False,
        close_verified=False,readback_verified=False,automatic_retry=False,persistence_after_reopen_verified=False,production_qualified=False)
    journal.create()
    try:
        backend.start();r['before_close_binding']=backend.capture_binding();journal.persist()
        require(group.exact(r['before_close_binding'],loaded['current_snapshot']['binding']),'Current21 binding/counts differ from saved authority')
        r.update(preclose_parameters_reused_from_saved_receipt=True,preclose_parameter_changes_independently_excluded=False,
            cam_dirty_state='No independent CAM dirty getter; exact clean saved continuation and exclusive process lock required')
        journal.persist();backend.check_clean();journal.execute('CloseActiveDocument',backend.close_target)
        r['open_documents_after_close']=backend.verify_closed();require(r['open_documents_after_close']==[],'Owned process must be empty after the single target close');r['close_verified']=True;journal.verified('CloseActiveDocument',True)
        backend.disconnect_closed();r.update(status='saved_part_closed',phase='finished',readback_verified=True)
    except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
        journal.persist()
    return r

def prepare(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact close action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS and p['acknowledgement']==ACK,'Exact close request required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict positive owned PID required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v)is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v)is str and re.fullmatch('[0-9a-f]{64}',v),'Exact SHA required')
    require(p['module_sha256']==reuse._file_hash(__file__),'Sealed close implementation differs')
    loaded,q=checkpoint.load_current(p['authority_path'],p['authority_sha256'])
    require(loaded['ownership']['process_id']==p['process_id']and loaded['source_sha256']==p['expected_source_sha256']and common._key(loaded['guide_parameters']['document']['path'])==common._key(p['expected_document_path']),'Exact current ownership/document/source required')
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['pins']=common._merge(loaded['pins'],[common._pin(__file__),common._pin(checkpoint.__file__),common._pin(process.__file__)])
    require(len(loaded['pins'])<=64,'Native live proof budget exceeded')
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=loaded['registration'];typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in loaded['pins'],'Actual CAM typelib differs')
    audit=reuse.reader.pocket.audit_interfaces(typelib,loaded['generated_pin'])
    receipt=common._local_receipt(p['receipt_path']);marker=receipt.with_name('saved18_close_'+group._digest(dict(scope=SCOPE,pid=p['process_id'],source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    forbidden_paths={common._key(v['path'])for v in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    for path in (receipt,marker):require(path.parent.is_dir()and not path.exists()and not path.is_symlink()and common._key(path)not in forbidden_paths,'Fresh nonaliased close outputs required')
    require(common._key(receipt)!=common._key(marker),'Distinct receipt/marker required')
    return p,loaded,registration,typelib,audit,receipt,marker

def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,audit,receipt,marker=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,counts=dict(operations=21,parameters_reused=12,paths=18),live_pin_count=len(loaded['pins']))
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
        sw,_=reuse.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
            ownership=deepcopy(loaded['ownership']),authority_pin=deepcopy(loaded['qualified_authority_pin']),interface_audit=audit)
        journal=Journal(r,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,r,journal.persist)
        return run_backend(backend,journal,loaded)
