"""True creator/recovery distinction and observed CAM Save dirty binding."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_pocket_definition_context as d
from test_autodetected_pocket_contract import core as creator,packet,body,inventory,header,dump,messages
from test_saved_caps_pocket import caps_packet
from test_definition_gop_context import saved_authority,verify_save


@pytest.fixture
def genuine_creator(caps_packet):
    v=caps_packet['v'];prepared=creator.prepare(v);before=inventory();before['capture_complete']=True
    before['sw_reference']=deepcopy(prepared['caps_data']['baseline']);before['all_solid_body_count']=1
    after=deepcopy(before);after['feature_count']=1;after['features']=[dict(native_id=999,setup_native_id=408)];after['feature_setups'][0]['feature_ids']=[999]
    h=dict(header(),taper_angle_native=0.)
    document=dict(path=v['expected_document_path'],title=Path(v['expected_document_path']).name,type=1,needs_save=False)
    snapshot=dict(pid=v['process_id'],path=v['expected_document_path'],saved_file_sha256=v['expected_source_sha256'],needs_save=False,features=deepcopy(before['sw_reference']['feature_tree']),solids=[body()],planes=[],spec=v['sketch_spec'])
    circle={'entities':[{'type':'circle'}]};observed=dict(snapshot=snapshot,circle_readback=circle,native_diagnostic={},sketch_plane_geometry={'origin_m':[0,0,.0258],'normal':[0,0,1]})
    raw=dict(scope=creator.SCOPE,status='definition_only',phase='finished',request=deepcopy(v),receipt_path=str(prepared['receipt']),marker_path=str(prepared['marker']),before=before,before_confirmation=deepcopy(before),after=after,after_confirmation=deepcopy(after),feature_header=h,new_feature_native_id=999,definition_proof=creator.verify_delta(before,after,h,v),messages=messages(),document_before=document,post_create_document_observation=dict(before=deepcopy(document),after=deepcopy(document)),circle_readback=circle,saved_caps_sketch_checks=[dict(before=deepcopy(observed),after=deepcopy(observed),readback_verified=True)])
    for label in ('before','before_confirmation','after','after_confirmation'):raw[label+'_diagnostic']={'capture_complete':True}
    for k in ('dispatch_claimed','native_call_attempted','native_call_returned','native_return_nonnull','auto_detect_islands_requested',*creator.FLAGS):raw[k]=True
    for k in ('native_dispatch_pending','Save_attempted','GOP_attempted','GTP_attempted','AFR_attempted','Import_attempted','model_saved','island_geometry_getter_attempted','automatic_replay','production_qualified','island_geometry_verified','physical_depth_verified','feature_association_verified','machining_eligible'):raw[k]=False
    raw['evidence_pins']=prepared['pins']+[dict(path=creator.__file__,sha256=creator._file_hash(creator.__file__))]
    dump(prepared['marker'],dict(scope=creator.SCOPE,request_digest=d._digest(v),receipt_path=raw['receipt_path'],source_sha256=v['expected_source_sha256'],automatic_replay=False))
    digest=dump(prepared['receipt'],raw)
    return prepared['receipt'],digest,raw


def test_true_creator_is_loaded_without_fabricating_recovery(genuine_creator,monkeypatch):
    from scripts import sw_cam_autodetected_pocket_recovery as recovery
    p,sha,raw=genuine_creator
    monkeypatch.setattr(recovery,'verify_recovery_receipt',lambda *args:pytest.fail('creator relabeled as recovery'))
    before=p.read_bytes();result=d._read_recovery(str(p),sha)
    assert result['origin_kind']=='creator' and result['old']['status']=='definition_only'
    assert result['receipt']==raw and result['creator_pin']==result['receipt_pin'] and p.read_bytes()==before
    assert result['sketch']['after']['pid']==999 and d.definition_sketch_baseline(result)['pid']==731


@pytest.mark.parametrize('damage',['status','pending','event','count','marker','inline','claim'])
def test_failed_or_mismatched_creator_never_becomes_authority(genuine_creator,damage):
    p,sha,raw=genuine_creator;r=deepcopy(raw)
    if damage=='status':r['status']='uncertain'
    if damage=='pending':r['native_dispatch_pending']=True
    if damage=='event':r['messages']['event_count']=1
    if damage=='count':r['feature_header']['island_count']=3
    if damage=='marker':Path(r['marker_path']).write_text('{}',encoding='utf-8')
    if damage=='inline':r['saved_caps_sketch_checks'][0]['after']['snapshot']['features']=[]
    if damage=='claim':r['production_qualified']=True
    sha=dump(p,r)
    with pytest.raises(ValueError):d.read_creator_receipt(str(p),sha)


def test_real_recovery_scope_still_uses_its_original_verifier(tmp_path,monkeypatch):
    from scripts import sw_cam_autodetected_pocket_recovery as recovery
    p=tmp_path/'recovered.json';sha=dump(p,{'scope':recovery.SCOPE});seen=[]
    monkeypatch.setattr(recovery,'verify_recovery_receipt',lambda *args:seen.append(args) or {'old':{'status':'uncertain'}})
    r=d._read_recovery(str(p),sha)
    assert r['origin_kind']=='recovery' and r['old']['status']=='uncertain' and seen==[(str(p),sha)]


@pytest.mark.parametrize('dirty',[False,True])
def test_saved_caps_definition_save_uses_actual_dirty_boolean(dirty):
    recovered,saved=saved_authority();raw=recovered['old'];raw['request']['source_variant']='saved_cam_caps'
    clean=dict(raw['document_before'],needs_save=False);actual=dict(clean,needs_save=dirty)
    raw['document_before']=clean;raw['post_create_document_observation']=dict(before=deepcopy(clean),after=actual)
    saved['before']['document']['needs_save']=dirty
    result=verify_save(recovered,saved)
    assert result['document']['needs_save'] is False and not result['persistence_verified']
    saved['before']['document']['needs_save']=not dirty
    with pytest.raises(ValueError):verify_save(recovered,saved)
