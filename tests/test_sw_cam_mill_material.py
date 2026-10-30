from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import json
import pytest
from scripts import sw_cam_mill_material as cam
from scripts import sw_cam_events as events
from test_sw_cam_mill_afr_delta import states

@pytest.fixture
def probe(tmp_path,monkeypatch,states):
    before,_=states;before['material_raw']='6061-T6'
    part=tmp_path/'EMPTY_MILL.SLDPRT';part.write_bytes(b'saved empty target')
    before['document'].update(path=str(part),title=part.name);before['saved_file_sha256']=cam._file_hash(part)
    after=deepcopy(before);after['material_raw']='304L';after['document']['needs_save']=True
    current=deepcopy(before);prepare_path=tmp_path/'prepare.json';receipt=tmp_path/'apply.json'
    catalogue=tmp_path/'catalogue.json';catalogue.write_text(json.dumps({'materials':['304L']}))
    evidence=tmp_path/'mapping.json';evidence.write_text(json.dumps(dict(status='qualified_mapping',
        document_path=str(part),native_material_name='304L',required_alloy='EN1.4307 / 304L',
        material_condition='+AT remains unverified',mapping_basis='Fixture observed exact catalogue name',
        catalogue_source_path=str(catalogue),catalogue_source_sha256=cam._file_hash(catalogue),verified_native_material_names=['304L'])))
    status=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    knobs=dict(on_native=None,on_capture=None,on_exit=None,no_write=False)
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
    def write(value):
        assert status['active'];assert value=='304L'
        assert Path(str(prepare_path)+'.apply_attempt.json').is_file()
        durable=json.loads(receipt.read_text())
        assert durable['native_dispatch_pending'] and not durable['native_call_returned']
        if not knobs['no_write']:current.clear();current.update(deepcopy(after))
        if knobs['on_native']:knobs['on_native']()
    setter=Mock(side_effect=write)
    class Workpiece:
        @property
        def Material(self):return current['material_raw']
        @Material.setter
        def Material(self,value):setter(value)
    workpiece=Workpiece();machine=N(IGetWorkpiece=lambda:workpiece)
    sw=N(GetProcessID=lambda:731)
    monkeypatch.setattr(cam,'capture_guarded_mill_inventory',capture)
    monkeypatch.setattr(cam,'raw_part_identity',lambda *_:deepcopy(current['document']))
    monkeypatch.setattr(cam,'_bootstrap',Mock(return_value=object()))
    monkeypatch.setattr(cam,'_mill_snapshot',lambda *a,**k:({},dict(machine=machine)))
    monkeypatch.setattr(cam,'_typed',lambda value,name,_:value if name=='ICWWorkpiece' else None)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    base=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=cam._file_hash(part),
        expected_old_material='6061-T6',value_native='304L',material_evidence=dict(path=str(evidence),sha256=cam._file_hash(evidence)),
        qualification_only=True,acknowledge_disposable_copy=True)
    def run(action='prepare',**changes):
        data=base|dict(action=action,receipt_path=str(prepare_path if action=='prepare' else receipt))
        if action=='apply':
            p=json.loads(prepare_path.read_text());data.update(expected_state_sha256=p['state_sha256'],
                prepare_receipt_path=str(prepare_path),prepare_receipt_sha256=cam._file_hash(prepare_path))
        return cam.configure_mill_material(sw,'clsid','tlb',**(data|changes))
    return N(**locals())


def test_single_material_setter_changes_only_name_and_consumes_prepare(probe):
    p=probe.run();assert p['apply_eligible'],p
    out=probe.run('apply');assert out['status']=='review_required' and out['readback_verified'],out
    assert out['after']['material_raw']=='304L'
    assert not any(out[k] for k in ('AFR_attempted','GOP_attempted','GTP_attempted','model_saved','stock_edit_attempted','TechDB_write_attempted','cutting_recipe_qualified','stock_grade_delivery_verified'))
    probe.setter.assert_called_once_with('304L')
    repeat=probe.run('apply',receipt_path=str(probe.tmp_path/'repeat.json'))
    assert not repeat['mutation_attempted'];probe.setter.assert_called_once_with('304L')


