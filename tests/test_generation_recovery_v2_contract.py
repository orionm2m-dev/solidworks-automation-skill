"""Independent pure admission tests. No CAD, filesystem authority or native seams mocked.
Fixture is an observed V2 partial receipt with sample paths and part names; no status or scope relabelling.
All numeric CAM observations are retained; repeated capture aliases are rebuilt below.
"""
from copy import deepcopy
import json, os, sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pocket_generation_recovery_v2 as c


def sync_captures(raw):
    for capture in raw['captures']:
        state=raw[capture['label']]
        capture['observation']=deepcopy(state)
        capture['diagnostic']['state']=deepcopy(state['inventory'])


@pytest.fixture
def case():
    raw=json.loads((Path(__file__).parent/'fixtures/observed_generation_v2_partial.json').read_text(encoding='utf-8'))
    sync_captures(raw)
    v={k:deepcopy(raw['request'][k])for k in c.IDENTITY}
    v.update(failed_generation_receipt_path='C:/cad/partial.json',failed_generation_receipt_sha256='a'*64,
        observed_xy_feed_before=raw['configured']['parameters'][0]['nc']['feeds_compensation']['XYFeed'],
        observed_xy_feed_after=raw['generated']['parameters'][0]['nc']['feeds_compensation']['XYFeed'],
        receipt_path='C:/cad/recovery.json',saved_cl_path='C:/cad/fresh/path.cl',qualification_only=True,
        acknowledge_observed_feed_save_export=True,message_policy='vendor_default')
    bundle={'state':deepcopy(raw['before']['inventory']),'parameters':deepcopy(raw['before']['parameters'])}
    return raw,v,bundle,deepcopy(raw['recipe'])


def verify(case):return c.verify_partial(*case)


def test_exact_observed_exception_and_inputs_are_not_modified(case):
    old=deepcopy(case);proof=verify(case)
    assert case==old and case[0]['status']=='uncertain'
    assert proof['expected_state']==case[0]['generated']
    assert proof['generation_proof']['selected_record_count']==21016
    assert proof['generation_proof']['protected_operation_native_ids']==[70]
    assert proof['feed_delta']==dict(operation_native_id=69,path='/parameters/0/nc/feeds_compensation/XYFeed',
        before=742.7489637568661,after=1485.4979275137323,feed_unqualified=True,cause_verified=False)
    proof['expected_state']['parameters'][0]['nc']['feeds_compensation']['XYFeed']=1.0
    assert case==old


def test_no_universal_times_two_rule_or_native_unit_qualification(case):
    raw,v,_,_=case
    raw['generated']['parameters'][0]['nc']['feeds_compensation']['XYFeed']=901.125
    v['observed_xy_feed_after']=901.125;sync_captures(raw)
    proof=verify(case)
    assert proof['feed_delta']['after']==901.125 and proof['feed_delta']['feed_unqualified']is True
    assert proof['generation_proof']['production_qualified']is False
    assert proof['generation_proof']['world_geometry_verified']is False


@pytest.mark.parametrize('key,value',[
 ('observed_xy_feed_before',742.0),('observed_xy_feed_after',1485.0),
 ('observed_xy_feed_after',True),('observed_xy_feed_after',float('nan')),
 ('observed_xy_feed_after',float('inf')),('observed_xy_feed_after',0),
 ('acknowledge_observed_feed_save_export',False),('qualification_only',False),
 ('selected_operation_native_id',70),('process_id',1234.0),
 ('expected_source_sha256','b'*64),('expected_document_path','C:/cad/other.SLDPRT')])
def test_explicit_request_binding_is_strict(case,key,value):
    case[1][key]=value
    with pytest.raises(ValueError):verify(case)


@pytest.mark.parametrize('key,value',[
 ('status','review_required'),('phase','generated'),('failed_phase','configured'),
 ('native_dispatch_pending',True),('native_call_returned',False),
 ('Save_attempted',True),('save_attempted',True),('model_saved',True),
 ('CL_export_attempted',True),('GOP_attempted',True),('Import_attempted',True),
 ('automatic_replay',True),('runtime_unchanged',True),('generation_verified',True),
 ('cleanup_error',{}),('runtime_error',{}),('receipt_write_error',{})])
