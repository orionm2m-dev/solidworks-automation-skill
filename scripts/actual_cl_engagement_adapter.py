"""Actual CL prefix to conservative cylindrical removal for engagement queries.

The exact exported-coordinate model is used. No WIP mesh, unknown arc sweep,
rapid move, future motion or unobserved tool profile receives removal credit.
"""
from fractions import Fraction as F
import math
import continuous_radial_engagement as k


def require(ok,message):
    if not ok: raise ValueError(message)


def number(v):
    require(type(v) in (int,float,str,F), 'Numeric coordinate required')
    if type(v) is float: require(math.isfinite(v),'Finite coordinate required')
    return F(str(v)) if type(v) is float else F(v)


def xyz(v,z_offset=0):
    require(type(v) in (list,tuple) and len(v)==3,'Three coordinates required')
    p=tuple(number(x)for x in v)
    return p[0],p[1],p[2]+number(z_offset)


def eligible_motion(m,profile):
    require(m.get('mode')in ('rapid','feed'),'Known CL mode required')
    require(xyz(m['axis_raw'])==(0,0,1),'Qualified positive-Z CL axis required')
    require(m.get('cutcom_state',{}).get('status')=='not_declared','No compensation allowed')
    for row in m.get('rotabl_records_before_motion',[]):
        require(number(row['angle_raw'])==0 and row['tokens'][0]in ('AAXIS','BAXIS','CAXIS')
                and row['tokens'][1]=='TABLE' and row['tokens'][2]in ('CLW','CCLW'),'Only zero table rotations allowed')
    c=[number(v)for v in m['cutter_raw']]
    require(len(c)==7 and c[0]==2*number(profile['radius_mm']) and c[1]==0
            and c[2]==number(profile['radius_mm']) and c[3:6]==[0,0,0] and c[6]==number(profile['overall_length_mm']),
            'Actual CL flat cutter diameter/end radius/OAL differs from observed profile')
    require(0<number(profile['cutting_length_mm'])<=number(profile['overall_length_mm']) and number(profile['radius_mm'])>0,'Positive observed cutting cylinder required')


def collect_events(parsed,profiles,*,z_offset=26):
    require(parsed.get('parse_complete')is True and parsed.get('native_count_matches')is True
            and parsed.get('declared_units')==['MM'],'Complete counted metric CL required')
    require(type(profiles)is dict and all(type(b)is int and b>=0 for b in profiles),'Explicit native-bound profile map required')
    events=[];previous=None;lastline=0;skipped=set()
    for m in parsed['motions']:
        require(type(m['line'])is int and m['line']>lastline,'Strict chronological CL line order required');lastline=m['line']
        b=m['block'];p=profiles.get(b)
        if p is not None:
            eligible_motion(m,p)
            if m['mode']=='feed':
                a=xyz(previous['xyz'],z_offset) if previous and previous['block']==b else None
                end=xyz(m['xyz'],z_offset)
                events.append(dict(line=m['line'],block=b,operation_native_id=p['operation_native_id'],
                    tool_native_id=p['tool_native_id'],a=a,b=end,radius=number(p['radius_mm']),
                    loc=number(p['cutting_length_mm']),circle=m.get('circle_record_line') is not None))
        else:skipped.add(b)
        previous=m
    return events,sorted(skipped)


def clip_tip_range(a,b,low,high):
    """Exact t range where the cutter covers every height of the query band."""
    if low>high:return None
    dz=b[2]-a[2]
    if dz==0:return (F(0),F(1)) if low<=a[2]<=high else None
    t0,t1=sorted(((low-a[2])/dz,(high-a[2])/dz))
    lo,hi=max(F(0),t0),min(F(1),t1)
    return (lo,hi) if lo<=hi else None


def lerp(a,b,t):return tuple(a[i]+(b[i]-a[i])*t for i in range(3))


