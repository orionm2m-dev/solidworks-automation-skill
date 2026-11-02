from copy import deepcopy
import ast,hashlib,importlib.util,json,os,sys
from pathlib import Path
import pytest
from cam_public_test_support import add_runtime, required_module, fixture_path
R=add_runtime()
m=required_module("sw_cam_mill_packet_projection")

@pytest.fixture
def golden():return json.loads(fixture_path('cam_mill_packet17_8_synthetic.json').read_text(encoding='utf-8'))


def test_seventeen_bindings_eight_groups_equal_synthetic_expected_snapshot(golden):
    result=m.project_packet(golden['packet'],golden['request'])
    assert m.reader.group.exact(result['snapshot'],golden['expected_snapshot'])
    assert len(result['snapshot']['binding']['operations'])==17
    assert [x['tool']['generic']['native_id']for x in result['snapshot']['parameters']]==[273]*4+[338]*4
    assert [x['nc']['feeds_compensation']['XYFeed']for x in result['snapshot']['parameters']]==[500.]*4+[1000.]*4
    d=result['diagnostic'];assert d['native_calls']==0 and d['typed_outputs_materialized']and not d['original_variant_tag_verified']
    assert not d['production_qualified']and not d['host_native_compatibility_qualified']
    assert sum(x['replayed_getters']for x in d['parameter_groups'])==896


def test_public_golden_is_labelled_synthetic_without_external_source(golden):
    assert golden['native_host_packet'] is False
    assert golden['scope']=='SYNTHETIC_FIXED_HOST_PACKET_TEST_FIXTURE'
    assert 'source_pin' not in golden
    assert golden['fixture_origin']=='public_synthetic_example'


def test_embedded_fixed_signatures_exactly_match_audited_typed_manifest():
    rows=json.loads(fixture_path('cam_mill_fixed_api_manifest.json').read_text(encoding='utf-8-sig'))
    want={'|'.join(r[k]for k in ('role','interface','member')):(r['group'],r['argument'],r['signature']['return_type'],tuple(p['type'].rstrip('&')for p in r['signature']['parameters']if p['is_out']))for r in rows}
    assert m._FIXED==want and len(want)==122


