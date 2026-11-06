"""完成后的续接证据测试；历史验证器在本组中隔离，几何和状态差量为真实实现。"""
from copy import deepcopy
import sys,types
import pytest
from scripts import sw_cam_current_circular_authority as a
from scripts import sw_cam_current_saved_parameter_fields as fields
from test_circular_continuation import completed,pin,config_values


@pytest.fixture
def resumed(completed,monkeypatch):
    old=completed['receipt'];root=completed['path']
    history=dict(original_binding=deepcopy(old['binding']),historical_before=deepcopy(old['before']),historical_after_sketch=deepcopy(old['confirm_after_sketch']),expected_state=deepcopy(old['confirm_after_feature']),new_feature_native_id=22,created_names=deepcopy(old['created_names']))
    history['pins']={k:pin(root/(k+'.json'),dict(synthetic_history=k)) for k in ('partial','old_marker','original_request','original_prepare')}
    d=deepcopy(old);d.update(action='resume_after_feature',continuation_stage='after_feature',continuation_verified=True,creation_replayed=False)
    d['binding']['continuation_mode']='after_feature'
    for key,prefix in (('partial','partial_receipt'),('old_marker','old_marker'),('original_request','original_apply_request'),('original_prepare','original_prepare_receipt')):
        d['binding'][prefix+'_path']=history['pins'][key]['path'];d['binding'][prefix+'_sha256']=history['pins'][key]['sha256']
    d['request_pin']['sha256']=a._digest(d['binding']);d['continuation_pins']=deepcopy(history['pins'])
    d['historical_capture_keys']=dict(before='before',after_sketch='confirm_after_sketch',after_feature='confirm_after_feature')
    for key,hkey in (('historical_before','historical_before'),('historical_after_sketch','historical_after_sketch'),('historical_after_feature','expected_state')):d[key]=deepcopy(history[hkey])
    d['before']=deepcopy(history['expected_state']);d['confirm_before']=deepcopy(d['before']);d['actions']=d['actions'][-2:]
    for key in ('after_sketch','confirm_after_sketch','after_feature','confirm_after_feature'):d.pop(key)
    def history_loader(binding,loaded):
        assert binding==d['binding'] and loaded['state']==completed['loaded']['state']
        return deepcopy(history)
    module=types.ModuleType('scripts.sw_cam_current_circular_resume_evidence');module.load_history=history_loader
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_current_circular_resume_evidence',module)
    def load(value=None):
        actual=d if value is None else value
        p=pin(root/'resumed.json',actual)
        return a.load_pocket(p['path'],p['sha256'],process_id=123,source_path=completed['v']['expected_document_path'],source_sha256='b'*64)
    return dict(completed=completed,receipt=d,history=history,load=load)


def test_completed_two_action_continuation_restores_original_recipe(resumed):
    d=resumed['receipt'];out=resumed['load']()
    assert out['receipt']==d and out['binding']==resumed['history']['original_binding']
    assert [x['kind'] for x in out['receipt']['actions']]==['InsertOperation','SaveActiveDocument']
    assert out['restore']==dict(new_feature_native_id=22,new_operations=d['new_operations'],created_names=d['created_names'])
    assert out['state']==d['saved'] and len([k for k in out['pins'] if k.startswith('creation_resume_')])==4
    assert d['historical_after_feature']==resumed['history']['expected_state']


@pytest.mark.parametrize('key',a.FLAGS)
def test_resume_requires_every_completed_flag(resumed,key):
    d=deepcopy(resumed['receipt']);d[key]=False
    with pytest.raises(ValueError):resumed['load'](d)


