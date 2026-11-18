"""Portable pure boundary tests: no CAD, receipt files or runtime writes."""
from copy import deepcopy
import pytest
from scripts import sw_cam_current_pocket_generation_delta as d
from scripts.sw_cam_generic_cl_reader_bounded import parse_generic_cl_bytes


def snapshot(ids=(31,48),source='a'*64):
    rows=[];params=[]
    for i,(oid,kind) in enumerate(zip(ids,(0,1))):
        tool=dict(native_id=81+i,is_mill_tool=True,cut_diameter_native=8.0)
        rows.append(dict(native_id=oid,mill_operation_type=kind,toolpath_generated=False,suppressed=False,
            toolpath_record_counts=[],linked_feature_ids=[53],all_linked_features_observed=True,
            setup_native_id=19,setup_index=0,operation_index=i,assigned_tool=deepcopy(tool)))
        params.append(dict(operation_native_id=oid,operation_type=kind,feature_native_id=53,read_complete=True,
            tool=dict(generic=deepcopy(tool),holder=dict(length=50.0)),levels=dict(origin=[0.0,0.0,26.0]),
            nc=dict(feed=100.0),rough=dict(entry_type=4,pitch=0.1),diagnostic=dict(complete=True,raw=[False,0.3])))
    inv=dict(capture_complete=True,operation_count=2,operation_counts=[2],operation_setup_count=1,
        generated_operation_count=0,total_record_count=0,unique_tool_count=2,operations=rows,
        operation_setups=[dict(native_id=19,operation_count=2,origin=[0.0,0.0,26.0])],
        feature_setups=[dict(native_id=7,origin=[0.0,0.0,0.0])],selected_feature=dict(native_id=53,island_count=4),
        document=dict(path='C:/cad/qualification.SLDPRT',type=1,needs_save=False),saved_file_sha256=source,
        definition_authority=dict(island_geometry_verified=False),CAD=dict(tree=['Imported','Sketch'],mass=[1.0,2.0]))
    return dict(inventory=inv,parameters=params)


def generated(before=None,count=19,dirty=False):
    x=deepcopy(snapshot() if before is None else before);r=x['inventory']['operations'][0]
    r.update(toolpath_generated=True,toolpath_record_counts=[count]);x['inventory'].update(generated_operation_count=1,total_record_count=count)
    x['inventory']['document']['needs_save']=dirty;return x


def native():return dict(attempted=True,returned=True,native_return_type='int',native_return_value=0,native_dispatch_pending=False)


def parsed(label='Unrelated_label',count=5):
    lines=['UNITS/MM',f'OPFEATSTART/{label}','CUTTER/8,0,0,0,0,0,40','TLAXIS/0,0,1','RAPID/']
    lines+=['RAPID/']*(count-4)
    lines+=['GOTO/0,0,10',f'OPFEATEND/{label}','FINI']
    return parse_generic_cl_bytes(('\n'.join(lines)+'\n').encode('ascii'),expected_block_record_counts=[count])


def test_flatten_keeps_all_fields_and_inputs():
    a=snapshot();saved=deepcopy(a);f=d.flatten(a)
    assert f['operation_parameters']==a['parameters'] and f['parameter_capture_complete']is True
    assert {k:v for k,v in f.items()if k not in ('operation_parameters','parameter_capture_complete')}==a['inventory']
    f['operation_parameters'][0]['nc']['feed']=0.0
    assert a==saved


@pytest.mark.parametrize('ids',[(31,48),(790,902)])
@pytest.mark.parametrize('dirty',[False,True])
def test_generic_single_first_path_and_false_dirty_are_valid(ids,dirty):
    a=snapshot(ids);b=generated(a,dirty=dirty);old=deepcopy((a,b))
    p=d.verify_generation(a,b,ids[0],native())
    assert p['selected_record_count']==19 and p['protected_operation_native_ids']==[ids[1]]
    assert p['after_aggregates']==dict(generated_operation_count=1,total_record_count=19)
    assert p['generated_current_context_readable_by_old_loader']is False and p['production_qualified']is False
    assert (a,b)==old


@pytest.mark.parametrize('key,value',[('attempted',False),('returned',False),('native_return_type','bool'),('native_return_value',False),('native_return_value',True),('native_return_value',1),('native_return_value',0.0),('native_dispatch_pending',True)])
def test_actual_native_return_is_required(key,value):
    n=native();n[key]=value
    with pytest.raises(ValueError):d.verify_generation(snapshot(),generated(),31,n)


@pytest.mark.parametrize('selected',[True,31.0,48,999,-1])
def test_only_exact_selected_rough(selected):
    with pytest.raises(ValueError):d.verify_generation(snapshot(),generated(),selected,native())


@pytest.mark.parametrize('key,value',[('generated_operation_count',False),('generated_operation_count',0),('generated_operation_count',2),('total_record_count',18),('total_record_count',19.0)])
def test_aggregate_values_cannot_be_masked(key,value):
    x=generated();x['inventory'][key]=value
    with pytest.raises(ValueError):d.verify_generation(snapshot(),x,31,native())


