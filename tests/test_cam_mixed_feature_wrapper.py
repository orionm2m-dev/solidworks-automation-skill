from cam_mixed_test_support import ROOT, SCRIPTS, evidence_file, evidence_json, server_nodes, synthetic_specs, synthetic_context
import ast,os
from pathlib import Path
import pytest
from test_cam_mixed_feature_diagnostic import m
STAGE=SCRIPTS


def test_wrapper_is_bounded_and_read_only():
    tree=ast.parse((ROOT/'mcp-server/server.py').read_text('utf-8-sig'))
    found=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='solidworks_cam_read_existing_mixed_feature')
    text=ast.unparse(found)
    assert "'readOnlyHint': True"in text
    assert 'desktop_guard=True'in text
    assert 'Explicit owned process connection required'in text
    assert '_cam_mixed_feature_diagnostic_sealed_payload'in text


def test_sealed_wrapper_checks_digest_and_implementation(tmp_path):
    import hashlib,json
    tree=ast.parse((ROOT/'mcp-server/server.py').read_text('utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='_cam_mixed_feature_diagnostic_sealed_payload')
    ns={'SCRIPTS_DIR':str(STAGE)};exec(compile(ast.Module(body=[node],type_ignores=[]),'<sealed-wrapper>','exec'),ns)
    payload=dict(action='read_existing_mixed_feature',params=dict(process_id=123,module_sha256=m.previous._file_hash(m.__file__),receipt_path=str(tmp_path/'out.json')))
    path=tmp_path/'request.json';path.write_text(json.dumps(payload));digest=hashlib.sha256(path.read_bytes()).hexdigest()
    check=ns[node.name];assert check(str(path),digest,123)==payload
    with pytest.raises(ValueError):check(str(path),'0'*64,123)
    with pytest.raises(ValueError):check(str(path),digest,124)
    payload['params']['module_sha256']='0'*64;path.write_text(json.dumps(payload));digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):check(str(path),digest,123)
