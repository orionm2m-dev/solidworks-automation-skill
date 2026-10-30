from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import json
import pytest
from scripts import sw_cam_mill_afr as cam
from scripts import sw_cam_events as events
from test_sw_cam_mill_afr_delta import states

@pytest.fixture
def probe(tmp_path,monkeypatch,states):
    before,after=states
    part=tmp_path/'AFR_COPY.SLDPRT';part.write_bytes(b'accepted target + configured raw stock')
    source=cam._file_hash(part);prepare_path=tmp_path/'prepare.json';receipt=tmp_path/'apply.json'
    for state in (before,after):
        state['document'].update(path=str(part),title=part.name);state['saved_file_sha256']=source
    current=deepcopy(before)
    status=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    knobs=dict(on_native=None,on_capture=None,on_exit=None,returned=2)
    class Session:
        def __enter__(self):status.update(subscribed=True,active=True,disconnected=False);return self
        def __exit__(self,*_):
            status.update(active=False,disconnected=True)
            if knobs['on_exit']:knobs['on_exit']()
        def summary(self):return deepcopy(status)
    calls=[]
    def capture(*args,**kw):
        assert status['active'];kw['check']();calls.append(True)
        kw['diagnostic']['last_native_method']='fixture_full_inventory'
        if knobs['on_capture']:knobs['on_capture']()
        kw['check']();return deepcopy(current)
    def extract():
        assert status['active']
        assert Path(str(prepare_path)+'.apply_attempt.json').is_file()
        durable=json.loads(receipt.read_text())
        assert durable['native_dispatch_pending'] and not durable['native_call_returned']
        current.clear();current.update(deepcopy(after))
        if knobs['on_native']:knobs['on_native']()
        return knobs['returned']
    native_doc=N(ExtractMachinableFeatures=Mock(side_effect=extract))
    sw=N(GetProcessID=lambda:731,ActiveDoc=N(GetPathName=lambda:current['document']['path'],GetBodies2=lambda *_:[object()]))
    monkeypatch.setattr(cam,'capture_guarded_mill_inventory',capture)
    monkeypatch.setattr(cam,'raw_part_identity',lambda *_:deepcopy(current['document']))
    monkeypatch.setattr(cam,'_bootstrap',Mock(return_value=object()))
    monkeypatch.setattr(cam,'_mill_snapshot',lambda *a,**k:({},dict(doc=native_doc)))
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    base=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=source,
        expected_material_raw='304L',expected_stock_sha256=cam._digest(before['stock']),stock_basis='documented_raw_stock',
        qualification_only=True,acknowledge_disposable_copy=True)
    def run(action='prepare',**changes):
        data=base|dict(action=action,receipt_path=str(prepare_path if action=='prepare' else receipt))
        if action=='apply':
            p=json.loads(prepare_path.read_text());data.update(expected_state_sha256=p['state_sha256'],
                prepare_receipt_path=str(prepare_path),prepare_receipt_sha256=cam._file_hash(prepare_path))
        return cam.qualify_mill_feature_recognition(sw,'clsid','tlb',**(data|changes))
    return N(**locals())
from pathlib import Path

def test_one_native_call_preserves_context_and_exclusive_prepare(probe):
    p=probe.run();assert p['apply_eligible'],p
    out=probe.run('apply')
    assert out['status']=='review_required' and out['readback_verified'],out
    assert out['delta']['new_feature_native_ids']==[100,101]
    assert not out['GOP_attempted'] and not out['GTP_attempted'] and not out['model_saved'] and not out['TechDB_write_attempted']
    assert not out['actual_incoming_WIP_verified'] and not out['TechDB_internal_writes_verified_absent']
    probe.native_doc.ExtractMachinableFeatures.assert_called_once_with()
    second=probe.run('apply',receipt_path=str(probe.tmp_path/'another.json'))
    assert not second['mutation_attempted'];probe.native_doc.ExtractMachinableFeatures.assert_called_once_with()

@pytest.mark.parametrize('kind',['pid','source','material','stock','dirty','features','event','prepare_changed','mass_change','body_visibility'])
def test_preconditions_stop_before_extraction(probe,kind):
    p=probe.run();assert p['apply_eligible']
    extra={}
    if kind=='pid':extra['process_id']=732
    if kind=='source':probe.part.write_bytes(b'other')
    if kind=='material':probe.current['material_raw']='6061-T6'
    if kind=='stock':probe.current['stock']['dimensions']=[66.,60.]
    if kind=='dirty':probe.current['document']['needs_save']=True
    if kind=='features':probe.current['features']=deepcopy(probe.after['features'])
    if kind=='event':probe.knobs['on_capture']=lambda:probe.status.update(event_count=1)
    if kind=='prepare_changed':
        data=json.loads(probe.prepare_path.read_text());data['request']['stock_basis']='actual_turning_wip';probe.prepare_path.write_text(json.dumps(data))
    if kind=='mass_change':probe.current['sw_reference']['solids'][0]['mass_raw'][3]=2.
    if kind=='body_visibility':probe.current['visible_solid_body_count']=0
    out=probe.run('apply',**extra)
    assert not out['mutation_attempted'] and not out['readback_verified'],out
    probe.native_doc.ExtractMachinableFeatures.assert_not_called()

