"""Read-only conical chamfer CL review in an explicitly qualified axial frame.

The output separates continuous containment from arc serialization, cutter
reference and manufacturing acceptance. No CAD, compensation or mesh fitting.
"""
from copy import deepcopy
import math

TOL = 3e-6
TAU = 2*math.pi
SCOPE = 'AXIAL_CONICAL_CHAMFER_CL_REVIEW_V1'


def require(ok, message):
    if not ok: raise ValueError(message)


def semantic(value):
    omitted = {'line','block','start_line','end_line','endpoint_line',
        'circle_record_line','last_record_line'}
    if isinstance(value,dict):
        return {k:semantic(v) for k,v in value.items() if k not in omitted}
    return [semantic(v) for v in value] if isinstance(value,list) else value


def block_signature(parsed,index):
    block = parsed['operation_blocks'][index]
    return dict(commands=[c['raw'] for c in parsed['commands']
                          if block['start_line']<c['line']<block['end_line']],
        motions=semantic([m for m in parsed['motions'] if m['block']==index]),
        circles=semantic([c for c in parsed['circle_records'] if c['block']==index]))


def isolate_added_block(parsed, baseline, *, prior_native_ids, added_native_id):
    require(parsed['parse_complete'] is True and baseline['parse_complete'] is True
        and parsed['native_count_matches'] is True and baseline['native_count_matches'] is True,
        'Complete native-count-matched current and accepted baseline CL required')
    require(len(parsed['operation_blocks'])==4 and len(baseline['operation_blocks'])==3,
        'Exact four-current/three-preserved block context required')
    require(len(prior_native_ids)==3 and len(set(prior_native_ids+[added_native_id]))==4
        and all(type(v) is int and v>0 for v in prior_native_ids+[added_native_id]),
        'Explicit distinct authoritative operation IDs required')
    current=[block_signature(parsed,i) for i in range(4)]
    matches=[]
    for old in range(3):
        sig=block_signature(baseline,old)
        hits=[i for i,row in enumerate(current) if row==sig]
        require(len(hits)==1,'Prior block has no unique unchanged semantic match')
        matches.append(hits[0])
    require(len(set(matches))==3 and matches==sorted(matches),'Prior block identity/order ambiguous')
    residual=[i for i in range(4) if i not in matches]
    require(len(residual)==1,'Exactly one newly generated block required')
    return dict(added_block=residual[0],added_operation_native_id=added_native_id,
        unchanged=[dict(native_id=oid,old_block=i,new_block=matches[i])
                   for i,oid in enumerate(prior_native_ids)],
        basis='Unique complete command/motion/circle matches; labels are not native IDs')


def validate_context(c):
    required={'z_offset_mm','stock_floor_mm','stock_top_mm','cavity_radius_mm',
        'chamfer_bottom_mm','chamfer_top_radius_mm','tip_radius_mm','cone_height_mm',
        'cone_slope','noncutting_radius_mm','holder_min_tip_z_mm','target_axis_radius_mm',
        'target_tip_world_z_mm','expected_cutter_raw','frame_verified',
        'tool_reference_verified','arc_direction_semantics_verified',
        'coincident_full_turn_semantics_verified'}
    require(type(c) is dict and set(c)==required,'Exact explicit bounded geometry context required')
    for name in required-{'expected_cutter_raw','frame_verified','tool_reference_verified',
            'arc_direction_semantics_verified','coincident_full_turn_semantics_verified'}:
        require(type(c[name]) in (float,int) and math.isfinite(c[name]),'Finite geometry required')
    for name in ('frame_verified','tool_reference_verified','arc_direction_semantics_verified',
                 'coincident_full_turn_semantics_verified'):
        require(type(c[name]) is bool,'Strict qualification flags required')
    require(c['stock_floor_mm']<c['chamfer_bottom_mm']<c['stock_top_mm']
        and c['cone_slope']>0 and c['cone_height_mm']>0 and c['tip_radius_mm']>0
        and c['noncutting_radius_mm']>0 and c['holder_min_tip_z_mm']>0,
        'Positive cone and ordered target levels required')
    require(abs(c['chamfer_top_radius_mm']-c['cavity_radius_mm']-
        (c['stock_top_mm']-c['chamfer_bottom_mm'])*c['cone_slope'])<=TOL,
        'Chamfer target and physical cone slope differ')
    raw=c['expected_cutter_raw']
    require(type(raw) is list and len(raw)==7 and all(type(v) in (float,int)
        and math.isfinite(v) for v in raw),'Explicit finite CUTTER serialization required')


