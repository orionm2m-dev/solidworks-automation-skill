"""Offline conservative duplicate policy for separately specified flat cutters.

This is a proposal helper, not a native writer. Complete observed candidates
must be supplied before one factory call. Matching identity or matching body
geometry requires reuse/reconciliation; diameter alone never proves identity.
"""
import math
from scripts.sw_cam_shared_cutter_geometry import values,TOL
from scripts.sw_cam_taper_tool_candidate import observed_profile_complete
from scripts.sw_cam_rough_firstcut import require

BODY_FIELDS=('CutDiameter','EffCutlength','ShoulderLength','ShankLength','NoOfFlutes',
    'ShoulderDia','ShankDia','MillToolShankType','OverallLen')


def identity_key(identity,*,allow_unknown=False):
    require(type(identity)is dict and {'ToolIdentifier','ToolVendor'}<=set(identity),'Observed vendor and exact identifier required')
    out=[]
    for name in ('ToolVendor','ToolIdentifier'):
        value=identity[name]
        require(type(value)is str and len(value)<=1000 and '\x00' not in value,'Bounded observed identity required')
        if not allow_unknown:require(bool(value.strip()),'Nonempty proposed identity required')
        out.append(' '.join(value.split()).casefold())
    return None if allow_unknown and not all(out) else tuple(out)


def body_key(full):
    require(full.get('geometry_read_complete')is True and full.get('profile_complete')is True,
        'Complete observed geometry required, not catalogue diameter alone')
    require(all(observed_profile_complete(full['profiles'][name])for name in ('tool','shank','holder')),
        'Complete tool, noncutting and holder curves required')
    raw=values(full);m=full['mill_tool']
    require(type(full['tool_type_raw'])is int and full['tool_type_raw']==1
        and type(m['type_raw'])is int and m['type_raw']==1,'Observed flat cutter required')
    result={k:raw[k]for k in BODY_FIELDS}
    result.update(subtype=m['subtype_raw'],end_radius=m['end_radius_native'])
    for key,value in result.items():
        require(type(value)in(int,float)and math.isfinite(value),'Finite full tool scalars required')
        if key in ('NoOfFlutes','MillToolShankType','subtype'):require(type(value)is int,'Strict native classification required')
    return result


def same_body(left,right):
    return set(left)==set(right)and all(type(left[k])is type(right[k])and left[k]==right[k]
        if type(right[k])is int else type(left[k])in(int,float)and abs(left[k]-right[k])<=TOL for k in right)


def require_new_exact_cutter(catalogue,observed_same_diameter,wanted_identity,wanted_target,*,accepted_identity_aliases=()):
    """Return only when all same-diameter candidates have distinct identities/bodies.

Aliases are explicit request evidence, never inferred from free-form names.
Same scalar body with different profile details also stops for reconciliation.
Protrusion/holder differences do not justify duplicating the same cutter body.
"""
    wanted=identity_key(wanted_identity);aliases={wanted}|{identity_key(v)for v in accepted_identity_aliases}
    require(type(catalogue)is list and 1<=len(catalogue)<=128,'Bounded current catalogue required')
    ids=[v['native_id']for v in catalogue]
    require(all(type(v)is int and v>0 for v in ids)and len(ids)==len(set(ids)),'Unique actual catalogue IDs required')
    diameter=wanted_target['CutDiameter'];require(type(diameter)in(int,float)and math.isfinite(diameter)and diameter>0,'Positive target diameter required')
    expected=[v['native_id']for v in catalogue if v['tool_type_raw']==1 and abs(v['CutDiameter']-diameter)<=TOL]
    require(type(observed_same_diameter)is list and [r['native_id']for r in observed_same_diameter]==expected,
        'Every same-diameter native tool must be fully read once in actual catalogue order')
    proposed={k:wanted_target[k]for k in BODY_FIELDS};proposed.update(subtype=3,end_radius=0.)
    distinct=[];unknown=[]
    for row in observed_same_diameter:
        require(type(row['native_id'])is int and row['full_tool']['tool_native_id']==row['native_id'],'Exact observed tool ID required')
        key=identity_key(row['identity'],allow_unknown=True);body=body_key(row['full_tool'])
        identifier=' '.join(row['identity']['ToolIdentifier'].split()).casefold()
        vendor=' '.join(row['identity']['ToolVendor'].split()).casefold()
        require(key not in aliases and not(identifier and (vendor==''or vendor==wanted[0]) and identifier in{v[1]for v in aliases}),
            'Matching manufacturer identity exists: reuse or reconcile; do not duplicate')
        if key is None:unknown.append(row['native_id'])
        require(not same_body(body,proposed),'Equivalent cutter body exists: reuse or reconcile; do not duplicate')
        distinct.append(row['native_id'])
    return {'policy':'complete_same_diameter_identity_and_body','distinct_existing_ids':distinct,'identity_unknown_ids':unknown,'physical_identity_verified':False,
        'new_definition_permitted_by_duplicate_policy':True,'native_called':False,'geometry_qualified':False}
