"""One explicit registered CAM LoadAddIn after E_POINTER, in an empty owned session."""
from __future__ import annotations
import hashlib
import json
import math
import re
from pathlib import Path
from scripts.sw_cam import _error, _member, inspect_cam
from scripts.sw_cam_feature_sketch import _call_method
from scripts.sw_executable_launch import _process_identity
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_checkpoint_exports import local_evidence_root

SCOPE = "CAM_UNAVAILABLE_API_LOAD_ONCE_V1"
E_POINTER = -2147467261
DISP_E_EXCEPTION = -2147352567


def require(value, reason):
    if not value:
        raise ValueError(reason)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def once_path(process_id, created, clsid):
    # Deliberately excludes receipt name, DLL spelling/hash and expected error.
    identity = dict(scope=SCOPE, process_id=process_id, create_time=created, clsid=clsid.upper())
    digest = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    return local_evidence_root() / ("cam_unavailable_api_load_" + digest + ".json")


def effective_pointer_error(exc):
    if getattr(exc,"hresult",None) == E_POINTER:
        return True
    info=getattr(exc,"excepinfo",None)
    return (getattr(exc,"hresult",None) == DISP_E_EXCEPTION
        and type(info) in (tuple,list) and len(info)==6 and type(info[5]) is int
        and info[5] in (E_POINTER, E_POINTER & 0xffffffff))


def initialize_unavailable_api(sw, clsid, addin_path, *, expected_no_documents,
        process_id, expected_process_create_time, expected_failure_hresult,
        expected_addin_sha256, receipt_path):
    """Never unload, restart, create/open/save a document, or change a license."""
    require(expected_no_documents is True,"Explicit empty-session scope required")
    require(type(process_id) is int and 0<process_id<2**32,"Exact process_id required")
    require(type(expected_process_create_time) in (int,float)
        and math.isfinite(expected_process_create_time) and expected_process_create_time>0,
        "Exact finite process lifetime required")
    require(type(expected_failure_hresult) is int and expected_failure_hresult==E_POINTER,
        "Only the observed E_POINTER case is qualified for an attempt")
    require(type(clsid) is str and re.fullmatch(r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}",clsid),"Exact registered CLSID required")
    require(type(expected_addin_sha256) is str and re.fullmatch("[0-9a-f]{64}",expected_addin_sha256),"Exact registered DLL hash required")
    dll=Path(addin_path)
    require(dll.is_absolute() and dll.is_file() and not dll.is_symlink()
        and dll.suffix.lower()=='.dll',"Existing registered DLL required")
    out=Path(receipt_path)
    require(out.is_absolute() and out.suffix.lower()=='.json' and out.parent.is_dir()
        and not out.exists() and not out.is_symlink(),"Fresh absolute JSON receipt required")
    marker=once_path(process_id,float(expected_process_create_time),clsid)
    require(out.resolve()!=marker.resolve() and not marker.exists() and not marker.is_symlink(),
        "Attempt already claimed for this process lifetime; inspect, never replay")
    report=dict(scope=SCOPE,status='error',phase='preflight',process_id=process_id,
        expected_process_create_time=expected_process_create_time,addin_clsid=clsid,
        addin_path=str(dll),expected_addin_sha256=expected_addin_sha256,
        expected_failure_hresult=expected_failure_hresult,receipt_path=str(out),once_marker_path=str(marker),
        load_attempted=False,load_calls=0,native_dispatch_pending=False,readback_verified=False,
        initialization_verified=False,may_continue=False,automatic_retry=False,
        unload_attempted=False,process_restart_attempted=False,license_change_attempted=False,
        model_change_requested=False,model_saved=False)
    receipt_created=False
    def guard():
        owner=_process_identity(process_id)
        require(owner.get('alive') is True and owner.get('process_id')==process_id
            and owner.get('create_time')==expected_process_create_time
            and Path(owner.get('executable','')).name.lower()=='sldworks.exe',"Owned process lifetime changed")
        require(_call_method(sw,'GetProcessID')==process_id,"Connected process differs")
        docs=_call_method(sw,'GetDocuments')
        require(docs is None or type(docs) in (list,tuple) and len(docs)==0,"All documents must be closed, including hidden documents")
        require(_member(sw,'ActiveDoc') is None,"Active document present")
        require(file_sha(dll)==expected_addin_sha256,"Registered DLL bytes changed")
        require(_process_identity(process_id)==owner,"Process changed during empty-session guard")
        return owner
    def observe_unavailable():
        bridge=_member(sw,'GetAddInObject',clsid)
        require(bridge is not None,"Existing CAM bridge required for this bounded case")
        try:
            app=_member(bridge,'GetCWApp')
        except Exception as exc:
            require(effective_pointer_error(exc),"Fresh GetCWApp error differs from E_POINTER")
            return _error(exc)
        require(app is not None,"GetCWApp returned no API object without the pinned error")
        return None
    try:
        report['owner_before']=guard()
        report['api_failure_before']=observe_unavailable()
        guard()
        if report['api_failure_before'] is None:
            report['api_after']=inspect_cam(sw,clsid)
            require(guard()==report['owner_before'],"Owner changed during already-ready read")
            require(report['api_after'].get('status')=='ok' and report['api_after'].get('api_available') is True
                and report['api_after'].get('active_document_unchanged') is True
                and report['api_after'].get('document_before') is None
                and report['api_after'].get('document_after') is None,"Existing CAM API readiness not verified")
            report.update(status='ok',phase='finished',already_ready=True,readback_verified=True,may_continue=True)
            _write_receipt(out,report,create=True)
            return report
        # The durable claim survives failures and different output filenames.
        _write_receipt(marker,dict(scope=SCOPE,status='claimed_no_replay',process_id=process_id,
            expected_process_create_time=expected_process_create_time,addin_clsid=clsid,
            receipt_path=str(out)),create=True)
        _write_receipt(out,report,create=True);receipt_created=True
        require(guard()==report['owner_before'],"Owner changed before dispatch")
        report.update(phase='LoadAddIn',load_attempted=True,load_calls=1,native_dispatch_pending=True)
        _write_receipt(out,report)
        returned=_call_method(sw,'LoadAddIn',str(dll))
        report.update(load_result=returned,native_dispatch_pending=False)
        require(guard()==report['owner_before'],"Owner changed after dispatch")
        report['api_after']=inspect_cam(sw,clsid)
        report['owner_after']=guard()
        require(report['owner_after']==report['owner_before'],"Owner changed during API verification")
        require(type(returned) is int and returned==0,"LoadAddIn did not return integer success zero")
        require(report['api_after'].get('status')=='ok' and report['api_after'].get('api_available') is True
            and report['api_after'].get('active_document_unchanged') is True
            and report['api_after'].get('document_before') is None
            and report['api_after'].get('document_after') is None,"CAM API did not recover in the empty session")
        report.update(status='ok',phase='finished',initialization_verified=True,
            readback_verified=True,may_continue=True)
    except Exception as exc:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),
            initialization_verified=False,readback_verified=False,may_continue=False)
    if receipt_created:
        try:
            _write_receipt(out,report)
        except Exception as exc:
            report.update(status='error',phase='finished',receipt_write_issue=_error(exc),
                initialization_verified=False,readback_verified=False,may_continue=False)
    return report
