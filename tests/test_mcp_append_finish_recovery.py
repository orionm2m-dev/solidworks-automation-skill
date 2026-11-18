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
    def dispatch(sw,clsid,tlb,values,*,runtime_check):
        calls.append(('dispatch',(sw,clsid,tlb,values.copy(),runtime_check)))
        return dict(status='review_required',readback_verified=True,source_unchanged=False,
                    saved=True,save_attempted=True,save_return_value=0,saved_file_sha256='e'*64,
                    snapshots=[dict(operation_count=28)],mutation_attempted=True)
    def failure(result,error):
        calls.append(('runtime_failure',str(error)))
        return {**result,'status':'error','readback_verified':False,'runtime_unchanged':False}
    core=SimpleNamespace(validate=validate,dispatch=dispatch,finalize_runtime_failure=failure)
    monkeypatch.setattr(scripts,'sw_cam_append_finish_definitions',core,raising=False)
    env=dict(SolidWorksCamTargetInput=Target,ConfigDict=ConfigDict,Field=Field,
             Literal=Literal,Optional=Optional,model_validator=model_validator,field_validator=field_validator,mcp=MCP(),Path=Path,
             _runtime_identity=SimpleNamespace(assert_current=runtime),_selected_process_id=123,
             _cam_target=target,_run_locked=lambda op,fmt:op())
    source=Path(__file__).parents[1]/'server.fragment.py'
    if source.exists():tree=ast.parse(source.read_text(encoding='utf-8'))
    else:
        source=Path(__file__).parents[1]/'mcp-server/server.py'
        tree=ast.parse(source.read_text(encoding='utf-8-sig'))
        names={'SolidWorksCamAppendFinishDefinitionsInput','solidworks_cam_append_finish_definitions'}
        tree=ast.Module(body=[n for n in tree.body if getattr(n,'name',None)in names],type_ignores=[])
        assert len(tree.body)==2
    exec(compile(tree,str(source),'exec'),env)
    values=dict(addin_clsid='{11111111-2222-3333-4444-555555555555}',process_id=123,expected_process_create_time=100.25,expected_document_path='C:/job/current.sldprt',
        expected_source_sha256='a'*64,revision_receipt_path='C:/job/revision.json',revision_receipt_sha256='b'*64,
        revision_marker_path='C:/job/marker.json',revision_marker_sha256='c'*64,
        recipe_path='C:/job/recipe.json',recipe_sha256='d'*64,receipt_path='C:/job/append.json')
    return env,calls,core,values


def invoke(env,values):
    return env['solidworks_cam_append_finish_definitions'](env['SolidWorksCamAppendFinishDefinitionsInput'](**values))


def test_validated_before_application_then_one_exact_read_dispatch(wrapper):
    env,calls,core,v=wrapper;result=invoke(env,v)
    assert [c[0]for c in calls]==['registration','runtime','validate','target','dispatch','runtime']
    args=next(c[1]for c in calls if c[0]=='dispatch')
    assert args[:2]==('owned_sw','fixture') and Path(args[2]).name=='camworks.tlb' and callable(args[4])
    expected={**{k:value for k,value in v.items() if k!='addin_clsid'},'qualification_only':True,'message_policy':'vendor_default'}
    assert args[3]==expected and next(c[1]for c in calls if c[0]=='validate')==expected
    assert result['readback_verified'] and result['mutation_attempted'] and result['saved']


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
    assert result['snapshots']==[dict(operation_count=28)] and result['mutation_attempted']
    assert result['saved'] and result['save_attempted'] and result['save_return_value']==0
    assert result['saved_file_sha256']=='e'*64
    assert sum(c[0]=='dispatch'for c in calls)==sum(c[0]=='runtime_failure'for c in calls)==1


