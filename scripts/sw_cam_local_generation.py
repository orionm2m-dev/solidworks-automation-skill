"""Generate only four saved configured operations, save once, and export18 paths.

No tool/feature/operation creation or parameter setters are exposed. Unexpected
NC changes preserve completed generation evidence and stop before model Save.
"""
from copy import deepcopy
from pathlib import Path
from math import isfinite
import hashlib
from scripts import sw_cam_local_saved_context as context
from scripts.sw_cam_rough_firstcut import require
configured=context.configured;prior=context.prior;common=context.common;group=context.group
engine=configured.engine;config=configured.config;generation=configured.generation
SCOPE='SAVED_CONFIGURED_LOCAL_FOUR_GENERATION_V1'
ACTION='generate_configured_local_group'
ACK='generate4_saved_configured_operations_save1_export18_no_setters_no_replay'
PARAMS={'process_id','expected_document_path','expected_source_sha256','configuration_receipt_path','configuration_receipt_sha256','module_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}

def marker_path(p):
    identity='\0'.join((SCOPE,common._key(p['expected_document_path']),p['expected_source_sha256']))
    return common.local_evidence_root()/('local_configured_gtp_'+hashlib.sha256(identity.encode()).hexdigest()+'.json')

class Journal(configured.assembly.Journal):
    def _marker_state(self):return dict(super()._marker_state(),scope=SCOPE,configuration_receipt_pin=self.report['configuration_receipt_pin'])
    def entry(self,name):
        allowed={'SaveActiveDocument'}|{'GTP:'+str(i)for i in self.report['actual_new_ids']}
        require(name in allowed,'Only four selected generation calls and one Save are permitted')
        return super().entry(name)

class NativeBackend(prior.NativeBackend):
    def insert(self,*a,**k):raise ValueError('Operation insertion forbidden')
    def assign(self,*a,**k):raise ValueError('Tool assignment forbidden')
    def set_field(self,*a,**k):raise ValueError('Recipe mutation forbidden')
    def set_nc(self,*a,**k):raise ValueError('NC mutation forbidden in generation packet')


def describe_nc_drift(before,after,targets,counts):
    """An exact diagnostic, never permission to accept or restore a new NC value."""
    normal=deepcopy(after);old={v['operation_native_id']:v for v in before['parameters']}
    selected={v['operation_native_id']for v in targets};changes=[]
    for row in normal['parameters']:
        oid=row['operation_native_id']
        if oid not in selected:continue
        for field in ('GetSpndlSpeed','XYFeed'):
            a=old[oid]['nc']['feeds_compensation'][field];b=row['nc']['feeds_compensation'][field]
            if group.exact(a,b):continue
            require(type(b)in(int,float)and isfinite(b)and b>0,'Nonpositive or nonfinite observed NC is not a restore candidate')
            changes.append(dict(operation_native_id=oid,field=field,before=deepcopy(a),observed=deepcopy(b)))
            row['nc']['feeds_compensation'][field]=deepcopy(a)
    require(changes,'An observed NC difference is required')
    engine.verify_generation(before,normal,targets,counts,{t['key']:[]for t in targets})
    return dict(status='EXACT_NC_ONLY_DIFFERENCES_REVIEW_REQUIRED',changes=changes,
        other_parameters_and_bindings_exact=True,automatic_acceptance=False,automatic_restore=False,
        GTP_replay_allowed=False,CL_feed_update_without_GTP_qualified=False,
        next_action='Separately seal the exact observed state and planned spindle-then-XY restoration; read back and verify actual exported CL before claiming its feed corrected',
        physical_cutting_conditions_qualified=False,production_qualified=False)


def run_once(backend,journal,loaded):
    require(not journal.created and not journal.claimed and not journal.receipt.exists()and not journal.marker.exists(),'Fresh unclaimed generation journal required before any report change')
    r=journal.report;c=loaded['configuration_generation'];baseline=loaded['guide_parameters']['expected_parameters']
    backend.learned=deepcopy(c['targets']);ids=engine.ids(backend.learned,'operation_native_id')
    r.update(status='error',phase='preflight',actions={},actual_new_ids=ids,learned_targets=deepcopy(backend.learned),
        mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
        GTP_attempted=False,model_saved=False,readback_verified=False,automatic_retry=False,automatic_rollback=False,
        operation_creation_attempted=False,tool_assignment_attempted=False,parameter_setter_attempted=False,
        physical_cutting_conditions_qualified=False,production_qualified=False,geometry_accepted=False,persistence_after_reopen_verified=False,
        continuation_ready=False,completed_gtp_counts={},feed_policy={t['key']:[]for t in backend.learned})
    try:
        journal.create();backend.start();r['before']=backend.capture_snapshot('saved_configuration_before_gtp',full=True)
        require(group.exact(r['before'],c['snapshot']),'Fresh complete21/12 differs from saved configuration')
        configured.cl.contract(r['before']['binding'],baseline['binding'],backend.learned)
        r['configured']=deepcopy(r['before']);r['nc_readbacks']=deepcopy(c['nc_readbacks']);journal.persist()
        counts={}
        for target in backend.learned:
            oid=target['operation_native_id'];label='GTP:'+str(oid)
            def pending():r['GTP_attempted']=True;journal.pending(label)
            journal.entry(label)
            # The reused generate implementation binds typed interfaces before
            # dispatch_once claims the vendor call. Its Boolean diagnostic is
            # required to be a bool, without inventing True as an idle signal.
            result=backend.generate(target,pending)
            action=r['actions'][label];require(action['attempted']is True,'Generation bypassed pending journal')
            action.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(result))
            r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist()
            require(type(result)is int and result==0,'Exact GenerateToolpath HRESULT0 required')
            backend.refresh_dirty();outcome=backend.outcome(target);generation.status_contract(outcome,target,True)
            counts[oid]=deepcopy(outcome['record_counts']);r['completed_gtp_counts']=deepcopy(counts);journal.verified(label,outcome)
        r['generated']=backend.capture_snapshot('generated_four',full=True);journal.persist()
        try:r['generation_verification']=engine.verify_generation(r['configured'],r['generated'],backend.learned,counts,r['feed_policy'])
        except Exception:
            try:r['nc_restore_candidate']=describe_nc_drift(r['configured'],r['generated'],backend.learned,counts)
            except Exception:r['nc_restore_candidate']=dict(status='NOT_PROVEN_NC_ONLY',automatic_restore=False,GTP_replay_allowed=False)
            journal.persist();raise
        r['save_stage']={};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['generated'])
            r['saved']=backend.capture_snapshot('saved_generated_four',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['generated']),'Save changed the complete generated21/12 snapshot')
        def save():
            value=backend.save();a=r['actions']['SaveActiveDocument'];require(a['attempted']is True,'Save bypassed pending')
            a.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value));r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved source did not advance');r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding'])
        r['saved_cl_verification']=prior.cl.verify_saved(loaded['generated']['saved_cl'],r['saved_cl'],backend.learned,r['saved'])
        backend.finish();r.update(status='saved_configured_local_generation_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:
        from scripts.sw_cam import _error
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:
            from scripts.sw_cam import _error
            r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r


def validate_completed(r,loaded):
    c=loaded['configuration_generation'];targets=c['targets'];ids=engine.ids(targets,'operation_native_id')
    require(r['scope']==SCOPE and r['status']=='saved_configured_local_generation_review_required'and r['phase']=='finished','Completed selected-generation receipt required')
    require(r['readback_verified']is True and r['model_saved']is True and r['GTP_attempted']is True and r['continuation_ready']is True and r['native_dispatch_pending']is False,'Complete saved nonpending generation required')
    require(not any(r.get(k)for k in ('issue','cleanup_issue','terminal_issue','nc_restore_candidate')),'Unknown or altered generation state cannot authorize Save')
    prior.clean_events(r)
    for key in ('operation_creation_attempted','tool_assignment_attempted','parameter_setter_attempted','physical_cutting_conditions_qualified','production_qualified','geometry_accepted','persistence_after_reopen_verified'):
        require(r[key]is False,'Unqualified or forbidden scope must remain false')
    require(group.exact(r['configuration_receipt_pin'],loaded['configuration_receipt_pin'])and group.exact(r['learned_targets'],targets)and r['actual_new_ids']==ids,'Exact saved authority and four learned IDs required')
    require(group.exact(r['before'],c['snapshot'])and group.exact(r['configured'],r['before']),'Exact saved configuration adoption required')
    require(list(r['actions'])==['GTP:'+str(i)for i in ids]+['SaveActiveDocument'],'Exactly four once-only GTP calls followed by one Save required')
    counts={int(k):v for k,v in r['completed_gtp_counts'].items()};require(set(counts)==set(ids),'All four native outcomes required')
    for t in targets:
        a=r['actions']['GTP:'+str(t['operation_native_id'])];configured.verified_action(a)
        require(a['attempted']is True and a['returned']is True,'Each selected GTP must have a real completed vendor call')
        generation.status_contract(a['observed'],t,True)
        require(group.exact(a['observed']['record_counts'],counts[t['operation_native_id']]),'Outcome/CL count differs')
    policy={t['key']:[]for t in targets};require(group.exact(r['feed_policy'],policy),'No new feed transition was authorized')
    proof=engine.verify_generation(r['configured'],r['generated'],targets,counts,policy)
    require(group.exact(proof,r['generation_verification'])and group.exact(r['saved'],r['generated']),'Saved generation proof differs')
    a=r['actions']['SaveActiveDocument'];configured.verified_action(a);new=prior._sha(r['saved_source_sha256'])
    require(a['attempted']is True and a['observed']==new and new!=r['source_sha256'],'Actual one changed-source Save required')
    transition=r['source_transition'];require(transition['source_before_sha256']==r['source_sha256']and transition['source_after_sha256']==new and type(transition['strict_save_return'])is int and transition['strict_save_return']==0 and transition['document']['needs_save']is False,'Strict native Save and clean document required')
    clproof=prior.cl.verify_saved(loaded['generated']['saved_cl'],r['saved_cl'],targets,r['saved'])
    require(group.exact(clproof,r['saved_cl_verification'])and r['saved_cl']['source_sha256']==new,'Saved18 CL authority differs')
    require([v['phase']for v in r['phase_proof_checks']]==['before_native_start','before_save','after_export_and_cleanup']and all(v['verified']is True for v in r['phase_proof_checks']),'Complete phase proof checks required')
    return dict(status='saved_selected_generation_authority_verified',operations=21,parameters=12,paths=18,new_generated_paths=4,protected_old_paths=14,source_sha256=new,geometry_accepted=False,production_qualified=False)


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact configured-generation action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact generation fields required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31 and p['acknowledgement']==ACK,'Exact selected PID and bounded action acknowledgement required')
    for key,v in p.items():
        if key.endswith('_path'):require(type(v)is str and Path(v).is_absolute(),'Absolute explicit path required')
        if key.endswith('_sha256'):prior._sha(v)
    require(p['module_sha256']==prior._file_hash(__file__),'Generation module changed')
    r,pin=prior.read_json_pin(p['configuration_receipt_path'],p['configuration_receipt_sha256'],limit=32*1024*1024)
    historical,outer,verification,extra=context.reconstruct_configuration(r)
    loaded,outer=context.project_current(r,historical,outer,p)
    require(prior._file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current saved source differs')
    prior.partition_pins(outer,loaded,common._merge(extra,[pin,common._pin(__file__),common._pin(context.__file__)]))
    own=common._pin(__file__);loaded['pins']=common._merge(loaded['pins'],[own]);loaded['phase_proof_pins']=[v for v in loaded['phase_proof_pins']if common._key(v['path'])!=common._key(own['path'])]
    require(len(loaded['pins'])+1<=64,'Native closure plus source exceeds64')
    loaded['pin_partition'].update(live_file_count=len(loaded['pins']),maximum_with_source=len(loaded['pins'])+1,phase_proof_count=len(loaded['phase_proof_pins']))
    registration=common.discover_export_registration(loaded,outer['registration']['clsid']);require(group.exact(registration,outer['registration']),'Checked registration changed')
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb');require(common._pin(typelib)in loaded['pins'],'Exact native typelib required')
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    loaded['native_guard_preflight']=prior.guard_reuse.guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);mark=marker_path(p);outputs=[receipt,Path(p['progress_path']),mark,prior.cl.prior._fresh_path(p['saved_cl_path'])]
    protected={common._key(v['path'])for v in loaded['pins']+loaded['phase_proof_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in outputs})==4,'Separate new output files required')
    for out in outputs:require(not out.exists()and not out.is_symlink()and common._key(out)not in protected,'Existing output or evidence alias forbids replay')
    for out in outputs[:3]:require(out.parent.is_dir(),'Existing output parent required')
    loaded.update(configuration_receipt_pin=pin,configuration_terminal_verification=verification,dispatch_ready=True)
    return p,loaded,registration,typelib,receipt,mark


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,receipt,mark=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_partition=loaded['pin_partition'],native_guard_preflight=loaded['native_guard_preflight'],targets=engine.ids(loaded['configuration_generation']['targets'],'operation_native_id'),allowed_actions='GTP4+Save1+CL18',setters_allowed=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=2,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['phase_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,request=deepcopy(p),module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],configuration_receipt_pin=deepcopy(loaded['configuration_receipt_pin']),ownership=deepcopy(loaded['ownership']),live_pins=deepcopy(loaded['pins']),phase_proof_pins=deepcopy(loaded['phase_proof_pins']),pin_partition=deepcopy(loaded['pin_partition']),tool_dimensions=deepcopy(loaded['local_tool_dimensions']))
        journal=Journal(r,receipt,mark)
        backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,r,journal.persist,before_generate=prior.nc.before_generate,exporter=prior.cl.export_saved)
        run_once(backend,journal,loaded)
        if r['readback_verified']is True:
            try:
                r['terminal_verification']=validate_completed(r,loaded)
                r['saved_checkpoint']=dict(source_path=p['expected_document_path'],source_sha256=r['saved_source_sha256'],document=deepcopy(r['source_transition']['document']),configuration=deepcopy(loaded['guide_parameters']['configuration']),snapshot=deepcopy(r['saved']),saved_cl=deepcopy(r['saved_cl']),learned_targets=deepcopy(r['learned_targets']),tool_catalogue=deepcopy(loaded['serial_flat_catalogue']),tool_dimensions=deepcopy(loaded['local_tool_dimensions']),current_counts=dict(operations=21,parameters=12,paths=18,tools=21),GTP_complete=True,nominal_geometry_accepted=False,production_qualified=False)
            except Exception as exc:
                from scripts.sw_cam import _error
                r.update(status='uncertain',readback_verified=False,continuation_ready=False,terminal_issue=_error(exc))
            journal.persist()
        return r
