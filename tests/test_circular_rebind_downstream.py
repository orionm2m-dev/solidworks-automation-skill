"""Portable offline cross-session lineage tests; native calls are synthetic."""
from copy import deepcopy
from pathlib import Path
import ast,json
import pytest
from scripts import sw_cam_current_circular_authority as a
from scripts import sw_cam_circular_session_rebind as rebind
from scripts.sw_cam_current_circular_continuation import CircularBatchContext,CircularGenerationContext
from test_circular_continuation import completed,config_values,pin
from test_circular_engines import circular_engine

ROOT=Path(__file__).parents[1]

def association(completed,values):
    h=completed['load']();old=deepcopy(h['state']);state=deepcopy(old);state['sketch_state']['pid']=456
    path=completed['path']/'rebind.json'
    v=dict(process_id=456,expected_process_create_time=200.5,expected_document_path=values['expected_document_path'],expected_source_sha256='b'*64,pocket_receipt_path=h['pin']['path'],pocket_receipt_sha256=h['pin']['sha256'],expected_feature_native_id=22,expected_operation_native_id=13,expected_operation_native_ids=[x['native_id'] for x in state['operations']],expected_generated_operation_count=sum(x['toolpath_generated'] for x in state['operations']),expected_total_record_count=sum(sum(x['toolpath_record_counts']) for x in state['operations']),receipt_path=str(path))
    doc=dict(scope=rebind.SCOPE,status='observed',phase='finished',request=v,historical_pocket_pin=h['pin'],historical_process_id=123,historical_process_create_time=100.25,process_id=456,expected_process_create_time=200.5,source_sha256='b'*64,historical_receipt_modified=False,mutation_attempted=False,save_attempted=False,GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,production_qualified=False,session_rebind_verified=True,readback_verified=True,runtime_unchanged=True,module_sha256=rebind._file_hash(rebind.__file__),before=state,after=deepcopy(state),state_sha256=a._digest(state),messages=dict(active=False,subscribed=True,disconnected=True,event_count=0),test_only_synthetic_native_observation=True)
    p=pin(path,doc)
    values.update(process_id=456,expected_process_create_time=200.5,session_rebind_receipt_path=p['path'],session_rebind_receipt_sha256=p['sha256'])
    return values,doc,h

@pytest.fixture
def rebound(completed):
    v,_,_=config_values(completed);return association(completed,v)

def test_verified_new_owner_keeps_original_authority_and_raw_history(rebound):
    v,d,h=rebound;before=Path(h['pin']['path']).read_bytes();data=a.load_inputs(v)
    assert data['circular']['binding']['process_id']==123
    assert data['circular']['current_owner']==dict(process_id=456,expected_process_create_time=200.5)
    assert data['baseline']['sketch_state']['pid']==456
    assert data['circular']['original']==h['original']
    assert data['protected_pins']['session_rebind']['sha256']==v['session_rebind_receipt_sha256']
    assert Path(h['pin']['path']).read_bytes()==before
    assert a.binding(v)['session_rebind_receipt_sha256']==v['session_rebind_receipt_sha256']

@pytest.mark.parametrize('defect',['no_pin','one_pin','wrong_sha','old_pid','other_pid','wrong_lifetime','other_pocket','forged_flag','wrong_raw_pid','stale_module','changed_tool'])
def test_reject_forged_stale_cross_session_authority(rebound,defect):
    v,d,h=rebound
    if defect=='no_pin':v.pop('session_rebind_receipt_path');v.pop('session_rebind_receipt_sha256')
    elif defect=='one_pin':v.pop('session_rebind_receipt_sha256')
    elif defect=='wrong_sha':v['session_rebind_receipt_sha256']='e'*64
    elif defect=='old_pid':v['process_id']=123
    elif defect=='other_pid':v['process_id']=789
    elif defect=='wrong_lifetime':v['expected_process_create_time']+=1
    elif defect=='other_pocket':
        other=pin(Path(v['pocket_receipt_path']).with_name('different_pocket.json'),h['receipt']);v.update(pocket_receipt_path=other['path'],pocket_receipt_sha256=other['sha256'])
    else:
        if defect=='forged_flag':d['session_rebind_verified']=False
        elif defect=='wrong_raw_pid':d['after']['sketch_state']['pid']=789
        elif defect=='stale_module':d['module_sha256']='e'*64
        elif defect=='changed_tool':d['after']['operations'][-1]['assigned_tool']['native_id']=999
        p=pin(Path(v['session_rebind_receipt_path']),d);v['session_rebind_receipt_sha256']=p['sha256']
    with pytest.raises((ValueError,AssertionError)):a.load_inputs(v)

