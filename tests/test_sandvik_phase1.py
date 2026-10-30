"""Pure contract, mutation-batch and mesh failure tests for the bounded UD stage."""
import importlib.util
import math
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT
from scripts import sw_cam_sandvik_phase1 as m

def setup_fields():
    tool=SimpleNamespace(CutDiameter=0.,Protrusion=0.)
    ud=SimpleNamespace(**{k:0 if k in m.INTEGER_FIELDS else 0. for k,v in m.FIELDS if k not in ("CutDiameter","Protrusion")})
    return dict(tool=tool,ud=ud),dict(field_attempts=[])

def test_exact_order_and_no_redundant_zero_writes():
    targets,report=setup_fields();calls=[]
    result=m.apply_ud_fields(targets=targets,read=getattr,
        dispatch=lambda label,fn:(calls.append(label),fn())[1],report=report,persist=lambda:None)
    assert result==dict(m.FIELDS)
    assert calls==["property:"+k for k,v in m.FIELDS if v!=0]
    assert len(report["field_attempts"])==9
    assert all(x["readback_verified"] for x in report["field_attempts"])

@pytest.mark.parametrize("name",list(dict(m.FIELDS)))
def test_bad_scalar_bool_or_nonfinite_rejected(name):
    targets,report=setup_fields()
    setattr(targets["tool" if name in ("CutDiameter","Protrusion") else "ud"],name,True)
    calls=[]
    with pytest.raises(ValueError,match="Invalid initial"):
        m.apply_ud_fields(targets=targets,read=getattr,dispatch=lambda l,f:calls.append(l),
                          report=report,persist=lambda:None)
    assert not calls

def test_dispatch_failure_never_retries_or_advances():
    targets,report=setup_fields();calls=[]
    def dispatch(label,fn):
        calls.append(label)
        if label=="property:CutDiameter":raise RuntimeError("unknown dispatch")
        fn()
    with pytest.raises(RuntimeError,match="unknown"):
        m.apply_ud_fields(targets=targets,read=getattr,dispatch=dispatch,report=report,persist=lambda:None)
    assert calls==["property:OverallLength","property:ShankDia","property:CutDiameter"]
    assert targets["ud"].CutLength==0

def test_unexpected_coupled_field_stops():
    targets,report=setup_fields();calls=[]
    def dispatch(label,fn):
        calls.append(label);fn()
        targets["tool"].Protrusion=24
    with pytest.raises(ValueError,match="Unexpected coupled"):
        m.apply_ud_fields(targets=targets,read=getattr,dispatch=dispatch,report=report,persist=lambda:None)
    assert calls==["property:OverallLength"]

def test_coupled_exact_target_is_allowed_without_replay():
    targets,report=setup_fields();calls=[]
    def dispatch(label,fn):
        calls.append(label);fn()
        if label=="property:OverallLength":targets["ud"].ShankDia=8
    m.apply_ud_fields(targets=targets,read=getattr,dispatch=dispatch,report=report,persist=lambda:None)
    assert "property:ShankDia" not in calls

def test_readback_rejection_stops():
    targets,report=setup_fields();calls=[]
    def dispatch(label,fn):calls.append(label)
    with pytest.raises(ValueError,match="Setter readback"):
        m.apply_ud_fields(targets=targets,read=getattr,dispatch=dispatch,report=report,persist=lambda:None)
    assert calls==["property:OverallLength"]

def test_attempt_identity_is_source_and_payload_not_receipt(tmp_path):
    p=tmp_path/"part.sldprt";p.write_bytes(b"x")
    a=m.attempt_marker(p,"a"*64,"b"*64)
    assert a==m.attempt_marker(p,"a"*64,"b"*64)
    assert a!=m.attempt_marker(p,"a"*64,"c"*64)
    assert a.parent==p.parent

@pytest.mark.parametrize("existing,wrong",[(True,False),(False,True)])
def test_fresh_output_rejects_existing_and_suffix(tmp_path,existing,wrong):
    p=tmp_path/("out.txt" if wrong else "out.stl")
    if existing:p.write_bytes(b"x")
    with pytest.raises(ValueError):m.fresh_output(p,".stl",set())

def test_fresh_output_rejects_pinned_path(tmp_path):
    p=tmp_path/"out.stl"
    with pytest.raises(ValueError):m.fresh_output(p,".stl",{p.resolve()})

def test_holder_alias_rejected():
    with pytest.raises(ValueError,match="aliases"):m.reject_holder_alias(4,{145:4},identity=lambda o:o)
    assert m.reject_holder_alias(6,{145:4},identity=lambda o:o)
    with pytest.raises(ValueError):m.reject_holder_alias(None,{145:4},identity=lambda o:o)

