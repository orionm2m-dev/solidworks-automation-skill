from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import ast,json,hashlib
import pytest
from scripts import sw_cam_current_generation_native as n
from scripts import sw_cam_current_saved_generation as g
from test_generation_capture_compatibility import env,generated


def ctx(e,monkeypatch,*,attempted=()):
    c=n.NativeGenerationContext.__new__(n.NativeGenerationContext)
    c.v=dict(expected_feature_native_id=70,expected_feature_setup_native_id=7,parameter_operation_native_ids=[356,358],candidate_tool_native_id=249)
    c.data=dict(authority=dict(definition_mode='selected_insert'));c.consumer_ids=[248,320];c.attempted=list(attempted);c.loaded=dict(selected_ids=[356]);c.report={};c.persist=lambda:None;c.app={};c.tlb='tlb';c.native=e['native'];c.read=e['read'];c.typed=e['typed'];c.boundary=lambda:dict(path='part.sldprt',type=1,needs_save=False);c.check=lambda:None
    def capture(app,tlb,read,typed,state,v,boundary,**kwargs):
        assert kwargs=={'verify_operation_pins':False};state.update(deepcopy(e['state']));state.update(features=[dict(geometry=dict(native_id=70))],target_header=dict(native_id=70));return e['native']
    monkeypatch.setattr(n.current,'_capture',capture)
    monkeypatch.setattr(n,'read_compound_strategy',lambda state,native,read,typed,details,**k:details.update(attribute_id=1))
    monkeypatch.setattr(n,'read_catalogues',lambda *a,**k:[])
    return c


def test_native_bridge_full_postgeneration_capture(env,monkeypatch):
    generated(env);c=ctx(env,monkeypatch,attempted=[356]);out={};actual=c.capture('after',out)
    assert actual is out and actual['operations'][2]['toolpath_generated'] and actual['parameter_capture_complete']
    assert actual['parameter_batch']['target_nc']['356']['feeds_compensation']['XYFeed']==456.


def test_native_bridge_rejects_unattempted_generated_target(env,monkeypatch):
    generated(env);c=ctx(env,monkeypatch);out={}
    with pytest.raises(ValueError,match='unattempted'):c.capture('after',out)
    assert out['operations'][2]['toolpath_generated'] and not out.get('parameter_capture_complete')


def test_native_bridge_default_before_capture(env,monkeypatch):
    c=ctx(env,monkeypatch);out={};c.capture('before',out)
    assert out['parameter_capture_complete'] and out['operations'][2]['toolpath_generated']is False


def test_native_bridge_inherits_lifetime_source_runtime_identity():
    for name in ('identity','boundary','read','typed','__enter__','__exit__'):
        assert name not in n.NativeGenerationContext.__dict__


def server_namespace(tmp_path):
    base=Path(__file__).resolve().parents[1];source=base/'server_nodes.py'
    if not source.is_file():source=base/'mcp-server/server.py'
    s=source.read_text(encoding='utf-8');namespace=dict(Path=Path,SCRIPTS_DIR=str(tmp_path))
    tree=ast.parse(s);functions=[x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name in {'_cam_configured_local_group_sealed_payload','solidworks_cam_generate_configured_local_group'}]
    for f in functions:f.returns=None;f.args.args[0].annotation=None;f.decorator_list=[]
    exec(compile(ast.Module(body=functions,type_ignores=[]),'staged_server','exec'),namespace)
    return namespace


def sealed(tmp_path,mode):
    module=tmp_path/('sw_cam_current_saved_generation.py'if mode else'sw_cam_local_generation.py');module.write_text('sentinel')
    p=dict(process_id=123,expected_document_path=str(tmp_path/'part.sldprt'),configuration_receipt_path=str(tmp_path/'config.json'),module_sha256=hashlib.sha256(module.read_bytes()).hexdigest(),receipt_path=str(tmp_path/'out.json'),progress_path=str(tmp_path/'progress.json'),saved_cl_path=str(tmp_path/'saved.cl'))
    if mode:p.update(generation_mode='current_saved',before_cl_path=str(tmp_path/'before.cl'))
    request=dict(action='generate_configured_local_group',params=p);path=tmp_path/'request.json';path.write_text(json.dumps(request));return request,path,hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('mode',[True,False])
def test_existing_sealed_helper_accepts_correct_branch_module(tmp_path,mode):
    ns=server_namespace(tmp_path);request,p,sha=sealed(tmp_path,mode)
    assert ns['_cam_configured_local_group_sealed_payload'](str(p),sha,123)==request


def test_new_sealed_helper_checks_precl_output_alias(tmp_path):
    ns=server_namespace(tmp_path);request,p,sha=sealed(tmp_path,True);request['params']['before_cl_path']=request['params']['expected_document_path'];p.write_text(json.dumps(request));sha=hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='alias'):ns['_cam_configured_local_group_sealed_payload'](str(p),sha,123)


def test_legacy_tool_body_preserved_as_ast_suffix():
    base=Path(__file__).resolve().parents[1];source=base/'server_nodes.py'
    if not source.is_file():source=base/'mcp-server/server.py'
    old=json.loads((Path(__file__).resolve().parent/'fixtures/generation_legacy_endpoint_ast.json').read_text(encoding='utf-8'))
    new=ast.parse(source.read_text(encoding='utf-8'))
    b=next(x for x in new.body if isinstance(x,ast.FunctionDef)and x.name=='solidworks_cam_generate_configured_local_group')
    assert old==[ast.dump(x)for x in b.body[-2:]]


def test_compound_abi_rejection_precedes_backend_native_start(monkeypatch,tmp_path):
    from scripts import sw_cam_mill_current_compound_read as current
    calls=[]
    monkeypatch.setattr(g,'prepare_request',lambda request:({}, {},tmp_path/'marker.json'))
    monkeypatch.setattr(g,'preflight',lambda tlb:calls.append('gtp_save_cl_metadata'))
    def reject(tlb):calls.append('compound_metadata');raise ValueError('Exact getter ABI differs')
    monkeypatch.setattr(current,'_abi',reject)
    def factory(*a):calls.append('native_backend');raise AssertionError('Native must not start')
    with pytest.raises(ValueError,match='getter ABI'):g.dispatch_current_saved(None,None,'tlb',{},runtime_check=lambda:calls.append('runtime'),_backend_factory=factory)
    assert calls==['gtp_save_cl_metadata','compound_metadata']and not(tmp_path/'marker.json').exists()
