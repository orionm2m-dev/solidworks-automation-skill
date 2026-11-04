from pathlib import Path
from copy import deepcopy
import hashlib,json,importlib
import pytest
from test_current_saved_append import planning
from test_current_saved_compound import env
from scripts import sw_cam_mill_current_append as m
from scripts import sw_cam_mill_current_compound_read as current

@pytest.fixture
def saving(planning,monkeypatch):
 e=planning;monkeypatch.setattr(m,'save_abi',lambda path:None)
 app=e['sw']['GetAddInObject']('clsid')['GetCWApp'];e['app']=app
 def save():e.update(digest='b'*64,dirty=False);return 0
 app['SaveActiveDocument']=save
 return e

def durable(r):return json.loads(Path(r['receipt_path']).read_text(encoding='utf-8'))

def test_checked_save_after_two_verified_delta_captures(saving):
 e=saving;r=e['apply'](save_after_verified=True)
 assert r['readback_verified'] and r['save_readback_verified'] and r['model_saved'],r
 assert r['source_update_verified'] and r['saved_file_sha256']=='b'*64 and r['source_hash_changed']
 assert r['save_hresult']==0 and r['save_return_type']=='int' and r['observed_needs_save_before'] is True and r['observed_needs_save_after'] is False
 assert r['saved']==r['confirm_saved'] and r['saved']['operations']==r['after']['operations']
 assert r['captures']==['before','confirm_before','after','confirm_after','saved','confirm_saved']
 assert e['calls'].count('GenerateOpPlan')==e['calls'].count('SaveActiveDocument')==1
 assert e['calls'].index('GenerateOpPlan')<e['calls'].index('SaveActiveDocument')
 assert not r['GTP_attempted'] and not r['reopen_persistence_verified'] and not any(x.startswith('Close') for x in e['calls'])
 assert durable(r)['saved']==r['saved']

@pytest.mark.parametrize('value',[None,True,False,1,-1,'0'])
def test_unqualified_save_return_stops_before_saved_cam_capture(saving,value):
 e=saving
 def save():e.update(digest='b'*64,dirty=False);return value
 e['app']['SaveActiveDocument']=save;r=e['apply'](save_after_verified=True)
 assert r['status']=='uncertain' and r['save_call_returned'] and not r['save_readback_verified']
 assert not r['source_update_verified'] and 'saved' not in r and e['calls'][-1]=='SaveActiveDocument'
 assert durable(r)['save_return_type']==type(value).__name__ and e['calls'].count('SaveActiveDocument')==1

@pytest.mark.parametrize('defect',['raise_after_disk_change','dirty','changed_tool','changed_step'])
def test_partial_save_retains_actual_evidence_and_never_replays(saving,defect):
 e=saving
 def save():
  e['digest']='b'*64
  if defect=='raise_after_disk_change':raise OSError('partial native save')
  e['dirty']=defect=='dirty'
  if defect=='changed_tool':e['tool']['Protrusion']=26.
  if defect=='changed_step':e['positions'][0]['GetCoordinates']=[0.,0.,-12.9]
  return 0
 e['app']['SaveActiveDocument']=save;r=e['apply'](save_after_verified=True)
 assert r['status']=='uncertain' and not r['readback_verified'] and not r['model_saved'] and not r['save_readback_verified']
 assert e['calls'].count('SaveActiveDocument')==1 and e['calls'].count('GenerateOpPlan')==1
 if defect=='raise_after_disk_change':assert r['native_dispatch_pending'] and not r['save_call_returned'] and 'saved' not in r
 else:
  assert r['save_call_returned'] and r['source_after_sha256']=='b'*64 and r['saved']['capture_complete']
  assert durable(r)['saved']==r['saved']
  if defect=='changed_tool':assert r['saved']['operations'][0]['assigned_tool']!=r['after']['operations'][0]['assigned_tool']
 e['calls'].clear();again=e['plan'](receipt_path=str(e['tmp']/'retry.json'))
 assert again['status']=='error' and not e['calls']

@pytest.mark.parametrize('defect',['source','lifetime','runtime'])
def test_changed_guard_after_delta_prevents_save(saving,defect):
 e=saving;n=0
 def runtime():
  nonlocal n
  n+=1
  if n==3:
   if defect=='source':e['digest']='c'*64
   elif defect=='lifetime':e['process']['create_time']=200.
   else:raise RuntimeError('drift')
 e['runtime_check']=runtime;r=e['apply'](save_after_verified=True)
 assert r['status']=='uncertain' and 'confirm_after' in r and 'SaveActiveDocument' not in e['calls']
 assert not r['model_saved'] and durable(r)['confirm_after']['capture_complete']

def test_event_at_save_return_retains_return_and_stops_all_cam(saving):
 e=saving
 def hook(name):
  if name=='SaveActiveDocument':e['session'].state['event_count']=1
 e['hook']=hook;r=e['apply'](save_after_verified=True)
 assert r['status']=='uncertain' and r['save_call_returned'] and e['calls'][-1]=='SaveActiveDocument'
 assert 'saved' not in r and durable(r)['save_hresult']==0

def test_prepare_is_read_only_and_rejects_save_request(saving):
 e=saving;r=e['plan']();assert r['readback_verified'] and not r['save_attempted'] and 'SaveActiveDocument' not in e['calls']
 e['calls'].clear();bad=e['plan'](save_after_verified=True,receipt_path=str(e['tmp']/'badprepare.json'))
 assert bad['status']=='error' and not e['calls']

def test_runtime_drift_preserves_saved_capture_but_revokes_save_claim(saving):
 e=saving;r=e['apply'](save_after_verified=True);assert r['model_saved'];e['calls'].clear()
 m.runtime_drift(r,RuntimeError('changed'))
 assert not r['save_readback_verified'] and not r['source_update_verified'] and not r['model_saved']
 assert r['save_call_returned'] and r['saved']['capture_complete'] and not e['calls']
 assert durable(r)['save_call_returned'] and not durable(r)['model_saved']

def test_actual_declared_save_abi(monkeypatch):
 mod=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
 monkeypatch.setattr(current,'_interface_class',lambda name,path:getattr(mod,name));m.save_abi('no-CAD')
