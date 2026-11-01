import ast,json,hashlib
from pathlib import Path
import pytest
import os
S=Path(os.environ.get('SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT',str(Path(__file__).resolve().parents[1]))).resolve()
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1]))).resolve()
C=Path(os.environ.get('SW_CAM_DEEP_GUIDE_MODULE_ROOT',str(R/'scripts'))).resolve()
W=S/'WRITER_MCP_SNIPPET.py'if 'SW_CAM_DEEP_GUIDE_MODULE_ROOT'in os.environ else R/'mcp-server/server.py'

def reader():
    tree=ast.parse(W.read_text(encoding='utf-8-sig'))
    f=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='_cam_deep_guide_packet_sealed_payload')
    ns={'SCRIPTS_DIR':str(C)};exec(compile(ast.Module(body=[f],type_ignores=[]),'wrapper','exec'),ns)
    return ns[f.name]

def payload(tmp_path):
    return {'action':'apply_deep_guide_group','params':{'process_id':123,'module_sha256':hashlib.sha256((C/'sw_cam_deep_guide_group.py').read_bytes()).hexdigest(),'receipt_path':str(tmp_path/'result.json'),'progress_path':str(tmp_path/'progress.json'),'before_cl_path':str(tmp_path/'before/route.cl'),'generated_cl_path':str(tmp_path/'generated/route.cl'),'saved_cl_path':str(tmp_path/'saved/route.cl')}}

def write(tmp_path,p):
    path=tmp_path/'request.json';path.write_text(json.dumps(p));return path,hashlib.sha256(path.read_bytes()).hexdigest()

def test_accept_exact_request(tmp_path):
    p=payload(tmp_path);path,h=write(tmp_path,p);assert reader()(str(path),h,123)==p

@pytest.mark.parametrize('damage',['pid','bool_pid','action','module','digest','receipt_alias','progress_alias','cl_alias','duplicate','nan'])
def test_reject_changed_or_aliasing_request(tmp_path,damage):
    p=payload(tmp_path)
    if damage=='pid':p['params']['process_id']=124
    elif damage=='bool_pid':p['params']['process_id']=True
    elif damage=='action':p['action']='export_corrected_guides_wip'
    elif damage=='module':p['params']['module_sha256']='0'*64
    elif damage=='receipt_alias':p['params']['receipt_path']=str(tmp_path/'request.json')
    elif damage=='progress_alias':p['params']['progress_path']=str(tmp_path/'request.json')
    elif damage=='nan':p['params']['bad']=float('nan')
    path,h=write(tmp_path,p)
    if damage=='cl_alias':
        p['params']['saved_cl_path']=str(path);path.write_text(json.dumps(p));h=hashlib.sha256(path.read_bytes()).hexdigest()
    if damage=='digest':h='0'*64
    if damage=='duplicate':
        path.write_text('{"action":"apply_deep_guide_group","action":"apply_deep_guide_group","params":{}}');h=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):reader()(str(path),h,123)

def test_wrapper_flags_and_dispatch_scope():
    s=W.read_text(encoding='utf-8-sig');assert '"readOnlyHint":False'in s
    assert 'from scripts.sw_cam_deep_guide_group import dispatch_request'in s
    assert 'desktop_guard=True'in s and 'load_automation=False'in s
