from pathlib import Path
from copy import deepcopy
import hashlib,json,importlib
import pytest
from test_current_saved_selected_insert import packet,durable
from test_current_saved_append_save import saving
from test_current_saved_append import planning,pin
from test_current_saved_compound import env,collection
from scripts import sw_cam_mill_current_append as m
from scripts import sw_cam_mill_selected_insert as selected
from scripts import sw_cam_mill_selected_continue as continuation
from scripts import sw_cam_comtypes as bridge


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

@pytest.fixture
def recovering(packet,monkeypatch):
 e=packet;realtyped=m._typed
 # 重现已记录旧版本在插入之后才检查缺失 registry 的失败。
 with monkeypatch.context() as old:
  old.setattr(selected,'nc_abi',lambda path:None)
  old.delitem(bridge._INTERFACES,'ICWNCParam2')
  def typed(raw,name,path):
   if name=='ICWNCParam2':bridge._interface_class(name,path)
   return realtyped(raw,name,path)
  old.setattr(m,'_typed',typed)
  partial=e['selected_apply'](save_after_verified=True)
 assert partial['status']=='uncertain' and partial['failed_phase']=='IGetNCParam' and len(partial['definition_actions'])==3,partial
 assert partial['definition_actions'][-1]['actual_native_id']==400 and not partial['save_attempted']
 e['partial']=partial;e['old_receipt']=Path(partial['receipt_path']);e['old_marker']=Path(partial['dispatch_marker_path'])
 e['immutable']={str(x):digest(x) for x in (e['old_receipt'],e['old_marker'])}
 e['planning_args'].update(definition_mode='selected_continue',partial_receipt_path=str(e['old_receipt']),partial_receipt_sha256=digest(e['old_receipt']),partial_attempt_marker_path=str(e['old_marker']),partial_attempt_marker_sha256=digest(e['old_marker']),retained_operation_native_id=400,receipt_path=str(e['tmp']/'recovery_prepare.json'))
 e['calls'].clear()
 def apply(**kw):
  prep=e['plan']();assert prep['readback_verified'],prep
  args=dict(action='apply',prepare_receipt_path=prep['receipt_path'],prepare_receipt_sha256=digest(prep['receipt_path']),expected_strategy_id=50,expected_strategy_name='Rough-Finish',receipt_path=str(e['tmp']/'continuation_apply.json'));args.update(kw)
  return e['plan'](**args)
 e['continue_apply']=apply
 return e


def test_dirty_recovery_two_full_captures_and_own_nc_no_mutation(recovering):
 e=recovering;r=e['plan']();assert r['readback_verified'] and r['continuation_recovery_verified'],r
 assert r['before']==r['confirm_before'] and r['before']['document']['needs_save'] is True
 assert [x['native_id'] for x in r['before']['operations']]==[195,267,300,302,400]
 assert r['before']['retained_operation_nc']['nc']['spindle_speed_native']==1200.
 assert r['before']['retained_operation_nc']['nc']['xy_feed_native']==100.
 assert not r['mutation_attempted'] and not r['marker_created']
 assert not any(x in e['calls'] for x in ('PUT_Suppressed','InsertOperation','GenerateOpPlan','SaveActiveDocument'))
 assert e['immutable']=={path:digest(path) for path in e['immutable']}


def test_finish_only_actual_helper_then_checked_save_no_replay(recovering):
 e=recovering;r=e['continue_apply'](save_after_verified=True)
 assert r['readback_verified'] and r['operation_delta_verified'] and r['save_readback_verified'],r
 assert e['calls'].count('InsertOperation')==1 and e['calls'].count('SaveActiveDocument')==1
 assert 'PUT_Suppressed' not in e['calls'] and 'GenerateOpPlan' not in e['calls']
 assert [x['native_id'] for x in r['retained_operations']]==[400] and [x['native_id'] for x in r['new_operations']]==[401]
 assert len(r['definition_actions'])==1 and r['definition_actions'][0]['anchor_native_id']==400
 assert r['saved']['operations'][:5]==r['before']['operations'] and r['saved']['retained_operation_nc']==r['before']['retained_operation_nc']
 assert r['saved']==r['confirm_saved'] and r['saved_file_sha256']=='c'*64
 assert r['dispatch_marker_path']!=str(e['old_marker']) and e['immutable']=={path:digest(path) for path in e['immutable']}
 e['calls'].clear();again=e['plan'](receipt_path=str(e['tmp']/'again.json'));assert again['status']=='error' and not e['calls']

