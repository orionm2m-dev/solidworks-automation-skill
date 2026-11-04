from copy import deepcopy
from pathlib import Path
import hashlib,json,importlib
import pytest
from test_current_saved_compound import env,collection,Native
from test_current_saved_append import planning,pin
from test_current_saved_append_save import saving
from scripts import sw_cam_mill_selected_insert as selected
from scripts import sw_cam_mill_current_append as m
from scripts import sw_cam_mill_current_compound_read as current
from scripts import sw_cam_comtypes

@pytest.fixture
def packet(saving,monkeypatch):
 e=saving
 class Operation(Native):
  def __setattr__(self,name,value):
   assert name=='Suppressed' and value is True
   e['calls'].append('PUT_Suppressed');self[name]=value;e['dirty']=True;e['hook']('PUT_Suppressed')
 def operation(oid,kind,tid):
  x=Operation(_id=oid,OpernType=kind,Suppressed=False,GetIsToolpathGenerated=False,IGetAllFeatures=collection([e['target']]),IGetEnumToolpaths=collection([]),IGetTool=dict(_id=tid,IsMillTool=True,ToolType=1,CutDiameter=8.,Protrusion=25.),IGetNCParam=dict(GetSpndlSpeed=1200.,XYFeed=100.))
  x['QueryInterface']=lambda iid:x
  return x
 old=[operation(300,8,301),operation(302,2,303)];e['local']=old
 def gop(flag):e['os1']['IGetEnumOperations']=collection(old);e['dirty']=True
 e['target']['GenerateOpPlan']=gop
 prior=e['apply'](save_after_verified=True);assert prior['model_saved'],prior
 ap,ah=pin(e['tmp']/'authority.json',prior)
 e['args'].update(expected_source_sha256='b'*64,expected_operation_native_ids=[195,267,300,302])
 e['planning_args'].update(e['args'],definition_mode='selected_insert',saved_authority_receipt_path=ap,saved_authority_receipt_sha256=ah,
  current_read_request_path=None,current_read_request_sha256=None,current_read_receipt_path=None,current_read_receipt_sha256=None,
  insert_operations=[dict(operation_type=i,default_operation_name='Default',default_operation_id=100+i) for i in (0,1)],
  suppress_operation_native_ids=[300,302],anchor_operation_native_id=302,receipt_path=str(e['tmp']/'selected_prepare.json'))
 e['doc']['GetCWObjectFromID']=lambda kind,oid:(e['target'],True) if kind==1 and oid==70 else (next(x for x in e['local'] if x['_id']==oid),True)
 def insert(kind,default,anchor):
  assert kind==len(e['local'])-2 and default==100+kind and anchor is e['local'][-1]
  new=operation(400+kind,kind,500+kind);e['local'].append(new);e['os1']['IGetEnumOperations']=collection(e['local']);e['dirty']=True;return new
 e['target']['InsertOperation']=insert
 e['app']['SaveActiveDocument']=lambda:e.update(digest='c'*64,dirty=False) or 0
 monkeypatch.setattr(selected,'abi',lambda path:None)
 monkeypatch.setattr(selected.definitions,'_member',m._member)
 monkeypatch.setattr(sw_cam_comtypes,'_is_comtypes_pointer',lambda x:isinstance(x,Operation))
 e['calls'].clear()
 def apply(**kw):
  prep=e['plan']();assert prep['readback_verified'],prep
  return e['plan'](action='apply',prepare_receipt_path=prep['receipt_path'],prepare_receipt_sha256=hashlib.sha256(Path(prep['receipt_path']).read_bytes()).hexdigest(),expected_strategy_id=50,expected_strategy_name='Rough-Finish',receipt_path=str(e['tmp']/'selected_apply.json'),**kw)
 e['selected_apply']=apply
 return e


def durable(r):return json.loads(Path(r['receipt_path']).read_text(encoding='utf-8'))


def test_actual_saved_authority_prepare_no_setter_or_insert(packet):
 r=packet['plan']();assert r['readback_verified'],r
 assert r['before']==r['confirm_before'] and r['selected_definition_plan']['suppress_operation_native_ids']==[300,302]
 assert not any(x in packet['calls'] for x in ('PUT_Suppressed','InsertOperation','GenerateOpPlan','SaveActiveDocument'))
 assert not r['marker_created']


def test_actual_helper_two_suppressions_two_inserts_checked_save(packet):
 e=packet;r=e['selected_apply'](save_after_verified=True)
 assert r['readback_verified'] and r['operation_delta_verified'] and r['save_readback_verified'],r
 assert e['calls'].count('PUT_Suppressed')==2 and e['calls'].count('InsertOperation')==2 and e['calls'].count('SaveActiveDocument')==1
 assert 'GenerateOpPlan' not in e['calls'] and not r['GOP_attempted'] and not r['GTP_attempted']
 assert [x['native_id'] for x in r['new_operations']]==[400,401]
 assert r['saved']['operations'][:2]==r['before']['operations'][:2]
 for old,new in zip(r['before']['operations'][2:],r['saved']['operations'][2:4]):
  expected=deepcopy(old);expected['suppressed']=True;assert expected==new
 assert r['saved_file_sha256']=='c'*64 and r['saved']==r['confirm_saved']
 assert len(r['definition_actions'])==4 and all(x['readback_verified'] for x in r['definition_actions'])
 assert all(x['own_nc']['read_complete'] for x in r['definition_actions'][2:])
 assert durable(r)['definition_actions']==r['definition_actions']
 e['calls'].clear();again=e['plan'](receipt_path=str(e['tmp']/'again.json'));assert again['status']=='error' and not e['calls']

