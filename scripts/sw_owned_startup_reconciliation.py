"""Read-only reconciliation of one timed-out, provably owned executable startup."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import re
from scripts.sw_cam import _member,_error
from scripts.sw_cam_feature_sketch import _call_method
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_inprocess_reader import require,key,check_files
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_owned_empty_exit import validate_ownership
from scripts.sw_owned_process_recovery import Win32ProcessAPI,_match_identity,_EPOCH
from scripts.sw_operation_guard import solidworks_operation_lock

SCOPE='OWNED_STARTUP_RECONCILIATION_V1'
FIELDS={'process_id','expected_creation_filetime','expected_executable_path',
    'startup_receipt_path','startup_receipt_sha256','receipt_path'}


def parameters(value):
    require(type(value) is dict and set(value)==FIELDS,'Exact startup reconciliation fields required')
    p=deepcopy(value)
    require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict exact PID required')
    require(type(p['expected_creation_filetime']) is int and _EPOCH<p['expected_creation_filetime']<2**63,'Exact creation FILETIME required')
    for name in ('expected_executable_path','startup_receipt_path','receipt_path'):
        require(type(p[name]) is str and 0<len(p[name])<=32767 and Path(p[name]).is_absolute(),'Absolute bounded paths required')
    require(Path(p['expected_executable_path']).name.casefold()=='sldworks.exe','Exact SOLIDWORKS executable required')
    require(type(p['startup_receipt_sha256']) is str and re.fullmatch('[0-9a-f]{64}',p['startup_receipt_sha256']),'Exact startup SHA256 required')
    require(Path(p['startup_receipt_path']).suffix.lower()=='.json' and Path(p['receipt_path']).suffix.lower()=='.json','JSON receipts required')
    return p


def prepare(p):
    owned,pin=read_pin(p['startup_receipt_path'],p['startup_receipt_sha256'])
    require(owned.get('status')=='uncertain' and owned.get('phase')=='waiting_for_exact_pid_rot',
        'Only the recorded ROT-wait startup timeout can be reconciled')
    require(owned.get('automatic_retry') is False and owned.get('termination_attempted') is False,
        'Startup must have no retry or termination')
    require(owned.get('user_control_verified') is False and owned.get('visible_verified') is False,
        'Unexpected later startup phase proof')
    require(key(owned.get('startup_receipt_path',''))==key(p['startup_receipt_path']),'Original startup receipt path differs')
    error=owned.get('error')
    require(type(error) is dict and error.get('type')=='SolidWorksConnectionError'
        and type(error.get('message')) is str and error['message'].startswith('[SW_PROCESS_NOT_FOUND]'),
        'Only exact PID ROT-not-found startup evidence accepted')
    prior=owned.get('known_process_ids_before')
    require(type(prior) is list and len(prior)<=8192 and all(type(x) is int and 0<=x<2**32 for x in prior)
        and len(set(prior))==len(prior),'Bounded genuine pre-launch PID inventory required')
    # Reuse the existing ownership identity/timing predicate without broadening it.
    candidate=deepcopy(owned);candidate.update(status='ok',phase='connected')
    validate_ownership(candidate,p)
    out=Path(p['receipt_path'])
    require(out.parent.is_dir() and not out.exists() and not out.is_symlink()
        and key(out)!=key(p['startup_receipt_path']),'Fresh separate output required; original is immutable')
    return owned,dict(path=pin['path'],sha256=pin['sha256']),out


class NativeBackend:
    def __init__(self,p):self.p=p;self.api=None;self.handle=None;self.sw=None
    def start(self):
        self.api=Win32ProcessAPI();self.handle=self.api.open(self.p['process_id'],terminate=False)
        _match_identity(self.p,self.api.identity(self.handle))
        from scripts.sw_connect import connect_solidworks
        self.sw,_=connect_solidworks(process_id=self.p['process_id'],launch_new_instance=False,wait_seconds=1)
    def owner(self):return self.api.identity(self.handle)
    def snapshot(self):
        pid=_call_method(self.sw,'GetProcessID')
        require(type(pid) is int and pid==self.p['process_id'],'Connected proxy is not the owned PID')
        docs=_call_method(self.sw,'GetDocuments')
        require(docs is None or type(docs) in (tuple,list) and len(docs)==0,'Session must contain no documents, including hidden ones')
        require(_member(self.sw,'ActiveDoc') is None,'Session has an active document')
        require(_member(self.sw,'UserControl') is True,'UserControl must already be true; no setter used')
        try:visible=_member(self.sw,'Visible')
        except Exception:visible=None
        if type(visible) is not bool:visible=None
        return dict(process_id=pid,documents=[],document_count=0,active_document=None,user_control=True,visible=visible)
    def close(self):
        if self.handle is not None:self.api.close(self.handle);self.handle=None


def run_reconciliation(params,*,backend=None):
    p=parameters(params);owned,pin,out=prepare(p);engine=backend or NativeBackend(p)
    r=dict(scope=SCOPE,status='pending',phase='reconcile_owned_startup',process_id=p['process_id'],
        mutation_attempted=False,launch_attempted_by_reconciliation=False,termination_attempted=False,
        close_document_attempted=False,save_attempted=False,exit_attempted=False,
        ownership_verified=False,readback_verified=False,original_receipt_preserved=False,
        reconciliation_source=dict(pin,original_status=owned['status'],original_phase=owned['phase']),
        request=p)
    _write_receipt(out,r,create=True)
    try:
        engine.start();before=engine.owner();_match_identity(p,before)
        first=engine.snapshot();require(engine.owner()==before,'Owner changed during first read')
        check_files([pin])
        second=engine.snapshot();after=engine.owner();_match_identity(p,after)
        require(first==second and before==after,'Process or empty-session observations changed')
        # Verify fake/native backend results equally; no claimed snapshot can skip guards.
        expected=dict(process_id=p['process_id'],documents=[],document_count=0,active_document=None,user_control=True)
        require(set(first)==set(expected)|{'visible'} and all(first[k]==v for k,v in expected.items())
            and type(first.get('process_id')) is int and type(first.get('document_count')) is int
            and first.get('user_control') is True and (type(first['visible']) is bool or first['visible'] is None),
            'Complete strict empty user-controlled snapshot required')
        check_files([pin])
        reconciled=deepcopy(owned);original_error=reconciled.pop('error')
        reconciled.update(r)
        reconciled.update(status='ok',phase='connected',startup_receipt_path=str(out),
            user_control_verified=True,visible_verified=second["visible"] is True,visible_observed=second["visible"],ownership_verified=True,readback_verified=True,
            original_receipt_preserved=True,live_identity=after,empty_session=second,
            original_startup_error=original_error,startup_ownership_reconciled=True,
            launch_attempted_semantics='Historical original executable launch; reconciliation launched nothing')
        validate_ownership(reconciled,p)
        r=reconciled
    except Exception as exc:
        r.update(status='error',phase='finished',issue=_error(exc),ownership_verified=False,readback_verified=False)
    finally:
        try:engine.close()
        except Exception as exc:r.update(status='error',phase='finished',cleanup_issue=_error(exc),ownership_verified=False,readback_verified=False)
    try:_write_receipt(out,r)
    except Exception as exc:r.update(status='error',phase='finished',receipt_write_issue=_error(exc),ownership_verified=False,readback_verified=False)
    return r


def reconcile_owned_startup(params):
    p=parameters(params)
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        return run_reconciliation(p)
