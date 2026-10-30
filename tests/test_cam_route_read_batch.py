"""移植的离线回归测试；不连接 CAD 进程。"""
from cam_route_test_fixtures import REPO
import ast
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
import scripts
from test_read_batch_guard import env, Obj
from scripts import sw_cam_route_read_batch as m
from scripts import sw_cam_read_batch_guard as old
'移植的离线回归测试；只使用合成数据和模拟接口。'
ROOT = REPO

@pytest.fixture
def route(env, monkeypatch):
    (doc, machine, op) = (env.root, Obj(), Obj())
    native = {'doc': doc, 'machine': machine, 'operations': {247: op}}
    ref = {'operations': [{'native_id': 247}]}
    env.state.update(native_id=247, doc_type=1, machine_type=1)
    old_native = old._member

    def member(obj, name, *args):
        if name == 'GetDocType':
            assert obj is doc
            return env.state['doc_type']
        if name == 'MachType':
            assert obj is machine
            return env.state['machine_type']
        if name == 'GetCWObjectID':
            assert obj is doc and args == (op,)
            return (env.state['native_id'], True)
        return old_native(obj, name, *args)
    monkeypatch.setattr(m, '_member', member)
    monkeypatch.setattr(m, '_typed', old._typed)
    kwargs = {k: v for (k, v) in env.kwargs.items() if k not in ('retained_objects', 'verify_retained_binding')}

    def make(**changes):
        return m.ScopedCamRouteReadBatch(env.sw, 'not-loaded.tlb', native_context=native, reference_state=ref, **kwargs | changes)
    return SimpleNamespace(env=env, doc=doc, machine=machine, op=op, native=native, ref=ref, make=make)

def test_allowed_reads_keep_per_getter_events_and_strong_boundaries(route):
    g = route.make()
    with g:
        before = route.env.counts['identity']
        for _ in range(3):
            assert g.read(route.op, 'OpernType') == 7
        assert g.typed(route.op, 'ICWMillOperation') is route.op
        assert route.env.counts['identity'] == before
        with pytest.raises(ValueError):
            g.require_complete()
    assert g.require_complete()
    s = g.summary()
    assert s['complete_boundary_checks'] == 2 and s['content_hash_reads'] == 4
    assert s['binding_native_calls'] == 6 and s['retained_binding_checks'] == 2
    assert s['getter_calls'] == 3 and s['query_interface_calls'] == 1
    assert not s['reacquired_wrapper_identity_comparison']

@pytest.mark.parametrize('phase', ['entry', 'exit'])
@pytest.mark.parametrize('key,value', [('native_id', 999), ('doc_type', True), ('machine_type', 2)])
def test_numeric_root_binding_fails_closed(route, key, value, phase):
    g = route.make()
    if phase == 'entry':
        route.env.state[key] = value
    with pytest.raises(ValueError):
        with g:
            g.read(route.op, 'OpernType')
            if phase == 'exit':
                route.env.state[key] = value
    with pytest.raises(ValueError):
        g.require_complete()
    assert g.summary()['invalid']

@pytest.mark.parametrize('name', ['QueryInterface', 'ActiveDoc', 'IGetActiveDoc', 'GetUnits', 'GetUseDocumentUnit', 'Save', 'Save3', 'GenerateToolpath', 'SetTool', 'SetTypeOfFirstCutZ', 'GetRecord', 'GetToolProfile', 'unknown'])
def test_forbidden_members_are_not_dispatched(route, name):
    g = route.make()
    before = route.env.counts['native']
    with pytest.raises(ValueError, match='scope'):
        with g:
            g.read(route.op, name)
    assert route.env.counts['native'] == before
    with pytest.raises(ValueError):
        g.require_complete()

@pytest.mark.parametrize('name', ['ICWApp4', 'ICWDoc3', 'ICWMachine', 'ICWCurve', 'IUnknown'])
def test_no_global_interface_discovery(route, name):
    with pytest.raises(ValueError, match='scope'):
        with route.make() as g:
            g.typed(route.op, name)
    assert route.env.counts['qi'] == 0

def test_batch_does_not_dispatch(route):
    attempted = []
    with pytest.raises(ValueError, match='cannot dispatch'):
        with route.make() as g:
            g.dispatch_once(lambda : attempted.append(True), persist_pending=lambda : None)
    assert not attempted

def test_unknown_owner_and_native_argument_rejected(route):
    for (owner, args) in ((Obj(), ()), (route.doc, (Obj(),))):
        with pytest.raises(ValueError, match='retained document graph'):
            with route.make() as g:
                g.read(owner, 'GetCWObjectID', *args)

