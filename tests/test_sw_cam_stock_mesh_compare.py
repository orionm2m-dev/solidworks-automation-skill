"""Offline represented-volume comparison; no CAD, mocks of acceptance, or fitting."""
from pathlib import Path
import importlib.util
import math
import struct
import pytest

D = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stock_mesh_compare_stage',D/'scripts/sw_cam_stock_mesh_compare.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)


def prism(points=None,z0=-32.,z1=28.,fan_shift=0,dimple=False):
    points = points or [(32.5*math.cos(2*math.pi*i/32),32.5*math.sin(2*math.pi*i/32)) for i in range(32)]
    n=len(points);bottom=[(x,y,z0) for x,y in points];top=[(x,y,z1) for x,y in points]
    rotated_b=bottom[fan_shift:]+bottom[:fan_shift];rotated_t=top[fan_shift:]+top[:fan_shift]
    triangles=[(rotated_b[0],rotated_b[i+1],rotated_b[i]) for i in range(1,n-1)]
    if dimple:
        center=(sum(x for x,y in points)/n,sum(y for x,y in points)/n,z1-2.)
        triangles += [(top[i],top[(i+1)%n],center) for i in range(n)]
    else:triangles += [(rotated_t[0],rotated_t[i],rotated_t[i+1]) for i in range(1,n-1)]
    for i in range(n):
        j=(i+1)%n;triangles += [(bottom[i],bottom[j],top[j]),(bottom[i],top[j],top[i])]
    return triangles


def binary(path,triangles,header=b'unit-test STL'):
    data=bytearray(header.ljust(80,b' ')[:80])+struct.pack('<I',len(triangles))
    for triangle in triangles:
        data += struct.pack('<12fH',0.,0.,0.,*(x for v in triangle for x in v),0)
    path.write_bytes(data);return path


def ascii_stl(path,triangles):
    lines=['solid stock']
    for triangle in triangles:
        lines += ['facet normal 0 0 0','outer loop']
        lines += ['vertex '+' '.join(format(x,'.17g') for x in vertex) for vertex in triangle]
        lines += ['endloop','endfacet']
    path.write_text('\n'.join(lines+['endsolid stock'])+'\n',encoding='ascii');return path


def transform(triangles,fn,reverse=False):
    result=[tuple(fn(v) for v in t) for t in triangles]
    return [tuple(reversed(t)) for t in result] if reverse else result


def subdivide(triangles):
    result=[]
    for a,b,c in triangles:
        m=tuple((a[i]+b[i]+c[i])/3 for i in range(3))
        result += [(a,b,m),(b,c,m),(c,a,m)]
    return result


@pytest.fixture
def pair(tmp_path):
    triangles=prism();a=binary(tmp_path/'expected.stl',triangles);b=binary(tmp_path/'actual.stl',triangles)
    return a,b,triangles


def test_identical_geometry_is_certified_beyond_hash_or_bounds(pair):
    a,b,_=pair;before=(a.read_bytes(),b.read_bytes());out=g.compare_stock_meshes(a,b)
    assert out['equivalent_within_verification_tolerance'] is True
    assert out['exact_triangle_canonical_multiset_equal'] is True and out['byte_identical'] is True
    assert out['expected_mesh']['triangles']==124 and out['expected_mesh']['vertices']==64
    assert out['expected_mesh']['edges']==186 and out['expected_mesh']['Euler_characteristic']==2
    assert out['files_pinned_before_after'] is True
    assert out['verification_tolerance_mm']==0.0001
    assert out['float32_paired_coordinate_rounding_bound_mm'] < out['verification_tolerance_mm']
    assert out['mutual_containment']['vertex_plane_tests'] > 0
    assert (a.read_bytes(),b.read_bytes())==before


def test_reordering_cyclic_vertices_and_binary_solid_header_preserve_geometry(pair):
    a,b,triangles=pair
    binary(b,[t[1:]+t[:1] for t in reversed(triangles)],header=b'solid binary file')
    out=g.compare_stock_meshes(a,b)
    assert out['exact_triangle_canonical_multiset_equal'] is True and out['byte_identical'] is False


@pytest.mark.parametrize('kind',['changed_cap_fan','triangle_subdivision','ascii'])
def test_equivalent_retriangulation_and_encoding_do_not_require_same_hash(pair,kind):
    a,b,triangles=pair
    if kind=='changed_cap_fan':binary(b,prism(fan_shift=7))
    if kind=='triangle_subdivision':binary(b,subdivide(triangles))
    if kind=='ascii':ascii_stl(b,triangles)
    out=g.compare_stock_meshes(a,b)
    assert out['equivalent_within_verification_tolerance'] is True and out['byte_identical'] is False
    if kind!='ascii':assert out['exact_triangle_canonical_multiset_equal'] is False
    if kind=='triangle_subdivision':assert out['actual_mesh']['triangles']==372
    if kind=='ascii':assert out['actual_mesh']['encoding']=='ascii_numeric'


@pytest.mark.parametrize('delta',[.01,-.01,1.])
def test_translated_stock_fails_without_registration(pair,delta):
    a,b,t=pair;binary(b,transform(t,lambda v:(v[0]+delta,v[1],v[2])))
    with pytest.raises(ValueError,match='geometry differs'):g.compare_stock_meshes(a,b)


@pytest.mark.parametrize('scale',[1.01,.99,.001,25.4])
def test_scale_or_unit_change_is_not_silently_fitted(pair,scale):
    a,b,t=pair;binary(b,transform(t,lambda v:tuple(x*scale for x in v)))
    with pytest.raises(ValueError):g.compare_stock_meshes(a,b)