@pytest.mark.parametrize('fault',['wrong_schema','true_int','wrong_scope','wrong_engine','host_error','mutation','raw_complete_claim','variant_claim','wrong_pid','changed_doc','wrong_path','wrong_config','route_order','duplicate_route','setup_count','feature_key','extra_binding','extra_feature','extra_op','bool_op_id','target_order','duplicate_target','kind','target_tool','tool_binding','missing_group','extra_group','missing_field','extra_field','wrong_role_key','missing_shapes','extra_shapes','shape_type','shape_arity','out_arity','out_bool','out_nonfinite','void_scalar','planes_missing','plane_hr','plane_claim','starts_extra','start_metadata','starts_finish','shared_tool_drift'])
def test_packet_rejects_malformed_or_unbound_inputs(golden,fault):
    p,q=golden['packet'],golden['request'];row=p['parameters'][0]
    if fault=='wrong_schema':p['schema_version']=1
    elif fault=='true_int':p['schema_version']=True
    elif fault=='wrong_scope':p['scope']='other'
    elif fault=='wrong_engine':p['engine_version']='future'
    elif fault=='host_error':p['message']='failed'
    elif fault=='mutation':p['mutation_attempted']=True
    elif fault=='raw_complete_claim':p['full_snapshot_complete']=True
    elif fault=='variant_claim':p['original_variant_tag_verified']=True
    elif fault=='wrong_pid':p['process_id']+=1
    elif fault=='changed_doc':p['document_after']['needs_save']=True
    elif fault=='wrong_path':q['expected_document_path']='different'
    elif fault=='wrong_config':q['expected_sw_configuration']='different'
    elif fault=='route_order':q['expected_operation_ids'].reverse()
    elif fault=='duplicate_route':q['expected_operation_ids'][-1]=q['expected_operation_ids'][0]
    elif fault=='setup_count':p['binding']['operation_setups'][0]['operation_count']-=1
    elif fault=='feature_key':p['binding']['features']['80']['native_id']=81
    elif fault=='extra_binding':p['binding']['unknown']=True
    elif fault=='extra_feature':p['binding']['features']['80']['unknown']=True
    elif fault=='extra_op':p['binding']['operations'][0]['unknown']=True
    elif fault=='bool_op_id':p['binding']['operations'][0]['native_id']=True
    elif fault=='target_order':p['parameters'].reverse();q['parameter_targets'].reverse()
    elif fault=='duplicate_target':p['parameters'][-1]=deepcopy(p['parameters'][0]);q['parameter_targets'][-1]=deepcopy(q['parameter_targets'][0])
    elif fault=='kind':row['operation_type']=q['parameter_targets'][0]['operation_type']=2
    elif fault=='target_tool':row['tool_native_id']=q['parameter_targets'][0]['tool_native_id']=999
    elif fault=='tool_binding':row['generic_tool']['cut_diameter_native']=3
    elif fault=='missing_group':p['parameters'].pop()
    elif fault=='extra_group':p['parameters'].append(deepcopy(row))
    elif fault=='missing_field':row['values'].pop('operation|ICWMillOperation|GetMachiningDepth')
    elif fault=='extra_field':row['values']['operation|ICWOperation|GenerateToolpath']=True
    elif fault=='wrong_role_key':row['values']['lead_in|ICWRghMillOp|GetEntryExitType']=row['values'].pop('operation|ICWRghMillOp|GetEntryExitType')
    elif fault=='missing_shapes':row['value_shapes']={}
    elif fault=='extra_shapes':row['value_shapes']['operation|ICWMillOperation|GetMachiningDepth']={'kind':'double'}
    elif fault=='shape_type':row['value_shapes']['operation|ICWRghMillOp|GetEntryStartPtX']['items'][0]={'kind':'bool'}
    elif fault=='shape_arity':row['value_shapes']['operation|ICWRghMillOp|GetEntryStartPtX']['items'].pop()
    elif fault=='out_arity':row['values']['toolpath|ICWToolpathParam|GetToolpathParameters'].pop()
    elif fault=='out_bool':row['values']['operation|ICWRghMillOp|GetStartDepth'][0]=0
    elif fault=='out_nonfinite':row['values']['operation|ICWMillOperation|GetMachiningDepth']=float('nan')
    elif fault=='void_scalar':row['values']['operation|ICWRghMillOp|GetToolDiameterPercent']=1.0
    elif fault=='planes_missing':row['planes'].pop('GetClrPlanePrms')
    elif fault=='plane_hr':row['planes']['GetClrPlanePrms']['hresult']=1
    elif fault=='plane_claim':row['planes']['GetClrPlanePrms']['unit_binding_verified']=True
    elif fault=='starts_extra':row['startpoints']['unknown']=1
    elif fault=='start_metadata':row['startpoints']['metadata']['guid']='arbitrary'
    elif fault=='starts_finish':p['parameters'][1]['startpoints']=deepcopy(row['startpoints'])
    elif fault=='shared_tool_drift':p['parameters'][1]['values']['tool|ICWMillTool|OverallLen']+=1
    with pytest.raises(ValueError):m.project_packet(p,q)


def test_valid_actual_value_change_is_observed_never_normalized_to_golden(golden):
    p=golden['packet'];p['parameters'][7]['values']['nc|ICWNCParam2|XYFeed']=1234
    result=m.project_packet(p,golden['request'])
    assert result['snapshot']['parameters'][7]['nc']['feeds_compensation']['XYFeed']==1234.
    assert not m.reader.group.exact(result['snapshot'],golden['expected_snapshot'])


