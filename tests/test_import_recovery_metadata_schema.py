"""Portable schema and real public metadata checks; no application activation."""
import ast,importlib.util,os,sys
from pathlib import Path
from enum import Enum
from typing import Literal,Optional
from types import SimpleNamespace
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
S=Path(__file__).resolve().parents[1];R=Path(os.environ.get('SWMCP_RUNTIME_ROOT',S))
sys.path.insert(0,str(R));import scripts
scripts.__path__.insert(0,str(S/'scripts'))
from scripts import sw_cam_process_import_recovery as c
from scripts.sw_operation_guard import absolute_document_path
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def test_all_actual_inventory_interfaces_and_configuration_getter_abi(monkeypatch):
 tlb=os.environ.get('SWMCP_CAM_TYPELIB')
 if not tlb:pytest.skip('Set SWMCP_CAM_TYPELIB for public metadata qualification')
 helper=load('patched_metadata',S/'scripts/sw_cam_comtypes.py')
 monkeypatch.setattr(c,'_interface_class',helper._interface_class)
 proof=c.preflight(tlb);assert proof['interfaces_verified']==15 and proof['native_application_calls']==0
 assert set(c.TYPES)<=set(helper._INTERFACES)
 for fn in(c.core.capture_import_inventory,c.core.read_generic_tool,c.core._items):
  import inspect
  tree=ast.parse(inspect.getsource(fn))
  literals={a.value for n in ast.walk(tree)if isinstance(n,ast.Call)for a in n.args if isinstance(a,ast.Constant)and isinstance(a.value,str)and a.value.startswith('ICW')}
  assert literals<=set(c.TYPES)
def test_constructor_never_accesses_application():
 class NoApplication:
  def __getattribute__(self,name):raise AssertionError(name)
 x=c.ReadContext(NoApplication(),'observed','metadata-only',{}, {}, {},lambda:None,lambda:None)
 assert x.session is None and x.expected is None
def test_readguard_rejects_mutators_and_unaudited_interfaces_before_access():
 g=object.__new__(c.ReadGuard)
 for name in('ImportCAMData','SaveActiveDocument','Save3','Rebuild','GenerateToolpath','SetMachine2','DeleteFeature'):
  with pytest.raises(ValueError):g.read(None,name)
 with pytest.raises(ValueError):g.typed(None,'ICWUnknown')
 with pytest.raises(ValueError):g.dispatch_once(lambda:None,persist_pending=lambda:None)
@pytest.fixture
def ns():
 tree=ast.parse((R/'mcp-server/server.py').read_text(encoding='utf-8-sig'));classes={n.name:n for n in tree.body if isinstance(n,ast.ClassDef)}
 env=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal,Optional=Optional,Enum=Enum,Path=Path,absolute_document_path=absolute_document_path)
 for n in('ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput'):exec(compile(ast.Module(body=[classes[n]],type_ignores=[]),'inherited','exec'),env)
 env['mcp']=SimpleNamespace(tool=lambda **k:lambda f:f);fragment=S/'server.fragment.py'
 nodes=ast.parse(fragment.read_text(encoding='utf-8-sig')).body if fragment.exists()else[n for n in tree.body if getattr(n,'name',None)in('SolidWorksCamImportRecoveryReadInput','solidworks_cam_read_imported_process')]
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'fragment','exec'),env);return env
@pytest.fixture
def values(tmp_path):
 return dict(addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',process_id=123,expected_process_create_time=456.,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,expected_sw_configuration='CAD',expected_cam_configuration='CAM',import_receipt_path=str(tmp_path/'import.json'),import_receipt_sha256='b'*64,receipt_path=str(tmp_path/'read.json'),qualification_only=True,message_policy='vendor_default')
@pytest.mark.parametrize('key,value',[('process_id',True),('expected_process_create_time',True),('qualification_only',1),('expected_sw_configuration',''),('receipt_path','relative'),('expected_document_title','part'),('extra',True)])
def test_public_schema_rejects_bad_identity_and_coercion(ns,values,key,value):
 values[key]=value
 with pytest.raises(ValueError):ns['SolidWorksCamImportRecoveryReadInput'](**values)
def test_endpoint_prepares_once_before_application_and_consumes_same_bundle(ns,values,monkeypatch):
 trace=[];bundle=object()
 monkeypatch.setattr(c,'prepare',lambda v,**k:(trace.append('prepare')or bundle))
 def read(*args,_prepared,**kw):assert _prepared is bundle;trace.append('read');return {'readback_verified':True}
 monkeypatch.setattr(c,'run_read',read)
 ns.update(_runtime_identity=SimpleNamespace(assert_current=lambda:trace.append('runtime')),_selected_process_id=123,
   _cam_target=lambda p:(trace.append('target')or(object(),{'clsid':values['addin_clsid'],'addin_path':str(Path(values['receipt_path']).parent/'cam.dll')})),
   _run_locked=lambda fn,fmt:fn())
 out=ns['solidworks_cam_read_imported_process'](ns['SolidWorksCamImportRecoveryReadInput'](**values))
 assert out['readback_verified']is True and trace.count('prepare')==1 and trace.index('prepare')<trace.index('target')<trace.index('read')
