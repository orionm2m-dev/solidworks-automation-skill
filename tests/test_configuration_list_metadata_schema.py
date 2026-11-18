"""Only new ABI/schema and application-free construction; installed readers reused."""
import ast,os,sys
from pathlib import Path
from typing import Literal,Optional
from enum import Enum
from types import SimpleNamespace
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
S=Path(__file__).resolve().parents[1];R=Path(os.environ.get('SWMCP_RUNTIME_ROOT',S))
sys.path.insert(0,str(R));import scripts;scripts.__path__.insert(0,str(S/'scripts'))
from scripts import sw_cam_process_configuration_list as c
from scripts.sw_operation_guard import absolute_document_path
def test_new_public_getallconfigurations_abi():
 tlb=os.environ.get('SWMCP_CAM_TYPELIB')
 if not tlb:pytest.skip('Set SWMCP_CAM_TYPELIB for actual public metadata check')
 r=c.preflight(tlb);assert r['GetAllConfigurations_dispid']==23 and r['native_application_calls']==0
def test_no_application_constructor_and_no_activation_gate():
 class NoApplication:
  def __getattribute__(self,name):raise AssertionError(name)
 ctx=c.ReadContext(NoApplication(),'observed','metadata',{}, {}, {},lambda:None,lambda:None)
 assert ctx.expected is None
 g=object.__new__(c.ReadGuard)
 for n in('ActivateConfiguration','ActivateConfiguration2','AddNewConfiguration','DeleteConfiguration','SaveActiveDocument','ImportCAMData'):
  with pytest.raises(ValueError):g.read(None,n)
 with pytest.raises(ValueError):g.dispatch_once(lambda:None,persist_pending=lambda:None)
@pytest.fixture
def env():
 tree=ast.parse((R/'mcp-server/server.py').read_text(encoding='utf-8-sig'));classes={n.name:n for n in tree.body if isinstance(n,ast.ClassDef)}
 e=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal,Optional=Optional,Enum=Enum,Path=Path,absolute_document_path=absolute_document_path)
 for n in('ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamImportRecoveryReadInput'):
  exec(compile(ast.Module(body=[classes[n]],type_ignores=[]),'actual parents','exec'),e)
 e['mcp']=SimpleNamespace(tool=lambda **k:lambda f:f)
 fragment=S/'server.fragment.py';nodes=ast.parse(fragment.read_text(encoding='utf-8-sig')).body if fragment.exists()else[n for n in tree.body if getattr(n,'name',None)in('SolidWorksCamConfigurationListInput','solidworks_cam_list_import_configurations')]
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'fragment','exec'),e);return e
@pytest.fixture
def vals(tmp_path):
 return dict(addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',process_id=123,expected_process_create_time=456.,expected_document_path=str(tmp_path/'p.sldprt'),expected_source_sha256='a'*64,expected_sw_configuration='CAD',expected_cam_configuration='CAM',import_receipt_path=str(tmp_path/'import.json'),import_receipt_sha256='b'*64,empty_read_receipt_path=str(tmp_path/'empty.json'),empty_read_receipt_sha256='c'*64,receipt_path=str(tmp_path/'out.json'),qualification_only=True,message_policy='vendor_default')
@pytest.mark.parametrize('key,value',[('process_id',True),('empty_read_receipt_path','relative'),('empty_read_receipt_sha256','bad'),('activation',True),('qualification_only',1)])
def test_schema_preserves_strict_inherited_scope(env,vals,key,value):
 vals[key]=value
 with pytest.raises(ValueError):env['SolidWorksCamConfigurationListInput'](**vals)
def test_wrapper_prepares_once_before_app(env,vals,monkeypatch):
 trace=[];bundle=object()
 def prepare(v,**kw):assert kw['_validate']is c.validate;trace.append('prepare');return bundle
 monkeypatch.setattr(c.recovery,'prepare',prepare)
 def run(*args,_prepared,**kwargs):assert _prepared is bundle;trace.append('run');return dict(readback_verified=True)
 monkeypatch.setattr(c,'run_read',run)
 env.update(_runtime_identity=SimpleNamespace(assert_current=lambda:None),_selected_process_id=123,_run_locked=lambda f,fmt:f(),
   _cam_target=lambda p:(trace.append('target')or(object(),{'clsid':vals['addin_clsid'],'addin_path':str(Path(vals['receipt_path']).parent/'cam.dll')})))
 assert env['solidworks_cam_list_import_configurations'](env['SolidWorksCamConfigurationListInput'](**vals))['readback_verified']
 assert trace==['prepare','target','run']
