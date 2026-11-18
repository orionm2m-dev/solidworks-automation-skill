"""Definition-only GOP contract; native boundary is mocked throughout."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_pocket_definition_context as d
from scripts import sw_cam_mill_feature_process as cam
from test_sw_cam_mill_feature_process import probe
from test_mcp_cam_mill_feature_plan import context, core, params, server

def state():
    return dict(document=dict(path='C:/cad/p.sldprt',title='p.sldprt',type=1,needs_save=False),saved_file_sha256='a'*64,
        feature_setups=[dict(native_id=64,feature_ids=[111])],selected_feature=dict(native_id=111,island_count=4),
        operation_setups=[],operations=[],operation_count=0,generated_operation_count=0,total_record_count=0,
        unique_tool_count=0,operation_setup_count=0,operation_counts=[],definition_authority=dict(geometry_unqualified=True))
def after(a):
    b=deepcopy(a);b.update(operation_setups=[dict(index=0,native_id=70,operation_count=1)],operation_count=1,unique_tool_count=1,operation_setup_count=1,operation_counts=[1])
    b['operations']=[dict(setup_index=0,operation_index=0,setup_native_id=70,native_id=201,mill_operation_type=3,base_operation_type=1,
        linked_feature_ids=[111],all_linked_features_observed=True,suppressed=False,toolpath_generated=False,toolpath_record_counts=[],
        assigned_tool=dict(native_id=501,is_mill_tool=True,native_read_complete=True,tool_type_raw=2,cut_diameter_native=8.,protrusion_native=30.))]
    return b

def test_complete_draft_inventory_only():
    a=state();b=after(a);assert d.verify_delta(a,b,111)==b['operations'];assert b['total_record_count']==0

@pytest.mark.parametrize('change',[
    lambda b:b['operations'][0].update(linked_feature_ids=[112]),lambda b:b['operations'][0].update(toolpath_generated=True),
    lambda b:b['operations'][0].update(toolpath_record_counts=[1]),lambda b:b['operations'][0].update(suppressed=True),
    lambda b:b['operations'][0].update(setup_native_id=71),lambda b:b['operations'][0].update(operation_index=1),
    lambda b:b['operations'][0]['assigned_tool'].update(native_id=True),lambda b:b['operations'][0]['assigned_tool'].update(native_read_complete=False),
    lambda b:b['operations'][0]['assigned_tool'].update(is_mill_tool=False),lambda b:b['selected_feature'].update(island_count=3),
    lambda b:b.update(saved_file_sha256='b'*64),lambda b:b['document'].update(title='wrong.sldprt'),
    lambda b:b.update(unique_tool_count=2),lambda b:b.update(generated_operation_count=1),lambda b:b.update(total_record_count=1),
    lambda b:b['feature_setups'][0].update(native_id=65),lambda b:b.update(operation_count=2),
])
def test_rejects_unrequested_delta_or_partial_inventory(change):
    a=state();b=after(a);change(b)
    with pytest.raises(ValueError):d.verify_delta(a,b,111)

@pytest.mark.parametrize('kwargs',[
    dict(feature_kind='open_pocket',definition_recovery_receipt_path='C:/proof.json'),
    dict(feature_kind='autodetected_pocket'),
    dict(feature_kind='autodetected_pocket',definition_recovery_receipt_path='relative.json',definition_recovery_receipt_sha256='a'*64,definition_save_receipt_path='C:/evidence/saved.json',definition_save_receipt_sha256='b'*64),
    dict(feature_kind='autodetected_pocket',definition_recovery_receipt_path='C:/proof.json',definition_recovery_receipt_sha256='a'*64,circle_creation_receipt_path='C:/old.json'),
])
def test_authority_union_is_explicit(kwargs):
    with pytest.raises(ValueError):d.validate_request(**kwargs)

def test_marker_prevents_new_receipt_replay(tmp_path):
    c=dict(marker=tmp_path/'consumed.json',pins=[],evidence=dict(sha256='a'*64),expected_feature_native_id=111)
    path=d.claim(c,tmp_path/'first.json','b'*64);assert json.loads(Path(path).read_text(encoding='utf-8'))['feature_native_id']==111
    with pytest.raises(ValueError):d.claim(c,tmp_path/'second.json','b'*64)

@pytest.fixture
def definition_probe(probe,monkeypatch):
    p=probe;p.current['document']['needs_save']=False
    c=dict(saved_transition=dict(document=deepcopy(p.current['document'])),marker=p.tmp_path/'consumed.json',pins=[],evidence=dict(sha256='a'*64),expected_feature_native_id=111)
    monkeypatch.setattr(d,'load',lambda **kw:c)
    monkeypatch.setattr(d,'identity',lambda sw,c:dict(document=deepcopy(p.current['document']),saved_file_sha256=cam._file_hash(p.path)))
    def capture(sw,clsid,tlb,context,check,diagnostic):
        x,n=p.captures(sw,check=check,diagnostic=diagnostic)
        x.update(operation_setups=[dict(index=0,native_id=70,operation_count=len(x['operations']))],operation_count=len(x['operations']),generated_operation_count=0,total_record_count=0,unique_tool_count=1 if x['operations'] else 0)
        for row in x['operations']:
            row.update(setup_native_id=70,all_linked_features_observed=True,assigned_tool=dict(native_id=501,is_mill_tool=True,native_read_complete=True,tool_type_raw=2,cut_diameter_native=8.,protrusion_native=30.))
        return x,n
    monkeypatch.setattr(d,'capture',capture)
    kw=dict(feature_kind='autodetected_pocket',definition_recovery_receipt_path=str(p.tmp_path/'creator.json'),definition_recovery_receipt_sha256='a'*64,definition_save_receipt_path='C:/evidence/saved.json',definition_save_receipt_sha256='b'*64)
    return p,c,kw

def test_existing_lifecycle_runs_one_retain_gop_from_recovered_saved_definition(definition_probe):
    p,c,kw=definition_probe;prepared=p.run('prepare',**kw);assert prepared['apply_eligible']
    result=p.run(expected_state_sha256=prepared['state_sha256'],**kw)
    assert result['status']=='review_required' and result['readback_verified'] and result['insertion_delta_verified']
    assert result['before']['document']['needs_save'] is False and c['marker'].exists()
    p.feature.GenerateOpPlan.assert_called_once_with(1)
    assert not result['model_saved'] and not result['GTP_attempted'] and not result['physical_depth_verified'] and result['geometry_unqualified']
    assert len(result['new_operations'])==2 and all(r['assigned_tool']['native_id']==501 for r in result['new_operations'])

def test_unknown_dirty_not_general_permission(probe):
    probe.current['document']['needs_save']=True
    result=probe.run('prepare');assert not result['apply_eligible'];probe.feature.GenerateOpPlan.assert_not_called()

def test_consumed_definition_attempt_cannot_replay(definition_probe):
    p,c,kw=definition_probe;c['marker'].write_text('{}',encoding='utf-8')
    result=p.run('prepare',**kw);assert not result['apply_eligible'];p.feature.GenerateOpPlan.assert_not_called()

def test_only_gop_schema_accepts_new_authority(context,core):
    p=params(context,feature_kind='autodetected_pocket',definition_recovery_receipt_path='C:/evidence/creator.json',definition_recovery_receipt_sha256='a'*64,definition_save_receipt_path='C:/evidence/saved.json',definition_save_receipt_sha256='b'*64)
    server.solidworks_cam_qualify_mill_feature_operation_plan(p)
    assert core.call_args.kwargs['feature_kind']=='autodetected_pocket'
    with pytest.raises(ValueError):server.SolidWorksCamSelectedFeatureContextInput(feature_kind='autodetected_pocket')

@pytest.mark.parametrize('change',[
    dict(definition_recovery_receipt_path=None),dict(definition_recovery_receipt_sha256=None),dict(definition_save_receipt_path=None),dict(definition_save_receipt_sha256=None),dict(circle_creation_receipt_path=None),dict(circle_creation_receipt_sha256='b'*64)])
def test_schema_requires_new_definition_only_union(context,change):
    kw=dict(feature_kind='autodetected_pocket',definition_recovery_receipt_path='C:/evidence/creator.json',definition_recovery_receipt_sha256='a'*64,definition_save_receipt_path='C:/evidence/saved.json',definition_save_receipt_sha256='b'*64);kw.update(change)
    with pytest.raises(ValueError):params(context,**kw)

def test_legacy_schema_rejects_definition_fields_even_none(context):
    with pytest.raises(ValueError):params(context,definition_recovery_receipt_path=None)


def saved_authority():
    a=state()['document'];a['needs_save']=True
    v=dict(process_id=123,expected_document_path=a['path'],expected_source_sha256='a'*64,expected_axis_native=[0.,0.,-1.],expected_origin_native=[0.,0.,0.])
    recovered=dict(old=dict(status='uncertain',request=v,document_before=deepcopy(a)),header=dict(native_id=111,owner_setup_native_id=64))
    before=dict(document=deepcopy(a),saved_file_sha256='a'*64,current_machine=dict(machine_type=1),machine_kind='mill_qualification',process_id=123,operation_counts=[0],feature_setups=[dict(native_id=64,feature_count=1,axis_native=v['expected_axis_native'],origin_native=v['expected_origin_native'])])
    final=deepcopy(before);final['document']['needs_save']=False;final['saved_file_sha256']='b'*64
    save=dict(status='review_required',phase='finished',action='save',machine_kind='mill_qualification',process_id=123,message_policy='vendor_default',native_return_type='int',native_return_value=0,native_hresult=0,native_outcome='save_returned_readback_verified',before=before,after=final,final_state=deepcopy(final),state_sha256=d._digest(final),after_cleanup_sw_file=dict(document=deepcopy(final['document']),saved_file_sha256='b'*64),messages=dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]))
    for key in ('mutation_attempted','native_call_attempted','native_call_returned','native_save_call_returned','save_readback_verified','saved_file_changed'):save[key]=True
    for key in ('native_dispatch_pending','native_close_call_returned','close_verified','persistence_verified','generation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','post_cleanup_CAM_getters'):save[key]=False
    return recovered,save

def verify_save(rec,save):return d.verify_saved_transition(rec,save,process_id=123,expected_document_path='C:/cad/p.sldprt',expected_source_sha256='b'*64,expected_feature_native_id=111)

def test_explicit_zero_op_save_binds_new_source_without_changing_raw_uncertain():
    rec,save=saved_authority();original=deepcopy(rec);out=verify_save(rec,save)
    assert out['source_before_sha256']=='a'*64 and out['source_after_sha256']=='b'*64
    assert out['document']['needs_save']is False and not out['persistence_verified'] and rec==original and rec['old']['status']=='uncertain'

@pytest.mark.parametrize('key,value',[
    ('status','uncertain'),('save_readback_verified',False),('native_return_value',True),('native_hresult',False),('native_return_type','bool'),
    ('saved_file_changed',False),('native_save_call_returned',False),('native_dispatch_pending',True),('persistence_verified',True),
    ('generation_attempted',True),('GOP_attempted',True),('GTP_attempted',True),('native_close_call_returned',True),('process_id',124),
    ('state_sha256','c'*64),('issue',{'type':'failure'}),('runtime_error',{'type':'changed'}),
])
def test_saved_authority_rejects_unqualified_or_wrong_native_save(key,value):
    rec,save=saved_authority();save[key]=value
    with pytest.raises(ValueError):verify_save(rec,save)

@pytest.mark.parametrize('change',[
    lambda r,s:s['before'].update(saved_file_sha256='c'*64),
    lambda r,s:s['before']['document'].update(needs_save=False),
    lambda r,s:s['after']['document'].update(needs_save=True),
    lambda r,s:s['before']['feature_setups'][0].update(feature_count=0),
    lambda r,s:s['before']['feature_setups'][0].update(native_id=65),
    lambda r,s:s['before'].update(operation_counts=[1]),
    lambda r,s:s['before'].update(operation_counts=[False]),
    lambda r,s:s['messages'].update(event_count=1),
    lambda r,s:r['old']['request'].update(process_id=124),
    lambda r,s:r['header'].update(native_id=112),
    lambda r,s:r['header'].update(owner_setup_native_id=65),
    lambda r,s:s['after_cleanup_sw_file'].update(saved_file_sha256='a'*64),
])
def test_saved_authority_rejects_wrong_history_or_extra_changes(change):
    rec,save=saved_authority();change(rec,save)
    with pytest.raises(ValueError):verify_save(rec,save)


@pytest.fixture
def file_authority(tmp_path,monkeypatch):
    rec,save=saved_authority();target=tmp_path/'qualification.sldprt';target.write_bytes(b'new saved definition')
    oldsha='a'*64;newsha=d._file_hash(target)
    protected=tmp_path/'original.sldprt';protected.write_bytes(b'immutable original')
    def pin(path):return dict(path=str(path),sha256=d._file_hash(path))
    rec['old']['request']['expected_document_path']=str(target)
    rec['old']['document_before']['path']=str(target)
    for key in ('before','after','final_state'):
        save[key]['document']['path']=str(target)
        if key!='before':save[key]['saved_file_sha256']=newsha
    save['after_cleanup_sw_file']=dict(document=deepcopy(save['after']['document']),saved_file_sha256=newsha)
    save['state_sha256']=d._digest(save['after'])
    proofs=[]
    for name in ('creator.json','marker.json','recovery.json'):
        path=tmp_path/name;path.write_text('{}',encoding='utf-8');proofs.append(pin(path))
    rec.update(creator_pin=proofs[0],marker_pin=proofs[1],receipt_pin=proofs[2],pins=[dict(path=str(target),sha256=oldsha),pin(protected)],
        expected_inventory=dict(sw_reference=dict(feature_tree=[dict(name='exact observed attribute',type='Attribute')])) ,
        sketch=dict(after=dict(path=str(target),saved_file_sha256=oldsha,needs_save=True,features=[dict(name='profile',type='ProfileFeature')])),spec={})
    savepath=tmp_path/'save.json';savepath.write_text(json.dumps(save),encoding='utf-8')
    monkeypatch.setattr(d,'_read_recovery',lambda path,sha:deepcopy(rec))
    args=dict(process_id=123,expected_document_path=str(target),expected_source_sha256=newsha,expected_feature_native_id=111,
        definition_recovery_receipt_path=proofs[2]['path'],definition_recovery_receipt_sha256=proofs[2]['sha256'],definition_save_receipt_path=str(savepath),definition_save_receipt_sha256=d._file_hash(savepath))
    return rec,save,target,protected,args

def test_loader_replaces_only_current_target_pin_and_preserves_raw_history(file_authority):
    rec,save,target,protected,args=file_authority;original=deepcopy(rec);loaded=d.load(**args)
    assert rec==original and loaded['creator']['status']=='uncertain'
    assert all(p['sha256']==args['expected_source_sha256']for p in loaded['pins']if d.creator.same_path(p['path'],str(target)))
    assert loaded['historical_target_pins']==[dict(path=str(target),sha256='a'*64)]
    assert loaded['current_sketch_baseline']['features']==rec['expected_inventory']['sw_reference']['feature_tree']
    assert loaded['current_sketch_baseline']['needs_save']is False and rec['sketch']['after']['needs_save']is True
    protected.write_bytes(b'tampered')
    with pytest.raises(ValueError):d.verify_files(loaded)

@pytest.mark.parametrize('change',['missing_historical_target','wrong_historical_sha','wrong_current_sha'])
def test_loader_refuses_unproved_target_transition(file_authority,change):
    rec,save,target,protected,args=file_authority
    if change=='missing_historical_target':rec['pins']=rec['pins'][1:]
    elif change=='wrong_historical_sha':rec['pins'][0]['sha256']='c'*64
    else:args['expected_source_sha256']='c'*64
    with pytest.raises(ValueError):d.load(**args)
