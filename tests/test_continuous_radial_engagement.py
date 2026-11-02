"""Synthetic continuous-geometry regressions; no machining qualification."""
from fractions import Fraction as F
from pathlib import Path
import pytest
from cam_public_test_support import add_runtime, required_module
R=add_runtime()
m=required_module('continuous_radial_engagement')

def fast(**kw):
    return m.Budget(max_cells=kw.pop('max_cells',20000),max_intervals=kw.pop('max_intervals',64),
                    max_spatial_depth=kw.pop('max_spatial_depth',6),max_temporal_depth=kw.pop('max_temporal_depth',0),**kw)


def test_air_is_proved_for_model_only():
    r=m.analyze([m.Box(-1,2,1,3)],[m.Line((-1,0),(1,0))],budget=fast())
    assert r['mathematical_status']=='PROVED' and F(r['ae_upper_fraction'])==0
    assert not r['qualified_2d_bound_proved'] and not r['production_ready']


@pytest.mark.parametrize('sign',[1,-1])
def test_continuous_side_008(sign):
    a,b=sorted((F('0.392')*sign,F('0.4')*sign))
    r=m.analyze([m.Box(-10,a,10,b)],[m.Line((-1,0),(1,0))],stock_enclosure_qualified=True,budget=fast())
    assert r['qualified_2d_bound_proved']
    assert F(r['ae_upper_fraction'])==F('0.008')
    assert r['interval_checks']==1


def test_full_slot_is_not_accepted():
    r=m.analyze([m.Box(-2,-1,2,1)],[m.Line((-1,0),(1,0))],budget=fast(max_spatial_depth=1))
    assert r['mathematical_status']=='UNRESOLVED'
    assert F(r['ae_upper_fraction'])==F('0.8')


def test_material_on_both_sides_is_full_slot_bound():
    stock=[m.Box(-1,'0.392',1,'0.4'),m.Box(-1,'-0.4',1,'-0.392')]
    r=m.analyze(stock,[m.Line((-1,0),(1,0))],budget=fast(max_spatial_depth=0))
    assert F(r['ae_upper_fraction'])==F('0.8') and not r['supplied_model_bound_proved']


def test_unqualified_precision_never_becomes_qualified_stock():
    r=m.analyze([m.Box(-1,'0.392',1,'0.4')],[m.Line((-1,0),(1,0))],stock_enclosure_qualified=False,budget=fast())
    assert r['supplied_model_bound_proved'] and not r['qualified_2d_bound_proved']
    assert not r['physical_stock_certified_by_kernel']
    assert not r['external_authorities_validated'] and not r['stock_authority_checked_by_kernel']


def test_uncertain_stock_inflation_can_remove_acceptance():
    r=m.analyze([m.Box(-1,'0.38',1,'0.42')],[m.Line((-1,0),(1,0))],budget=fast(max_spatial_depth=1))
    assert not r['supplied_model_bound_proved'] and F(r['ae_upper_fraction'])>=F('.02')


@pytest.mark.parametrize('field',['max_cells','max_intervals'])
def test_exhausted_budget_never_returns_proof(field):
    r=m.analyze([], [m.Line((-1,0),(1,0))],budget=fast(**{field:0}))
    # No intervals is always unresolved; an empty stock union needs no cell checks.
    if field=='max_intervals': assert not r['supplied_model_bound_proved']
    else:
        r=m.analyze([m.Box(-1,'0.392',1,'0.4')],[m.Line((-1,0),(1,0))],budget=fast(max_cells=0))
        assert not r['supplied_model_bound_proved']


def test_later_pass_cannot_retroactively_erase_first_contact():
    stock=[m.Box(-1,'-0.4',1,'0.408')]
    paths=[m.Line((-2,0),(2,0)),m.Line((-2,'0.008'),(2,'0.008'))]
    r=m.analyze(stock,paths,budget=fast(max_spatial_depth=8,max_cells=50000))
    first=[x for x in r['intervals'] if x['motion_index']==0]
    second=[x for x in r['intervals'] if x['motion_index']==1]
    assert first[0]['credited_prior_intervals']==0 and not first[0]['proved']
    assert second[0]['credited_prior_intervals']==1 and all(x['proved'] for x in second)
    assert not r['supplied_model_bound_proved']


