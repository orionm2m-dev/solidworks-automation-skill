"""Receipt-bound append reconciliation never repeats either native mutation."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_sw_cam_turn_feature_regenerate import transaction,regenerate
from scripts import sw_cam_turn_recipe_reconcile as cam
from scripts import sw_cam_turn_feature_regenerate as core


def append_block(state):
    old=deepcopy(state);ordered=[x for x in old['operations'] if x['native_id']<400]+[x for x in old['operations'] if x['native_id']>=400]
    inventory={op['native_id']:inv for op,inv in zip(old['operations'],old['inventory']['operations'])}
    state['operations']=ordered;state['inventory']['operations']=[inventory[x['native_id']] for x in ordered]
    for rows in (state['operations'],state['inventory']['operations']):
        for i,row in enumerate(rows):row['operation_index']=i
    for field in ('own_operations','nc'):
        mapping={x['operation_native_id']:x for x in old[field]};state[field]=[mapping[x['native_id']] for x in ordered]


@pytest.fixture
def completed(transaction,monkeypatch):
    t=transaction;before=deepcopy(t.state);before['copy_file_identity']=core.files(t.config,t.policy)
    attribute=deepcopy(before);attribute['current_attribute']=dict(native_id=50,name='Rough-Finish')
    attribute['current_attribute_lookup_id_raw']=50;attribute['current_id_matches_lookup']=True
    attribute['features'][1].update(attribute_id_raw=50,attribute_name='Rough-Finish')
    after=deepcopy(attribute);regenerate(after);append_block(after)
    t.state.clear();t.state.update(deepcopy(after))
    prepared=core._digest(dict(config=t.config,policy=t.policy,state=before))
    parent_path=t.tmp_path/'completed.json';marker=core.marker_path(t.config,before['copy_file_identity'])
    parent=dict(scope=core.SCOPE,status='uncertain',phase='finished',failed_phase='GenerateOpPlan_returned',
        actions={x:dict(attempted=True,returned=True) for x in ('Attribute','GenerateOpPlan')},
        native_dispatch_pending=False,readback_verified=False,native_recipe_ram_verified=False,model_saved=False,
        GTP_attempted=False,tool_assignment_attempted=False,mutation_attempted=True,
        messages=dict(subscribed=True,disconnected=True,active=False,event_count=0),
        request=dict(t.config,policy=t.policy,action='apply',expected_state_sha256=prepared,receipt_path=str(parent_path)),
        before=before,after_attribute=attribute,after=after,prepared_state_sha256=prepared,marker_path=str(marker))
    marker.write_text(json.dumps(dict(scope=core.SCOPE,status='claimed_no_replay',copy_file_identity=before['copy_file_identity'],
        feature_native_id=76,source_sha256=t.digest,receipt_path=str(parent_path),prepared_state_sha256=prepared)),encoding='utf-8')
    def publish():parent_path.write_text(json.dumps(parent),encoding='utf-8');return core._file_hash(parent_path)
    parent_sha=publish();marker_sha=core._file_hash(marker)
    monkeypatch.setattr(cam,'document_snapshot',lambda _:deepcopy(t.state['document']))
    monkeypatch.setattr(cam,'CamMessageSession',t.Session)
    params=dict(process_id=731,expected_process_create_time=1234.,expected_document_path=str(t.target),
        expected_source_sha256=t.digest,parent_receipt_path=str(parent_path),parent_receipt_sha256=parent_sha,
        expected_after_state_sha256=core._digest(after),expected_operation_order=[x['native_id'] for x in after['operations']],
        receipt_path=str(t.tmp_path/'reconcile.json'),acknowledge_append_definitions_only=True)
    def call(**changes):return cam.reconcile_turn_feature_recipe(t.sw,'clsid','tlb',**(params|changes))
    return N(**locals())


def test_append_is_opt_in_and_mutating_default_is_unchanged(completed):
    c=completed
    with pytest.raises(ValueError):core.verify_delta(c.attribute,c.after,c.t.config,c.t.policy)
    assert core.verify_delta(c.attribute,c.after,c.t.config,c.t.policy,new_position='append_definitions_only')['protected_operation_ids']==[127,135]
    with pytest.raises(ValueError):core.verify_delta(c.attribute,c.after,c.t.config,c.t.policy,new_position='anything')


def test_readonly_reconcile_preserves_original_receipt_and_marker(completed):
    c=completed;result=c.call()
    assert result['status']=='review_required' and result['readback_verified'] and result['native_recipe_ram_verified']
    assert result['full_model_geometry_verified'] is False and len(result['nc_parameter_scope'])==2
    assert result['read_only'] and not any(result[x] for x in ('mutation_attempted','route_order_qualified',
        'model_saved','GTP_attempted','tool_assignment_attempted','toolpath_coordinates_verified','persistence_verified','production_qualified'))
    assert result['final_state_sha256']==c.params['expected_after_state_sha256'] and not c.t.calls
    assert core._file_hash(c.parent_path)==c.parent_sha and core._file_hash(c.marker)==c.marker_sha
    assert json.loads(Path(c.params['receipt_path']).read_text())==result


@pytest.mark.parametrize('change',['pending','unreturned','messages','parent_state','protected_nc','marker','old_receipt_pin',
    'wrong_after_pin','wrong_order','wrong_process','no_ack','current_drift'])
def test_no_reconciliation_from_uncertain_or_different_evidence(completed,change):
    c=completed;args={}
    if change=='pending':c.parent['native_dispatch_pending']=True
    elif change=='unreturned':c.parent['actions']['GenerateOpPlan']['returned']=False
    elif change=='messages':c.parent['messages']['event_count']=1
    elif change=='parent_state':c.parent['before']['current_attribute']['native_id']=21
    elif change=='protected_nc':c.parent['after']['nc'][0]['feed_rate_ipm_native']=99.;args['expected_after_state_sha256']=core._digest(c.parent['after'])
    elif change=='marker':c.marker.write_text('{}')
    elif change=='old_receipt_pin':args['parent_receipt_sha256']='0'*64
    elif change=='wrong_after_pin':args['expected_after_state_sha256']='0'*64
    elif change=='wrong_order':args['expected_operation_order']=list(reversed(c.params['expected_operation_order']))
    elif change=='wrong_process':args['process_id']=999
    elif change=='no_ack':args['acknowledge_append_definitions_only']=False
    else:c.t.state['nc'][0]['feed_rate_ipm_native']=99.
    if change in ('pending','unreturned','messages','parent_state','protected_nc'):args['parent_receipt_sha256']=c.publish()
    result=c.call(**args)
    assert result['status']=='error' and not result['readback_verified'] and not result['native_recipe_ram_verified'] and not c.t.calls


def test_terminal_write_error_cannot_claim_reconciled(completed,monkeypatch):
    c=completed;original=cam._write_receipt
    def write(path,value,**kwargs):
        if value.get('status')=='review_required':raise OSError('terminal unavailable')
        return original(path,value,**kwargs)
    monkeypatch.setattr(cam,'_write_receipt',write)
    result=c.call()
    assert result['status']=='error' and not result['native_recipe_ram_verified'] and not c.t.calls


def test_equivalent_receipt_slash_spelling_keeps_exact_marker_binding(completed):
    c=completed
    c.parent['request']['receipt_path']=c.parent_path.as_posix()
    result=c.call(parent_receipt_sha256=c.publish())
    assert result['readback_verified'] and not result['route_order_qualified'] and not c.t.calls
    assert core._file_hash(c.marker)==c.marker_sha
