"""Analytic conical bounds include intermediate line positions and arc loci."""
from copy import deepcopy
import importlib.util
import math
import os
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', ROOT))
sys.path.insert(0,str(RUNTIME))
from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes
spec=importlib.util.spec_from_file_location('chamfer_geometry_under_test',ROOT/'scripts/sw_cam_chamfer_cl_review.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.fixture
def context():
    return dict(z_offset_mm=26.,stock_floor_mm=12.6,stock_top_mm=26.,
        cavity_radius_mm=23.35,chamfer_bottom_mm=25.8,chamfer_top_radius_mm=23.55,
        tip_radius_mm=.3,cone_height_mm=.7,cone_slope=1.,noncutting_radius_mm=1.5,
        holder_min_tip_z_mm=19.95853166,target_axis_radius_mm=22.75,
        target_tip_world_z_mm=25.5,expected_cutter_raw=[2.,0.,.3,0.,45.,0.,40.],
        frame_verified=True,tool_reference_verified=True,
        arc_direction_semantics_verified=True,coincident_full_turn_semantics_verified=False)


def block(label='new',quarter=True):
    body=['CUTTER/2,0,.3,0,45,0,40','TLAXIS/0,0,1','RAPID/','GOTO/0,0,2',
        'GOTO/0,0,-.5','FEDRAT/MMPM,100','GOTO/22.75,0,-.5']
    if quarter:
        for end in ('0,22.75','-22.75,0','0,-22.75','22.75,0'):
            body+=['CIRCLE/0,0,-.5,0,0,1,22.75,COUNTERCLOCKWISE','GOTO/'+end+',-.5']
    else:body+=['CIRCLE/0,0,-.5,0,0,1,22.75,COUNTERCLOCKWISE','GOTO/22.75,0,-.5']
    body+=['GOTO/0,0,-.5','RAPID/','GOTO/0,0,2']
    return ['OPFEATSTART/'+label]+body+['OPFEATEND/'+label]


def parse(blocks):
    raw=('UNITS/MM\n'+'\n'.join(x for b in blocks for x in b)+'\nFINI\n').encode('ascii')
    result=parse_generic_cl_bytes(raw,encoding='ascii',expected_block_record_counts=[len(b)-2 for b in blocks])
    assert result['parse_complete'],result['invalid_commands']
    return result


def test_nominal_cone_reaches_both_chamfer_boundaries(context):
    c=context
    for z,wanted in ((25.8,23.35),(26.,23.55)):
        assert c['target_axis_radius_mm']+c['tip_radius_mm']+(z-c['target_tip_world_z_mm'])*c['cone_slope']==pytest.approx(wanted)
    r=m.review_block(parse([block()]),0,c)
    assert r['continuous_containment_proved'] and not r['issues']
    assert r['candidate_full_360'] and r['full_360_verified']
    assert r['minimum_tip_world_z_mm']==25.5
    assert r['noncutting_axial_gap_mm']==pytest.approx(.2)
    assert r['holder_axial_gap_mm']==pytest.approx(19.45853166)
    assert r['geometry_acceptance_complete'] is False and r['production_qualified'] is False
    assert 'incoming_inter_operation_path' in r['unverified']


def test_line_critical_stock_entry_catches_collision_not_present_at_endpoints(context):
    a,b=[26.,0.,27.],[20.,0.,24.]
    assert m.point_margin(math.hypot(*a[:2]),a[2],context,chamfer=True) is None
    assert m.point_margin(math.hypot(*b[:2]),b[2],context,chamfer=True)<0
    r=m.line_envelope(a,b,context,chamfer=True)
    assert not r['containment_proved'] and r['maximum_margin_mm']>0
    assert 0<r['worst']['parameter']<1


def test_line_continuous_bound_dominates_dense_independent_sampling(context):
    a,b=[26.,-3.,27.],[20.,2.,24.]
    r=m.line_envelope(a,b,context,chamfer=True)
    sampled=[]
    for i in range(1001):
        t=i/1000;p=[a[j]+t*(b[j]-a[j]) for j in range(3)]
        for k in range(101):
            z=context['stock_floor_mm']+(context['stock_top_mm']-context['stock_floor_mm'])*k/100
            if 0<=z-p[2]<=context['cone_height_mm']:
                allowed=context['cavity_radius_mm']+max(0,z-context['chamfer_bottom_mm'])
                sampled.append(math.hypot(*p[:2])+.3+z-p[2]-allowed)
    assert r['maximum_margin_mm']>=max(sampled)-1e-10


def test_wrong_tip_depth_is_detected_across_all_motions(context):
    p=parse([block()])
    for move in p['motions']:move['xyz'][2]-=.05
    for c in p['circle_records']:
        for key in ('center_raw','start_raw','endpoint_raw'):c[key][2]-=.05
    r=m.review_block(p,0,context)
    assert not r['continuous_containment_proved']
    assert any(x['kind']=='stock_containment_not_proved' for x in r['issues'])
    assert not r['candidate_full_360']


def test_rapid_does_not_assume_own_chamfer_has_already_been_removed(context):
    p=parse([block()])
    for move in p['motions']:
        if move['xyz']==[22.75,0.,-.5] and 'circle_record_line' not in move:move['mode']='rapid'
    r=m.review_block(p,0,context)
    assert any(x['mode']=='rapid' and not x['containment_proved'] for x in r['segments'])


def test_unknown_arc_direction_cannot_verify_coverage(context):
    context['arc_direction_semantics_verified']=False
    r=m.review_block(parse([block()]),0,context)
    assert r['continuous_containment_proved'] and r['candidate_full_360']
    assert not r['full_360_verified'] and 'arc_direction_serialization' in r['unverified']


def test_coincident_circle_is_not_implicitly_one_turn(context):
    r=m.review_block(parse([block(quarter=False)]),0,context)
    assert r['candidate_full_360'] and not r['full_360_verified']
    assert 'coincident_circle_turn_count' in r['unverified']
    assert r['continuous_containment_proved']


def test_missing_cut_quadrant_is_a_coverage_gap(context):
    p=parse([block()])
    p['circle_records']=p['circle_records'][:-1]
    r=m.review_block(p,0,context)
    assert not r['candidate_full_360'] and not r['full_360_verified']


@pytest.mark.parametrize('field',['frame_verified','tool_reference_verified'])
def test_missing_physical_reference_is_reported_not_implied(context,field):
    context[field]=False
    r=m.review_block(parse([block()]),0,context)
    assert r['nominal_math_only'] and not r['geometry_acceptance_complete']
    assert ('fixed_world_frame' if field=='frame_verified' else 'CUTTER_tip_reference') in r['unverified']


@pytest.mark.parametrize('change',['tilt','compensation','cutter','rotation','units','incomplete'])
def test_unsupported_cl_context_rejected(context,change):
    p=parse([block()])
    if change=='tilt':p['motions'][0]['axis_raw']=[1.,0.,0.]
    elif change=='compensation':p['motions'][0]['cutcom_state']['status']='active'
    elif change=='cutter':p['motions'][0]['cutter_raw'][0]=3.
    elif change=='rotation':p['motions'][0]['rotabl_records_before_motion']=[dict(angle_raw=90.)]
    elif change=='units':p['declared_units']=['INCH']
    else:p['parse_complete']=False
    with pytest.raises(ValueError):m.review_block(p,0,context)


def test_arc_bound_includes_radial_extremum_away_from_endpoints(context):
    p=parse([block()])
    c=p['circle_records'][0]
    c['center_raw']=[.2,0.,-.5]
    c['radius_raw']=22.75
    r=m.review_block(p,0,context)
    hit=next(x for x in r['segments'] if x['to_line']==c['endpoint_line'])
    assert hit['maximum_margin_mm']==pytest.approx(.2)
    assert not hit['containment_proved']


def test_block_matching_uses_unique_full_streams_not_labels():
    old=[block(str(i)) for i in range(3)]
    for i,b in enumerate(old):b[b.index('FEDRAT/MMPM,100')]='FEDRAT/MMPM,'+str(100+i)
    new=deepcopy(old)+[block('same-label')]
    for i in range(3):new[i][0]='OPFEATSTART/renamed'+str(i);new[i][-1]='OPFEATEND/renamed'+str(i)
    # Different new feed avoids accidental identity with a preserved full stream.
    new[-1][new[-1].index('FEDRAT/MMPM,100')]='FEDRAT/MMPM,200'
    r=m.isolate_added_block(parse(new),parse(old),prior_native_ids=[267,247,248],added_native_id=271)
    assert r['added_block']==3 and [x['native_id'] for x in r['unchanged']]==[267,247,248]


def test_duplicate_unchanged_stream_is_ambiguous():
    old=[block(str(i)) for i in range(3)]
    with pytest.raises(ValueError):
        m.isolate_added_block(parse(old+[block('new')]),parse(old),
            prior_native_ids=[267,247,248],added_native_id=271)


def test_rapid_tangent_contact_is_not_positive_clearance(context):
    p=parse([block()])
    moves=p['motions']
    # At Z25.5, largest immersed cone section has radius0.8.
    # R22.55+0.8=R23.35 touches the original wall exactly.
    moves[2]['xyz']=[22.55,0.,-.5]
    moves[2]['mode']='rapid'
    r=m.review_block(p,0,context)
    assert any(x['kind']=='positive_rapid_clearance_not_proved' for x in r['issues'])

def test_plunge_cutting_ability_is_separate_from_nominal_containment(context):
    p=parse([block()])
    p['motions'][1]['xyz']=[22.75,0.,20.]
    p['motions'][1]['mode']='rapid'
    p['motions'][2]['mode']='feed'
    r=m.review_block(p,0,context)
    assert r['nominal_geometric_containment_proved']
    assert not r['continuous_containment_proved']
    assert r['issues']==[dict(line=p['motions'][2]['line'],kind='axial_cutting_ability_unverified')]
