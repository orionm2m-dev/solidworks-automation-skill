from copy import deepcopy
from types import SimpleNamespace
import hashlib
import pytest
from optimization_fixture import fixture
from scripts import sw_cam_local_optimization_native as m
from scripts import sw_cam_dispatch_guard as guard_module

def real_guard(tmp_path,monkeypatch,calls):
    source=tmp_path/'part.sldprt';source.write_bytes(b'synthetic')
    g=guard_module.ScopedCamDispatchGuard(None,'synthetic-metadata',process_id=123,expected_document={'path':str(source),'title':source.name,'type':1,'needs_save':False},source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),evidence_pins=[dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest())],verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None)
    g._identity=lambda:None
    def typed(obj,name,path):calls.append('QI:'+name);return obj
    monkeypatch.setattr(guard_module,'_typed',typed)
    monkeypatch.setattr(guard_module,'_member',lambda obj,name,*args:False)
    return g

def backend():
    _,snap,targets,plan=fixture();b=object.__new__(m.NativeBackend)
    b.report={'configured':snap};b.loaded={'optimization_plan':plan};b.learned=targets
    b.target=lambda g,t:(object(),object())
    b.outcome=lambda t:dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],background_over_before=False,background_over_after=False,generated=True,generated_for_feature=True,record_counts=[117])
    b._read_existing_nc=lambda g,t:deepcopy(snap['parameters'][8]['nc']['feeds_compensation'])
    return b,targets

def test_real_guard_gtp_prebind_before_pending_false_diagnostic(tmp_path,monkeypatch):
    calls=[];g=real_guard(tmp_path,monkeypatch,calls);b,targets=backend();b.ctx=SimpleNamespace(guard=lambda:g,app=object())
    monkeypatch.setattr(m,'_member',lambda obj,name:calls.append(name)or 0)
    assert b.generate(targets[0],lambda:calls.append('pending'))==0
    assert calls==['QI:ICWMillOperation','pending','GenerateToolpath']
    assert g.summary()['native_call_attempted']and g.summary()['native_call_returned']
    with pytest.raises(ValueError):g.dispatch_once(lambda:0,persist_pending=lambda:None)

def test_real_guard_fincut_raw_property_before_pending(tmp_path,monkeypatch):
    calls=[];g=real_guard(tmp_path,monkeypatch,calls);b,targets=backend();b.ctx=SimpleNamespace(guard=lambda:g)
    owner=SimpleNamespace(_ICWRghMillOp__com__set_FinCutAmt=lambda value:calls.append(('FinCutAmt',value))or 0)
    b.owner=lambda scope,t,spec:(scope.typed(owner,'ICWRghMillOp'),object(),'ICWRghMillOp')
    assert b.set_field(targets[0],m.fields.ROUGH_SPECS[2],0.,lambda:calls.append('pending'))==0
    assert calls==['QI:ICWRghMillOp','pending',('FinCutAmt',0.)]

@pytest.mark.parametrize('value',[.25,False,float('nan')])
def test_unsealed_final_depth_never_dispatches(value):
    b,targets=backend()
    with pytest.raises(ValueError):b.set_field(targets[0],m.fields.ROUGH_SPECS[2],value,lambda:pytest.fail('native claim'))

def test_forbidden_mutators_remain_unavailable():
    b,_=backend()
    for name in ['insert','assign','set_nc']:
        with pytest.raises(ValueError):getattr(b,name)()

@pytest.mark.parametrize('field,value',[('XYFeed',70.),('GetSpndlSpeed',8000.),('GetCNCComp',1)])
def test_nc_mismatch_never_claims(tmp_path,monkeypatch,field,value):
    calls=[];g=real_guard(tmp_path,monkeypatch,calls);b,targets=backend();b.ctx=SimpleNamespace(guard=lambda:g,app=object())
    nc=deepcopy(b.report['configured']['parameters'][8]['nc']['feeds_compensation']);nc[field]=value;b._read_existing_nc=lambda *a:nc
    with pytest.raises(ValueError):b.generate(targets[0],lambda:pytest.fail('pending'))
    assert not g.summary()['native_call_attempted']
