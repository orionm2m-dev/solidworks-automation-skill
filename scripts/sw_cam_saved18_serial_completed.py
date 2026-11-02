"""Offline loader for completed serial V2 evidence; no CAD dispatch or output creation.

The executed V2 producer stays installed and hash-pinned unchanged. The reused
prepare logic differs only by accepting its existing canonical receipt in
completed mode. Original snapshot/CL/marker/producer validators stay intact.
"""
from pathlib import Path
from copy import deepcopy
from scripts import sw_cam_saved18_serial_dirty_verify as serial
opt,dirty,common,group,require=serial.opt,serial.dirty,serial.common,serial.group,serial.require
ACTION,ACK,PARAMS,DIRTY_SHA,SCOPE=serial.ACTION,serial.ACK,serial.PARAMS,serial.DIRTY_SHA,serial.SCOPE
partition,failed_host_contract,marker_path,validate_completed=serial.partition,serial.failed_host_contract,serial.marker_path,serial.validate_completed
EXECUTED_PRODUCER_SHA='1e63fa2fce8cd01244a8b4223a715debfa82e161e0d6d00c6ec2ae3776a1d7f2'

def existing_receipt(path):
    p=Path(path)
    require(p.is_absolute() and p.suffix.casefold()=='.json' and p.parent.is_dir()
        and p.is_file() and not p.is_symlink() and not p.resolve().drive.startswith('\\\\'),
        'Existing local-drive non-symlink JSON receipt required')
    return p

def prepare(request,*,completed=True):
    require(completed is True,'Completed evidence loading only; native dispatch forbidden')
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact serial verification action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS and p['acknowledgement']==ACK,'Exact serial verification parameters required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Owned positive PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute paths required')
        if key.endswith('_sha256'):opt.prior._sha(value)
    require(p['module_sha256']==opt.prior._file_hash(serial.__file__)and common._pin(dirty.__file__)['sha256']==DIRTY_SHA,'Frozen serial/lineage implementations required')
    original,requestpin=opt.prior.read_json_pin(p['dirty_request_path'],p['dirty_request_sha256'])
    # Native-free original preparation rechecks exact source, verified process
    # transition and raw dirty observation. Its host routines are never invoked.
    oldp,loaded,q,old,new,ref,pins,*_=dirty.prepare(original,completed=True)
    require(loaded['ownership']['process_id']==p['process_id']and loaded['source_sha256']==p['expected_source_sha256']and common._key(loaded['guide_parameters']['document']['path'])==common._key(p['expected_document_path']),'Exact owned current source/document required')
    require(loaded['guide_parameters']['document']['needs_save']is True,'Observed dirty input must remain explicit')
    failed,failedpin=opt.prior.read_json_pin(p['host_failure_path'],p['host_failure_sha256'])
    history=failed_host_contract(failed,loaded,original)
    extra=common._merge(pins,[requestpin,failedpin,common._pin(dirty.__file__)])
    partition(loaded,extra)
    p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    tlb=str(Path(loaded['registration']['addin_path']).parent/'camworks.tlb')
    guard=opt.prior.guard_reuse.guard_constructor_preflight(p,loaded,tlb)
    loaded['serial_verification']=dict(dirty_request_pin=requestpin,host_failure_pin=failedpin,host_failure_history=history,native_guard_preflight=guard)
    out=existing_receipt(p['receipt_path']);mark=marker_path(p)
    clpath=Path(p['saved_cl_path'])if completed else opt.cl._fresh_path(p['saved_cl_path'])
    protected={common._key(v['path'])for v in loaded['pins']+loaded['phase_proof_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in (out,mark,clpath)})==3,'Distinct serial outputs required')
    for v in (out,mark,clpath):require(not v.is_symlink()and common._key(v)not in protected and(completed or not v.exists()),'Existing or aliased serial output forbids replay')
    require(out.parent.is_dir(),'Existing local receipt directory required')
    return p,loaded,q,tlb,out,mark

def load_completed_rebind(path,digest,*,check_current=True):
    require(check_current is True,'Current exact source verification required')
    require(common._pin(serial.__file__)['sha256']==EXECUTED_PRODUCER_SHA,'Exact unchanged executed V2 producer required')
    r,rpin=opt.prior.read_json_pin(path,digest)
    require(r.get('module_pin')==common._pin(serial.__file__),'Exact serial verification producer required')
    prepared=prepare(dict(action=ACTION,params=deepcopy(r['request'])),completed=True);p,l,q,tlb,out,mark=prepared
    require(common._key(out)==common._key(path),'Serial receipt output path differs')
    proof=validate_completed(r,l,q);require(group.exact(proof,r['terminal_verification']),'Terminal serial contract differs')
    marker=dirty.read_pin(common._pin(mark));require(marker==dict(scope=SCOPE,status=r['status'],receipt_pin=rpin,automatic_replay=False),'Serial completion marker differs')
    l['reopened_checkpoint_pin']=rpin;l['serial_rebind_qualified']=True;l['host_native_compatibility_qualified']=False
    l['checkpoint_pins']=common._merge(l['checkpoint_pins'],[rpin,common._pin(serial.__file__)])
    return l,q,r,common._merge(l['pins'],l['phase_proof_pins'],[rpin,common._pin(mark)])
