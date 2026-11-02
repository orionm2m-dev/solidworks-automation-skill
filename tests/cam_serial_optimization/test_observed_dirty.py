from copy import deepcopy
import pytest
from test_optimization_workflow import workflow
from test_optimization_prepare import fixture_prepare
from scripts import sw_cam_local_serial_optimization as m

def test_actual_dirty_input_not_normalized_in_full_workflow(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch);doc=deepcopy(l['guide_parameters']['document'])
    r=m.run_once(b,j,l)
    assert doc['needs_save']is True and l['guide_parameters']['document']==doc
    assert r['source_transition']['document']['needs_save']is False
    assert b.calls.count('save')==1 and b.calls.count('generate')==4
    assert m.validate_completed(r,l)['paths']==18

@pytest.mark.parametrize('change',['path','unexpected_identity','saved_still_dirty','input_clean','input_bool_int','missing_save','wrong_source'])
def test_only_dirty_to_clean_transition_is_accepted(tmp_path,monkeypatch,change):
    b,j,l=workflow(tmp_path,monkeypatch);r=m.run_once(b,j,l)
    if change=='path':r['source_transition']['document']['path']+='changed'
    elif change=='unexpected_identity':r['source_transition']['document']['title']='other'
    elif change=='saved_still_dirty':r['source_transition']['document']['needs_save']=True
    elif change=='input_clean':l['guide_parameters']['document']['needs_save']=False
    elif change=='input_bool_int':l['guide_parameters']['document']['needs_save']=1
    elif change=='missing_save':r['save_stage']['save_attempted']=False
    else:r['source_transition']['source_before_sha256']='c'*64
    with pytest.raises(ValueError):m.validate_completed(r,l)

def test_prepare_keeps_verified_observed_dirty(tmp_path,monkeypatch):
    req,l,q=fixture_prepare(tmp_path,monkeypatch)
    p,loaded,*_=m.prepare_request(req)
    assert loaded['guide_parameters']['document']['needs_save']is True
    assert loaded['guide_parameters']['document']==l['guide_parameters']['document']
    assert loaded['pin_partition']['serial_completed_loader_live']is True

@pytest.mark.parametrize('value',[False,1,None])
def test_prepare_rejects_unqualified_clean_or_wrong_type(tmp_path,monkeypatch,value):
    req,l,q=fixture_prepare(tmp_path,monkeypatch);l['guide_parameters']['document']['needs_save']=value
    with pytest.raises(ValueError):m.prepare_request(req)
