"""Experimental exact-candidate MT serialization and raw profile comparison."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re

PART = "1K334-0800-XB1730"
CAD_SHA256 = "f3b52ab743ea80a97f5dd6b502220da31e0abc5e557373c0c975d4d24f929fb4"
REFERENCE_MT_SHA256 = "c795a4850ce14b768c3f677e9389983b2f555a18d2d60aa43ff3dd6da4e40d76"
POINTS = ((0.,0.),(3.8,0.),(4.,.2),(4.,19.),(4.,62.4),(3.4,63.))
TOLERANCE_NATIVE = 1e-12
_SCOPE = "EXPERIMENTAL_SANDVIK_LINE_MT_V1"

def _require(value, message):
    if not value: raise ValueError(message)

def _pin(path, sha256):
    p=Path(path)
    _require(p.is_absolute() and p.is_file() and not p.is_symlink(), "Existing absolute regular input required")
    _require(type(sha256) is str and re.fullmatch("[0-9a-f]{64}",sha256), "Exact lowercase SHA256 required")
    content=p.read_bytes()
    _require(hashlib.sha256(content).hexdigest()==sha256, "Pinned input changed")
    return content,dict(path=str(p.resolve()),sha256=sha256)

def _points(value, expected):
    _require(type(value) is list and len(value)==len(expected), "Exact candidate point count required")
    for p,q in zip(value,expected):
        _require(type(p) is list and len(p)==2
            and all(type(v) in (int,float) and math.isfinite(v) for v in p)
            and tuple(p)==tuple(q), "Exact nominal candidate profile required")

def load_candidate_contract(contract_path,contract_sha256,source_cad_path,source_cad_sha256,
        reference_mt_path,reference_mt_sha256,analysis_path,analysis_sha256):
    raw,contract_pin=_pin(contract_path,contract_sha256);data=json.loads(raw)
    _require(data.get("tool")==PART, "Exact candidate part identity required")
    _require(source_cad_sha256==CAD_SHA256 and data["factory_STEP"]["sha256"]==CAD_SHA256,
        "Exact factory CAD identity required")
    _,cad_pin=_pin(source_cad_path,source_cad_sha256)
    _require(reference_mt_sha256==REFERENCE_MT_SHA256
        and data["installed_MT_example"]["sha256"]==REFERENCE_MT_SHA256, "Exact proven MT specimen required")
    reference,mt_pin=_pin(reference_mt_path,reference_mt_sha256)
    lines=reference.decode("ascii").splitlines()
    _require(lines[0].strip()=="Version Clouds", "Observed header required")
    records=[s for s in lines[1:] if s.strip() and not s.lstrip().startswith("#")]
    _require(len(records)==8 and all(re.fullmatch(r"line(?: +-?\d+\.\d+){4}\s*",s) for s in records),
        "Proven specimen grammar changed")
    analysis_raw,analysis_pin=_pin(analysis_path,analysis_sha256);analysis=json.loads(analysis_raw)
    _require(analysis["source_MT"]["sha256"]==REFERENCE_MT_SHA256
        and type(analysis["numeric_mapping"]["native_per_MT_unit"]) in (int,float)
        and analysis["numeric_mapping"]["native_per_MT_unit"]==1.0
        and analysis["partition"]["GetToolProfile_contains_entire_MT"] is True
        and analysis["units"]["native_profile_physical_mm_proven"] is False,
        "Exact raw-only profile evidence required")
    _require(data["units"]=="mm", "Nominal factory geometry units required")
    _points(data["closed_half_section_for_revolved_sketch_rz"],list(POINTS)+[(0.,63.),(0.,0.)])
    _points(data["cutting_part"]["outside_profile_rz"],POINTS[:4])
    _points(data["noncutting_part"]["outside_profile_rz"],POINTS[3:])
    params=data["expected_parameters"]
    expected={"ICWTool.CutDiameter":8,"ICWMillUDTool.CutLength":19,"ICWMillUDTool.OverallLength":63,
        "ICWMillUDTool.ShankDia":8,"ICWMillUDTool.Flutes":4,"ICWMillUDTool.TipOffset":0,
        "ICWMillUDTool.TipLength":0}
    _require(all(type(params.get(k)) in (int,float) and params[k]==v for k,v in expected.items()),
        "Exact nominal scalar specification required")
    requested=analysis["physical_configuration"]["candidate_protrusion_mm"]
    _require(type(requested) in (int,float) and requested==25, "Only recorded proposed protrusion supported")
    return dict(scope=_SCOPE,part=PART,source_cad_sha256=CAD_SHA256,
        pins=[contract_pin,cad_pin,mt_pin,analysis_pin],
        nominal_points_rz=[list(v) for v in POINTS],nominal_parameters=deepcopy(expected),
        protrusion=dict(requested=25,verified=False,apply_automatically=False),
        record_count=5,open_outer_contour=True,units_verified=False,
        cutting_partition_verified=False,production_qualified=False,
        definition="Factory-derived rotating envelope; not stationary Weldon seating or flute geometry.")

def _check_contract(candidate):
    _require(type(candidate) is dict and type(candidate.get("pins")) is list
        and len(candidate["pins"])==4, "Complete exact candidate pins required")
    args=[]
    for p in candidate["pins"]:args += [p["path"],p["sha256"]]
    current=load_candidate_contract(*args)
    _require(candidate==current, "Candidate contract was altered")
    return current

def render_candidate_mt(candidate):
    _check_contract(candidate)
    lines=["Version Clouds", "# Experimental exact rotating envelope: "+PART,
        "# Raw numeric contract only; physical units and production use are unqualified.",
        "# Segments follow:"]
    for a,b in zip(POINTS,POINTS[1:]):
        lines.append("line "+" ".join(format(v,".6f") for v in (*a,*b)))
    return ("\n".join(lines)+"\n").encode("ascii")

def write_candidate_mt(candidate,output_path,*,acknowledge_experimental=False):
    _require(acknowledge_experimental is True, "Explicit experimental output acknowledgement required")
    content=render_candidate_mt(candidate);p=Path(output_path)
    _require(p.is_absolute() and p.suffix.casefold()==".mt" and p.parent.is_dir()
        and not p.exists() and not p.is_symlink(), "New absolute .mt output in an existing directory required")
    resolved=p.resolve()
    _require(all(resolved!=Path(pin["path"]).resolve() for pin in candidate["pins"]),
        "Output cannot replace input evidence")
    with p.open("xb") as stream:
        stream.write(content);stream.flush();os.fsync(stream.fileno())
    actual=p.read_bytes()
    _require(actual==content, "Exclusive output content verification failed; retained for diagnosis, do not replay")
    directory_synced=False
    if os.name!="nt":
        descriptor=os.open(str(p.parent),os.O_RDONLY)
        try:os.fsync(descriptor);directory_synced=True
        finally:os.close(descriptor)
    return dict(scope=_SCOPE,part=PART,path=str(resolved),sha256=hashlib.sha256(actual).hexdigest(),
        size_bytes=len(actual),record_count=5,pins=deepcopy(candidate["pins"]),exclusive_create=True,
        content_verified=True,file_fsync=True,parent_fsync=directory_synced,
        experimental=True,native_loaded=False,units_verified=False,cutting_partition_verified=False,
        production_qualified=False,operation_assignment_attempted=False)

def _xyz(value):
    _require(type(value) is list and len(value)==3
        and all(type(v) in (int,float) and math.isfinite(v) for v in value), "Finite strict XYZ required")
    _require(abs(value[1])<=TOLERANCE_NATIVE,"Native profile must remain in the observed XZ plane")
    return (float(value[0]),float(value[2]))

def _near(a,b):
    return math.dist(a,b)<=TOLERANCE_NATIVE

def _same_edge(a,b,c,d):
    return (_near(a,c) and _near(b,d)) or (_near(a,d) and _near(b,c))

def _on_segment(p,a,b):
    length=math.dist(a,b)
    return abs(math.dist(a,p)+math.dist(p,b)-length)<=TOLERANCE_NATIVE

def _curves(profile):
    _require(type(profile) is dict and profile.get("status")=="observed", "Full native profile observation required")
    chains=profile.get("chains");count=profile.get("declared_chain_count")
    _require(type(chains) is list and type(count) is int and count==len(chains)
        and 1<=count<=8, "Complete bounded native chains required")
    total=0
    for i,chain in enumerate(chains):
        curves=chain.get("curves");n=chain.get("declared_curve_count")
        _require(type(chain.get("index")) is int and chain["index"]==i and chain.get("read_complete") is True
            and type(curves) is list and type(n) is int and n==len(curves) and 0<=n<=32,
            "Complete ordered bounded native curves required")
        total+=n;_require(total<=64,"Native curve budget exceeded")
        for j,curve in enumerate(curves):
            _require(type(curve.get("index")) is int and curve["index"]==j
                and curve.get("read_complete") is True and type(curve.get("curve_type")) is int
                and curve["curve_type"]==0,"Only complete native line observations supported")
            yield i,j,_xyz(curve["start_native"]),_xyz(curve["end_native"])

def validate_native_profiles(candidate,profiles):
    _check_contract(candidate)
    _require(type(profiles) is dict and "tool" in profiles and "shank" in profiles,
        "Both complete generic native profiles required")
    expected=list(zip(POINTS,POINTS[1:]));cap=(POINTS[-1],(0.,63.))
    observed=[];extras=[];shank_edges=[]
    for label in ("tool","shank"):
        cap_count=0;degenerate_count=0
        for chain,index,a,b in _curves(profiles[label]):
            if _near(a,b):
                _require(any(_on_segment(a,c,d) for c,d in expected+[cap]),
                    "Unexpected external degenerate point")
                degenerate_count+=1;_require(degenerate_count<=32,"Degenerate budget exceeded")
                extras.append(dict(profile=label,chain=chain,curve=index,kind="zero_length"));continue
            matching=[i for i,(c,d) in enumerate(expected) if _same_edge(a,b,c,d)]
            if matching:
                (observed if label=="tool" else shank_edges).append(matching[0]);continue
            if _same_edge(a,b,*cap):
                cap_count+=1;_require(cap_count<=1,"Duplicate native cap")
                extras.append(dict(profile=label,chain=chain,curve=index,kind="radial_rear_cap"));continue
            raise ValueError("Native profile contains an unmatched external edge")
    _require(sorted(observed)==list(range(5)), "Full tool profile must cover each exact outer segment once")
    _require(len(set(shank_edges))==len(shank_edges),"Duplicated shank profile edges")
    return dict(scope=_SCOPE,part=PART,raw_numeric_profile_match=True,source_segments_covered=5,
        mapping=dict(native_X="nominal radius",native_Y=0,native_Z="nominal axial coordinate",scale=1.0),
        comparison_tolerance_native=TOLERANCE_NATIVE,tolerance_is_machining_tolerance=False,
        extra_native_segments=extras,shank_nonzero_outer_segments=len(shank_edges),
        units_verified=False,cutting_partition_verified=False,physical_tool_qualified=False,
        production_qualified=False)