@pytest.mark.parametrize('defect',['missing_rough','second_extra','wrong_kind','wrong_link','wrong_owner','old_tool','old_path','unsuppressed','rough_path','rough_tool','document_flag_type','source'])
def test_recovery_rejects_unproven_actual_delta_without_mutation(recovering,defect):
 e=recovering
 if defect=='missing_rough':e['local'].pop();e['os1']['IGetEnumOperations']=collection(e['local'])
 elif defect=='second_extra':e['local'].append(dict(e['local'][-1],_id=402));e['os1']['IGetEnumOperations']=collection(e['local'])
 elif defect=='wrong_kind':e['local'][-1]['OpernType']=1
 elif defect=='wrong_link':e['local'][-1]['IGetAllFeatures']=collection([dict(_id=64)])
 elif defect=='wrong_owner':e['os1']['GetSetup']=dict(_id=69)
 elif defect=='old_tool':e['tool']['Protrusion']=26.
 elif defect=='old_path':e['op1']['IGetEnumToolpaths']=collection([dict(RecordCount=41)])
 elif defect=='unsuppressed':e['local'][0]['Suppressed']=False
 elif defect=='rough_path':e['local'][-1]['GetIsToolpathGenerated']=True
 elif defect=='rough_tool':e['local'][-1]['IGetTool']['IsMillTool']=False
 elif defect=='document_flag_type':e['dirty']=None
 else:e['digest']='d'*64
 r=e['plan']();assert r['status']=='error' and not r['readback_verified'],r
 assert not any(x in e['calls'] for x in ('PUT_Suppressed','InsertOperation','SaveActiveDocument'))

@pytest.mark.parametrize('defect',['unknown_return','pending','save_attempt','different_id','wrong_failure','extra_action','suppression_capture','wrong_binding'])
def test_partial_authority_defects_rejected_before_native(recovering,defect):
 e=recovering;d=json.loads(e['old_receipt'].read_text())
 if defect=='unknown_return':d['definition_actions'][-1]['returned']=False
 elif defect=='pending':d['native_dispatch_pending']=True
 elif defect=='save_attempt':d['save_attempted']=True
 elif defect=='different_id':d['definition_actions'][-1]['actual_native_id']=401
 elif defect=='wrong_failure':d['failed_phase']='InsertOperation'
 elif defect=='extra_action':d['definition_actions'].append(d['definition_actions'][-1])
 elif defect=='suppression_capture':d['after_suppress_302']['operations'][0]['assigned_tool']['protrusion_native']=26.
 else:d['binding']['expected_process_create_time']=101.
 _,dh=pin(e['old_receipt'],d);e['planning_args']['partial_receipt_sha256']=dh
 marker=json.loads(e['old_marker'].read_text());marker['receipt_sha256']=dh;_,mh=pin(e['old_marker'],marker);e['planning_args']['partial_attempt_marker_sha256']=mh
 r=e['plan']();assert r['status']=='error' and not e['calls']


def test_original_marker_pin_changed_no_native(recovering):
 e=recovering;e['old_marker'].write_text('{}');r=e['plan']();assert r['status']=='error' and not e['calls']


def test_finish_exception_retains_attempt_new_marker_old_receipts_unchanged(recovering):
 e=recovering;original=e['target']['InsertOperation']
 def fail(*args):original(*args);raise OSError('unknown native outcome')
 e['target']['InsertOperation']=fail;r=e['continue_apply'](save_after_verified=True)
 assert r['status']=='uncertain' and r['native_dispatch_pending'] and not r['save_attempted']
 assert e['calls'].count('InsertOperation')==1 and 'PUT_Suppressed' not in e['calls']
 assert durable(r)['definition_actions'][0]['attempted'] and e['immutable']=={path:digest(path) for path in e['immutable']}


def test_finish_side_effect_bad_state_retained_and_save_blocked(recovering):
 e=recovering;original=e['target']['InsertOperation']
 def insert(*args):
  out=original(*args);e['tool']['Protrusion']=30.;return out
 e['target']['InsertOperation']=insert;r=e['continue_apply'](save_after_verified=True)
 assert r['status']=='uncertain' and e['calls'].count('InsertOperation')==1 and not r['save_attempted']
 assert durable(r)['after_insert_1']['operations'][0]['assigned_tool']['protrusion_native']==30.