@pytest.mark.parametrize('change',[
 {'process_id':True},{'process_id':0},{'expected_process_create_time':float('inf')},
 {'expected_source_sha256':'bad'},{'revision_receipt_sha256':'A'*64},
 {'revision_marker_sha256':'a'*63},{'revision_marker_path':''},{'recipe_sha256':'broken'},
 {'recipe_path':''},{'qualification_only':False},{'qualification_only':1},
 {'qualification_only':'true'},{'expected_document_title':'other'},
 {'message_policy':'yes'},{'set_feed':5.},{'receipt_path':''},{'addin_clsid':None},
 {'addin_clsid':'invalid'},{'tool_native_id':252},{'generate':True},
 {'definitions':[{},{}]},{'expected_document_path':'relative.sldprt'}])
def test_invalid_or_expanded_scope_rejected_before_dispatch(wrapper,change):
    env,calls,core,v=wrapper;v.update(change)
    with pytest.raises(ValidationError):invoke(env,v)
    assert not any(c[0]in {'validate','target','dispatch'}for c in calls)


def test_additive_registration_does_not_promise_replaying_same_receipt(wrapper):
    env,calls,core,v=wrapper;meta=calls[0][1]
    assert meta['name']=='solidworks_cam_append_finish_definitions'
    assert meta['annotations']==dict(readOnlyHint=False,destructiveHint=False,idempotentHint=False,openWorldHint=False)



def test_real_inherited_schema_requires_exact_registered_addin(wrapper):
    env,calls,core,v=wrapper
    del v['addin_clsid']
    with pytest.raises(ValidationError):invoke(env,v)
    assert not any(c[0]in {'validate','target','dispatch'}for c in calls)


def test_recipe_hash_and_predecessor_fields_are_not_discarded(wrapper):
    env,calls,core,v=wrapper;invoke(env,v)
    values=next(c[1][3]for c in calls if c[0]=='dispatch')
    expected_keys=set(v)-{'addin_clsid'}|{'qualification_only','message_policy'}
    assert set(values)==expected_keys
    for k in ('recipe_path','recipe_sha256','revision_receipt_path','revision_receipt_sha256',
              'revision_marker_path','revision_marker_sha256','expected_source_sha256'):
        assert values[k]==v[k]


def test_backend_exception_does_not_replay_or_claim_saved(wrapper):
    env,calls,core,v=wrapper
    def fail(*args,**kwargs):
        calls.append(('failed_dispatch',None))
        raise RuntimeError('native outcome retained in backend receipt')
    core.dispatch=fail
    with pytest.raises(RuntimeError,match='native outcome'):invoke(env,v)
    assert sum(c[0]=='failed_dispatch'for c in calls)==1
    assert not any(c[0]=='runtime_failure'for c in calls)


@pytest.fixture
def recovery_wrapper(wrapper,monkeypatch):
    env,calls,core,v=wrapper
    def validate(values):calls.append(('recovery_validate',values.copy()))
    def dispatch(sw,clsid,tlb,values,*,runtime_check):
        calls.append(('recovery_dispatch',(sw,clsid,tlb,values.copy(),runtime_check)))
        return dict(status='review_required',inspection_verified=True,mutation_attempted=False,
                    save_attempted=False,marker_created=False,observed={'operations':27})
    def failure(result,error):
        calls.append(('recovery_finalize',str(error)))
        return {**result,'status':'error','inspection_verified':False}
    recovery=SimpleNamespace(validate=validate,dispatch=dispatch,finalize_runtime_failure=failure)
    monkeypatch.setattr(scripts,'sw_cam_append_finish_recovery',recovery,raising=False)
    v.update(mode='recovery_inspect',failure_receipt_path='C:/job/failure.json',failure_receipt_sha256='1'*64,
             failure_marker_path='C:/job/failed_marker.json',failure_marker_sha256='2'*64)
    return env,calls,recovery,v


def test_inspect_routes_only_recovery_exact_fields_no_append(recovery_wrapper):
    env,calls,core,v=recovery_wrapper
    result=invoke(env,v)
    assert [x[0]for x in calls]==['registration','runtime','recovery_validate','target','recovery_dispatch','runtime']
    passed=next(x[1][3]for x in calls if x[0]=='recovery_dispatch')
    assert passed=={**{k:x for k,x in v.items()if k!='addin_clsid'},'qualification_only':True,'message_policy':'vendor_default'}
    assert not any(x is None for x in passed.values())
    assert result['inspection_verified'] and not result['mutation_attempted'] and not result['save_attempted'] and not result['marker_created']


