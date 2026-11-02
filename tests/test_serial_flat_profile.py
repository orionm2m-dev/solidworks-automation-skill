"""Portable offline regressions for conservative flat-tool silhouettes."""
from pathlib import Path
from copy import deepcopy
import os,sys
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module
ROOT=add_runtime()
g=required_module("sw_cam_serial_flat_profile")
TARGET=dict(CutDiameter=.8,EffCutlength=4.,ShankDia=4.,OverallLen=45.,Protrusion=19.,ShoulderDia=.8,ShoulderLength=4.,ShankLength=4.,NoOfFlutes=2,MillToolShankType=0)
def profile(target=None,shank=False):
 t=target or TARGET
 curves=[dict(read_complete=True,curve_type=0,start_native=[a[0],0.,a[1]],end_native=[b[0],0.,b[1]])for a,b in g.segments(t,shank_only=shank)]
 return dict(status='observed',declared_chain_count=1,chains=[dict(read_complete=True,declared_curve_count=len(curves),curves=curves)])
@pytest.mark.parametrize('shank',[False,True])
def test_complete_native_unequal_step_profile(shank):
 assert g.verify_profile(profile(shank=shank),TARGET,shank_only=shank)['status']=='PASS'
@pytest.mark.parametrize('diameter,shank',[(.8,False),(.8,True),(2.,False),(2.,True)])
def test_generic_equal_diameter_and_reversed_split_lines(diameter,shank):
 t=dict(TARGET,CutDiameter=diameter,ShoulderDia=diameter,ShankDia=diameter)
 p=profile(t,shank);old=p['chains'][0]['curves'];out=[]
 for c in reversed(old):
  a,b=c['end_native'],c['start_native'];mid=[(x+y)/2 for x,y in zip(a,b)]
  out.extend([dict(c,start_native=a,end_native=mid),dict(c,start_native=mid,end_native=b)])
 p['chains'][0].update(curves=out,declared_curve_count=len(out))
 assert g.verify_profile(p,t,shank_only=shank)['status']=='PASS'
@pytest.mark.parametrize('damage',['short_cut','no_step','step_gap','long_body','wrong_radius','unexpected_plane','arc','bad_y','negative_radius','incomplete','false_count','nan','bool_coordinate'])
def test_actual_full_profile_rejects_wrong_or_missing_geometry(damage):
 p=profile();ch=p['chains'][0];c=ch['curves']
 if damage=='short_cut':c[0]['end_native'][2]=3.99
 elif damage=='no_step':c.pop(1);ch['declared_curve_count']-=1
 elif damage=='step_gap':c[1]['start_native'][0]=.401
 elif damage=='long_body':c[-1]['end_native'][2]=45.1
 elif damage=='wrong_radius':c[-1]['end_native'][0]=2.01
 elif damage=='unexpected_plane':c.append(dict(c[1],start_native=[.4,0.,2.],end_native=[.5,0.,2.]));ch['declared_curve_count']+=1
 elif damage=='arc':c[1]['curve_type']=1
 elif damage=='bad_y':c[0]['start_native'][1]=.0001
 elif damage=='negative_radius':c[0]['start_native'][0]=-.4
 elif damage=='incomplete':ch['read_complete']=False
 elif damage=='false_count':ch['declared_curve_count']+=1
 elif damage=='nan':c[0]['start_native'][0]=float('nan')
 elif damage=='bool_coordinate':c[0]['start_native'][0]=True
 with pytest.raises(ValueError):g.verify_profile(p,TARGET)
@pytest.mark.parametrize('field,value',[('MillToolShankType',1),('NoOfFlutes',True),('NoOfFlutes',33),('EffCutlength',19.),('ShankLength',4.1),('ShoulderDia',1.),('CutDiameter',5.),('Protrusion',45.),('OverallLen',float('inf'))])
def test_invalid_or_unqualified_target_rejected(field,value):
 with pytest.raises(ValueError):g.validate_target(dict(TARGET,**{field:value}))
def test_split_caps_do_not_hide_missing_step():
 p=profile();c=p['chains'][0]['curves'];c[1]['end_native'][0]=1.5
 c.append(dict(c[1],start_native=[1.6,0.,4.],end_native=[2.,0.,4.]))
 p['chains'][0]['declared_curve_count']+=1
 with pytest.raises(ValueError,match='Gap'):g.verify_profile(p,TARGET)
def test_valid_radial_cap_can_cover_required_step():
 p=profile();p['chains'][0]['curves'][1]['start_native'][0]=0.
 assert g.verify_profile(p,TARGET)['status']=='PASS'

def candidate():
 full=dict(geometry_read_complete=True,profile_complete=True,tool_native_id=500,tool_type_raw=1,
  cut_diameter_native=.8,tool_protrusion_native=19.,mill_tool=dict(type_raw=1,subtype_raw=3,end_radius_native=0.))
 for name,section,key in g.FIELDS:
  (full[section]if section else full)[key]=TARGET[name]
 holder=dict(file_path='C:/approved/holder.mh',pins=[],records=[dict(kind='line',start_rz=[4.,0.],end_rz=[4.,1.])])
 hp=dict(status='observed',declared_chain_count=1,chains=[dict(read_complete=True,declared_curve_count=1,
  curves=[dict(read_complete=True,curve_type=0,start_native=[4.,0.,19.],end_native=[4.,0.,20.])])])
 full.update(holder=dict(holder_protrusion_native=19.,name=holder['file_path']),
  profiles=dict(tool=profile(),shank=profile(shank=True),holder=hp))
 identity=dict(ToolIdentifier='fixture',ToolVendor='vendor',ToolDescription='conservative step')
 return dict(full_tool=full,identity=identity),dict(target=deepcopy(TARGET),identity=identity),holder

def test_actual_complete_candidate_schema():
 observed,recipe,holder=candidate();r=g.verify_candidate(observed,recipe,holder)
 assert r['profile_verified']is True and r['production_qualified']is False

@pytest.mark.parametrize('damage',['identity','tooltype','subtype','endradius','cutlength','holderpath','holderplacement','profile_complete'])
def test_full_candidate_rejects_native_binding_or_profile_change(damage):
 observed,recipe,holder=candidate();full=observed['full_tool']
 if damage=='identity':observed['identity']=dict(observed['identity'],ToolIdentifier='wrong')
 elif damage=='tooltype':full['tool_type_raw']=3
 elif damage=='subtype':full['mill_tool']['subtype_raw']=2
 elif damage=='endradius':full['mill_tool']['end_radius_native']=.01
 elif damage=='cutlength':full['mill_tool']['effective_cutting_length_native']=3.4
 elif damage=='holderpath':full['holder']['name']='C:/different.mh'
 elif damage=='holderplacement':full['profiles']['holder']['chains'][0]['curves'][0]['end_native'][2]=20.01
 elif damage=='profile_complete':full['profile_complete']=False
 with pytest.raises(ValueError):g.verify_candidate(observed,recipe,holder)
