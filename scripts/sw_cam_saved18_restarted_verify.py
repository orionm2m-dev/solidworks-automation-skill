"""Verify a newly owned saved18 session: host identity, one snapshot and one CL export.

The old process must already have exited through the verified-empty tool. This
module never closes, starts or loads an application/add-in and never saves CAM.
"""
from copy import deepcopy
from pathlib import Path
import json,time,hashlib,re
from datetime import datetime,timezone
from scripts import sw_cam_saved18_checkpoint as checkpoint
from scripts import sw_cam_saved18_preclose as preclose
from scripts import sw_cam_mill_host_lifecycle as lifecycle
from scripts import sw_cam_host_identity_read as identity
from scripts import sw_cam_inprocess_host_load as loader
from scripts import sw_cam_mill_packet_projection as projection
from scripts import sw_owned_empty_exit as owned_exit
from scripts import sw_cam_local_operation_cl as cl
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _member,_error
common=lifecycle.common
require=common.require
SCOPE='SAVED_EIGHTEEN_NEW_OWNED_HOST_REOPEN_LATE_EXIT_V1'
ACTION='verify_saved_eighteen_after_owned_restart'
PARAMS={'process_id','expected_process_creation_time','expected_document_path','expected_source_sha256','authority_pin','close_receipt_pin','exit_receipt_pin','startup_receipt_pin','late_exit_observation_pin','old_artifact_pin','new_artifact_pin','module_sha256','receipt_path','saved_cl_path'}

def read_pin(pin):return checkpoint.authority.read(pin['path'],pin['sha256'])


def verify_late_transition(loaded,closed,exited,startup,late,exit_pin,late_pin):
    """Qualify observed absence after one returned ExitApp, retaining raw history."""
    require(exited.get('scope')=='OWNED_VERIFIED_EMPTY_SESSION_EXIT_V1'and exited.get('status')=='exit_not_observed'and exited.get('phase')=='finished','Exact original exit timeout required')
    require(exited.get('process_exit_verified')is False and exited.get('readback_verified')is False and exited.get('exit_returned')is True and exited.get('exit_call_count')==1,'Only returned graceful exit with timed-out observation is supported')
    require(exited.get('exit_observation_source')=='WaitForSingleObject_on_retained_verified_process_handle'and exited.get('owner_after_timeout')==exited.get('owner_before'),'Retained exact process was alive at the original deadline')
    require(late.get('scope')=='OWNED_EXIT_LATE_PROCESS_OBSERVATION_V1'and late.get('status')=='exit_observed_after_deadline'and late.get('original_status')=='exit_not_observed'and late.get('original_receipt_modified')is False,'Separate immutable late exit observation required')
    source=late['original_exit_receipt_pin'];require(source['sha256']==exit_pin['sha256']and common.key(source['path'])==common.key(exit_pin['path']),'Late observation refers to another original exit')
    require(late['owner_before']==exited['owner_before']==closed['owner_handle_before_close'],'Exact original PID/FILETIME observation required')
    obs=late['observation'];require(set(obs)=={'api','requested_access','process_id','winerror','process_absent'}and obs['api']=='OpenProcess'and obs['requested_access']=='query limited information and synchronize; no terminate'and type(obs['process_id'])is int and obs['process_id']==loaded['ownership']['process_id']and type(obs['winerror'])is int and obs['winerror']==87 and obs['process_absent']is True,'Exact read-only OS absence observation required')
    require(all(late.get(k)is False for k in ('exit_repeated','termination_attempted','launch_attempted')),'Late observer must not repeat exit, terminate or launch')
    source=late['expected_source_pin'];require(source['sha256']==loaded['source_sha256']and common.key(source['path'])==common.key(loaded['guide_parameters']['document']['path']),'Late observation source differs')
    observed=datetime.fromisoformat(late['observed_utc']);require(observed.tzinfo is not None,'Timezone-aware OS observation required')
    epoch=observed.astimezone(timezone.utc).timestamp()
    require(loaded['ownership']['create_time']<epoch<=startup['launch_intent_time'],'Late absence must precede the new launch')
    # Reuse the unchanged close/exit/startup structural verifier on an explicitly
    # local verification projection. No original receipt/status is overwritten.
    verification=deepcopy(exited);verification.update(status='exited',process_exit_verified=True,readback_verified=True)
    result=checkpoint.verify_transition(loaded,closed,verification,startup)
    result['ownership_transition'].update(exit_basis='late_read_only_OS_absence_after_one_returned_graceful_exit',
        original_exit_status='exit_not_observed',original_exit_receipt_modified=False,late_exit_observation_pin=deepcopy(late_pin))
    return result

