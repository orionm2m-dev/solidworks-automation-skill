"""The current public wrapper must reject a stale historical producer request."""
from pathlib import Path
import ast, hashlib, json
import pytest

def test_historical_producer_request_cannot_dispatch(tmp_path):
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'mcp-server/server.py').read_text(encoding='utf-8'))
    helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_cam_deep_tool_replacement_current_sealed_payload')
    ns={'SCRIPTS_DIR':str(tmp_path)}
    exec(compile(ast.Module(body=[helper],type_ignores=[]),'current_wrapper','exec'),ns)
    old=b'historical producer';current=b'current corrected producer'
    (tmp_path/'sw_cam_deep_long_tool_replace.py').write_bytes(old)
    (tmp_path/'sw_cam_deep_long_tool_replace_current.py').write_bytes(current)
    payload={'action':'replace_existing_deep_guide_tool','params':{'process_id':7,'module_sha256':hashlib.sha256(old).hexdigest(),'receipt_path':str(tmp_path/'receipt.json'),'progress_path':str(tmp_path/'progress.json'),'saved_cl_path':str(tmp_path/'route.cl')}}
    request=tmp_path/'sealed.json';request.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(ValueError,match='Installed replacement module digest differs'):
        ns[helper.name](str(request),hashlib.sha256(request.read_bytes()).hexdigest(),7)
