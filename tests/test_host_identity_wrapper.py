import ast
import hashlib
import json
import os
from pathlib import Path
from cam_public_test_support import runtime_root
from types import SimpleNamespace
import sys
import pytest

HELPER="_cam_host_identity_read_sealed_payload"
TOOL="solidworks_cam_read_existing_reader_host_identity"

@pytest.fixture
def env(tmp_path):
    root=runtime_root()
    server=root/"mcp-server/server.py"
    tree=ast.parse(server.read_text("utf-8-sig") if server.exists() else "")
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in (HELPER,TOOL)]
    assert len(nodes)==2
    for n in nodes:n.decorator_list=[]
    namespace=dict(SCRIPTS_DIR=str(tmp_path),SolidWorksCamHostIdentityReadInput=object,
        _selected_process_id=123,_run_locked=lambda fn,*a,**kw:fn())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),"<identity-wrapper>","exec"),namespace)
    module=tmp_path/"sw_cam_host_identity_read.py";module.write_bytes(b"identity")
    value=dict(action="read_existing_host_identity",params=dict(process_id=123,
        module_sha256=hashlib.sha256(module.read_bytes()).hexdigest(),receipt_path=str(tmp_path/"result.json")))
    path=tmp_path/"sealed.json"
    def seal(raw=None):
        path.write_bytes(raw if raw is not None else json.dumps(value).encode())
        return SimpleNamespace(process_id=123,request_path=str(path),request_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),response_format="json")
    return namespace,module,value,path,seal


def test_exact_readonly_request(env):
    n,m,v,path,seal=env;p=seal()
    assert n[HELPER](p.request_path,p.request_sha256,123)==v

@pytest.mark.parametrize("fault",["module","pid","action","alias","extra","duplicate"])
def test_bad_request_rejected(env,fault):
    n,m,v,path,seal=env
    if fault=="module":m.write_bytes(b"changed")
    if fault=="pid":v["params"]["process_id"]=True
    if fault=="action":v["action"]="load_host"
    if fault=="alias":v["params"]["receipt_path"]=str(path)
    if fault=="extra":v["invoke"]="LoadAddIn"
    p=seal(b'{"action":"a","action":"b","params":{}}'if fault=="duplicate"else None)
    with pytest.raises(ValueError):n[HELPER](p.request_path,p.request_sha256,123)


def test_dispatch_copy_and_seal_recheck(env,monkeypatch):
    n,m,v,path,seal=env;p=seal();before=path.read_bytes()
    def call(payload):payload["params"]["receipt_path"]="mutated copy";return "observed"
    monkeypatch.setitem(sys.modules,"scripts.sw_cam_host_identity_read",SimpleNamespace(dispatch_request=call))
    assert n[TOOL](p)=="observed" and path.read_bytes()==before