def void_radius(z,c,*,chamfer):
    if not chamfer or z<=c['chamfer_bottom_mm']:
        return c['cavity_radius_mm']
    return c['cavity_radius_mm']+(z-c['chamfer_bottom_mm'])*c['cone_slope']


def point_margin(radius,tip_z,c,*,chamfer):
    """Max cutter radius minus allowed void, over all intersected stock Z."""
    lo=max(tip_z,c['stock_floor_mm'])
    hi=min(tip_z+c['cone_height_mm'],c['stock_top_mm'])
    if hi<lo: return None
    zs={lo,hi}
    if lo<=c['chamfer_bottom_mm']<=hi:zs.add(c['chamfer_bottom_mm'])
    return max(radius+c['tip_radius_mm']+(z-tip_z)*c['cone_slope']-
        void_radius(z,c,chamfer=chamfer) for z in zs)


def line_envelope(a,b,c,*,chamfer):
    # In each cell split by stock levels and cutter endpoints the margin is a
    # convex norm plus an affine function. Its maximum lies at a cell vertex.
    ts={0.,1.}
    dz=b[2]-a[2]
    if dz:
        for level in (c['stock_floor_mm'],c['chamfer_bottom_mm'],c['stock_top_mm']):
            for delta in (0.,c['cone_height_mm']):
                t=(level-a[2]-delta)/dz
                if 0<t<1:ts.add(t)
    values=[]
    for t in sorted(ts):
        p=[a[i]+t*(b[i]-a[i]) for i in range(3)]
        margin=point_margin(math.hypot(p[0],p[1]),p[2],c,chamfer=chamfer)
        if margin is not None:values.append(dict(parameter=t,margin_mm=margin,point_mm=p))
    worst=max(values,key=lambda v:v['margin_mm']) if values else None
    return dict(maximum_margin_mm=worst['margin_mm'] if worst else None,worst=worst,
        containment_proved=worst is None or worst['margin_mm']<=TOL,
        method='Exact convex-cell endpoint maximum for a linear axis path')


def merge_angles(intervals):
    out=[]
    for a,b in sorted(intervals):
        if out and a<=out[-1][1]+1e-9:out[-1][1]=max(out[-1][1],b)
        else:out.append([a,b])
    return out


def arc_intervals(circle):
    """Conventional directed single sweep; caller must qualify serialization."""
    a=math.atan2(circle['start_raw'][1],circle['start_raw'][0])%TAU
    b=math.atan2(circle['endpoint_raw'][1],circle['endpoint_raw'][0])%TAU
    if circle['coincident_endpoints']:return [[0.,TAU]]
    if circle['direction_token']=='CLOCKWISE':a,b=b,a
    length=(b-a)%TAU
    require(length>1e-12,'Degenerate noncoincident directed arc')
    return [[a,a+length]] if a+length<=TAU else [[a,TAU],[0.,a+length-TAU]]


