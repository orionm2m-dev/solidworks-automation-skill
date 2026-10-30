from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import json
import pytest
from test_sw_cam_mill_afr import probe,states
from scripts import sw_cam_mill_afr as cam

@pytest.fixture
def gated(probe,monkeypatch):
    p=probe
    method=dict(value=1,name='MFGVIEW',status='observed_via_ICWDoc3_FeatureCreationStyle')
    for state in (p.before,p.after,p.current):state['recognition_method']=deepcopy(method)
    export=p.tmp_path/'native_stock_export.json';export.write_text('{}')
    p.base.update(stock_export_receipt_path=str(export),stock_export_receipt_sha256=cam._file_hash(export))
    anchor=deepcopy(p.current)
    def verify(state):
        if not cam._same_inventory(anchor,state):raise ValueError('Stock proof baseline changed')
    proof=N(summary=Mock(return_value=dict(receipt_sha256=cam._file_hash(export),offset_read_status='unavailable_native_false')),
        check_files=Mock(),verify_initial=Mock(side_effect=verify),verify_geometry=Mock(),read_stock=Mock(return_value=(anchor['stock'],object())))
    loader=Mock(return_value=proof);monkeypatch.setattr(cam,'load_stock_export_evidence',loader)
    old_capture=cam.capture_guarded_mill_inventory
    def capture(*args,**kw):
        assert 'stock_reader' in kw
        result=kw['stock_reader']('workpiece','tlb','read')
        assert result[0]==anchor['stock']
        return old_capture(*args,**kw)
    monkeypatch.setattr(cam,'capture_guarded_mill_inventory',capture)
    return N(**locals())


def test_optional_evidence_used_in_prepare_and_one_mfgview_extraction(gated):
    g=gated;p=g.p
    prepared=p.run();assert prepared['apply_eligible'],prepared
    assert prepared['request']['stock_export_receipt_sha256']==p.base['stock_export_receipt_sha256']
    assert prepared['recognition_probe_method']=='EMF/MfgView'
    result=p.run('apply');assert result['readback_verified'],result
    assert result['before']['recognition_method']==result['after']['recognition_method']==g.method
    assert result['stock_mesh_evidence_checked'] and not result['stock_offsets_verified']
    assert not result['actual_incoming_WIP_verified'] and not result['model_saved'] and not result['GOP_attempted'] and not result['GTP_attempted']
    assert g.proof.verify_initial.call_count==4 and g.loader.call_count==2
    assert g.proof.verify_geometry.call_count==6
    assert g.proof.read_stock.call_count==6
    p.native_doc.ExtractMachinableFeatures.assert_called_once_with()


def test_default_request_uses_strict_inventory_without_receipt_hook(probe,monkeypatch):
    loader=Mock(side_effect=AssertionError('default must not load proof'));monkeypatch.setattr(cam,'load_stock_export_evidence',loader)
    capture=cam.capture_guarded_mill_inventory
    def strict(*args,**kw):
        assert 'stock_reader' not in kw
        return capture(*args,**kw)
    monkeypatch.setattr(cam,'capture_guarded_mill_inventory',strict)
    result=probe.run();assert result['apply_eligible'],result
    assert not any(k.startswith('stock_export_receipt') for k in result['request'])
    loader.assert_not_called()

@pytest.mark.parametrize('orphan',['path','sha'])
def test_backend_rejects_unpaired_evidence_even_when_request_omits_optional_fields(probe,orphan):
    path=probe.tmp_path/'proof.json';path.write_text('{}')
    extra=dict(stock_export_receipt_path=str(path)) if orphan=='path' else dict(stock_export_receipt_sha256='b'*64)
    result=probe.run(**extra)
    assert not result['readback_verified'] and not result['mutation_attempted']
    assert not probe.calls

@pytest.mark.parametrize('kind',['mode','stock','material','options','source','geometry'])
def test_current_context_must_match_export_proof_before_emf(gated,kind):
    g=gated;p=g.p
    if kind=='mode':p.current['recognition_method']['value']=0
    if kind=='stock':p.current['stock']['dimensions'][0]=66.
    if kind=='material':p.current['material_raw']='316'
    if kind=='options':p.current['recognition_options']['new']=True
    if kind=='source':p.current['saved_file_sha256']='b'*64
    if kind=='geometry':p.current['sw_reference']['solids'][0]['mass_raw'][3]=2.
    result=p.run();assert not result['apply_eligible'] and not result['mutation_attempted']
    p.native_doc.ExtractMachinableFeatures.assert_not_called()


def test_file_change_after_reserved_attempt_prevents_dispatch_and_consumes_prepare(gated):
    g=gated;p=g.p;p.run()
    def fail():
        if p.receipt.exists() and json.loads(p.receipt.read_text()).get('native_dispatch_pending'):raise ValueError('Stock export asset changed')
    g.proof.check_files.side_effect=fail
    result=p.run('apply');assert not result['mutation_attempted'] and not result['readback_verified'],result
    p.native_doc.ExtractMachinableFeatures.assert_not_called()
    assert Path(str(p.prepare_path)+'.apply_attempt.json').is_file()
    retry=p.run('apply',receipt_path=str(p.tmp_path/'retry.json'));assert not retry['mutation_attempted']


def test_file_change_after_native_is_uncertain_without_replay(gated):
    g=gated;p=g.p;p.run()
    def fail():
        if p.native_doc.ExtractMachinableFeatures.called:raise ValueError('Proof asset changed after dispatch')
    g.proof.check_files.side_effect=fail
    result=p.run('apply');assert result['status']=='uncertain' and not result['readback_verified'],result
    p.native_doc.ExtractMachinableFeatures.assert_called_once_with()


def test_optional_receipt_is_part_of_immutable_emf_request(gated):
    g=gated;p=g.p;p.run();other=p.tmp_path/'other.json';other.write_text('{}')
    result=p.run('apply',stock_export_receipt_path=str(other),stock_export_receipt_sha256=cam._file_hash(other))
    assert not result['mutation_attempted'];p.native_doc.ExtractMachinableFeatures.assert_not_called()


def test_failed_loader_stops_before_capture(gated):
    g=gated;g.loader.side_effect=ValueError('Unsuccessful native export proof')
    result=g.p.run();assert not result['mutation_attempted'] and not g.p.calls


def test_source_or_mode_post_emf_still_uses_existing_delta_guard(gated):
    g=gated;p=g.p;p.run();p.knobs['on_native']=lambda:p.current['recognition_method'].update(value=0,name='AFR')
    result=p.run('apply');assert result['status']=='uncertain' and not result['readback_verified'],result
    p.native_doc.ExtractMachinableFeatures.assert_called_once_with()
