"""Synthetic provenance-chain tests only; no project geometry or private paths."""
from copy import deepcopy
from pathlib import Path
import hashlib,importlib.util,json
import pytest
from scripts import sw_cam_mill_inventory_recovery_evidence as g
from scripts import sw_cam_mill_stock_export_evidence as stock

# Reuse the installed package's portable synthetic cube/empty-state fixture.
_fixture_path=Path(stock.__file__).resolve().parents[1]/'tests/test_sw_cam_mill_stock_export_evidence.py'
_spec=importlib.util.spec_from_file_location('recovery_synthetic_stock_fixture',_fixture_path)
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)


def write(path,data):
    raw=json.dumps(data,ensure_ascii=False).encode('utf-8');path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def setpath(obj,path,value):
    keys=path.split('.');node=obj
    for key in keys[:-1]:node=node[int(key)] if type(node) is list else node[key]
    if type(node) is list:node[int(keys[-1])]=value
    else:node[keys[-1]]=value


@pytest.fixture
def sample(tmp_path):
    root=tmp_path/'export';root.mkdir();q16,a,b=_fixture.synthetic_receipt(root)
    for state in (q16['before'],q16['after']):
        state.update(extend_holes_to_stock=False,unit_record_raw=None,unit_record_status='unavailable')
    ep=tmp_path/'export.json';esha=write(ep,q16);base=deepcopy(q16['before']);pid=q16['request']['process_id'];path=base['document']['path']
    old=base['saved_file_sha256'];new='b'*64
    proof=stock.load_stock_export_evidence(str(ep),esha,process_id=pid,expected_document_path=path,
        expected_source_sha256=old,expected_material_raw='304L',expected_stock_sha256=stock._digest(base['stock']),stock_basis='documented_raw_stock')
    q18=dict(scope='MILL_EMPTY_COPY_AFR_SMOKE_V1',status='uncertain',action='apply',phase='finished',failed_phase='after_native_action',
        native_return_type='int',native_return_value=2,recognition_probe_method='EMF/MfgView',before=deepcopy(base),
        mutation_attempted=True,native_call_attempted=True,native_call_returned=True,AFR_attempted=True,stock_mesh_evidence_checked=True,
        may_continue=False,apply_eligible=False,native_dispatch_pending=False,GOP_attempted=False,GTP_attempted=False,model_saved=False,
        stock_edit_attempted=False,material_edit_attempted=False,TechDB_write_attempted=False,TechDB_internal_writes_verified_absent=False,
        readback_verified=False,physical_depth_verified=False,production_qualified=False,actual_incoming_WIP_verified=False,
        post_cleanup_CAM_getters=False,stock_offsets_verified=False,messages=deepcopy(g._MESSAGES),stock_export_evidence=proof.summary(),
        request=dict(process_id=pid,expected_document_path=path,expected_source_sha256=old,expected_material_raw='304L',
            expected_stock_sha256=stock._digest(base['stock']),stock_basis='documented_raw_stock',
            stock_export_receipt_path=str(ep),stock_export_receipt_sha256=esha))
    fresh=deepcopy(base);fresh['saved_file_sha256']=new
    fresh['feature_setups']=[dict(native_id=10,name='Synthetic setup',feature_count=2,axis_native=[0.,0.,1.],origin_native=[0.,0.,0.],origin_type_raw=6)]
    fresh['features']=[dict(setup_index=0,feature_index=i,setup_native_id=10,geometry=dict(native_id=20+i)) for i in range(2)]
    fresh['operation_counts']=[0];fresh['operation_setups']=[dict(index=0,native_id=11,operation_count=0)]
    sa={k:deepcopy(fresh[k]) for k in g._HEADER-{'machine_kind','process_id'}};sa.update(machine_kind='mill_qualification',process_id=pid)
    sb=deepcopy(sa);sb['document']['needs_save']=True;sb['saved_file_sha256']=old
    q20=dict(status='review_required',machine_kind='mill_qualification',process_id=pid,action='save',phase='finished',native_return_type='int',
        native_outcome='save_returned_readback_verified',snapshot_scope='MILL configuration and bounded feature counts; no complete feature geometry',
        last_CAM_snapshot_scope='inside active event subscription before cleanup',message_policy='vendor_default',
        reason='SAVE_RETURNED_PERSISTENCE_REQUIRES_REOPEN',mutation_attempted=True,native_call_attempted=True,native_call_returned=True,
        native_save_call_returned=True,save_readback_verified=True,saved_file_changed=True,may_continue=False,native_dispatch_pending=False,
        native_close_call_returned=False,close_verified=False,persistence_verified=False,generation_attempted=False,AFR_attempted=False,
        GOP_attempted=False,GTP_attempted=False,post_cleanup_CAM_getters=False,native_return_value=0,native_hresult=0,messages=deepcopy(g._MESSAGES),
        before=sb,after=sa,final_state=deepcopy(sa),after_cleanup_sw_file={k:deepcopy(sa[k]) for k in ('document','saved_file_sha256')})
    rp=tmp_path/'recognition.json';sp=tmp_path/'save.json'
    kw=dict(process_id=pid,expected_document_path=path,expected_source_sha256=new)
    def load(**overrides):
        return g.load_mill_inventory_recovery_evidence(str(rp),write(rp,q18),str(sp),write(sp,q20),**dict(kw,**overrides))
    return dict(q16=q16,q18=q18,q20=q20,fresh=fresh,load=load,kw=kw,paths=[rp,sp,ep,a,b])


