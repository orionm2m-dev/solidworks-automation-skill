"""Bounded offline convex STL comparison in fixed WORLD millimetres.

No alignment, scaling, application calls or geometry repair. Exact topology uses
stored coordinates. Convexity and mutual half-space inclusion use a fixed 0.0001
mm verification tolerance, not a manufacturing tolerance. Coordinates are bounded
by 256 mm: the paired binary32 coordinate-rounding bound is <0.000053 mm.
"""
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import math
import os
import stat
import struct

TOLERANCE_MM = 0.0001
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TRIANGLES = 4096
MAX_VERTICES = 2048
MAX_ABS_COORDINATE_MM = 256.0
MAX_HALFSPACE_TESTS = 8_000_000
FLOAT32_PAIRED_COORDINATE_ROUNDING_BOUND_MM = math.sqrt(3.0) * 2.0 ** -15


def _signature(s):
    if s.st_ino == 0:
        raise ValueError('STL file has no reliable file identity')
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode, s.st_ctime_ns)


def _read_pinned(value):
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError('An absolute regular STL file path is required')
    p = Path(value)
    if not p.is_absolute() or p.suffix.casefold() != '.stl' or p.is_symlink():
        raise ValueError('An absolute non-symlink STL file is required')
    try:
        resolved = p.resolve(strict=True)
        before = p.stat()
        if _signature(resolved.stat())[:-1] != _signature(before)[:-1]:
            raise ValueError('STL canonical path identity differs from requested file')
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= MAX_FILE_BYTES:
            raise ValueError('STL file size or kind exceeds the bound')
        with p.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            # Windows-to-WSL path and handle APIs may report different ctime.
            # Path ctime can also change on read through that bridge.
            # Pin handle ctime strictly; path identity uses dev/ino/size/mtime/mode.
            if _signature(opened)[:-1] != _signature(before)[:-1]:
                raise ValueError('STL path/handle changed before reading')
            data = stream.read(MAX_FILE_BYTES + 1)
            closed = os.fstat(stream.fileno())
        after = p.stat()
        if (len(data) != before.st_size or len(data) > MAX_FILE_BYTES or
                _signature(opened) != _signature(closed) or
                _signature(before)[:-1] != _signature(after)[:-1] or
                _signature(before)[:-1] != _signature(resolved.stat())[:-1] or
                p.is_symlink() or p.resolve(strict=True) != resolved):
            raise ValueError('STL file changed during reading')
    except OSError as exc:
        raise ValueError('STL file cannot be read stably') from exc
    pin = dict(path=str(p), canonical_path=str(resolved), bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), identity=list(_signature(opened)),
        path_identity=list(_signature(before)[:-1]),
        ctime_policy='Handle ctime pinned before/after read and across comparison; path/canonical metadata use dev/ino/size/mtime/mode because Windows-WSL path ctime changes on read.')
    return data, pin


def _finite(values, *, coordinates=False):
    if not all(math.isfinite(x) for x in values):
        raise ValueError('Non-finite STL coordinate or normal')
    if coordinates and any(abs(x) > MAX_ABS_COORDINATE_MM for x in values):
        raise ValueError('STL coordinates exceed the fixed WORLD-mm verification domain')


