"""Sealed MCP wrapper tests without CAD or a running server."""
from pathlib import Path
from types import SimpleNamespace
import ast,hashlib,json,os,sys
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]));sys.path.insert(0,str(ROOT))
STAGE=Path(__file__).resolve().parents[1]
import scripts
if not(ROOT/'scripts/sw_cam_deep_long_tool_gtp_recover.py').is_file():scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_deep_long_tool_gtp_recover as target

@pytest.fixture
def wrapper(tmp_path):
    names={'_cam_zero_native_deep_recovery_sealed_payload','solidworks_cam_recover_zero_native_deep_guides'}
    server=Path(os.environ.get('SW_CAM_WRAPPER_SOURCE',str(ROOT/'mcp-server/server.py')))
    tree=ast.parse(server.read_text(encoding='utf-8'))if server.is_file()else None
    if tree is None or not names<={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}:
        tree=ast.parse((STAGE/'MCP_SNIPPET.py').read_text(encoding='utf-8'))
    rows=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name in names]
    assert len(rows)==2
    for n in rows:n.decorator_list=[];n.returns=None
    for n in rows:
        for a in n.args.args:a.annotation=None
    ns={'SCRIPTS_DIR':str(tmp_path),'_selected_process_id':7,'_run_locked':lambda fn,*a,**kw:fn()}
    exec(compile(ast.Module(body=rows,type_ignores=[]),'wrapper','exec'),ns)
    module=tmp_path/'sw_cam_deep_long_tool_gtp_recover.py';module.write_bytes(b'validated module fixture')
    request={'action':'recover_zero_native_deep_guide_generation','params':{'process_id':7,'module_sha256':hashlib.sha256(module.read_bytes()).hexdigest(),'receipt_path':str(tmp_path/'result.json'),'progress_path':str(tmp_path/'progress.json'),'saved_cl_path':str(tmp_path/'cl/route.cl')}}
    f=tmp_path/'request.json';f.write_text(json.dumps(request),encoding='utf-8')
    params=SimpleNamespace(request_path=str(f),request_sha256=hashlib.sha256(f.read_bytes()).hexdigest(),process_id=7,response_format='json')
    return ns,f,params,request


def test_one_sealed_dispatch(wrapper,monkeypatch):
    ns,f,p,r=wrapper;calls=[];monkeypatch.setattr(target,'dispatch_request',lambda value:calls.append(value)or{'ok':True})
    assert ns['solidworks_cam_recover_zero_native_deep_guides'](p)=={'ok':True}
    assert calls==[r]

@pytest.mark.parametrize('bad',['owner','digest','action','module','alias'])
def test_wrapper_rejects_before_dispatch(wrapper,monkeypatch,bad):
    ns,f,p,r=wrapper;calls=[];monkeypatch.setattr(target,'dispatch_request',lambda value:calls.append(value))
    if bad=='owner':ns['_selected_process_id']=8
    elif bad=='digest':p.request_sha256='0'*64
    elif bad=='action':r['action']='anything_else'
    elif bad=='module':r['params']['module_sha256']='0'*64
    elif bad=='alias':r['params']['saved_cl_path']=str(f)
    if bad in('action','module','alias'):
        f.write_text(json.dumps(r),encoding='utf-8');p.request_sha256=hashlib.sha256(f.read_bytes()).hexdigest()
    with pytest.raises(ValueError):ns['solidworks_cam_recover_zero_native_deep_guides'](p)
    assert calls==[]


def test_dispatch_may_mutate_its_copy_without_changing_sealed_original(wrapper,monkeypatch):
    ns,f,p,r=wrapper;original=f.read_bytes();calls=[]
    def mutate(value):
        calls.append(value)
        value['params']['expected_configuration']='observed configuration'
        value['params']['process_id']=999
        value['params']['nested']={'changed':True}
        return {'ok':True,'native_dispatch_completed':True}
    monkeypatch.setattr(target,'dispatch_request',mutate)
    assert ns['solidworks_cam_recover_zero_native_deep_guides'](p)=={'ok':True,'native_dispatch_completed':True}
    assert len(calls)==1 and calls[0]['params']['process_id']==999
    assert f.read_bytes()==original and r['params']['process_id']==7
    assert 'expected_configuration'not in r['params']
