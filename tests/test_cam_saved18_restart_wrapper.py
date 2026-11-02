from pathlib import Path
from types import SimpleNamespace
import ast,hashlib,json,os,sys
import pytest
from cam_public_test_support import add_runtime
R=add_runtime()
@pytest.fixture
def wrapper(tmp_path):
    file=R/'mcp-server/server.py';name='_cam_saved18_restart_sealed_payload'
    if not file.is_file():raise RuntimeError('Required installed MCP server is missing')
    source=file.read_text(encoding='utf-8-sig')
    if ('def '+name+'(')not in source:raise RuntimeError('Required installed sealed wrapper is missing')
    tree=ast.parse(source);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name==name]
    assert len(nodes)==1
    ns={'SCRIPTS_DIR':str(tmp_path)};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(file),'exec'),ns)
    module=tmp_path/'sw_cam_saved18_restarted_verify.py';module.write_text('fixed implementation')
    request=dict(action='verify_saved_eighteen_after_owned_restart',params=dict(process_id=50,module_sha256=hashlib.sha256(module.read_bytes()).hexdigest(),receipt_path=str(tmp_path/'out.json'),saved_cl_path=str(tmp_path/'export/saved.cl')))
    def call(value=None,raw=None,pid=50,wronghash=False):
        path=tmp_path/'request.json';path.write_bytes(raw if raw is not None else json.dumps(request if value is None else value).encode())
        return ns[name](str(path),'f'*64 if wronghash else hashlib.sha256(path.read_bytes()).hexdigest(),pid)
    return call,request,tmp_path,module

def test_sealed_wrapper_accepts_exact_request(wrapper):
    call,r,_,_=wrapper;assert call()==r
@pytest.mark.parametrize('change',['pid','bool','action','module','alias','relative'])
def test_sealed_wrapper_rejects_drift(wrapper,change):
    call,r,p,module=wrapper
    if change=='pid':r['params']['process_id']=51
    elif change=='bool':r['params']['process_id']=True
    elif change=='action':r['action']='save'
    elif change=='module':module.write_text('changed')
    elif change=='alias':r['params']['receipt_path']=str(p/'request.json')
    elif change=='relative':r['params']['receipt_path']='relative.json'
    with pytest.raises(ValueError):call(r)
@pytest.mark.parametrize('raw',[b'{"action":"x","action":"y","params":{}}',b'{"action":"x","params":{"v":NaN}}'])
def test_strict_json(wrapper,raw):
    with pytest.raises(ValueError):wrapper[0](raw=raw)
def test_wrong_seal(wrapper):
    with pytest.raises(ValueError):wrapper[0](wronghash=True)
