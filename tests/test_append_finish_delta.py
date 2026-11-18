"""Independent pure-delta tests using one pinned saved receipt read per test session.

Set CAM_FINISH_TEST_RECEIPT and CAM_FINISH_TEST_RECEIPT_SHA to run the saved-case
qualification. These tests never access an application or write that evidence.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json,os,sys
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]))
STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_append_finish_definitions as m


@pytest.fixture(scope='session')
def saved_once():
    path=os.environ.get('CAM_FINISH_TEST_RECEIPT');digest=os.environ.get('CAM_FINISH_TEST_RECEIPT_SHA')
    if not path or not digest:pytest.skip('Pinned saved-case qualification receipt not supplied')
    raw=Path(path).read_bytes();assert hashlib.sha256(raw).hexdigest()==digest
    r=json.loads(raw);assert r['status']=='review_required' and r['phase']=='finished' and r['model_saved']is True
    state=r['saved'];assert state['operation_count']==26 and len(state['operations'])==26
    assert sum(bool(x['toolpath_record_counts'])for x in state['operations'])==19
    assert sum(sum(x['toolpath_record_counts'])for x in state['operations'])==83563
    return state


@pytest.fixture
def before(saved_once):return deepcopy(saved_once)


def added_state(before,tools=(249,249)):
    out=deepcopy(before);anchor=before['operations'][-1];rows=[];pb=out['parameter_batch']
    for i,(oid,fid,tid) in enumerate(zip((80001,80002),(359,70),tools)):
        generic=next(x for x in pb['toolcrib_catalogue']if x['native_id']==tid)
        row=dict(setup_index=anchor['setup_index'],setup_native_id=anchor['setup_native_id'],operation_index=anchor['operation_index']+i+1,native_id=oid,
            mill_operation_type=1,base_operation_type=0,suppressed=False,toolpath_generated=False,linked_feature_ids=[fid],toolpath_record_counts=[],assigned_tool=deepcopy(generic))
        rows.append(row);out['operations'].append(deepcopy(row))
        if tid==pb['candidate_tool']['generic']['native_id']:
            pb['candidate_consumer_ids'].append(oid);consumer=deepcopy(pb['candidate_consumers']['361']);consumer['operation_native_id']=oid
            pb['candidate_consumers'][str(oid)]=consumer
    si=anchor['setup_index'];out['operation_count']+=2;out['operation_counts'][si]+=2;out['operation_setups'][si]['operation_count']+=2;out['selected_operation_setup']['operation_count']+=2
    out['document']['needs_save']=True;out['sketch_state']['needs_save']=True
    return out,rows


def recipe(before):
    return dict(scope=m.SCOPE,producer_operation_native_id=361,anchor_operation_native_id=361,definitions=[
        dict(role='floor',feature_native_id=359,feature_owner_setup_native_id=71,operation_setup_native_id=94,default_operation_id=146,default_operation_name='Contour and floor machining',expected_bottom_finish=True),
        dict(role='wall',feature_native_id=70,feature_owner_setup_native_id=71,operation_setup_native_id=94,default_operation_id=145,default_operation_name='Contour machining',expected_bottom_finish=False)])


def test_actual26_prefix_two_empty_definitions_keep_all19_paths(before):
    after,rows=added_state(before);proof=m.verify_appended(before,after,rows)
    assert proof['existing_operation_count']==26 and proof['new_operation_ids']==[80001,80002]
    assert after['operations'][:26]==before['operations']
    assert sum(sum(x['toolpath_record_counts'])for x in after['operations'])==83563
    assert m.validate_recipe(recipe(before),before)==recipe(before)


def test_defaults_can_use_existing_other_tool_without_mutating249(before):
    after,rows=added_state(before,tools=(252,252));m.verify_appended(before,after,rows)
    assert after['parameter_batch']==before['parameter_batch']


@pytest.mark.parametrize('fault',['old_path','old_row','feature359','profile70','tool249','toolcrib','old_consumer','target_nc','unknown_consumer','missing_consumer','consumer_identity','consumer_incomplete','consumer_order','source_path','source_hash','dirty_integer','sketch_dirty_integer','defaults','generation','suffix_order','duplicate_id','wrong_setup','old_setup_count'])
def test_no_protected_changes_or_forged_growth_accepted(before,fault):
    after,rows=added_state(before);pb=after['parameter_batch']
    if fault=='old_path':after['operations'][0]['toolpath_record_counts']=[999]
    elif fault=='old_row':after['operations'][0]['suppressed']=not before['operations'][0]['suppressed']
    elif fault=='feature359':after['target_header']['depth_native']=7.6
    elif fault=='profile70':after['reference_profile']['observed_steps'][1]['diameter_native']=17.9
    elif fault=='tool249':pb['candidate_tool']['generic']['cut_diameter_native']=7.9
    elif fault=='toolcrib':pb['toolcrib_catalogue'][0]['cut_diameter_native']+=1.
    elif fault=='old_consumer':pb['candidate_consumers']['361']['feeds_compensation']['XYFeed']+=1.
    elif fault=='target_nc':pb['target_nc']['361']['feeds_compensation']['GetSpndlSpeed']+=1.
    elif fault=='unknown_consumer':pb['candidate_consumer_ids'].append(999);pb['candidate_consumers']['999']=deepcopy(pb['candidate_consumers']['80001'])
    elif fault=='missing_consumer':del pb['candidate_consumers']['80001']
    elif fault=='consumer_identity':pb['candidate_consumers']['80001']['operation_native_id']=999
    elif fault=='consumer_incomplete':pb['candidate_consumers']['80001']['read_complete']=False
    elif fault=='consumer_order':pb['candidate_consumer_ids'][-2:]=[80002,80001]
    elif fault=='source_path':after['document']['path']+='-other'
    elif fault=='source_hash':after['source_sha256']='0'*64
    elif fault=='dirty_integer':after['document']['needs_save']=1
    elif fault=='sketch_dirty_integer':after['sketch_state']['needs_save']=1
    elif fault=='defaults':after['target_catalogues'][1]['entries'][0]['default_operation_id']+=1
    elif fault=='generation':after['operations'][-1]['toolpath_generated']=True;after['operations'][-1]['toolpath_record_counts']=[1];rows[-1]=deepcopy(after['operations'][-1])
    elif fault=='suffix_order':after['operations'][-2:]=list(reversed(after['operations'][-2:]))
    elif fault=='duplicate_id':rows[-1]['native_id']=361;after['operations'][-1]['native_id']=361
    elif fault=='wrong_setup':rows[-1]['setup_native_id']=93;after['operations'][-1]['setup_native_id']=93
    elif fault=='old_setup_count':after['operation_setups'][0]['operation_count']+=1
    with pytest.raises(ValueError):m.verify_appended(before,after,rows)


@pytest.mark.parametrize('fault',['wrong_anchor','swapped_roles','wrong_floor_default','wrong_bottom_mode','wrong_owner','boolean_id','feature_alias'])
def test_recipe_exact_current_feature_and_default_binding(before,fault):
    value=recipe(before)
    if fault=='wrong_anchor':value['anchor_operation_native_id']=358
    elif fault=='swapped_roles':value['definitions'].reverse()
    elif fault=='wrong_floor_default':value['definitions'][0]['default_operation_id']=145
    elif fault=='wrong_bottom_mode':value['definitions'][0]['expected_bottom_finish']=False
    elif fault=='wrong_owner':value['definitions'][0]['feature_owner_setup_native_id']=69
    elif fault=='boolean_id':value['definitions'][0]['feature_native_id']=True
    elif fault=='feature_alias':value['definitions'][1]['feature_native_id']=359
    with pytest.raises(ValueError):m.validate_recipe(value,before)


def test_compact_link_check_rejects_same_schema_wrong_new_feature(before):
    after,rows=added_state(before);definition=recipe(before)['definitions'][-1]
    compact={k:deepcopy(after[k])for k in m.BASE_KEYS};compact['target_header']=deepcopy(before['reference_header']);compact['profile']=deepcopy(before['reference_profile'])
    assert m.verify_compact(before,compact,rows,definition,80002)['native_id']==80002
    compact['operations'][-1]['linked_feature_ids']=[359];rows[-1]['linked_feature_ids']=[359]
    with pytest.raises(ValueError):m.verify_compact(before,compact,rows,definition,80002)
