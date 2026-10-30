"""Circular lifecycle saves only pinned creator geometry and original SW reference."""
from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_sw_cam_circular_mill_qualification import case,cam
from scripts import sw_cam_mill_feature_lifecycle as lifecycle
from scripts import sw_cam_circle_lifecycle_evidence as evidence
from scripts import sw_cam_lifecycle as dispatch

@pytest.fixture
def saved(case,monkeypatch):
    creation=case.apply()
    assert creation['status']=='review_required',creation
    creator_path=case.receipt
    source_hash=lifecycle._file_hash(case.part)
    state=deepcopy(creation['after'])
    state['selected_feature']=state.pop('features')[0]
    state.update(operations=[],operation_setup_count=0,feature_kind='circular_pocket')
    output=case.tmp_path/'lifecycle.json'
    app=N(GetUseDocumentUnit=lambda:True)
    knobs=dict(returned=0,on_save=None)
    def save():
        assert case.status['active']
        durable=json.loads(output.read_text())
        assert durable['native_dispatch_pending'] and not durable['native_call_returned']
        case.document['needs_save']=False
        case.part.write_bytes(b'saved circular CAM')
        if knobs['on_save']:knobs['on_save']()
        return knobs['returned']
    app.SaveActiveDocument=Mock(side_effect=save)
    app.CloseActiveDocument=Mock(side_effect=AssertionError('not requested'))
    def capture(*args,**kw):
        assert kw['feature_kind']=='circular_pocket' and kw['expected_feature_native_id']==99
        kw['check']()
        value=deepcopy(state)
        value['document']=deepcopy(case.document)
        value['saved_file_sha256']=lifecycle._file_hash(case.part)
        return value,dict(app=app)
    monkeypatch.setattr(lifecycle,'capture_mill_feature_state',capture)
    monkeypatch.setattr(lifecycle,'_bootstrap',Mock(return_value=app))
    monkeypatch.setattr(lifecycle,'_typed',lambda obj,*_:obj)
    for name in ('_read_sketch','_features','_bodies'):
        monkeypatch.setattr(evidence,name,getattr(cam,name))
    base=dict(process_id=731,expected_document_path=str(case.part),acknowledge_qualification_copy=True,
        expected_feature_native_id=99,expected_operation_native_ids=[],feature_kind='circular_pocket',
        expected_source_sha256=source_hash,circle_creation_receipt_path=str(creator_path),
        circle_creation_receipt_sha256=lifecycle._file_hash(creator_path))
    def run(action='prepare',**kwargs):
        return lifecycle.mill_feature_document_lifecycle(case.sw,'clsid','tlb',action=action,**(base|kwargs))
    def apply(**kwargs):
        p=run();assert p['status']=='ok',p
        return run('save',expected_state_sha256=p['state_sha256'],receipt_path=str(output),**kwargs)
    return N(**locals())

def test_save_single_exact_circle_and_reuse_immutable_creation(saved):
    p=saved.run()
    assert p['status']=='ok' and not saved.app.SaveActiveDocument.called
    assert p['before']['feature_kind']=='circular_pocket'
    out=saved.apply()
    assert out['status']=='review_required' and out['save_readback_verified'],out
    assert not out['persistence_verified'] and not out['physical_depth_verified']
    assert out['after']['selected_feature']==saved.creation['observed_feature']
    assert out['after']['circle_reference']==out['before']['circle_reference']
    assert lifecycle._file_hash(saved.creator_path)==saved.base['circle_creation_receipt_sha256']
    saved.app.SaveActiveDocument.assert_called_once_with()
    saved.app.CloseActiveDocument.assert_not_called()

@pytest.mark.parametrize('kind',['hash','source','feature','sketch','body','tree'])
def test_pin_failure_never_saves(saved,kind):
    extra={}
    if kind=='hash':extra['circle_creation_receipt_sha256']='0'*64
    if kind=='source':extra['expected_source_sha256']='0'*64
    if kind=='feature':saved.state['selected_feature']['depth_native']=5
    if kind=='sketch':saved.case.sketch['entities'][0]['radius_m']+=.001
    if kind=='body':saved.case.state['solids'][0]['mass_raw'][3]*=2
    if kind=='tree':saved.case.state['tree'].append(dict(name='unexpected',type='Cut'))
    out=saved.run(**extra)
    assert out['status']=='error',out
    saved.app.SaveActiveDocument.assert_not_called()

