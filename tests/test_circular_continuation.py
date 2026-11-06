from copy import deepcopy
from pathlib import Path
import hashlib,json,ast
import pytest
from scripts import sw_cam_current_circular_authority as a
from scripts import sw_cam_current_saved_generation as g
from scripts import sw_cam_current_saved_parameter_batch as batch
from scripts import sw_cam_current_saved_parameter_fields as f
from scripts.sw_cam_current_circular_continuation import CircularGenerationProof,CircularGenerationContext
from test_current_circular_pocket import fixture,sketch_state,feature_state,insert_state,saved_state
from test_current_saved_parameter_fields import actual_change


def pin(path,value):
    path.write_text(json.dumps(value),encoding='utf-8');return a.read_pin(str(path),hashlib.sha256(path.read_bytes()).hexdigest())[1]


@pytest.fixture
def completed(tmp_path,monkeypatch):
    v,loaded,before=fixture(tmp_path)
    monkeypatch.setattr(batch,'load_inputs',lambda binding,clsid=None:dict(authority=dict(definition_mode='selected_continue')))
    original=pin(tmp_path/'original.json',dict(kind='synthetic_original_authority'))
    loaded['pin']=original;v.update(configuration_receipt_path=original['path'],configuration_receipt_sha256=original['sha256'])
    def original_loader(path,sha,**kw):
        assert path==original['path'] and sha==original['sha256'] and kw['source_sha256']=='a'*64 and kw['selected_ids']==[10]
        return deepcopy(loaded)
    monkeypatch.setattr(g,'load_completed_configuration',original_loader)
    sketch=sketch_state(before,v);feature=feature_state(sketch,v);insert=insert_state(feature,v);saved=saved_state(insert)
    b={k:deepcopy(x) for k,x in v.items() if k not in {'action','receipt_path','attempt_registry_path','prepare_receipt_path','prepare_receipt_sha256'}}
    d=dict(scope=a.POCKET_SCOPE,action='apply',status='review_required',phase='finished',binding=b,request_pin=dict(kind='canonical_binding',sha256=a._digest(b)),authority_pin=original,source_before_sha256='a'*64,source_after_sha256='b'*64,saved_file_sha256='b'*64,save_hresult=0,new_feature_native_id=22,new_operation_native_id=13,new_operations=[deepcopy(insert['operations'][-1])],created_names=['BOUND_PLANE','BOUND_CIRCLE'],actions=[],messages=dict(active=False,subscribed=True,disconnected=True,event_count=0),GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,native_dispatch_pending=False)
    d.update({k:True for k in a.FLAGS})
    for key,state in [('before',before),('after_sketch',sketch),('after_feature',feature),('after_insert',insert),('saved',saved)]:d[key]=deepcopy(state);d['confirm_'+key]=deepcopy(state)
    for kind in ['CreateSketch','CreateMillFeature2','InsertOperation','SaveActiveDocument']:
        value=dict(return_type='int',hresult=0) if kind=='SaveActiveDocument' else dict(return_type='pointer',nonnull=True)
        d['actions'].append(dict(kind=kind,attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,native_result=value))
    def load(value=None):
        p=pin(tmp_path/'pocket.json',d if value is None else value)
        return a.load_pocket(p['path'],p['sha256'],process_id=123,source_path=v['expected_document_path'],source_sha256='b'*64)
    return dict(v=v,loaded=loaded,before=before,receipt=d,load=load,path=tmp_path)


def test_completed_pocket_uses_real_geometry_delta_and_honest_reference(completed):
    out=completed['load']();assert out['state']==completed['receipt']['saved'] and out['restore']['new_feature_native_id']==22
    assert out['original']['state']==completed['loaded']['state'] and out['restore']['new_operations'][0]['native_id']==13


@pytest.mark.parametrize('key',a.FLAGS)
def test_pocket_false_completed_flag(completed,key):
    d=deepcopy(completed['receipt']);d[key]=False
    with pytest.raises(ValueError):completed['load'](d)


