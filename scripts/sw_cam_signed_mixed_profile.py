"""Bounded exact LINE/ARC profile support for the shared native sketch creator."""
from copy import deepcopy
import math

MAX_SEGMENTS = 32
TAU = 2 * math.pi


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite strict number required')
    return float(value)


def vector(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('three finite coordinates required')
    return [number(x) for x in value]


def at(seg, fraction):
    a, b = seg['start_model_mm'], seg['end_model_mm']
    if seg['kind'] == 'line':
        return [x + fraction * (y - x) for x, y in zip(a, b)]
    c = seg['center_model_mm']; r = seg['radius_mm']
    angle = math.atan2(a[1] - c[1], a[0] - c[0]) + fraction * seg['sweep_radians']
    return [c[0] + r * math.cos(angle), c[1] + r * math.sin(angle), c[2]]


def length(seg):
    return (math.dist(seg['start_model_mm'], seg['end_model_mm']) if seg['kind'] == 'line'
            else seg['radius_mm'] * abs(seg['sweep_radians']))


def _on_arc(seg, p, tolerance):
    c = seg['center_model_mm']; a = seg['start_model_mm']; sweep = seg['sweep_radians']
    if abs(math.dist(p[:2], c[:2]) - seg['radius_mm']) > tolerance:
        return False
    theta = math.atan2(p[1] - c[1], p[0] - c[0]) - math.atan2(a[1] - c[1], a[0] - c[0])
    advance = (theta if sweep > 0 else -theta) % TAU
    angular = tolerance / seg['radius_mm']
    return advance <= abs(sweep) + angular or TAU - advance <= angular


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def intersections(a, b, tolerance):
    """Analytic candidate intersections; collinear/coincident overlaps fail closed."""
    if a['kind'] == 'arc' and b['kind'] == 'line':
        return intersections(b, a, tolerance)
    p, q = a['start_model_mm'][:2], a['end_model_mm'][:2]
    if a['kind'] == b['kind'] == 'line':
        r, s = b['start_model_mm'][:2], b['end_model_mm'][:2]
        u = [q[i] - p[i] for i in range(2)]; v = [s[i] - r[i] for i in range(2)]
        w = [r[i] - p[i] for i in range(2)]; det = _cross(u, v)
        scale = math.hypot(*u) * math.hypot(*v)
        if abs(det) <= 1e-13 * scale:
            if abs(_cross(w, u)) <= tolerance * math.hypot(*u):
                projection = sorted(sum((x[i]-p[i])*u[i] for i in range(2))/sum(z*z for z in u) for x in (r,s))
                low,high=max(0.,projection[0]),min(1.,projection[1])
                if high-low > tolerance/math.hypot(*u):raise ValueError('overlapping line segments')
                if high>=low-tolerance/math.hypot(*u):return [[p[i]+low*u[i] for i in range(2)]]
            return []
        t, f = _cross(w, v) / det, _cross(w, u) / det
        if -tolerance/math.hypot(*u) <= t <= 1+tolerance/math.hypot(*u) and -tolerance/math.hypot(*v) <= f <= 1+tolerance/math.hypot(*v):
            return [[p[i]+t*u[i] for i in range(2)]]
        return []
    if a['kind'] == 'line':
        c = b['center_model_mm'][:2]; r = b['radius_mm']
        u = [q[i]-p[i] for i in range(2)]; w = [p[i]-c[i] for i in range(2)]
        aa = sum(x*x for x in u); bb = 2*sum(x*y for x,y in zip(u,w)); cc = sum(x*x for x in w)-r*r
        disc = bb*bb-4*aa*cc
        if disc < -1e-13*max(bb*bb,abs(4*aa*cc),1e-12):return []
        disc = max(0.,disc)
        candidates = [[p[i]+t*u[i] for i in range(2)] for t in ((-bb-math.sqrt(disc))/(2*aa),(-bb+math.sqrt(disc))/(2*aa)) if -tolerance/math.sqrt(aa)<=t<=1+tolerance/math.sqrt(aa)]
        return [x for x in candidates if _on_arc(b,x,tolerance)]
    c, d = a['center_model_mm'][:2], b['center_model_mm'][:2]
    r, s = a['radius_mm'], b['radius_mm']; distance=math.dist(c,d)
    if distance <= tolerance and abs(r-s) <= tolerance:
        def angular_intervals(seg):
            center=seg['center_model_mm'];start=seg['start_model_mm'];sweep=seg['sweep_radians']
            low=(math.atan2(start[1]-center[1],start[0]-center[0])+min(0.,sweep))%TAU
            high=low+abs(sweep)
            return [(low,min(high,TAU))]+([(0.,high-TAU)] if high>TAU else [])
        if any(min(x[1],y[1])-max(x[0],y[0])>tolerance/min(r,s) for x in angular_intervals(a) for y in angular_intervals(b)):
            raise ValueError('overlapping circular arcs')
        return [x[:2] for x in (a['start_model_mm'],a['end_model_mm']) if _on_arc(b,x,tolerance)]
    if distance > r+s+tolerance or distance < abs(r-s)-tolerance or distance == 0:return []
    along=(r*r-s*s+distance*distance)/(2*distance); h2=r*r-along*along
    if h2 < -tolerance*max(r,s):return []
    h=math.sqrt(max(0.,h2)); ux,uy=(d[0]-c[0])/distance,(d[1]-c[1])/distance
    candidates=[[c[0]+along*ux-sign*h*uy,c[1]+along*uy+sign*h*ux] for sign in (-1,1)]
    return [x for x in candidates if _on_arc(a,x,tolerance) and _on_arc(b,x,tolerance)]


def validate_profile(profile, *, plane_axis, plane_offset_mm, tolerance_mm=1e-5):
    if plane_axis != 'Z':raise ValueError('mixed profiles currently require a world XY plane')
    if type(profile) is not dict or set(profile) != {'kind','segments'} or profile['kind']!='closed_mixed':
        raise ValueError('exact closed_mixed profile fields required')
    rows=deepcopy(profile['segments'])
    if not isinstance(rows,list) or not 3<=len(rows)<=MAX_SEGMENTS:raise ValueError('3..32 mixed segments required')
    tol=number(tolerance_mm)
    if tol != 1e-5:raise ValueError('qualified profile tolerance must not change')
    for s in rows:
        keys={'kind','start_model_mm','end_model_mm','mid_model_mm'}
        if s.get('kind')=='arc':keys|={'center_model_mm','radius_mm','sweep_radians'}
        elif s.get('kind')!='line':raise ValueError('only bounded line and arc supported')
        if set(s)!=keys:raise ValueError('exact segment fields required')
        for key in keys-{'kind','radius_mm','sweep_radians'}:
            s[key]=vector(s[key])
            if max(map(abs,s[key]))>1000 or abs(s[key][2]-plane_offset_mm)>1e-6:raise ValueError('segment not on requested plane')
        if s['kind']=='arc':
            s['radius_mm']=number(s['radius_mm']);s['sweep_radians']=number(s['sweep_radians'])
            if not .001<=s['radius_mm']<=500 or not 1e-6<abs(s['sweep_radians'])<TAU-1e-6:raise ValueError('arc radius/sweep outside bound')
            if abs(math.dist(s['start_model_mm'],s['center_model_mm'])-s['radius_mm'])>tol:raise ValueError('arc start radius mismatch')
            if math.dist(at(s,1),s['end_model_mm'])>tol:raise ValueError('arc signed sweep endpoint mismatch')
        if length(s)<=tol*4:raise ValueError('degenerate or sub-tolerance segment')
        if math.dist(at(s,.5),s['mid_model_mm'])>tol:raise ValueError('segment midpoint mismatch')
    for i,a in enumerate(rows):
        if math.dist(a['end_model_mm'],rows[(i+1)%len(rows)]['start_model_mm'])>tol:raise ValueError('closed chain discontinuity')
        for j in range(i+1,len(rows)):
            b=rows[j]; hits=intersections(a,b,tol)
            shared=[]
            if j==i+1:shared.append(a['end_model_mm'][:2])
            if i==0 and j==len(rows)-1:shared.append(a['start_model_mm'][:2])
            if any(not any(math.dist(hit,x)<=tol for x in shared) for hit in hits):raise ValueError('self intersection or nonadjacent contact')
    return {'kind':'closed_mixed','segments':rows}


def create_segments(manager, profile, *, local, mutate):
    for s in profile['segments']:
        a,b=local(s['start_model_mm']),local(s['end_model_mm'])
        if s['kind']=='line':entity=mutate(manager,'CreateLine',*a,*b)
        else:entity=mutate(manager,'Create3PointArc',*a,*b,*local(s['mid_model_mm']))
        if entity is None:raise ValueError('mixed profile creator returned null; no retry')




def match_rows(expected, rows, tolerance_m):
    if tolerance_m != 1e-8:raise ValueError('qualified readback tolerance must not change')
    for row in rows:
        if row.get('type') not in ('line','arc') or number(row.get('length_m'))<=0:raise ValueError('invalid native segment')
        if len(row['points_model_m'])!=2:raise ValueError('two native endpoints required')
        for point in row['points_model_m']+[row['mid_model_m']]:vector(point)
        if row['type']=='arc':
            vector(row['center_model_m'])
            if number(row['radius_m'])<=0:raise ValueError('positive native radius required')
    if len(rows)!=len(expected):raise ValueError('mixed entity count mismatch')
    unused=list(range(len(rows))); matched=[]
    for s in expected:
        points=[[x/1000 for x in s[k]] for k in ('start_model_mm','end_model_mm')]
        found=[]
        for index in unused:
            row=rows[index]
            if row['type']!=s['kind']:continue
            if not any(all(math.dist(a,b)<=tolerance_m for a,b in zip(points,p)) for p in (row['points_model_m'],row['points_model_m'][::-1])):continue
            if abs(row['length_m']-length(s)/1000)>tolerance_m:continue
            if math.dist(row['mid_model_m'],[v/1000 for v in s['mid_model_mm']])>tolerance_m:continue
            if s['kind']=='arc' and (abs(row['radius_m']-s['radius_mm']/1000)>tolerance_m or math.dist(row['center_model_m'],[v/1000 for v in s['center_model_mm']])>tolerance_m):continue
            found.append(index)
        if len(found)!=1:raise ValueError('mixed curve readback is missing or ambiguous')
        unused.remove(found[0]);matched.append(found[0])
    return matched


def read_native(sw,sketch,spec,*,call,point,point_values,typed_segment,rigid_transform,tolerance_m):
    if call(sketch,'Is3D') is not False:raise ValueError('2D sketch required')
    raw=call(sketch,'GetSketchSegments');expected=spec['profile']['segments']
    if not isinstance(raw,(list,tuple)) or len(raw)!=len(expected):raise ValueError('mixed entity count mismatch')
    mu=call(sw,'GetMathUtility');transform=sketch.ModelToSketchTransform;rigid_transform(transform)
    inverse=call(transform,'Inverse');rigid_transform(inverse);rows=[]
    for seg in raw:
        k=call(seg,'GetType')
        if type(k) is not int or k not in (0,1) or seg.ConstructionGeometry is not False:raise ValueError('unexpected mixed entity type')
        native=typed_segment(seg,k)
        endpoints=[point(mu,point_values(call(native,key)),inverse) for key in ('GetStartPoint2','GetEndPoint2')]
        row={'type':'arc' if k else 'line','points_model_m':endpoints,'length_m':number(call(seg,'GetLength'))}
        if k:
            is_circle=call(native,'IsCircle')
            if type(is_circle) is not int or is_circle!=0:raise ValueError('partial arc requires native integer zero')
            row.update(center_model_m=point(mu,point_values(call(native,'GetCenterPoint2')),inverse),radius_m=number(call(native,'GetRadius')))
            local_endpoints=[point_values(call(native,key)) for key in ('GetStartPoint2','GetEndPoint2')]
            center_local=point_values(call(native,'GetCenterPoint2'))
            direction=call(native,'GetRotationDir');normal=call(native,'GetNormalVector')
            trimmed=reconstruct_arc(*local_endpoints,center_local,row['radius_m'],row['length_m'],direction,normal,tolerance_m=tolerance_m)
            row.update(mid_model_m=point(mu,trimmed['mid_sketch_m'],inverse),native_trim=trimmed)
        else:row['mid_model_m']=[(a+b)/2 for a,b in zip(*endpoints)]
        rows.append(row)
    mapping=match_rows(expected,rows,tolerance_m)
    return {'entities':rows,'expected_segment_to_native_index':mapping,'model_to_sketch_transform':[number(v) for v in transform.ArrayData],'readback_tolerance_m':tolerance_m,'arc_interval_midpoint_verified':True,'native_rotation_direction_assumed':False,'native_rotation_direction_qualified':True,'native_arc_trim_basis':'native_endpoints_rotation_and_independent_length','underlying_curve_trim_used':False}


def _arc_finite(value):
    if type(value) not in (float,int) or not math.isfinite(value):
        raise ValueError('Finite native numeric value required')
    return float(value)


def _arc_point(value):
    if type(value) not in (list,tuple) or len(value)!=3:
        raise ValueError('Exact three-component sketch coordinate required')
    return [_arc_finite(v) for v in value]


def reconstruct_arc(start,end,center,radius,length,rotation,normal,*,tolerance_m=1e-8):
    """Use GetRotationDir1/-1 about proved positive sketch Z; check normal and length."""
    a,b,c,n=map(_arc_point,(start,end,center,normal))
    r,observed,tol=map(_arc_finite,(radius,length,tolerance_m))
    if type(rotation) is not int or rotation not in (-1,1):
        raise ValueError('Native rotation must be exact integer1 or minus1')
    if not(r>0 and observed>0 and tol>0 and tol<r):
        raise ValueError('Positive nondegenerate native arc and tolerance required')
    if math.dist(n,[0.,0.,float(rotation)])>1e-9:
        raise ValueError('Oriented native arc normal disagrees with its rotation direction')
    if max(abs(v[2])for v in (a,b,c))>tol:
        raise ValueError('Native coordinates are not on the sketch-local XY plane')
    u=[a[i]-c[i]for i in range(3)];v=[b[i]-c[i]for i in range(3)]
    if abs(math.hypot(u[0],u[1])-r)>tol or abs(math.hypot(v[0],v[1])-r)>tol:
        raise ValueError('Actual endpoints disagree with native radius')
    if math.dist(a,b)<=tol:
        raise ValueError('Coincident endpoints cannot identify a partial arc')
    angle=math.atan2(u[0]*v[1]-u[1]*v[0],u[0]*v[0]+u[1]*v[1])
    if angle<=0:angle+=2*math.pi
    sweep=angle if rotation==1 else angle-2*math.pi
    expected=r*abs(sweep)
    if abs(expected-observed)>tol:
        raise ValueError('Native length rejects reconstructed arc interval')
    half=sweep/2
    middle=[c[0]+u[0]*math.cos(half)-u[1]*math.sin(half),
            c[1]+u[0]*math.sin(half)+u[1]*math.cos(half),c[2]]
    return dict(mid_sketch_m=middle,signed_sweep_rad=sweep,rotation_direction_raw=rotation,
                normal_vector_raw=n,native_length_m=observed,reconstructed_length_m=expected,
                independent_native_length_verified=True,underlying_curve_trim_used=False)