@pytest.mark.parametrize('value',[None,1,False,True,'success',0.])
def test_hresult_strict_and_single_call(saved,value):
    saved.knobs['returned']=value
    out=saved.apply()
    assert out['status']=='uncertain' and not out['save_readback_verified']
    saved.app.SaveActiveDocument.assert_called_once_with()

def test_saved_geometry_drift_after_native_is_uncertain(saved):
    saved.knobs['on_save']=lambda:saved.state['selected_feature'].update(depth_native=9.)
    out=saved.apply()
    assert out['status']=='uncertain' and not out['save_readback_verified']
    saved.app.SaveActiveDocument.assert_called_once_with()

def test_receipt_changed_after_prepare_stops_save(saved):
    p=saved.run();saved.creator_path.write_text('{}')
    out=saved.run('save',expected_state_sha256=p['state_sha256'],receipt_path=str(saved.output))
    assert out['status']=='error'
    saved.app.SaveActiveDocument.assert_not_called()

@pytest.mark.parametrize('value',[0,1,None,0.])
def test_raw_dirty_type_not_coerced(saved,value):
    saved.case.document['needs_save']=value
    out=saved.run()
    assert out['status']=='error';saved.app.SaveActiveDocument.assert_not_called()

def test_existing_save_receipt_not_overwritten(saved):
    p=saved.run();saved.output.write_text('old')
    out=saved.run('save',expected_state_sha256=p['state_sha256'],receipt_path=str(saved.output))
    assert out['status']=='error' and saved.output.read_text()=='old'
    saved.app.SaveActiveDocument.assert_not_called()

@pytest.mark.parametrize('field,value',[
 ('status','uncertain'),('readback_verified',False),('creation_delta_verified',False),
 ('physical_depth_verified',True),('contour_readback_verified',False)])
def test_invalid_creator_evidence_not_trusted(saved,field,value):
    raw=json.loads(saved.creator_path.read_text());raw[field]=value
    saved.creator_path.write_text(json.dumps(raw))
    out=saved.run(circle_creation_receipt_sha256=lifecycle._file_hash(saved.creator_path))
    assert out['status']=='error';saved.app.SaveActiveDocument.assert_not_called()

def test_default_dispatch_does_not_forward_new_fields(monkeypatch):
    mock=Mock(return_value={'ok':True})
    monkeypatch.setattr(lifecycle,'mill_feature_document_lifecycle',mock)
    dispatch.document_lifecycle(object(),'clsid','tlb',expected_document_path='C:/fixture.sldprt',
        action='prepare',machine_kind='mill_single_feature_qualification',process_id=1,
        acknowledge_qualification_copy=True,expected_feature_native_id=2,expected_operation_native_ids=[])
    assert not {'feature_kind','expected_source_sha256','circle_creation_receipt_path','circle_creation_receipt_sha256'} & mock.call_args.kwargs.keys()


@pytest.mark.parametrize('key',['current_machine','mill_catalogue','feature_setups','material_raw',
                               'extend_holes_to_stock','unit_record_raw','unit_record_status'])
def test_creator_context_not_silently_rebased(saved,key):
    saved.state[key]=['changed']
    out=saved.run()
    assert out['status']=='error';saved.app.SaveActiveDocument.assert_not_called()

def test_exact_raw_bytes_hash_prevents_aba_receipt_read(saved,monkeypatch):
    original=evidence.Path.read_bytes
    def swapped(path):
        raw=original(path)
        return raw+b' ' if path==saved.creator_path else raw
    monkeypatch.setattr(evidence.Path,'read_bytes',swapped)
    # Keep before/after path hashes as the originally pinned state.
    original_hash=evidence._file_hash
    monkeypatch.setattr(evidence,'_file_hash',lambda p:saved.base['circle_creation_receipt_sha256']
        if str(p)==str(saved.creator_path) else original_hash(p))
    out=saved.run()
    assert out['status']=='error';saved.app.SaveActiveDocument.assert_not_called()

def test_creator_unit_flags_pinned(saved):
    saved.app.GetUseDocumentUnit=lambda:False
    out=saved.run()
    assert out['status']=='error';saved.app.SaveActiveDocument.assert_not_called()
