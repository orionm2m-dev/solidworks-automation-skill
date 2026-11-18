"""Use actual inherited installed schema AST; no server import or application access."""
from pathlib import Path
from types import SimpleNamespace
from enum import Enum
from typing import Literal,Optional
import ast,os,sys
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
S=Path(__file__).resolve().parents[1];K=Path(os.environ.get('SWMCP_RUNTIME_ROOT',os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1])) )
sys.dont_write_bytecode=True;sys.path.insert(0,str(K));import scripts;scripts.__path__.insert(0,str(S/'scripts'))
from scripts import sw_cam_process_import as core
from scripts.sw_operation_guard import absolute_document_path

@pytest.fixture
def ns():
 source=(K/'mcp-server/server.py').read_text(encoding='utf-8-sig');tree=ast.parse(source);nodes={n.name:n for n in tree.body if isinstance(n,ast.ClassDef)}
 env=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal,Optional=Optional,Path=Path,Enum=Enum,absolute_document_path=absolute_document_path)
 for name in('ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput'):
  exec(compile(ast.Module(body=[nodes[name]],type_ignores=[]),'installed_schema','exec'),env)
 class MCP:
  def tool(self,**kw):return lambda f:f
 env['mcp']=MCP();fragment=S/'server.fragment.py'
 if fragment.exists():selected=ast.parse(fragment.read_text(encoding='utf-8-sig')).body
 else:selected=[n for n in tree.body if getattr(n,'name',None)in('SolidWorksCamProcessImportInput','solidworks_cam_import_process_data')]
 exec(compile(ast.Module(body=selected,type_ignores=[]),'fragment','exec'),env);return env

@pytest.fixture
def values(tmp_path):
 return dict(addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',process_id=123,expected_process_create_time=456.,expected_document_path=str(tmp_path/'copy/copy.sldprt'),expected_source_sha256='a'*64,original_document_path=str(tmp_path/'original/original.sldprt'),original_source_sha256='a'*64,export_receipt_path=str(tmp_path/'history/export.json'),export_receipt_sha256='b'*64,receipt_path=str(tmp_path/'history/import.json'),qualification_only=True,message_policy='vendor_default',acknowledge_isolated_copy=True,allow_vendor_default_import_rebuild=True)

@pytest.mark.parametrize('fault',['missing_addin','bool_pid','false_ack','int_ack','str_allow','title','relative','extra'])
def test_real_inherited_public_schema_rejects_unsafe_or_coerced_fields(ns,values,fault):
 if fault=='missing_addin':del values['addin_clsid']
 elif fault=='bool_pid':values['process_id']=True
 elif fault=='false_ack':values['acknowledge_isolated_copy']=False
 elif fault=='int_ack':values['acknowledge_isolated_copy']=1
 elif fault=='str_allow':values['allow_vendor_default_import_rebuild']='true'
 elif fault=='title':values['expected_document_title']='other'
 elif fault=='relative':values['original_document_path']='../part.sldprt'
 elif fault=='extra':values['Save']=True
 with pytest.raises(ValueError):ns['SolidWorksCamProcessImportInput'](**values)

@pytest.mark.parametrize('fault',[None,'owner','post_runtime'])
def test_wrapper_prepares_once_before_target_and_passes_same_private_bundle(ns,values,monkeypatch,fault):
 params=ns['SolidWorksCamProcessImportInput'](**values);trace=[];bundle=object()
 def runtime():
  trace.append('runtime')
  if fault=='post_runtime'and 'run'in trace:raise ValueError('runtime changed')
 ns.update(_runtime_identity=SimpleNamespace(assert_current=runtime),_selected_process_id=999 if fault=='owner'else 123,_run_locked=lambda fn,fmt:fn())
 def prepare(v,*,runtime_check):trace.append('prepare');assert set(v)==core.KEYS;return bundle
 def target(p):trace.append('target');return object(),dict(clsid=values['addin_clsid'],addin_path=str(Path(values['receipt_path']).parent/'cam.dll'))
 def run(*args,runtime_check,_prepared,**v):
  trace.append('run');assert _prepared is bundle and set(v)==core.KEYS
  return dict(import_observed=True,native_call_returned=True,native_return_value=0,model_saved=False)
 def revoke(r,e):trace.append('revoke');return dict(r,readback_verified=False,runtime_unchanged=False)
 monkeypatch.setattr(core,'prepare',prepare);monkeypatch.setattr(core,'run_import',run);monkeypatch.setattr(core,'revoke_runtime',revoke);ns['_cam_target']=target
 if fault=='owner':
  with pytest.raises(ValueError):ns['solidworks_cam_import_process_data'](params)
  assert 'prepare'not in trace and 'target'not in trace
 else:
  r=ns['solidworks_cam_import_process_data'](params)
  assert trace.count('prepare')==trace.count('target')==trace.count('run')==1
  assert trace.index('prepare')<trace.index('target')<trace.index('run')
  assert r['native_return_value']==0 and r['model_saved']is False
  if fault=='post_runtime':assert r['readback_verified']is False and trace[-1]=='revoke'


