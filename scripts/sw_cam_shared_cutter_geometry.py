"""Pure bounded target validation and native rotational-envelope comparison."""
from copy import deepcopy
import math

TOL = 1e-7
# Order keeps flute/protrusion/overall limits coherent during the batch.
FIELDS = (
    ('EffCutlength','mill_tool','effective_cutting_length_native'),
    ('ShoulderLength','mill_tool','shoulder_length_native'),
    ('ShankLength','mill_tool','shank_length_native'),
    ('NoOfFlutes','mill_tool','flute_count_raw'),
    ('CutDiameter',None,'cut_diameter_native'),
    ('ShoulderDia','mill_tool','shoulder_diameter_native'),
    ('ShankDia','mill_tool','shank_diameter_native'),
    ('MillToolShankType','mill_tool','shank_type_raw'),
    ('Protrusion',None,'tool_protrusion_native'),
    ('OverallLen','mill_tool','overall_length_native'),
)
KEYS = tuple(row[0] for row in FIELDS)
INTEGER_FIELDS = {'NoOfFlutes','MillToolShankType'}


def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('Finite strict numeric geometry required')
    return float(value)


def close(a,b):
    return abs(number(a)-number(b)) <= TOL


def values(full):
    return {prop:(full[section][key] if section else full[key]) for prop,section,key in FIELDS}


def validate_target(target):
    if type(target) is not dict or set(target)!=set(KEYS):
        raise ValueError('Exactly ten explicit supported cutter fields required')
    for prop,v in target.items():
        if prop in INTEGER_FIELDS:
            if type(v) is not int:raise ValueError('Strict integral tool classification/count required')
        elif number(v)<=0:raise ValueError('Positive native tool dimensions required')
    if not 1<=target['NoOfFlutes']<=32 or target['MillToolShankType']!=1:
        raise ValueError('Bounded tapered flat-end cutter only')
    d,e,sd,l,sl,sh=([number(target[k]) for k in ('CutDiameter','EffCutlength','ShankDia',
                                              'OverallLen','ShoulderLength','ShankLength')])
    if not (d<=target['ShoulderDia']<=sd and close(target['ShoulderDia'],d)
            and close(sl,e) and 0<e<sh<l and e<target['Protrusion']<l):
        raise ValueError('Coherent no-neck tapered cutter and stickout dimensions required')
    return dict(target)


def expected_segments(target, *, shank_only=False):
    validate_target(target)
    r=target['CutDiameter']/2
    r2=target['ShankDia']/2
    e=target['EffCutlength'];s=target['ShankLength'];l=target['OverallLen']
    result=[((r,0.0),(r,e)),((r,e),(r2,s)),((r2,s),(r2,l))]
    return result[1:] if shank_only else result


def _point(raw):
    if not isinstance(raw,(list,tuple)) or len(raw)!=3:
        raise ValueError('Exact native XYZ profile point required')
    x,y,z=map(number,raw)
    if abs(y)>TOL or x < -TOL:raise ValueError('Tool profile leaves nonnegative XZ half-plane')
    return x,z


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
    e=target['EffCutlength'];s=target['ShankLength'];l=target['OverallLen']
    min_z=e if shank_only else 0
    allowed_caps=[e,s,l] if shank_only else [0,e,s,l]
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
                radius=target['CutDiameter']/2 if z<=e+TOL else (
                    target['ShankDia']/2 if z>=s-TOL else
                    target['CutDiameter']/2+(target['ShankDia']-target['CutDiameter'])/2*(z-e)/(s-e))
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
            if not matched:raise ValueError('Native longitudinal profile differs from nominal STEP body')
    for bounds,((_,z0),(_,z1)) in zip(coverage,segments):
        cursor=z0
        for lo,hi in sorted(bounds):
            if lo>cursor+TOL:raise ValueError('Gap in native silhouette coverage')
            cursor=max(cursor,hi)
        if cursor<z1-TOL:raise ValueError('Incomplete native silhouette coverage')
    return dict(status='PASS',raw_tolerance=TOL,curve_count=count,shank_only=shank_only,
                units_verified=False,physical_tool_identity_verified=False)


def translated_profile(before,after,delta):
    """Verify a holder profile changes only by the planned axial placement."""
    if type(before) is not type(after):return False
    if isinstance(before,dict):
        if before.keys()!=after.keys():return False
        for key,value in before.items():
            if key in ('start_native','end_native','mid_native','centre_native'):
                if not isinstance(value,list) or len(value)!=3 or not isinstance(after[key],list) or len(after[key])!=3:return False
                if not all(close(a,b) for a,b in zip([value[0],value[1],value[2]+delta],after[key])):return False
            elif not translated_profile(value,after[key],delta):return False
        return True
    if isinstance(before,list):
        return len(before)==len(after) and all(translated_profile(a,b,delta) for a,b in zip(before,after))
    if type(before) in (int,float):
        return close(before,after)
    return before==after


def verify_full_delta(before,after,target,holder_recipe=None):
    validate_target(target)
    if (before.get('geometry_read_complete') is not True or before.get('profile_complete') is not True
        or after.get('geometry_read_complete') is not True or after.get('profile_complete') is not True):
        raise ValueError('Complete baseline and final tool/holder/profile data required')
    new_values=values(after)
    for prop,wanted in target.items():
        if prop in INTEGER_FIELDS:
            if type(new_values[prop]) is not int or new_values[prop]!=wanted:
                raise ValueError('Strict requested integral tool field differs')
        elif not close(new_values[prop],wanted):raise ValueError('Requested tool dimension differs')
    proofs=[verify_profile(after['profiles']['tool'],target),
            verify_profile(after['profiles']['shank'],target,shank_only=True)]
    delta=target['Protrusion']-before['tool_protrusion_native']
    if not close(after['holder']['holder_protrusion_native'],target['Protrusion']):
        raise ValueError('Holder/tool planned protrusion mismatch')
    holder_proof=None
    if holder_recipe is None:
        if not translated_profile(before['profiles']['holder'],after['profiles']['holder'],delta):
            raise ValueError('Holder profile changed beyond explicit axial placement')
    else:
        from pathlib import Path
        from scripts.sw_cam_shared_holder_geometry import verify_holder_profile
        if str(Path(after['holder']['name'])).casefold()!=str(Path(holder_recipe['file_path'])).casefold():
            raise ValueError('Assigned holder file differs')
        holder_proof=verify_holder_profile(after['profiles']['holder'],holder_recipe,target['Protrusion'])
    expected=deepcopy(before);actual=deepcopy(after)
    for prop,section,key in FIELDS:
        (expected[section] if section else expected)[key]=(actual[section] if section else actual)[key]
    expected['holder']['holder_protrusion_native']=actual['holder']['holder_protrusion_native']
    if holder_recipe is not None:expected['holder']['name']=actual['holder']['name']
    expected['profiles']=actual['profiles']
    expected['profile_budget']=actual['profile_budget']
    if expected!=actual:
        raise ValueError('Undeclared non-profile tool or holder field changed')
    return dict(nominal_raw_cutter_profile_verified=True,profile_comparisons=proofs,
                holder_shape_unchanged_except_axial_placement=holder_recipe is None,holder_profile_comparison=holder_proof,
                physical_holder_qualified=False,production_qualified=False)
