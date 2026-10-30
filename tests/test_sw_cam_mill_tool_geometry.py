"""Synthetic callback tests; no platform paths, production fixtures or native calls."""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from scripts import sw_cam_mill_tool_geometry as g
from scripts import sw_cam_mill_inventory_geometry as chains


class Node:
    def __init__(self,*interfaces,**fields):self.interfaces=set(interfaces);self.fields=fields


def pos(x=0.,y=0.,z=0.):return Node('ICWPosition',GetCoordinates=[x,y,z])
def normal():return Node('ICWUnitVector',GetCoordinates=[0.,0.,1.])
def curve(kind):
    return Node('ICWCurve',*{0:[],1:['ICWArc'],2:['ICWCircle']}.get(kind,[]),
        GetTypeOfCurve=kind,GetStart=pos(1),GetEnd=pos(0,1),GetMid=pos(.7,.7),CenterPoint=pos(),
        IGetRadius=1.,GetRadius=1.,IGetNormal=normal(),IGetSense=-1,GetDirection=1)
def chain(curves,following=None,declared=1):
    return Node('ICWSegChain',IGetNumChains=declared,GetNumOfCurves=len(curves),
        GetCurveAtIndex=lambda index:curves[index._obj.value],IGetNextChain=following)


@pytest.fixture
def probe():
    holder=Node('ICWMillToolHolder',GetHolderId=42,GetHolderNumber='ER08',GetHolderShape='Basic',
        GetHolderType='Collet',GetHolderSpec='observed',GetName='holder',GetHolderTopDia=20.,GetHolderBottomDia=10.,
        GetHolderOverallLength=40.,GetHolderBottomLength=8.,GetProtrusion=27.,GetHolderProfile=chain([curve(0)]))
    tool=Node('ICWTool','ICWMillTool',MillToolType=1,MillToolSubType=0,EffCutlength=7,ShankDia=3.,
        OverallLen=39.,EndRadius=0.,NoOfFlutes=4,ShoulderLength=8.866,MillToolShankType=0,
        ShoulderDia=3.,ShankLength=30.,IGetMillToolHolder=holder,
        GetToolProfile=chain([curve(0),curve(1),curve(2)]),GetShankProfile=chain([curve(2)]))
    generic=dict(native_id=71,is_mill_tool=True,native_read_complete=True,tool_type_raw=1,
        cut_diameter_native=2.,protrusion_native=25.,units_verified=False,holder_geometry_verified=False)
    calls=[];qies=[];diag={}
    def read(obj,name,*args):
        calls.append((obj,name));value=obj.fields[name];return value(*args) if callable(value) else value
    def typed(obj,name):
        qies.append((obj,name))
        if name not in obj.interfaces:raise ValueError('unsupported QI '+name)
        return obj
    def run():return g.read_full_mill_tool(tool,generic=generic,read=read,typed=typed,diagnostic=diag)
    return SimpleNamespace(tool=tool,holder=holder,generic=generic,read=read,typed=typed,calls=calls,qies=qies,diag=diag,run=run)


def test_complete_observation_keeps_two_protrusions_raw_values_and_no_generic_repeats(probe):
    before=deepcopy(probe.generic);out=probe.run()
    assert probe.generic==before and out['tool_native_id']==71
    assert out['geometry_read_complete'] is True and out['profile_complete'] is True
    assert out['tool_protrusion_native']==25. and out['holder']['holder_protrusion_native']==27.
    assert type(out['mill_tool']['effective_cutting_length_native']) is int
    assert out['mill_tool']['flute_count_raw']==4 and out['holder']['holder_id_raw']==42
    assert out['profile_budget']==dict(curves=5,chains=3,islands=0)
    assert [c['curve_type'] for c in out['profiles']['tool']['chains'][0]['curves']]==[0,1,2]
    assert probe.qies.count((probe.tool,'ICWMillTool'))==1
    assert probe.qies.count((probe.holder,'ICWMillToolHolder'))==1
    assert not any(name=='ICWTool' for _,name in probe.qies)
    assert not any(name in ('IsMillTool','ToolType','CutDiameter','Protrusion') for _,name in probe.calls)
    assert not any(out[k] for k in ('units_verified','holder_geometry_verified','holder_clearance_verified','physical_tool_identity_verified','production_qualified','closed_loops_verified'))
    json.dumps(probe.diag,allow_nan=False)
    out['mill_tool']['overall_length_native']=999
    assert probe.diag['state']['mill_tool']['overall_length_native']==39.


