from pathlib import Path
from copy import deepcopy
from types import ModuleType
import ast,hashlib,importlib.util,json,os,sys
import pytest
from cam_optional_test_evidence import evidence_root, required_evidence
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).parents[1]));sys.path.insert(0,str(R))
P=R/'scripts/sw_cam_deep_long_cut_reopen.py'
spec=importlib.util.spec_from_file_location('saved_reopen_under_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
@pytest.fixture(scope='session')
def actual():
    root=evidence_root('SW_CAM_LONG_CUT_REOPEN_EVIDENCE_ROOT')
    r=json.loads(required_evidence(root,'deep_long_tool_completed_save_20261102/ACTUAL_COMPLETED_DEEP_SAVED_NATIVE.json').read_text(encoding='utf-8-sig'))
    c=r['replacement_checkpoint_context']
    loaded=dict(ownership=deepcopy(r['ownership']),guide_parameters=dict(configuration=deepcopy(c['configuration']),targets=[dict(operation_native_id=i)for i in(322,324,326,328)]),replacement_tool_dimensions=deepcopy(c['tool_dimensions']),tool_creation_context=dict(large='unneeded'))
    p=dict(process_id=r['ownership']['process_id'],expected_document_path=r['source_path'],expected_source_sha256=r['saved_source_sha256'])
    return loaded,r,p

def test_exact_mixed_tools_feed_and_compact_carrier(actual):
    loaded,r,p=deepcopy(actual);before=deepcopy((loaded,r,p));v=m.project_saved(loaded,r,p)
    assert(v['guide_parameters']['expected_parameters']==r['saved'])
    assert[x['tool']['generic']['native_id']for x in v['guide_parameters']['expected_parameters']['parameters']]==[273]*4+[338]*4
    assert[x['nc']['feeds_compensation']['XYFeed']for x in v['guide_parameters']['expected_parameters']['parameters']]==[500.]*4+[1000.]*4
    assert'tool_creation_context'not in v and set(v['generated'])=={'saved_cl'}
    assert(loaded,r,p)==before
@pytest.mark.parametrize('mutation',[
 lambda l,r,p:p.__setitem__('expected_source_sha256','0'*64),
 lambda l,r,p:p.__setitem__('process_id',1),
 lambda l,r,p:l['ownership'].__setitem__('create_time',0),
 lambda l,r,p:p.__setitem__('expected_document_path','C:/other.sldprt'),
 lambda l,r,p:r['replacement_checkpoint_context']['document'].__setitem__('needs_save',True),
 lambda l,r,p:r['replacement_checkpoint_context']['document'].__setitem__('type',2),
 lambda l,r,p:r['replacement_checkpoint_context'].__setitem__('configuration',{}),
 lambda l,r,p:r['replacement_checkpoint_context'].__setitem__('operation_order',[]),
 lambda l,r,p:r['replacement_checkpoint_context'].__setitem__('generated_ids',[]),
 lambda l,r,p:r['replacement_checkpoint_context']['saved_snapshot']['parameters'].reverse(),
 lambda l,r,p:l['replacement_tool_dimensions']['generic'].__setitem__('native_id',273),
])
def test_projection_rejects_wrong_saved_boundary(actual,mutation):
    l,r,p=deepcopy(actual);mutation(l,r,p)
    with pytest.raises(ValueError):m.project_saved(l,r,p)

def test_native_engine_and_actions_are_exact_reuse():
    assert m.NativeBackend is m.existing.NativeBackend
    tree=ast.parse(P.read_text())
    assert not any(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr in{'save','generate','assign','set_field','set_nc'}for n in ast.walk(tree))

def test_real_constructors_have_no_callable_shadow(actual):
    l,r,p=deepcopy(actual);l=m.project_saved(l,r,p)
    l.update(pins=[],checkpoint_pins=[],bootstrap_export_pins=[],generated_pin=dict(path='metadata',sha256='0'*64))
    b=m.NativeBackend(l,p,object(),'clsid','typelib',{},lambda:None)
    assert b.parameter_reader is None
    for name in('start','capture_parameters','capture_binding','check_clean','close_target','verify_closed','disconnect_closed','open_target','finish','close'):assert callable(getattr(b,name))
    reader=m.existing.ParameterBackend(l,p,object(),'clsid','typelib',{},lambda:None)
    assert isinstance(reader.capture,ModuleType)
    for name in('capture_snapshot','capture_parameters','capture_binding','start','boundary','finish','close'):assert callable(getattr(reader,name))

def test_new_marker_scope_keeps_old_journal_shape():
    report=dict(scope=m.SCOPE,source_path='C:/part.sldprt',source_sha256='a'*64,deep_checkpoint_pin=dict(path='receipt',sha256='b'*64),phase='prepared',status='prepared',actions={})
    j=m.Journal(report,Path('C:/receipt.json'),Path('C:/marker.json'))
    state=j._marker_state();assert state['scope']==m.SCOPE and state['automatic_replay']is False and state['actions']=={}

@pytest.fixture
def wrapper(tmp_path):
    root=Path(__file__).parents[1];server=root/'mcp-server/server.py'
    snippet=server if server.is_file()else root/'MCP_SNIPPET.py';tree=ast.parse(snippet.read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='_cam_long_cut_guide_reopen_sealed_payload')
    ns=dict(SCRIPTS_DIR=tmp_path);exec(compile(ast.Module(body=[node],type_ignores=[]),str(snippet),'exec'),ns)
    module=tmp_path/'sw_cam_deep_long_cut_reopen.py';module.write_text('fixed module')
    payload=dict(action=m.ACTION,params=dict(process_id=123,module_sha256=hashlib.sha256(module.read_bytes()).hexdigest(),receipt_path=str(tmp_path/'receipt.json')))
    return ns[node.name],tmp_path,payload

def run_wrapper(case,payload=None,raw=None,pid=123):
    fn,d,p=case;p=p if payload is None else payload;raw=json.dumps(p).encode()if raw is None else raw;path=d/'request.json';path.write_bytes(raw)
    return fn(str(path),hashlib.sha256(raw).hexdigest(),pid)
def test_wrapper_accepts_exact_sealed_payload(wrapper):assert run_wrapper(wrapper)==wrapper[2]
@pytest.mark.parametrize('mutation',[
 lambda p:p.__setitem__('action','verify_deep_guides_reopen'),
 lambda p:p['params'].__setitem__('process_id',True),
 lambda p:p['params'].__setitem__('process_id',124),
 lambda p:p['params'].__setitem__('module_sha256','0'*64),
 lambda p:p.__setitem__('extra',1),
])
def test_wrapper_rejects_wrong_identity(wrapper,mutation):
    p=deepcopy(wrapper[2]);mutation(p)
    with pytest.raises(ValueError):run_wrapper(wrapper,p)
def test_wrapper_duplicate_keys_rejected(wrapper):
    with pytest.raises(ValueError):run_wrapper(wrapper,raw=b'{"action":"x","action":"x","params":{}}')
def test_wrapper_nonfinite_rejected(wrapper):
    with pytest.raises(ValueError):run_wrapper(wrapper,raw=b'{"action":"x","params":{"x":NaN}}')
def test_wrapper_alias_rejected(wrapper):
    p=deepcopy(wrapper[2]);p['params']['receipt_path']=str(wrapper[1]/'request.json')
    with pytest.raises(ValueError):run_wrapper(wrapper,p)
