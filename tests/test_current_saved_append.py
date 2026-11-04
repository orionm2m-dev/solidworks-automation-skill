from copy import deepcopy
from pathlib import Path
import hashlib,json,importlib
import pytest
from test_current_saved_compound import env,collection
from scripts import sw_cam_mill_current_append as m
from scripts import sw_cam_mill_current_compound_read as current


def pin(p,data):
 p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');return str(p),hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def planning(env,tmp_path,monkeypatch):
 e=env;r=e['run']();assert r['readback_verified'];r['runtime_unchanged']=True
 request={'requests':[{'name':'solidworks_cam_inspect_current_saved_compound','arguments':{'params':dict(e['args'],addin_clsid='clsid')}}]}
 result={'results':[{'name':'solidworks_cam_inspect_current_saved_compound','result':{'isError':False,'content':[{'parsed_json':r}]}}]}
 rq,rqs=pin(tmp_path/'request.json',request);rr,rrs=pin(tmp_path/'result.json',result)
 for name in ['_member','_typed','_process_identity','document_snapshot','solidworks_operation_lock','CamMessageSession']:
  monkeypatch.setattr(m,name,getattr(current,name))
 monkeypatch.setattr(m,'_file_hash',lambda path:e['digest'] if str(path)==e['args']['expected_document_path'] else hashlib.sha256(Path(path).read_bytes()).hexdigest())
 monkeypatch.setattr(m,'gop_abi',lambda path:None)
 e['target'].update(Attribute=50,GetAttribute=('Rough-Finish',50),IGetActiveAttribute='Rough-Finish',IGetAllAttributes=['Rough-Finish'],IGetAllAttributes2=['Rough-Finish'],IGetAllDefaultOperations=lambda kind:['Default'],GetTdbIdForDefaultOperation=lambda kind,name:100+kind)
 e['new_tool']=dict(_id=301,IsMillTool=True,ToolType=1,CutDiameter=8.,Protrusion=25.)
 e['new_op']=dict(_id=300,OpernType=1,Suppressed=False,GetIsToolpathGenerated=False,IGetAllFeatures=collection([e['target']]),IGetEnumToolpaths=collection([]),IGetTool=e['new_tool'])
 def gop(flag):
  assert flag==1;e['os1']['IGetEnumOperations']=collection([e['new_op']]);e['dirty']=True;return None
 e['target']['GenerateOpPlan']=gop
 e['planning_args']=dict(e['args'],planning_mode='current_saved',action='prepare',current_read_request_path=rq,current_read_request_sha256=rqs,current_read_receipt_path=rr,current_read_receipt_sha256=rrs,prepare_receipt_path=None,prepare_receipt_sha256=None,expected_strategy_id=None,expected_strategy_name=None,save_after_verified=False,acknowledge_disposable_copy=True,attempt_registry_path=str(tmp_path),receipt_path=str(tmp_path/'prepare.json'))
 e['runtime_check']=lambda:None
 e['plan']=lambda **kw:m.runtime_complete(m.run_current_saved_append(e['sw'],'clsid','fixture.tlb',runtime_check=e['runtime_check'],**dict(e['planning_args'],**kw)))
 e['calls'].clear();e['tmp']=tmp_path
 def apply(**kw):
  prep=e['plan']();assert prep['readback_verified'],prep
  return e['plan'](action='apply',prepare_receipt_path=str(tmp_path/'prepare.json'),prepare_receipt_sha256=hashlib.sha256((tmp_path/'prepare.json').read_bytes()).hexdigest(),expected_strategy_id=50,expected_strategy_name='Rough-Finish',receipt_path=str(tmp_path/'apply.json'),**kw)
 e['apply']=apply
 return e


def test_prepare_actual_strategy_catalogues_two_captures_no_marker(planning):
 r=planning['plan']();assert r['status']=='review_required' and r['readback_verified'],r
 assert r['before']==r['confirm_before'] and r['may_apply']
 assert r['selected_strategy']['attribute_id']==50
 assert [x['operation_type'] for x in r['default_operation_catalogues']]==[0,1]
 assert 'GenerateOpPlan' not in planning['calls'] and not Path(r['dispatch_marker_path']).exists()
 assert not r['mutation_attempted'] and not r['model_saved']


def test_one_hresult_only_none_dispatch_additive_delta_old_paths_preserved(planning):
 r=planning['apply']();assert r['status']=='review_required' and r['operation_delta_verified'],r
 assert planning['calls'].count('GenerateOpPlan')==1 and r['native_call_returned']
 assert r['native_return_type']=='NoneType' and r['native_hresult'] is None
 assert r['after']==r['confirm_after'] and [x['native_id'] for x in r['new_operations']]==[300]
 assert r['after']['operations'][:2]==r['before']['operations']
 assert not r['GTP_attempted'] and not r['model_saved'] and not r['full_hidden_geometry_preservation_verified']
 assert not any(x.startswith(('Save','Set','Insert','Add')) for x in planning['calls'])
 assert Path(r['dispatch_marker_path']).is_file()


