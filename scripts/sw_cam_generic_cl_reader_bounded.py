"""Pure bounded reader for up to 200000 ordered MILL generic CL records.

The original grammar and raw-data interpretation remain unchanged. This module
performs no file writes, native calls, coordinate transforms or machining approval.
The explicit per-block bound and legacy-count contract remain 100000 records.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import math
import re

MAX_TOTAL_RECORDS = 200000
MAX_TEXT_LINES = 200100

SCOPE="OBSERVED_MILL_GENERIC_CL_RAW_READER_V1"
NUM=re.compile(r"[+-]?(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)(?:[Ee][+-]?[0-9]+)?\Z")
KNOWN={"UNITS","BOX","CUTTER","TLAXIS","OPFEATSTART","OPFEATEND","ROTABL","RAPID","GOTO","CIRCLE","FEDRAT","MOVE_ATTRIB","CUTCOM","FINI"}


def require(value, message):
    if not value:
        raise ValueError(message)


def _record_counts(value):
    if (type(value) is not list or not 1 <= len(value) <= 32
            or any(type(n) is not int or not 0 <= n <= 100000 for n in value)
            or not 0 < sum(value) <= 100000):
        raise ValueError('Exact bounded positive-total native record counts required')
    return value


def initial_cutcom_state():
    return dict(status="not_declared",enabled=None,side=None,last_record_line=None,
        coordinate_offset_applied=False,physical_effect_verified=False)


def transition_cutcom(previous,token,line):
    """Observe only ON -> LEFT/RIGHT -> OFF; never calculate a cutter offset."""
    require(token in {"ON","LEFT","RIGHT","OFF"},"Unsupported CUTCOM fields; explicit observed token required")
    state=deepcopy(previous)
    if token=="ON":
        require(previous["status"] in {"not_declared","off"},"CUTCOM ON requires a closed or undeclared sequence")
        state.update(status="enabled_without_side",enabled=True,side=None)
    elif token in {"LEFT","RIGHT"}:
        require(previous["status"]=="enabled_without_side","CUTCOM side requires preceding ON without intervening motion")
        state.update(status="active",enabled=True,side=token)
    else:
        require(previous["status"]=="active","CUTCOM OFF requires an active explicit side")
        state.update(status="off",enabled=False,side=None)
    state["last_record_line"]=line
    return state


def classify_planar_circle_sweep(circle,previous_circle=None):
    """Keep coincident endpoints unresolved; repetition alone proves no turn count."""
    coincident=circle["coincident_endpoints"]
    same_geometry=bool(previous_circle and previous_circle.get("endpoint_validated")
        and previous_circle.get("block")==circle["block"]
        and previous_circle.get("endpoint_line")==circle["start_line"]
        and all(previous_circle.get(k)==circle.get(k) for k in ("center_raw","normal_raw","radius_raw","direction_token")))
    return dict(sweep_classification="coincident_planar_circle_unqualified" if coincident else "noncoincident_planar_arc",
        preceding_same_circle_geometry=same_geometry,full_circle_qualified=False,turn_count=None,
        sweep_angle_interpreted=False,
        sweep_evidence_required="Coincident start/end plus repeated CIRCLE is a full-turn candidate; no vendor serialization or native sweep evidence is supplied." if coincident else None)


def numbers(text,count=None,trailing=False):
    tokens=[t.strip() for t in text.split(',')]
    if trailing and tokens[-1:]==['']:tokens=tokens[:-1]
    require(tokens and all(NUM.fullmatch(t) for t in tokens),"Strict finite numeric fields required")
    values=[float(t) for t in tokens]
    require(all(math.isfinite(v) for v in values),"Finite values required")
    require(count is None or len(values)==count,"Unexpected numeric field count")
    return values


def bounds(points):
    return [[min(p[i] for p in points) for i in range(3)],[max(p[i] for p in points) for i in range(3)]] if points else None


def validate_axial_helix_endpoint(circle,endpoint,axis,*,coordinate_quantum=None):
    """Observed descending +Z/CCW minor-arc dialect; no hidden-turn inference."""
    start=circle["start_raw"];center=circle["center_raw"];radius=circle["radius_raw"]
    require(max(abs(a-b) for a,b in zip(circle["normal_raw"],[0.,0.,1.]))<=1e-8
        and max(abs(a-b) for a,b in zip(axis,[0.,0.,1.]))<=1e-8,
        "Only observed axial +Z helical normal/tool axis supported")
    require(circle["direction_token"]=="COUNTERCLOCKWISE","Only observed CCW helix supported")
    require(abs(start[2]-center[2])<=1e-5,"Helix center Z must equal start Z")
    dz=endpoint[2]-start[2];require(dz < -1e-5,"Only observed descending helix supported")
    vectors=[[p[i]-center[i] for i in (0,1)] for p in (start,endpoint)]
    require(all(abs(math.hypot(*v)-radius)<=1e-5 for v in vectors),"Projected helix endpoint radius differs")
    a,b=vectors;angle=math.atan2(a[0]*b[1]-a[1]*b[0],a[0]*b[0]+a[1]*b[1])
    if angle<0:angle+=2*math.pi
    quantized_antipodal = angle > math.pi + 1e-8
    antipodal_residual = math.hypot(a[0]+b[0],a[1]+b[1])
    if quantized_antipodal:
        # Each rounded XY coordinate is within q/2 of its source value. Thus
        # start+end-2*center has at most 2*q error per coordinate. This permits
        # only the observed half-turn boundary, never an arbitrary major arc.
        require(coordinate_quantum == 1e-6,"Major helix needs exact observed six-decimal coordinate serialization")
        bound = 2*math.sqrt(2)*coordinate_quantum
        require(antipodal_residual <= bound and all(abs(math.hypot(*v)-radius) <= (math.sqrt(2)+.5)*coordinate_quantum for v in vectors),
            "Helix exceeds rounded antipodal coordinate bound")
        angular_bound = 2*math.asin(min(1.,bound/(2*min(math.hypot(*v) for v in vectors))))
        require(angle-math.pi <= angular_bound,"Helix exceeds rounded half-turn angle bound")
    else:
        require(1e-8<angle<=math.pi+1e-8,"Only observed positive CCW minor arcs supported")
    pitch=abs(dz)*2*math.pi/angle
    result = dict(motion_kind="axial_helix",angle_raw_rad=angle,axial_delta_raw=dz,
        pitch_raw_per_rev=pitch,slope_deg=math.degrees(math.atan2(abs(dz),radius*angle)),
        one_minor_arc_assumption=True,extra_turns_verified=False,
        direction_semantics_basis="Observed COUNTERCLOCKWISE token with +Z normal; positive single minor arc used, no hidden turns inferred",
        helical_envelope_bounds_raw=[[center[0]-radius,center[1]-radius,min(start[2],endpoint[2])],
            [center[0]+radius,center[1]+radius,max(start[2],endpoint[2])]],
        envelope_basis="Conservative full circumference over endpoint Z interval under observed monotone axial helix convention")
    if quantized_antipodal:
        result.update(one_minor_arc_assumption=False,rounded_antipodal_arc=True,
            coordinate_quantum_raw=coordinate_quantum,antipodal_residual_raw=antipodal_residual,
            antipodal_residual_bound_raw=bound,angle_excess_over_pi_raw=angle-math.pi,
            angle_excess_bound_raw=angular_bound,coordinates_snapped=False,
            direction_semantics_basis="Observed +Z CCW single near-antipodal arc within six-decimal rounding bounds; raw coordinates and angle retained, hidden turns not inferred")
    return result


def six_decimal_coordinates(text,count):
    tokens=[part.strip() for part in text.split(',')]
    return len(tokens)==count and all(re.fullmatch(r"[+-]?[0-9]+[.][0-9]{6}",part) for part in tokens)


def parse_generic_cl_bytes(raw,*,encoding="cp1251",expected_record_counts=None, expected_block_record_counts=None):
    require(expected_record_counts is None or expected_block_record_counts is None,
        "Legacy and explicit ordered block counts are mutually exclusive")
    if expected_block_record_counts is not None:
        require(type(expected_block_record_counts) is list and 1 <= len(expected_block_record_counts) <= 32
            and all(type(v) is int and 1 <= v <= 100000 for v in expected_block_record_counts)
            and sum(expected_block_record_counts) <= MAX_TOTAL_RECORDS, "Bounded ordered positive block counts required")
    require(type(raw) is bytes and 0<len(raw)<=64*1024*1024,"Bounded nonempty CL bytes required")
    require(encoding in {"cp1251","utf-8","ascii"},"Explicit supported text encoding required")
    text=raw.decode(encoding,errors="strict")
    require(chr(0) not in text,"Binary/NUL content is not this observed text dialect")
    lines=text.splitlines();require(1<=len(lines)<=MAX_TEXT_LINES,"Bounded text line count required")
    commands=[];motions=[];circles=[];blocks=[];unknown=[];invalid=[];structure=[];pending_circle=None;cutcom_records=[]
    cutcom=initial_cutcom_state()
    axis=None;cutter=None;feed=None;mode=None;attrib=[];rotations=[];current=None;units=[];finished=False
    previous_coordinate_quantum=None;pending_coordinate_quantum=None
    for line_number,line in enumerate(lines,1):
        stripped=line.strip()
        if not stripped:continue
        name,sep,value=stripped.partition('/');name=name.strip();value=value.strip()
        command=dict(line=line_number,name=name,raw=stripped)
        commands.append(command)
        if finished:structure.append(dict(line=line_number,error="Command after FINI"))
        if current is not None and name!="OPFEATEND":current["command_count"]+=1
        if name not in KNOWN:
            unknown.append(command);continue
        try:
            require(pending_circle is None or name=="GOTO","CIRCLE requires the immediately following GOTO endpoint")
            require(name=="FINI" or sep=='/',"Slash required")
            if name=="UNITS":
                require(value in {"MM","INCH"},"Unsupported unit token")
                units.append(value);command["value"]=value
            elif name=="BOX":command["values_raw"]=numbers(value,6)
            elif name=="CUTTER":
                cutter=numbers(value,7,trailing=True);command["values_raw"]=cutter[:]
            elif name=="TLAXIS":
                axis=numbers(value,3);require(abs(sum(v*v for v in axis)-1)<1e-5,"Unit axis expected")
                command["values_raw"]=axis[:]
            elif name=="OPFEATSTART":
                require(current is None and bool(value),"Non-nested labelled operation block required")
                current=dict(index=len(blocks),label=value,start_line=line_number,end_line=None,command_count=0)
                require(len(blocks)<32,"At most 32 operation blocks supported")
                blocks.append(current);mode=None;feed=None;attrib=[];rotations=[];cutcom=initial_cutcom_state()
            elif name=="OPFEATEND":
                require(current is not None and current["label"]==value,"Matching operation block end required")
                require(cutcom["status"] in {"not_declared","off"},"Operation ends with active or incomplete CUTCOM sequence")
                current["end_line"]=line_number;current=None
                # Do not inherit a previous operation's tool, axis, mode or feeds.
                axis=None;cutter=None;mode=None;feed=None;attrib=[];rotations=[]
            elif name=="ROTABL":
                parts=[p.strip() for p in value.split(',')]
                require(len(parts)==4 and parts[1] in {"AAXIS","BAXIS","CAXIS"}
                    and parts[2]=="TABLE" and parts[3] in {"CLW","CCLW"},"Observed ROTABL tokens required")
                command["angle_raw"]=numbers(parts[0],1)[0];command["tokens"]=parts[1:]
                rotations.append(dict(line=line_number,angle_raw=command["angle_raw"],tokens=parts[1:]))
            elif name=="RAPID":
                require(not value,"Empty RAPID expected");mode="rapid"
            elif name=="FEDRAT":
                parts=[p.strip() for p in value.split(',')]
                require(len(parts)==2 and parts[0] in {"MMPM","IPM"},"Observed feed units required")
                feed=dict(unit=parts[0],value=numbers(parts[1],1)[0]);require(feed["value"]>0,"Positive feed required")
                mode="feed";command["feed_raw"]=dict(feed)
            elif name=="CUTCOM":
                require(current is not None,"CUTCOM requires an operation block")
                previous=deepcopy(cutcom);cutcom=transition_cutcom(cutcom,value,line_number)
                record=dict(line=line_number,block=current["index"],token=value,before=previous,after=deepcopy(cutcom))
                cutcom_records.append(record);command["cutcom"]=deepcopy(record)
            elif name=="MOVE_ATTRIB":
                attrib=[p.strip() for p in value.split(',')]
                require(len(attrib)>=2 and attrib[-1]=="END_ATTRIB" and all(attrib),"Terminated raw attribute list required")
                command["tokens"]=attrib[:]
            elif name=="CIRCLE":
                parts=[p.strip() for p in value.split(',')]
                require(len(parts)==8 and parts[-1] in {"CLOCKWISE","COUNTERCLOCKWISE"},"Observed CIRCLE fields required")
                values=numbers(','.join(parts[:-1]),7);center=values[:3];normal=values[3:6];radius=values[6]
                require(radius>0 and abs(sum(v*v for v in normal)-1)<1e-5,"Positive radius and unit normal required")
                require(current is not None and motions and motions[-1]["block"]==current["index"]
                    and mode=="feed","Observed feed circle requires a preceding motion in the same block")
                pending_circle=dict(line=line_number,block=current["index"],center_raw=center,normal_raw=normal,
                    radius_raw=radius,direction_token=parts[-1],start_raw=motions[-1]["xyz"][:],
                    start_line=motions[-1]["line"],mode=mode,endpoint_raw=None,endpoint_line=None,
                    units_frame_interpreted=False,sweep_angle_interpreted=False)
                pending_coordinate_quantum=1e-6 if previous_coordinate_quantum==1e-6 and six_decimal_coordinates(','.join(parts[:3]),3) and six_decimal_coordinates(parts[6],1) else None
                circles.append(pending_circle);command["values_raw"]=values;command["direction_token"]=parts[-1]
            elif name=="GOTO":
                xyz=numbers(value,3)
                endpoint_coordinate_quantum=1e-6 if six_decimal_coordinates(value,3) else None
                require(cutcom["status"]!="enabled_without_side","Motion before CUTCOM direction is not supported")
                require(current is not None and mode in {"rapid","feed"} and axis is not None and cutter is not None,
                    "Motion requires one operation, declared axis/cutter and explicit mode")
                motions.append(dict(line=line_number,block=current["index"],mode=mode,xyz=xyz,
                    axis_raw=axis[:],cutter_raw=cutter[:],feed_raw=dict(feed) if feed else None,
                    move_attrib_tokens=attrib[:],rotabl_records_before_motion=[dict(r) for r in rotations],cutcom_state=deepcopy(cutcom)))
                command["xyz_raw"]=xyz
                if pending_circle is not None:
                    circle=pending_circle
                    planar=all(abs(sum((point[i]-circle["center_raw"][i])*circle["normal_raw"][i] for i in range(3)))<=1e-5
                        and abs(math.sqrt(sum((point[i]-circle["center_raw"][i])**2 for i in range(3)))-circle["radius_raw"])<=1e-5
                        for point in (circle["start_raw"],xyz))
                    if not planar and abs(xyz[2]-circle["start_raw"][2])>1e-5:
                        require(max(abs(a-b) for a,b in zip(motions[-2]["axis_raw"],[0.,0.,1.]))<=1e-8,
                            "Helix start tool axis must also be +Z")
                        additions=validate_axial_helix_endpoint(circle,xyz,axis,coordinate_quantum=1e-6 if pending_coordinate_quantum==endpoint_coordinate_quantum==1e-6 else None)
                        circle.update(additions,endpoint_raw=xyz[:],endpoint_line=line_number,
                            endpoint_validated=True,coincident_endpoints=False)
                        motions[-1]["motion_kind"]="axial_helix"
                    else:
                        for point in (circle["start_raw"],xyz):
                            relative=[point[i]-circle["center_raw"][i] for i in range(3)]
                            require(abs(sum(relative[i]*circle["normal_raw"][i] for i in range(3)))<=1e-5
                                and abs(math.sqrt(sum(v*v for v in relative))-circle["radius_raw"])<=1e-5,
                                "Circle start/end must lie on the declared planar circle")
                        circle.update(endpoint_raw=xyz[:],endpoint_line=line_number,endpoint_validated=True,
                            coincident_endpoints=max(abs(a-b) for a,b in zip(circle["start_raw"],xyz))<=1e-6)
                        circle.update(classify_planar_circle_sweep(circle,circles[-2] if len(circles)>1 else None))
                        normal_squared=sum(v*v for v in circle["normal_raw"])
                        half=[circle["radius_raw"]*math.sqrt(max(0.,1-v*v/normal_squared)) for v in circle["normal_raw"]]
                        circle["full_circle_locus_bounds_raw"]=[
                            [circle["center_raw"][i]-half[i] for i in range(3)],
                            [circle["center_raw"][i]+half[i] for i in range(3)]]
                    circle["cutcom_state"]=deepcopy(cutcom)
                    motions[-1]["circle_record_line"]=circle["line"]
                    pending_circle=None
                previous_coordinate_quantum=endpoint_coordinate_quantum
            elif name=="FINI":
                require(not sep and not value and current is None,"FINI after a closed block required");finished=True
        except ValueError as exc:invalid.append(dict(line=line_number,name=name,error=str(exc)))
    if pending_circle is not None:structure.append(dict(error="Unfinished or invalid circle endpoint"))
    if current is not None:structure.append(dict(error="Unclosed operation block"))
    if not finished:structure.append(dict(error="Missing FINI"))
    if len(units)!=1:structure.append(dict(error="Exactly one declared unit record required"))
    expected_blocks=1 if expected_block_record_counts is None else len(expected_block_record_counts)
    if len(blocks)!=expected_blocks:structure.append(dict(error="Exact explicitly bounded operation block count required"))
    for block in blocks:
        if not any(m["block"]==block["index"] for m in motions):
            structure.append(dict(block=block["index"],error="Every operation block requires a validated motion"))
    counts=[b["command_count"] for b in blocks]
    expected=list(expected_block_record_counts) if expected_block_record_counts is not None else (_record_counts(expected_record_counts) if expected_record_counts is not None else None)
    count_matches=counts==expected if expected is not None else None
    complete=not (unknown or invalid or structure) and bool(motions) and (count_matches is not False)
    circle_bounds=[point for c in circles if c.get("endpoint_validated") for point in c.get("helical_envelope_bounds_raw",c.get("full_circle_locus_bounds_raw",[]))]
    envelope_points=[m["xyz"] for m in motions]+circle_bounds
    groups={name:[m["xyz"] for m in motions if m["mode"]==name] for name in ("rapid","feed")}
    return dict(scope=SCOPE,status="review_required",parser_revision=3,parse_complete=complete,encoding_requested=encoding,
        cutcom_records=cutcom_records,cutcom_state_semantics="Observed ON/LEFT/RIGHT/OFF transitions only; no offset magnitude, controller mode or coordinate transformation inferred",
        cutter_compensation_effect_qualified=False,cutter_compensation_applied=False,
        unresolved_coincident_circle_lines=[c["line"] for c in circles if c.get("coincident_endpoints")],
        full_turn_semantics_qualified=False,
        encoding_declared_by_file=False,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),line_count=len(lines),
        command_counts=dict(Counter(c["name"] for c in commands)),operation_blocks=blocks,
        expected_block_record_counts=expected_block_record_counts,operation_native_ids_inferred_from_labels=False,
        block_order_native_qualified=False,declared_units=units,expected_native_record_counts=expected,block_command_counts=counts,native_count_matches=count_matches,
        motions=motions,circle_records=circles,circle_count=len(circles),
        helix_count=sum(c.get("motion_kind")=="axial_helix" for c in circles),commands=commands,unknown_commands=unknown,
        raw_bounds_kind="GOTO endpoint bounds only",
        raw_path_envelope_bounds=bounds(envelope_points),
        raw_path_envelope_basis="GOTO endpoints plus full declared circle loci and observed axial helix envelopes; conservative for partial arcs, no world-frame claim",
        circle_direction_semantics_verified=False,circle_sweep_angles_verified=False,invalid_commands=invalid,structure_issues=structure,
        motion_count=len(motions),motion_mode_counts=dict(Counter(m["mode"] for m in motions)),
        raw_bounds=bounds([m["xyz"] for m in motions]),raw_feed_bounds=bounds(groups["feed"]),raw_rapid_bounds=bounds(groups["rapid"]),
        raw_feed_Z_levels=sorted({p[2] for p in groups["feed"]}),physical_poses_verified=False,
        units_scale_verified=False,coordinate_frame_verified=False,tool_reference_verified=False,
        coordinate_transform_applied=False,tool_mesh_scale_applied=False,full_swept_union_checked=False,
        may_simulate=False,production_qualified=False,native_calls=0,
        interpretation="Declared raw CL reference locations and axis records; not world-space cutter poses. Unknown commands prevent completeness.")
