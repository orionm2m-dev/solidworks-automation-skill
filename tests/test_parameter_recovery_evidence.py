from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import sw_cam_current_parameter_recovery_evidence as e
from scripts.sw_cam_turn_tool import _digest
from test_current_saved_parameter_fields import fixture,assigned,actual_change

@pytest.fixture
def history():
 before,plan,candidate=fixture();before.update(capture_complete=True)
 fields=[('entry_type',1,4),('spiral_radius',.2,3.),('first_depth',[False,10.],[False,.3]),('subsequent_depth',[False,10.],[False,.3]),('side_allowance',1.,.5),('floor_allowance',1.,.2),('side_step',[True,50.],[False,1.6])]
 plan['rows'][0]['fields']=[dict(field=k,expected=a,new=b) for k,a,b in fields]
 aftertool=assigned(before,candidate);after=deepcopy(aftertool)
 for k,a,b in fields:actual_change(after['operation_parameters'][0],k,b)
 row=after['operation_parameters'][0];row['rough']['depth']['DepthAllow']['raw']=.2
 ob=next(x for x in row['rough_diagnostic']['observations'] if x['member']=='DepthAllow');ob['raw_observation']['raw']=.2;ob['value']['raw']=.2
 base=dict(process_id=7,expected_process_create_time=1.,expected_document_path='C:/part.sldprt',expected_source_sha256='a'*64,parameter_operation_native_ids=[10,11],expected_feature_native_id=20,candidate_tool_native_id=32)
 pins={k:dict(path=p,sha256=h*64) for k,p,h in [('partial','C:/evidence/partial.json','b'),('old_marker','C:/evidence/attempts/once.json','c'),('original_prepare','C:/evidence/prepare.json','d'),('original_request','C:/evidence/request.json','e')]}
 flags={k:False for k in ('GOP_attempted','GTP_attempted','AFR_attempted','save_attempted','save_call_returned','save_readback_verified','model_saved','source_update_verified','automatic_replay','automatic_rollback','native_dispatch_pending')}
 common=dict(scope=e.SCOPE,phase='finished',binding=deepcopy(base),recipe=deepcopy(plan),request_pin=dict(kind='canonical_binding',sha256=_digest(base)),runtime_unchanged=True,source_before_sha256='a'*64,save_hresult=None,messages=dict(subscribed=True,disconnected=True,active=False,event_count=0),before=deepcopy(before),confirm_before=deepcopy(before),state_sha256=_digest(before),**flags)
 prep=dict(deepcopy(common),action='prepare',status='review_required',mutation_attempted=False,readback_verified=True,may_apply=True,actions=[],marker_created=False)
 actions=[dict(kind='SetTool',operation_native_id=10,change=None,attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,return_type='int',return_value=0,capture='after_tool_10')]
 for change in plan['rows'][0]['fields']:actions.append(dict(kind='field',operation_native_id=10,change=deepcopy(change),attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,return_type='int',return_value=0,observed=dict(returned=True,raw=dict(recorded=True,raw=deepcopy(change['new'])))))
 partial=dict(deepcopy(common),action='apply',status='uncertain',mutation_attempted=True,readback_verified=False,parameter_delta_verified=False,receipt_created=True,marker_created=True,receipt_path=pins['partial']['path'],dispatch_marker_path=pins['old_marker']['path'],captures=['before','confirm_before','after_tool_10','confirm_tool_10','after'],after_tool_10=aftertool,confirm_tool_10=deepcopy(aftertool),after=after,actions=actions,issue=dict(type='ValueError',hresult=None,actual_return_type=None,locations=[dict(file=f,function=fn,line=1) for f,fn in [('sw_cam_current_saved_parameter_batch.py','run_current_saved_configuration'),('sw_cam_current_saved_parameter_fields.py','verify_final'),('sw_cam_current_saved_parameter_fields.py','require')]]))
 args=dict(deepcopy(base),configuration_mode='current_saved',action='apply',save_after_verified=True,acknowledge_qualification_only=True,prepare_receipt_path=pins['original_prepare']['path'],prepare_receipt_sha256=pins['original_prepare']['sha256'],receipt_path=pins['partial']['path'],attempt_registry_path='C:/evidence/attempts')
 request=dict(requests=[dict(name='solidworks_cam_configure_guide_definitions',arguments=dict(params=args))]);marker=dict(scope=e.SCOPE,status='uncertain',automatic_replay=False,receipt_path=pins['partial']['path'],receipt_sha256=pins['partial']['sha256'])
 baseline=deepcopy(before);baseline.pop('parameter_batch')
 return dict(partial=partial,original_prepare=prep,original_request=request,old_marker=marker,base_binding=base,plan=plan,baseline=baseline,pins=pins)

