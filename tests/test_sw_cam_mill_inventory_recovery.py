"""Synthetic wrapper guards; no native recognition or stock assignment."""
from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_sw_cam_mill_inventory import probe,native
from scripts import sw_cam_mill_inventory as cam
from scripts import sw_cam_mill_inventory_recovery_evidence as evidence

@pytest.fixture
def recovery(probe,monkeypatch):
    rp=probe.tmp_path/'recognition.json';rp.write_text('{}')
    sp=probe.tmp_path/'save.json';sp.write_text('{}')
    extra=dict(recognition_receipt_path=str(rp),recognition_receipt_sha256='b'*64,
        preservation_save_receipt_path=str(sp),preservation_save_receipt_sha256='c'*64)
    proof=Mock()
    proof.summary.return_value={'synthetic':True}
    proof.verify_inventory.return_value={'new_feature_native_ids':[101,102]}
    proof.read_stock.return_value=({'offset_read_status':'unavailable_native_false'},None)
    loader=Mock(return_value=proof);monkeypatch.setattr(evidence,'load_mill_inventory_recovery_evidence',loader)
    original=cam.capture_mill_inventory
    def capture(*args,**kw):
        assert 'stock_reader' in kw
        kw['stock_reader']('workpiece','tlb','read')
        return original(*args,**kw)
    monkeypatch.setattr(cam,'capture_mill_inventory',capture)
    def run(**changes):return probe.run(**dict(extra,**changes))
    return N(**locals())

def test_recovery_two_complete_checks_without_native_mutation(recovery):
    out=recovery.run();p=recovery.proof
    assert out['readback_verified'] is True and out['recovery_delta_verified'] is True
    assert p.verify_inventory.call_count==2 and p.check_files.call_count==5
    assert p.read_stock.call_count==2 and recovery.loader.call_count==1
    assert out['EMF_replayed'] is False and out['original_recognition_readback_verified'] is False
    assert out['stock_offsets_verified'] is False and out['actual_incoming_WIP_verified'] is False
    assert all(out[k] is False for k in ('mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','model_saved'))
    assert json.loads(recovery.probe.receipt.read_text())==out

@pytest.mark.parametrize('kind',['loader','first_delta','second_delta','first_files','final_files','capture','receipt'])
def test_proof_or_capture_failure_never_promotes_inventory(recovery,kind,monkeypatch):
    bad=ValueError('synthetic changed proof')
    if kind=='loader':recovery.loader.side_effect=bad
    if kind=='first_delta':recovery.proof.verify_inventory.side_effect=bad
    if kind=='second_delta':recovery.proof.verify_inventory.side_effect=[{},bad]
    if kind=='first_files':recovery.proof.check_files.side_effect=bad
    if kind=='final_files':recovery.proof.check_files.side_effect=[True]*4+[bad]
    if kind=='capture':recovery.probe.knobs['on_capture']=lambda:(_ for _ in ()).throw(bad)
    if kind=='receipt':
        write=cam._write_receipt
        def failing(path,result,**kw):
            if result.get('recovery_delta_verified') is True:raise OSError('synthetic disk failure')
            return write(path,result,**kw)
        monkeypatch.setattr(cam,'_write_receipt',failing)
    out=recovery.run()
    assert out['status']=='error' and out['readback_verified'] is False
    assert out.get('recovery_delta_verified',False) is False
    assert out['AFR_attempted'] is False and len(recovery.probe.calls)<=2

@pytest.mark.parametrize('kind',['missing_pair','relative','bad_sha','same_receipt','missing_file'])
def test_invalid_lineage_fails_before_event_host(recovery,kind):
    extra={}
    if kind=='missing_pair':extra['preservation_save_receipt_sha256']=None
    if kind=='relative':extra['recognition_receipt_path']='recognition.json'
    if kind=='bad_sha':extra['recognition_receipt_sha256']='B'*64
    if kind=='same_receipt':extra['preservation_save_receipt_path']=str(recovery.rp)
    if kind=='missing_file':extra['recognition_receipt_path']=str(recovery.probe.tmp_path/'missing.json')
    out=recovery.run(**extra)
    assert not out['readback_verified'];recovery.loader.assert_not_called();cam._bootstrap.assert_not_called()

def test_feature_failure_resets_inherited_machine_capture_complete(native,monkeypatch):
    original=cam._mill_snapshot
    def snapshot(*args,**kw):
        if 'diagnostic' in kw:kw['diagnostic'].update(capture_complete=True,stage='complete')
        return original(*args,**kw)
    monkeypatch.setattr(cam,'_mill_snapshot',snapshot)
    native.decoder.side_effect=ValueError('unsupported synthetic feature')
    with pytest.raises(ValueError):native.run()
    assert native.diagnostic['capture_complete'] is False
    assert native.diagnostic['stage']=='feature_inventory'
    assert len(native.diagnostic['features'])==1

def test_default_request_never_loads_optional_recovery(probe,monkeypatch):
    load=Mock(side_effect=AssertionError('default must remain strict'))
    monkeypatch.setattr(evidence,'load_mill_inventory_recovery_evidence',load)
    out=probe.run();assert out['readback_verified'] and 'recovery_evidence' not in out
    load.assert_not_called()
