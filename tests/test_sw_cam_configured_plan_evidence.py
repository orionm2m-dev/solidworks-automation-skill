"""Saved tool continuation rejects stale, partial, or inconsistent evidence."""
from copy import deepcopy
import pytest
from test_sw_cam_shared_cutter_config import evidence_case, lifecycle
from test_sw_cam_shared_holder_geometry import build_case
from scripts import sw_cam_configured_plan_evidence as m
from scripts.sw_cam_turn_tool import _digest

@pytest.fixture
def configured(evidence_case, monkeypatch):
    c = evidence_case
    holder = build_case(c['part'].parent)
    out, pointer = lifecycle(c, monkeypatch, holder_case=holder, save=True)
    assert out['save_readback_verified'] is True
    previous = c['e'].load_cutter_evidence(**c['args'])
    binding = dict(process_id=c['args']['process_id'],
        expected_document_path=str(c['part']), expected_source_sha256=out['saved_file_sha256'])
    return out, previous, holder[0], binding, pointer

def test_saved_continuation_preserves_current_state_without_mutation(configured):
    out, previous, holder, binding, pointer = configured
    events = deepcopy(pointer.events)
    assert m.validate_saved_configuration(out, previous, holder, **binding)
    evidence = m.ConfiguredPlanEvidence(out, dict(path='receipt',sha256='a'*64), previous, holder)
    assert evidence.state == out['saved'] and evidence.verify(out['saved'])
    assert evidence.data == out
    assert evidence.state['operations'][0]['assigned_tool']['cut_diameter_native'] == 2
    assert evidence.summary()['original_receipts_modified'] is False
    assert pointer.events == events
    changed = deepcopy(out['saved'])
    changed['operations'][0]['assigned_tool']['cut_diameter_native'] = 20
    with pytest.raises(ValueError):evidence.verify(changed)

@pytest.mark.parametrize('field', m.TRUE_FLAGS)
def test_incomplete_save_rejected(configured, field):
    out, previous, holder, binding, _ = configured
    out[field] = False
    with pytest.raises(ValueError):m.validate_saved_configuration(out,previous,holder,**binding)

@pytest.mark.parametrize('field', m.FALSE_FLAGS)
def test_unexpected_action_rejected(configured, field):
    out, previous, holder, binding, _ = configured
    out[field] = True
    with pytest.raises(ValueError):m.validate_saved_configuration(out,previous,holder,**binding)

@pytest.mark.parametrize('fault', ['pid','dirty','source','before_source','state_digest',
    'continuation','tool_digest','profile','lineage','holder_reference','holder_proof',
    'save_bool_hresult','changed_sibling','wrong_shared_user','cleanup','failed_phase'])
def test_corrupt_save_rejected(configured, fault):
    out, previous, holder, binding, _ = configured
    if fault=='pid':binding['process_id']+=1
    if fault=='dirty':out['saved']['document']['needs_save']=True
    if fault=='source':binding['expected_source_sha256']='0'*64
    if fault=='before_source':out['source_before_sha256']='0'*64
    if fault=='state_digest':out['state_sha256']='0'*64
    if fault=='continuation':out['continuation_state']={}
    if fault=='tool_digest':out['tool_details_sha256']='0'*64
    if fault=='profile':out['profile_comparison']['nominal_raw_cutter_profile_verified']=False
    if fault=='lineage':out['anchor']['target_geometry']['OverallLen']=40
    if fault=='holder_reference':out['holder_reference']['after']='wrong.mh'
    if fault=='holder_proof':out['holder_profile_readback_verified']=False
    if fault=='save_bool_hresult':out['save_hresult']=False
    if fault=='changed_sibling':out['after']['operations'][1]['assigned_tool']['native_id']=146
    if fault=='wrong_shared_user':
        for label in ('saved_tool_details','after_tool_details'):
            out[label]['items'][1]['operation_native_id']=999
        out['tool_details_sha256']=_digest(out['saved_tool_details'])
    if fault=='cleanup':out['messages']['event_count']=1
    if fault=='failed_phase':out['failed_phase']='saved'
    with pytest.raises((ValueError,KeyError)):
        m.validate_saved_configuration(out,previous,holder,**binding)

def test_existing_loader_routes_configuration_explicitly(tmp_path, monkeypatch):
    from scripts import sw_cam_mill_saved_plan_tools as old
    monkeypatch.setattr(old,'read_pin',lambda *a:({'scope':m.SCOPE},{}))
    seen=[]
    monkeypatch.setattr(m,'load_configured_plan_evidence',lambda *a,**kw:seen.append((a,kw)) or 'configured')
    args=dict(process_id=7,expected_document_path='part',expected_source_sha256='a'*64,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145)
    assert old.load_saved_plan_tools_evidence('receipt','b'*64,**args)=='configured'
    assert seen[0][1]==args
    with pytest.raises(ValueError):
        old.load_saved_plan_tools_evidence('receipt','b'*64,**args,
            session_rebind_receipt_path='another',session_rebind_receipt_sha256='c'*64)
