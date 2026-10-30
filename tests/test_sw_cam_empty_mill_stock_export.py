from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import json,math
import pytest
from scripts import sw_cam_empty_mill_stock_export as cam
from scripts import sw_cam_events as events
from scripts import sw_cam_mill_stock as strict_stock

@pytest.fixture
def observer(tmp_path,monkeypatch):
    stl=tmp_path/'input.stl';stl.write_bytes(b'input stock')
    data=dict(GetMillWorkpieceType=4,GetBoundingBoxSize=(-.0325,-.0325,-.032,.0325,.0325,.028,True),
        GetWorkpieceFromSTLParam=(str(stl),0,'',True),GetSTLOffset=(1.e-310,)*6+(False,True,False,False))
    monkeypatch.setattr(cam,'_typed',lambda *a:object())
    monkeypatch.setattr(strict_stock,'_typed',lambda *a:object())
    diag={}
    def read(obj,name,*args):return data[name]
    def run():return cam._export_stock(object(),'tlb',read,diag)[0]
    return N(**locals())


def test_false_discards_all_nine_outs_and_keeps_raw_diagnostic(observer):
    out=observer.run();assert out['offset_read_status']=='unavailable_native_false'
    assert out['offsets_native'] is None and out['uniform_flags'] is None
    digest=cam._digest(out)
    observer.data['GetSTLOffset']=(float('nan'),None,object(),'garbage',True,1e300,37,None,object(),False)
    assert cam._digest(observer.run())==digest
    assert observer.diag['GetSTLOffset']['raw']['length']==10
    assert observer.diag['GetSTLOffset']['raw']['items'][0]['finite'] is False
    with pytest.raises(ValueError):strict_stock._stock(object(),'tlb',observer.read)

@pytest.mark.parametrize('value',[None,False,[],[False]*9,[False]*11,[0]*9+[0],[0]*9+[1],tuple([0]*9+['False'])])
def test_unknown_offset_shape_or_retval_hard_stops(observer,value):
    observer.data['GetSTLOffset']=value
    with pytest.raises(ValueError):observer.run()
    assert 'raw' in observer.diag['GetSTLOffset']


def test_success_offset_remains_strict_and_does_not_qualify_false_scope(observer):
    observer.data['GetSTLOffset']=(0.,)*6+(False,False,False,True)
    assert observer.run()['offset_read_status']=='observed_native_true'
    for raw in [(float('nan'),)+(0.,)*5+(False,False,False,True),(0.,)*6+(0,False,False,True)]:
        observer.data['GetSTLOffset']=raw
        with pytest.raises(ValueError):observer.run()