def test_once_marker_blocks_second_attempt_without_native(planning):
 r=planning['apply']();assert r['readback_verified'];planning['calls'].clear()
 repeated=planning['plan'](receipt_path=str(planning['tmp']/'again.json'))
 assert repeated['status']=='error' and not planning['calls']


@pytest.mark.parametrize('defect',['old_tool','new_link','new_path'])
def test_bad_delta_durable_actual_after_uncertain_no_second_capture(planning,defect):
 original=planning['target']['GenerateOpPlan']
 def changed(flag):
  result=original(flag)
  if defect=='old_tool':planning['tool']['Protrusion']=26.
  elif defect=='new_link':planning['new_op']['IGetAllFeatures']=collection([{'_id':64}])
  else:planning['new_op']['GetIsToolpathGenerated']=True;planning['new_op']['IGetEnumToolpaths']=collection([dict(RecordCount=1)])
  return result
 planning['target']['GenerateOpPlan']=changed;r=planning['apply']()
 assert r['status']=='uncertain' and not r['readback_verified'] and 'confirm_after' not in r
 saved=json.loads(Path(r['receipt_path']).read_text(encoding='utf-8'))
 assert saved['after']['capture_complete'] and saved['after']==r['after']
 assert planning['calls'].count('GenerateOpPlan')==1


def test_exception_after_mutation_keeps_claim_uncertain_no_replay(planning):
 def boom(flag):raise OSError('native dispatch failed')
 planning['target']['GenerateOpPlan']=boom;r=planning['apply']()
 assert r['status']=='uncertain' and r['native_dispatch_pending'] and not r['native_call_returned']
 assert planning['calls'][-1]=='GenerateOpPlan' and Path(r['dispatch_marker_path']).exists()


def test_return_then_event_retained_and_no_post_cam(planning):
 def hook(name):
  if name=='GenerateOpPlan':planning['session'].state['event_count']=1
 planning['hook']=hook;r=planning['apply']()
 assert r['status']=='uncertain' and r['native_call_returned'] and planning['calls'][-1]=='GenerateOpPlan'
 assert 'after' not in r and json.loads(Path(r['receipt_path']).read_text())['native_call_returned']


def test_wrong_reviewed_strategy_no_claim_no_dispatch(planning):
 prep=planning['plan']();assert prep['readback_verified']
 r=planning['plan'](action='apply',prepare_receipt_path=prep['receipt_path'],prepare_receipt_sha256=hashlib.sha256(Path(prep['receipt_path']).read_bytes()).hexdigest(),expected_strategy_id=51,expected_strategy_name='other',receipt_path=str(planning['tmp']/'wrong.json'))
 assert r['status']=='error' and not r['marker_created'] and 'GenerateOpPlan' not in planning['calls']


def test_actual_request_source_mismatch_rejected_before_native(planning):
 r=planning['plan'](expected_source_sha256='b'*64)
 assert r['status']=='error' and not planning['calls']


def test_runtime_drift_rewrites_only_owned_receipt_and_marker(planning):
 r=planning['apply']();assert r['readback_verified'];planning['calls'].clear()
 m.runtime_drift(r,RuntimeError('drift'))
 assert r['status']=='uncertain' and not r['readback_verified'] and not planning['calls']
 saved=json.loads(Path(r['receipt_path']).read_text());marker=json.loads(Path(r['dispatch_marker_path']).read_text())
 assert saved['native_call_returned'] and saved['after']['capture_complete'] and marker['status']=='uncertain'
 assert marker['receipt_sha256']==hashlib.sha256(Path(r['receipt_path']).read_bytes()).hexdigest()


def test_declared_real_gop_metadata(monkeypatch):
 mod=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
 monkeypatch.setattr(current,'_interface_class',lambda name,path:getattr(mod,name));m.gop_abi('offline')


def test_runtime_drift_after_captures_stops_before_claim_and_gop(planning):
 def drift():raise RuntimeError('runtime changed during capture')
 planning['runtime_check']=drift;r=planning['apply']()
 assert r['status']=='error' and not r['marker_created'] and 'GenerateOpPlan' not in planning['calls']


def test_runtime_drift_after_claim_stops_before_gop_keeps_once_marker(planning):
 count=0
 def drift():
  nonlocal count
  count+=1
  if count==2:raise RuntimeError('runtime changed after claim')
 planning['runtime_check']=drift;r=planning['apply']()
 assert r['status']=='error' and r['marker_created'] and not r['mutation_attempted']
 assert 'GenerateOpPlan' not in planning['calls'] and Path(r['dispatch_marker_path']).exists()
