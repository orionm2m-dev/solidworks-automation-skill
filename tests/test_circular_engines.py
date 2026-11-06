from copy import deepcopy
from pathlib import Path
import json,ast
import pytest
from scripts import sw_cam_current_circular_authority as a
from scripts import sw_cam_current_saved_parameter_batch as batch
from scripts import sw_cam_current_saved_generation as g
from scripts import sw_cam_current_saved_parameter_fields as fields
from test_circular_continuation import completed,config_values,configured_after,pin
from test_current_saved_parameter_fields import actual_change
from test_current_saved_generation_engine import Backend


@pytest.fixture
def circular_engine(completed,monkeypatch):
    v,data,recipe=config_values(completed);calls=[];control=dict(fail=None);root=completed['path'];marker=root/'once.json'
    def validate(values,clsid=None):
        if marker.exists():raise ValueError('No replay')
        got=deepcopy(data)
        if values['action']=='apply':got['prepare']=json.loads((root/'prepare.json').read_text())
        return marker,got
    monkeypatch.setattr(batch,'validate',validate)
    monkeypatch.setattr(batch.current,'_abi',lambda *_:None);monkeypatch.setattr(batch.parameters,'preflight',lambda *_:None);monkeypatch.setattr(batch.fields,'preflight',lambda *_:None);monkeypatch.setattr(batch.append,'save_abi',lambda *_:None)
    class Session:
        def summary(self):return dict(active=False,subscribed=True,disconnected=True,event_count=0)
    class Context:
        def __init__(self,sw,clsid,tlb,args,loaded,report,persist,runtime):self.state=deepcopy(data['baseline']);self.report=report;self.persist=persist;self.session=Session();self.source='b'*64
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def boundary(self):
            if control['fail']=='event_seen':raise ValueError('event stop')
            return self.state['document']
        def identity(self):return self.state['document']
        def capture(self,label,consumers):
            self.boundary();assert consumers==self.state['parameter_batch']['candidate_consumer_ids'];self.report[label]=deepcopy(self.state);self.report['captures'].append(label);self.persist();return self.report[label]
        def set_tool(self,row,candidate,pending,returned):
            pending();calls.append('SetTool');self.state=fields.expected_assignment_state(self.state,row,candidate);self.state['document']['needs_save']=True;self.state['sketch_state']['needs_save']=True;returned(0)
            if control['fail']=='tool_nc':self.state['parameter_batch']['target_nc']['13']['feeds_compensation']['XYFeed']=0.
        def set_field(self,row,change,pending,returned):
            pending();calls.append(change['field']);actual_change(self.state['operation_parameters'][0],change['field'],change['new'])
            if change['field']=='floor_allowance':fields._replace_observed(self.state['operation_parameters'][0],'depth','DepthAllow',change['new'])
            returned(0)
            if control['fail']=='event':control['fail']='event_seen';self.boundary()
        def read_field(self,row,change,diagnostic):
            value=fields.field_value(self.state['operation_parameters'][0],change['field']);diagnostic.update(returned=True,raw=dict(recorded=True,raw=value));self.persist();return value
        def save(self,pending,returned):
            pending();calls.append('Save');returned(None if control['fail']=='save_unknown' else 0)
            if control['fail']=='save_unknown':raise ValueError('Unknown native Save result')
            self.source='c'*64;self.state['document']['needs_save']=False;self.state['sketch_state'].update(needs_save=False,saved_file_sha256=self.source);self.report['source_after_sha256']=self.source
    def run(action):
        args=dict(v,action=action,save_after_verified=action=='apply',receipt_path=str(root/(action+'.json')))
        result=batch.run_current_saved_configuration(None,'clsid','tlb',runtime_check=lambda:None,_context_factory=Context,**args)
        return batch.runtime_finish(result)
    return dict(run=run,control=control,calls=calls,root=root,v=v,data=data)


def test_circular_prepare_apply_loader_and_generation_chain(circular_engine,completed):
    e=circular_engine;prep=e['run']('prepare');assert prep['readback_verified'],prep
    configured=e['run']('apply');assert configured['model_saved'] and configured['parameter_delta_verified'],configured
    assert e['calls']==['SetTool','side_allowance','floor_allowance','first_depth','Save']
    cp=pin(e['root']/'configured.json',configured)
    loaded=a.load_configured(cp['path'],cp['sha256'],process_id=123,source_path=e['v']['expected_document_path'],source_sha256='c'*64,selected_ids=[13])
    class CircularBackend(Backend):
        def __init__(self):super().__init__();self.value=deepcopy(loaded['state']);self.source='c'*64
        def generate(self,oid,prior,*,pending,returned):
            super().generate(oid,prior,pending=pending,returned=returned);self.value['sketch_state']['needs_save']=True
        def save(self,*,returned):
            result=super().save(returned=returned);self.value['sketch_state'].update(needs_save=False,saved_file_sha256='d'*64);return result
        def adopt_saved_source(self,report):self.source='d'*64;return self.source
    backend=CircularBackend();report={};j=g.Journal(e['root']/'generated.json',e['root']/'gtp_once.json',report);g.run_once(backend,j,loaded)
    assert report['readback_verified'] and report['model_saved'],report
    assert backend.calls.count('gtp')==backend.calls.count('save')==backend.calls.count('preCL')==backend.calls.count('postCL')==1
    assert report['CL_preservation']['protected_operation_native_ids']==[12]
    assert report['saved']['reference_parameter_observation']==loaded['state']['reference_parameter_observation']
    assert e['run']('apply')['status']=='error' and e['calls'].count('SetTool')==1


