"""Offline guards, one-call durability and wrapper routing; no native application calls."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"mcp-server"))
import server
from scripts import sw_cam_unavailable_api_load as core

CLSID='{CCAC6208-0E19-6455-2022-2026CEB541FA}'

class CamError(Exception):
    hresult=core.DISP_E_EXCEPTION
    excepinfo=(0,'SECRET_SOURCE','SECRET_LICENSE','SECRET_HELP',0,core.E_POINTER)

@pytest.fixture
def c(tmp_path,monkeypatch):
    dll=tmp_path/'cam.dll';dll.write_bytes(b'fake registered dll')
    markerroot=tmp_path/'markers';markerroot.mkdir()
    monkeypatch.setattr(core,'local_evidence_root',lambda:markerroot)
    owner=dict(process_id=731,create_time=1000.125,executable='C:/SW/SLDWORKS.exe',alive=True)
    identity=Mock(side_effect=lambda pid:dict(owner));monkeypatch.setattr(core,'_process_identity',identity)
    app=SimpleNamespace(GetVersion=Mock(return_value='2026'),GetServicePack=Mock(return_value='4.1'),
        GetBuildDate=Mock(return_value='2026'),GetIsCAMWorksInDemoMode=Mock(return_value=False))
    getter=Mock(side_effect=[CamError(),app])
    bridge=SimpleNamespace(GetCWApp=getter)
    sw=SimpleNamespace(ActiveDoc=None,GetDocuments=Mock(return_value=None),GetProcessID=Mock(return_value=731),
        GetAddInObject=Mock(return_value=bridge),LoadAddIn=Mock(return_value=0))
    args=dict(expected_no_documents=True,process_id=731,expected_process_create_time=1000.125,
        expected_failure_hresult=core.E_POINTER,expected_addin_sha256=core.file_sha(dll),receipt_path=str(tmp_path/'receipt.json'))
    def run(**changes):return core.initialize_unavailable_api(sw,CLSID,str(dll),**(args|changes))
    return SimpleNamespace(**locals())


def test_one_load_receipts_durable_before_native_call(c):
    def load(path):
        receipt=json.loads(Path(c.args['receipt_path']).read_text())
        assert receipt['native_dispatch_pending'] is True and receipt['load_calls']==1
        assert len(list(c.markerroot.glob('*.json')))==1
        assert path==str(c.dll)
        return 0
    c.sw.LoadAddIn.side_effect=load
    out=c.run()
    assert out['status']=='ok' and out['initialization_verified'] and out['readback_verified']
    assert not out['native_dispatch_pending'] and out['load_calls']==1
    c.sw.LoadAddIn.assert_called_once_with(str(c.dll))
    assert json.loads(Path(c.args['receipt_path']).read_text())==out
    assert 'SECRET' not in json.dumps(out)


def test_once_marker_cannot_be_bypassed_by_new_receipt(c):
    assert c.run()['status']=='ok'
    with pytest.raises(ValueError,match='already claimed'):
        c.run(receipt_path=str(c.tmp_path/'other.json'))
    assert c.sw.LoadAddIn.call_count==1

@pytest.mark.parametrize('change',[
    {'expected_no_documents':False},{'expected_no_documents':1},{'process_id':True},{'process_id':0},
    {'expected_process_create_time':True},{'expected_process_create_time':float('nan')},
    {'expected_failure_hresult':core.DISP_E_EXCEPTION},{'expected_failure_hresult':True},
    {'expected_addin_sha256':'x'},{'receipt_path':'relative.json'},
])
def test_invalid_input_never_loads(c,change):
    with pytest.raises(ValueError):c.run(**change)
    c.sw.LoadAddIn.assert_not_called()

@pytest.mark.parametrize('kind',['hidden_doc','active_doc','enumeration_error','pid','lifetime','dead','exe','dll','bridge_absent','different_error','null_api'])
def test_preflight_mismatch_never_loads(c,kind):
    if kind=='hidden_doc':c.sw.GetDocuments.return_value=[object()]
    if kind=='active_doc':c.sw.ActiveDoc=object()
    if kind=='enumeration_error':c.sw.GetDocuments.side_effect=RuntimeError('unknown')
    if kind=='pid':c.sw.GetProcessID.return_value=732
    if kind=='lifetime':c.owner['create_time']=2000
    if kind=='dead':c.owner['alive']=False
    if kind=='exe':c.owner['executable']='C:/other.exe'
    if kind=='dll':c.dll.write_bytes(b'changed')
    if kind=='bridge_absent':c.sw.GetAddInObject.return_value=None
    if kind=='different_error':c.getter.side_effect=ValueError('SECRET')
    if kind=='null_api':c.getter.side_effect=None;c.getter.return_value=None
    out=c.run()
    assert out['status']=='error' and not out['load_attempted'] and not out['readback_verified']
    c.sw.LoadAddIn.assert_not_called()


def test_already_ready_reports_verified_without_claim_or_load(c):
    c.getter.side_effect=None;c.getter.return_value=c.app
    out=c.run()
    assert out['status']=='ok' and out['already_ready'] and out['readback_verified']
    assert not out['load_attempted'] and not out['initialization_verified']
    c.sw.LoadAddIn.assert_not_called();assert list(c.markerroot.glob('*.json'))==[]
    assert Path(c.args['receipt_path']).is_file()

@pytest.mark.parametrize('failure_at',[1,2,3])
def test_receipt_or_marker_failure_before_load_stops(c,monkeypatch,failure_at):
    real=core._write_receipt;count=0
    def write(*args,**kwargs):
        nonlocal count
        count+=1
        if count==failure_at:raise OSError('disk failure')
        return real(*args,**kwargs)
    monkeypatch.setattr(core,'_write_receipt',write)
    out=c.run();assert out['status']=='error'
    c.sw.LoadAddIn.assert_not_called()

@pytest.mark.parametrize('result',[False,True,1,2,-1,None,'0'])
def test_nonzero_or_wrong_type_return_is_not_success(c,result):
    c.sw.LoadAddIn.return_value=result
    out=c.run();assert out['status']=='error' and not out['initialization_verified']
    assert out['load_calls']==1 and out['load_result']==result


def test_exception_after_dispatch_is_uncertain_no_retry(c):
    c.sw.LoadAddIn.side_effect=CamError()
    out=c.run();assert out['status']=='error' and out['native_dispatch_pending'] and out['load_calls']==1
    c.sw.LoadAddIn.assert_called_once()

@pytest.mark.parametrize('kind',['doc','pid','lifetime','dll','api','metadata'])
def test_post_load_drift_stops_without_retry(c,kind):
    def load(_):
        if kind=='doc':c.sw.GetDocuments.return_value=[object()]
        if kind=='pid':c.sw.GetProcessID.return_value=732
        if kind=='lifetime':c.owner['create_time']=2000
        if kind=='dll':c.dll.write_bytes(b'drift')
        if kind=='api':c.getter.side_effect=CamError()
        if kind=='metadata':c.app.GetVersion.side_effect=CamError()
        return 0
    c.sw.LoadAddIn.side_effect=load
    out=c.run();assert out['status']=='error' and not out['initialization_verified'] and out['load_calls']==1
    c.sw.LoadAddIn.assert_called_once()


def test_post_write_failure_never_reports_verified(c,monkeypatch):
    real=core._write_receipt;count=0
    def write(*args,**kwargs):
        nonlocal count
        count+=1
        if count==4:raise OSError('final receipt failure')
        return real(*args,**kwargs)
    monkeypatch.setattr(core,'_write_receipt',write)
    out=c.run();assert out['status']=='error' and not out['readback_verified'] and not out['may_continue']
    assert out['receipt_write_issue']

@pytest.mark.parametrize('scode',[core.E_POINTER,core.E_POINTER & 0xffffffff])
def test_signed_and_unsigned_excepinfo_code_match_without_text(c,scode):
    e=CamError();e.excepinfo=(0,'SECRET','SECRET',None,0,scode)
    c.getter.side_effect=[e,c.app]
    assert c.run()['status']=='ok'


def test_direct_pointer_hresult(c):
    e=CamError();e.hresult=core.E_POINTER;e.excepinfo=None
    c.getter.side_effect=[e,c.app]
    assert c.run()['status']=='ok'


def schema(c,**changes):
    return server.SolidWorksCamLoadInput(addin_clsid=CLSID,initialize_unavailable_api=True,**(c.args|changes))

@pytest.mark.parametrize('change',[
    {'expected_no_documents':False},{'process_id':None},{'expected_process_create_time':None},
    {'expected_process_create_time':True},{'expected_failure_hresult':None},
    {'expected_failure_hresult':core.DISP_E_EXCEPTION},{'receipt_path':None},{'receipt_path':'relative.json'},
    {'expected_addin_sha256':None},{'expected_addin_sha256':'x'},
])
def test_schema_requires_exact_opt_in_guards(c,change):
    with pytest.raises(ValueError):schema(c,**change)


def test_status_schema_rejects_initialization_option(c):
    with pytest.raises(ValueError):server.SolidWorksCamApplicationInput(addin_clsid=CLSID,initialize_unavailable_api=True,**c.args)


def test_opt_out_rejects_dangling_guards(c):
    with pytest.raises(ValueError):server.SolidWorksCamLoadInput(addin_clsid=CLSID,**c.args)


def test_wrapper_routes_registered_dll_and_preserves_application_guard(c,monkeypatch):
    p=schema(c)
    target=Mock(return_value=(c.sw,{'clsid':CLSID,'addin_path':str(c.dll)}))
    initialize=Mock(return_value={'status':'ok','readback_verified':True})
    readback=Mock(side_effect=lambda p,sw,out:out)
    monkeypatch.setattr(server,'_cam_application_target',target)
    monkeypatch.setattr(server,'_cam_application_readback',readback)
    monkeypatch.setattr(core,'initialize_unavailable_api',initialize)
    monkeypatch.setattr(server,'_run_locked',lambda op,fmt:op())
    assert server.solidworks_cam_load_addin(p)['status']=='ok'
    initialize.assert_called_once_with(c.sw,CLSID,str(c.dll),**c.args)
    target.assert_called_once_with(p);readback.assert_called_once()


def test_only_load_schema_exposes_option():
    assert 'initialize_unavailable_api' in json.dumps(server.mcp._tool_manager._tools['solidworks_cam_load_addin'].parameters)
    assert 'initialize_unavailable_api' not in json.dumps(server.mcp._tool_manager._tools['solidworks_cam_status'].parameters)
