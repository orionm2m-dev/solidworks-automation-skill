import os,sys,importlib.util
from pathlib import Path
from copy import deepcopy
import pytest
root=os.environ.get('SOLIDWORKS_SKILL_ROOT')
if root:sys.path.insert(0,root)
spec=importlib.util.spec_from_file_location('init_reconcile_test',Path(__file__).parents[1]/'scripts/sw_cam_turn_bore_initialization_reconcile.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def event_ok():return dict(active=False,subscribed=True,disconnected=True,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])


def fixture():
    a=dict(operation_native_id=201,operation_type=5,feature_native_id=70,tool_native_id=301)
    state=dict(document=dict(needs_save=True,path='part'),inventory=dict(operation_count=10,paths=[[40],[19],[97],[43]]))
    tools=[dict(native_id=301,complete=True)];candidate=tools[0]
    plan=dict(assignment=a,reference=state,candidate=candidate,observed=dict(tools=tools))
    r=dict(scope=m.initializer.SCOPE,status='uncertain',phase='finished',failed_phase='SetTool_201',mutation_attempted=True,readback_verified=False,issue=dict(type='COMError',hresult=-2147417851),native_dispatch_pending=True,actions=dict(SetTool_201=dict(attempted=True,pending=True,returned=False,readback_verified=False)),messages=event_ok(),assignment=deepcopy(a),accepted_candidate=deepcopy(candidate),before=deepcopy(state),tools_before=deepcopy(tools),**{k:False for k in m.initializer.FORBIDDEN})
    return r,plan


def test_exact_uncertain_initializer_accepts_read_only_observation():
    r,p=fixture();assert m.validate_failed(r,p)==p['assignment'];assert not r['readback_verified'] and r['issue']['hresult']==-2147417851

@pytest.mark.parametrize('bad',['scope','status','phase','failed_phase','not_mutated','completed','hresult','type','not_pending','extra_action','returned','save','insert','retry','after','reference','tools_after','cleanup','event','wrong_tool','candidate','route','tools'])
def test_other_states_cannot_authorize_reconciliation(bad):
    r,p=fixture()
    if bad=='scope':r['scope']='other'
    elif bad=='status':r['status']='initialized_ram_no_save'
    elif bad=='phase':r['phase']='running'
    elif bad=='failed_phase':r['failed_phase']='immediate_tool_reference'
    elif bad=='not_mutated':r['mutation_attempted']=False
    elif bad=='completed':r['readback_verified']=True
    elif bad=='hresult':r['issue']['hresult']=-2147220990
    elif bad=='type':r['issue']['type']='ValueError'
    elif bad=='not_pending':r['native_dispatch_pending']=False
    elif bad=='extra_action':r['actions']['SetTool_202']={}
    elif bad=='returned':r['actions']['SetTool_201']['returned']=True
    elif bad=='save':r['model_saved']=True
    elif bad=='insert':r['operation_inserted']=True
    elif bad=='retry':r['automatic_retry']=True
    elif bad=='after':r['after']={}
    elif bad=='reference':r['reference_after']={}
    elif bad=='tools_after':r['tools_after']=[]
    elif bad=='cleanup':r['cleanup_error']={}
    elif bad=='event':r['messages']['event_count']=1
    elif bad=='wrong_tool':r['assignment']['tool_native_id']=999
    elif bad=='candidate':r['accepted_candidate']['native_id']=999
    elif bad=='route':r['before']['inventory']['paths'][0]=[999]
    elif bad=='tools':r['tools_before'][0]['complete']=False
    with pytest.raises(ValueError):m.validate_failed(r,p)


def test_exact_existing_native_reader_is_reused():
    assert m.NativeBackend is m.reader.NativeBackend


def test_reused_flow_performs_one_observation_without_mutation():
    failed,p=fixture();r=dict(phase='prepared');trace=[]
    class Backend:
        def start(self):trace.append('start')
        def capture(self,label):trace.append(label);return deepcopy(p['reference'])
        def observe_reference(self,a):trace.append('IGetTool');assert a==p['assignment'];return dict(binding_determined=True,tool_native_id=301,outcome='desired_tool_reference_observed')
        def finish(self):trace.append('finish')
        def close(self):trace.append('close')
    out=m.reader.run_backend(Backend(),p,r,lambda:None)
    assert out['status']=='observed' and out['protected_route_unchanged'] and trace==['start','before','IGetTool','after','finish','close']
    assert failed['status']=='uncertain'


def test_reused_reader_does_not_turn_unavailable_into_null():
    class Unavailable(Exception):hresult=-2147220990
    calls=[];observations=[]
    def read(*a):calls.append(a);raise Unavailable('unavailable')
    result=m.reader.read_reference(object(),object(),301,read=read,typed=lambda *a:None,publish=lambda v:observations.append(deepcopy(v)))
    assert len(calls)==1 and result['binding_determined'] is False and result['outcome']=='tool_reference_unavailable'


def test_new_rpc_read_error_is_not_accepted_or_retried():
    class Fault(Exception):hresult=-2147417851
    calls=[]
    def read(*a):calls.append(a);raise Fault('fault')
    with pytest.raises(Fault):m.reader.read_reference(object(),object(),301,read=read,typed=lambda *a:None,publish=lambda v:None)
    assert len(calls)==1