@pytest.mark.parametrize('value',[False,True,None,0,65,2.,'2'])
def test_invalid_return_is_not_replayed_or_followed_by_inventory(probe,value):
    probe.run();probe.knobs['returned']=value;start=len(probe.calls)
    out=probe.run('apply')
    assert out['status']=='uncertain' and not out['readback_verified']
    assert len(probe.calls)==start+2
    probe.native_doc.ExtractMachinableFeatures.assert_called_once_with()

@pytest.mark.parametrize('kind',['stock','material','options','extra_operation','body','event','exception'])
def test_unexpected_native_effect_is_uncertain_no_retry(probe,kind):
    probe.run()
    def changed():
        if kind=='stock':probe.current['stock']['dimensions'][0]=66.
        if kind=='material':probe.current['material_raw']='6061-T6'
        if kind=='options':probe.current['recognition_options']['EMFHoleMaxDiameter']=99.
        if kind=='extra_operation':probe.current['operation_counts'][0]=1
        if kind=='body':probe.current['sw_reference']['solids'][0]['mass_raw'][3]=2.
        if kind=='event':probe.status['event_count']=1
        if kind=='exception':raise RuntimeError('native outcome unknown')
    probe.knobs['on_native']=changed
    out=probe.run('apply');assert out['status']=='uncertain' and not out['readback_verified'],out
    probe.native_doc.ExtractMachinableFeatures.assert_called_once_with()


def test_unknown_outcome_consumes_marker_even_if_capture_fails(probe):
    probe.run();probe.knobs['on_native']=lambda:probe.current.update(unsupported_geometry=True)
    def fail_after_call():
        if probe.native_doc.ExtractMachinableFeatures.called:raise ValueError('unsupported curve')
    probe.knobs['on_capture']=fail_after_call
    out=probe.run('apply');assert out['status']=='uncertain'
    assert Path(str(probe.prepare_path)+'.apply_attempt.json').is_file()
    assert out['snapshot_diagnostics'][-1]['last_native_method']=='fixture_full_inventory'


def test_receipt_pending_write_failure_prevents_native_call(probe,monkeypatch):
    probe.run();original=cam._write_receipt
    def fail(path,report,**kw):
        if report.get('native_dispatch_pending'):raise OSError('durability failed')
        return original(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    out=probe.run('apply');assert not out['mutation_attempted']
    probe.native_doc.ExtractMachinableFeatures.assert_not_called()


def test_known_techdb_source_change_observed_without_claiming_internal_no_write(probe):
    db=probe.tmp_path/'known.mdb';db.write_bytes(b'caller identified DB')
    probe.base.update(techdb_source_path=str(db),techdb_source_sha256=cam._file_hash(db))
    probe.run();probe.knobs['on_native']=lambda:db.write_bytes(b'changed')
    out=probe.run('apply');assert out['status']=='uncertain' and not out['TechDB_internal_writes_verified_absent']
    assert out['caller_identified_techdb_source']['before']!=out['caller_identified_techdb_source']['after_dispatch']


def test_allowed_mass_roundoff_between_prepare_and_apply_does_not_rebase_source(probe):
    p=probe.run();original=probe.prepare_path.read_bytes()
    probe.current['sw_reference']['solids'][0]['mass_raw'][3]*=1.+1e-12
    out=probe.run('apply')
    assert out['status']=='review_required' and out['readback_verified'],out
    assert probe.prepare_path.read_bytes()==original
    assert out['state_sha256']==p['state_sha256']
    assert out['before']['saved_file_sha256']==p['before']['saved_file_sha256']


@pytest.mark.parametrize('drift',['source','identity'])
def test_cleanup_drift_cannot_finish_successfully(probe,drift):
    probe.run()
    def changed():
        if drift=='source':probe.part.write_bytes(b'changed during disconnect')
        else:probe.current['document']['title']='another part'
    probe.knobs['on_exit']=changed
    out=probe.run('apply')
    assert out['status']=='uncertain' and not out['readback_verified'],out
    probe.native_doc.ExtractMachinableFeatures.assert_called_once_with()
