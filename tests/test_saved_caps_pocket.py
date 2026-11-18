"""Portable saved-cap source authority and bounded dirty-adoption regressions."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_autodetected_pocket_contract import core,packet,digest,dump,body,messages,change_receipt


def batch(names,payloads):
    return dict(status='success',results=[dict(name=n,outcome={'status':'success'},result={'isError':False,'content':[{'parsed_json':p}]})for n,p in zip(names,payloads)])


@pytest.fixture
def caps_packet(packet,tmp_path):
    v=packet['v'];v['source_variant']='saved_cam_caps'
    cad=tmp_path/'saved_caps.bin';cad.write_bytes(b'CAD cap snapshot before CAM setup');v['caps_saved_sha256']=digest(cad)
    features=packet['sketch']['after']['features'];ref=dict(feature_tree=deepcopy(features),solids=[body()])
    src=dict(process_id=v['process_id'],expected_process_creation_time=v['expected_process_create_time'],expected_document_path=v['expected_document_path'],protected_document_path=v['original_document_path'],protected_source_sha256=v['original_source_sha256'],expected_configuration=v['expected_sw_configuration'])
    caps=dict(scope='EXISTING_CAP_REMAINING_THREE_CONTINUATION_V1',status='caps_observed_ram_only',phase='finished',completed_count=4,adopted_count=1,readback_verified=True,source_unchanged=True,selection_cleanup_verified=True,native_dispatch_pending=False,model_saved=False,CAM_calls=0,source_request=src,actions=[dict(index=i,attempted=True,returned_object=True,pending=False,readback_verified=True)for i in (1,2,3)],profiles_after=[],preflight_profiles=[],after=dict(needs_save=True,features=features,solids=[body()]))
    pin=lambda p:dict(path=str(p),sha256=digest(p))
    geo=dict(scope='FOUR_CAM_MANUFACTURING_CAP_STEP_PROOF_V1',passed=True,stage='FINISHED',inputs_unchanged=True,proof=dict(mode='full',passed=True,whole_body_proof=True,local_proof=True,top_profiles=dict(passed=True,faces=[{}]*4)),boolean_fuzzy_mm=0,healing_applied=False,residual_volume_waiver=False,inputs={'candidate':pin(v['native_geometry_path']),'baseline':pin(cad)},module=pin(cad),reused_sources=[])
    doc=dict(path=v['expected_document_path'],type=1,title=Path(v['expected_document_path']).name)
    inspect=lambda dirty:dict(process_id=v['process_id'],document_count=1,active_document=doc,documents=[dict(doc,needs_save=dirty)])
    sav=batch(['solidworks_connect','solidworks_inspect_open_documents','solidworks_save_document','solidworks_inspect_open_documents'],[{},inspect(True),dict(status='ok',success=True,save_referenced=False,process_id=v['process_id'],document=doc),inspect(False)])
    export=batch(['solidworks_connect','solidworks_continue_existing_sketch_caps','solidworks_export_active','solidworks_inspect_open_documents'],[{},dict(caps,process_id=v['process_id'],runtime_identity={'fixture':True}),dict(status='ok',success=True,format='step',process_id=v['process_id'],document=doc,output_path=v['native_geometry_path']),inspect(True)])
    state=dict(document=dict(doc,needs_save=False),saved_file_sha256=v['caps_saved_sha256'],features=[],feature_setups=[],operation_setups=[],operation_counts=[],operation_count=0,sw_reference=ref)
    inv=dict(process_id=v['process_id'],status='review_required',phase='finished',readback_verified=True,inventory_read_complete=True,mutation_attempted=False,messages=messages(),before=deepcopy(state),after=deepcopy(state))
    rows={'caps':caps,'caps_geometry':geo,'caps_save':sav,'caps_inventory':inv,'caps_export':export}
    for name,row in rows.items():
        p=tmp_path/(name+'.json');v[name+'_receipt_path']=str(p);v[name+'_receipt_sha256']=dump(p,row)
    for label in ('before','after'):packet['setup'][label]['saved_file_sha256']=v['caps_saved_sha256']
    packet['save']['before']={**deepcopy(packet['setup']['after']),'machine_kind':'mill_qualification','process_id':v['process_id']}
    for name in ('setup','save'):
        key='setup_save'if name=='save'else'setup';v[key+'_receipt_sha256']=dump(packet['paths'][name],packet[name])
    packet['sketch']['before']['pid']=999;packet['sketch']['after']['pid']=999
    packet['sketch']['after']['path']=v['original_document_path']
    v['sketch_receipt_sha256']=dump(packet['paths']['sketch'],packet['sketch'])
    packet['caps_rows']=rows
    return packet


def test_saved_caps_accepts_historical_spec_without_relabeling_creator(caps_packet):
    d=core.prepare(caps_packet['v'])
    assert d['caps_data']['historical_circle_role']=='geometry_spec_only'
    assert d['sketch']['after']['pid']==999 and d['request']['process_id']==731
    assert d['caps_data']['baseline']['feature_tree']==caps_packet['caps_rows']['caps']['after']['features']


@pytest.mark.parametrize('row,damage',[('caps',lambda r:r.update(completed_count=3)),('caps_geometry',lambda r:r['proof'].update(whole_body_proof=False)),('caps_geometry',lambda r:r.update(inputs_unchanged=False)),('caps_save',lambda r:r['results'][2]['result']['content'][0]['parsed_json'].update(success=False)),('caps_inventory',lambda r:r['after'].update(saved_file_sha256='0'*64)),('caps_export',lambda r:r['results'][2]['result']['content'][0]['parsed_json'].update(output_path='C:/wrong.step'))])
def test_saved_caps_broken_lineage_is_rejected(caps_packet,row,damage):
    v=caps_packet['v'];r=deepcopy(caps_packet['caps_rows'][row]);damage(r)
    v[row+'_receipt_sha256']=dump(Path(v[row+'_receipt_path']),r)
    with pytest.raises(ValueError):core.prepare(v)


@pytest.mark.parametrize('dirty',[False,True])
def test_post_create_adopts_only_observed_boolean_dirty_flag(dirty):
    original=dict(path='part',title='part',type=1,needs_save=False);observed=dict(original,needs_save=dirty);calls=[]
    ctx=SimpleNamespace(expected=deepcopy(original),r={},identity=lambda:deepcopy(observed),verify_files=lambda:calls.append('files'),check_events=lambda:calls.append('events'),persist=lambda:None)
    core.adopt_created_document(ctx)
    assert ctx.expected==observed and ctx.r['post_create_document_observation']==dict(before=original,after=observed)
    assert calls==['files','events','files','events']


@pytest.mark.parametrize('change',[{'title':'other'},{'path':'other'},{'type':2},{'needs_save':1}])
def test_post_create_does_not_adopt_other_identity_or_loose_bool(change):
    expected=dict(path='part',title='part',type=1,needs_save=False);actual=dict(expected,**change)
    ctx=SimpleNamespace(expected=deepcopy(expected),r={},identity=lambda:actual,verify_files=lambda:None,check_events=lambda:None,persist=lambda:None)
    with pytest.raises(ValueError):core.adopt_created_document(ctx)
    assert ctx.expected==expected and ctx.r['post_create_document_observation']['after']==actual


def test_saved_circle_capture_accepts_only_existing_narrow_mass_noise():
    a=dict(snapshot=dict(features=[],solids=[body()],needs_save=False),circle_readback={'fixed':True})
    b=deepcopy(a);b['snapshot']['solids'][0]['mass_raw'][3]*=1+8.55e-13
    assert core.same_saved_sketch_capture(a,b)
    b['snapshot']['solids'][0]['box_m'][0]+=1e-12
    assert not core.same_saved_sketch_capture(a,b)