def guaranteed_prefix(events,*,before_line,z_band,window=None,guard='0.00002'):
    """Return only capsules common to the complete supplied height band."""
    require(type(before_line)is int and before_line>0,'Explicit target CL line required')
    require(len(z_band)==2,'Two band limits required');zlo,zhi=map(number,z_band)
    require(zlo<=zhi,'Ordered cutting-height band required');g=number(guard);require(g>=0,'Nonnegative erosion guard required')
    unique={};origins={};endpoint_count=line_count=0
    def keep(c,e,kind):
        nonlocal endpoint_count,line_count
        if window is not None and c.excludes(window):return
        key=(min(c.a,c.b),max(c.a,c.b),c.radius)
        if key not in unique:
            unique[key]=c;origins[key]=dict(block=e['block'],line=e['line'],operation_native_id=e['operation_native_id'],kind=kind)
            if kind=='completed_endpoint_disc':endpoint_count+=1
            else:line_count+=1
    for e in events:
        if e['line']>=before_line:break
        radius=e['radius']-g
        if radius<=0:continue
        low,high=zhi-e['loc']+g,zlo-g
        if low<=e['b'][2]<=high:
            keep(k.Capsule(e['b'][:2],e['b'][:2],radius),e,'completed_endpoint_disc')
        if e['a'] is None or e['circle']:continue
        t=clip_tip_range(e['a'],e['b'],low,high)
        if t is None:continue
        a,b=lerp(e['a'],e['b'],t[0]),lerp(e['a'],e['b'],t[1])
        keep(k.Capsule(a[:2],b[:2],radius),e,'completed_straight_sweep')
    return list(unique.values()),{'unique_capsules':len(unique),'straight_capsules':line_count,'endpoint_discs':endpoint_count,
        'maximum_credited_line':max((r['line']for r in origins.values()),default=None),'before_line':before_line,
        'z_band_mm':[str(zlo),str(zhi)],'erosion_guard_mm':str(g),'sources':list(origins.values()),
        'unknown_arc_sweeps_credited':False,'rapid_sweeps_credited':False,'future_credit':False}



class BandBudgetExhausted(RuntimeError):
    pass


class PrefixIndex:
    """Cache band geometry while keeping the earliest completion line per capsule."""
    def __init__(self,events,guard='0.00002'):
        require(type(events)is list and all(events[i]['line']<events[i+1]['line']for i in range(len(events)-1)),
                'Strict chronological events required')
        self.events=events;self.guard=number(guard);self.cache={}
        require(self.guard>=0,'Nonnegative erosion guard required')
    def query(self,*,before_line,z_band,window):
        require(type(before_line)is int and before_line>0 and type(window)is k.Box,'Bounded query identity required')
        band=tuple(map(number,z_band));require(len(band)==2 and band[0]<=band[1],'Ordered Z band required')
        if band not in self.cache:
            if len(self.cache)>=128:raise BandBudgetExhausted('At most128 distinct cutting bands per index')
            end=max((e['line']for e in self.events),default=0)+1
            caps,proof=guaranteed_prefix(self.events,before_line=end,z_band=band,guard=self.guard)
            self.cache[band]=[(c,c.bbox(),origin)for c,origin in zip(caps,proof['sources'])]
        selected=[(c,origin)for c,box,origin in self.cache[band]
                  if origin['line']<before_line and box.intersection(window)is not None and not c.excludes(window)]
        origins=[v[1]for v in selected]
        return [v[0]for v in selected],{'unique_capsules':len(selected),'before_line':before_line,
            'maximum_credited_line':max((v['line']for v in origins),default=None),
            'z_band_mm':list(map(str,band)),'erosion_guard_mm':str(self.guard),'sources':origins,
            'future_credit':False,'unknown_arc_sweeps_credited':False,'rapid_sweeps_credited':False,
            'band_cache_is_geometry_only_filtered_by_actual_completion_line':True}


def checked_interval(motion,removed,*,radius='0.4',limit='0.016',max_cells=20000,max_spatial_depth=8):
    radius,limit=number(radius),number(limit)
    require(type(motion)in (k.Line,k.Arc) and radius>0 and 0<limit<2*radius,'Supported bounded engagement query required')
    require(type(removed)is list and len(removed)<=100000 and all(type(v)is k.Capsule for v in removed),'Bounded guaranteed previous capsules required')
    budget=k.Budget(max_cells=max_cells,max_intervals=1,max_spatial_depth=max_spatial_depth,max_temporal_depth=0)
    budget.validate()
    outer,_=motion.capsules(F(0),F(1),radius)
    # Completely filled local query box is an over-approximation of ANY initial
    # stock that could contact this interval. No mesh accuracy premise is used.
    stock=[outer.bbox()]
    relevant=[c for c in removed if not c.excludes(stock[0])]
    ok,upper,reason=k.interval_bound(motion,F(0),F(1),stock,relevant,radius,limit,budget)
    return {'nominal_model_proved':ok,'ae_upper_fraction':str(upper),'reason':reason,'cell_checks':budget.cells,
        'prefix_capsules_used':len(relevant),'initial_stock':'entire_outer_query_box_solid',
        'unqualified_mesh_used':False,'physical_qualification':False,'actual_arc_sense_required':False}