@pytest.mark.parametrize('counts',[[0],[True],[-1],[1,2],[100001],[]])
def test_native_counts_must_be_one_positive_integer(counts):
    x=generated();x['inventory']['operations'][0]['toolpath_record_counts']=counts
    with pytest.raises(ValueError):d.verify_generation(snapshot(),x,31,native())


def test_preexisting_path_is_not_first_path():
    a=generated();b=deepcopy(a)
    with pytest.raises(ValueError):d.verify_generation(a,b,31,native())


def test_contour_generation_is_rejected_even_with_consistent_aggregates():
    b=generated();b['inventory']['operations'][1].update(toolpath_generated=True,toolpath_record_counts=[3]);b['inventory'].update(generated_operation_count=2,total_record_count=22)
    with pytest.raises(ValueError):d.verify_generation(snapshot(),b,31,native())


@pytest.mark.parametrize('change',[
 lambda x:x['parameters'][1]['nc'].update(feed=101.0),
 lambda x:x['parameters'][0]['rough'].update(pitch=0.2),
 lambda x:x['parameters'][0]['diagnostic'].update(raw=[True,0.3]),
 lambda x:x['inventory']['feature_setups'][0].update(origin=[0.0,0.0,26.0]),
 lambda x:x['inventory']['operation_setups'][0].update(origin=[0.0,0.0,0.0]),
 lambda x:x['inventory']['CAD']['tree'].append('Unexpected'),
 lambda x:x['inventory']['CAD'].update(mass=[1.0,2.001]),
 lambda x:x['inventory']['selected_feature'].update(island_count=3),
 lambda x:x['inventory'].update(saved_file_sha256='b'*64),
 lambda x:x['inventory']['document'].update(path='C:/cad/other.SLDPRT'),
 lambda x:x['inventory']['operations'][1].update(suppressed=True),
 lambda x:x['inventory']['operations'].reverse(),
 lambda x:x['parameters'].reverse(),
 lambda x:x['inventory']['operations'][0]['assigned_tool'].update(native_id=99),
 lambda x:x['parameters'][0]['tool']['holder'].update(length=50.01),
 lambda x:x['inventory']['document'].update(needs_save=1),
])
def test_all_nonpath_state_remains_protected(change):
    b=generated();change(b)
    with pytest.raises(ValueError):d.verify_generation(snapshot(),b,31,native())


@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf'),(1,2)])
def test_nonjson_or_nonfinite_snapshot_rejected(value):
    a=snapshot();a['parameters'][0]['extra']=value
    with pytest.raises(ValueError):d.flatten(a)


def test_flatten_rejects_parameter_shadow_or_incomplete_row():
    a=snapshot();a['inventory']['operation_parameters']=[]
    with pytest.raises(ValueError):d.flatten(a)
    a=snapshot();a['parameters'][1]['read_complete']=False
    with pytest.raises(ValueError):d.flatten(a)


def test_first_cl_uses_observed_sole_inventory_not_label():
    p=parsed(label='MISLEADING_NATIVE_ID_999')
    result=d.verify_first_cl(p,31,5)
    assert result['expected_operation_native_id']==31 and result['native_id_inferred_from_label']is False
    assert result['caller_file_and_inventory_binding_required']is True
    assert result['preCL_required']is False and result['world_geometry_verified']is False


@pytest.mark.parametrize('key,value',[
 ('parse_complete',False),('native_count_matches',False),('declared_units',['INCH']),
 ('expected_block_record_counts',[6]),('expected_native_record_counts',[True]),('block_command_counts',[6]),
 ('unknown_commands',[{'name':'UNKNOWN'}]),('invalid_commands',[{'error':'bad'}]),('structure_issues',[{}]),
 ('operation_blocks',[]),('motions',[]),('motion_count',0),('sha256','x'*64),('bytes',0),
 ('units_scale_verified',True),('coordinate_frame_verified',True),('production_qualified',True),
 ('operation_native_ids_inferred_from_labels',True),('full_turn_semantics_qualified',True)])
def test_first_cl_is_complete_bounded_and_unqualified(key,value):
    p=parsed();p[key]=value
    with pytest.raises(ValueError):d.verify_first_cl(p,31,5)


def test_first_cl_rejects_extra_blocks_and_wrong_motion_owner():
    p=parsed();p['operation_blocks'].append(deepcopy(p['operation_blocks'][0]))
    with pytest.raises(ValueError):d.verify_first_cl(p,31,5)
    p=parsed();p['motions'][0]['block']=1
    with pytest.raises(ValueError):d.verify_first_cl(p,31,5)


@pytest.mark.parametrize('oid,count',[(True,5),(31,True),(31,0),(31,100001),(31,6)])
def test_first_cl_strict_request(oid,count):
    with pytest.raises(ValueError):d.verify_first_cl(parsed(),oid,count)
