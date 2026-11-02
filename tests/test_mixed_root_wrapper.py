import ast,hashlib,json,os
from pathlib import Path
import pytest

@pytest.fixture
def sealed(tmp_path):
    root=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]));server=root/'mcp-server/server.py';name='_cam_mixed_root_pockets_sealed_payload'
    source=server.read_text(encoding='utf-8-sig')if server.exists()else''
    tree=ast.parse(source);nodes=[x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name==name]
    if not nodes:
        stage=Path(os.environ.get('SW_CAM_MIXED_ROOT_EVIDENCE_ROOT',Path(__file__).resolve().parents[1]));tree=ast.parse((stage/'MCP_SNIPPET.py').read_text(encoding='utf-8-sig'));nodes=[x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name==name]
    assert len(nodes)==1
    namespace={'SCRIPTS_DIR':str(tmp_path)};exec(compile(ast.Module(body=nodes,type_ignores=[]),'sealed-wrapper','exec'),namespace)
    module=tmp_path/'sw_cam_mixed_root_pockets.py';module.write_bytes(b'qualified module')
    payload={'action':'create_two_mixed_root_pockets','params':{'process_id':123,'module_sha256':hashlib.sha256(module.read_bytes()).hexdigest(),'receipt_path':str(tmp_path/'result.json')}}
    return namespace[name],tmp_path,module,payload


def invoke(case,payload=None,raw=None,pid=123,digest=None):
    fn,folder,module,value=case;request=folder/'request.json'
    data=(json.dumps(value if payload is None else payload).encode()if raw is None else raw);request.write_bytes(data)
    return fn(str(request),digest or hashlib.sha256(data).hexdigest(),pid)


def test_exact_sealed_request(sealed):assert invoke(sealed)==sealed[3]

@pytest.mark.parametrize('fault',['digest','pid','boolpid','action','module','duplicate','nan','alias','unknown_top'])
def test_invalid_sealed_request(sealed,fault):
    fn,folder,module,value=sealed
    if fault=='digest':
        with pytest.raises(ValueError):invoke(sealed,digest='0'*64)
        return
    if fault=='pid':
        with pytest.raises(ValueError):invoke(sealed,pid=124)
        return
    if fault=='module':module.write_bytes(b'changed')
    if fault=='boolpid':value['params']['process_id']=True
    if fault=='action':value['action']='other'
    if fault=='alias':value['params']['receipt_path']=str(folder/'request.json')
    if fault=='unknown_top':value['unknown']=1
    raw=b'{"action":1,"action":2}'if fault=='duplicate'else(b'{"params":NaN}'if fault=='nan'else None)
    with pytest.raises(ValueError):invoke(sealed,raw=raw)