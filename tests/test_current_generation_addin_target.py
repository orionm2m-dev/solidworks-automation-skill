from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast,json,enum,typing
import pytest
from pydantic import BaseModel,Field,ConfigDict,model_validator,field_validator,ValidationError
from scripts import sw_cam_current_saved_generation as core
from scripts.sw_operation_guard import absolute_document_path
from test_current_saved_generation_authority import authority,load

CLSID='{11111111-2222-3333-4444-555555555555}'


def namespace():
    roots=[Path.cwd(),*Path(__file__).resolve().parents]
    runtime=next(p for p in roots if (p/'mcp-server/server.py').is_file() and (p/'scripts/sw_cam.py').is_file())
    tree=ast.parse((runtime/'mcp-server/server.py').read_text(encoding='utf-8'))
    names={'ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamConfiguredLocalGenerationInput'}
    nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in names]
    stage=Path(__file__).resolve().parents[1]/'server_nodes.py'
    wrapper_tree=ast.parse(stage.read_text(encoding='utf-8')) if stage.is_file() else tree
    wrapper=next(n for n in wrapper_tree.body if isinstance(n,ast.FunctionDef) and n.name=='solidworks_cam_generate_configured_local_group');wrapper.decorator_list=[]
    ns=dict(Enum=enum.Enum,Optional=typing.Optional,Path=Path,BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,field_validator=field_validator,model_validator=model_validator,absolute_document_path=absolute_document_path)
    exec(compile(ast.Module(body=nodes+[wrapper],type_ignores=[]),'real_generation_wrapper_and_models','exec'),ns)
    return ns


def test_completed_loader_exposes_only_pinned_explicit_addin(tmp_path):
    assert load(tmp_path,authority(tmp_path))['addin_clsid']==CLSID


@pytest.mark.parametrize('mutation',[
 lambda r,b,p:r['requests'][0].update(name='different_tool'),
 lambda r,b,p:r['requests'].append(deepcopy(r['requests'][0])),
 lambda r,b,p:r['requests'][0]['arguments']['params'].update(process_id=True),
 lambda r,b,p:r['requests'][0]['arguments']['params'].update(expected_document_path='C:/different.sldprt'),
 lambda r,b,p:r['requests'][0]['arguments']['params'].update(expected_source_sha256='e'*64),
 lambda r,b,p:r['requests'][0]['arguments']['params'].update(expected_process_create_time=42.),
 lambda r,b,p:r['requests'][0]['arguments']['params'].update(observation='profile'),
 lambda r,b,p:r['requests'][0]['arguments']['params'].update(addin_clsid='not-a-GUID'),
 lambda r,b,p:r['requests'][0]['arguments']['params'].pop('addin_clsid'),
 lambda r,b,p:b.update(current_read_request_sha256='e'*64),
])
def test_no_guessed_or_mismatched_addin_request(tmp_path,mutation):
    d=authority(tmp_path);p=d['qualified_read_pins']['request'];r=json.loads(Path(p['path']).read_text());mutation(r,d['binding'],p)
    with pytest.raises(ValueError):core._configuration_addin_clsid(r,p,d['binding'])


def test_actual_wrapper_uses_real_required_target_model_before_mock_com(tmp_path,monkeypatch):
    ns=namespace();calls=[];document=str(tmp_path/'part.sldprt')
    payload=dict(action='generate_configured_local_group',params=dict(generation_mode='current_saved',expected_document_path=document))
    ns.update(_selected_process_id=123,_runtime_identity=SimpleNamespace(assert_current=lambda:calls.append('runtime')),_cam_configured_local_group_sealed_payload=lambda *a:deepcopy(payload),_run_locked=lambda op,*a,**k:op())
    monkeypatch.setattr(core,'prepare_request',lambda p:(p['params'],dict(addin_clsid=CLSID),None))
    sw=object()
    def target(params):
        assert isinstance(params,ns['SolidWorksCamTargetInput'])
        assert params.addin_clsid==CLSID and params.expected_document_path==document
        calls.append('target');return sw,dict(clsid=CLSID,addin_path=str(tmp_path/'cam.dll'))
    def dispatch(actual,clsid,tlb,packet,**kwargs):
        assert actual is sw and clsid==CLSID and packet==payload;calls.append('dispatch_mock');return dict(readback_verified=True)
    ns['_cam_target']=target;monkeypatch.setattr(core,'dispatch_current_saved',dispatch)
    params=ns['SolidWorksCamConfiguredLocalGenerationInput'](process_id=123,request_path=str(tmp_path/'sealed.json'),request_sha256='a'*64)
    result=ns['solidworks_cam_generate_configured_local_group'](params)
    assert result==dict(readback_verified=True) and calls.count('target')==1 and calls.count('dispatch_mock')==1
    with pytest.raises(ValidationError):ns['SolidWorksCamTargetInput'](expected_document_path=document)


def test_actual_wrapper_stops_failed_pinned_request_before_target(tmp_path,monkeypatch):
    ns=namespace();calls=[];payload=dict(params=dict(generation_mode='current_saved',expected_document_path=str(tmp_path/'part.sldprt')))
    ns.update(_selected_process_id=123,_runtime_identity=SimpleNamespace(assert_current=lambda:None),_cam_configured_local_group_sealed_payload=lambda *a:payload,_run_locked=lambda op,*a,**k:op(),_cam_target=lambda x:calls.append('FORBIDDEN_TARGET'))
    def reject(p):raise ValueError('Pinned add-in request binding differs')
    monkeypatch.setattr(core,'prepare_request',reject)
    params=ns['SolidWorksCamConfiguredLocalGenerationInput'](process_id=123,request_path=str(tmp_path/'sealed.json'),request_sha256='a'*64)
    with pytest.raises(ValueError,match='Pinned add-in'):ns['solidworks_cam_generate_configured_local_group'](params)
    assert calls==[]
