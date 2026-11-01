"""Export one whole-machine WIP from the saved deep-guide checkpoint.

Reuses the completed deep-packet verifier, existing parameter reader and established
CreateSTLOfWIPs2 export protocol. No setters, generation, Save or document closure.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_deep_guide_checkpoint as authority
from scripts import sw_cam_completed_gtp_wip as core
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_rough_firstcut import require

group,common,generation=authority.group,authority.common,authority.generation
SCOPE='SAVED_DEEP_GUIDE_WHOLE_MACHINE_WIP_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','deep_receipt_path','deep_receipt_sha256',
    'module_sha256','receipt_path','progress_path','output_dir','project_root','acknowledgement'}
MAX_CHECKPOINT_PINS=authority.MAX_CHECKPOINT_PINS+2


def expected_generated(binding):
    rows=authority.cl.contract(binding)
    require(len(rows)==14,'Exactly fourteen saved generated streams required')
    return rows


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='export_deep_guides_wip','Exact WIP action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact deep WIP fields required')
    require(p['acknowledgement']=='export_existing_saved_whole_machine_wip_no_generation','Explicit whole-machine scope required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path')or key in ('output_dir','project_root'):
            require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
    require(p['module_sha256']==_file_hash(__file__),'WIP adapter changed')
    loaded,registration,typelib,abi,pin=authority.load_checkpoint(p)
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],[common._pin(__file__),common._pin(core.__file__)])
    require(len(loaded['checkpoint_pins'])<=MAX_CHECKPOINT_PINS,'Bounded WIP proof closure required')
    common._check(loaded['checkpoint_pins']);expected=expected_generated(loaded['guide_parameters']['baseline'])
    marker=common.local_evidence_root()/('deep_guide_wip_'+group._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.json')
    directory,canonical=core.output_plan(p['output_dir'],p['project_root'],p['receipt_path'],p['expected_document_path'],loaded['pins']+loaded['checkpoint_pins'],marker)
    progress=Path(p['progress_path']);protected={common._key(v['path'])for v in loaded['pins']+loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(progress.parent.is_dir()and not progress.exists()and not progress.is_symlink()
        and common._key(progress)not in protected and common._key(progress)not in {common._key(x)for x in (directory,canonical,marker,Path(p['receipt_path']))}
        and not progress.resolve().is_relative_to(canonical),'Fresh separate progress path required')
    return p,dict(loaded=loaded,registration=registration,typelib=typelib,abi=abi,pin=pin,marker=marker,directory=directory,canonical=canonical,expected=expected)


def capture(backend,p,plan,label):
    snapshot=backend.capture_parameters('wip_'+label)
    require(group.exact(snapshot,plan['loaded']['guide_parameters']['expected_parameters']),
        'WIP export changed saved parameters, route, tool or path records')
    require(expected_generated(snapshot['binding'])==plan['expected'],'Generated route changed')
    with backend.ctx.guard()as guard:
        active=guard.read(backend.ctx.app,'IGetActiveDoc');doc=guard.typed(active,'ICWDoc3');part=guard.typed(active,'ICWPartDoc')
        machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine')
        require(guard.read(doc,'GetDocType')==1 and guard.read(machine,'MachType')==1,'Exact MILL document required')
    identity=backend.ctx.identity()
    require(group.exact(identity,plan['loaded']['guide_parameters']['document'])and identity['needs_save']is False
        and _file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Exact clean source changed')
    return dict(document=identity,saved_file_sha256=p['expected_source_sha256'],snapshot=snapshot),{'machine':machine}


def run_backend(backend,p,plan,report,persist):
    directory,canonical=plan['directory'],plan['canonical']
    try:
        backend.start();directory.mkdir();require(directory.resolve(strict=True)==canonical,'WIP output directory changed')
        def claim():
            require(not any(directory.iterdir())and directory.resolve(strict=True)==canonical,'WIP output changed before dispatch')
            _write_receipt(plan['marker'],dict(scope=SCOPE,source_sha256=p['expected_source_sha256'],receipt_path=p['receipt_path'],output_dir=str(directory),
                status='native_export_claimed_no_replay'),create=True)
        core.run_one_wip_export(report,capture=lambda label:capture(backend,p,plan,label),guard_factory=backend.ctx.guard,persist=persist,
            claim=claim,invoke=lambda machine:_member(machine,'CreateSTLOfWIPs2',*report['native_parameters']),
            collect=lambda:core.collect_wip_files(directory,canonical))
        backend.finish()
        require(group.exact(backend.ctx.identity(),plan['loaded']['guide_parameters']['document'])
            and core.collect_wip_files(directory,canonical)==report['files'],'WIP/source changed after cleanup')
        common._check(plan['loaded']['pins']);common._check(plan['loaded']['checkpoint_pins'])
        report.update(status='review_required',phase='finished',phase_proofs_verified_after_export=True,checkpoint_export_readback_verified=True)
    except Exception as exc:
        report.update(status='uncertain'if report['mutation_attempted']else'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,export_files_verified=False)
    finally:
        try:generation.close_checked(backend,report)
        except Exception as exc:report.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,export_files_verified=False)
        persist()
    return report


def new_report(p,plan):
    return dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],
        deep_checkpoint_pin=plan['pin'],module_pin=common._pin(__file__),expected_generated_operations=plan['expected'],
        native_scope='all_wip_parts_all_setups',single_operation_scope_claimed=False,native_method='ICWMachine5.CreateSTLOfWIPs2',
        native_parameters=[str(plan['directory'])+'\\','wip.stl','',0,0],export_quality_raw=0,export_quality_label='FINE',
        native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,native_call_count=0,mutation_attempted=False,
        readback_verified=False,export_files_verified=False,files=[],GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,model_saved=False,
        setter_attempted=False,assignment_attempted=False,simulation_attempted=False,automatic_replay=False,automatic_retry=False,
        geometry_verified=False,geometry_acceptance_complete=False,mesh_error_bound_qualified=False,temporal_collision_verified=False,production_qualified=False,
        phase_proofs_verified_after_export=False,checkpoint_export_readback_verified=False,runtime_pins=plan['loaded']['pins'],
        checkpoint_pins=plan['loaded']['checkpoint_pins'],marker_path=str(plan['marker']),request=deepcopy(p),interface_audit=plan['abi'])


def dispatch_request(request,*,validate_only=False):
    p,plan=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(plan['loaded']['pins']),
        checkpoint_pin_count=len(plan['loaded']['checkpoint_pins']),expected_generated_operations=plan['expected'],
        native_parameters=[str(plan['directory'])+'\\','wip.stl','',0,0])
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=authority.reopen.sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=new_report(p,plan);persist=lambda:_write_receipt(p['receipt_path'],report)
        _write_receipt(p['receipt_path'],report,create=True)
        backend=authority.ParameterBackend(plan['loaded'],p,sw,plan['registration']['clsid'],plan['typelib'],report,persist)
        return run_backend(backend,p,plan,report,persist)
