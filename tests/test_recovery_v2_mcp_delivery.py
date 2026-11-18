"""Actual named MCP schema/dispatch integration; no application connections."""
from pathlib import Path
from types import ModuleType,SimpleNamespace
from enum import Enum
from typing import Optional,Literal
import ast,os,sys
import pytest
from pydantic import BaseModel,Field,ConfigDict,field_validator,model_validator,ValidationError
RT=Path(os.environ['SWMCP_RUNTIME_ROOT']);ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RT))
import scripts
from scripts import sw_cam_current_pocket_generation_recovery as legacy
from scripts.sw_operation_guard import absolute_document_path
NAMES={'ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamCurrentPocketGenerationRecoveryInput','SolidWorksCamCurrentPocketGenerationRecoveryV2Input','solidworks_cam_recover_generated_current_pocket_v2'}

@pytest.fixture
def adapter(monkeypatch,tmp_path):
    server=ROOT/'mcp-server/server.py'
    if not server.is_file():server=RT/'mcp-server/server.py'
    nodes=[n for n in ast.parse(server.read_text(encoding='utf-8')).body if isinstance(n,(ast.ClassDef,ast.FunctionDef))and n.name in NAMES]
    assert {n.name for n in nodes}==NAMES
    trace=[];controls={'pid':123,'fail_prepare':False,'drift':False,'runs':0}
    backend=ModuleType('scripts.sw_cam_current_pocket_generation_recovery_v2')
    def shape(v):trace.append('shape_v2');legacy.shape(v)
    def prepare(v):
        trace.append('prepare');assert set(v)==legacy.KEYS
        if controls['fail_prepare']:raise ValueError('preflight rejected')
        return {'request':v,'consumed':False}
    def run(sw,clsid,tlb,v,*,prepared,runtime_check):
        trace.append('run');controls['runs']+=1
        assert sw=='verified-sw'and clsid==vparams['addin_clsid']and tlb.endswith('camworks.tlb')
        assert prepared['request']==v and prepared['consumed']is False
        return {'status':'review_required','GTP_attempted':False}
    def revoke(result,error):trace.append('revoke');return dict(result,status='error',reason=str(error))
    backend.shape,backend.prepare,backend.run,backend.revoke=shape,prepare,run,revoke
    monkeypatch.setitem(sys.modules,backend.__name__,backend);monkeypatch.setattr(scripts,'sw_cam_current_pocket_generation_recovery_v2',backend,raising=False)
    def current():
        trace.append('runtime')
        if controls['drift']and controls['runs']:raise ValueError('runtime changed')
    def target(params):trace.append('target');return 'verified-sw',{'clsid':params.addin_clsid,'addin_path':str(tmp_path/'cam.dll')}
    env=dict(BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,field_validator=field_validator,model_validator=model_validator,Optional=Optional,Literal=Literal,Enum=Enum,Path=Path,absolute_document_path=absolute_document_path,mcp=SimpleNamespace(tool=lambda **kw:lambda f:f),_runtime_identity=SimpleNamespace(assert_current=current),_selected_process_id=123,_cam_target=target,_run_locked=lambda op,fmt:op())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(server),'exec'),env)
    vparams=dict(process_id=123,expected_process_create_time=1000.25,expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='a'*64,expected_feature_native_id=22,expected_operation_native_ids=[31,32],selected_operation_native_id=31,failed_generation_receipt_path=str(tmp_path/'raw.json'),failed_generation_receipt_sha256='b'*64,observed_xy_feed_before=100.0,observed_xy_feed_after=200.0,saved_cl_path=str(tmp_path/'fresh_cl/path.cl'),receipt_path=str(tmp_path/'new.json'),qualification_only=True,acknowledge_observed_feed_save_export=True,message_policy='vendor_default',addin_clsid='{11111111-2222-3333-4444-555555555555}')
    return env,vparams,trace,controls

def test_actual_v2_schema_dispatch_uses_only_v2_backend(adapter):
    env,v,trace,_=adapter
    model=env['SolidWorksCamCurrentPocketGenerationRecoveryV2Input'].model_validate(v)
    assert trace==['shape_v2']
    result=env['solidworks_cam_recover_generated_current_pocket_v2'](model)
    assert result['status']=='review_required' and result['GTP_attempted']is False
    assert trace==['shape_v2','runtime','prepare','target','run','runtime']

@pytest.mark.parametrize('field,value',[('process_id',True),('expected_operation_native_ids',[31,True]),('expected_operation_native_ids',[31,31]),('selected_operation_native_id',32),('observed_xy_feed_after',100.0),('expected_document_title','part'),('qualification_only',False),('acknowledge_observed_feed_save_export',False),('unexpected','field')])
def test_invalid_schema_never_prepares_or_connects(adapter,field,value):
    env,v,trace,_=adapter;v[field]=value
    with pytest.raises(ValidationError):env['SolidWorksCamCurrentPocketGenerationRecoveryV2Input'].model_validate(v)
    assert not {'prepare','target','run'}&set(trace)

def test_missing_inherited_addin_rejected(adapter):
    env,v,trace,_=adapter;del v['addin_clsid']
    with pytest.raises(ValidationError):env['SolidWorksCamCurrentPocketGenerationRecoveryV2Input'].model_validate(v)
    assert 'target'not in trace

def test_wrong_selected_pid_stops_before_prepare(adapter):
    env,v,trace,_=adapter;model=env['SolidWorksCamCurrentPocketGenerationRecoveryV2Input'].model_validate(v);env['_selected_process_id']=124
    with pytest.raises(ValueError,match='process'):env['solidworks_cam_recover_generated_current_pocket_v2'](model)
    assert 'prepare'not in trace

def test_failed_file_preparation_never_resolves_cam_target(adapter):
    env,v,trace,c=adapter;c['fail_prepare']=True
    with pytest.raises(ValueError,match='preflight'):env['solidworks_cam_recover_generated_current_pocket_v2'](env['SolidWorksCamCurrentPocketGenerationRecoveryV2Input'].model_validate(v))
    assert 'target'not in trace and c['runs']==0

def test_post_return_runtime_change_revokes_result(adapter):
    env,v,trace,c=adapter;c['drift']=True
    result=env['solidworks_cam_recover_generated_current_pocket_v2'](env['SolidWorksCamCurrentPocketGenerationRecoveryV2Input'].model_validate(v))
    assert result['status']=='error'and trace[-1]=='revoke'and c['runs']==1
