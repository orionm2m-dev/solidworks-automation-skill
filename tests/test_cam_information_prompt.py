"""Exact informational prompt tests with fake windows only; never operate UI."""
import enum,json,os,re,sys
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import sw_cam_information_prompt as m

TEXT='Synthetic informational warning.'
EXE=r'C:\Program Files\SOLIDWORKS\SLDWORKS.exe'
MAIN='SOLIDWORKS Design 2026 - [SYNTHETIC.SLDPRT]'

@pytest.fixture
def ui(tmp_path):
    windows={}
    for root,pid in ((10,100),(20,200)):
        windows[root]=dict(text=m.TITLE,cls='#32770',pid=pid,parent=0,id=0,visible=True,enabled=True,exists=True)
        windows[root+1]=dict(text=TEXT,cls='Static',pid=pid,parent=root,id=-1,visible=True,enabled=True,exists=True)
        windows[root+2]=dict(text='ОК',cls='Button',pid=pid,parent=root,id=1,visible=True,enabled=True,exists=True)
    windows[1]=dict(text=MAIN,cls='SolidWorksMain',pid=100,parent=0,id=0,visible=True,enabled=True,exists=True)
    state=dict(dismiss=True,post_error=False,identity_count=0,identity_hook=None)
    receipt=tmp_path/'receipt.json';durable=[]
    def enum_windows(fn,arg):
        for h,w in list(windows.items()):
            if w['parent']==0 and w['exists']:fn(h,arg)
    def enum_children(h,fn,arg):
        for ch,w in list(windows.items()):
            if w['parent']==h and w['exists']:fn(ch,arg)
    def post(*args):
        durable.append(json.loads(receipt.read_text(encoding='utf-8')))
        if state['post_error']:raise OSError('synthetic post failure')
        if state['dismiss']:windows[args[0]]['exists']=False
    gui=SimpleNamespace(EnumWindows=enum_windows,EnumChildWindows=enum_children,GetWindowText=lambda h:windows[h]['text'],
        GetClassName=lambda h:windows[h]['cls'],GetDlgCtrlID=lambda h:windows[h]['id'],GetParent=lambda h:windows[h]['parent'],
        IsWindowVisible=lambda h:windows[h]['visible'],IsWindowEnabled=lambda h:windows[h]['enabled'],
        IsWindow=lambda h:windows[h]['exists'],GetDlgItem=lambda h,i:next((k for k,v in windows.items()if v['parent']==h and v['id']==i),0),PostMessage=Mock(side_effect=post))
    identity=dict(process_id=100,create_time=123.5,executable=EXE,alive=True)
    def read_identity(pid):
        state['identity_count']+=1
        if state['identity_hook']:state['identity_hook'](state['identity_count'])
        return dict(identity)
    def run(**changes):
        args=dict(process_id=100,expected_creation_time=123.5,expected_executable=EXE,expected_main_title=MAIN,
            expected_text=TEXT,receipt_path=str(receipt),action='acknowledge',acknowledge_information=True,
            gui=gui,processes=SimpleNamespace(GetWindowThreadProcessId=lambda h:(1,windows[h]['pid'])),read_identity=read_identity,sleep=lambda _:None)
        args.update(changes);return m.handle_information_prompt(**args)
    return SimpleNamespace(windows=windows,state=state,identity=identity,gui=gui,receipt=receipt,durable=durable,run=run)


def test_exact_owned_ok_once_with_durable_pending_and_final_receipt(ui):
    r=ui.run();assert r['status']=='dismissed' and r['dismissal_confirmed'] and not r['action_pending']
    ui.gui.PostMessage.assert_called_once_with(10,0x111,1,12)
    assert ui.durable[0]['status']=='dispatch_pending' and ui.durable[0]['action_pending']
    assert json.loads(ui.receipt.read_text(encoding='utf-8'))==r
    assert ui.windows[20]['exists'] and not r['native_cam_api_used'] and not r['native_operation_success_verified']
    with pytest.raises(ValueError):ui.run()
    ui.gui.PostMessage.assert_called_once()


def test_inspect_does_not_acknowledge(ui):
    r=ui.run(action='inspect',acknowledge_information=False)
    assert r['status']=='inspected' and r['button_invocation_count']==0
    ui.gui.PostMessage.assert_not_called()


