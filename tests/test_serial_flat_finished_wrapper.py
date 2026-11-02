import ast,hashlib,json,os
from pathlib import Path
from cam_public_test_support import runtime_root
import pytest

@pytest.fixture
def wrapper(tmp_path):
    root=runtime_root();name='_cam_serial_flat_finished_sealed_payload'
    source=root/'mcp-server/server.py';text=source.read_text('utf-8-sig')if source.exists()else'';tree=ast.parse(text)
    found=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name==name]
    assert len(found)==1
    scope={'SCRIPTS_DIR':str(tmp_path)};exec(compile(ast.Module(body=found,type_ignores=[]),'<wrapper>','exec'),scope)
    creator=tmp_path/'sw_cam_serial_flat_tool.py';creator.write_bytes(b'creator')
    provider=tmp_path/'sw_cam_serial_flat_finished_context.py';provider.write_bytes(b'provider')
    value=dict(action='create_serial_flat_tool_after_mixed_pockets',params=dict(process_id=123,module_sha256=hashlib.sha256(creator.read_bytes()).hexdigest(),receipt_path=str(tmp_path/'result.json')),
        authority=dict(creation_receipt_path=str(tmp_path/'authority.json'),creation_receipt_sha256='a'*64,provider_sha256=hashlib.sha256(provider.read_bytes()).hexdigest()))
    def invoke(payload=value,pid=123):
        path=tmp_path/'sealed.json';path.write_text(json.dumps(payload));return scope[name](str(path),hashlib.sha256(path.read_bytes()).hexdigest(),pid)
    return invoke,value,creator,provider


def test_exact_provider_and_creator_sealed(wrapper):
    invoke,value,*_=wrapper;assert invoke()==value

@pytest.mark.parametrize('fault',['provider','creator','authority','action','pid','boolpid','alias'])
def test_bad_authority_or_implementation_rejected(wrapper,fault):
    invoke,value,creator,provider=wrapper
    if fault=='provider':provider.write_bytes(b'changed')
    if fault=='creator':creator.write_bytes(b'changed')
    if fault=='authority':value['authority']['module']='untrusted.py'
    if fault=='action':value['action']='other'
    if fault=='pid':
        with pytest.raises(ValueError):invoke(pid=124)
        return
    if fault=='boolpid':value['params']['process_id']=True
    if fault=='alias':value['params']['receipt_path']=str(creator.parent/'sealed.json')
    with pytest.raises(ValueError):invoke()