@pytest.mark.parametrize('kind',['pid','source','material','stock','dirty','features','event','prepare_changed','mass_change','body_visibility','options','operations','mapping','catalogue','new_name'])
def test_preconditions_stop_before_setter(probe,kind):
    p=probe.run();assert p['apply_eligible'];extra={}
    if kind=='pid':extra['process_id']=732
    if kind=='source':probe.part.write_bytes(b'other')
    if kind=='material':probe.current['material_raw']='316S'
    if kind=='stock':probe.current['stock']['dimensions']=[66.,60.]
    if kind=='dirty':probe.current['document']['needs_save']=True
    if kind=='features':probe.current['feature_setups'][0]['feature_count']=1
    if kind=='event':probe.knobs['on_capture']=lambda:probe.status.update(event_count=1)
    if kind=='prepare_changed':
        data=json.loads(probe.prepare_path.read_text());data['request']['value_native']='316S';probe.prepare_path.write_text(json.dumps(data))
    if kind=='mass_change':probe.current['sw_reference']['solids'][0]['mass_raw'][3]=2.
    if kind=='body_visibility':probe.current['visible_solid_body_count']=0
    if kind=='options':probe.current['recognition_options']['EMFHoleMaxDiameter']=99.
    if kind=='operations':probe.current['operation_counts'][0]=1
    if kind=='mapping':probe.evidence.write_text('{}')
    if kind=='catalogue':probe.catalogue.write_text('{}')
    if kind=='new_name':extra['value_native']='316S'
    out=probe.run('apply',**extra)
    assert not out['mutation_attempted'] and not out['readback_verified'],out;probe.setter.assert_not_called()


@pytest.mark.parametrize('kind',['stock','material','options','extra_operation','body','event','exception','no_write','mapping'])
def test_unexpected_native_effect_is_uncertain_no_retry(probe,kind):
    probe.run()
    def changed():
        if kind=='stock':probe.current['stock']['dimensions'][0]=66.
        if kind=='material':probe.current['material_raw']='316S'
        if kind=='options':probe.current['recognition_options']['EMFHoleMaxDiameter']=99.
        if kind=='extra_operation':probe.current['operation_counts'][0]=1
        if kind=='body':probe.current['sw_reference']['solids'][0]['mass_raw'][3]=2.
        if kind=='event':probe.status['event_count']=1
        if kind=='exception':raise RuntimeError('native outcome unknown')
        if kind=='mapping':probe.evidence.write_text('{}')
    probe.knobs['no_write']=kind=='no_write';probe.knobs['on_native']=changed
    out=probe.run('apply');assert out['status']=='uncertain' and not out['readback_verified'],out
    probe.setter.assert_called_once_with('304L')
    again=probe.run('apply',receipt_path=str(probe.tmp_path/'retry.json'))
    assert not again['mutation_attempted'];probe.setter.assert_called_once_with('304L')


def test_receipt_pending_write_failure_prevents_setter(probe,monkeypatch):
    probe.run();original=cam._write_receipt
    def fail(path,report,**kw):
        if report.get('native_dispatch_pending'):raise OSError('durability failed')
        return original(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    out=probe.run('apply');assert not out['mutation_attempted'];probe.setter.assert_not_called()


def test_allowed_mass_roundoff_does_not_rebase_prepared_source(probe):
    p=probe.run();original=probe.prepare_path.read_bytes()
    probe.current['sw_reference']['solids'][0]['mass_raw'][3]*=1.+1e-12
    out=probe.run('apply');assert out['status']=='review_required' and out['readback_verified'],out
    assert probe.prepare_path.read_bytes()==original and out['state_sha256']==p['state_sha256']


@pytest.mark.parametrize('drift',['source','identity'])
def test_cleanup_drift_cannot_finish_successfully(probe,drift):
    probe.run()
    def changed():
        if drift=='source':probe.part.write_bytes(b'changed during disconnect')
        else:probe.current['document']['title']='another part'
    probe.knobs['on_exit']=changed
    out=probe.run('apply');assert out['status']=='uncertain' and not out['readback_verified'],out
    probe.setter.assert_called_once_with('304L')
