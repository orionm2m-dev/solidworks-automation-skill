"""Pure geometry tests: no COM, CAD or runtime imports."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import math
import pytest
P = Path(__file__).resolve().parents[1] / 'scripts/sw_cam_taper_profile.py'
spec = importlib.util.spec_from_file_location('taper_profile_under_test', P)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def profile(edges):
    curves=[dict(index=i,read_complete=True,curve_type=0,start_native=[a[0],0.,a[1]],end_native=[b[0],0.,b[1]]) for i,(a,b) in enumerate(edges)]
    return dict(status='observed',declared_chain_count=1,chains=[dict(index=0,read_complete=True,declared_curve_count=len(curves),curves=curves)])
def candidate(full=True,radius=1.,height=.7):
    cone=[((0.,0.),(.3,0.)),((.3,0.),(radius,height))]
    rest=[((radius,height),(1.5,height)),((1.5,height),(1.5,40.))] if full else [((radius,height),(0.,height))]
    return dict(tool=profile(cone+rest),shank=profile([((1.5,height),(1.5,40.))]))
def run(p,stage='complete'):
    return m.validate_native_profiles(p,deepcopy(m.CONTRACT),stage=stage)

@pytest.mark.parametrize('full',[True,False])
def test_exact_cut_and_conservative_body(full):
    result=run(candidate(full))
    assert result['complete_qualified'] is True
    assert result['geometry']['cone_end_rz_mm']==[1.,.7]
    assert abs(result['geometry']['physical_flank_angle_deg']-45.)<1e-12
    assert not result['factory_profile'] and not result['production_qualified']
    assert not result['comparison_guard_is_manufacturing_tolerance']

def test_subdivisions_reverse_order_and_orientation():
    edges=[((0.,0.),(.15,0.)),((.15,0.),(.3,0.)),((.3,0.),(.65,.35)),((.65,.35),(1.,.7)),
           ((1.,.7),(1.5,.7)),((1.5,.7),(1.5,20.)),((1.5,20.),(1.5,40.)),((1.5,40.),(0.,40.))]
    p=dict(tool=profile([(b,a) for a,b in reversed(edges)]),shank=profile([((1.5,40.),(1.5,20.)),((1.5,20.),(1.5,.7))]))
    assert run(p)['complete_qualified']

@pytest.mark.parametrize('stage,radius,height',[
 ('after_end_dia',2.,5.),('after_taper_length',1.2,.7),('after_taper_angle',1.,.7)])
def test_partial_is_not_complete(stage,radius,height):
    result=run(candidate(radius=radius,height=height),stage)
    assert result['complete_qualified'] is False and result['profile_edge_counts'] is None

@pytest.mark.parametrize('stage,radius,height',[
 ('after_taper_length',1.,6.),('after_taper_angle',6.3,.7),
 ('after_taper_angle',1.001,.7),('after_taper_angle',1.,.71)])
def test_wrong_cone_semantics_stop(stage,radius,height):
    with pytest.raises(ValueError):run(candidate(radius=radius,height=height),stage)

@pytest.mark.parametrize('transform',['diameter','scale','rotate','negative','nan','bool'])
def test_no_fit_or_numeric_guessing(transform):
    p=candidate()
    for record in p.values():
        for curve in record['chains'][0]['curves']:
            for name in ('start_native','end_native'):
                xyz=curve[name]
                if transform=='diameter':xyz[0]*=2
                elif transform=='scale':curve[name]=[v*.001 for v in xyz]
                elif transform=='rotate':curve[name]=[0.,xyz[0],xyz[2]]
                elif transform=='negative':xyz[0]*=-1
                elif transform=='nan':xyz[0]=math.nan
                else:xyz[0]=True
    with pytest.raises(ValueError):run(p)

@pytest.mark.parametrize('edges',[
 [((1.5,.7),(1.5,20.)),((1.5,20.01),(1.5,40.))],
 [((1.5,.7),(1.5,40.)),((1.5,.7),(1.5,40.))],
 [((1.4,.7),(1.4,40.))],[((1.6,.7),(1.6,40.))],[((1.5,6.),(1.5,40.))]])
def test_bound_has_no_gap_duplicate_wrong_radius_or_wrong_start(edges):
    p=candidate();p['shank']=profile(edges)
    with pytest.raises(ValueError):run(p)

@pytest.mark.parametrize('edges',[
 [((0.,0.),(.3,0.)),((.3,0.),(.6,.3)),((.61,.31),(1.,.7))],
 [((0.,0.),(.3,0.)),((.3,0.),(1.,.7)),((.3,0.),(1.,.7))]])
def test_cone_gap_or_duplicate_rejected(edges):
    p=candidate();p['tool']=profile(edges)
    with pytest.raises(ValueError):run(p)

@pytest.mark.parametrize('fault',['missing_count','bool_count','partial','arc','wrong_key'])
def test_incomplete_native_observation_rejected(fault):
    p=candidate()
    if fault=='missing_count':del p['tool']['declared_chain_count']
    elif fault=='bool_count':p['tool']['declared_chain_count']=True
    elif fault=='partial':p['tool']['chains'][0]['read_complete']=False
    elif fault=='arc':p['tool']['chains'][0]['curves'][0]['curve_type']=1
    else:
        curve=p['tool']['chains'][0]['curves'][0];curve['curve_type_raw']=curve.pop('curve_type')
    with pytest.raises(ValueError):run(p)

def test_contract_cannot_loosen_guard_or_scale():
    c=deepcopy(m.CONTRACT);c['comparison_tolerance']=1.
    with pytest.raises(ValueError):m.validate_native_profiles(candidate(),c)
    c=deepcopy(m.CONTRACT);c['coordinates']['scale']=.001
    with pytest.raises(ValueError):m.validate_native_profiles(candidate(),c)

def test_zero_length_point_must_lie_on_expected_boundary():
    p=candidate();curves=p['tool']['chains'][0]['curves']
    curves.append(dict(index=len(curves),read_complete=True,curve_type=0,start_native=[1.5,0.,20.],end_native=[1.5,0.,20.]))
    p['tool']['chains'][0]['declared_curve_count']+=1
    assert run(p)['complete_qualified']
    curves[-1]['start_native']=curves[-1]['end_native']=[2.,0.,20.]
    with pytest.raises(ValueError):run(p)

