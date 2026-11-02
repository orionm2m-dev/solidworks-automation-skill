"""Exact OSG3130520 nominal rotational body and native profile qualification.

Uses existing typed type1 cutter fields. A native silhouette must reproduce
the declared manufacturer body before Save. Shank-chain partition conventions
never erase the noncutting cylinder6..7.5, which the complete tool profile proves.
"""
from pathlib import Path
from scripts.sw_cam_shared_cutter_geometry import FIELDS,INTEGER_FIELDS,values,close,number,TOL,_point
from scripts.sw_cam_shared_holder_geometry import verify_holder_profile
from scripts.sw_cam_rough_firstcut import require
TARGET={'CutDiameter':2.,'EffCutlength':6.,'ShoulderLength':7.5,'ShankLength':11.2,
    'NoOfFlutes':4,'ShoulderDia':2.,'ShankDia':4.,'MillToolShankType':1,
    'Protrusion':22.,'OverallLen':40.}


def validate_target(target):
    require(type(target)is dict and set(target)==set(TARGET),'Exact3130520 ten-field recipe required')
    for key,wanted in TARGET.items():
        require(type(target[key])is int and target[key]==wanted if key in INTEGER_FIELDS else close(target[key],wanted),
            'Only reviewed3130520 geometry allowed: '+key)
    return dict(target)


def segments(target):
    validate_target(target)
    return [((1.,0.),(1.,7.5)),((1.,7.5),(2.,11.2)),((2.,11.2),(2.,40.))]


def radius_at(z):
    return 1. if z<=7.5 else 2. if z>=11.2 else 1.+(z-7.5)/3.7


def verify_profile(profile,target,*,shank_only=False):
    body=segments(target);minimum=6. if shank_only else 0.
    wanted=[((1.,7.5),(2.,11.2)),((2.,11.2),(2.,40.))]if shank_only else body
    intervals=[[]for _ in wanted];count=0
    chains=profile.get('chains')
    require(profile.get('status')=='observed'and type(chains)is list and 1<=len(chains)<=16
        and profile.get('declared_chain_count')==len(chains),'Complete bounded native chains required')
    for chain in chains:
        curves=chain.get('curves');require(chain.get('read_complete')is True and type(curves)is list
            and chain.get('declared_curve_count')==len(curves),'Complete exact curve chain required')
        for curve in curves:
            count+=1;require(count<=256 and curve.get('read_complete')is True and type(curve.get('curve_type'))is int
                and curve['curve_type']==0,'Only bounded complete line profiles allowed')
            a,b=_point(curve['start_native']),_point(curve['end_native'])
            require(all(minimum-TOL<=z<=40.+TOL for _,z in (a,b)),'Native profile axial extent differs')
            if close(a[1],b[1]):
                z=(a[1]+b[1])/2
                require(any(close(z,c)for c in (minimum,6.,7.5,11.2,40.))and max(a[0],b[0])<=radius_at(z)+TOL,
                    'Unexpected radial seam or excessive body')
                continue
            valid=False
            for (r0,z0),(r1,z1)in body:
                if all(z0-TOL<=z<=z1+TOL and close(r,r0+(r1-r0)*(z-z0)/(z1-z0))for r,z in (a,b)):
                    valid=True;break
            require(valid,'Native profile does not reproduce manufacturer body')
            lo,hi=sorted((a[1],b[1]))
            for index,((r0,z0),(r1,z1))in enumerate(wanted):
                if lo>=z0-TOL and hi<=z1+TOL:intervals[index].append((max(z0,lo),min(z1,hi)))
    for pieces,((_,lo),(_,hi))in zip(intervals,wanted):
        cursor=lo
        for begin,end in sorted(pieces):
            require(begin<=cursor+TOL,'Gap in complete native silhouette');cursor=max(cursor,end)
        require(cursor>=hi-TOL,'Incomplete native silhouette')
    return {'status':'PASS','curve_count':count,'shank_only':shank_only,'raw_tolerance':TOL,
        'noncutting_extension_mm':[6.,7.5],'manufacturer_microgeometry_verified':False}


def verify_candidate(observed,recipe,holder_recipe):
    target=validate_target(recipe['target']);full=observed['full_tool'];mill=full['mill_tool']
    require(observed['identity']==recipe['identity'],'Exact separate serial identity required')
    require(full.get('geometry_read_complete')is True and full.get('profile_complete')is True,'Complete tool/shank/holder required')
    require(type(full['tool_type_raw'])is int and full['tool_type_raw']==1 and type(mill['type_raw'])is int
        and mill['type_raw']==1 and type(mill['subtype_raw'])is int and mill['subtype_raw']==3
        and close(mill['end_radius_native'],0.),'Flat BOTH zero-radius tool required')
    actual=values(full)
    for key,wanted in target.items():
        require(type(actual[key])is int and actual[key]==wanted if key in INTEGER_FIELDS else close(actual[key],wanted),
            'Native3130520 scalar differs: '+key)
    require(close(full['holder']['holder_protrusion_native'],22.)and str(Path(full['holder']['name'])).casefold()==str(Path(holder_recipe['file_path'])).casefold(),
        'Existing holder reference or22mm protrusion differs')
    return {'profile_verified':True,'tool':verify_profile(full['profiles']['tool'],target),
        'shank':verify_profile(full['profiles']['shank'],target,shank_only=True),
        'holder':verify_holder_profile(full['profiles']['holder'],holder_recipe,22.),
        'noncutting_extension_confirmed_by_complete_body':True,'physical_tool_identity_verified':False,
        'physical_collet_seating_verified':False,'production_qualified':False}