def test_old_binding_digest_unchanged_by_null_optional_pair(completed):
    v,_,_=config_values(completed);old=a.binding(v);v.update(session_rebind_receipt_path=None,session_rebind_receipt_sha256=None)
    assert a.binding(v)==old and a._digest(a.binding(v))==a._digest(old)

def test_context_updates_only_live_identity(rebound):
    v,d,h=rebound;data=a.load_inputs(v);immutable=deepcopy(data['circular'])
    c=CircularBatchContext(None,'clsid','unused',v,data,dict(native_read_count=0),lambda:None,lambda:None)
    assert c.v['process_id']==c.request['process_id']==456
    assert c.v['expected_process_create_time']==c.request['expected_process_create_time']==200.5
    assert data['circular']==immutable and c.loaded==h['original']
    loaded=dict(circular=data['circular'],pin=data['pins']['pocket'],pins=data['protected_pins'],state=data['baseline'])
    g=CircularGenerationContext(None,'clsid','unused',v,loaded,dict(native_read_count=0),lambda:None,lambda:None)
    assert g.v['process_id']==g.request['process_id']==456
    assert data['circular']==immutable

@pytest.mark.parametrize('field,value',[('process_id',789),('expected_process_create_time',200.6)])
def test_context_rejects_mismatched_explicit_owner(rebound,field,value):
    v,d,h=rebound;data=a.load_inputs(v);v[field]=value
    with pytest.raises(ValueError,match='Current owner'):CircularBatchContext(None,'clsid','unused',v,data,{},lambda:None,lambda:None)

def test_full_configure_save_then_generation_loader_new_session(circular_engine,completed):
    e=circular_engine;v,d,h=association(completed,e['v']);data=a.load_inputs(v);e['data'].clear();e['data'].update(data)
    oldbytes=Path(h['pin']['path']).read_bytes()
    assert e['run']('prepare')['readback_verified']
    applied=e['run']('apply');assert applied['model_saved'] and applied['parameter_delta_verified'],applied
    p=pin(e['root']/'configured_rebound.json',applied)
    # The physical file has crossed Save: source loading must follow the pinned lineage.
    Path(v['expected_document_path']).write_bytes(b'synthetic post-save source')
    loaded=a.load_configured(p['path'],p['sha256'],process_id=456,source_path=v['expected_document_path'],source_sha256='c'*64,selected_ids=[13])
    assert loaded['state']['sketch_state']['pid']==456 and loaded['source_sha256']=='c'*64
    assert loaded['circular']['binding']['process_id']==123
    assert loaded['circular']['current_owner']['process_id']==456
    assert loaded['binding']['session_rebind_receipt_sha256']==v['session_rebind_receipt_sha256']
    assert Path(h['pin']['path']).read_bytes()==oldbytes
    assert e['calls']==['SetTool','side_allowance','floor_allowance','first_depth','Save']
    assert e['run']('apply')['status']=='error'

def test_schema_optional_pair_and_exact_types(monkeypatch,completed):
    from pydantic import BaseModel,Field,ConfigDict,model_validator
    from typing import Literal,Optional,Annotated
    class Target(BaseModel):
        addin_clsid:str='clsid'
        expected_document_title:Optional[str]=None
        response_format:str='json'
    ns=dict(BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,model_validator=model_validator,Literal=Literal,Optional=Optional,Annotated=Annotated,SolidWorksCamTargetInput=Target)
    source=(ROOT/'mcp-server/server.py').read_text('utf-8-sig');tree=ast.parse(source)
    selected=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in {'SolidWorksCamCircularDependentReadback','SolidWorksCamCircularConfigurationInput'}]
    assert len(selected)==2
    exec(compile(ast.Module(body=selected,type_ignores=[]),'installed_schema','exec'),ns)
    cls=ns['SolidWorksCamCircularConfigurationInput'];v,_,_=config_values(completed)
    monkeypatch.setattr(a,'validate',lambda x,*args:a.rebind_options(x))
    assert cls.model_validate(v).session_rebind_receipt_path is None
    v['session_rebind_receipt_path']=str(completed['path']/'rebind.json')
    with pytest.raises(ValueError):cls.model_validate(v)
    v['session_rebind_receipt_sha256']='a'*64;assert cls.model_validate(v).session_rebind_receipt_sha256=='a'*64
    v['session_rebind_receipt_path']=True
    with pytest.raises(ValueError):cls.model_validate(v)






