"""Synthetic saved-path adapter regressions; no physical stock authority."""
from fractions import Fraction as F
from pathlib import Path
import sys
import pytest
from cam_public_test_support import add_runtime, required_module
R=add_runtime()
sys.path.insert(0,str(R/'scripts'))
a=required_module('actual_cl_engagement_adapter')
k=a.k
assert Path(k.__file__).resolve()==(R/'scripts/continuous_radial_engagement.py').resolve()

def profile(loc=4):return dict(operation_native_id=344,tool_native_id=342,radius_mm='.4',cutting_length_mm=str(loc),overall_length_mm='45')
def motion(line,xyz,mode='feed',circle=False):
    m=dict(line=line,block=0,mode=mode,xyz=xyz,axis_raw=[0,0,1],cutter_raw=[.8,0,.4,0,0,0,45],cutcom_state={'status':'not_declared'},rotabl_records_before_motion=[])
    if circle:m['circle_record_line']=line-1
    return m

def parsed(rows):return dict(parse_complete=True,native_count_matches=True,declared_units=['MM'],motions=rows,circle_records=[])


def test_complete_line_gets_cylinder_common_to_entire_z_band():
    p=parsed([motion(1,[0,0,0],'rapid'),motion(2,[2,0,0])])
    e,skip=a.collect_events(p,{0:profile()},z_offset=0)
    caps,proof=a.guaranteed_prefix(e,before_line=3,z_band=[1,3],guard=0)
    assert not skip and proof['straight_capsules']==1
    assert any(c.a==(0,0)and c.b==(2,0)for c in caps)


def test_no_future_or_current_credit():
    e,_=a.collect_events(parsed([motion(1,[0,0,0],'rapid'),motion(2,[2,0,0])]),{0:profile()},z_offset=0)
    caps,proof=a.guaranteed_prefix(e,before_line=2,z_band=[1,3])
    assert caps==[] and proof['maximum_credited_line']is None


def test_unknown_arc_gives_endpoint_only():
    e,_=a.collect_events(parsed([motion(1,[0,0,0],'rapid'),motion(3,[2,0,0],circle=True)]),{0:profile()},z_offset=0)
    caps,proof=a.guaranteed_prefix(e,before_line=4,z_band=[1,3],guard=0)
    assert len(caps)==1 and caps[0].a==caps[0].b==(2,0)
    assert proof['straight_capsules']==0 and proof['unknown_arc_sweeps_credited']is False


def test_rapid_has_no_credit():
    e,_=a.collect_events(parsed([motion(1,[0,0,0],'rapid'),motion(2,[2,0,0],'rapid')]),{0:profile()},z_offset=0)
    assert not e


def test_short_LOC_cannot_clear_taller_band():
    e,_=a.collect_events(parsed([motion(1,[0,0,0],'rapid'),motion(2,[2,0,0])]),{0:profile(3)},z_offset=0)
    caps,_=a.guaranteed_prefix(e,before_line=3,z_band=[0,F('3.4')],guard=0)
    assert not caps


def test_ramp_clips_exact_common_Z_band():
    e,_=a.collect_events(parsed([motion(1,[0,0,0],'rapid'),motion(2,[4,0,4])]),{0:profile()},z_offset=0)
    caps,_=a.guaranteed_prefix(e,before_line=3,z_band=[2,5],guard=0)
    assert len(caps)==1 and caps[0].a==(1,0)and caps[0].b==(2,0)


def test_erosion_shrinks_radial_and_axial_credit():
    e,_=a.collect_events(parsed([motion(1,[0,0,0],'rapid'),motion(2,[2,0,0])]),{0:profile()},z_offset=0)
    assert not a.guaranteed_prefix(e,before_line=3,z_band=[0,4],guard='.001')[0]
    caps,_=a.guaranteed_prefix(e,before_line=3,z_band=[1,3],guard='.001')
    assert all(c.radius==F('.399')for c in caps)


def test_unknown_profile_block_is_not_guessed():
    e,skip=a.collect_events(parsed([motion(1,[0,0,0],'rapid'),motion(2,[2,0,0])]),{},z_offset=0)
    assert not e and skip==[0]


@pytest.mark.parametrize('field,value',[('axis_raw',[0,0,-1]),('cutter_raw',[2,0,1,0,0,0,45]),('cutcom_state',{'status':'enabled'})])
def test_incompatible_CL_rejected(field,value):
    m=motion(2,[2,0,0]);m[field]=value
    with pytest.raises(ValueError):a.collect_events(parsed([motion(1,[0,0,0],'rapid'),m]),{0:profile()},z_offset=0)


def test_fully_solid_box_can_only_be_cleared_by_guaranteed_prefix():
    line=k.Line((-1,0),(1,0))
    cut=[k.Capsule((-2,0),(2,0),1)]
    r=a.checked_interval(line,cut,max_cells=100)
    assert r['nominal_model_proved']and r['ae_upper_fraction']=='0'
    no=a.checked_interval(line,[],max_cells=100)
    assert not no['nominal_model_proved']