def test_retained_nc_change_during_finish_blocks_save(recovering):
 e=recovering;original=e['target']['InsertOperation']
 def insert(*args):
  out=original(*args);e['local'][2]['IGetNCParam']['XYFeed']=101.;return out
 e['target']['InsertOperation']=insert;r=e['continue_apply'](save_after_verified=True)
 assert r['status']=='uncertain' and not r['save_attempted']
 assert durable(r)['after_insert_1']['retained_operation_nc']['nc']['xy_feed_native']==101.


@pytest.mark.parametrize('name',['ICWNCParam2','ICWNCParam','ICWMillOperation'])
def test_missing_registered_nc_extension_rejected_before_first_setter(packet,monkeypatch,name):
 e=packet;monkeypatch.delitem(bridge._INTERFACES,name);r=e['plan']()
 assert r['status']=='error' and not r['mutation_attempted'] and not e['calls']
 assert not r['receipt_created'] and not r['marker_created']


def test_reused_own_nc_reader_resolves_real_bridge_registry_primary_classes(packet,monkeypatch):
 primary=pytest.importorskip('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0',reason='Requires locally installed CAM primary metadata')
 monkeypatch.setattr(bridge,'_load_type_library',lambda path:primary)
 e=packet;resolved=[]
 def typed(raw,name):
  cls=bridge._interface_class(name,'offline-primary');resolved.append((name,str(cls._iid_)));return raw
 out=selected.definitions.read_own_nc(e['local'][0],read=m._member,typed=typed)
 assert out['read_complete'] and out['spindle_speed_native']==1200. and out['xy_feed_native']==100.
 assert resolved==[('ICWMillOperation','{4EDDCA74-325A-11D6-A9A7-00062999E55F}'),('ICWNCParam','{7532C780-3BC4-11D6-A9AF-00062999E55F}'),('ICWNCParam2','{7B7640FD-F53E-4B98-A073-EB4E6992E802}')]
 selected.nc_abi('offline-primary')


def test_real_registry_wrong_xyfeed_abi_stops_before_native(packet,monkeypatch):
 from types import SimpleNamespace
 module=pytest.importorskip('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0',reason='Requires locally installed CAM primary metadata')
 cls=module.ICWNCParam2;methods=[SimpleNamespace(name=x.name,restype=x.restype,argtypes=x.argtypes,paramflags=x.paramflags,idlflags=x.idlflags) for x in cls._methods_]
 next(x for x in methods if x.name=='_get_XYFeed').paramflags=((2,'value'),)
 fake=SimpleNamespace(_iid_=cls._iid_,_methods_=methods)
 class Library:
  def __getattr__(self,name):return fake if name=='ICWNCParam2' else getattr(module,name)
 monkeypatch.setattr(bridge,'_load_type_library',lambda path:Library())
 r=packet['plan']();assert r['status']=='error' and not packet['calls'] and not r['mutation_attempted']


@pytest.mark.parametrize('apply',[False,True])
def test_observed_false_host_save_flag_does_not_hide_unsaved_cam_delta(recovering,apply):
 e=recovering;d=json.loads(e['old_receipt'].read_text())
 for label in d['captures']:d[label]['document']['needs_save']=False
 _,dh=pin(e['old_receipt'],d);e['planning_args']['partial_receipt_sha256']=dh
 marker=json.loads(e['old_marker'].read_text());marker['receipt_sha256']=dh;_,mh=pin(e['old_marker'],marker);e['planning_args']['partial_attempt_marker_sha256']=mh
 e['dirty']=False;r=e['continue_apply'](save_after_verified=True) if apply else e['plan']()
 assert r['readback_verified'] and r['continuation_recovery_verified'],r
 assert r['before']==r['confirm_before'] and r['before']['document']['needs_save'] is False
 assert r['before']['operation_count']==5 and [x['native_id'] for x in r['before']['operations'][-3:]]==[300,302,400]
 if apply:
  assert r['save_readback_verified'] and e['calls'].count('InsertOperation')==1 and e['calls'].count('SaveActiveDocument')==1
  assert 'PUT_Suppressed' not in e['calls'] and r['saved']['operation_count']==6
 else:assert not r['mutation_attempted'] and not any(x in e['calls'] for x in ('PUT_Suppressed','InsertOperation','SaveActiveDocument'))
