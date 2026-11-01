from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME));import scripts;scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_guide_finish_compensation as m


def setup(monkeypatch,*,generated=False,paths=None):
    state=dict(GetTlpComp=1,GetCNCComp=1,GetSpndlSpeed=4000.,GetRetractType=0,XYFeed=500.)
    target=dict(operation_native_id=324,feature_native_id=82,operation_type=1,assigned_tool={'native_id':273})
    trace=[];raw=object();doc=object();feature=object();tool=deepcopy(target['assigned_tool'])
    class NC:
        def SetCNCComp(self,value):
            trace.append(('SetCNCComp',value));state['GetCNCComp']=value;return 0
    nc=NC()
    class Guard:
        def typed(self,value,name):trace.append(('QI',name));return value
        def read(self,value,name,*args):
            trace.append(('read',name))
            if name=='GetIsToolpathGenerated':return generated
            if name=='IGetEnumToolpaths':return list(paths or [])
            if name=='IGetNCParam':return nc
            if name=='RecordCount':return value if type(value)is int else 116
            return state[name]
        def dispatch_once(self,call,persist_pending):persist_pending();return call()
    @contextmanager
    def guard():yield Guard()
    b=SimpleNamespace(doc=doc,boundary=lambda:trace.append('boundary'),target=lambda g,t:(raw,feature),ctx=SimpleNamespace(guard=guard))
    monkeypatch.setattr(m.generation,'read_generic_tool',lambda *a:(deepcopy(tool),None))
    monkeypatch.setattr(m.generation,'_items',lambda values,*a:list(values))
    return b,target,state,trace,tool


def test_one_raw_zero_setter_uses_pending_and_fresh_readback(monkeypatch):
    b,t,state,trace,_=setup(monkeypatch);before=m.read_candidate_state(b,t)
    result=m.set_raw_zero_candidate(b,t,before,lambda:trace.append('pending'))
    assert result==0 and trace.count(('SetCNCComp',0))==1
    assert trace.index('pending')<trace.index(('SetCNCComp',0))
    proof=m.verify_candidate_readback(before,m.read_candidate_state(b,t))
    assert proof['raw_zero_readback_verified']and not proof['numeric_enum_meaning_qualified']
    with pytest.raises(ValueError):m.set_raw_zero_candidate(b,t,before,lambda:trace.append('pending'))
    assert trace.count(('SetCNCComp',0))==1


@pytest.mark.parametrize('bad',['tool','target','type','offset','comp','feed','boolean','nonfinite','generated','paths'])
def test_changed_or_unsupported_state_never_dispatches(monkeypatch,bad):
    b,t,state,trace,tool=setup(monkeypatch,generated=bad=='generated',paths=[object()]if bad=='paths'else None)
    expected=deepcopy(state)
    if bad=='tool':tool['native_id']=999
    if bad=='target':t['operation_native_id']=322
    if bad=='type':t['operation_type']=True
    if bad=='offset':state['GetTlpComp']=0
    if bad=='comp':state['GetCNCComp']=0
    if bad=='feed':state['XYFeed']=600.
    if bad=='boolean':state['GetCNCComp']=True
    if bad=='nonfinite':state['XYFeed']=float('nan')
    with pytest.raises(ValueError):m.set_raw_zero_candidate(b,t,expected,lambda:trace.append('pending'))
    assert 'pending'not in trace and not any(isinstance(v,tuple)and v[0]=='SetCNCComp'for v in trace)


@pytest.mark.parametrize('key',['GetTlpComp','GetSpndlSpeed','XYFeed','GetRetractType'])
def test_readback_protects_all_observed_nontarget_nc_fields(key):
    before=dict(GetTlpComp=1,GetCNCComp=1,GetSpndlSpeed=4000.,GetRetractType=0,XYFeed=500.)
    after=dict(before,GetCNCComp=0);after[key]+=1
    with pytest.raises(ValueError):m.verify_candidate_readback(before,after)


def test_pending_failure_does_not_call_native_setter(monkeypatch):
    b,t,state,trace,_=setup(monkeypatch)
    def pending():raise OSError('durable receipt unavailable')
    with pytest.raises(OSError):m.set_raw_zero_candidate(b,t,deepcopy(state),pending)
    assert not any(isinstance(v,tuple)and v[0]=='SetCNCComp'for v in trace)