def test_reflected_asymmetric_closed_outward_stock_fails(tmp_path):
    t=prism(points=[(0.,0.),(3.,0.),(0.,2.)],z0=0.,z1=4.)
    a=binary(tmp_path/'expected.stl',t);b=binary(tmp_path/'actual.stl',transform(t,lambda v:(-v[0],v[1],v[2]),reverse=True))
    with pytest.raises(ValueError,match='geometry differs'):g.compare_stock_meshes(a,b)


def test_nonconvex_dimple_with_identical_bounding_box_fails(pair):
    a,b,t=pair;d=prism(dimple=True)
    assert [min(v[i] for tri in t for v in tri) for i in range(3)]==[min(v[i] for tri in d for v in tri) for i in range(3)]
    assert [max(v[i] for tri in t for v in tri) for i in range(3)]==[max(v[i] for tri in d for v in tri) for i in range(3)]
    binary(b,d)
    with pytest.raises(ValueError,match='non-convex'):g.compare_stock_meshes(a,b)


@pytest.mark.parametrize('case',['open','one_reversed','all_reversed','duplicate','degenerate','internal_cavity'])
def test_invalid_or_nonconvex_shells_are_not_accepted_by_matching_extent(pair,case):
    a,b,t=pair
    if case=='open':t=t[:-1]
    if case=='one_reversed':t=[tuple(reversed(t[0]))]+t[1:]
    if case=='all_reversed':t=[tuple(reversed(x)) for x in t]
    if case=='duplicate':t=t+[t[0]]
    if case=='degenerate':t=t+[(t[0][0],t[0][0],t[0][1])]
    if case=='internal_cavity':
        inner=prism(points=[(-1.,-1.),(1.,-1.),(1.,1.),(-1.,1.)],z0=-1.,z1=1.)
        t=t+[tuple(reversed(x)) for x in inner]
    binary(b,t)
    with pytest.raises(ValueError):g.compare_stock_meshes(a,b)


@pytest.mark.parametrize('encoding',['binary','ascii'])
@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_vertex_is_rejected_before_geometry(pair,encoding,value):
    a,b,t=pair;t=deepcopy_triangles(t);t[0][0]=(value,t[0][0][1],t[0][0][2])
    (binary if encoding=='binary' else ascii_stl)(b,t)
    with pytest.raises(ValueError):g.compare_stock_meshes(a,b)


def deepcopy_triangles(triangles):return [list(t) for t in triangles]


def test_nonfinite_stored_normal_is_rejected(pair):
    a,b,t=pair;data=bytearray(b.read_bytes());struct.pack_into('<f',data,84,float('nan'));b.write_bytes(data)
    with pytest.raises(ValueError,match='Non-finite'):g.compare_stock_meshes(a,b)


@pytest.mark.parametrize('case',['truncated','trailing','ascii_grammar','empty','oversize'])
def test_file_grammar_and_size_fail_closed(pair,case):
    a,b,t=pair
    if case=='truncated':b.write_bytes(b.read_bytes()[:-1])
    if case=='trailing':b.write_bytes(b.read_bytes()+b'garbage')
    if case=='ascii_grammar':b.write_text('solid x\nfacet normal 0 0 0\nendsolid x',encoding='ascii')
    if case=='empty':b.write_bytes(b'')
    if case=='oversize':b.write_bytes(b'x'*(g.MAX_FILE_BYTES+1))
    with pytest.raises(ValueError):g.compare_stock_meshes(a,b)


@pytest.mark.parametrize('constant,value',[('MAX_TRIANGLES',100),('MAX_VERTICES',32),('MAX_HALFSPACE_TESTS',1)])
def test_computation_bounds_are_enforced_before_unbounded_work(pair,monkeypatch,constant,value):
    monkeypatch.setattr(g,constant,value)
    with pytest.raises(ValueError):g.compare_stock_meshes(pair[0],pair[1])


def test_file_changes_during_comparison_invalidate_pins(pair,monkeypatch):
    a,b,t=pair;original=g._halfspace_extreme;changed=False
    def racing(*args):
        nonlocal changed
        if not changed:
            data=bytearray(b.read_bytes());data[0]^=1;b.write_bytes(data);changed=True
        return original(*args)
    monkeypatch.setattr(g,'_halfspace_extreme',racing)
    with pytest.raises(ValueError,match='changed during comparison'):g.compare_stock_meshes(a,b)


def test_self_comparison_cannot_stand_for_native_export(pair):
    with pytest.raises(ValueError,match='distinct'):g.compare_stock_meshes(pair[0],pair[0])


def test_missing_file_identity_fails_closed(pair,monkeypatch):
    from types import SimpleNamespace
    original=g.os.fstat
    def unavailable(fd):
        st=original(fd)
        values={name:getattr(st,name) for name in ('st_dev','st_size','st_mtime_ns','st_mode','st_ctime_ns')}
        return SimpleNamespace(st_ino=0,**values)
    monkeypatch.setattr(g.os,'fstat',unavailable)
    with pytest.raises(ValueError,match='reliable file identity'):
        g.compare_stock_meshes(pair[0],pair[1])


def test_canonical_path_identity_must_match_requested_file(pair,monkeypatch):
    a,b,_=pair;original=Path.resolve
    def changed(path,*args,**kwargs):
        return original(b,*args,**kwargs) if path==a else original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'resolve',changed)
    with pytest.raises(ValueError,match='canonical path identity'):
        g.compare_stock_meshes(a,b)


def test_hard_link_cannot_stand_for_separate_native_export(pair,tmp_path):
    a,b,_=pair;alias=tmp_path/'hardlink.stl'
    try:g.os.link(a,alias)
    except OSError as exc:pytest.skip('Filesystem does not support hard links: '+str(exc))
    with pytest.raises(ValueError,match='distinct'):
        g.compare_stock_meshes(a,alias)
