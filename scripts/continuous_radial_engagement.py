"""Continuous transverse engagement bounds for a supplied exact rational 2D model.

This module does not certify a measured stock mesh, infer CL arc direction,
validate tool forces, or promote a two-dimensional result to 3D machining.
"""
from dataclasses import dataclass
from fractions import Fraction as F
from math import isfinite, isqrt, nextafter, inf


def q(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a coordinate")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("Finite coordinate required")
    return F(value)


def point(value):
    if len(value) != 2:
        raise ValueError("Two coordinates required")
    return tuple(q(v) for v in value)


def add(a, b): return (a[0]+b[0], a[1]+b[1])
def sub(a, b): return (a[0]-b[0], a[1]-b[1])
def mul(a, t): return (a[0]*t, a[1]*t)
def dot(a, b): return a[0]*b[0]+a[1]*b[1]


def sqrt_bounds(value, bits=48):
    """Exact rational enclosing bounds, with no floating arithmetic."""
    value = q(value)
    if value < 0:
        raise ValueError("Negative squared length")
    scale = 1 << bits
    k = isqrt(value.numerator * scale * scale // value.denominator)
    lo = F(k, scale)
    return lo, lo if lo*lo == value else F(k+1, scale)


@dataclass(frozen=True)
class Box:
    xmin: F
    ymin: F
    xmax: F
    ymax: F

    def __post_init__(self):
        for name in ("xmin", "ymin", "xmax", "ymax"):
            object.__setattr__(self, name, q(getattr(self, name)))
        if self.xmin > self.xmax or self.ymin > self.ymax:
            raise ValueError("Ordered stock box required")

    def corners(self):
        return ((self.xmin,self.ymin),(self.xmax,self.ymin),
                (self.xmax,self.ymax),(self.xmin,self.ymax))

    def intersection(self, other):
        a,b,c,d=max(self.xmin,other.xmin),max(self.ymin,other.ymin),min(self.xmax,other.xmax),min(self.ymax,other.ymax)
        return Box(a,b,c,d) if a <= c and b <= d else None

    def split(self):
        x,y=(self.xmin+self.xmax)/2,(self.ymin+self.ymax)/2
        if self.xmin == self.xmax and self.ymin == self.ymax:
            return [self]
        if self.xmin == self.xmax:
            return [Box(self.xmin,self.ymin,self.xmax,y),Box(self.xmin,y,self.xmax,self.ymax)]
        if self.ymin == self.ymax:
            return [Box(self.xmin,self.ymin,x,self.ymax),Box(x,self.ymin,self.xmax,self.ymax)]
        return [Box(self.xmin,self.ymin,x,y),Box(x,self.ymin,self.xmax,y),
                Box(self.xmin,y,x,self.ymax),Box(x,y,self.xmax,self.ymax)]


def segment_point_distance2(a, b, p):
    d=sub(b,a); den=dot(d,d)
    t=max(F(0),min(F(1),dot(sub(p,a),d)/den)) if den else F(0)
    e=sub(p,add(a,mul(d,t)))
    return dot(e,e)


def segment_intersects_box(a, b, box):
    lo,hi=F(0),F(1)
    for j,(low,high) in enumerate(((box.xmin,box.xmax),(box.ymin,box.ymax))):
        delta=b[j]-a[j]
        if not delta:
            if not low <= a[j] <= high: return False
        else:
            t0,t1=sorted(((low-a[j])/delta,(high-a[j])/delta))
            lo,hi=max(lo,t0),min(hi,t1)
            if lo > hi: return False
    return True


def segment_box_distance2(a, b, box):
    if segment_intersects_box(a,b,box): return F(0)
    def endpoint_distance(p):
        dx=max(box.xmin-p[0],F(0),p[0]-box.xmax)
        dy=max(box.ymin-p[1],F(0),p[1]-box.ymax)
        return dx*dx+dy*dy
    return min(endpoint_distance(a),endpoint_distance(b),
               *(segment_point_distance2(a,b,p) for p in box.corners()))


@dataclass(frozen=True)
class Capsule:
    a: tuple
    b: tuple
    radius: F

    def __post_init__(self):
        object.__setattr__(self,'a',point(self.a));object.__setattr__(self,'b',point(self.b))
        object.__setattr__(self,'radius',q(self.radius))
        if self.radius < 0: raise ValueError("Nonnegative capsule radius required")

    def bbox(self):
        return Box(min(self.a[0],self.b[0])-self.radius,min(self.a[1],self.b[1])-self.radius,
                   max(self.a[0],self.b[0])+self.radius,max(self.a[1],self.b[1])+self.radius)

    def excludes(self, box):
        return segment_box_distance2(self.a,self.b,box) > self.radius*self.radius

    def contains(self, box):
        # Capsule convexity makes all-corner containment sufficient for the whole box.
        return all(segment_point_distance2(self.a,self.b,p) <= self.radius*self.radius for p in box.corners())


@dataclass(frozen=True)
class Line:
    a: tuple
    b: tuple

    def __post_init__(self):
        object.__setattr__(self,'a',point(self.a));object.__setattr__(self,'b',point(self.b))
        if self.a == self.b: raise ValueError("Nonzero cutting line required")

    def at(self,t): return add(self.a,mul(sub(self.b,self.a),t))
    def capsules(self,lo,hi,radius):
        c=Capsule(self.at(lo),self.at(hi),radius)
        return c,c
    def projection(self,box,lo,hi,radius):
        d=sub(self.b,self.a);n=(-d[1],d[0]);length=sqrt_bounds(dot(d,d))
        if not length[0]: raise ValueError("Line too short for selected enclosing precision")
        values=[dot(n,sub(p,self.a)) for p in box.corners()]
        candidates=[v/l for v in (min(values),max(values)) for l in length]
        return min(candidates),max(candidates)


@dataclass(frozen=True)
class Arc:
    """Exact rational minor arc; q=tan(theta/2), not an unqualified CL adapter."""
    center: tuple
    radius: F
    unit_start: tuple
    q_start: F
    q_end: F

    def __post_init__(self):
        object.__setattr__(self,'center',point(self.center));object.__setattr__(self,'unit_start',point(self.unit_start))
        for name in ('radius','q_start','q_end'): object.__setattr__(self,name,q(getattr(self,name)))
        if self.radius <= 0 or dot(self.unit_start,self.unit_start) != 1:
            raise ValueError("Positive radius and exactly unit rational basis required")
        if not (-1 <= self.q_start <= 1 and -1 <= self.q_end <= 1) or self.q_start == self.q_end:
            raise ValueError("Bounded nonzero rational arc required")
        if dot(self.unit(0),self.unit(1)) < 0:
            raise ValueError("At most quarter-circle arc required")

    def unit(self,t):
        v=self.q_start+(self.q_end-self.q_start)*t
        co,si=(1-v*v)/(1+v*v),2*v/(1+v*v)
        a,b=self.unit_start
        return (a*co-b*si,a*si+b*co)
    def at(self,t): return add(self.center,mul(self.unit(t),self.radius))
    def capsules(self,lo,hi,radius):
        a,b=self.at(lo),self.at(hi);d=sub(a,b)
        # Chord/arc Hausdorff distance for a minor circular arc.
        sag=self.radius-sqrt_bounds(self.radius*self.radius-dot(d,d)/4)[0]
        return Capsule(a,b,radius+sag),Capsule(a,b,max(F(0),radius-sag)) if radius >= sag else None
    def projection(self,box,lo,hi,radius):
        t=(lo+hi)/2;u=self.unit(t);c=self.at(t)
        sign=-1 if self.q_end > self.q_start else 1
        n=mul(u,sign)
        delta2=max(dot(sub(self.unit(e),u),sub(self.unit(e),u)) for e in (lo,hi))
        delta=sqrt_bounds(delta2)[1]
        # For actual contact |x-c(t)|<=R: normal rotation error <=delta*R,
        # and |n_ref.(c(t)-c_ref)| = r*|u_ref.u(t)-1| <=r*delta^2/2.
        error=delta*radius+self.radius*delta*delta/2
        values=[dot(n,sub(p,c)) for p in box.corners()]
        return min(values)-error,max(values)+error


@dataclass
class Budget:
    max_cells: int = 50000
    max_intervals: int = 1024
    max_spatial_depth: int = 8
    max_temporal_depth: int = 8
    cells: int = 0
    intervals: int = 0

    def validate(self):
        for name in ('max_cells','max_intervals','max_spatial_depth','max_temporal_depth'):
            v=getattr(self,name)
            if type(v) is not int or v < 0: raise ValueError("Nonnegative integer budget required")
        if self.cells or self.intervals: raise ValueError("Fresh budget required")


def engagement_bound(low,high,radius):
    if low <= 0 <= high: return 2*radius
    if low > 0: return max(F(0),min(2*radius,radius-low))
    if high < 0: return max(F(0),min(2*radius,radius+high))
    return 2*radius


def interval_bound(motion,lo,hi,stock,removed,radius,limit,budget):
    outer,_=motion.capsules(lo,hi,radius)
    cells=[v for b in stock if (v:=b.intersection(outer.bbox())) is not None]
    last=2*radius
    for depth in range(budget.max_spatial_depth+1):
        contacts=[];projections=[]
        for box in cells:
            if budget.cells >= budget.max_cells:
                return False,last,'spatial_budget'
            budget.cells+=1
            if type(motion) is Line and not removed and segment_intersects_box(outer.a,outer.b,box):
                # A conservative early unresolved result; this never certifies
                # physical material presence or a load violation.
                return False,2*radius,'possible_centerline_contact'
            if outer.excludes(box) or any(c.contains(box) for c in removed): continue
            a,b=motion.projection(box,lo,hi,radius)
            a,b=max(-radius,a),min(radius,b)
            if a > b: continue
            contacts.append(box);projections.append((a,b))
        if not contacts: return True,F(0),'air_or_guaranteed_removed'
        last=engagement_bound(min(v[0] for v in projections),max(v[1] for v in projections),radius)
        if last <= limit: return True,last,'continuous_transverse_bound'
        if depth == budget.max_spatial_depth: return False,last,'spatial_depth'
        cells=[child for box in contacts for child in box.split()]
    raise AssertionError("unreachable")


def analyze(stock,motions,*,radius='0.4',ae_limit='0.016',stock_enclosure_qualified=False,budget=None):
    """Audit chronological CUTTING moves only; supplied model and authority stay separate."""
    radius,limit=q(radius),q(ae_limit)
    if not 0 < limit < 2*radius: raise ValueError("Positive radius and bounded engagement limit required")
    if type(stock_enclosure_qualified) is not bool: raise ValueError("Explicit stock authority flag required")
    if not isinstance(stock,(list,tuple)) or len(stock)>10000 or not all(type(b) is Box for b in stock):
        raise ValueError("Bounded exact stock-box union required")
    if not isinstance(motions,(list,tuple)) or not 0<len(motions)<=256 or not all(type(m) in (Line,Arc) for m in motions):
        raise ValueError("Bounded explicitly qualified cutting paths required")
    budget=budget or Budget();budget.validate();removed=[];leaves=[]
    def visit(m,index,lo,hi,depth):
        if budget.intervals >= budget.max_intervals:
            leaves.append({'motion_index':index,'lo':str(lo),'hi':str(hi),'proved':False,
                           'ae_upper_fraction':str(2*radius),'reason':'temporal_budget','credited_prior_intervals':len(removed)})
            return
        budget.intervals+=1
        ok,upper,reason=interval_bound(m,lo,hi,stock,removed,radius,limit,budget)
        if not ok and depth < budget.max_temporal_depth and budget.cells < budget.max_cells and budget.intervals < budget.max_intervals:
            mid=(lo+hi)/2
            visit(m,index,lo,mid,depth+1);visit(m,index,mid,hi,depth+1)
            return
        leaves.append({'motion_index':index,'lo':str(lo),'hi':str(hi),'proved':ok,
                       'ae_upper_fraction':str(upper),'reason':reason,'credited_prior_intervals':len(removed)})
        # Even an unresolved load interval cuts its nominal swept disc under this
        # geometric model; credit is added only after its audit, never to itself.
        _,under=m.capsules(lo,hi,radius)
        if under is not None: removed.append(under)
    for index,m in enumerate(motions): visit(m,index,F(0),F(1),0)
    proved=all(v['proved'] for v in leaves)
    upper=max(F(v['ae_upper_fraction']) for v in leaves)
    return {'scope':'CONTINUOUS_2D_TRANSVERSE_ENGAGEMENT_V1','mathematical_status':'PROVED' if proved else 'UNRESOLVED',
            'supplied_model_bound_proved':proved,'stock_enclosure_qualified':stock_enclosure_qualified,
            'qualified_2d_bound_proved':proved and stock_enclosure_qualified,
            'ae_upper_fraction':str(upper),'ae_upper_mm_outward':nextafter(float(upper),inf),
            'ae_limit_fraction':str(limit),'cell_checks':budget.cells,'interval_checks':budget.intervals,'intervals':leaves,
            'physical_stock_certified_by_kernel':False,'stock_authority_checked_by_kernel':False,
            'external_authorities_validated':False,'actual_CL_adapter_qualified':False,
            'three_dimensional_engagement_verified':False,'production_ready':False,
            'model_assumptions':['supplied stock boxes contain all material in this 2D section',
             'paths and cutter radius are exact in the supplied rational model',
             'previous cutting moves remove their nominal swept disc; no physical cutting failure modeled',
             'arc direction and plane are supplied, not inferred from CL']}