def test_failure_save_replay_and_partial_boundary_cannot_be_relabelled(case,key,value):
    case[0][key]=value
    with pytest.raises(ValueError):verify(case)


@pytest.mark.parametrize('key,value',[
 ('attempted',False),('returned',False),('native_dispatch_pending',True),
 ('native_return_type','bool'),('native_return_value',True),('native_return_value',False),
 ('native_return_value',0.0),('native_return_value',1)])
def test_historical_gtp_requires_completed_strict_int_zero(case,key,value):
    case[0]['actions']['GTP:69'][key]=value
    with pytest.raises(ValueError):verify(case)


@pytest.mark.parametrize('where',[
 'aggregate_count','aggregate_total','selected_count','second_path','second_feed','selected_other_feed',
 'selected_parameter','feature_origin','operation_origin','tool','source','cad_feature'])
def test_all_other_generated_fields_remain_protected_even_with_complete_capture(case,where):
    raw=case[0];x=raw['generated'];inv=x['inventory'];p=x['parameters']
    if where=='aggregate_count':inv['generated_operation_count']=2
    elif where=='aggregate_total':inv['total_record_count']+=1
    elif where=='selected_count':inv['operations'][0]['toolpath_record_counts']=[21015]
    elif where=='second_path':
        inv['operations'][1].update(toolpath_generated=True,toolpath_record_counts=[3])
        inv.update(generated_operation_count=2,total_record_count=21019)
    elif where=='second_feed':p[1]['nc']['feeds_compensation']['XYFeed']+=0.01
    elif where=='selected_other_feed':p[0]['nc']['feeds_compensation']['GetSpndlSpeed']+=0.01
    elif where=='selected_parameter':p[0]['rough']['unexpected_parameter']=1
    elif where=='feature_origin':inv['feature_setups'][0]['unexpected_origin']=1
    elif where=='operation_origin':inv['operation_setups'][0]['unexpected_origin']=1
    elif where=='tool':inv['operations'][0]['assigned_tool']['cut_diameter_native']+=0.01
    elif where=='source':inv['saved_file_sha256']='b'*64
    elif where=='cad_feature':inv['selected_feature']['unexpected_geometry']=1
    sync_captures(raw)
    with pytest.raises(ValueError):verify(case)


@pytest.mark.parametrize('kind',['incomplete','observation_mismatch','state_mismatch','missing','unexpected'])
def test_full_capture_witnesses_must_match_claimed_snapshots(case,kind):
    cs=case[0]['captures']
    if kind=='incomplete':cs[2]['diagnostic']['capture_complete']=False
    elif kind=='observation_mismatch':cs[2]['observation']['parameters'][0]['nc']['feeds_compensation']['XYFeed']=1.0
    elif kind=='state_mismatch':cs[2]['diagnostic']['state']['total_record_count']=1
    elif kind=='missing':cs.pop()
    else:cs.append(deepcopy(cs[-1]))
    with pytest.raises(ValueError):verify(case)


@pytest.mark.parametrize('key,value',[
 ('active',True),('disconnected',False),('event_count',1),('overflow',1),
 ('callback_errors',[{}]),('disconnect_errors',[{}]),('subscription_error',{})])
def test_original_message_cleanup_must_be_clean(case,key,value):
    case[0]['messages'][key]=value
    with pytest.raises(ValueError):verify(case)


def test_action_and_readback_provenance_cannot_omit_or_add_native_calls(case):
    raw=case[0];raw['actions']['SaveActiveDocument']=deepcopy(raw['actions']['GTP:69'])
    with pytest.raises(ValueError):verify(case)
    raw['actions'].pop('SaveActiveDocument');raw['field_readbacks'][0]['actual']=0
    with pytest.raises(ValueError):verify(case)


@pytest.mark.parametrize('key', ['save_readback_verified','production_qualified','native_units_verified','cutting_conditions_qualified'])
def test_contradictory_save_or_physical_qualification_is_not_admitted(case,key):
    case[0][key]=True
    with pytest.raises(ValueError):verify(case)