@pytest.mark.parametrize('defect',['pending','savebool','saveaction','actionorder','newid','oldpath','refnc','bottomsign','statehash','oldsource','lifetime','dirty','unequal','error'])
def test_partial_or_drifted_creation_rejected(completed,defect):
    d=deepcopy(completed['receipt'])
    if defect=='pending':d['native_dispatch_pending']=True
    elif defect=='savebool':d['save_hresult']=True
    elif defect=='saveaction':d['actions'][-1]['native_result']['hresult']=None
    elif defect=='actionorder':d['actions'].reverse()
    elif defect=='newid':d['new_feature_native_id']=20
    elif defect=='oldpath':d['after_insert']['operations'][2]['toolpath_record_counts']=[100];d['confirm_after_insert']=deepcopy(d['after_insert'])
    elif defect=='refnc':d['before']['reference_parameter_observation']['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']=1.;d['confirm_before']=deepcopy(d['before'])
    elif defect=='bottomsign':
        for key in ('after_feature','confirm_after_feature'):d[key]['target_geometry']['bottom_curves_native'][0]['centre_native']=[0.,0.,0.]
    elif defect=='statehash':d['saved']['sketch_state']['saved_file_sha256']='e'*64;d['confirm_saved']=deepcopy(d['saved'])
    elif defect=='oldsource':d['source_before_sha256']='f'*64
    elif defect=='lifetime':d['binding']['expected_process_create_time']+=1;d['request_pin']['sha256']=a._digest(d['binding'])
    elif defect=='dirty':d['saved']['sketch_state']['needs_save']=True;d['confirm_saved']=deepcopy(d['saved'])
    elif defect=='unequal':d['confirm_saved']['target_header']['depth_native']+=1
    else:d['issue']={}
    with pytest.raises((ValueError,AssertionError)):completed['load'](d)


def config_values(completed,dependent=True):
    loaded=completed['load']();state=loaded['state'];tmp=completed['path'];source=Path(completed['v']['expected_document_path']);source.write_bytes(b'synthetic saved circular part')
    # 文件摘要检查单独测试；此 fixture 的历史 digest 仍明确标为 synthetic。
    recipe=dict(schema_version=1,rows=[dict(operation_native_id=13,feature_native_id=22,operation_type=0,expected_tool_native_id=30,existing_tool_native_id=32,fields=[dict(field='side_allowance',expected=1.,new=0.),dict(field='floor_allowance',expected=1.,new=0.),dict(field='first_depth',expected=[False,10.],new=[False,.3])])])
    rp=pin(tmp/'recipe.json',recipe)
    v=dict(configuration_mode=a.MODE,process_id=123,expected_process_create_time=100.25,expected_document_path=str(source),expected_source_sha256='b'*64,pocket_receipt_path=loaded['pin']['path'],pocket_receipt_sha256=loaded['pin']['sha256'],expected_feature_native_id=22,parameter_operation_native_ids=[13],candidate_tool_native_id=32,expected_candidate_consumer_ids=[],recipe_path=rp['path'],recipe_sha256=rp['sha256'],dependent_readbacks=[dict(operation_native_id=13,member='DepthAllow',expected=1.,new=0.)] if dependent else[],action='prepare',save_after_verified=False,acknowledge_qualification_only=True,prepare_receipt_path=None,prepare_receipt_sha256=None,attempt_registry_path=str(tmp),receipt_path=str(tmp/'params_prepare.json'))
    return v,a.load_inputs(v),recipe


def test_single_rough_plan_and_declared_dependency(completed):
    v,data,recipe=config_values(completed)
    assert data['plan']==recipe and len(data['baseline']['operation_parameters'])==1
    assert data['authority']['definition_mode']=='selected_continue'


@pytest.mark.parametrize('defect',['member','op','expected','new','integer','duplicate'])
def test_dependent_readback_is_exact_request_not_global_alias(completed,defect):
    v,data,recipe=config_values(completed);decl=deepcopy(v['dependent_readbacks'])
    if defect=='member':decl[0]['member']='Anything'
    elif defect=='op':decl[0]['operation_native_id']=10
    elif defect=='expected':decl[0]['expected']=.2
    elif defect=='new':decl[0]['new']=.2
    elif defect=='integer':decl[0]['new']=0
    else:decl+=deepcopy(decl)
    with pytest.raises(ValueError):a.dependencies(data['baseline'],recipe,decl)