@pytest.fixture
def probe(tmp_path,monkeypatch):
    part=tmp_path/'EMPTY_MILL.SLDPRT';part.write_bytes(b'saved empty 304L stock')
    stl=tmp_path/'input.stl';stl.write_bytes(b'input stock')
    prepare_path=tmp_path/'prepare.json';receipt=tmp_path/'apply.json';output_dir=tmp_path/'export'
    bounds=[-.0325,-.0325,-.032,.0325,.0325,.028]
    stock=dict(type_raw=4,bounds_native=bounds,stl_path=str(stl),stl_sha256=cam._file_hash(stl),length_units_raw=0,coordinate_system='',
        offset_read_status='unavailable_native_false',offsets_native=None,uniform_flags=None)
    current=dict(document=dict(path=str(part),title=part.name,type=1,needs_save=False),saved_file_sha256=cam._file_hash(part),
        current_machine=dict(machine_type=1),mill_catalogue=[],material_raw='304L',stock=stock,
        recognition_options={},recognition_method=dict(value=0,name='AFR',status='observed_via_ICWDoc3_FeatureCreationStyle'),
        feature_setups=[],features=[],operation_counts=[],operation_setups=[],operation_count=0,
        sw_reference=dict(feature_tree=[],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[0.,0.,0.,1.])]),
        visible_solid_body_count=1,all_solid_body_count=1)
    status=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    knobs=dict(on_native=None,on_capture=None,on_exit=None,no_file=False,returned=True,compare_failure=False)
    class Session:
        def __enter__(self):status.update(subscribed=True,active=True,disconnected=False);return self
        def __exit__(self,*_):
            status.update(active=False,disconnected=True)
            if knobs['on_exit']:knobs['on_exit']()
        def summary(self):return deepcopy(status)
    captures=[]
    def capture(*args,**kw):
        assert status['active'];kw['check']();captures.append(True)
        assert callable(kw['stock_reader'])
        if knobs['on_capture']:knobs['on_capture']()
        kw['check']();return deepcopy(current)
    def export(path,cs,units):
        assert status['active'];assert cs=='' and units==0
        assert Path(str(prepare_path)+'.apply_attempt.json').is_file()
        durable=json.loads(receipt.read_text());assert durable['native_dispatch_pending'] and not durable['native_call_returned']
        if not knobs['no_file']:Path(path).write_bytes(b'exported stock')
        if knobs['on_native']:knobs['on_native']()
        return knobs['returned']
    exporter=Mock(side_effect=export);machine=N(CreateSTLOfStock=exporter);sw=N(GetProcessID=lambda:731)
    monkeypatch.setattr(cam,'capture_guarded_mill_inventory',capture)
    monkeypatch.setattr(cam,'raw_part_identity',lambda *_:deepcopy(current['document']))
    monkeypatch.setattr(cam,'_bootstrap',Mock(return_value=object()))
    monkeypatch.setattr(cam,'_mill_snapshot',lambda *a,**k:({},dict(machine=machine)))
    monkeypatch.setattr(cam,'_typed',lambda value,name,_:value if name=='ICWMachine5' else None)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    def compare(expected,actual):
        assert status['disconnected'] and not status['active']
        if knobs['compare_failure']:raise ValueError('Mesh geometry differs')
        return dict(equivalent_within_verification_tolerance=True,expected_file=dict(sha256=cam._file_hash(expected)),actual_file=dict(sha256=cam._file_hash(actual)))
    comparator=Mock(side_effect=compare);monkeypatch.setattr(cam,'compare_stock_meshes',comparator)
    base=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=cam._file_hash(part),expected_stock_path=str(stl),
        expected_stock_sha256=cam._file_hash(stl),expected_stock_bounds_native=bounds,output_dir=str(output_dir),
        qualification_only=True,acknowledge_disposable_copy=True,acknowledge_document_wide_export=True)
    def run(action='prepare',**changes):
        data=base|dict(action=action,receipt_path=str(prepare_path if action=='prepare' else receipt))
        if action=='apply':
            p=json.loads(prepare_path.read_text());data.update(expected_state_sha256=p['state_sha256'],prepare_receipt_path=str(prepare_path),prepare_receipt_sha256=cam._file_hash(prepare_path))
        return cam.export_empty_mill_stock(sw,'clsid','tlb',**(data|changes))
    return N(**locals())


def test_one_export_consumes_prepare_no_CAD_edits_and_mesh_keeps_unknown_offsets(probe):
    p=probe.run();assert p['apply_eligible'],p
    assert not probe.output_dir.exists();probe.exporter.assert_not_called();probe.comparator.assert_not_called()
    out=probe.run('apply');assert out['status']=='review_required' and out['readback_verified'] and out['mesh_content_verified'],out
    assert out['offset_read_status']=='unavailable_native_false'
    assert not any(out[k] for k in ['offsets_verified','AFR_gate_opened','AFR_attempted','GOP_attempted','GTP_attempted','model_saved','stock_edit_attempted','material_edit_attempted','TechDB_write_attempted','production_qualified'])
    probe.exporter.assert_called_once_with(str(probe.output_dir/'stock.stl'),'',0)
    again=probe.run('apply',receipt_path=str(probe.tmp_path/'repeat.json'))
    assert not again['native_call_attempted'];assert probe.exporter.call_count==1