def stl(path,rings,*,shift=0.,scale=1.,missing=False,wedge=False):
    n=16
    angles=[(2*math.pi*i/n) for i in range(n)]
    if wedge:angles=[0.,math.pi/2,math.pi,3*math.pi/2]
    points=[[(scale*r*math.cos(a),scale*r*math.sin(a),scale*z+shift) for a in angles] for r,z in rings]
    n=len(angles);tri=[]
    for a,b in zip(points,points[1:]):
        for i in range(n):
            j=(i+1)%n;tri.extend([(a[i],a[j],b[j]),(a[i],b[j],b[i])])
    for ring,rev in ((points[0],True),(points[-1],False)):
        c=(0.,0.,ring[0][2])
        for i in range(n):
            j=(i+1)%n;tri.append((c,ring[j],ring[i]) if rev else (c,ring[i],ring[j]))
    if missing:tri.pop()
    data=b"raw numeric fixture".ljust(80,b" ")+struct.pack("<I",len(tri))
    for t in tri:data+=struct.pack("<12fH",0.,0.,0.,*(v for p in t for v in p),0)
    path.write_bytes(data);return path

@pytest.mark.parametrize("portion,rings",[
    ("cutting",[(3.8,0),(4,.2),(4,19)]),("noncutting",[(4,19),(4,62.4),(3.4,63)])])
def test_valid_numeric_mesh_is_never_full_classification(tmp_path,portion,rings):
    p=stl(tmp_path/"a.stl",rings)
    result=m.numeric_mesh_observation(p,portion)
    assert result["mesh_health_verified"] and result["outer_bound_compatible"]
    assert not result["filled_rotational_coverage_verified"]
    assert not result["cutting_partition_verified"]
    assert not result["units_verified"]

def test_same_bounds_sparse_polyhedron_does_not_prove_rotational_coverage(tmp_path):
    p=stl(tmp_path/"a.stl",[(3.8,0),(4,.2),(4,19)],wedge=True)
    result=m.numeric_mesh_observation(p,"cutting")
    assert not result["filled_rotational_coverage_verified"]

@pytest.mark.parametrize("rings,kwargs",[
    ([(3.8,0),(4,.2),(4,63)],{}),
    ([(3.8,0),(4,.2),(4,19)],{"shift":.1}),
    ([(3.8,0),(4,.2),(4,19)],{"scale":.001}),
    ([(3.8,0),(4,.2),(4,19)],{"missing":True}),
    ([(4,0),(4,.2),(4,19)],{}),
    ([(3.8,0),(4.1,.2),(4.1,19)],{})])
def test_unsafe_or_malformed_cut_mesh_rejected(tmp_path,rings,kwargs):
    p=stl(tmp_path/"a.stl",rings,**kwargs)
    with pytest.raises(ValueError):m.numeric_mesh_observation(p,"cutting")

def test_empty_mesh_rejected(tmp_path):
    p=tmp_path/"a.stl";p.write_bytes(b"")
    with pytest.raises(ValueError):m.numeric_mesh_observation(p,"cutting")

def test_backend_contains_no_assignment_or_path_dispatch():
    source=(STAGE/"scripts/sw_cam_sandvik_phase1.py").read_text(encoding="utf-8-sig")
    for forbidden in ('"SetTool"', '"GenerateToolpath"', '"GenerateOperationPlan"', '"Save3"', '"RunSimulationSilent"'):
        assert forbidden not in source



def test_healthy_noncutting_larger_than_shank_is_pending_observation(tmp_path):
    p=tmp_path/"noncut_with_unknown_outer_geometry.stl"
    stl(p,[(4.,19.),(10.,25.),(10.,70.)])
    result=m.numeric_mesh_observation(p,"noncutting")
    assert result["mesh_health_verified"] is True
    assert result["expected_shank_envelope_compatible"] is False
    assert result["outer_bound_compatible"] is False
    assert result["maximum_radius_native"]==pytest.approx(10.)
    assert result["axial_extent_native"]==[19.,70.]
    assert result["classification_pending"] is True
    assert result["holder_inclusion_verified"] is False
    assert not result["units_verified"] and not result["physical_tool_qualified"]
    assert result["envelope_observation_issues"]

@pytest.mark.parametrize("raw",[b"",b"solid invalid\nendsolid invalid",b"not an STL"])
def test_malformed_noncutting_mesh_still_rejected(tmp_path,raw):
    p=tmp_path/"bad_noncut.stl";p.write_bytes(raw)
    with pytest.raises(ValueError):m.numeric_mesh_observation(p,"noncutting")


@pytest.mark.parametrize("kwargs",[{"missing":True},{"scale":float("nan")}])
def test_open_or_nonfinite_noncutting_mesh_rejected(tmp_path,kwargs):
    p=stl(tmp_path/"invalid_noncut.stl",[(4.,19.),(10.,25.),(10.,70.)],**kwargs)
    with pytest.raises(ValueError):m.numeric_mesh_observation(p,"noncutting")

