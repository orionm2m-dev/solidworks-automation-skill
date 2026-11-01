import importlib.util,json,sys,time
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
import pytest
from test_cam_inprocess_reader import fixture,Fake,m
sys.modules['scripts.sw_cam_inprocess_reader']=m
spec=importlib.util.spec_from_file_location('host_load',Path(__file__).parents[1]/'scripts/sw_cam_inprocess_host_load.py');loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)

class LoadFake(Fake):
    def __init__(self,p,v):super().__init__(p,v);self.loaded=False;self.diagnostic_mode='valid';self.load_result=0;self.qi=True
    def document(self):return deepcopy(self.payload['document_before'])
    def diagnostics(self):
        if not self.loaded:return None
        stamp=datetime.now(timezone.utc).isoformat()
        d=dict(status='connected',hostProcessId=self.p['process_id'],hostProcessName='SLDWORKS',addinGuid=m.HOST_CLSID,callbackRegistered=True,commandGroupReady=True,taskPaneReady=True,propertyManagerPageReady=True,errors=[],connectedAtUtc=stamp,lastUpdatedUtc=stamp)
        if self.diagnostic_mode=='wrong_pid':d['hostProcessId']+=1
        if self.diagnostic_mode=='stale':d['connectedAtUtc']='2020-01-01T00:00:00+00:00'
        if self.diagnostic_mode=='disconnected':d['status']='disconnected'
        if self.diagnostic_mode=='partial':d['taskPaneReady']=False
        if self.diagnostic_mode=='errors':d['errors']=['error']
        if self.diagnostic_mode=='absent':return None
        return dict(data=d,sha256='new',path='host-status.json')
    def load_once(self):self.calls+=1;self.loaded=True;return self.load_result
    def verify_reader_interface(self):return dict(qualified_interface=self.qi,cam_reader_called=False,interface_iid=m.READER_IID)


def params(p):return dict(p,acknowledge_host_load=True)

def test_one_load_with_connected_proof_and_unchanged_document(fixture):
    p,v=fixture;b=LoadFake(p,v);r=loader.run_load(params(p),backend=b)
    assert r['status']=='observed' and r['readback_verified'] and b.calls==1
    assert r['document_before']==r['document_after'] and r['owner_before']==r['owner_after']
    assert not r['loaded_mvid_verified'] and not r['model_saved'] and not r['cam_reader_called']
    assert r['document_unchanged_verified'] and not r['model_change_requested'] and 'model_modified' not in r

@pytest.mark.parametrize('mode',['wrong_pid','stale','disconnected','partial','errors','absent'])
def test_zero_return_does_not_prove_success(fixture,mode):
    p,v=fixture;b=LoadFake(p,v);b.diagnostic_mode=mode;r=loader.run_load(params(p),backend=b)
    assert r['load_result']==0 and r['status']=='error' and not r['readback_verified'] and b.calls==1

@pytest.mark.parametrize('value',[True,False,1,None])
def test_nonzero_or_noninteger_load_result_rejected(fixture,value):
    p,v=fixture;b=LoadFake(p,v);b.load_result=value;r=loader.run_load(params(p),backend=b)
    assert r['status']=='error' and b.calls==1

def test_qi_required(fixture):
    p,v=fixture;b=LoadFake(p,v);b.qi=False;r=loader.run_load(params(p),backend=b);assert r['status']=='error' and b.calls==1

def test_load_unknown_result_never_replayed(fixture):
    p,v=fixture;b=LoadFake(p,v)
    def fail():b.calls+=1;raise RuntimeError('Load fault')
    b.load_once=fail;r=loader.run_load(params(p),backend=b);assert r['status']=='error' and r['native_dispatch_pending'] and b.calls==1
    with pytest.raises(ValueError):loader.run_load(params(p),backend=b)
    assert b.calls==1

def test_changed_document_after_load_caught(fixture):
    p,v=fixture;b=LoadFake(p,v);base=b.document
    def doc():
        d=base()
        if b.loaded:d['configuration']='Other'
        return d
    b.document=doc;r=loader.run_load(params(p),backend=b);assert r['status']=='error' and b.calls==1
    assert not r['document_unchanged_verified'] and 'model_modified' not in r

def test_connected_owned_host_not_loaded_again(fixture):
    p,v=fixture;b=LoadFake(p,v);b.loaded=True;r=loader.run_load(params(p),backend=b);assert r['status']=='error' and b.calls==0

def test_load_requires_explicit_acknowledgement(fixture):
    p,v=fixture;b=LoadFake(p,v)
    with pytest.raises(ValueError):loader.run_load(p,backend=b)
    assert b.calls==0