@pytest.mark.parametrize('defect',['stage','unverified','replayed','pending','gop','savebool','save_none','nonnull','old_creation_action','partial_error','event','cleanup','history_pin','history_key','raw_history','before_drift','insert_oldpath','saved_oldnc','dirty','capture_incomplete','extended_incomplete','operation_id','retained_feature','names','wrong_source','lifetime','unequal','extra_geometry_drift'])
def test_resume_rejects_partial_false_history_or_unrequested_delta(resumed,defect):
    d=deepcopy(resumed['receipt'])
    if defect=='stage':d['continuation_stage']='after_sketch'
    elif defect=='unverified':d['continuation_verified']=False
    elif defect=='replayed':d['creation_replayed']=True
    elif defect=='pending':d['native_dispatch_pending']=True
    elif defect=='gop':d['GOP_attempted']=True
    elif defect=='savebool':d['save_hresult']=True
    elif defect=='save_none':d['actions'][-1]['native_result']['hresult']=None
    elif defect=='nonnull':d['actions'][0]['native_result']['nonnull']=False
    elif defect=='old_creation_action':d['actions'].insert(0,deepcopy(resumed['completed']['receipt']['actions'][0]))
    elif defect=='partial_error':d['issue']={}
    elif defect=='event':d['messages']['event_count']=1
    elif defect=='cleanup':d['messages']['disconnected']=False
    elif defect=='history_pin':d['continuation_pins']['partial']['sha256']='e'*64
    elif defect=='history_key':d['historical_capture_keys']['after_feature']='after_feature'
    elif defect=='raw_history':d['historical_after_feature']['sketch_state']['solids'][0]['mass_raw'][0]+=1.e-12
    elif defect=='before_drift':d['before']['target_header']['depth_native']+=.1;d['confirm_before']=deepcopy(d['before'])
    elif defect=='insert_oldpath':d['after_insert']['operations'][2]['toolpath_record_counts']=[100];d['confirm_after_insert']=deepcopy(d['after_insert'])
    elif defect=='saved_oldnc':d['saved']['reference_parameter_observation']['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']+=1.;d['confirm_saved']=deepcopy(d['saved'])
    elif defect=='dirty':d['saved']['sketch_state']['needs_save']=True;d['confirm_saved']=deepcopy(d['saved'])
    elif defect=='capture_incomplete':d['before']['capture_complete']=False;d['confirm_before']=deepcopy(d['before'])
    elif defect=='extended_incomplete':d['after_insert']['extended_capture_complete']=False;d['confirm_after_insert']=deepcopy(d['after_insert'])
    elif defect=='operation_id':d['new_operation_native_id']=14
    elif defect=='retained_feature':d['new_feature_native_id']=23
    elif defect=='names':d['created_names']=['OTHER']
    elif defect=='wrong_source':d['source_before_sha256']='f'*64
    elif defect=='lifetime':d['binding']['expected_process_create_time']+=1;d['request_pin']['sha256']=a._digest(d['binding'])
    elif defect=='unequal':d['confirm_saved']['target_header']['depth_native']+=1.
    else:d['after_insert']['target_geometry']['bounds_native'][0]+=.1;d['confirm_after_insert']=deepcopy(d['after_insert'])
    with pytest.raises((ValueError,AssertionError)):resumed['load'](d)


def test_fresh_mass_jitter_allowed_but_raw_history_remains_exact(resumed):
    d=resumed['receipt']
    for key in ('before','confirm_before','after_insert','confirm_after_insert','saved','confirm_saved'):
        d[key]['sketch_state']['solids'][0]['mass_raw'][0]+=1.e-12
    out=resumed['load']()
    assert out['state']['sketch_state']['solids']==d['saved']['sketch_state']['solids']
    assert d['historical_after_feature']==resumed['history']['expected_state']


def test_original_four_action_authority_remains_supported(completed):
    assert completed['load']()['receipt']['action']=='apply'


def test_resume_source_is_pre_save_history_and_current_saved_output(resumed):
    out=resumed['load']()
    assert out['binding']['expected_source_sha256']=='a'*64 and out['source_sha256']=='b'*64
    assert out['state']['sketch_state']['saved_file_sha256']=='b'*64