def test_reversed_order_changes_available_prefix_only():
    p=m.Line((-2,0),(2,0));stock=[m.Box(-1,'-0.4',1,'0.4')]
    r=m.analyze(stock,[p,p],budget=fast(max_spatial_depth=1))
    assert not r['intervals'][0]['proved'] and r['intervals'][1]['proved']
    assert r['intervals'][1]['ae_upper_fraction']=='0'


def test_arc_air_and_small_side_are_continuously_bounded():
    arc=m.Arc((0,0),100,(0,1),0,F('-0.0001'))
    air=m.analyze([], [arc],budget=fast())
    assert air['supplied_model_bound_proved']
    side=m.analyze([m.Box(-1,'100.392',1,'100.4')],[arc],budget=fast())
    assert side['supplied_model_bound_proved']
    assert F('.008') <= F(side['ae_upper_fraction']) < F('.016')


def test_arc_sagitta_has_outer_and_under_enclosures():
    arc=m.Arc((0,0),1,(1,0),0,1)
    outer,under=arc.capsules(F(0),F(1),F('.4'))
    assert outer.radius>F('.4') and 0<under.radius<F('.4')
    # These rational points are regression witnesses; mathematical enclosure is
    # the minor-arc Hausdorff theorem, not these finite samples.
    for k in range(101):
        c=arc.at(F(k,100))
        assert m.segment_point_distance2(outer.a,outer.b,c) <= (outer.radius-F('.4'))**2
    assert outer.radius-under.radius > 0


def test_large_arc_has_no_negative_under_capsule():
    a=m.Arc((0,0),100,(1,0),0,1)
    outer,under=a.capsules(F(0),F(1),F('.4'))
    assert under is None and outer.radius > F('.4')


def test_spatial_corner_containment_is_not_center_sampling():
    c=m.Capsule((-1,0),(1,0),F('.4'))
    assert not c.contains(m.Box('-.1','-.5','.1','.5'))
    assert c.contains(m.Box('-.1','-.3','.1','.3'))


def test_union_gap_not_credited_from_separate_corner_hits():
    left=m.Capsule((-1,0),(-1,0),F('.1'));right=m.Capsule((1,0),(1,0),F('.1'))
    box=m.Box(-1,0,1,0)
    assert not left.contains(box) and not right.contains(box)


@pytest.mark.parametrize('a,b,box,expected',[
    ((-2,0),(2,0),m.Box(-1,-1,1,1),0),
    ((-2,2),(2,2),m.Box(-1,-1,1,1),1),
    ((2,2),(3,3),m.Box(-1,-1,1,1),2),
    ((0,0),(0,0),m.Box(1,1,2,2),2),
])
def test_exact_segment_box_distance(a,b,box,expected):
    assert m.segment_box_distance2(m.point(a),m.point(b),box)==expected


@pytest.mark.parametrize('x',['0','2','1/3','10000000000/3','1/10000000000'])
def test_sqrt_bounds_are_outward(x):
    lo,hi=m.sqrt_bounds(F(x))
    assert lo*lo<=F(x)<=hi*hi


@pytest.mark.parametrize('make',[
    lambda:m.Line((0,0),(0,0)),
    lambda:m.Arc((0,0),1,(1,1),0,1),
    lambda:m.Arc((0,0),1,(1,0),-1,1),
    lambda:m.Arc((0,0),1,(1,0),0,0),
    lambda:m.Box(1,0,0,1),
    lambda:m.Line((0,0),(float('nan'),1)),
])
def test_invalid_geometry_fails_closed(make):
    with pytest.raises(ValueError): make()


def test_touching_centerline_is_conservative_full_slot():
    assert m.engagement_bound(F(0),F(".1"),F(".4"))==F(".8")
    assert m.engagement_bound(F("-.1"),F(0),F(".4"))==F(".8")


def test_arc_projection_contains_contact_witnesses():
    arc=m.Arc((0,0),2,(1,0),0,F(".2"));radius=F(".4")
    for k in range(21):
        t=F(k,20);c=arc.at(t);u=arc.unit(t)
        for sign in [-1,1]:
            x=m.add(c,m.mul(u,sign*radius));box=m.Box(x[0],x[1],x[0],x[1])
            lo,hi=arc.projection(box,F(0),F(1),radius)
            exact=m.dot(m.mul(u,-1),m.sub(x,c))
            assert lo<=exact<=hi
