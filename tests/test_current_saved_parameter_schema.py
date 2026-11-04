import ast,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID,context,server
from scripts import sw_cam_current_saved_parameter_batch as core

SOURCE=Path(__file__).resolve().parents[1]/'server_nodes.py'
if SOURCE.is_file():
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'));assert len(tree.body)==2
    server.mcp._tool_manager._tools.pop('solidworks_cam_configure_guide_definitions',None)
    exec(compile(tree,str(SOURCE),'exec'),server.__dict__)

@pytest.fixture
def fake(context,monkeypatch):
    monkeypatch.setattr(core,'validate',lambda *a,**k:None)
    f=Mock(return_value=dict(status='review_required',mutation_attempted=False,readback_verified=True,before={'captured':True},confirm_before={'captured':True}))
    monkeypatch.setattr(core,'run_current_saved_configuration',f)
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=lambda:None))
    return f

def params(context,**kw):
    values=dict(process_id=731,expected_process_create_time=100.25,addin_clsid=CLSID,expected_document_path=context.document,expected_source_sha256='a'*64,expected_feature_native_id=70,expected_feature_setup_native_id=71,expected_operation_setup_native_id=94,expected_operation_native_ids=[355,356],expected_generated_operation_count=0,expected_total_record_count=0,observation='operation_parameters',parameters_authority_receipt_path='authority.json',parameters_authority_receipt_sha256='b'*64,parameter_operation_native_ids=[355,356],qualification_only=True,configuration_mode='current_saved',candidate_tool_native_id=50,expected_candidate_consumer_ids=[],current_read_request_path='request.json',current_read_request_sha256='c'*64,current_read_receipt_path='read.json',current_read_receipt_sha256='d'*64,recipe_path='recipe.json',recipe_sha256='e'*64,acknowledge_qualification_only=True,attempt_registry_path='attempts',receipt_path='output.json')
    values.update(kw);return server.SolidWorksCamCurrentSavedConfigurationInput(**values)

def test_exact_forwarding_existing_endpoint(context,fake):
    p=params(context);r=json.loads(server.solidworks_cam_configure_guide_definitions(p))
    assert r['readback_verified'] and r['runtime_unchanged']
    fake.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),runtime_check=server._runtime_identity.assert_current,**p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    tool=server.mcp._tool_manager._tools['solidworks_cam_configure_guide_definitions']
    assert 'SolidWorksCamCurrentSavedConfigurationInput' in json.dumps(tool.parameters)

@pytest.mark.parametrize('kw',[{'candidate_tool_native_id':True},{'candidate_tool_native_id':'50'},{'expected_candidate_consumer_ids':[True]},{'expected_candidate_consumer_ids':['2']},{'save_after_verified':1},{'configuration_mode':'legacy'},{'unknown_setter':'anything'},{'recipe_sha256':'short'}])
def test_strict_schema_no_native(context,fake,kw):
    with pytest.raises(ValueError):params(context,**kw)
    fake.assert_not_called()

@pytest.mark.parametrize('pid',[None,True,732])
def test_owned_process_before_core(context,fake,monkeypatch,pid):
    monkeypatch.setattr(server,'_selected_process_id',pid)
    r=json.loads(server.solidworks_cam_configure_guide_definitions(params(context)))
    assert r['status']=='error';fake.assert_not_called()

def test_wrapper_post_drift_keeps_returned_evidence(context,fake,monkeypatch):
    fake.return_value.update(mutation_attempted=True,save_call_returned=True,save_hresult=0,saved={'complete':True})
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock(side_effect=[None,ValueError('drift')])))
    r=json.loads(server.solidworks_cam_configure_guide_definitions(params(context)))
    assert r['status']=='uncertain' and r['saved']['complete'] and r['save_call_returned']
    assert not r['readback_verified'] and not r['runtime_unchanged'] and fake.call_count==1

def test_legacy_sealed_wrapper_branch_ast_unchanged():
    import hashlib
    source=SOURCE if SOURCE.is_file() else Path.cwd()/'mcp-server/server.py'
    staged=next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='solidworks_cam_configure_guide_definitions')
    actual=hashlib.sha256(ast.dump(ast.Module(body=staged.body[2:],type_ignores=[])).encode()).hexdigest()
    assert actual=='d06074706a2bdcf3ea13bd89fbe6bad2e9009f87476b6cac74adc39f7f0e31f2'