def prepare(request,*,completed=False):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact restarted verification action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact restarted verification parameters required')
    require(p['module_sha256']==common.digest(__file__),'Sealed verification implementation differs')
    for name in ('receipt_path','saved_cl_path','expected_document_path'):require(type(p[name])is str and Path(p[name]).is_absolute(),'Absolute document/output path required')
    require(type(p['process_id'])is int and p['process_id']>0 and common.finite(p['expected_process_creation_time']),'Strict new owned process required')
    loaded,q=checkpoint.load_current(p['authority_pin']['path'],p['authority_pin']['sha256'])
    require(p['authority_pin']['sha256']==loaded['qualified_authority_pin']['sha256']and common.key(p['authority_pin']['path'])==common.key(loaded['qualified_authority_pin']['path']),'Authority pin differs')
    closed,exited,startup=(read_pin(p[k])for k in ('close_receipt_pin','exit_receipt_pin','startup_receipt_pin'))
    require(closed['module_pin']==checkpoint.common._pin(preclose.__file__)and exited['client_module_sha256']==common.digest(owned_exit.__file__),'Executed close/exit implementations differ')
    late=read_pin(p['late_exit_observation_pin'])
    loaded=verify_late_transition(loaded,closed,exited,startup,late,p['exit_receipt_pin'],p['late_exit_observation_pin'])
    require(loaded['ownership']['process_id']==p['process_id']and loaded['ownership']['create_time']==p['expected_process_creation_time']and loaded['source_sha256']==p['expected_source_sha256'],'New owned process/source differs')
    require(common.key(loaded['guide_parameters']['document']['path'])==common.key(p['expected_document_path']),'Reopened document differs')
    old=lifecycle.artifact(lifecycle.read_pin(p['old_artifact_pin']),'1.0.0.0');new=lifecycle.artifact(lifecycle.read_pin(p['new_artifact_pin']),lifecycle.VERSION)
    require(old['mvid']!=new['mvid'],'Distinct known old/new host identities required')
    lifecycle.type_library(old['tlb']['path'],mill=False)
    lifecycle.type_library(new['tlb']['path'],mill=True)
    loaded['pins']=checkpoint.common._merge(loaded['pins'],[checkpoint.common._pin(v)for v in (__file__,checkpoint.__file__,preclose.__file__)])
    require(len(loaded['pins'])<=64,'Native live closure exceeds bound')
    transitionpins=[p[k]for k in ('authority_pin','close_receipt_pin','exit_receipt_pin','startup_receipt_pin','late_exit_observation_pin','old_artifact_pin','new_artifact_pin')]
    hostpins=[lifecycle.pin(v.__file__)for v in (checkpoint,preclose,lifecycle,identity,loader,projection,owned_exit,common,cl)]+[lifecycle.pin(__file__)]+[new['dll'],new['tlb']]+new['dependencies']+[old['dll'],old['tlb']]+old['dependencies']
    pins=lifecycle.merge_pins(loaded['pins'],loaded['checkpoint_pins'],transitionpins,hostpins)
    common.check_files(pins)
    ref=checkpoint.host_reference(loaded);p['expected_dirty']=False;p['expected_configuration']=ref['document']['configuration']
    out=Path(p['receipt_path']);clpath=Path(p['saved_cl_path'])if completed else cl._fresh_path(p['saved_cl_path'])
    require(out.suffix.lower()=='.json'and out.parent.is_dir()and not out.is_symlink()and(completed or not out.exists()),'Fresh verification receipt required')
    forbidden={common.key(v['path'])for v in pins}
    require(common.key(out)not in forbidden and common.key(clpath)not in forbidden and common.key(out)!=common.key(clpath),'Aliased verification outputs forbidden')
    marker=out.with_name('saved18_host_'+hashlib.sha256(json.dumps([SCOPE,p['process_id'],p['expected_process_creation_time'],common.key(p['expected_document_path']),p['expected_source_sha256']],separators=(',',':')).encode()).hexdigest()+'.json')
    require((completed or not marker.exists())and not marker.is_symlink()and common.key(marker)not in forbidden|{common.key(out),common.key(clpath)},'Existing verification attempt; do not replay')
    return p,loaded,q,old,new,ref,pins,out,marker

