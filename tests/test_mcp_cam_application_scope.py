"""CAM application-only status/load guards; no CAD access."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp-server'))
import server
from scripts import sw_cam, sw_cam_installation

CLSID='{00000000-0000-0000-0000-000000000001}'
TOOLS=('solidworks_cam_load_addin','solidworks_cam_status')

@pytest.fixture
def case(tmp_path,monkeypatch):
    dll=tmp_path/'cam.dll';dll.write_bytes(b'offline only')
    sw=SimpleNamespace(ActiveDoc=None,GetDocuments=Mock(return_value=None),
        GetProcessID=Mock(return_value=731),RevisionNumber='34.4.0')
    connect=Mock(return_value=(sw,None));discover=Mock(return_value={'errors':[]})
    registration={'clsid':CLSID,'addin_path':str(dll),'registry_key':'SOFTWARE/SOLIDWORKS/SOLIDWORKS 2026/AddIns/'+CLSID}
    select=Mock(return_value=registration)
    load=Mock(return_value={'status':'ok','load_attempted':True,'load_result':0})
    inspect=Mock(return_value={'status':'ok','api_available':True})
    def member(obj,name,*args):
        v=getattr(obj,name);return v(*args) if callable(v) else v
    def locked(op,fmt,**_):
        try:return server._result(op(),fmt)
        except Exception as e:return server._tool_error(e,fmt)
    monkeypatch.setattr(server,'_run_locked',locked)
    monkeypatch.setattr(server,'_selected_process_id',731)
    monkeypatch.setattr(server,'connect_solidworks',connect)
    monkeypatch.setattr(server,'get_com_member',member,raising=False)
    monkeypatch.setattr(sw_cam_installation,'discover_cam_installations',discover)
    monkeypatch.setattr(sw_cam,'select_registration',select)
    monkeypatch.setattr(sw_cam,'load_cam_addin',load)
    monkeypatch.setattr(sw_cam,'inspect_cam',inspect)
    def run(tool='solidworks_cam_load_addin',**changes):
        params=server.SolidWorksCamApplicationInput(**(dict(addin_clsid=CLSID,
            expected_no_documents=True,process_id=731)|changes))
        return json.loads(getattr(server,tool)(params))
    return SimpleNamespace(**locals())

@pytest.mark.parametrize('tool',TOOLS)
@pytest.mark.parametrize('empty',[None,[],()])
def test_empty_scope_verifies_before_after_and_routes_only_registered_app(case,tool,empty):
    case.sw.GetDocuments.return_value=empty
    out=case.run(tool)
    assert out['status']=='ok' and out['empty_document_scope_verified'] and out['may_continue']
    assert out['open_documents_before']==out['open_documents_after']==[]
    assert case.sw.GetDocuments.call_count==2
    case.connect.assert_called_once_with(wait_seconds=1,process_id=731)
    if tool==TOOLS[0]:case.load.assert_called_once_with(case.sw,CLSID,str(case.dll))
    else:case.inspect.assert_called_once_with(case.sw,CLSID)

@pytest.mark.parametrize('changes',[
    {'expected_no_documents':1},{'expected_no_documents':'true'},
    {'process_id':None},{'process_id':True},{'process_id':'731'},
    {'process_id':0},{'expected_document_path':'C:/part.sldprt'},
    {'expected_document_title':'unsaved'},{'expected_no_documents':False}])
def test_explicit_schema_strict_exclusive(case,changes):
    with pytest.raises(ValueError):case.run(**changes)
    case.connect.assert_not_called();case.load.assert_not_called()

@pytest.mark.parametrize('tool',TOOLS)
@pytest.mark.parametrize('problem',['bound','actual_pid','year','documents','active','enumeration_error','unknown_shape','registry'])
def test_failed_precondition_never_reads_or_loads_cam(case,tool,problem,monkeypatch):
    if problem=='bound':monkeypatch.setattr(server,'_selected_process_id',732)
    if problem=='actual_pid':case.sw.GetProcessID.return_value=732
    if problem=='year':case.sw.RevisionNumber='33.4.0'
    if problem=='documents':case.sw.GetDocuments.return_value=[object()]
    if problem=='active':case.sw.ActiveDoc=object()
    if problem=='enumeration_error':case.sw.GetDocuments.side_effect=AttributeError('GetDocuments unavailable')
    if problem=='unknown_shape':case.sw.GetDocuments.return_value=False
    if problem=='registry':case.discover.return_value={'errors':['incomplete']}
    out=case.run(tool)
    assert out['status']=='error'
    case.load.assert_not_called();case.inspect.assert_not_called()

@pytest.mark.parametrize('tool',TOOLS)
@pytest.mark.parametrize('problem',['documents','active','pid','enumeration_error'])
def test_postcondition_failure_keeps_native_result_and_stops(case,tool,problem):
    chosen=case.load if tool==TOOLS[0] else case.inspect
    def effect(*_):
        if problem=='documents':case.sw.GetDocuments.return_value=[object()]
        if problem=='active':case.sw.ActiveDoc=object()
        if problem=='pid':case.sw.GetProcessID.return_value=732
        if problem=='enumeration_error':case.sw.GetDocuments.side_effect=RuntimeError('unreadable')
        return {'status':'ok','load_attempted':tool==TOOLS[0],'native_marker':'returned'}
    chosen.side_effect=effect
    out=case.run(tool)
    assert out['status']=='error' and not out['empty_document_scope_verified'] and not out['may_continue']
    assert out['native_marker']=='returned' and out['reason']=='CAM_APPLICATION_SCOPE_CHANGED_OR_UNREADABLE'
    chosen.assert_called_once()

def test_other_cam_schemas_do_not_accept_empty_scope():
    with pytest.raises(ValueError):server.SolidWorksCamTargetInput(addin_clsid=CLSID,expected_no_documents=True)
    for tool in ('solidworks_cam_inspect_turning','solidworks_cam_set_turn_machine'):
        assert 'expected_no_documents' not in json.dumps(server.mcp._tool_manager._tools[tool].parameters)

def test_loaded_status_unavailable_is_not_continue_permission(case):
    case.inspect.return_value={'status':'unavailable','api_available':False}
    out=case.run('solidworks_cam_status')
    assert out['empty_document_scope_verified'] and not out['may_continue']

def test_explicit_method_dispatch_handles_eager_dynamic_properties(case):
    class Dispatch:
        def __init__(self):self.flags=set();self.ActiveDoc=None;self.RevisionNumber='34.4.0'
        def _FlagAsMethod(self,name):self.flags.add(name)
        def __getattr__(self,name):
            if name in ('GetDocuments','GetProcessID'):
                assert name in self.flags,'Method must be flagged before dynamic getattr'
                return lambda: None if name=='GetDocuments' else 731
            raise AttributeError(name)
    case.connect.return_value=(Dispatch(),None)
    assert case.run()['empty_document_scope_verified']