def _decode(data):
    # A binary STL may start with the word solid. Its exact byte layout wins.
    if len(data) >= 84:
        count = struct.unpack_from('<I', data, 80)[0]
        if len(data) == 84 + 50 * count:
            if not 1 <= count <= MAX_TRIANGLES:
                raise ValueError('Binary STL triangle count exceeds bound')
            triangles = []
            for i in range(count):
                row = struct.unpack_from('<12fH', data, 84 + 50 * i)
                _finite(row[:12]); _finite(row[3:12], coordinates=True)
                triangles.append(tuple(tuple(row[3 + j*3:6 + j*3]) for j in range(3)))
            return triangles, 'binary_float32'
    try:
        lines = [line.strip() for line in data.decode('ascii').splitlines() if line.strip()]
    except UnicodeDecodeError as exc:
        raise ValueError('Malformed binary STL or non-ASCII STL') from exc
    if (len(lines) < 9 or lines[0].split()[0].casefold() != 'solid' or
            lines[-1].split()[0].casefold() != 'endsolid' or (len(lines)-2) % 7):
        raise ValueError('Strict single-solid ASCII STL grammar required')
    count = (len(lines)-2)//7
    if not 1 <= count <= MAX_TRIANGLES:
        raise ValueError('ASCII STL triangle count exceeds bound')
    triangles = []
    try:
        for i in range(count):
            block = lines[1+7*i:8+7*i]
            header = block[0].split()
            if (len(header) != 5 or [x.casefold() for x in header[:2]] != ['facet', 'normal'] or
                    block[1].casefold() != 'outer loop' or block[5].casefold() != 'endloop' or
                    block[6].casefold() != 'endfacet'):
                raise ValueError('Malformed ASCII STL facet')
            _finite([float(x) for x in header[2:]])
            triangle = []
            for line in block[2:5]:
                row = line.split()
                if len(row) != 4 or row[0].casefold() != 'vertex':
                    raise ValueError('Malformed ASCII STL vertex')
                point = tuple(float(x) for x in row[1:]); _finite(point, coordinates=True)
                triangle.append(point)
            triangles.append(tuple(triangle))
    except (ValueError, OverflowError) as exc:
        raise ValueError('Invalid bounded ASCII STL facet data') from exc
    return triangles, 'ascii_numeric'


def _sub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _dot(a, b):
    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]


def _connected(adjacency, start):
    seen = {start}; pending = [start]
    while pending:
        for node in adjacency[pending.pop()] - seen:
            seen.add(node); pending.append(node)
    return seen


def _mesh(triangles):
    vertices = []; lookup = {}; faces = []; edges = defaultdict(list); links = defaultdict(list)
    canonical = Counter(); planes = set()
    for fi, triangle in enumerate(triangles):
        key = tuple(sorted(triangle)); canonical[key] += 1
        if canonical[key] != 1 or len(set(triangle)) != 3:
            raise ValueError('Duplicate or degenerate STL triangle')
        normal = _cross(_sub(triangle[1],triangle[0]), _sub(triangle[2],triangle[0]))
        norm = math.sqrt(_dot(normal, normal))
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError('Zero-area or invalid STL triangle')
        unit = tuple(x/norm for x in normal)
        planes.add((unit[0],unit[1],unit[2],_dot(unit,triangle[0])))
        ids = []
        for point in triangle:
            if point not in lookup:
                if len(vertices) >= MAX_VERTICES:
                    raise ValueError('Unique STL vertex count exceeds bound')
                lookup[point] = len(vertices); vertices.append(point)
            ids.append(lookup[point])
        face = tuple(ids); faces.append(face)
        for a,b in zip(face,face[1:]+face[:1]):
            edges[tuple(sorted((a,b)))].append((fi,a,b))
        for i,v in enumerate(face):
            links[v].append((face[(i+1)%3],face[(i+2)%3]))
    adjacency = defaultdict(set)
    for incidents in edges.values():
        if (len(incidents) != 2 or incidents[0][1] != incidents[1][2] or
                incidents[0][2] != incidents[1][1]):
            raise ValueError('STL is not a closed consistently oriented edge manifold')
        a,b = incidents[0][0],incidents[1][0]; adjacency[a].add(b); adjacency[b].add(a)
    if len(_connected(adjacency,0)) != len(faces):
        raise ValueError('STL must have one connected shell')
    for segments in links.values():
        graph = defaultdict(set)
        for a,b in segments:
            graph[a].add(b); graph[b].add(a)
        if (any(len(v) != 2 for v in graph.values()) or
                len(_connected(graph,next(iter(graph)))) != len(graph)):
            raise ValueError('STL vertex link is not one manifold cycle')
    if len(vertices)-len(edges)+len(faces) != 2:
        raise ValueError('Convex closed shell must have Euler characteristic two')
    center = tuple(math.fsum(v[i] for v in vertices)/len(vertices) for i in range(3))
    volume = math.fsum(_dot(_sub(a,center),_cross(_sub(b,center),_sub(c,center)))
        for a,b,c in triangles)/6.0
    if not math.isfinite(volume) or volume <= 0:
        raise ValueError('STL winding must enclose positive oriented volume')
    bounds = [min(v[i] for v in vertices) for i in range(3)] + [max(v[i] for v in vertices) for i in range(3)]
    return dict(vertices=vertices, planes=sorted(planes), canonical=canonical,
        facts=dict(triangles=len(faces),vertices=len(vertices),edges=len(edges),
            unique_oriented_planes=len(planes),bounds_world_mm=bounds,
            signed_volume_mm3=volume,closed_connected_oriented_manifold=True,
            vertex_links_single_cycles=True,Euler_characteristic=2))