@pytest.mark.parametrize('handle,key,value',[(10,'pid',200),(10,'text','Other'),(10,'cls','Other'),(10,'enabled',False),
    (11,'text',TEXT+'changed'),(11,'pid',200),(12,'text','Cancel'),(12,'enabled',False),(12,'visible',False),
    (12,'id',0),(12,'parent',20),(1,'text','SOLIDWORKS - [OTHER.SLDPRT]'),(1,'pid',200)])
def test_wrong_dialog_or_main_never_acknowledged(ui,handle,key,value):
    ui.windows[handle][key]=value;r=ui.run();assert r['status']=='blocked'
    ui.gui.PostMessage.assert_not_called()


@pytest.mark.parametrize('key,value',[('create_time',123.6),('executable',r'C:\other\SLDWORKS.exe'),('alive',False),('process_id',200)])
def test_exact_process_identity_required(ui,key,value):
    ui.identity[key]=value;assert ui.run()['status']=='blocked';ui.gui.PostMessage.assert_not_called()


def test_second_button_or_matching_owned_dialog_refused(ui):
    ui.windows[13]=dict(ui.windows[12],text='Cancel',id=2)
    assert ui.run()['status']=='blocked';ui.gui.PostMessage.assert_not_called()


def test_second_matching_dialog_refused(ui):
    for h in (20,21,22):ui.windows[h]['pid']=100
    assert ui.run()['status']=='blocked';ui.gui.PostMessage.assert_not_called()


def test_changed_after_pending_never_posted(ui):
    def change(n):
        if n==3:ui.windows[11]['text']='Changed after receipt'
    ui.state['identity_hook']=change
    r=ui.run();assert r['status']=='uncertain' and r['action_pending']
    ui.gui.PostMessage.assert_not_called()


@pytest.mark.parametrize('key,value',[('dismiss',False),('post_error',True)])
def test_post_uncertainty_never_retried(ui,key,value):
    ui.state[key]=value;r=ui.run()
    assert r['status']=='uncertain' and r['button_invocation_count']==1 and not r['dismissal_confirmed']
    ui.gui.PostMessage.assert_called_once()


def test_pre_dispatch_receipt_failure_blocks_action(ui,monkeypatch):
    original=m.os.fsync;count=[0]
    def fsync(fd):
        count[0]+=1
        if count[0]>1:raise OSError('synthetic durable write failure')
        return original(fd)
    monkeypatch.setattr(m.os,'fsync',fsync)
    r=ui.run();assert r['status']=='uncertain';ui.gui.PostMessage.assert_not_called()


@pytest.mark.parametrize('bad',[False,1,'true',None])
def test_explicit_strict_ack_required(ui,bad):
    with pytest.raises(ValueError):ui.run(acknowledge_information=bad)
    ui.gui.PostMessage.assert_not_called()


def test_mcp_wrapper_no_cam_lock_no_com_and_exact_binding(monkeypatch,tmp_path):
    from pydantic import BaseModel,ConfigDict,Field
    class Base(BaseModel):model_config=ConfigDict(extra='forbid')
    class Format(enum.Enum):JSON='json'
    class MCP:
        def tool(self,**kwargs):return lambda f:f
    helper=Mock(return_value={'status':'inspected'});runtime=Mock();forbidden=Mock(side_effect=AssertionError('Forbidden lock/COM'))
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_information_prompt',SimpleNamespace(handle_information_prompt=helper))
    monkeypatch.delenv('SOLIDWORKS_MCP_PROCESS_ID',raising=False)
    namespace=dict(BaseInput=Base,Field=Field,Literal=Literal,ResponseFormat=Format,mcp=MCP(),os=os,re=re,
        _runtime_identity=SimpleNamespace(assert_current=runtime),_selected_process_id=100,_result=lambda x,f:x,
        _tool_error=lambda e,f:{'status':'error','message':str(e)},_run_locked=forbidden,_load_automation_modules=forbidden)
    import ast
    tree=ast.parse((ROOT/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    names={'SolidWorksCamInformationPromptInput','solidworks_cam_information_prompt'}
    nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names]
    assert {n.name for n in nodes}==names
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'installed_wrapper','exec'),namespace)
    args=namespace['SolidWorksCamInformationPromptInput'](process_id=100,expected_creation_time=123.5,
        expected_executable=EXE,expected_main_title=MAIN,expected_text=TEXT,receipt_path=str(tmp_path/'r.json'))
    assert namespace['solidworks_cam_information_prompt'](args)['status']=='inspected'
    helper.assert_called_once();forbidden.assert_not_called()
    namespace['_selected_process_id']=200
    assert namespace['solidworks_cam_information_prompt'](args)['status']=='error'
    helper.assert_called_once()