def test_actual_history_to_labelled_synthetic_completed_authority(tmp_path):
    """可选真实历史回归；后续 Insert/Save 明确为合成数据，不声称原生执行。"""
    import os,json,hashlib
    from pathlib import Path
    from scripts import sw_cam_current_circular_resume_evidence as history_module
    from scripts import sw_cam_current_saved_generation as generation
    external=os.environ.get('SW_CAM_TEST_CIRCULAR_APPLY_REQUEST')
    if not external:pytest.skip('Optional immutable external circular apply request not configured')
    request_path=Path(external)
    if not request_path.is_file():pytest.skip('Optional immutable external request unavailable')
    request=json.loads(request_path.read_text(encoding='utf-8-sig'))
    original_values=next(x['arguments']['params'] for x in request['requests'] if x['name']=='solidworks_cam_add_circular_pocket_plan')
    partial_path=Path(original_values['receipt_path']);partial=json.loads(partial_path.read_text(encoding='utf-8-sig'))
    v=deepcopy(partial['binding']);v['continuation_mode']='after_feature'
    for prefix,path in {'partial_receipt':partial_path,'old_marker':Path(partial['dispatch_marker_path']),'original_apply_request':request_path,'original_prepare_receipt':Path(original_values['prepare_receipt_path'])}.items():
        v[prefix+'_path']=str(path);v[prefix+'_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    loaded=generation.load_completed_configuration(v['configuration_receipt_path'],v['configuration_receipt_sha256'],process_id=v['process_id'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'],selected_ids=[v['anchor_operation_native_id']])
    history=history_module.load_history(v,loaded);before=history['expected_state'];fid=history['new_feature_native_id']
    assert a.pocket.verify_geometry(before,history['original_binding'],fid)['GetBoundParams_used_as_analytic_diameter'] is False
    assert before['target_header']['bounds_native'][:2]!=[2.*v['sketch_spec']['profile']['radius_mm']]*2
    insert=deepcopy(before);oid=max(x['native_id'] for x in before['operations'])+100000
    reference=insert['reference_parameter_observation'];source_param=next(x for x in reference['operation_parameters'] if x['operation_type']==0)
    default_tool=next(x for x in reference['parameter_batch']['source_tools'].values() if all(fields.equal(x['generic'].get(k),value) for k,value in v['expected_default_tool'].items()))
    source_row=next(x for x in insert['operations'] if x['native_id']==source_param['operation_native_id'])
    row=deepcopy(source_row);si=next(x['index'] for x in insert['operation_setups'] if x['native_id']==v['operation_setup_native_id'])
    row.update(native_id=oid,operation_index=insert['operation_setups'][si]['operation_count'],setup_index=si,setup_native_id=v['operation_setup_native_id'],linked_feature_ids=[fid],assigned_tool=deepcopy(default_tool['generic']))
    insert['operations'].append(row);insert['operation_count']+=1;insert['operation_counts'][si]+=1;insert['operation_setups'][si]['operation_count']+=1;insert['selected_operation_setup']['operation_count']+=1
    param=deepcopy(source_param);param.update(operation_native_id=oid,feature_native_id=fid,tool=deepcopy(default_tool));param['levels']['levels']['machining_depth_native']=v['depth_native']
    insert['operation_parameters']=[param];insert['parameter_capture_complete']=True;insert['parameter_batch']=deepcopy(reference['parameter_batch']);pb=insert['parameter_batch'];pb['source_tools']={str(default_tool['generic']['native_id']):deepcopy(default_tool)}
    nc=deepcopy(pb['target_nc'][str(source_param['operation_native_id'])]);nc['operation_native_id']=oid;nc['assigned_tool_native_id']=default_tool['generic']['native_id'];pb['target_nc']={str(oid):nc}
    a.pocket.verify_insert(before,insert,history['original_binding'],oid,fid)
    output_sha='b'*64;saved=deepcopy(insert);saved['document']['needs_save']=False;saved['sketch_state'].update(needs_save=False,saved_file_sha256=output_sha)
    d=dict(test_only_synthetic_completion=True,scope=a.POCKET_SCOPE,action='resume_after_feature',status='review_required',phase='finished',binding=v,request_pin=dict(kind='canonical_binding',sha256=a._digest(v)),authority_pin=loaded['pin'],source_before_sha256=v['expected_source_sha256'],source_after_sha256=output_sha,saved_file_sha256=output_sha,save_hresult=0,new_feature_native_id=fid,new_operation_native_id=oid,new_operations=[row],created_names=history['created_names'],continuation_stage='after_feature',continuation_verified=True,creation_replayed=False,continuation_pins=history['pins'],historical_capture_keys=history['historical_capture_keys'],historical_before=history['historical_before'],historical_after_sketch=history['historical_after_sketch'],historical_after_feature=history['expected_state'],messages=dict(active=False,subscribed=True,disconnected=True,event_count=0),GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,native_dispatch_pending=False)
    d.update({k:True for k in a.FLAGS});d['actions']=[dict(kind='InsertOperation',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,native_result=dict(return_type='pointer',nonnull=True)),dict(kind='SaveActiveDocument',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,native_result=dict(return_type='int',hresult=0))]
    for key,state in [('before',before),('after_insert',insert),('saved',saved)]:d[key]=deepcopy(state);d['confirm_'+key]=deepcopy(state)
    record=pin(tmp_path/'synthetic_completed_from_actual_history.json',d)
    out=a.load_pocket(record['path'],record['sha256'],process_id=v['process_id'],source_path=v['expected_document_path'],source_sha256=output_sha)
    assert out['restore']['new_feature_native_id']==fid and out['restore']['new_operations'][0]['native_id']==oid
    assert out['state']==saved and out['binding']==history['original_binding']
    assert {x['sha256'] for k,x in out['pins'].items() if k.startswith('creation_resume_')}=={x['sha256'] for x in history['pins'].values()}
