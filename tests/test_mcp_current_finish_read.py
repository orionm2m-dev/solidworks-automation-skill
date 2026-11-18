"""Portable input and dispatch contract tests; no application connection."""
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Optional
from enum import Enum
import ast
import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator, ValidationError
import scripts
from scripts.sw_operation_guard import absolute_document_path


@pytest.fixture
def wrapper(monkeypatch):
    calls=[]
    # Execute actual inherited schema nodes, never a permissive stand-in.
    root = Path(scripts.__file__).resolve().parents[1]
    server = root / "mcp-server" / "server.py"
    parsed = ast.parse(server.read_text(encoding="utf-8-sig"))
    names = {"ResponseFormat", "BaseInput", "ActiveDocumentInput", "SolidWorksCamTargetInput"}
    inherited = ast.Module(body=[n for n in parsed.body if getattr(n, "name", None) in names], type_ignores=[])
    assert len(inherited.body) == 4
    base_env = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, Optional=Optional,
                    Enum=Enum, field_validator=field_validator, absolute_document_path=absolute_document_path)
    exec(compile(inherited, str(server), "exec"), base_env)
    Target = base_env["SolidWorksCamTargetInput"]
    class MCP:
        def tool(self,**metadata):
            calls.append(('registration',metadata))
            return lambda f:f
    def runtime():calls.append(('runtime',None))
    def target(params):
        calls.append(('target',params.process_id))
        return 'owned_sw',dict(clsid='fixture',addin_path='C:/vendor/cam.dll')
    def validate(values):calls.append(('validate',values.copy()))
    def dispatch(sw,clsid,tlb,*,runtime_check,**values):
        calls.append(('dispatch',(sw,clsid,tlb,values.copy(),runtime_check)))
        return dict(status='review_required',readback_verified=True,source_unchanged=True,
                    snapshots=[dict(feed=12.)],mutation_attempted=False)
    def failure(result,error):
        calls.append(('runtime_failure',str(error)))
        return {**result,'status':'error','readback_verified':False,'runtime_unchanged':False}
    core=SimpleNamespace(validate=validate,dispatch=dispatch,finalize_runtime_failure=failure)
    monkeypatch.setattr(scripts,'sw_cam_current_finish_read',core,raising=False)
    env=dict(SolidWorksCamTargetInput=Target,ConfigDict=ConfigDict,Field=Field,
             Literal=Literal,model_validator=model_validator,mcp=MCP(),Path=Path,
             _runtime_identity=SimpleNamespace(assert_current=runtime),_selected_process_id=123,
             _cam_target=target,_run_locked=lambda op,fmt:op())
    source=Path(__file__).parents[1]/'server.fragment.py'
    if source.exists():tree=ast.parse(source.read_text(encoding='utf-8'))
    else:
        source=Path(__file__).parents[1]/'mcp-server/server.py'
        tree=ast.parse(source.read_text(encoding='utf-8-sig'))
        names={'SolidWorksCamCurrentFinishReadInput','solidworks_cam_read_current_finish_context'}
        tree=ast.Module(body=[n for n in tree.body if getattr(n,'name',None)in names],type_ignores=[])
        assert len(tree.body)==2
    exec(compile(tree,str(source),'exec'),env)
    values=dict(addin_clsid='{11111111-2222-3333-4444-555555555555}',process_id=123,expected_process_create_time=100.25,expected_document_path='C:/job/current.sldprt',
        expected_source_sha256='a'*64,revision_receipt_path='C:/job/revision.json',revision_receipt_sha256='b'*64,
        revision_marker_path='C:/job/marker.json',revision_marker_sha256='c'*64,operation_native_id=401,
        expected_feature_native_id=359,expected_tool_native_id=249,receipt_path='C:/job/finish_read.json')
    return env,calls,core,values


def invoke(env,values):
    return env['solidworks_cam_read_current_finish_context'](env['SolidWorksCamCurrentFinishReadInput'](**values))


def test_validated_before_application_then_one_exact_read_dispatch(wrapper):
    env,calls,core,v=wrapper;result=invoke(env,v)
    assert [c[0]for c in calls]==['registration','runtime','validate','target','dispatch','runtime']
    args=next(c[1]for c in calls if c[0]=='dispatch')
    assert args[:2]==('owned_sw','fixture') and Path(args[2]).name=='camworks.tlb' and callable(args[4])
    expected={**{k:value for k,value in v.items() if k!='addin_clsid'},'qualification_only':True,'message_policy':'vendor_default','read_scope':'full','prior_read_receipt_path':None,'prior_read_receipt_sha256':None}
    assert args[3]==expected and next(c[1]for c in calls if c[0]=='validate')==expected
    assert result['readback_verified'] and not result['mutation_attempted']