@pytest.mark.parametrize('kind',['pid','source','material','stock','dirty','features','event','prepare_changed','mass_change','body_visibility','options','operations','input_file','output_exists','mode','offset_status'])
def test_preconditions_stop_before_export(probe,kind):
    assert probe.run()['apply_eligible'];extra={}
    if kind=='pid':extra['process_id']=732
    if kind=='source':probe.part.write_bytes(b'other')
    if kind=='material':probe.current['material_raw']='6061-T6'
    if kind=='stock':probe.current['stock']['coordinate_system']='another'
    if kind=='dirty':probe.current['document']['needs_save']=True
    if kind=='features':probe.current['features']=[{}]
    if kind=='event':probe.knobs['on_capture']=lambda:probe.status.update(event_count=1)
    if kind=='prepare_changed':
        data=json.loads(probe.prepare_path.read_text());data['request']['output_dir']='C:/other';probe.prepare_path.write_text(json.dumps(data))
    if kind=='mass_change':probe.current['sw_reference']['solids'][0]['mass_raw'][3]=2.
    if kind=='body_visibility':probe.current['visible_solid_body_count']=0
    if kind=='options':probe.current['recognition_options']['new']=True
    if kind=='operations':probe.current['operation_counts']=[1]
    if kind=='input_file':probe.stl.write_bytes(b'changed')
    if kind=='output_exists':probe.output_dir.mkdir()
    if kind=='mode':probe.current['recognition_method']['value']=1
    if kind=='offset_status':probe.current['stock']['offset_read_status']='observed_native_true'
    out=probe.run('apply',**extra);assert not out['native_call_attempted'],out;probe.exporter.assert_not_called()

@pytest.mark.parametrize('kind',['stock','material','dirty','options','operations','body','event','exception','no_file','returnedfalse','returnedint','input_file','mesh'])
def test_unexpected_native_effect_uncertain_consumed_no_retry(probe,kind):
    probe.run()
    def changed():
        if kind=='stock':probe.current['stock']['bounds_native'][0]=-1.
        if kind=='material':probe.current['material_raw']='316S'
        if kind=='dirty':probe.current['document']['needs_save']=True
        if kind=='options':probe.current['recognition_options']['new']=True
        if kind=='operations':probe.current['operation_counts']=[1]
        if kind=='body':probe.current['sw_reference']['solids'][0]['mass_raw'][3]=2.
        if kind=='event':probe.status['event_count']=1
        if kind=='exception':raise RuntimeError('native outcome unknown')
        if kind=='input_file':probe.stl.write_bytes(b'changed')
    probe.knobs.update(on_native=changed,no_file=kind=='no_file',returned=False if kind=='returnedfalse' else 1 if kind=='returnedint' else True,compare_failure=kind=='mesh')
    out=probe.run('apply');assert out['status']=='uncertain' and not out['readback_verified'] and not out['mesh_content_verified'],out
    assert probe.exporter.call_count==1
    again=probe.run('apply',receipt_path=str(probe.tmp_path/'retry.json'));assert not again['native_call_attempted'];assert probe.exporter.call_count==1


def test_pending_receipt_failure_prevents_native_export(probe,monkeypatch):
    probe.run();original=cam._write_receipt
    def fail(path,report,**kw):
        if report.get('native_dispatch_pending'):raise OSError('durability failed')
        return original(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    out=probe.run('apply');assert not out['native_call_attempted'];probe.exporter.assert_not_called()
    assert Path(str(probe.prepare_path)+'.apply_attempt.json').is_file()

@pytest.mark.parametrize('kind',['source','identity','event','output'])
def test_cleanup_drift_stops_before_mesh_claim(probe,kind):
    probe.run()
    def changed():
        if kind=='source':probe.part.write_bytes(b'changed')
        if kind=='identity':probe.current['document']['title']='other'
        if kind=='event':probe.status['disconnect_errors'].append('failure')
        if kind=='output':(probe.output_dir/'stock.stl').write_bytes(b'changed')
    probe.knobs['on_exit']=changed
    out=probe.run('apply');assert out['status']=='uncertain' and not out['mesh_content_verified'],out
    probe.comparator.assert_not_called()


def test_existing_mass_roundoff_keeps_prepare_anchor(probe):
    p=probe.run();raw=probe.prepare_path.read_bytes()
    probe.current['sw_reference']['solids'][0]['mass_raw'][3]*=1+1e-12
    out=probe.run('apply');assert out['readback_verified'],out
    assert probe.prepare_path.read_bytes()==raw and out['state_sha256']==p['state_sha256']
