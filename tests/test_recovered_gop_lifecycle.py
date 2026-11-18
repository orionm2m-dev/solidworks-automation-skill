"""Existing Save flow with explicit recovered/GOP authority; no native CAD."""
from copy import deepcopy
import json,sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_pocket_definition_context as definition
from scripts import sw_cam_mill_feature_lifecycle as lifecycle
from scripts import sw_cam_lifecycle as entry
from test_sw_cam_mill_feature_lifecycle import probe
from test_mcp_cam_mill_feature_lifecycle import context,core,feature_params,server

@pytest.fixture
def recovered_probe(probe,monkeypatch):
    p=probe
    pins=[]
    for name in ('gop.json','marker.json'):
        path=p.tmp_path/name;path.write_text('{}',encoding='utf-8');pins.append(dict(path=str(path),sha256=lifecycle._file_hash(path)))
    ctx=dict(expected_document_path=str(p.path),expected_source_sha256=lifecycle._file_hash(p.path),pins=[dict(path=str(p.path),sha256=lifecycle._file_hash(p.path))],current_sketch_baseline=dict(saved_file_sha256=lifecycle._file_hash(p.path)))
    plan=dict(after=deepcopy(p.current),gop_pin=pins[0],marker_pin=pins[1],operation_ids=[77])
    monkeypatch.setattr(definition,'load',lambda **kw:deepcopy(ctx))
    def identity(sw,c):
        if lifecycle._file_hash(p.path)!=c['expected_source_sha256']:raise ValueError('current source differs')
        return dict(document=deepcopy(p.current['document']),saved_file_sha256=c['expected_source_sha256'])
    monkeypatch.setattr(definition,'identity',identity)
    monkeypatch.setattr(definition,'capture',lambda sw,clsid,tlb,c,check,diagnostic:p.snapshots(sw,expected_feature_native_id=55,check=check,diagnostic=diagnostic))
    reader=Mock(return_value=plan);monkeypatch.setitem(sys.modules,'scripts.sw_cam_pocket_gop_evidence',N(read_gop_receipt=reader))
    options=dict(feature_kind='autodetected_pocket',expected_source_sha256=ctx['expected_source_sha256'],definition_recovery_receipt_path='C:/proof/recovery.json',definition_recovery_receipt_sha256='a'*64,definition_save_receipt_path='C:/proof/saved.json',definition_save_receipt_sha256='b'*64,definition_gop_receipt_path=pins[0]['path'],definition_gop_receipt_sha256=pins[0]['sha256'])
    return p,ctx,plan,reader,options

def test_one_existing_save_preserves_exact_gop_inventory(recovered_probe):
    p,ctx,plan,reader,options=recovered_probe;result=p.run(**options)
    assert result['status']=='review_required' and result['save_readback_verified'] and not result['persistence_verified']
    assert result['after']['operations']==plan['after']['operations'] and not result['generation_attempted']
    assert result['saved_file_sha256_after_native_return']==lifecycle._file_hash(p.path)!=ctx['expected_source_sha256']
    assert result['before']['saved_file_sha256']==ctx['expected_source_sha256'] and ctx['pins'][0]['sha256']==ctx['expected_source_sha256']
    assert result['geometry_unqualified'] and not result['physical_depth_verified'] and not result['production_qualified']
    p.app.SaveActiveDocument.assert_called_once_with();p.app.CloseActiveDocument.assert_not_called();reader.assert_called_once()
    assert json.loads(p.receipt.read_text(encoding='utf-8'))==result

def test_prepare_never_saves_and_exact_ids_are_passed_to_verifier(recovered_probe):
    p,ctx,plan,reader,options=recovered_probe;result=p.run('prepare',**options)
    assert result['status']=='ok' and not p.receipt.exists();p.app.SaveActiveDocument.assert_not_called()
    assert reader.call_args.args[-1]==[77]

