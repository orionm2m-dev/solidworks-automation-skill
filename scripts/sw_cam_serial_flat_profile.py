"""Bounded configurable straight-shank flat-tool profile contract.

The noncutting step is an explicitly declared conservative envelope. It is
not an assertion that a purchased cutter has a square physical shoulder.
"""
from pathlib import Path
import math
from scripts.sw_cam_shared_cutter_geometry import FIELDS,INTEGER_FIELDS,values,close,number,TOL,_point
from scripts.sw_cam_shared_holder_geometry import verify_holder_profile
from scripts.sw_cam_rough_firstcut import require

KEYS={row[0]for row in FIELDS}
BASIS='conservative_step_shank_requires_native_readback'

def validate_target(target):
 require(type(target)is dict and set(target)==KEYS,'Exact ten-field flat cutter recipe required')
 for key,value in target.items():
  if key in INTEGER_FIELDS:require(type(value)is int,'Strict integral tool classification required')
  else:require(number(value)>0,'Positive finite tool dimension required')
 d,e,ds,l,p=(number(target[k])for k in ['CutDiameter','EffCutlength','ShankDia','OverallLen','Protrusion'])
 require(target['MillToolShankType']==0 and 1<=target['NoOfFlutes']<=32,'Bounded straight-shank flat tool only')
 require(0<d<=ds and 0<e<p<l and close(target['ShoulderDia'],d)
  and close(target['ShoulderLength'],e) and close(target['ShankLength'],e),
  'Coherent step at the actual cutting-length boundary required')
 return dict(target)

def segments(target,*,shank_only=False):
 t=validate_target(target);r,s,e,l=t['CutDiameter']/2,t['ShankDia']/2,t['EffCutlength'],t['OverallLen']
 out=[]if shank_only else [((r,0.),(r,e))]
 if s>r+TOL:out.append(((r,e),(s,e)))
 out.append(((s,e),(s,l)))
 return out

def _interval_on(a,b,p,q):
 """Return a segment's covered parameter interval, orNone."""
 dx,dz=q[0]-p[0],q[1]-p[1];length=math.hypot(dx,dz)
 require(length>TOL,'Nondegenerate reference segment required')
 v=[dx/length,dz/length];uv=[]
 for x,z in (a,b):
  t=(x-p[0])*v[0]+(z-p[1])*v[1];normal=(x-p[0])*v[1]-(z-p[1])*v[0]
  if abs(normal)>TOL or t<-TOL or t>length+TOL:return None
  uv.append(min(length,max(0.,t)))
 return min(uv),max(uv)

def verify_profile(profile,target,*,shank_only=False):
 t=validate_target(target);wanted=segments(t,shank_only=shank_only)
 r,s,e,l=t['CutDiameter']/2,t['ShankDia']/2,t['EffCutlength'],t['OverallLen']
 minimum=e if shank_only else 0.
 require(profile.get('status')=='observed'and type(profile.get('chains'))is list,'Observed complete native profile required')
 chains=profile['chains'];require(1<=len(chains)<=16 and profile.get('declared_chain_count')==len(chains),'Exact bounded chain count required')
 coverage=[[]for _ in wanted];count=0
 for chain in chains:
  curves=chain.get('curves');require(chain.get('read_complete')is True and type(curves)is list
   and chain.get('declared_curve_count')==len(curves),'Complete native curve chain required')
  for curve in curves:
   count+=1;require(count<=256 and curve.get('read_complete')is True and type(curve.get('curve_type'))is int
    and curve['curve_type']==0,'Complete bounded LINE silhouettes only')
   a,b=_point(curve['start_native']),_point(curve['end_native'])
   require(all(minimum-TOL<=z<=l+TOL for _,z in(a,b)),'Native axial extent differs')
   matched=False
   for i,(p,q)in enumerate(wanted):
    interval=_interval_on(a,b,p,q)
    if interval is not None:
     coverage[i].append(interval);matched=True
   if matched:continue
   # Native cross-section caps/zero-length seams are allowed only on declared planes.
   require(close(a[1],b[1]),'Unexpected longitudinal native silhouette')
   z=(a[1]+b[1])/2
   require(any(close(z,k)for k in(minimum,e,l)),'Unexpected radial seam plane')
   maximum=r if close(z,0.)else s
   require(max(a[0],b[0])<=maximum+TOL,'Radial seam exceeds conservative envelope')
   if close(z,e)and s>r+TOL:
    lo,hi=sorted((a[0],b[0]));lo=max(lo,r);hi=min(hi,s)
    if hi>=lo:
     index=0 if shank_only else 1
     coverage[index].append((lo-r,hi-r))
 for intervals,(p,q)in zip(coverage,wanted):
  extent=math.dist(p,q);cursor=0.
  for lo,hi in sorted(intervals):
   require(lo<=cursor+TOL,'Gap in complete native profile')
   cursor=max(cursor,hi)
  require(cursor>=extent-TOL,'Incomplete native silhouette')
 return dict(status='PASS',representation='conservative_step_shank',shank_only=shank_only,
  curve_count=count,raw_tolerance=TOL,exact_manufacturer_taper_verified=False)

def verify_candidate(observed,recipe,holder_recipe):
 target=validate_target(recipe['target']);full=observed['full_tool'];mill=full['mill_tool']
 require(observed['identity']==recipe['identity'],'Exact declared serial identity required')
 require(full.get('geometry_read_complete')is True and full.get('profile_complete')is True,'Complete tool/shank/holder required')
 require(type(full['tool_type_raw'])is int and full['tool_type_raw']==1 and type(mill['type_raw'])is int and mill['type_raw']==1
  and type(mill['subtype_raw'])is int and mill['subtype_raw']==3 and close(mill['end_radius_native'],0.),'Flat BOTH zero-radius tool required')
 actual=values(full)
 for key,wanted in target.items():
  require(type(actual[key])is int and actual[key]==wanted if key in INTEGER_FIELDS else close(actual[key],wanted),'Native scalar differs: '+key)
 protrusion=target['Protrusion']
 require(close(full['holder']['holder_protrusion_native'],protrusion)
  and str(Path(full['holder']['name'])).casefold()==str(Path(holder_recipe['file_path'])).casefold(),'Holder identity or protrusion differs')
 return dict(profile_verified=True,tool=verify_profile(full['profiles']['tool'],target),
  shank=verify_profile(full['profiles']['shank'],target,shank_only=True),
  holder=verify_holder_profile(full['profiles']['holder'],holder_recipe,protrusion),
  physical_tool_identity_verified=False,physical_collet_seating_verified=False,
  exact_manufacturer_taper_verified=False,production_qualified=False)