def test_continue_requires_pinned_inspect_and_does_not_replay_append(recovery_wrapper):
    env,calls,core,v=recovery_wrapper
    v.update(mode='recovery_continue',inspection_receipt_path='C:/job/inspect.json',inspection_receipt_sha256='3'*64)
    invoke(env,v)
    passed=next(x[1][3]for x in calls if x[0]=='recovery_dispatch')
    assert passed['mode']=='recovery_continue' and passed['inspection_receipt_sha256']=='3'*64
    assert passed['failure_receipt_sha256']=='1'*64
    assert sum(x[0]=='recovery_dispatch'for x in calls)==1 and not any(x[0]=='dispatch'for x in calls)


@pytest.mark.parametrize('field',['failure_receipt_path','failure_receipt_sha256','failure_marker_path','failure_marker_sha256'])
def test_recovery_needs_every_failure_pin(recovery_wrapper,field):
    env,calls,core,v=recovery_wrapper;v.pop(field)
    with pytest.raises(ValidationError):invoke(env,v)
    assert not any(x[0]in ('target','dispatch','recovery_dispatch')for x in calls)


@pytest.mark.parametrize('change',[
    {'mode':'recovery_continue'},
    {'mode':'recovery_continue','inspection_receipt_path':'C:/job/inspect.json'},
    {'mode':'recovery_continue','inspection_receipt_sha256':'3'*64},
    {'inspection_receipt_path':'C:/job/inspect.json','inspection_receipt_sha256':'3'*64},
    {'mode':'append'},{'mode':'inspect'},{'mode':'recovery_continue','inspection_receipt_path':'','inspection_receipt_sha256':'3'*64},
    {'failure_receipt_sha256':'A'*64},{'generate':True},{'role':'floor'},{'save':True}])
def test_ambiguous_or_expanded_recovery_rejected(recovery_wrapper,change):
    env,calls,core,v=recovery_wrapper;v.update(change)
    with pytest.raises(ValidationError):invoke(env,v)
    assert not any(x[0]in ('target','dispatch','recovery_dispatch')for x in calls)


def test_recovery_owner_checked_before_failure_validation(recovery_wrapper):
    env,calls,core,v=recovery_wrapper;env['_selected_process_id']=124
    with pytest.raises(ValueError):invoke(env,v)
    assert not any(x[0]in ('target','recovery_validate','recovery_dispatch')for x in calls)


def test_recovery_failure_validation_precedes_native_target(recovery_wrapper):
    env,calls,core,v=recovery_wrapper
    core.validate=lambda values:(_ for _ in ()).throw(ValueError('mismatched failure'))
    with pytest.raises(ValueError,match='mismatched failure'):invoke(env,v)
    assert not any(x[0]in ('target','recovery_dispatch')for x in calls)


def test_recovery_post_runtime_failure_retains_outcome_and_dispatches_once(recovery_wrapper):
    env,calls,core,v=recovery_wrapper;n=0
    def check():
        nonlocal n
        n+=1
        if n==2:raise RuntimeError('runtime drift')
    env['_runtime_identity'].assert_current=check
    result=invoke(env,v)
    assert result['status']=='error' and result['observed']=={'operations':27}
    assert not result['mutation_attempted'] and not result['marker_created']
    assert sum(x[0]=='recovery_dispatch'for x in calls)==sum(x[0]=='recovery_finalize'for x in calls)==1


def test_recovery_real_inherited_addin_required(recovery_wrapper):
    env,calls,core,v=recovery_wrapper;v.pop('addin_clsid')
    with pytest.raises(ValidationError):invoke(env,v)
    assert not any(x[0]in ('target','recovery_dispatch')for x in calls)