def test_null_profiles_are_observed_absence_without_fabricated_geometry(probe):
    probe.tool.fields['GetToolProfile']=None;probe.tool.fields['GetShankProfile']=None;probe.holder.fields['GetHolderProfile']=None
    out=probe.run()
    assert out['geometry_read_complete'] is True and out['profile_complete'] is False
    assert all(p['status']=='observed_not_available' and p['chains']==[] and p['declared_chain_count'] is None for p in out['profiles'].values())


@pytest.mark.parametrize('member',['EffCutlength','ShankDia','OverallLen','EndRadius','ShoulderLength','ShoulderDia','ShankLength'])
@pytest.mark.parametrize('value',[True,float('nan'),float('inf'),-1.])
def test_tool_dimension_failures_keep_serializable_partial_diagnostics(probe,member,value):
    probe.tool.fields[member]=value
    with pytest.raises(ValueError):probe.run()
    assert probe.diag['capture_complete'] is False and probe.diag['state']['geometry_read_complete'] is False
    json.dumps(probe.diag,allow_nan=False)


@pytest.mark.parametrize('member',['GetHolderTopDia','GetHolderBottomDia','GetHolderOverallLength','GetHolderBottomLength','GetProtrusion'])
@pytest.mark.parametrize('value',[False,float('-inf'),-0.01])
def test_holder_dimension_failures(probe,member,value):
    probe.holder.fields[member]=value
    with pytest.raises(ValueError):probe.run()
    json.dumps(probe.diag,allow_nan=False)


@pytest.mark.parametrize('member',['MillToolType','MillToolSubType','MillToolShankType'])
@pytest.mark.parametrize('value',[True,1.,-2147483649,2147483648])
def test_raw_enum_types_and_int32_bounds(probe,member,value):
    probe.tool.fields[member]=value
    with pytest.raises(ValueError):probe.run()


@pytest.mark.parametrize('value',[True,1.,-1,1025])
def test_flute_count_is_strict_and_bounded(probe,value):
    probe.tool.fields['NoOfFlutes']=value
    with pytest.raises(ValueError):probe.run()


def test_zero_flutes_observed_but_not_qualified(probe):
    probe.tool.fields['NoOfFlutes']=0;out=probe.run()
    assert out['mill_tool']['flute_count_raw']==0 and out['production_qualified'] is False


@pytest.mark.parametrize('member,value',[('GetHolderId',True),('GetHolderId',2**31),('GetName',False),
    ('GetHolderSpec','x'*4097),('GetHolderType',Node('unsafe'))])
def test_holder_identity_exact_types(probe,member,value):
    probe.holder.fields[member]=value
    with pytest.raises(ValueError):probe.run()
    json.dumps(probe.diag,allow_nan=False)


@pytest.mark.parametrize('key,value',[('native_id',True),('is_mill_tool',1),('native_read_complete',False),
 ('tool_type_raw',1.),('cut_diameter_native',0),('protrusion_native',float('nan'))])
def test_invalid_generic_snapshot_stops_before_any_new_native_reads(probe,key,value):
    probe.generic[key]=value
    with pytest.raises(ValueError):probe.run()
    assert not probe.calls and not probe.qies