@pytest.mark.parametrize('failure',['operation','tool','feature','event'])
def test_immediate_native_return_and_new_hash_survive_failed_readback(recovered_probe,failure):
    p,ctx,plan,reader,options=recovered_probe
    def change():
        if failure=='operation':p.current['operations'][0]['native_id']=78
        elif failure=='tool':p.current['operations'][0]['assigned_tool']={'native_id':999}
        elif failure=='feature':p.current['selected_feature']['depth_native']=99
        else:p.data['event_count']=1
    p.state['on_native']=change;result=p.run(**options)
    assert result['status']=='uncertain' and not result['save_readback_verified']
    assert result['native_return_value']==0 and result['saved_file_sha256_after_native_return']==lifecycle._file_hash(p.path)
    p.app.SaveActiveDocument.assert_called_once_with()

def test_wrong_gop_snapshot_stops_before_save(recovered_probe):
    p,ctx,plan,reader,options=recovered_probe;plan['after']['operations'][0]['native_id']=999
    result=p.run('prepare',**options);assert result['status']=='error';p.app.SaveActiveDocument.assert_not_called()

def test_recovered_branch_forbids_close(recovered_probe):
    p,ctx,plan,reader,options=recovered_probe;result=p.run('close',**options)
    assert result['status']=='error';p.app.SaveActiveDocument.assert_not_called();p.app.CloseActiveDocument.assert_not_called()

@pytest.mark.parametrize('value',[None,False,True,1,0.0])
def test_wrong_native_return_never_promoted(recovered_probe,value):
    p,ctx,plan,reader,options=recovered_probe;p.state['returned']=value;result=p.run(**options)
    assert result['status']=='uncertain' and not result['save_readback_verified']
    assert type(result['native_return_value'])is type(value);p.app.SaveActiveDocument.assert_called_once_with()

def lifecycle_options():return dict(feature_kind='autodetected_pocket',expected_source_sha256='a'*64,definition_recovery_receipt_path='C:/proof/recovery.json',definition_recovery_receipt_sha256='b'*64,definition_save_receipt_path='C:/proof/saved.json',definition_save_receipt_sha256='c'*64,definition_gop_receipt_path='C:/proof/gop.json',definition_gop_receipt_sha256='d'*64)

@pytest.mark.parametrize('action',['prepare','save'])
def test_existing_endpoint_routes_explicit_authority(context,core,action):
    options=lifecycle_options();p=feature_params(context,action,**options);server.solidworks_cam_document_lifecycle(p)
    for k,v in options.items():assert core.call_args.kwargs[k]==v

@pytest.mark.parametrize('changes',[dict(action='close'),dict(expected_operation_native_ids=[]),dict(expected_source_sha256=None),dict(definition_gop_receipt_path=None),dict(definition_gop_receipt_sha256=None),dict(definition_save_receipt_path=None),dict(circle_creation_receipt_path=None)])
def test_schema_rejects_incomplete_or_wrong_scope(context,changes):
    options=lifecycle_options();options.update(changes)
    with pytest.raises(ValueError):feature_params(context,**options)

def test_legacy_scope_rejects_explicit_recovery_fields(context):
    with pytest.raises(ValueError):feature_params(context,definition_gop_receipt_path=None)


from test_pocket_gop_evidence import packet
@pytest.mark.parametrize('change',['changed_id','removed_empty_setup'])
def test_gop_preserves_preexisting_operation_setup_identity(packet,change):
    _context,r,_path,_marker=packet;before=deepcopy(r['before']);after=deepcopy(r['after'])
    if change=='changed_id':
        after['operation_setups'][0]['native_id']=999
        for row in after['operations']:row['setup_native_id']=999
    else:
        before['operation_setups'].append(dict(index=1,native_id=999,operation_count=0));before['operation_counts']=[0,0];before['operation_setup_count']=2
    with pytest.raises(ValueError):definition.verify_delta(before,after,111)


def test_CAM_only_unknown_dirty_false_flag_still_saves_once(recovered_probe):
    p,ctx,plan,reader,options=recovered_probe
    p.current['document']['needs_save']=False;plan['after']['document']['needs_save']=False
    result=p.run(**options)
    assert result['status']=='review_required' and result['save_readback_verified']
    assert result['before']['document']['needs_save']is False and result['after']['document']['needs_save']is False
    assert result['saved_file_changed'] and result['saved_file_sha256_after_native_return']!=ctx['expected_source_sha256']
    assert result['native_return_value']==0 and not result['persistence_verified']
    p.app.SaveActiveDocument.assert_called_once_with()
