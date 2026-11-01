"""Explicit load-only operation for the already registered, pinned reader host."""
from __future__ import annotations
import json,time
from datetime import datetime
from pathlib import Path
from scripts.sw_cam_inprocess_reader import (HOST_CLSID,HOST_LIBID,READER_IID,require,validate_params,pins_for,check_files,check_owner,validate_document,key,digest,_member,_error,_write_receipt,solidworks_operation_lock)


def parameters(params):
    require(type(params) is dict and params.get('acknowledge_host_load') is True,'Explicit host load acknowledgement required')
    p=validate_params({k:v for k,v in params.items() if k!='acknowledge_host_load'})
    require(not p.get('nc_operation_ids') and p['reference_receipt_path'] is None,'Load-only request must not include CAM reads or reference comparison')
    return p


def utc_epoch(value):
    """Read .NET round-trip timestamps; conservatively truncate 100 ns to microseconds."""
    import re
    require(type(value) is str and len(value)<=64,'Diagnostic UTC timestamp required')
    match=re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,7}))?(Z|[+-][0-9]{2}:[0-9]{2})',value)
    require(match is not None,'Strict timezone-aware .NET timestamp required')
    date,fraction,offset=match.groups()
    if offset=='Z':offset='+00:00'
    else:
        hours,minutes=int(offset[1:3]),int(offset[4:6])
        require(minutes<60 and (hours<14 or (hours==14 and minutes==0)),'Invalid .NET timezone offset')
    normalized=date+('.'+fraction[:6].ljust(6,'0') if fraction else '')+offset
    stamp=datetime.fromisoformat(normalized)
    return stamp.timestamp()


def verify_diagnostics(before,after,p,started):
    require(type(after) is dict and type(after.get('data')) is dict,'Connected diagnostic required')
    d=after['data'];require(d.get('status')=='connected' and type(d.get('hostProcessId')) is int and d['hostProcessId']==p['process_id'] and str(d.get('hostProcessName','')).casefold()=='sldworks','Diagnostic owned host mismatch')
    require(str(d.get('addinGuid','')).strip('{}').casefold()==HOST_CLSID.strip('{}').casefold(),'Diagnostic add-in mismatch')
    require(all(d.get(n) is True for n in ('callbackRegistered','commandGroupReady','taskPaneReady','propertyManagerPageReady')) and d.get('errors')==[],'Host connection incomplete')
    require(utc_epoch(d.get('connectedAtUtc'))>=started-1 and utc_epoch(d.get('lastUpdatedUtc'))>=started-1,'Stale connection diagnostic')
    require(after.get('sha256') and (before is None or after['sha256']!=before.get('sha256')),'Connection diagnostic was not refreshed')


class LoaderBackend:
    def __init__(self,p):self.p=p;self.sw=None
    def owner(self):
        from scripts.sw_executable_launch import _process_identity
        return _process_identity(self.p['process_id'])
    def application(self):
        if self.sw is None:
            from scripts.sw_connect import connect_solidworks
            self.sw,_=connect_solidworks(process_id=self.p['process_id'],launch_new_instance=False,wait_seconds=1)
        require(_member(self.sw,'GetProcessID')==self.p['process_id'],'Bound SW PID differs');return self.sw
    def document(self):
        doc=_member(self.application(),'ActiveDoc');require(doc is not None,'Active document required')
        manager=_member(doc,'ConfigurationManager');config=_member(manager,'ActiveConfiguration')
        return dict(path=_member(doc,'GetPathName'),title=_member(doc,'GetTitle'),type=_member(doc,'GetType'),needs_save=bool(_member(doc,'GetSaveFlag')),configuration=_member(config,'Name'))
    def diagnostics(self):
        from scripts.sw_addin_host import _read_diagnostics
        path,data,error=_read_diagnostics();require(error is None,'Host diagnostic cannot be read')
        return None if data is None else dict(path=str(path),data=data,sha256=digest(path))
    def load_once(self):return _member(self.application(),'LoadAddIn',self.p['host_dll_path'])
    def verify_reader_interface(self):
        from ctypes import POINTER
        from comtypes import BSTR,typeinfo
        from comtypes.client import GetModule
        from scripts.sw_cam_comtypes import _marshal_pywin32_unknown
        from scripts.sw_cam_pocket_rough_apply import require_abi
        library=typeinfo.LoadTypeLibEx(self.p['host_tlb_path'],typeinfo.REGKIND_NONE);attr=library.GetLibAttr()
        require(str(attr.guid).upper()==HOST_LIBID and (attr.wMajorVerNum,attr.wMinorVerNum)==(1,0),'Exact host TLB required')
        module=GetModule(library);interface=module.ICamBatchReader;require(str(interface._iid_).upper()==READER_IID,'Reader IID mismatch')
        members=[x for x in interface._methods_ if x.name=='ReadTurnSnapshot'];require(len(members)==1,'Reader method missing');require_abi(members[0],1,(BSTR,POINTER(BSTR)),(1,10))
        raw=_member(self.application(),'GetAddInObject',HOST_CLSID);require(raw is not None,'Loaded host object absent')
        pointer=_marshal_pywin32_unknown(raw).QueryInterface(interface);require(bool(pointer),'Reader QI failed')
        return {'interface_iid':READER_IID,'qualified_interface':True,'cam_reader_called':False}