def full_circle_queries(center,radius):
    radius=number(radius);require(radius>0,'Positive reported circle radius required')
    return [k.Arc(tuple(map(number,center)),radius,u,0,1)for u in ((1,0),(0,1),(-1,0),(0,-1))]


def review_full_circle(center,circle_radius,removed,**kw):
    """All quadrant queries use the SAME previous prefix: never clear an assumed circle."""
    rows=[checked_interval(m,removed,**kw)for m in full_circle_queries(center,circle_radius)]
    return {'nominal_model_proved':all(r['nominal_model_proved']for r in rows),
        'ae_upper_fraction':str(max(F(r['ae_upper_fraction'])for r in rows)),'quadrants':rows,
        'arc_direction_inferred':False,'full_circle_removal_credited':False,
        'bound_domain':'all positions and either direction of the reported circular locus'}


def query_actual_motion(parsed,motion,previous,events,*,target_profile,motion_index,z_offset=26,max_cells=20000,prefix_index=None):
    """Audit one real feed record; caller retains unresolved and all actual records."""
    require(type(motion_index)is int and 0<motion_index<len(parsed['motions'])
            and parsed['motions'][motion_index]==motion and parsed['motions'][motion_index-1]==previous,
            'Exact adjacent parsed motion positions required')
    require(motion['mode']=='feed','Only cutting feed engagement queries accepted')
    eligible_motion(motion,target_profile)
    require(previous is not None and previous['line']<motion['line'],'Explicit real previous CL position required')
    a,b=xyz(previous['xyz'],z_offset),xyz(motion['xyz'],z_offset)
    R,loc=number(target_profile['radius_mm']),number(target_profile['cutting_length_mm'])
    band=(min(a[2],b[2]),max(a[2],b[2])+loc)
    circleline=motion.get('circle_record_line')
    if circleline is None:
        if a[:2]==b[:2]:return {'status':'UNRESOLVED','reason':'vertical_axial_entry_not_a_transverse_cut','line':motion['line']}
        geometry=k.Line(a[:2],b[:2]);outer,_=geometry.capsules(F(0),F(1),R);window=outer.bbox()
    else:
        matches=[c for c in parsed['circle_records']if c['line']==circleline]
        require(len(matches)==1,'Unique actual circle binding required');c=matches[0]
        require(c.get('endpoint_validated')is True and c['endpoint_line']==motion['line']
                and c['start_line']==previous['line'] and c['block']==motion['block'],'Actual adjacent circle binding required')
        normal=xyz(c['normal_raw']);require(normal[:2]==(0,0)and abs(normal[2])==1,'Qualified axial circle required')
        center=xyz(c['center_raw'],z_offset)[:2];rad=number(c['radius_raw'])
        require(rad>0,'Positive circle radius required')
        window=k.Box(center[0]-rad-R,center[1]-rad-R,center[0]+rad+R,center[1]+rad+R)
        # For the existing parser the helix envelope contains complete Z bounds.
        key='helical_envelope_bounds_raw' if c.get('motion_kind')=='axial_helix' else 'full_circle_locus_bounds_raw'
        bounds=c[key];lo,hi=xyz(bounds[0],z_offset),xyz(bounds[1],z_offset)
        band=(min(band[0],lo[2]),max(band[1],hi[2]+loc))
    if prefix_index is None:
        removed,proof=guaranteed_prefix(events,before_line=motion['line'],z_band=band,window=window)
    else:
        require(type(prefix_index)is PrefixIndex and prefix_index.events is events,'Exact event index required')
        try:
            removed,proof=prefix_index.query(before_line=motion['line'],z_band=band,window=window)
        except BandBudgetExhausted:
            return {'status':'UNRESOLVED','reason':'height_band_cache_budget','line':motion['line'],'block':motion['block'],
                'production_qualified':False}
    value=checked_interval(geometry,removed,radius=R,max_cells=max_cells)if circleline is None else review_full_circle(center,rad,removed,radius=R,max_cells=max_cells)
    return {'status':'PROVED_NOMINAL_EXPORTED_COORDINATE_MODEL'if value['nominal_model_proved']else'UNRESOLVED',
        'line':motion['line'],'block':motion['block'],'z_band_mm':list(map(str,band)),
        'query':value,'prefix':proof,'real_machine_stock_verified':False,'production_qualified':False,
        'scope':'complete cylindrical cutting-height union band; holder/body and axial entry checked separately',
        'actual_block_native_mapping_verified':False,'CL_coordinate_error_enclosure_verified':False}
