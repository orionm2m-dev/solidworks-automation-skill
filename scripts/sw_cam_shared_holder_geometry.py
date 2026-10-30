"""Bounded vendor holder geometry and native profile verification."""
import hashlib,json,math
from pathlib import Path
TOL=1e-6
def num(v):
    if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('Finite geometry required')
    return float(v)
def near(a,b):
    return len(a)==len(b) and all(abs(num(x)-num(y))<=TOL for x,y in zip(a,b))
def point(v,n):
    if type(v) not in (list,tuple) or len(v)!=n:raise ValueError('Exact point dimension required')
    return tuple(map(num,v))
def read_holder_recipe(file_path,file_sha256,recipe_path,recipe_sha256):
    blobs=[];pins=[]
    for path,sha in [(file_path,file_sha256),(recipe_path,recipe_sha256)]:
        p=Path(path)
        if not p.is_absolute() or type(sha) is not str or len(sha)!=64:raise ValueError('Absolute asset and SHA256 required')
        raw=p.read_bytes()
        if len(raw)>262144 or hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Holder asset differs')
        blobs.append(raw);pins.append(dict(path=str(p),sha256=sha))
    text=blobs[0].decode('utf-8-sig');recipe=json.loads(blobs[1])
    if Path(file_path).suffix.lower()!='.mh' or 'CWToolGen Version: <1.0>' not in text:raise ValueError('Vendor MH format required')
    if recipe.get('source_sha256')!=file_sha256 or recipe.get('coordinate_order')!=['radius','axial_z']:raise ValueError('Nominal binding differs')
    records=recipe.get('records')
    if type(records) is not list or not 1<=len(records)<=256 or recipe.get('record_count')!=len(records):raise ValueError('Bounded exact records required')
    lines=[v.split() for v in text.splitlines() if v.strip() and not v.lstrip().startswith('#')]
    if len(lines)!=len(records):raise ValueError('Record count differs')
    for t,r in zip(lines,records):
        kind=r.get('kind')
        if kind not in ('line','arc') or t[0]!=kind or len(t)!=(5 if kind=='line' else 8):raise ValueError('Unsupported record')
        expected=list(point(r['start_rz'],2))+list(point(r['end_rz'],2))
        if kind=='arc':
            flag=r.get('native_file_direction_flag')
            if type(flag) is not int or flag not in (0,1):raise ValueError('Explicit arc flag required')
            expected+=list(point(r['center_rz'],2))+[flag]
        if not near(list(map(float,t[1:])),expected):raise ValueError('Nominal differs from asset')
    return dict(file_path=str(Path(file_path)),pins=pins,records=records)
def check_holder_pins(recipe):
    for pin in recipe['pins']:
        if hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('Holder asset changed')

def verify_holder_profile(profile,recipe,protrusion):
    """Verify all segments and intended minor fillet arcs, including midpoint.
    Does not generalize MH flags or qualify physical grip, spindle or collisions.
    """
    shift=num(protrusion);chains=profile.get('chains');curves=[]
    if profile.get('status')!='observed' or type(chains) is not list or not 1<=len(chains)<=16 or profile.get('declared_chain_count')!=len(chains):raise ValueError('Complete holder chains required')
    for c in chains:
        items=c.get('curves')
        if c.get('read_complete') is not True or type(items) is not list or c.get('declared_curve_count')!=len(items):raise ValueError('Incomplete holder chain')
        curves+=items
    if len(curves)!=len(recipe['records']) or len(curves)>256:raise ValueError('Curve count differs')
    def xyz(rz):
        r,z=point(rz,2);return r,0.,z+shift
    remaining=list(curves)
    for record in recipe['records']:
        a,b=xyz(record['start_rz']),xyz(record['end_rz'])
        kind=0 if record['kind']=='line' else 1;matches=[]
        for i,c in enumerate(remaining):
            if c.get('read_complete') is not True or type(c.get('curve_type')) is not int or c['curve_type']!=kind:continue
            start,end=point(c['start_native'],3),point(c['end_native'],3)
            if (near(start,a) and near(end,b)) or (near(start,b) and near(end,a)):matches.append(i)
        if len(matches)!=1:raise ValueError('Missing, extra or ambiguous segment')
        c=remaining.pop(matches[0])
        if kind==1:
            centre=xyz(record['center_rz'])
            if not near(point(c['centre_native'],3),centre):raise ValueError('Arc centre differs')
            va=[x-y for x,y in zip(a,centre)];vb=[x-y for x,y in zip(b,centre)]
            radius=math.sqrt(sum(x*x for x in va))
            if radius<=TOL or not near([math.sqrt(sum(x*x for x in vb)),c['radius_native']],[radius,radius]):raise ValueError('Arc radius differs')
            bisector=[x+y for x,y in zip(va,vb)];norm=math.sqrt(sum(x*x for x in bisector))
            if norm<=TOL:raise ValueError('Semicircle or degenerate fillet unsupported')
            midpoint=[x+radius*v/norm for x,v in zip(centre,bisector)]
            if not near(point(c['mid_native'],3),midpoint):raise ValueError('Arc takes wrong sweep')
    return dict(native_holder_shape_verified=True,curve_count=len(curves),raw_tolerance=TOL,
        physical_grip_verified=False,spindle_compatibility_verified=False,
        collision_clearance_verified=False,production_qualified=False)

def apply_holder_reference(holder,recipe,*,read,invoke,guard,persist,report):
    before=read(holder,'GetName');wanted=recipe['file_path']
    if str(Path(before)).casefold()==str(Path(wanted)).casefold():
        raise ValueError('Holder reference already at target; do not replay')
    report['holder_reference']=dict(before=before,requested=wanted,setter_attempted=False,readback_verified=False)
    guard();check_holder_pins(recipe)
    report.update(mutation_attempted=True,holder_assignment_attempted=True,native_dispatch_pending=True)
    report['holder_reference']['setter_attempted']=True
    persist();guard()
    result=invoke(holder,'SetFilePathForUserDefinedHolder',wanted)
    report.update(native_dispatch_pending=False)
    report['holder_reference'].update(return_type=type(result).__name__,hresult=result if type(result) is int else None,native_call_returned=True)
    persist();guard()
    if type(result) is not int or result!=0:raise ValueError('Unexpected holder setter HRESULT; do not replay')
    after=read(holder,'GetName');report['holder_reference']['after']=after
    if str(Path(after)).casefold()!=str(Path(wanted)).casefold():raise ValueError('Holder reference readback differs')
    report['holder_reference']['readback_verified']=True
    report['holder_assignment_performed']=True
    check_holder_pins(recipe);guard();persist()