def _halfspace_extreme(vertices, planes):
    maximum = -math.inf
    for x,y,z,h in planes:
        for a,b,c in vertices:
            maximum = max(maximum,x*a+y*b+z*c-h)
    return maximum


def compare_stock_meshes(expected_path, actual_path):
    """Return JSON facts for equivalent convex stock, otherwise raise ValueError.

    Byte hashes pin inputs, not the geometric acceptance criterion. A reflected
    geometrically symmetric solid is indistinguishable from the original shape;
    inversions and geometry changes beyond tolerance fail without fitting.
    """
    first, expected_pin = _read_pinned(expected_path)
    second, actual_pin = _read_pinned(actual_path)
    if (expected_pin['canonical_path'] == actual_pin['canonical_path'] or
            expected_pin['identity'][:2] == actual_pin['identity'][:2]):
        raise ValueError('Expected and exported stock must be distinct files')
    et, ef = _decode(first); at, af = _decode(second)
    expected = _mesh(et); actual = _mesh(at)
    tests = (len(expected['vertices'])+len(actual['vertices']))*(len(expected['planes'])+len(actual['planes']))
    if tests > MAX_HALFSPACE_TESTS:
        raise ValueError('Vertex-to-plane comparison budget exceeded')
    ec = _halfspace_extreme(expected['vertices'],expected['planes'])
    ac = _halfspace_extreme(actual['vertices'],actual['planes'])
    if max(ec,ac) > TOLERANCE_MM:
        raise ValueError('STL shell is non-convex beyond the verification tolerance')
    ea = _halfspace_extreme(expected['vertices'],actual['planes'])
    ae = _halfspace_extreme(actual['vertices'],expected['planes'])
    if max(ea,ae) > TOLERANCE_MM:
        raise ValueError('Stock geometry differs in fixed WORLD-mm coordinates')
    _, expected_after = _read_pinned(expected_path)
    _, actual_after = _read_pinned(actual_path)
    if expected_after != expected_pin or actual_after != actual_pin:
        raise ValueError('Pinned STL files changed during comparison')
    return dict(status='PASS_CONVEX_STOCK_GEOMETRY_COMPARISON', equivalent_within_verification_tolerance=True,
        coordinate_frame='WORLD',units='mm',native_unit_input_required='CW_MM=0; caller must verify export contract',
        verification_tolerance_mm=TOLERANCE_MM,
        tolerance_basis='Fixed serialization verification budget; paired binary32 coordinate-rounding bound for abs(coordinate)<=256 mm is below 0.000053 mm. Not a manufacturing tolerance.',
        float32_paired_coordinate_rounding_bound_mm=FLOAT32_PAIRED_COORDINATE_ROUNDING_BOUND_MM,
        alignment_performed=False,rescaling_performed=False,reflection_performed=False,
        expected_file=expected_pin,actual_file=actual_pin,files_pinned_before_after=True,
        expected_mesh=dict(expected['facts'],encoding=ef,max_outward_vertex_plane_mm=ec),
        actual_mesh=dict(actual['facts'],encoding=af,max_outward_vertex_plane_mm=ac),
        mutual_containment=dict(expected_vertices_in_actual_max_signed_distance_mm=ea,
            actual_vertices_in_expected_max_signed_distance_mm=ae,vertex_plane_tests=tests,
            criterion='Both closed connected manifold shells convex within tolerance; all vertices of each satisfy every inward half-space of the other.'),
        exact_triangle_canonical_multiset_equal=expected['canonical']==actual['canonical'],
        byte_identical=expected_pin['sha256']==actual_pin['sha256'],
        bounds_and_volume_are_corroboration_only=True,production_qualified=False,
        limits=['Comparison concerns represented nominal stock geometry in caller-established WORLD mm, not an unknown native unit/frame.',
            'Differences below the fixed verification tolerance are not resolved. Symmetries yielding the same represented solid cannot reveal an earlier reflection or rotation.',
            'No BRep identity, material condition, machining recipe, holder/fixture, actual incoming WIP or production qualification.'])