class NativeBackend:
    """Read-only composition. Only exported CL is written by the CAM API."""
    def __init__(self,p,loaded,old,new,reference,report,persist):
        self.p,self.loaded,self.old,self.new,self.reference,self.report,self.persist=p,loaded,old,new,reference,report,persist
        self.reader=loader.LoaderBackend(p);self.parameters=None;self.identity_calls=0;self.mill_calls=0;self.export_calls=0
    def owner(self):return self.reader.owner()
    def application(self):return self.reader.application()
    def document(self):return self.reader.document()
    def identity_once(self):
        require(self.identity_calls==0,'Identity may be read once');self.identity_calls+=1
        return lifecycle.NativeBackend._read(self,self.old,mill=False,text='{}')
    def start_events(self):
        args=dict(process_id=self.p['process_id'],expected_document_path=self.p['expected_document_path'],expected_source_sha256=self.p['expected_source_sha256'],expected_configuration=self.p['expected_configuration'])
        self.parameters=preclose.ReadOnlyParameters(self.loaded,args,self.application(),self.loaded['registration']['clsid'],self.reference['cam_typelib_pin']['path'],self.report,self.persist)
        self.parameters.start();return self.parameters.session.summary()
    def read_once(self):
        require(self.mill_calls==0,'MILL snapshot may be read once');self.mill_calls+=1
        return lifecycle.NativeBackend._read(self,self.new,mill=True,text=json.dumps(self.reference['mill_request'],ensure_ascii=False,allow_nan=False))
    def export_once(self,diagnostic):
        require(self.export_calls==0,'CL export may be called once');self.export_calls+=1
        b=self.parameters;out=cl._fresh_path(self.p['saved_cl_path']);canonical=str(out.resolve());b.boundary()
        with b.ctx.guard()as guard:
            b.doc=guard.typed(guard.read(b.ctx.app,'IGetActiveDoc'),'ICWDoc3')
            part=guard.typed(b.doc,'ICWPartDoc');machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine')
            require(guard.read(machine,'MachType')==1,'Current MILL machine required')
            target=guard.typed(machine,'ICWMachine5');controller=cl.post._controller(guard.read(target,'GetController2'))
            diagnostic['controller']=controller;self.persist();out.parent.mkdir()
            require(not out.parent.is_symlink()and str(out.resolve())==canonical and not out.exists(),'Exclusive fresh CL output changed')
            def pending():diagnostic.update(native_dispatch_pending=True,native_call_attempted=True);self.persist()
            returned=guard.dispatch_once(lambda:_member(target,'SaveCLFile',str(out)),persist_pending=pending)
        diagnostic.update(native_dispatch_pending=False,native_call_returned=True,native_return=checkpoint.group.return_observation(returned));self.persist()
        require(type(returned)is int and returned==0,'Strict SaveCLFile S_OK required');b.boundary()
        with b.ctx.guard()as guard:
            machine=guard.typed(guard.read(guard.typed(b.doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine5')
            require(cl.post._controller(guard.read(machine,'GetController2'))==controller,'Controller changed during export')
        require(out.is_file()and not out.is_symlink()and not out.parent.is_symlink()and str(out.resolve())==canonical and 0<out.stat().st_size<=64*1024*1024 and sorted(v.name for v in out.parent.iterdir())==[out.name],'Invalid native CL output')
        diagnostic['output']=lifecycle.pin(out);self.persist();return diagnostic['output']
    def close_events(self):
        if self.parameters is None:return None
        self.parameters.close();self.parameters.events(False)
        self.report['cleanup_session_active']=self.parameters.session_active
        return self.parameters.session.summary()

def run_prepared(prepared,*,backend=None):
    p,loaded,q,old,new,ref,pins,out,marker=prepared
    require(not out.exists()and not marker.exists(),'Existing verification receipt/marker; no replay')
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request=deepcopy(p),module_pin=lifecycle.pin(__file__),authority_pin=loaded['qualified_authority_pin'],
        late_exit_observation_pin=deepcopy(p['late_exit_observation_pin']),original_exit_status='exit_not_observed',original_exit_receipt_modified=False,
        ownership=deepcopy(loaded['ownership']),historical_ownership=deepcopy(loaded['historical_ownership']),ownership_transition=deepcopy(loaded['ownership_transition']),
        source_sha256=p['expected_source_sha256'],read_only=True,mutation_attempted=False,model_saved=False,GTP_attempted=False,host_load_attempted=False,registration_attempted=False,
        readback_verified=False,persistence_after_reopen_verified=False,automatic_replay=False,production_qualified=False)
    _write_receipt(out,r,create=True)
    def persist():_write_receipt(out,r)
    engine=backend or NativeBackend(p,loaded,old,new,ref,r,persist)
    def boundary():
        common.check_owner(engine.owner(),p);doc=engine.document();common.validate_document(doc,p)
        require(doc==ref['document']and doc['needs_save']is False,'Reopened clean exact document differs')
        common.check_files(pins)
    started=time.perf_counter()
    try:
        boundary();_write_receipt(marker,dict(scope=SCOPE,receipt_path=str(out),status='pending',automatic_replay=False),create=True)
        r.update(phase='ReadTurnIdentity',identity_attempted=True);persist()
        raw=engine.identity_once();r['raw_identity']=raw;persist()
        result=common.decode(raw);r['identity']=identity.classify_identity(result,p,old,new);persist()
        require(r['identity']['loaded_artifact']=='new','Old host still loaded; stop before CAM getters')
        boundary();r['events_before']=engine.start_events();lifecycle.event_check(r['events_before']);persist()
        r.update(phase='ReadMillSnapshot',mill_read_attempted=True);persist();began=time.perf_counter()
        raw=engine.read_once();r['host_call_seconds']=time.perf_counter()-began;r['raw_host_response']=raw;persist()
        packet=common.decode(raw);r['host_response']=packet;persist()
        require(packet.get('host_module_version_id')==new['mvid']and common.key(packet.get('host_assembly_location',''))==common.key(new['dll']['path']),'Host identity changed before MILL read')
        checked=projection.project_packet(packet,ref['mill_request']);r['projection']=checked;persist()
        require(checkpoint.group.exact(checked['snapshot'],ref['expected_snapshot']),'Reopened21/12 semantics differ from saved authority')
        boundary();r.update(phase='SaveCLFile');r['cl_export']={};persist()
        pin=engine.export_once(r['cl_export']);want=q['saved_cl']['output']
        require(pin['sha256']==want['sha256']and pin['bytes']==want['bytes'],'Reopened complete18 CL bytes differ')
        r['cl_verification']=dict(all18_complete_streams_bit_identical=True,protected14_verified=True,source_output_pin=deepcopy(want),output_pin=pin,expected_generated_operations=deepcopy(q['saved_cl']['expected_generated_operations']),bounded_parse_reused_from_identical_qualified_bytes=True)
        r['events_after']=engine.close_events();lifecycle.event_check(r['events_after'],closed=True);boundary()
        r.update(status='saved_eighteen_reopen_verified',phase='finished',loaded_mvid_verified=True,host_native_compatibility_qualified=True,readback_verified=True,persistence_after_reopen_verified=True,document_unchanged_verified=True)
    except Exception as exc:
        r.update(status='error',phase='finished',issue=_error(exc),readback_verified=False,persistence_after_reopen_verified=False)
        try:
            final=engine.close_events()
            if final is not None:r['events_after']=final
        except Exception as clean:r['cleanup_issue']=_error(clean)
    r['elapsed_seconds']=time.perf_counter()-started;persist()
    if marker.exists():_write_receipt(marker,dict(scope=SCOPE,status=r['status'],receipt_pin=lifecycle.pin(out),automatic_replay=False))
    return r

def dispatch_request(request,*,validate_only=False):
    prepared=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,counts=prepared[5]['counts'],host_expected_mvid=prepared[4]['mvid'])
    with common.solidworks_operation_lock(timeout_seconds=1,process_id=prepared[0]['process_id']):return run_prepared(prepared)


def load_completed_rebind(path,digest,*,check_current=True):
    """Current reopened authority only; historical future-Save loading is separate."""
    require(check_current is True,'This loader requires the current unchanged saved source')
    r=checkpoint.authority.read(path,digest)
    require(r.get('scope')==SCOPE and r.get('status')=='saved_eighteen_reopen_verified'and r.get('phase')=='finished','Completed new-owned saved18 verification required')
    require(r.get('module_pin')==lifecycle.pin(__file__)and not any(k in r for k in ('issue','cleanup_issue')),'Exact successful verifier required')
    require(all(r.get(k)is True for k in ('readback_verified','persistence_after_reopen_verified','loaded_mvid_verified','host_native_compatibility_qualified','document_unchanged_verified')),'Complete reopened persistence proof required')
    require(all(r.get(k)is False for k in ('mutation_attempted','model_saved','GTP_attempted','host_load_attempted','registration_attempted','automatic_replay','production_qualified')),'Unexpected modifying/replayed verification')
    req={k:deepcopy(r['request'][k])for k in PARAMS}
    p,loaded,q,old,new,ref,pins,out,marker=prepare(dict(action=ACTION,params=req),completed=True)
    require(common.key(path)==common.key(out)and r['source_sha256']==q['source_sha256']and r['authority_pin']==loaded['qualified_authority_pin']and r['ownership']==loaded['ownership']and r['ownership_transition']==loaded['ownership_transition'],'Terminal provenance differs')
    require(r['cleanup_session_active']is False,'CAM event session still active')
    lifecycle.event_check(r['events_before']);lifecycle.event_check(r['events_after'],closed=True)
    actual=identity.classify_identity(common.decode(r['raw_identity']),p,old,new)
    require(actual==r['identity']and actual['loaded_artifact']=='new','Actual identity receipt differs')
    packet=common.decode(r['raw_host_response']);require(packet==r['host_response'],'Raw host packet differs')
    require(packet.get('host_module_version_id')==new['mvid']and common.key(packet.get('host_assembly_location',''))==common.key(new['dll']['path']),'Actual host identity differs')
    checked=projection.project_packet(packet,ref['mill_request'])
    require(checkpoint.group.exact(checked,r['projection'])and checkpoint.group.exact(checked['snapshot'],loaded['current_snapshot']),'Actual reopened snapshot differs')
    clpin=r['cl_export']['output'];checkpoint.authority.check(clpin)
    require(clpin['sha256']==q['saved_cl']['output']['sha256']and clpin['bytes']==q['saved_cl']['output']['bytes']and r['cl_verification']['expected_generated_operations']==q['saved_cl']['expected_generated_operations'],'Full saved18 CL identity differs')
    ret=r['cl_export']['native_return'];require(ret['python_type']=='int'and ret['value_recorded']is True and type(ret['value'])is int and ret['value']==0 and r['cl_export']['native_call_returned']is True and r['cl_export']['native_dispatch_pending']is False,'One successful native CL export required')
    final_marker=lifecycle.read_pin(lifecycle.pin(marker))
    require(final_marker==dict(scope=SCOPE,status=r['status'],receipt_pin=lifecycle.pin(out),automatic_replay=False),'Completion marker differs')
    loaded['reopened_checkpoint_pin']=lifecycle.pin(path);loaded['host_reference']=ref;loaded['host_artifact']=new
    loaded['checkpoint_pins']=checkpoint.common._merge(loaded['checkpoint_pins'],pins,[lifecycle.pin(path),clpin,lifecycle.pin(marker)])
    loaded['phase_proof_pins']=deepcopy(loaded['checkpoint_pins']);return loaded,q,r,deepcopy(loaded['checkpoint_pins'])


def build_request(*,authority_pin,close_receipt_pin,exit_receipt_pin,startup_receipt_pin,late_exit_observation_pin,old_artifact_pin,new_artifact_pin,receipt_path,saved_cl_path):
    """Seal only actual completed close/exit/new-launch evidence, offline."""
    loaded,q=checkpoint.load_current(authority_pin['path'],authority_pin['sha256'])
    startup=read_pin(startup_receipt_pin)
    request=dict(action=ACTION,params=dict(process_id=startup['process_id'],expected_process_creation_time=startup['process_identity']['create_time'],
        expected_document_path=loaded['guide_parameters']['document']['path'],expected_source_sha256=loaded['source_sha256'],
        authority_pin=deepcopy(authority_pin),close_receipt_pin=deepcopy(close_receipt_pin),exit_receipt_pin=deepcopy(exit_receipt_pin),startup_receipt_pin=deepcopy(startup_receipt_pin),
        late_exit_observation_pin=deepcopy(late_exit_observation_pin),old_artifact_pin=deepcopy(old_artifact_pin),new_artifact_pin=deepcopy(new_artifact_pin),module_sha256=common.digest(__file__),receipt_path=str(receipt_path),saved_cl_path=str(saved_cl_path)))
    prepare(request)
    return request