def test_full_circle_does_not_credit_its_own_quadrants():
    cut=[k.Capsule((0,0),(0,0),2)];before=list(cut)
    r=a.review_full_circle((0,0),'.2',cut,max_cells=100)
    assert r['nominal_model_proved']and r['ae_upper_fraction']=='0'
    assert cut==before and not r['full_circle_removal_credited']


def test_direct_kernel_adapter_enforces_budget_and_threshold():
    line=k.Line((0,0),(1,0))
    for kw in [{'radius':0},{'limit':1},{'max_cells':-1}]:
        with pytest.raises(ValueError):a.checked_interval(line,[],**kw)


def test_actual_adjacency_and_vertical_entry_reject_silent_guesses():
    rows=[motion(1,[0,0,0],'rapid'),motion(2,[0,0,-1])];p=parsed(rows)
    r=a.query_actual_motion(p,rows[1],rows[0],[],target_profile=profile(),motion_index=1,z_offset=0)
    assert r['status']=='UNRESOLVED'and 'axial' in r['reason']
    with pytest.raises(ValueError):a.query_actual_motion(p,rows[1],motion(1,[100,0,0],'rapid'),[],target_profile=profile(),motion_index=1,z_offset=0)


def test_cached_geometry_filters_future_capsules_before_credit():
    rows=[motion(1,[0,0,0],'rapid'),motion(2,[2,0,0]),motion(3,[4,0,0])]
    events,_=a.collect_events(parsed(rows),{0:profile()},z_offset=0)
    index=a.PrefixIndex(events,guard=0);window=k.Box(-1,-1,5,1)
    first,proof=index.query(before_line=2,z_band=[1,3],window=window)
    assert first==[] and proof['maximum_credited_line']is None
    second,proof=index.query(before_line=3,z_band=[1,3],window=window)
    assert second and proof['maximum_credited_line']==2
    assert all(c.b[0]<=2 for c in second)


def test_cached_duplicate_uses_earliest_actual_completion():
    rows=[motion(1,[0,0,0],'rapid'),motion(2,[2,0,0]),motion(3,[0,0,0]),motion(4,[2,0,0])]
    events,_=a.collect_events(parsed(rows),{0:profile()},z_offset=0)
    index=a.PrefixIndex(events,guard=0);window=k.Box(-1,-1,3,1)
    caps,proof=index.query(before_line=3,z_band=[1,3],window=window)
    assert any(c.a==(0,0)and c.b==(2,0)for c in caps)
    assert max(v['line']for v in proof['sources'])==2


def prefix_fixture():
    import review_actual18_engagement_chunk as r
    prior={'parse_complete':True,'native_count_matches':True,'operation_blocks':list(range(14))}
    current={'parse_complete':True,'native_count_matches':True,'operation_blocks':list(range(18))}
    rows=[{'operation_native_id':i+1,'toolpath_record_counts':[5]}for i in range(18)]
    targets=[{'key':key,'operation_native_id':i+15,'feature_native_id':339+i//2,'operation_type':i%2}
        for i,key in enumerate(['left_rough','left_finish','right_rough','right_finish'])]
    return r,prior,current,rows[:14],rows,targets


def test_actual_prefix_uses_complete_signature_and_actual_roles():
    r,prior,current,old,new,targets=prefix_fixture()
    got=r.bind_prefix(prior,current,old,new,targets,lambda p,i:p['operation_blocks'][i])
    assert got['protected14_full_streams_unchanged']and not got['actual_new_feature_geometry_mapping_verified']


@pytest.mark.parametrize('fault',['old_change','count_change','id_overlap','role_change','feature_change','new_order','partial_parse','duplicate_signature'])
def test_actual_prefix_rejects_ambiguous_or_changed_evidence(fault):
    import copy
    r,prior,current,old,new,targets=prefix_fixture();new=copy.deepcopy(new)
    if fault=='old_change':current['operation_blocks'][0]=100
    if fault=='count_change':new[0]['toolpath_record_counts']=[6]
    if fault=='id_overlap':new[17]['operation_native_id']=1
    if fault=='role_change':targets[0]['key']='right_rough'
    if fault=='feature_change':targets[1]['feature_native_id']=999
    if fault=='new_order':new[14],new[15]=new[15],new[14]
    if fault=='partial_parse':current['parse_complete']=False
    if fault=='duplicate_signature':current['operation_blocks'][17]=0
    with pytest.raises(ValueError):r.bind_prefix(prior,current,old,new,targets,lambda p,i:p['operation_blocks'][i])


def test_flat_cutter_taper_change_is_not_ignored():
    m=motion(2,[2,0,0]);m['cutter_raw'][5]=45
    with pytest.raises(ValueError):a.collect_events(parsed([motion(1,[0,0,0],'rapid'),m]),{0:profile()},z_offset=0)


def test_height_band_budget_is_explicit():
    index=a.PrefixIndex([])
    index.cache={tuple(map(F,(i,i+1))):[]for i in range(128)}
    with pytest.raises(a.BandBudgetExhausted):index.query(before_line=1,z_band=[1000,1001],window=k.Box(0,0,1,1))
