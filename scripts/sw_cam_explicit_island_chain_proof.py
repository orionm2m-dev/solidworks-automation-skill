"""Pure indexed-profile proof; caller owns pinned CAD placement/association.
No native calls, world-frame fit, enum interpretation or machining acceptance.
"""
import math
TOL_MM=1e-6

def require(ok,message):
    if not ok:raise ValueError(message)
def num(v):
    require(type(v)in(int,float)and math.isfinite(v),'Finite strict number required');return float(v)
def point(v):
    require(type(v)in(list,tuple)and len(v)==3,'Three coordinates required');return tuple(num(x)for x in v)
def near(a,b):return math.dist(a,b)<=TOL_MM
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def normal(v):
    n=point(v);require(abs(n[0])<=1e-12 and abs(n[1])<=1e-12 and abs(abs(n[2])-1)<=1e-12,'Axial normal required')
def integer(v,n):return type(v)is int and v==n

def sequence(rows,observed):
    require(type(rows)is list and len(rows)==4,'Exactly four curves required');out=[]
    for i,r in enumerate(rows):
        if observed:
            require(integer(r['index'],i)and r['read_complete']is True,'Complete ordered curves required')
            require(type(r['curve_type'])is int and r['curve_type']in(0,1),'Line/arc only')
            kind='arc'if r['curve_type']==1 else'line';a,b=point(r['start_native']),point(r['end_native'])
            mid=point(r['mid_native'])if kind=='arc'else tuple((x+y)/2 for x,y in zip(a,b))
            c=point(r['centre_native'])if kind=='arc'else None;radius=num(r['radius_native'])if kind=='arc'else None
            if kind=='arc':normal(r['normal_native'])
        else:
            kind=r['kind'];require(kind in('line','arc'),'Signed line/arc only')
            a,b,mid=(point(r[k])for k in('start_model_mm','end_model_mm','mid_model_mm'))
            c=point(r['center_model_mm'])if kind=='arc'else None;radius=num(r['radius_mm'])if kind=='arc'else None
        require(math.dist(a,b)>TOL_MM,'Nonzero edge required')
        item=dict(kind=kind,start=a,end=b,mid=mid,center=c,radius=radius)
        if kind=='arc':
            require(radius>TOL_MM and all(abs(math.dist(p,c)-radius)<=TOL_MM for p in(a,b,mid)),'Arc points/radius differ')
            require(all(abs(p[2]-c[2])<=TOL_MM for p in(a,b,mid)),'Nonplanar arc')
            va,vm,vb=(sub(p,c)for p in(a,mid,b))
            half=[math.atan2(x[0]*y[1]-x[1]*y[0],x[0]*y[0]+x[1]*y[1])for x,y in((va,vm),(vm,vb))];sweep=sum(half)
            require(half[0]*half[1]>0 and 0<abs(sweep)<math.pi,'Simple minor arc with interior midpoint required')
            if not observed:require(abs(num(r['sweep_radians'])-sweep)*radius<=TOL_MM,'Signed sweep differs')
            item['length']=abs(sweep)*radius
        else:
            require(near(mid,tuple((x+y)/2 for x,y in zip(a,b))),'Line midpoint differs');item['length']=math.dist(a,b)
        out.append(item)
    require(sum(x['kind']=='arc'for x in out)==2,'Two arcs/two lines required')
    require(all(near(out[i]['end'],out[(i+1)%4]['start'])for i in range(4)),'Closed ordered chain required')
    arcs=[x for x in out if x['kind']=='arc'];center=arcs[0]['center']
    require(near(center,arcs[1]['center'])and abs(arcs[0]['radius']-arcs[1]['radius'])>TOL_MM,'Concentric distinct radii required')
    for x in out:
        for key in('start','end','mid'):
            require(abs(x[key][2]-center[2])<=TOL_MM,'Planar profile required');x[key]=sub(x[key],center)
    lines=[x for x in out if x['kind']=='line'];d=[sub(x['end'],x['start'])for x in lines]
    require(abs(d[0][0]*d[1][1]-d[0][1]*d[1][0])<=TOL_MM*min(x['length']for x in lines),'Parallel sides required')
    return out

def match(a,b):
    return a['kind']==b['kind']and all(near(a[k],b[k])for k in('start','end','mid'))and abs(a['length']-b['length'])<=TOL_MM and(a['kind']=='line'or abs(a['radius']-b['radius'])<=TOL_MM)
