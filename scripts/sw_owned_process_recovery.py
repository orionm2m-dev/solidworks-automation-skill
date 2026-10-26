"""Bounded owned SOLIDWORKS process recovery. No COM, UI, restart or PID search.

Bounded process recovery with explicit ownership and qualification guards.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path
import re

_EPOCH = 116444736000000000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {'process_id','expected_executable_path','expected_creation_filetime',
           'ownership_receipt','process_identity_evidence','recovery_manifest'}


def _path(value):
    if not isinstance(value,str) or not value or not ntpath.isabs(value):
        raise ValueError('An explicit absolute path is required')
    return ntpath.normcase(ntpath.normpath(value))


def _hash_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def _pin(ref, *, json_document=True):
    if not isinstance(ref,dict) or set(ref)!={'path','sha256'}:
        raise ValueError('Evidence must contain only path and sha256')
    _path(ref['path'])
    if not isinstance(ref['sha256'],str) or not _HASH.fullmatch(ref['sha256']):
        raise ValueError('Invalid SHA256')
    path=Path(ref['path'])
    if not path.is_file() or path.is_symlink(): raise ValueError('Evidence is not a regular file')
    if json_document:
        if path.stat().st_size>8*1024*1024: raise ValueError('Evidence JSON exceeds 8 MiB')
        data=path.read_bytes()
        actual=hashlib.sha256(data).hexdigest()
    else: actual=_hash_file(path)
    if actual!=ref['sha256']: raise ValueError('Pinned file SHA256 differs: '+str(path))
    if json_document:
        value=json.loads(data.decode('utf-8-sig'))
        if not isinstance(value,dict): raise ValueError('Evidence must be a JSON object')
        return value
    return actual


def _filetime_from_iso(value):
    match=re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.(\d{7})(Z|[+-]\d\d:\d\d)',str(value))
    if not match: raise ValueError('Identity evidence needs exact seven-digit creation time')
    basic=datetime.fromisoformat(match[1]+match[3].replace('Z','+00:00'))
    seconds=int(basic.astimezone(timezone.utc).timestamp())
    return _EPOCH+seconds*10_000_000+int(match[2])


def _spec(spec):
    if not isinstance(spec,dict) or set(spec)!=_FIELDS: raise ValueError('Exact recovery spec fields required')
    spec=json.loads(json.dumps(spec,allow_nan=False))
    if type(spec['process_id']) is not int or not 0<spec['process_id']<2**32: raise ValueError('Invalid PID')
    if type(spec['expected_creation_filetime']) is not int or not _EPOCH<spec['expected_creation_filetime']<2**63:
        raise ValueError('Invalid exact creation FILETIME')
    if ntpath.basename(_path(spec['expected_executable_path']))!='sldworks.exe':
        raise ValueError('Only an explicit SLDWORKS.exe is allowed')
    return spec


def _evidence(spec):
    pid=spec['process_id']; exe=_path(spec['expected_executable_path']); ticks=spec['expected_creation_filetime']
    owned=_pin(spec['ownership_receipt']); observed=_pin(spec['process_identity_evidence']); manifest=_pin(spec['recovery_manifest'])
    if not (owned.get('status')=='ok' and owned.get('phase')=='connected'
            and owned.get('launch_mode')=='executable' and owned.get('launch_attempted') is True
            and owned.get('new_process_verified') is True and owned.get('process_id')==pid):
        raise ValueError('Successful explicitly owned startup is not proven')
    before=owned.get('known_process_ids_before')
    if not isinstance(before,list) or pid in before: raise ValueError('PID was not proven new at owned startup')
    identity=owned.get('process_identity',{})
    if identity.get('process_id')!=pid or _path(identity.get('executable'))!=exe or _path(owned.get('executable'))!=exe:
        raise ValueError('Startup process identity differs')
    created=identity.get('create_time'); intent=owned.get('launch_intent_time')
    if type(created) not in (int,float) or type(intent) not in (int,float) or not math.isfinite(created) or not math.isfinite(intent):
        raise ValueError('Startup time evidence missing')
    exact_seconds=Decimal(ticks-_EPOCH)/Decimal(10_000_000)
    # Existing startup helper records milliseconds. The independent OS record below pins all 100 ns.
    if abs(Decimal(str(created))-exact_seconds)>=Decimal('0.001') or not 0<=created-intent<=120:
        raise ValueError('Startup creation time does not match exact OS evidence')
    os_identity=observed.get('process',{})
    if os_identity.get('Id')!=pid or _path(os_identity.get('Path'))!=exe or _filetime_from_iso(os_identity.get('StartTime'))!=ticks:
        raise ValueError('Exact OS identity evidence differs')
    if manifest.get('process_id')!=pid or manifest.get('complete_known_document_inventory') is not True or manifest.get('no_other_unsaved_work_known') is not True:
        raise ValueError('Known document/discard inventory is incomplete')
    documents=manifest.get('documents'); items=manifest.get('known_unsaved_items')
    if not isinstance(documents,list) or not 1<=len(documents)<=64 or not isinstance(items,list) or not 1<=len(items)<=256:
        raise ValueError('Bounded checkpoint/discard lists required')
    paths=set(); evidence_pins=[]
    for doc in documents:
        if not isinstance(doc,dict) or set(doc)!={'path','sha256','saved_evidence'}: raise ValueError('Invalid checkpoint schema')
        norm=_path(doc['path'])
        if norm in paths: raise ValueError('Duplicate checkpoint document')
        paths.add(norm); _pin({'path':doc['path'],'sha256':doc['sha256']},json_document=False)
        saved=_pin(doc['saved_evidence']); after=saved.get('after',{})
        if not (saved.get('native_save_call_returned') is True and saved.get('save_readback_verified') is True
                and after.get('document',{}).get('needs_save') is False
                and _path(after.get('document',{}).get('path'))==norm
                and after.get('saved_file_sha256')==doc['sha256']):
            raise ValueError('Saved checkpoint not proven by native save receipt')
        evidence_pins.append(doc['saved_evidence'])
    ids=[]
    for item in items:
        if not isinstance(item,dict) or set(item)!={'id','document_path','description','evidence'}: raise ValueError('Invalid discard item')
        if not isinstance(item['id'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',item['id']): raise ValueError('Invalid discard ID')
        if item['id'] in ids or _path(item['document_path']) not in paths: raise ValueError('Duplicate/uncheckpointed discard item')
        if not isinstance(item['description'],str) or not 1<=len(item['description'])<=4000: raise ValueError('Discard description required')
        if not isinstance(item['evidence'],list) or not 1<=len(item['evidence'])<=16: raise ValueError('Discard evidence required')
        for ref in item['evidence']: _pin(ref); evidence_pins.append(ref)
        ids.append(item['id'])
    return {'checkpoint_documents':documents,'known_unsaved_items':items,'discard_ids':sorted(ids),
            'scope':'Supplied complete known inventory; no COM/live document inspection',
            'pinned_supporting_evidence':evidence_pins}


class Win32ProcessAPI:
    """Same-handle public Win32 identity and termination; no enumeration or COM."""
    def __init__(self):
        if os.name!='nt': raise OSError('Win32 process recovery requires Windows')
        self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        specs={
            'OpenProcess':([wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE),
            'CloseHandle':([wintypes.HANDLE],wintypes.BOOL),
            'GetProcessId':([wintypes.HANDLE],wintypes.DWORD),
            'QueryFullProcessImageNameW':([wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
            'GetProcessTimes':([wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4,wintypes.BOOL),
            'WaitForSingleObject':([wintypes.HANDLE,wintypes.DWORD],wintypes.DWORD),
            'TerminateProcess':([wintypes.HANDLE,wintypes.UINT],wintypes.BOOL),
            'GetExitCodeProcess':([wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
        }
        for name,(args,ret) in specs.items():
            fn=getattr(self.k,name); fn.argtypes=args; fn.restype=ret
    def open(self,pid,*,terminate=False):
        handle=self.k.OpenProcess(0x1000|0x100000|(1 if terminate else 0),False,pid)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        return handle
    def identity(self,handle):
        pid=self.k.GetProcessId(handle)
        if not pid: raise ctypes.WinError(ctypes.get_last_error())
        buf=ctypes.create_unicode_buffer(32768); size=wintypes.DWORD(len(buf))
        if not self.k.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)): raise ctypes.WinError(ctypes.get_last_error())
        if not 0<size.value<len(buf): raise ValueError('Invalid executable image length')
        times=[wintypes.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(handle,*(ctypes.byref(x) for x in times)): raise ctypes.WinError(ctypes.get_last_error())
        ticks=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
        wait=self.k.WaitForSingleObject(handle,0)
        if wait not in (0,258): raise OSError('Process wait state unavailable')
        return {'process_id':int(pid),'executable':buf.value,'creation_filetime':ticks,'alive':wait==258}
    def terminate(self,handle):
        if not self.k.TerminateProcess(handle,1): raise ctypes.WinError(ctypes.get_last_error())
    def wait(self,handle,milliseconds):
        value=self.k.WaitForSingleObject(handle,milliseconds)
        if value not in (0,258): raise OSError('Termination wait failed')
        return value==0
    def close(self,handle):
        if not self.k.CloseHandle(handle): raise ctypes.WinError(ctypes.get_last_error())


def _match_identity(spec,identity):
    if not (identity.get('process_id')==spec['process_id']
            and _path(identity.get('executable'))==_path(spec['expected_executable_path'])
            and identity.get('creation_filetime')==spec['expected_creation_filetime']
            and identity.get('alive') is True):
        raise ValueError('Exact live owned process identity/alive guard failed')


def _digest(spec,evidence,identity):
    return hashlib.sha256(json.dumps({'spec':spec,'evidence':evidence,'identity':identity},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _write(path,report,*,initial=False):
    target=path if initial else path.with_name(path.name+'.tmp')
    with target.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    if not initial: os.replace(target,path)


def _real_lock(pid):
    from scripts.sw_operation_guard import solidworks_operation_lock
    return solidworks_operation_lock(timeout_seconds=1,process_id=pid)


def recover_owned_process(*,action,spec,expected_state_sha256=None,
        acknowledge_terminate_owned_process=False,acknowledged_discard_ids=None,
        receipt_path=None,wait_milliseconds=5000,_api=None,_lock_factory=None):
    """inspect/prepare/apply. All real process effects are confined to explicit apply.

    `_api` / `_lock_factory` are test injection hooks, not MCP schema fields.
    inspect/prepare never create a receipt or acquire termination rights.
    """
    report={'status':'blocked','action':action,'termination_attempted':False,'termination_returned':False,
            'process_exit_verified':False,'saved_files_preserved':None,'termination_intent_recorded':False,
            'restart_attempted':False,'COM_calls':0,'UI_calls':0,
            'may_continue':False,'phase':'validation'}
    api=None; handle=None; receipt=None; receipt_created=False
    try:
        if action not in ('inspect','prepare','apply'): raise ValueError('Unsupported action')
        spec=_spec(spec)
        report['request_spec']=spec
        if type(wait_milliseconds) is not int or not 0<=wait_milliseconds<=10000: raise ValueError('Wait must be 0..10000 ms')
        evidence=_evidence(spec)
        if action=='apply':
            if acknowledge_terminate_owned_process is not True: raise ValueError('Explicit termination acknowledgement required')
            if not isinstance(acknowledged_discard_ids,list) or sorted(acknowledged_discard_ids)!=evidence['discard_ids']:
                raise ValueError('Acknowledged discard IDs must exactly equal all evidenced items')
            if not isinstance(expected_state_sha256,str) or not _HASH.fullmatch(expected_state_sha256): raise ValueError('Prepared state SHA required')
            _path(receipt_path); receipt=Path(receipt_path)
            if receipt.suffix.lower()!='.json' or not receipt.parent.is_dir() or receipt.exists() or receipt.with_name(receipt.name+'.tmp').exists():
                raise ValueError('A new JSON receipt with existing parent is required')
        elif receipt_path is not None: raise ValueError('Read-only action must not write a receipt')
        api=_api if _api is not None else Win32ProcessAPI()
        lock=(_lock_factory or _real_lock)(spec['process_id'])
        with lock:
            handle=api.open(spec['process_id'],terminate=action=='apply')
            identity=api.identity(handle); _match_identity(spec,identity)
            evidence=_evidence(spec)
            state=_digest(spec,evidence,identity)
            report.update(process_identity=identity,state_sha256=state,evidence=evidence,phase='prepared',status='ok')
            if action!='apply':
                report['apply_eligible']=True
            else:
                if state!=expected_state_sha256: raise ValueError('Prepared state changed')
                report.update(phase='termination_intent',status='pending',acknowledged_discard_ids=list(acknowledged_discard_ids))
                _write(receipt,report,initial=True); receipt_created=True
                # Recheck both exact handle identity and every file immediately before the one destructive API.
                current=api.identity(handle); _match_identity(spec,current)
                current_evidence=_evidence(spec)
                if _digest(spec,current_evidence,current)!=state: raise ValueError('State changed before termination')
                report.update(phase='before_terminate',termination_intent_recorded=True,
                              durable_intent_meaning='Intent only; API entry/outcome unknown until final receipt')
                _write(receipt,report)
                report['termination_attempted']=True
                api.terminate(handle)
                report['termination_returned']=True
                report['process_exit_verified']=api.wait(handle,wait_milliseconds)
                if report['process_exit_verified']:
                    report['phase']='post_exit_checkpoint_verification'
                    _evidence(spec)
                    report['saved_files_preserved']=True
                report.update(phase='completed' if report['process_exit_verified'] else 'exit_pending',
                              status='ok' if report['process_exit_verified'] else 'review_required')
    except Exception as error:
        report.update(status='review_required' if report['termination_attempted'] else 'blocked',
                      error={'type':type(error).__name__,'message':str(error)})
    finally:
        if handle is not None:
            try: api.close(handle)
            except Exception as error:
                report['handle_cleanup_error']={'type':type(error).__name__,'message':str(error)}
                report['status']='review_required'
        if receipt_created:
            try: _write(receipt,report)
            except Exception as error:
                report['receipt_finalize_error']={'type':type(error).__name__,'message':str(error)}
                report['status']='review_required'
    return report