@pytest.mark.parametrize('target',['mill','holder','null_holder'])
def test_single_qi_failure_never_tries_fallback(probe,target):
    if target=='mill':probe.tool.interfaces.remove('ICWMillTool')
    elif target=='holder':probe.holder.interfaces.clear()
    else:probe.tool.fields['IGetMillToolHolder']=None
    with pytest.raises(ValueError):probe.run()
    assert probe.qies.count((probe.tool,'ICWMillTool'))==1
    assert probe.qies.count((probe.holder,'ICWMillToolHolder'))<=1
    assert not any(name.startswith('Set') for _,name in probe.calls)


@pytest.mark.parametrize('case',['unknown','early_end','extra','count_change','scalar_null'])
def test_profiles_fail_closed_with_partial_observations(probe,case):
    first=probe.tool.fields['GetToolProfile']
    if case=='unknown':probe.tool.fields['GetToolProfile']=chain([curve(99)])
    if case=='early_end':first.fields['IGetNumChains']=2
    if case=='extra':first.fields['IGetNextChain']=chain([curve(0)])
    if case=='count_change':
        values=iter([3,4]);first.fields['GetNumOfCurves']=lambda:next(values)
    if case=='scalar_null':probe.tool.fields['GetToolProfile']=False
    with pytest.raises(ValueError):probe.run()
    assert probe.diag['state']['geometry_read_complete'] is False
    json.dumps(probe.diag,allow_nan=False)


def test_profile_global_curve_budget_shared_across_all_three_profiles(probe,monkeypatch):
    monkeypatch.setattr(chains,'MAX_TOTAL_CURVES',3)
    with pytest.raises(ValueError,match='Global curve budget'):probe.run()
    assert probe.diag['state']['profile_budget']['curves']==3
    assert probe.diag['state']['profiles']['tool']['status']=='observed'
    assert probe.diag['state']['profiles']['shank']['status']=='reading'


def test_feature_and_island_decoder_extraction_preserves_existing_output(probe):
    island=Node('ICWIslandInfo',GetStartPosition=pos(2,3,4),GetDepth=2.,IGetTopSegChain=chain([curve(2)]),IGetBottomSegChain=None,IGetWallSegChain=None)
    collection=Node('ICWDispatchCollection',Count=1,Item=lambda index:island)
    feature=Node('ICWFeature','ICWMillFeature',VolumeType=2,SubType=0,Shape=0,Suppressed=False,
        FeatureName='feature',Axis=[0.,0.,-1.],Depth=4.1,GetBoundParams=[5.3,5.3,4.1],
        GetStartPosition=[0.,0.,10.9],IGetTopSegChain=chain([curve(0),curve(1),curve(2)]),
        IGetBottomSegChain=None,IGetWallSegChain=None,IGetIslandCount=1,IGetIslands=collection)
    diag={};budget=dict(curves=0,chains=0,islands=0)
    out=chains.read_mill_feature(feature,read=probe.read,typed=probe.typed,object_id=lambda _:66,diagnostic=diag,budget=budget)
    assert out['native_id']==66 and out['depth_native']==4.1 and out['islands']['declared_count']==1
    assert out['contours']['bottom']==dict(status='observed_not_available',declared_chain_count=None,chains=[])
    assert [c['curve_type'] for c in out['contours']['top']['chains'][0]['curves']]==[0,1,2]
    assert out['islands']['items'][0]['start_native']==[2.,3.,4.]
    assert budget==dict(curves=4,chains=2,islands=1) and diag['capture_complete'] is True


def test_feature_partial_contour_stays_attached_after_extraction(probe):
    owner=Node('owner',GetProfile=chain([curve(99)]));attached={};diag={'state':attached}
    with pytest.raises(ValueError):chains.read_segment_chains(owner,'GetProfile',read=probe.read,typed=probe.typed,diagnostic=diag,budget=dict(curves=0,chains=0,islands=0))
    assert diag['state'] is attached and attached['chains'][0]['curves'][0]['curve_type']==99
    assert attached['chains'][0]['read_complete'] is False
