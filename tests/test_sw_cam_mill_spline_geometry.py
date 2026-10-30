"""Bounded callback-only spline observations; no native application or pointers."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast, importlib.util, json
import pytest
from test_sw_cam_mill_inventory_geometry import Node, position, curve, chain, feature, probe, g


def spline(facets=None, **changes):
    facets = [curve(0), curve(1)] if facets is None else facets
    return Node('ICWCurve', 'ICWSpline', **(dict(GetTypeOfCurve=3,
        GetNumOfFacet=len(facets), IGetNumControlPoints=4, GetDegree=3, GetOrder=4,
        IGetDimension=3, GetIsPeriodic=0, IGetIsRational=1,
        IGetStartParam=0., IGetEndParam=1., GetStart=position((1.,0.,0.)),
        GetEnd=position((0.,1.,0.)),
        GetFacetAtIndex=lambda index:facets[index._obj.value]) | changes))


def item(probe):
    return probe.diagnostic['state']['contours']['top']['chains'][0]['curves'][0]


def test_spline_typed_metadata_and_facets_keep_unknown_tolerance(probe):
    raw=spline();out=probe.run(feature(chain([raw,curve(2)])))
    observed=out['contours']['top']['chains'][0]['curves'][0]
    assert observed['curve_type']==3 and observed['read_complete'] is True
    assert observed['representation']=='native_spline_metadata_and_facets'
    assert observed['geometry_exact'] is False and observed['approximation_tolerance_native'] is None
    assert not observed['exact_control_points_read'] and not observed['exact_knots_read']
    assert observed['facets_status']=='observed_unknown_tolerance'
    assert [f['curve_type'] for f in observed['facets']]==[0,1]
    assert observed['declared_facet_count']==2 and observed['control_point_count_raw']==4
    assert observed['start_native']==[1.,0.,0.] and observed['end_native']==[0.,1.,0.]
    assert probe.budget==dict(curves=4,chains=1,islands=0)
    assert probe.qies.count((raw,'ICWSpline'))==1
    assert [a[0]._obj.value for _,n,a in probe.calls if n=='GetFacetAtIndex']==[0,1]
    assert not any(n in ('GetControlPointsData','IGetKnotsData','GetBCurveParams','IFacetCurve','IFacetCurveTol','SetNextCurve') for _,n,_ in probe.calls)
    assert out['physical_depth_verified'] is False and out['closed_loops_verified'] is False
    json.dumps(probe.diagnostic,allow_nan=False)


def test_no_native_facets_is_explicit_metadata_only_observation(probe):
    out=probe.run(feature(chain([spline([])])))
    observed=out['contours']['top']['chains'][0]['curves'][0]
    assert observed['facets']==[] and observed['facets_status']=='observed_no_facets'
    assert observed['geometry_exact'] is False and observed['read_complete'] is True
    assert not any(n=='GetFacetAtIndex' for _,n,_ in probe.calls)


def test_declared_int_flags_remain_raw_and_not_coerced_to_bool(probe):
    probe.run(feature(chain([spline(GetIsPeriodic=-1,IGetIsRational=-1)])))
    assert item(probe)['periodic_raw']==-1 and item(probe)['rational_raw']==-1
    assert type(item(probe)['periodic_raw']) is int


@pytest.mark.parametrize('field,value',[
    ('GetNumOfFacet',True),('GetNumOfFacet',1.),('GetNumOfFacet',-1),('GetNumOfFacet',257),
    ('IGetNumControlPoints',True),('IGetNumControlPoints',0),('IGetNumControlPoints',4097),
    ('GetDegree',False),('GetDegree',0),('GetDegree',33),
    ('GetOrder',1),('GetOrder',34),('GetOrder',4.),
    ('IGetDimension',0),('IGetDimension',5),('IGetDimension',True),
    ('GetIsPeriodic',True),('GetIsPeriodic',2**31),('IGetIsRational',False),('IGetIsRational',-2**31-1),
    ('IGetStartParam',float('nan')),('IGetStartParam',True),('IGetEndParam',float('inf'))])
def test_invalid_spline_metadata_stops_before_facets(probe,field,value):
    with pytest.raises(ValueError):probe.run(feature(chain([spline(**{field:value})])))
    assert item(probe)['read_complete'] is False and probe.diagnostic['capture_complete'] is False
    assert not any(n=='GetFacetAtIndex' for _,n,_ in probe.calls)
    json.dumps(probe.diagnostic,allow_nan=False)


def test_nonfinite_spline_endpoint_stops_before_facets(probe):
    with pytest.raises(ValueError):probe.run(feature(chain([spline(GetStart=position((0.,float('inf'),0.)))])))
    assert not any(n=='GetFacetAtIndex' for _,n,_ in probe.calls)


def test_missing_spline_interface_has_one_attempt_and_no_fallback(probe):
    raw=spline();raw.interfaces.remove('ICWSpline')
    with pytest.raises(ValueError,match='ICWSpline'):probe.run(feature(chain([raw])))
    assert probe.qies.count((raw,'ICWSpline'))==1
    assert not any(n=='GetNumOfFacet' for _,n,_ in probe.calls)


@pytest.mark.parametrize('facet',[None,3,4,99])
def test_unsupported_facet_shape_or_recursive_spline_is_not_flattened(probe,facet):
    raw=None if facet is None else spline([]) if facet==3 else curve(facet)
    with pytest.raises(ValueError):probe.run(feature(chain([spline([raw])])))
    assert item(probe)['read_complete'] is False and item(probe)['facets'][0]['read_complete'] is False
    assert len([1 for _,name in probe.qies if name=='ICWSpline'])==1
    json.dumps(probe.diagnostic,allow_nan=False)


@pytest.mark.parametrize('field',['GetNumOfFacet','IGetNumControlPoints'])
def test_count_drift_after_indexed_reads_is_partial_failure(probe,field):
    values=iter([2,3] if field=='GetNumOfFacet' else [4,5])
    raw=spline(**{field:lambda:next(values)})
    with pytest.raises(ValueError,match='count changed'):probe.run(feature(chain([raw])))
    assert len(item(probe)['facets'])==2 and all(x['read_complete'] for x in item(probe)['facets'])
    assert item(probe)['read_complete'] is False and probe.diagnostic['capture_complete'] is False


def test_global_budget_rejects_facets_before_indexed_reads(probe):
    probe.budget['curves']=8190
    with pytest.raises(ValueError,match='budget'):probe.run(feature(chain([spline()])))
    assert not any(n=='GetFacetAtIndex' for _,n,_ in probe.calls)
    assert probe.budget['curves']==8191


def test_facets_cannot_consume_reserved_budget_of_later_outer_curve(probe):
    probe.budget['curves']=8189
    with pytest.raises(ValueError,match='before next curve'):probe.run(feature(chain([spline(),curve(0)])))
    assert probe.budget['curves']==8192
    assert len([1 for _,n,_ in probe.calls if n=='GetCurveAtIndex'])==1
    assert item(probe)['read_complete'] is True


def test_budget_accumulates_spline_facets_across_features(probe):
    probe.run(feature(chain([spline()])))
    probe.run(feature(chain([spline([curve(2)])])))
    assert probe.budget['curves']==5 and probe.budget['chains']==2


def test_shared_segment_chain_reader_reuses_attached_partial_state(probe):
    holder=Node('Holder',Profile=chain([spline()]));out={};diagnostic={'state':out}
    def read(obj,name,*args):
        val=obj.fields[name];return val(*args) if callable(val) else val
    def typed(obj,name):
        assert name in obj.interfaces;return obj
    result=g.read_segment_chains(holder,'Profile',read=read,typed=typed,diagnostic=diagnostic,budget=probe.budget)
    assert result is out and diagnostic['capture_complete'] and result['chains'][0]['curves'][0]['geometry_exact'] is False



def test_verified_spline_IID_allowlist_only(monkeypatch):
    from scripts import sw_cam_comtypes as bridge
    expected='{6C37410C-1710-4F0A-BEFF-7BF83EFA7374}'
    assert bridge._INTERFACES['ICWSpline']==expected
    monkeypatch.setattr(bridge,'_load_type_library',lambda _:SimpleNamespace(ICWSpline=SimpleNamespace(_iid_=expected)))
    assert bridge._interface_class('ICWSpline','known.tlb')._iid_==expected
    monkeypatch.setattr(bridge,'_load_type_library',lambda _:SimpleNamespace(ICWSpline=SimpleNamespace(_iid_='{WRONG}')))
    with pytest.raises(ValueError,match='verified IID'):bridge._interface_class('ICWSpline','known.tlb')