@pytest.mark.parametrize('failure',['tool_nc','event','save_unknown'])
def test_circular_partial_keeps_returned_and_blocks_followup(circular_engine,failure):
    e=circular_engine;assert e['run']('prepare')['readback_verified'];e['control']['fail']=failure;result=e['run']('apply')
    assert result['status']=='uncertain' and not result['model_saved']
    assert result['actions'][0]['returned'] and (e['root']/'once.json').exists()
    if failure=='tool_nc':assert e['calls']==['SetTool']
    elif failure=='event':assert e['calls']==['SetTool','side_allowance']
    else:assert result['actions'][-1]['return_type']=='NoneType'
    assert e['run']('apply')['status']=='error'


def schema_classes(monkeypatch):
    source=Path(__file__).parents[1]/'server_nodes.py'
    if not source.is_file():
        from test_mcp_cam_operation_diagnostics import server
        monkeypatch.setattr(a,'validate',lambda *args:None)
        return server.SolidWorksCamCircularConfigurationInput
    from pydantic import BaseModel,Field,ConfigDict,model_validator
    from typing import Literal,Optional,Annotated
    class Target(BaseModel):
        addin_clsid:str
        expected_document_path:str
        expected_document_title:Optional[str]=None
        response_format:str='json'
    ns=dict(BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,model_validator=model_validator,Literal=Literal,Optional=Optional,Annotated=Annotated,SolidWorksCamTargetInput=Target)
    tree=ast.parse((Path(__file__).parents[1]/'server_nodes.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node,ast.ClassDef):exec(compile(ast.Module(body=[node],type_ignores=[]),'staged_schema','exec'),ns)
    monkeypatch.setattr(a,'validate',lambda *args:None)
    return ns['SolidWorksCamCircularConfigurationInput']


@pytest.mark.parametrize('defect',[None,'extra','boolean_id','wrong_mode','two_targets','arbitrary_dependency','bool_dependency','private_limit'])
def test_explicit_circular_schema_no_compound_masquerade(completed,monkeypatch,defect):
    v,_,_=config_values(completed);v.update(addin_clsid=completed['loaded']['addin_clsid'])
    if defect=='extra':v['current_read_request_path']='fake'
    elif defect=='boolean_id':v['expected_feature_native_id']=True
    elif defect=='wrong_mode':v['configuration_mode']='current_saved'
    elif defect=='two_targets':v['parameter_operation_native_ids']=[13,14]
    elif defect=='arbitrary_dependency':v['dependent_readbacks'][0]['member']='Anything'
    elif defect=='bool_dependency':v['dependent_readbacks'][0]['expected']=True
    elif defect=='private_limit':v['_native_read_limit']=100000
    cls=schema_classes(monkeypatch)
    if defect is None:assert cls.model_validate(v).configuration_mode==a.MODE
    else:
        with pytest.raises(ValueError):cls.model_validate(v)


@pytest.mark.parametrize('limit',[None,48000])
def test_native_read_budget_default_retained_explicit_circular_bound(monkeypatch,limit):
    ctx=object.__new__(batch.NativeBatchContext);ctx.report=dict(native_read_count=(limit or 24000)-1);ctx.check=lambda:None;calls=[]
    if limit is not None:ctx._native_read_limit=limit
    monkeypatch.setattr(batch,'_member',lambda *args:calls.append(args) or 0)
    assert ctx.read(None,'getter')==0 and len(calls)==1
    with pytest.raises(ValueError,match='budget'):ctx.read(None,'getter')
    assert len(calls)==1


def test_native_circular_limit_is_fixed_internal_not_request(completed):
    from scripts.sw_cam_current_circular_context import NativeCircularContext
    request=deepcopy(completed['v']);request['_native_read_limit']=100000
    context=NativeCircularContext(None,'clsid','tlb',request,completed['loaded'],{},lambda:None,lambda:None)
    assert context._native_read_limit==48000