def test_completed_observed_alias_proof_has_no_side_effects(history):
 original=deepcopy(history);out=e.validate_history(**history)
 assert history==original and out['expected_state']==history['partial']['after']
 assert out['consumer_ids']==[10] and out['recovery_pins']==history['pins']
 out['expected_state']['document']['needs_save']=True;assert not history['partial']['after']['document']['needs_save']

@pytest.mark.parametrize('bad',['pending','missing_action','order','hresult_none','hresult_bool','getter','action_unverified','save','event','native_error','wrong_failure','wrong_prepare','wrong_baseline','wrong_source','wrong_binding','marker_sha','marker_path','prepare_pin','new_alias','other_field','finish','shared_tool','nc','paths','incomplete','floor_value','pin_missing','pin_hash'])
def test_history_rejects_every_incomplete_or_unrequested_delta(history,bad):
 h=history;d=h['partial']
 if bad=='pending':d['actions'][1]['native_dispatch_pending']=True
 elif bad=='missing_action':d['actions'].pop()
 elif bad=='order':d['actions'][2],d['actions'][3]=d['actions'][3],d['actions'][2]
 elif bad=='hresult_none':d['actions'][1]['return_value']=None
 elif bad=='hresult_bool':d['actions'][1]['return_value']=False
 elif bad=='getter':d['actions'][1]['observed']['raw']['raw']=3
 elif bad=='action_unverified':d['actions'][4]['readback_verified']=False
 elif bad=='save':d['save_attempted']=True
 elif bad=='event':d['messages']['event_count']=1
 elif bad=='native_error':d['issue']['hresult']=-1
 elif bad=='wrong_failure':d['issue']['locations'][1]['function']='write_field_once'
 elif bad=='wrong_prepare':h['original_prepare']['confirm_before']['profile']['depth']=8.
 elif bad=='wrong_baseline':h['baseline']['profile']['depth']=8.
 elif bad=='wrong_source':d['source_before_sha256']='f'*64
 elif bad=='wrong_binding':d['binding']['process_id']=8
 elif bad=='marker_sha':h['old_marker']['receipt_sha256']='f'*64
 elif bad=='marker_path':h['pins']['old_marker']['path']='C:/different/once.json'
 elif bad=='prepare_pin':h['original_request']['requests'][0]['arguments']['params']['prepare_receipt_sha256']='f'*64
 elif bad=='new_alias':d['after']['operation_parameters'][0]['rough']['depth']['DepthAllow']['raw']=.3
 elif bad=='other_field':d['after']['operation_parameters'][0]['rough']['entry']['GetSpiralPitch']['raw']=.2
 elif bad=='finish':d['after']['operation_parameters'][1]['finish']['SideAllow']['raw']=0.
 elif bad=='shared_tool':d['after']['parameter_batch']['candidate_tool']['mill']['length']=99.
 elif bad=='nc':d['after']['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']=200.
 elif bad=='paths':d['after']['operations'][2]['toolpath_record_counts']=[100]
 elif bad=='incomplete':d['after']['parameter_batch']['read_complete']=False
 elif bad=='floor_value':h['plan']['rows'][0]['fields'][5]['new']=.3
 elif bad=='pin_missing':h['pins'].pop('original_request')
 else:h['pins']['partial']['sha256']=None
 with pytest.raises(ValueError):e.validate_history(**h)

def test_default_alias_remains_rejected(history):
 h=history;c=h['partial']['before']['parameter_batch']['candidate_tool']
 with pytest.raises(ValueError):e.fields.verify_final(h['partial']['before'],h['partial']['after'],h['plan'],{c['generic']['native_id']:c})