def reader_nodes(monkeypatch,fail_after=False,selected=456):
    from pydantic import BaseModel,Field,ConfigDict,model_validator
    from typing import Literal,Optional,Annotated
    class Target(BaseModel):
        addin_clsid:str='clsid'
        expected_document_title:Optional[str]=None
        response_format:str='json'
    class Registry:
        def tool(self,**kw):return lambda f:f
    class Runtime:
        count=0
        def assert_current(self):
            self.count+=1
            if fail_after and self.count==2:raise ValueError('changed runtime')
    calls=[];runtime=Runtime()
    def target(params):calls.append('target');return object(),dict(clsid='clsid',addin_path='C:/cam/test.dll')
    ns=dict(BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,model_validator=model_validator,Literal=Literal,Optional=Optional,Annotated=Annotated,SolidWorksCamTargetInput=Target,mcp=Registry(),Path=Path,_runtime_identity=runtime,_selected_process_id=selected,_cam_target=target,_run_locked=lambda f,*args:f())
    monkeypatch.setattr(rebind,'validate',lambda v:calls.append(('validate',deepcopy(v))))
    def run(sw,clsid,tlb,**v):
        calls.append(('run',v));result=dict(status='observed',phase='finished',session_rebind_verified=True,readback_verified=True,runtime_unchanged=True)
        Path(v['receipt_path']).write_text(json.dumps(result));return result
    monkeypatch.setattr(rebind,'run_rebind',run)
    source=(ROOT/'mcp-server/server.py').read_text('utf-8-sig');tree=ast.parse(source)
    selected=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in {'SolidWorksCamCircularSessionRebindInput','solidworks_cam_rebind_saved_circular_session'}]
    assert len(selected)==2
    exec(compile(ast.Module(body=selected,type_ignores=[]),'installed_reader_nodes','exec'),ns)
    return ns,calls

@pytest.mark.parametrize('case',['good','wrong_connected_pid','runtime_drift','bool_pid','extra_field'])
def test_reader_wrapper_exact_binding_and_durable_failure(monkeypatch,tmp_path,case):
    ns,calls=reader_nodes(monkeypatch,case=='runtime_drift',999 if case=='wrong_connected_pid' else 456)
    values=dict(process_id=456,expected_process_create_time=200.5,expected_document_path=str(tmp_path/'a.SLDPRT'),expected_source_sha256='b'*64,pocket_receipt_path=str(tmp_path/'pocket.json'),pocket_receipt_sha256='c'*64,expected_feature_native_id=22,expected_operation_native_id=13,expected_operation_native_ids=[10,11,12,13],expected_generated_operation_count=1,expected_total_record_count=100,receipt_path=str(tmp_path/'result.json'))
    if case=='bool_pid':values['process_id']=True
    elif case=='extra_field':values['arbitrary_method']='Save'
    cls=ns['SolidWorksCamCircularSessionRebindInput'];call=ns['solidworks_cam_rebind_saved_circular_session']
    if case in ('bool_pid','extra_field'):
        with pytest.raises(ValueError):cls.model_validate(values)
        return
    params=cls.model_validate(values)
    if case=='wrong_connected_pid':
        with pytest.raises(ValueError,match='connected'):call(params)
        assert 'target' not in calls;return
    result=call(params)
    assert result['session_rebind_verified'] is (case=='good')
    assert json.loads(Path(values['receipt_path']).read_text())==result
    passed=next(x[1] for x in calls if type(x) is tuple and x[0]=='run')
    assert passed['process_id']==456 and callable(passed['runtime_check'])
    assert not {'addin_clsid','response_format','expected_document_title'} & passed.keys()