def run_load(params,*,backend=None):
    p=parameters(params);pins=pins_for(p);check_files(pins);out=Path(p['receipt_path'])
    require(out.suffix.casefold()=='.json' and out.parent.is_dir() and not out.exists() and not out.is_symlink() and key(out) not in {key(x['path']) for x in pins},'Fresh nonaliased load receipt required')
    engine=backend or LoaderBackend(p)
    r=dict(scope='TURN_READER_HOST_LOAD_V1',status='prepared',phase='prepared',request=params,read_only=False,mutation_attempted=False,host_load_attempted=False,load_calls=0,model_change_requested=False,document_unchanged_verified=False,model_saved=False,GTP_attempted=False,cam_reader_called=False,readback_verified=False,loaded_mvid_verified=False,source_sha256=p['expected_source_sha256'],pins=pins,client_module_sha256=digest(__file__))
    _write_receipt(out,r,create=True);started=time.time()
    try:
        owner=engine.owner();check_owner(owner,p);r['owner_before']=owner
        before=engine.document();validate_document(before,p);r['document_before']=before
        diagnostic=engine.diagnostics();r['diagnostics_before']=diagnostic
        require(not (diagnostic and diagnostic['data'].get('status')=='connected' and diagnostic['data'].get('hostProcessId')==p['process_id']),'Host already connected in owned process; do not replay load')
        check_files(pins);r.update(phase='load',host_load_attempted=True,load_calls=1,mutation_attempted=True,native_dispatch_pending=True);_write_receipt(out,r)
        load_start=time.time();result=engine.load_once();r.update(load_result=result,native_dispatch_pending=False)
        after_owner=engine.owner();check_owner(after_owner,p);require(after_owner==owner,'Owner lifetime changed');r['owner_after']=after_owner
        after=engine.document();validate_document(after,p);r['document_after']=after;require(before==after,'Document changed during host load');check_files(pins)
        after_diagnostic=engine.diagnostics();r['diagnostics_after']=after_diagnostic
        require(type(result) is int and result==0,'LoadAddIn did not return zero success code')
        verify_diagnostics(diagnostic,after_diagnostic,p,load_start)
        r['reader_interface']=engine.verify_reader_interface()
        require(r['reader_interface'].get('qualified_interface') is True and r['reader_interface'].get('cam_reader_called') is False,'Reader interface proof missing')
        check_files(pins);r.update(status='observed',phase='finished',readback_verified=True,document_unchanged_verified=True)
    except Exception as exc:r.update(status='error',phase='finished',readback_verified=False,issue=_error(exc))
    r['elapsed_seconds']=time.time()-started;_write_receipt(out,r);return r


def load_reader_host(params):
    p=parameters(params)
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):return run_load(params)