@pytest.mark.parametrize('change',['old_tool','old_path','target_profile','wrong_new_link','new_path'])
def test_unexpected_first_insert_delta_durable_and_stops_before_finish(packet,change):
 e=packet;original=e['target']['InsertOperation']
 def insert(*args):
  result=original(*args)
  if change=='old_tool':e['tool']['Protrusion']=26.
  elif change=='old_path':e['op1']['IGetEnumToolpaths']=collection([dict(RecordCount=41)])
  elif change=='target_profile':e['positions'][0]['GetCoordinates']=[0.,0.,-12.9]
  elif change=='wrong_new_link':result['IGetAllFeatures']=collection([dict(_id=64)])
  else:result['GetIsToolpathGenerated']=True
  return result
 e['target']['InsertOperation']=insert;r=e['selected_apply'](save_after_verified=True)
 assert r['status']=='uncertain' and not r['readback_verified'] and not r['save_attempted'],r
 assert e['calls'].count('InsertOperation')==1 and 'SaveActiveDocument' not in e['calls']
 assert durable(r)['after_insert_0']['capture_complete'] and r['definition_actions'][-1]['returned']

@pytest.mark.parametrize('when',['PUT_Suppressed','InsertOperation'])
def test_event_after_native_return_stops_with_durable_result(packet,when):
 e=packet
 def hook(name):
  if name==when:e['session'].state['event_count']=1
 e['hook']=hook;r=e['selected_apply']()
 assert r['status']=='uncertain' and not r['readback_verified'] and e['calls'][-1]==when
 assert durable(r)['definition_actions'][-1]['returned']
 assert e['calls'].count(when)==1 and not r['save_attempted']


def test_suppression_side_effect_retained_no_second_setter(packet):
 e=packet
 def hook(name):
  if name=='PUT_Suppressed':e['tool']['CutDiameter']=9.
 e['hook']=hook;r=e['selected_apply']()
 assert r['status']=='uncertain' and e['calls'].count('PUT_Suppressed')==1 and 'InsertOperation' not in e['calls']
 assert durable(r)['after_suppress_300']['operations'][0]['assigned_tool']['cut_diameter_native']==9.


def test_insert_exception_after_mutation_never_replays(packet):
 e=packet;original=e['target']['InsertOperation']
 def fail(*args):original(*args);raise OSError('uncertain native result')
 e['target']['InsertOperation']=fail;r=e['selected_apply']()
 assert r['status']=='uncertain' and r['native_dispatch_pending'] and not r['definition_actions'][-1]['returned']
 assert e['calls'].count('InsertOperation')==1
 e['calls'].clear();bad=e['plan'](receipt_path=str(e['tmp']/'retry.json'));assert bad['status']=='error' and not e['calls']

@pytest.mark.parametrize('change',['save_flag','saved_source','order','path_count','lifetime','saved_state'])
def test_bad_real_authority_rejected_without_native(packet,change):
 e=packet;p=Path(e['planning_args']['saved_authority_receipt_path']);d=json.loads(p.read_text())
 if change=='save_flag':d['save_readback_verified']=False
 elif change=='saved_source':d['saved_file_sha256']='d'*64
 elif change=='order':d['saved']['operations'].reverse();d['confirm_saved']=deepcopy(d['saved'])
 elif change=='path_count':d['saved']['operations'][1]['toolpath_record_counts']=[41];d['confirm_saved']=deepcopy(d['saved'])
 elif change=='lifetime':d['binding']['expected_process_create_time']=101.
 else:d['confirm_saved']['target_header']['depth_native']=9.
 _,sha=pin(p,d);e['planning_args']['saved_authority_receipt_sha256']=sha;r=e['plan']()
 assert r['status']=='error' and not e['calls']

@pytest.mark.parametrize('field,value',[('insert_operations',[dict(operation_type=0,default_operation_name='missing',default_operation_id=100),dict(operation_type=1,default_operation_name='Default',default_operation_id=101)]),('suppress_operation_native_ids',[195,302]),('anchor_operation_native_id',300),('definition_mode','retain_plan')])
def test_no_guess_or_retain_guard_relaxation(packet,field,value):
 e=packet;r=e['plan'](**{field:value});assert r['status']=='error' and not e['calls']


def test_runtime_drift_between_suppression_and_insert_stops(packet):
 e=packet
 def runtime():
  if any(x['Suppressed'] for x in e['local']):raise RuntimeError('runtime drift')
 e['runtime_check']=runtime;r=e['selected_apply']()
 assert r['status']=='uncertain' and e['calls'].count('PUT_Suppressed')==1 and 'InsertOperation' not in e['calls']


def test_exact_declared_insert_and_property_metadata(monkeypatch):
 mod=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
 monkeypatch.setattr(current,'_interface_class',lambda name,path:getattr(mod,name));selected.abi('offline')
