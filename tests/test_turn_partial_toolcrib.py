import os,sys,importlib.util
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import pytest
root=os.environ.get('SOLIDWORKS_SKILL_ROOT')
if root:sys.path.insert(0,root)
sys.path.insert(0,str(Path(__file__).parent))
import turn_bore_partial_fixture as fixture
spec=importlib.util.spec_from_file_location('partial_crib_test',Path(__file__).parents[1]/'scripts/sw_cam_turn_partial_toolcrib.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def partial(tmp_path):
    call,r,trace,plan=fixture.fake_run(tmp_path,fail='tool201');call();r['issue']=dict(type='COMError',hresult=-2147220990)
    return r,plan


def test_exact_first_bore_partial_is_observation_only(tmp_path):
    r,plan=partial(tmp_path);s=m.validate_partial(r,plan['catalogue'],plan['roles'])
    assert s['inventory']['operation_count']==10 and s['operations'][6]['turn_operation_type']==5
    assert len(r['actions'])==1 and r['readback_verified'] is False and r['model_saved'] is False

@pytest.mark.parametrize('bad',['wrong_scope','success','wrong_phase','wrong_hresult','mutation_false','pending','save','second','returned_false','verified_true','wrong_bore_type','wrong_id','path_drift','tool_observed','event','cleanup','completed_after'])
def test_other_partial_or_completed_states_cannot_authorize_reader(tmp_path,bad):
    r,plan=partial(tmp_path)
    if bad=='wrong_scope':r['scope']='other'
    elif bad=='success':r['status']='created_bore_pair_ram_no_save'
    elif bad=='wrong_phase':r['failed_phase']='InsertOperation_rough_bore'
    elif bad=='wrong_hresult':r['issue']['hresult']=-2147417851
    elif bad=='mutation_false':r['mutation_attempted']=False
    elif bad=='pending':r['native_dispatch_pending']=True
    elif bad=='save':r['model_saved']=True
    elif bad=='second':r['actions']['InsertOperation_finish_bore']={}
    elif bad=='returned_false':r['actions']['InsertOperation_rough_bore']['returned']=False
    elif bad=='verified_true':r['actions']['InsertOperation_rough_bore']['readback_verified']=True
    elif bad=='wrong_bore_type':r['new_operations'][0]['turn_operation_type']=1
    elif bad=='wrong_id':r['actions']['InsertOperation_rough_bore']['new_native_id']=999
    elif bad=='path_drift':r['insertion_observations'][0]['inventory']['operations'][0]['toolpath_record_counts']=[99]
    elif bad=='tool_observed':r['tool_reference_observations']=[{}]
    elif bad=='event':r['messages']['event_count']=1
    elif bad=='cleanup':r['cleanup_issue']={}
    elif bad=='completed_after':r['after']={}
    with pytest.raises(ValueError):m.validate_partial(r,plan['catalogue'],plan['roles'])


def test_completed_pair_loader_stays_strict(tmp_path):
    r,plan=partial(tmp_path)
    with pytest.raises(ValueError):m.parent.validate_created(r,plan['catalogue'],plan['roles'])


def test_native_start_accepts_exact_observed_dirty_state(monkeypatch):
    trace=[];document=dict(needs_save=True,path='part')
    class Session:
        def __init__(self,*a):pass
        def __enter__(self):trace.append('events')
    monkeypatch.setattr(m.common,'_check',lambda _:None)
    monkeypatch.setattr(m,'_member',lambda obj,name,*a:trace.append(name) or object())
    monkeypatch.setattr(m,'_typed',lambda obj,*a:obj)
    monkeypatch.setattr(m.reader.prior.events,'CamMessageSession',Session)
    fake=SimpleNamespace(identity=lambda:deepcopy(document),plan=dict(reference=dict(document=deepcopy(document)),pins=[],catalogue=dict(request=dict(addin_clsid='clsid'))),sw=object(),typelib='tlb',boundary=lambda:trace.append('boundary'))
    m.NativeBackend.start(fake);assert fake.active and trace==['GetAddInObject','GetCWApp','events','boundary']
    document['needs_save']=False
    with pytest.raises(ValueError):m.NativeBackend.start(fake)


def test_reused_reader_has_no_operation_tool_lookup(monkeypatch):
    state=dict(inventory=dict(operation_count=10));r=dict(phase='prepared',tools=[]);trace=[]
    class Backend:
        def start(self):trace.append('start')
        def capture(self,label):trace.append(label);return deepcopy(state)
        def tools(self):trace.append('toolcrib');return [10,11]
        def finish(self):trace.append('finish')
        def close(self):trace.append('close')
    out=m.reader.run_backend(Backend(),dict(reference=state),r,lambda:None)
    assert out['status']=='observed' and trace==['start','before','toolcrib','after','finish','close']
