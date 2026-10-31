"""Nominal relieved-neck square-end cutter envelope and native profile proof.

The envelope is an explicit CAM proposal, not a manufacturer CAD replacement.
Only type1 flat cutters with neck type2 and a piecewise-linear shank are accepted.
"""
from pathlib import Path
from scripts.sw_cam_shared_cutter_geometry import FIELDS, INTEGER_FIELDS, values, close, number, TOL, _point
from scripts.sw_cam_shared_holder_geometry import verify_holder_profile


def validate_target(target):
    if type(target) is not dict or set(target)!={v[0] for v in FIELDS}:
        raise ValueError('Exactly ten declared cutter fields required')
    for name,value in target.items():
        if name in INTEGER_FIELDS:
            if type(value) is not int:raise ValueError('Strict integer tool field required')
        elif number(value)<=0:raise ValueError('Positive tool dimension required')
    if target['MillToolShankType']!=2 or not 1<=target['NoOfFlutes']<=32:
        raise ValueError('Relieved neck type2 required')
    if not (0<target['ShoulderDia']<target['CutDiameter']<=target['ShankDia']
        and 0<target['EffCutlength']<target['ShoulderLength']<target['ShankLength']
        <target['Protrusion']<target['OverallLen']):
        raise ValueError('Separate cutting length, neck, shoulder, shank and holder seating required')
    return dict(target)


def expected_segments(target, *, shank_only=False):
    validate_target(target)
    r=target['CutDiameter']/2;n=target['ShoulderDia']/2;s=target['ShankDia']/2
    e=target['EffCutlength'];a=target['ShoulderLength'];b=target['ShankLength'];l=target['OverallLen']
    segments=[((r,0.),(r,e)),((n,e),(n,a)),((n,a),(s,b)),((s,b),(s,l))]
    return segments[1:] if shank_only else segments


def cap_radius(target,z):
    e=target['EffCutlength'];a=target['ShoulderLength'];b=target['ShankLength']
    if z<=e+TOL:return target['CutDiameter']/2
    if z<=a+TOL:return target['ShoulderDia']/2
    if z>=b-TOL:return target['ShankDia']/2
    return target['ShoulderDia']/2+(target['ShankDia']-target['ShoulderDia'])/2*(z-a)/(b-a)


def verify_profile(profile,target,*,shank_only=False):
    """Require full longitudinal silhouette coverage; tolerate split/reversed lines.

    Native cutter/shank chains are open half profiles and may include cross
    sections or zero-length line seams. Those must stay within the nominal body.
    No extra non-horizontal edge, arc, unsupported segment or profile hole passes.
    """
    segments=expected_segments(target,shank_only=shank_only)
    if profile.get('status')!='observed' or type(profile.get('chains')) is not list:
        raise ValueError('Observed complete native segment chains required')
    chains=profile['chains']
    if not 1<=len(chains)<=16 or profile.get('declared_chain_count')!=len(chains):
        raise ValueError('Exact bounded profile chain count required')
    coverage=[[] for _ in segments]
    e=target['EffCutlength'];n=target['ShoulderLength'];s=target['ShankLength'];l=target['OverallLen']
    min_z=e if shank_only else 0
    allowed_caps=[e,n,s,l] if shank_only else [0,e,n,s,l]
    count=0
    for chain in chains:
        curves=chain.get('curves')
        if (chain.get('read_complete') is not True or type(curves) is not list
            or chain.get('declared_curve_count')!=len(curves)):
            raise ValueError('Complete exact curve collection required')
        for curve in curves:
            count+=1
            if count>256 or curve.get('read_complete') is not True or type(curve.get('curve_type')) is not int or curve['curve_type']!=0:
                raise ValueError('Only bounded complete line profiles supported')
            a=_point(curve['start_native']);b=_point(curve['end_native'])
            for x,z in (a,b):
                if z<min_z-TOL or z>l+TOL:raise ValueError('Tool profile exceeds nominal axial extent')
            if close(a[1],b[1]):
                z=(a[1]+b[1])/2
                if not any(close(z,c) for c in allowed_caps):
                    raise ValueError('Unexpected interior radial edge')
                radius=cap_radius(target,z)
                if max(a[0],b[0])>radius+TOL:
                    raise ValueError('Radial cap or seam extends outside nominal cutter')
                continue
            matched=False
            for index,((x0,z0),(x1,z1)) in enumerate(segments):
                def on(point):
                    x,z=point
                    return z0-TOL<=z<=z1+TOL and close(x,x0+(x1-x0)*(z-z0)/(z1-z0))
                if on(a) and on(b):
                    coverage[index].append((max(z0,min(a[1],b[1])),min(z1,max(a[1],b[1]))))
                    matched=True;break
            if not matched:raise ValueError('Native longitudinal profile differs from declared conservative neck envelope')
    for bounds,((_,z0),(_,z1)) in zip(coverage,segments):
        cursor=z0
        for lo,hi in sorted(bounds):
            if lo>cursor+TOL:raise ValueError('Gap in native silhouette coverage')
            cursor=max(cursor,hi)
        if cursor<z1-TOL:raise ValueError('Incomplete native silhouette coverage')
    return dict(status='PASS',raw_tolerance=TOL,curve_count=count,shank_only=shank_only,
                units_verified=False,physical_tool_identity_verified=False)



def verify_candidate(full,target,holder_recipe):
    validate_target(target)
    if full.get('geometry_read_complete') is not True or full.get('profile_complete') is not True:
        raise ValueError('Complete candidate tool/shank/holder profiles required')
    mill=full['mill_tool']
    if full['tool_type_raw']!=1 or mill['type_raw']!=1 or mill['subtype_raw']!=3 or not close(mill['end_radius_native'],0):
        raise ValueError('Flat square-end cutter with BOTH classification required')
    actual=values(full)
    for name,wanted in target.items():
        if name in INTEGER_FIELDS:
            if type(actual[name]) is not int or actual[name]!=wanted:raise ValueError('Integral target differs')
        elif not close(actual[name],wanted):raise ValueError('Candidate scalar differs: '+name)
    if not close(full['holder']['holder_protrusion_native'],target['Protrusion']):
        raise ValueError('Holder and tool protrusion differ')
    if str(Path(full['holder']['name'])).casefold()!=str(Path(holder_recipe['file_path'])).casefold():
        raise ValueError('Pinned separate holder reference differs')
    return dict(profile_verified=True,
        tool=verify_profile(full['profiles']['tool'],target),
        shank=verify_profile(full['profiles']['shank'],target,shank_only=True),
        holder=verify_holder_profile(full['profiles']['holder'],holder_recipe,target['Protrusion']),
        conservative_envelope_only=True,manufacturer_microgeometry_verified=False,
        physical_tool_identity_verified=False,physical_collet_seating_verified=False,production_qualified=False)
