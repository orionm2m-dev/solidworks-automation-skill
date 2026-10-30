"""Callback-only geometry negatives; no native application, registration or UI."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import sys
import pytest

sys.dont_write_bytecode = True
R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
D = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inventory_geometry_stage', D/'scripts/sw_cam_mill_inventory_geometry.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class Node:
    def __init__(self, *interfaces, **fields):
        self.interfaces = set(interfaces)
        self.fields = fields


def position(values=(0., 0., 0.)):
    return Node('ICWPosition', GetCoordinates=list(values))


def normal(values=(0., 0., 1.)):
    return Node('ICWUnitVector', GetCoordinates=list(values))


def curve(kind):
    return Node('ICWCurve', *({0: [], 1: ['ICWArc'], 2: ['ICWCircle']}.get(kind, [])),
        GetTypeOfCurve=kind, GetStart=position((1., 0., 0.)), GetEnd=position((0., 1., 0.)),
        GetMid=position((.7, .7, 0.)), CenterPoint=position(), IGetNormal=normal(),
        IGetRadius=1., GetRadius=1., IGetSense=-1, GetDirection=1)


def chain(curves, following=None, declared=1):
    return Node('ICWSegChain', IGetNumChains=declared, GetNumOfCurves=len(curves),
        GetCurveAtIndex=lambda index: curves[index._obj.value], IGetNextChain=following)


def island(top=None, bottom=None, wall=None):
    return Node('ICWIslandInfo', GetStartPosition=position((2., 3., 4.)), GetDepth=2.,
        IGetTopSegChain=top, IGetBottomSegChain=bottom, IGetWallSegChain=wall)


def feature(top=None, bottom=None, wall=None, islands=()):
    collection = Node('ICWDispatchCollection', Count=len(islands), Item=lambda i: islands[i]) if islands else None
    return Node('ICWFeature', 'ICWMillFeature', native_id=66, VolumeType=2, SubType=0, Shape=0,
        Suppressed=False, FeatureName='Observed feature', Axis=[0., 0., -1.], Depth=4.1,
        GetBoundParams=[5.3, 5.3, 4.1], GetStartPosition=[0., 0., 10.9],
        IGetTopSegChain=top, IGetBottomSegChain=bottom, IGetWallSegChain=wall,
        IGetIslandCount=len(islands), IGetIslands=collection)


@pytest.fixture
def probe():
    calls = []
    qies = []
    def read(obj, member, *args):
        calls.append((obj, member, args))
        value = obj.fields[member]
        return value(*args) if callable(value) else value
    def typed(obj, interface):
        qies.append((obj, interface))
        if interface not in obj.interfaces:
            raise ValueError('unsupported QI ' + interface)
        return obj
    diagnostic = {}
    budget = dict(curves=0, chains=0, islands=0)
    def run(raw):
        return g.read_mill_feature(raw, read=read, typed=typed,
            object_id=lambda obj: obj.fields['native_id'], diagnostic=diagnostic, budget=budget)
    return SimpleNamespace(run=run, diagnostic=diagnostic, budget=budget, calls=calls, qies=qies)


def test_mixed_two_chains_and_two_islands_are_retained_in_native_order(probe):
    tail = chain([curve(2)])
    first = chain([curve(0), curve(1), curve(2)], tail, declared=2)
    raw = feature(first, wall=chain([curve(0)]), islands=[
        island(chain([curve(2)])), island(chain([curve(1)]), chain([curve(0)]))])
    out = probe.run(raw)
    assert out['native_id'] == 66 and out['subtype_raw'] == 0 and out['shape_raw'] == 0
    assert [x['curve_type'] for x in out['contours']['top']['chains'][0]['curves']] == [0, 1, 2]
    assert len(out['contours']['top']['chains']) == 2
    assert out['contours']['bottom']['status'] == 'observed_not_available'
    assert out['contours']['bottom']['declared_chain_count'] is None
    assert len(out['islands']['items']) == 2 and out['islands']['collection_count'] == 2
    assert out['islands']['collection_representation_qualified'] is False
    assert out['islands']['items'][0]['start_native'] == [2., 3., 4.]
    assert probe.budget == dict(curves=8, chains=6, islands=2)
    assert probe.diagnostic['capture_complete'] is True
    assert out['physical_depth_verified'] is False and out['closed_loops_verified'] is False
    assert out['island_nesting_verified'] is False
    assert not any(name in ('GetTopFaces', 'GetBottomFaces', 'GetWallFaces') for _, name, _ in probe.calls)
    assert len([name for _, name in probe.qies if name == 'ICWDispatchCollection']) == 1
    json.dumps(probe.diagnostic, allow_nan=False)


def test_null_zero_island_collection_is_explicit_observation(probe):
    out = probe.run(feature())
    assert out['islands']['status'] == 'observed_no_islands'
    assert out['islands']['collection_representation_observed'] == 'null'
    assert out['islands']['collection_count'] is None
    assert out['islands']['items'] == []


@pytest.mark.parametrize('value', [True, 1., -1, 33])
def test_chain_declaration_strict_and_bounded(probe, value):
    raw = feature(chain([curve(0)], declared=value))
    with pytest.raises(ValueError): probe.run(raw)
    assert not any(n == 'GetCurveAtIndex' for _, n, _ in probe.calls)


@pytest.mark.parametrize('case', ['early_end', 'extra', 'cycle'])
def test_chain_declared_inventory_must_be_exact(probe, case):
    first = chain([curve(0)], declared=2 if case != 'extra' else 1)
    if case in ('extra', 'cycle'): first.fields['IGetNextChain'] = first
    with pytest.raises(ValueError): probe.run(feature(first))
    assert probe.diagnostic['capture_complete'] is False
    assert probe.diagnostic['state']['contours']['top']['chains'][0]['curves'][0]['read_complete'] is True


@pytest.mark.parametrize('case', ['positive_null', 'count_mismatch', 'unsupported_collection', 'late_count_change'])
def test_islands_fail_closed_without_unsafe_fallback(probe, case):
    raw = feature(islands=[island()])
    collection = raw.fields['IGetIslands']
    if case == 'positive_null': raw.fields['IGetIslands'] = None
    if case == 'count_mismatch': collection.fields['Count'] = 0
    if case == 'unsupported_collection': collection.interfaces.clear()
    if case == 'late_count_change':
        values = iter([1, 2]); collection.fields['Count'] = lambda: next(values)
    with pytest.raises(ValueError): probe.run(raw)
    assert probe.diagnostic['capture_complete'] is False
    if case == 'unsupported_collection':
        assert probe.qies.count((collection, 'ICWDispatchCollection')) == 1
        assert not any(obj is collection and n == 'Count' for obj, n, _ in probe.calls)
    assert not any(n in ('GetTopFaces', 'GetBottomFaces', 'GetWallFaces') for _, n, _ in probe.calls)


@pytest.mark.parametrize('field,value', [('Depth', float('nan')), ('Depth', True),
    ('Axis', [0., False, -1.]), ('GetBoundParams', [1., float('inf'), 2.]),
    ('Suppressed', 0), ('SubType', True), ('Shape', 1.), ('native_id', True)])
def test_feature_raw_types_rejected(probe, field, value):
    raw = feature(); raw.fields[field] = value
    with pytest.raises(ValueError): probe.run(raw)
    assert probe.diagnostic['capture_complete'] is False


@pytest.mark.parametrize('kind,field,value', [(2, 'GetRadius', 0.), (2, 'GetRadius', float('nan')),
    (1, 'IGetRadius', -1.), (1, 'IGetSense', True), (2, 'GetDirection', 1.),
    (1, 'IGetRadius', True)])
def test_arc_circle_invalid_fields_rejected_with_partial_diagnostic(probe, kind, field, value):
    c = curve(kind); c.fields[field] = value
    with pytest.raises(ValueError): probe.run(feature(chain([c])))
    item = probe.diagnostic['state']['contours']['top']['chains'][0]['curves'][0]
    assert item['curve_type'] == kind and item['read_complete'] is False


@pytest.mark.parametrize('kind', [4, 99, True, 1.])
def test_unknown_or_coerced_curve_type_never_reinterpreted(probe, kind):
    c = curve(0); c.fields['GetTypeOfCurve'] = kind
    with pytest.raises(ValueError): probe.run(feature(chain([c])))
    assert not any(n == 'GetStart' for _, n, _ in probe.calls)


def test_nonfinite_curve_position_rejected(probe):
    c = curve(0); c.fields['GetStart'] = position((float('inf'), 0., 0.))
    with pytest.raises(ValueError): probe.run(feature(chain([c])))


@pytest.mark.parametrize('scope', ['chain', 'global', 'islands'])
def test_caps_stop_before_indexed_reads(probe, scope):
    raw = feature(chain([curve(0)]))
    if scope == 'chain': raw.fields['IGetTopSegChain'].fields['GetNumOfCurves'] = 257
    if scope == 'global': probe.budget['curves'] = 8192
    if scope == 'islands':
        raw = feature(); raw.fields['IGetIslandCount'] = 65
    with pytest.raises(ValueError): probe.run(raw)
    assert not any(n in ('GetCurveAtIndex', 'Item') for _, n, _ in probe.calls)


def test_shared_global_budget_accumulates_across_features(probe):
    probe.run(feature(chain([curve(0), curve(2)])))
    probe.run(feature(chain([curve(1)])))
    assert probe.budget['curves'] == 3 and probe.budget['chains'] == 2


def test_curve_count_change_is_not_reported_complete(probe):
    first = chain([curve(0)]); values = iter([1, 2]); first.fields['GetNumOfCurves'] = lambda: next(values)
    with pytest.raises(ValueError, match='curve count changed'): probe.run(feature(first))
    assert probe.diagnostic['capture_complete'] is False


@pytest.mark.parametrize('value', [False, 0, [], 'unavailable'])
def test_scalar_null_substitutes_are_not_contour_absence(probe, value):
    with pytest.raises(ValueError): probe.run(feature(top=value))


@pytest.mark.parametrize('field', ['Suppressed', 'FeatureName'])
def test_unexpected_interface_in_scalar_does_not_poison_partial_json(probe, field):
    raw = feature(); raw.fields[field] = Node('unexpected')
    with pytest.raises(ValueError): probe.run(raw)
    json.dumps(probe.diagnostic, allow_nan=False)