def test_clr_shape_preserves_integer_versus_double_without_claiming_variant():
    assert type(m.clr_variant(0,{'kind':'double'}))is float
    assert type(m.clr_variant(0,{'kind':'int'}))is int
    assert m.clr_variant([0,False],{'kind':'array','items':[{'kind':'double'},{'kind':'bool'}]})==(0.,False)


def test_foreign_handles_and_nonfixed_member_rejected(golden):
    a=m.PacketReplay(golden['packet']['parameters'][0]);b=m.PacketReplay(golden['packet']['parameters'][0])
    with pytest.raises(ValueError):a.read(b.operation,'IGetTool')
    with pytest.raises(ValueError):a.typed(a.operation,'IDispatchInvoke')
    with pytest.raises(ValueError):a.read(a.typed(a.operation,'ICWMillOperation'),'GenerateToolpath')
    with pytest.raises(ValueError):a.read(a.typed(a.operation,'ICWMillOperation'),'GetMachiningDepth',b.feature)


@pytest.mark.parametrize('text',['{"a":1,"a":2}','{"inner":{"a":1,"\\u0061":2}}','{"x":NaN}','{"x":Infinity}','{"x":-Infinity}',' '*(1048576+1)],ids=['duplicate','escaped_duplicate','nan','inf','negative_inf','oversized'])
def test_json_rejects_duplicate_nonfinite_and_oversized(text):
    with pytest.raises(ValueError):m.read_packet_json(text)


def test_full_json_projection_matches_native(golden):
    p=m.read_packet_json(json.dumps(golden['packet']))
    assert m.reader.group.exact(m.project_packet(p,golden['request'])['snapshot'],golden['expected_snapshot'])


def test_projector_has_no_file_or_native_invocation():
    tree=ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
    forbidden={'open','exec','eval','getattr','connect_solidworks','dispatch_once','QueryInterface','_member','_call_method'}
    calls=[n.func.id if isinstance(n.func,ast.Name)else n.func.attr if isinstance(n.func,ast.Attribute)else'' for n in ast.walk(tree)if isinstance(n,ast.Call)]
    assert not(forbidden&set(calls))


@pytest.mark.parametrize('text',['{"x":1e400}','['*34+'0'+']'*34],ids=['overflow','deep'])
def test_json_numeric_overflow_and_deep_tree_rejected(text):
    with pytest.raises(ValueError):m.read_packet_json(text)


def test_vendor_class_cannot_be_changed(golden):
    golden['request']['cam_addin_clsid']='{other}'
    with pytest.raises(ValueError):m.project_packet(golden['packet'],golden['request'])


@pytest.mark.parametrize('fault',['missing','list','owner','path_spelling','extra_key'])
def test_validated_request_echo_rejects_mismatch(golden,fault):
    p,q=golden['packet'],golden['request']
    if fault=='missing':p.pop('validated_request')
    elif fault=='list':p['validated_request']=[]
    elif fault=='owner':q['feature_setup_id']+=1
    elif fault=='path_spelling':q['expected_document_path']=q['expected_document_path'].swapcase()
    elif fault=='extra_key':p['validated_request']['unknown']=True
    with pytest.raises(ValueError,match='echo'):m.project_packet(p,q)


def test_target_cannot_escape_both_checked_feature_inventories(golden):
    p,q=golden['packet'],golden['request'];row=p['parameters'][0];oid=row['operation_native_id']
    row['feature_native_id']=q['parameter_targets'][0]['feature_native_id']=999999
    next(x for x in p['binding']['operations']if x['native_id']==oid)['linked_feature_ids']=[999999]
    p['validated_request']=deepcopy(q)
    with pytest.raises(ValueError,match='outside checked feature inventory'):m.project_packet(p,q)


def test_echo_is_parser_binding_not_native_qualification(golden):
    d=m.project_packet(golden['packet'],golden['request'])['diagnostic']
    assert d['validated_request_echo_matches']and d['request_echo_means_parser_acceptance_only']
    assert not d['host_native_compatibility_qualified']and not d['original_variant_tag_verified']