def review_block(parsed, block, c):
    validate_context(c)
    require(parsed['parse_complete'] is True and parsed['native_count_matches'] is True
        and parsed['declared_units']==['MM'],'Complete count-matched millimetre CL required')
    moves=[m for m in parsed['motions'] if m['block']==block]
    circles={r['endpoint_line']:r for r in parsed['circle_records'] if r['block']==block}
    require(len(moves)>=2,'At least two motions in the uniquely associated new block required')
    issues=[];rows=[];coverage=[];unresolved=[];min_tip=float('inf')
    for m in moves:
        require(m['axis_raw']==[0.,0.,1.] and m['cutter_raw']==c['expected_cutter_raw']
            and all(math.isfinite(x) for x in m['xyz']),'Exact axial tool and CUTTER record required')
        require(m['cutcom_state']['status'] in ('not_declared','off')
            and all(r['angle_raw']==0 for r in m['rotabl_records_before_motion']),
            'Active CUTCOM or rotated frame is not supported')
        require(m['mode'] in ('rapid','feed'),'Explicit feed or rapid required')
    for a,b in zip(moves,moves[1:]):
        p=list(a['xyz']);q=list(b['xyz'])
        p[2]+=c['z_offset_mm'];q[2]+=c['z_offset_mm']
        min_tip=min(min_tip,p[2],q[2])
        row=dict(from_line=a['line'],to_line=b['line'],mode=b['mode'],
                 start_world_mm=p,end_world_mm=q)
        circle=circles.get(b['line'])
        if circle:
            require(circle.get('endpoint_validated') is True
                and circle.get('motion_kind')!='axial_helix'
                and circle['normal_raw']==[0.,0.,1.] and abs(p[2]-q[2])<=TOL,
                'Only planar +Z circle loci are bounded by this reviewer')
            radius_bound=math.hypot(*circle['center_raw'][:2])+circle['radius_raw']
            margin=point_margin(radius_bound,p[2],c,chamfer=b['mode']=='feed')
            row.update(kind='planar_circle_locus',maximum_margin_mm=margin,
                containment_proved=margin is None or margin<=TOL,
                method='Conservative complete circular locus, independent of turn count')
            on_target=math.hypot(*circle['center_raw'][:2])<=TOL and abs(
                circle['radius_raw']-c['target_axis_radius_mm'])<=TOL and abs(
                p[2]-c['target_tip_world_z_mm'])<=TOL
            if b['mode']=='feed' and on_target:
                coverage.extend(arc_intervals(circle))
                if not c['arc_direction_semantics_verified']:unresolved.append('arc_direction_serialization')
                if circle['coincident_endpoints'] and not c['coincident_full_turn_semantics_verified']:
                    unresolved.append('coincident_circle_turn_count')
        else:
            row.update(kind='line',**line_envelope(p,q,c,chamfer=b['mode']=='feed'))
            if b['mode']=='feed' and q[2]<p[2]-TOL:
                raw=line_envelope(p,q,c,chamfer=False)
                if not raw['containment_proved']:
                    issues.append(dict(line=b['line'],kind='axial_cutting_ability_unverified'))
        if b['mode']=='rapid' and row['maximum_margin_mm'] is not None and row['maximum_margin_mm']>=-TOL:
            row['containment_proved']=False
            issues.append(dict(line=b['line'],kind='positive_rapid_clearance_not_proved'))
        if not row['containment_proved']:
            issues.append(dict(line=b['line'],kind='stock_containment_not_proved',
                               margin_mm=row['maximum_margin_mm']))
        rows.append(row)
    if min_tip<c['stock_floor_mm']-TOL:issues.append(dict(kind='cutter_below_cavity_floor'))
    shank_gap=min_tip+c['cone_height_mm']-c['stock_top_mm']
    holder_gap=min_tip+c['holder_min_tip_z_mm']-c['stock_top_mm']
    if shank_gap<=0:issues.append(dict(kind='noncutting_body_axial_separation_not_proved'))
    if holder_gap<=0:issues.append(dict(kind='holder_axial_separation_not_proved'))
    merged=merge_angles(coverage)
    full=bool(merged and len(merged)==1 and merged[0][0]<=1e-9 and merged[0][1]>=TAU-1e-9)
    if not full:unresolved.append('complete_360_degree_cut_coverage')
    if not c['frame_verified']:unresolved.append('fixed_world_frame')
    if not c['tool_reference_verified']:unresolved.append('CUTTER_tip_reference')
    # The first CL location has no incoming path in this block; only its pose
    # and subsequent moves are checked. Inter-operation travel remains explicit.
    unresolved.append('incoming_inter_operation_path')
    return dict(scope=SCOPE,status='review_required',native_calls=0,
        segments=rows,continuous_containment_proved=not issues,
        issues=issues,unverified=sorted(set(unresolved)),
        candidate_coverage_intervals_radians=merged,candidate_full_360=full,
        full_360_verified=full and not any(x in unresolved for x in (
            'arc_direction_serialization','coincident_circle_turn_count')),
        minimum_tip_world_z_mm=min_tip,noncutting_axial_gap_mm=shank_gap,
        holder_axial_gap_mm=holder_gap,
        geometry_acceptance_complete=False,production_qualified=False,
        nominal_math_only=not(c['frame_verified'] and c['tool_reference_verified']),
        limitations=['Physical tolerances, runout, real grip and fixtures are not qualified.',
            'WIP tessellation is not proof of this chamfer.',
            'Circle safety uses a full locus; a failed bound is not proof of a real collision.',
            'Tool-body and holder bounds use positive axial separation; no inferred offset is added.'])


