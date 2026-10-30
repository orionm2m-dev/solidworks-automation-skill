"""Native-format fixtures for noncutting assemblies with multiple shells and bores."""
import math
import struct
from pathlib import Path
import pytest
from test_sandvik_phase1 import m,stl

def write_binary(path,triangles):
    raw=b"bounded topology fixture".ljust(80,b" ")+struct.pack("<I",len(triangles))
    for triangle in triangles:
        raw+=struct.pack("<12fH",0.,0.,0.,*(x for p in triangle for x in p),0)
    path.write_bytes(raw)
    return path

def triangles(path):
    return m._decode(Path(path).read_bytes())[0]

def shift(rows,dx=0.,dy=0.,dz=0.):
    return [tuple((x+dx,y+dy,z+dz) for x,y,z in t) for t in rows]

def reverse(rows):
    return [(a,c,b) for a,b,c in rows]

def torus(major=10.,minor=2.,n=24,k=12):
    points=[[( (major+minor*math.cos(2*math.pi*j/k))*math.cos(2*math.pi*i/n),
                (major+minor*math.cos(2*math.pi*j/k))*math.sin(2*math.pi*i/n),
                35.+minor*math.sin(2*math.pi*j/k)) for j in range(k)] for i in range(n)]
    rows=[]
    for i in range(n):
        for j in range(k):
            a,b,c,d=points[i][j],points[(i+1)%n][j],points[(i+1)%n][(j+1)%k],points[i][(j+1)%k]
            rows.extend([(a,b,c),(a,c,d)])
    return rows

def through_bore(n=24):
    rings=[(10.,19.),(10.,40.),(4.,40.),(4.,19.)]
    points=[[(r*math.cos(2*math.pi*i/n),r*math.sin(2*math.pi*i/n),z) for i in range(n)] for r,z in rings]
    rows=[]
    for a,b in zip(points,points[1:]+points[:1]):
        for i in range(n):
            j=(i+1)%n
            rows.extend([(a[i],a[j],b[j]),(a[i],b[j],b[i])])
    return rows

def test_two_separate_closed_components_are_observed(tmp_path):
    one=triangles(stl(tmp_path/"one.stl",[(4.,19.),(4.,30.)]))
    p=write_binary(tmp_path/"two.stl",one+shift(one,dx=20.))
    result=m.numeric_mesh_observation(p,"noncutting")
    topo=result["topology_observation"]
    assert result["mesh_health_verified"] and result["classification_pending"]
    assert result["topology_health_verified"] is True
    assert topo["component_count"]==2
    assert [c["Euler_characteristic"] for c in topo["components"]]==[2,2]
    assert topo["Euler_characteristic"]==4
    assert not topo["component_disjointness_verified"]
    assert not result["physical_tool_qualified"]

@pytest.mark.parametrize("factory",[torus,through_bore])
def test_closed_through_hole_genus_one_is_allowed(tmp_path,factory):
    p=write_binary(tmp_path/"bore.stl",factory())
    result=m.numeric_mesh_observation(p,"noncutting")
    topo=result["topology_observation"]
    assert topo["component_count"]==1 and topo["Euler_characteristic"]==0
    assert topo["components"][0]["signed_volume_native_cubed"]>0
    assert not topo["genus_restricted"]
    assert not topo["self_intersections_checked"] and not topo["material_union_verified"]

def test_negative_inner_shell_is_measured_not_physical_acceptance(tmp_path):
    outer=triangles(stl(tmp_path/"outer.stl",[(10.,19.),(10.,45.)]))
    inner=triangles(stl(tmp_path/"inner.stl",[(4.,20.),(4.,44.)]))
    result=m.numeric_mesh_observation(write_binary(tmp_path/"hollow.stl",outer+reverse(inner)),"noncutting")
    components=result["topology_observation"]["components"]
    assert components[0]["signed_volume_native_cubed"]>0
    assert components[1]["signed_volume_native_cubed"]<0
    assert not result["topology_observation"]["component_nesting_verified"]
    assert not result["topology_observation"]["volume_sign_is_acceptance_criterion"]
    assert not result["physical_tool_qualified"]

@pytest.mark.parametrize("fault",["open","edge_reversed","duplicate","degenerate","nonfinite"])
def test_invalid_noncutting_topology_is_rejected(tmp_path,fault):
    rows=torus()
    if fault=="open":rows.pop()
    elif fault=="edge_reversed":rows[0]=tuple(reversed(rows[0]))
    elif fault=="duplicate":rows.append(rows[0])
    elif fault=="degenerate":rows[0]=(rows[0][0],rows[0][0],rows[0][2])
    elif fault=="nonfinite":
        a,b,c=rows[0];rows[0]=((float("inf"),a[1],a[2]),b,c)
    p=write_binary(tmp_path/"invalid.stl",rows)
    with pytest.raises(ValueError):m.numeric_mesh_observation(p,"noncutting")

def test_point_touching_closed_shells_are_not_vertex_manifold(tmp_path):
    # Two tetrahedra share one vertex, while every edge still has two opposite incidents.
    a=(0.,0.,0.);b=(1.,0.,0.);c=(0.,1.,0.);d=(0.,0.,1.)
    one=[(a,c,b),(a,b,d),(a,d,c),(b,c,d)]
    two=[tuple((-x,-y,-z) for x,y,z in t) for t in one]
    with pytest.raises(ValueError,match="vertex link"):
        m.numeric_mesh_observation(write_binary(tmp_path/"pinch.stl",one+two),"noncutting")

def test_multi_shell_and_torus_are_still_rejected_by_cutting_stock_helper(tmp_path):
    one=triangles(stl(tmp_path/"one.stl",[(4.,19.),(4.,30.)]))
    for rows in (one+shift(one,dx=20.),torus()):
        with pytest.raises(ValueError):m._mesh(rows)