def test_budget_and_events_checked_per_read(route):
    with pytest.raises(ValueError, match='budget'):
        with route.make(max_native_calls=1) as g:
            g.read(route.op, 'OpernType')
            g.typed(route.op, 'ICWMillOperation')
    with pytest.raises(ValueError, match='event'):
        with route.make() as g:
            route.env.state['on_native'] = lambda : route.env.state.update(event_ok=False)
            g.read(route.op, 'OpernType')

def test_tuple_variant_preserved_without_interpretation(route):
    raw = ((1.0, 2.0, 3.0), False, 'raw')
    route.env.state['result'] = raw
    with route.make() as g:
        assert g.read(route.op, 'GetEntryStartPtX') is raw
    assert g.require_complete()

def test_idispatch_qi_is_counted_and_retained(route):

    class Feature:

        def QueryInterface(self, interface):
            from comtypes.automation import IDispatch
            assert interface is IDispatch
            return child
    feature = Feature()
    child = Obj()
    route.env.state['result'] = feature
    with route.make() as g:
        g.read(route.doc, 'GetCWObjectFromID', 1, 244)
        assert g.feature_dispatch(feature) is child
        g.read(child, 'GetCoordinates')
    assert g.require_complete() and g.summary()['query_interface_calls'] == 1

def test_helper_native_context_avoids_global_lookup_and_counts_feature_qi(monkeypatch):
    from scripts import sw_cam_completed_sandvik_assignment as a
    (feature, op) = (Obj(), Obj())
    native = {'doc': Obj(), 'machine': Obj(), 'operations': {247: op}}
    ref = {'operations': [dict(native_id=247, linked_feature_ids=[244], mill_operation_type=0, suppressed=False)]}

    def forbidden(*args, **kw):
        raise AssertionError('global or uncounted QI must not execute')
    monkeypatch.setattr(a, 'resolve_existing_context', forbidden)
    monkeypatch.setattr(a, 'read_route_operations', lambda *args, **kw: None)

    def levels(f, o, *, native_read, typed, getter, report):
        assert native_read('QueryInterface.IDispatch.feature', forbidden, interface=True) is feature
        report['complete'] = True
    monkeypatch.setattr(a, 'read_mill_level_values', levels)
    monkeypatch.setattr(a, 'read_firstcut_settings', lambda *args: {'firstcut': 1})
    monkeypatch.setattr(a, 'read_rough_entry_parameters', lambda *args, **kw: {'entry': 1})
    count = []
    result = a.capture_assignment_snapshot(Obj(), read=lambda obj, name, *args: (feature, True) if name == 'GetCWObjectFromID' else (244, True), typed=lambda obj, name: obj, reference_state=ref, current_document={'path': 'part'}, source_sha256='a' * 64, target_feature_native_id=244, target_operation_native_id=247, boundary=lambda : None, diagnostic={}, native_context=native, feature_dispatch_reader=lambda obj: count.append(obj) or obj)
    assert result[1] is native and count == [feature]

def test_candidate_supplied_metric_scope_avoids_global_lookup(monkeypatch):
    from scripts import sw_cam_completed_sandvik_assignment as a
    tool = Obj()
    native = {'doc': Obj(), 'machine': Obj()}
    fields = {key: value for (key, value) in a.FIELDS}
    holder = {name: i for (i, name) in enumerate(a.HOLDER_FIELDS)}
    reference = {'tools': [{'native_id': 263}], 'tool': {'mt_path_raw': 'candidate.mt'}, 'holder_fields': holder}
    monkeypatch.setattr(a, '_items', lambda *args: [tool])
    monkeypatch.setattr(a, '_object_id', lambda *args: 263)
    monkeypatch.setattr(a, 'check_document_target', lambda *args, **kw: None)

    def forbidden(*args, **kw):
        raise AssertionError('global unit lookup forbidden')
    monkeypatch.setattr(a, 'read_document_cam_unit_scope', forbidden)

    def read(obj, name, *args):
        if name in ('ActiveDoc', 'GetUnits', 'GetUseDocumentUnit'):
            forbidden()
        if name in fields:
            return fields[name]
        if name in holder:
            return holder[name]
        return {'IsMillTool': True, 'ToolType': 14, 'GetToolName': 'candidate.mt'}.get(name, tool)
    units = {'scope': 'already read under strong guard'}
    result = a.read_assignment_candidate(native, Obj(), Obj(), read=read, typed=lambda obj, name: obj, expected_candidate_tool_native_id=263, reference=reference, observation_pin={}, firstcut={}, diagnostic={}, metric_scope=units)
    assert result['metric_scope'] == units and result['metric_scope'] is not units