def curves(row,count):
    c=row['contour'];require(c['status']=='observed'and integer(c['declared_chain_count'],1)and len(c['chains'])==1,'One observed chain required');c=c['chains'][0]
    require(integer(c['index'],0)and c['read_complete']is True and integer(c['declared_curve_count'],count)and len(c['curves'])==count,'Complete bounded curves required');return c['curves']

def verify_indexed(observed,outer_spec,island_specs,*,length_scale_to_mm):
    require(type(length_scale_to_mm)in(int,float)and num(length_scale_to_mm)==1.,'Explicit scoped scale1 required')
    require(type(island_specs)is list and len(island_specs)==4,'Four signed islands required')
    specs=[outer_spec]+island_specs;wanted=[s['sketch_name']for s in specs]
    require(all(type(n)is str and 0<len(n)<=1024 for n in wanted)and len({n.casefold()for n in wanted})==5,'Five distinct exact names required')
    h=observed['headers'];require(observed['read_complete']is True and h['read_complete']is True and h['profile_headers_read_complete']is True,'Complete headers/profile required')
    require(integer(h['shape'],2)and integer(h['island_count'],4)and integer(h['sketch_count'],5),'Exact profile classification required')
    n=h['sketch_names'];require(n['value']==wanted and integer(n['observed_name_count'],5)and n['matches_sketch_count']is True,'Exact five ordered names required')
    rows=observed['indexed_chains'];require(type(rows)is list and len(rows)==5,'Exactly five indexed profiles required')
    for i,(r,name)in enumerate(zip(rows,wanted)):
        require(integer(r['native_index'],i)and r['expected_sketch_name']==name and r['name_matches']is True and r['segment_chain_read_attempted']is True and r['read_complete']is True,'Complete indexed name binding required')
        n=r['name_observation'];require(n['value']==[name]and integer(n['observed_name_count'],1)and n['matches_sketch_count']is True,'Actual per-index name differs')
    circle=curves(rows[0],1)[0];e=outer_spec['profile']
    require(e['kind']=='circle'and integer(circle['index'],0)and integer(circle['curve_type'],2)and circle['read_complete']is True,'Outer single circle required')
    point(e['center_model_mm']);point(circle['centre_native']);normal(circle['normal_native']);radius=num(e['radius_mm'])
    require(radius>TOL_MM and abs(num(circle['radius_native'])-radius)<=TOL_MM,'Outer radius differs')
    results=[]
    for row,spec in zip(rows[1:],island_specs):
        require(spec['profile']['kind']=='closed_mixed','Signed mixed profile required')
        a=sequence(curves(row,4),True);b=sequence(spec['profile']['segments'],False)
        reverse=[dict(x,start=x['end'],end=x['start'])for x in reversed(a)]
        matches=[(rev,k)for rev,seq in((False,a),(True,reverse))for k in range(4)if all(match(seq[(i+k)%4],b[i])for i in range(4))]
        require(len(matches)==1,'Relative island geometry differs or ambiguous')
        lines=[x for x in a if x['kind']=='line']
        results.append(dict(native_index=row['native_index'],sketch_name=spec['sketch_name'],radii_mm=sorted(x['radius']for x in a if x['kind']=='arc'),line_distances_from_arc_center_mm=[abs(x['start'][0]*x['end'][1]-x['start'][1]*x['end'][0])/x['length']for x in lines],curve_lengths_mm=[x['length']for x in a],traversal_reversed=matches[0][0],cyclic_shift=matches[0][1]))
    return dict(scope='EXPLICIT_NAMED_ISLAND_INDEXED_RELATIVE_SHAPE_PROOF_V1',indexed_chain_binding_verified=True,names=wanted,outer_radius_mm=radius,islands=results,length_scale_to_mm=1.,absolute_tolerance_mm=TOL_MM,relative_profile_geometry_verified=True,rotation_or_reflection_fitted=False,world_placement_verified=False,axial_semantics_verified=False,universal_native_units_verified=False,machining_eligible=False,production_qualified=False,limitations=['Caller binds immutable specs, native CAD model-coordinate sketch proof and actual feature association.','CAM local centres and heights are not mapped to world; only same-axis relative shapes are compared.','Raw native sense/direction enums are not interpreted; simple minor geometry is constrained by actual start/mid/end.'])