@pytest.mark.parametrize('owner',[None,True,124])
def test_wrong_owner_stops_before_history_and_application(wrapper,owner):
    env,calls,core,v=wrapper;env['_selected_process_id']=owner
    with pytest.raises(ValueError):invoke(env,v)
    assert not any(c[0]in {'validate','target','dispatch'}for c in calls)


def test_failed_history_guard_stops_before_application(wrapper):
    env,calls,core,v=wrapper
    core.validate=lambda values:(_ for _ in ()).throw(ValueError('stale revision'))
    with pytest.raises(ValueError,match='stale revision'):invoke(env,v)
    assert not any(c[0]in {'target','dispatch'}for c in calls)


def test_post_read_runtime_failure_keeps_observations_and_does_not_replay(wrapper):
    env,calls,core,v=wrapper;n=0
    def runtime():
        nonlocal n
        n+=1
        if n==2:raise RuntimeError('runtime drift')
    env['_runtime_identity'].assert_current=runtime
    result=invoke(env,v)
    assert result['status']=='error' and result['readback_verified']is False
    assert result['snapshots']==[dict(feed=12.)] and not result['mutation_attempted']
    assert sum(c[0]=='dispatch'for c in calls)==sum(c[0]=='runtime_failure'for c in calls)==1


@pytest.mark.parametrize('change',[
 {'process_id':True},{'expected_process_create_time':float('inf')},{'operation_native_id':True},
 {'expected_feature_native_id':0},{'expected_tool_native_id':False},{'expected_source_sha256':'bad'},
 {'revision_receipt_sha256':'A'*64},{'revision_marker_sha256':'a'*63},{'revision_marker_path':''},
 {'qualification_only':False},{'qualification_only':1},{'expected_document_title':'other'},
 {'message_policy':'yes'},{'set_feed':5.},{'receipt_path':''}])
def test_invalid_or_mutating_scope_rejected_before_dispatch(wrapper,change):
    env,calls,core,v=wrapper;v.update(change)
    with pytest.raises(ValidationError):invoke(env,v)
    assert not any(c[0]in {'target','dispatch'}for c in calls)


def test_readonly_registration_does_not_promise_replaying_same_receipt(wrapper):
    env,calls,core,v=wrapper;meta=calls[0][1]
    assert meta['name']=='solidworks_cam_read_current_finish_context'
    assert meta['annotations']==dict(readOnlyHint=True,destructiveHint=False,idempotentHint=False,openWorldHint=False)


def test_real_inherited_schema_requires_explicit_registered_addin(wrapper):
    env,calls,core,v=wrapper
    del v['addin_clsid']
    with pytest.raises(ValidationError):invoke(env,v)
    assert not any(c[0] in {'validate','target','dispatch'} for c in calls)


@pytest.mark.parametrize('change', [
    {'addin_clsid':None}, {'addin_clsid':'invalid'}, {'read_scope':'all'},
    {'read_scope':'modes_nc_only'},
    {'read_scope':'modes_nc_only','prior_read_receipt_path':'C:/job/prior.json'},
    {'read_scope':'modes_nc_only','prior_read_receipt_sha256':'d'*64},
    {'read_scope':'full','prior_read_receipt_path':'C:/job/prior.json','prior_read_receipt_sha256':'d'*64},
    {'read_scope':'modes_nc_only','prior_read_receipt_path':'','prior_read_receipt_sha256':'d'*64},
    {'read_scope':'modes_nc_only','prior_read_receipt_path':'C:/job/prior.json','prior_read_receipt_sha256':'wrong'}])
def test_scope_and_prior_limitation_fail_closed_before_application(wrapper,change):
    env,calls,core,v=wrapper;v.update(change)
    with pytest.raises(ValidationError):invoke(env,v)
    assert not any(c[0] in {'validate','target','dispatch'} for c in calls)


def test_modes_only_prior_pins_pass_through_without_hidden_retry(wrapper):
    env,calls,core,v=wrapper
    v.update(read_scope='modes_nc_only',prior_read_receipt_path='C:/job/prior.json',prior_read_receipt_sha256='d'*64)
    invoke(env,v)
    values=next(c[1][3] for c in calls if c[0]=='dispatch')
    for name in ('read_scope','prior_read_receipt_path','prior_read_receipt_sha256'):
        assert values[name]==v[name]
    assert 'addin_clsid' not in values
    assert sum(c[0]=='dispatch' for c in calls)==1