def test_full_recovery_preserves_live_state_and_uses_native_count(sample):
    gate=sample['load']();before=deepcopy(sample['fresh']);out=gate.verify_inventory(sample['fresh'])
    assert out['new_feature_native_ids']==[20,21] and out['native_return_feature_count']==2
    assert sample['fresh']==before and gate.check_files() is True
    summary=gate.summary();assert summary['original_recognition_readback_verified'] is False
    assert summary['reopen_persistence_verified'] is False and summary['production_qualified'] is False
    summary['recognition_receipt']['sha256']='bad';assert gate.summary()['recognition_receipt']['sha256']!='bad'


@pytest.mark.parametrize('field,value',[('status','review_required'),('failed_phase','before_native_action'),('native_return_value',True),
 ('native_return_value',0),('native_return_value',65),('native_call_returned',1),('readback_verified',True),('model_saved',True),
 ('TechDB_write_attempted',True),('messages.event_count',False),('messages.disconnected',False),('request.process_id',1),
 ('request.expected_source_sha256','c'*64),('request.stock_basis','actual_incoming_WIP'),('stock_export_evidence.offsets_verified',True),
 ('stock_export_evidence.stock_snapshot_sha256','c'*64),('before.material_raw','6061-T6')])
def test_recognition_receipt_negatives(sample,field,value):
    setpath(sample['q18'],field,value)
    with pytest.raises(ValueError):sample['load']()


@pytest.mark.parametrize('field,value',[('machine_kind','turn'),('action','close'),('status','uncertain'),('native_return_value',False),
 ('native_hresult',True),('save_readback_verified',1),('native_save_call_returned',False),('generation_attempted',True),
 ('messages.events',[{}]),('process_id',True),('snapshot_scope','full geometry'),('before.saved_file_sha256','c'*64),
 ('after.saved_file_sha256','c'*64),('after.document.needs_save',0),('before.operation_counts.0',False),
 ('after.feature_setups.0.native_id',True),('after.feature_setups.0.feature_count',3),('after.current_machine.machine_type',True),
 ('after.material_raw','6061-T6'),('final_state.material_raw','6061-T6'),('after_cleanup_sw_file.saved_file_sha256','c'*64)])
def test_preservation_receipt_negatives(sample,field,value):
    setpath(sample['q20'],field,value)
    with pytest.raises(ValueError):sample['load']()


@pytest.mark.parametrize('field,value',[('saved_file_sha256','c'*64),('material_raw','6061-T6'),('document.needs_save',True),
 ('operation_count',1),('operation_counts.0',False),('feature_setups.0.axis_native',[0.,1.,0.]),
 ('features.1.geometry.native_id',20),('features.0.setup_native_id',99),('stock.coordinate_system','other'),
 ('recognition_options.GetEMFFeatTypeOptions.0.enabled',False),('sw_reference.feature_tree.0.name','changed')])
def test_fresh_inventory_must_match_saved_header_and_original_delta(sample,field,value):
    gate=sample['load']();setpath(sample['fresh'],field,value)
    with pytest.raises(ValueError):gate.verify_inventory(sample['fresh'])


def test_missing_feature_does_not_become_verified_from_saved_counts(sample):
    gate=sample['load']();sample['fresh']['features'].pop()
    with pytest.raises(ValueError):gate.verify_inventory(sample['fresh'])


def test_geometry_anchor_does_not_roll_through_recognition_before(sample):
    sample['q18']['before']['sw_reference']['solids'][0]['mass_raw'][3]=1+8e-11
    gate=sample['load']();sample['fresh']['sw_reference']['solids'][0]['mass_raw'][3]=1+16e-11
    with pytest.raises(ValueError,match='immutable'):gate.verify_inventory(sample['fresh'])


@pytest.mark.parametrize('index',range(5))
def test_all_five_evidence_files_stay_pinned_at_boundaries(sample,index):
    gate=sample['load']();p=sample['paths'][index];p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError):gate.check_files()


def test_stock_observation_does_not_check_empty_feature_count_or_rehash_receipts(sample,monkeypatch):
    gate=sample['load']();calls=[];expected=deepcopy(sample['fresh']['stock'])
    monkeypatch.setattr(gate._stock,'read_stock',lambda *args:(calls.append(args) or expected,'native'))
    monkeypatch.setattr(g,'_receipt_bytes',lambda *args:pytest.fail('Boundary receipt read during native getter'))
    assert gate.read_stock('wp','tlb','read',{})==(expected,'native') and len(calls)==1


def test_partial_original_poststate_is_not_treated_as_complete(sample):
    sample['q18']['snapshot_diagnostics']=[dict(phase='after_native_action',features=[dict(partial=True)])]
    gate=sample['load']()
    assert gate.summary()['fresh_complete_inventory_required'] is True
    assert gate.verify_inventory(sample['fresh'])['native_return_feature_count']==2


@pytest.mark.parametrize('key,value',[('process_id',True),('expected_source_sha256','c'*64),('expected_document_path','relative.sldprt')])
def test_caller_binding_is_strict(sample,key,value):
    with pytest.raises(ValueError):sample['load'](**{key:value})