def configured_after(before,recipe,candidate,*,alias=True):
    after=deepcopy(before);row=recipe['rows'][0];param=after['operation_parameters'][0]
    next(x for x in after['operations'] if x['native_id']==13)['assigned_tool']=deepcopy(candidate['generic']);param['tool']=deepcopy(candidate)
    pb=after['parameter_batch'];pb['source_tools']={'32':deepcopy(candidate)};pb['candidate_consumer_ids']=[13];pb['candidate_consumers']['13']=dict(deepcopy(pb['target_nc']['13']),assigned_tool_native_id=32)
    for change in row['fields']:actual_change(param,change['field'],change['new'])
    if alias:f._replace_observed(param,'depth','DepthAllow',0.)
    after['document']['needs_save']=True;after['sketch_state']['needs_save']=True
    return after


def test_only_declared_current_circular_observation_accepted(completed):
    v,data,recipe=config_values(completed);before=data['baseline'];candidate=before['parameter_batch']['candidate_tool'];after=configured_after(before,recipe,candidate)
    a.CircularParameterProof(v['dependent_readbacks']).verify_final(before,after,recipe,{32:candidate})
    with pytest.raises(ValueError):a.CircularParameterProof([]).verify_final(before,after,recipe,{32:candidate})
    with pytest.raises(ValueError):f.verify_final(a.normalized(before),a.normalized(after),recipe,{32:candidate})


@pytest.mark.parametrize('defect',['old_nc','candidate','old_path','geometry','other_alias','hash'])
def test_declared_dependency_preserves_every_other_observation(completed,defect):
    v,data,recipe=config_values(completed);before=data['baseline'];candidate=before['parameter_batch']['candidate_tool'];after=configured_after(before,recipe,candidate)
    if defect=='old_nc':after['reference_parameter_observation']['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']=11.
    elif defect=='candidate':after['parameter_batch']['candidate_tool']['mill']['length']=100.
    elif defect=='old_path':after['operations'][2]['toolpath_record_counts']=[100]
    elif defect=='geometry':after['target_header']['depth_native']=3.
    elif defect=='other_alias':after['operation_parameters'][0]['rough']['entry']['GetSpiralRadius']['raw']=4.
    else:after['sketch_state']['saved_file_sha256']='e'*64
    with pytest.raises(ValueError):a.CircularParameterProof(v['dependent_readbacks']).verify_final(before,after,recipe,{32:candidate})


def test_generation_circular_save_transition_and_old_nc_protection(completed):
    before=completed['receipt']['saved'];after=deepcopy(before);after['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[31]);after['document']['needs_save']=True;after['sketch_state']['needs_save']=True
    class Backend:source='b'*64
    backend=Backend();proof=CircularGenerationProof(backend)
    proof.verify_generation(before,after,[13],[13]);saved=deepcopy(after);saved['document']['needs_save']=False;saved['sketch_state'].update(needs_save=False,saved_file_sha256='c'*64);backend.source='c'*64
    proof.verify_saved(after,saved);assert proof.save_comparison_state(after)==proof.save_comparison_state(saved)
    assert len(proof.cl_rows(before,saved,[13],completed_ids=[13]))==2
    saved['reference_parameter_observation']['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']=0.
    with pytest.raises(ValueError):proof.verify_saved(after,saved)


def test_native_adapter_partial_capture_is_preserved(monkeypatch):
    from scripts.sw_cam_current_circular_context import NativeCircularContext
    obj=object.__new__(CircularGenerationContext);obj.report={};obj.consumer_ids=[];obj.attempted=[13];obj.persist=lambda:None
    def fail(self,label,*args,**kw):
        assert kw==dict(attempted_generation_ids=(13,));self.report[label]=dict(capture_complete=False,actual_returned='kept');raise ValueError('safe stop')
    monkeypatch.setattr(NativeCircularContext,'capture',fail);partial={}
    with pytest.raises(ValueError):obj.capture('after',partial)
    assert partial==dict(capture_complete=False,actual_returned='kept')


def test_actual_completed_configuration_binding_has_no_definition_mode():
    import os
    external=os.environ.get('SW_CAM_TEST_COMPLETED_PARAMETER_RECEIPT')
    if not external:pytest.skip('Optional external evidence path is not configured')
    path=Path(external)
    if not path.is_file():pytest.skip('Optional external evidence file is unavailable')
    receipt=json.loads(path.read_text(encoding='utf-8-sig'))
    assert 'definition_mode' not in receipt['binding']
    actual=batch.load_inputs(receipt['binding'])
    assert actual['authority']['definition_mode']=='selected_continue'
