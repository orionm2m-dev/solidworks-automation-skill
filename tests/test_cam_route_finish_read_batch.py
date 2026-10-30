"""移植的离线回归测试；不连接 CAD 进程。"""
from cam_route_test_fixtures import REPO
from copy import deepcopy
from ctypes import byref, c_int, c_double, pointer
from pathlib import Path
from types import SimpleNamespace
import os, sys
import pytest
from test_read_batch_guard import env, Obj
from test_sw_cam_mill_tool_geometry import probe
from scripts import sw_cam_finish_read_batch as m
from scripts import sw_cam_route_read_batch as route_module
from scripts import sw_cam_read_batch_guard as base_batch
from scripts import sw_cam_finish_continuation as continuation
from test_cam_route_finish_continuation import install_native_fakes
'移植的离线回归测试；只使用合成数据和模拟接口。'
R = REPO

@pytest.fixture
def finish(env, monkeypatch):
    (doc, machine, op) = (env.root, Obj(), Obj())
    native = dict(doc=doc, machine=machine, operations={248: op})
    reference = dict(operations=[dict(native_id=248)])
    env.state.update(native_id=248, doc_type=1, machine_type=1)
    original = base_batch._member

    def member(obj, name, *args):
        if name == 'GetDocType':
            return env.state['doc_type']
        if name == 'MachType':
            return env.state['machine_type']
        if name == 'GetCWObjectID':
            return (env.state['native_id'], True)
        return original(obj, name, *args)
    monkeypatch.setattr(route_module, '_member', member)
    monkeypatch.setattr(m, '_member', original)
    monkeypatch.setattr(m, '_typed', base_batch._typed)
    kwargs = {k: v for (k, v) in env.kwargs.items() if k not in ('retained_objects', 'verify_retained_binding')}

    def make(**changes):
        return m.ScopedFinishReadBatch(env.sw, 'not-loaded.tlb', native_context=native, reference_state=reference, **kwargs | changes)
    return SimpleNamespace(env=env, doc=doc, machine=machine, op=op, make=make)

def test_finish_getter_has_two_full_boundaries_and_per_call_events(finish):
    g = finish.make()
    with g:
        identities = finish.env.counts['identity']
        events = finish.env.counts['event']
        for name in ('SideCutAmt', 'MillToolType', 'GetToolProfile'):
            assert g.read(finish.op, name) == 7
        assert g.typed(finish.op, 'ICWFinishMillOp3') is finish.op
        assert finish.env.counts['identity'] == identities
        assert finish.env.counts['event'] - events == 8
    assert g.require_complete()
    s = g.summary()
    assert s['complete_boundary_checks'] == 2 and s['content_hash_reads'] == 4
    assert s['retained_binding_checks'] == 2 and s['getter_calls'] == 3
    assert s['scope'] == m.SCOPE and (not s['original_route_qualification_extended'])
    assert not s['finish_native_match_verified'] and (not s['atomic_snapshot'])

@pytest.mark.parametrize('name', ['GetCurveAtIndex', 'GetFacetAtIndex'])
@pytest.mark.parametrize('index', [0, 255])
def test_exact_profile_byref_index_is_accepted(finish, name, index):
    with finish.make() as g:
        assert g.read(finish.op, name, byref(c_int(index))) == 7
    assert g.require_complete()

@pytest.mark.parametrize('bad', [0, True, byref(c_int(-1)), byref(c_int(256)), byref(c_double(1)), pointer(c_int(0)), SimpleNamespace(_obj=c_int(0))])
@pytest.mark.parametrize('name', ['GetCurveAtIndex', 'GetFacetAtIndex'])
def test_foreign_unbounded_pointer_never_reaches_native(finish, name, bad):
    with pytest.raises(ValueError):
        with finish.make() as g:
            g.read(finish.op, name, bad)
    assert finish.env.counts['native'] == 0
    with pytest.raises(ValueError):
        g.require_complete()

@pytest.mark.parametrize('name', ['SetTool', 'GenerateToolpath', 'SaveActiveDocument', 'QueryInterface', 'ActiveDoc', 'IGetActiveDoc', 'GetUnits', 'GetUseDocumentUnit'])
def test_mutation_or_global_read_is_refused(finish, name):
    with pytest.raises(ValueError):
        with finish.make() as g:
            g.read(finish.op, name)
    assert finish.env.counts['native'] == 0

@pytest.mark.parametrize('name', ['ICWApp', 'ICWDoc', 'IUnknown', 'Unknown'])
def test_foreign_interface_is_refused(finish, name):
    with pytest.raises(ValueError):
        with finish.make() as g:
            g.typed(finish.op, name)
    assert finish.env.counts['qi'] == 0

def test_unknown_owner_argument_and_dispatch_are_refused(finish):
    for (owner, args) in ((Obj(), ()), (finish.op, (Obj(),))):
        with pytest.raises(ValueError):
            with finish.make() as g:
                g.read(owner, 'GetPreviousAllowance', *args)
    calls = []
    with pytest.raises(ValueError):
        with finish.make() as g:
            g.dispatch_once(lambda : calls.append(1), persist_pending=lambda : calls.append(2))
    assert calls == [] and finish.env.counts['native'] == 0

@pytest.mark.parametrize('change', ['pid', 'document', 'source', 'pin', 'owned', 'event', 'binding'])
@pytest.mark.parametrize('phase', ['entry', 'exit'])
def test_changed_boundary_refuses_snapshot(finish, change, phase):

    def mutate():
        e = finish.env
        if change == 'pid':
            e.state['pid'] = 999
        elif change == 'document':
            e.state['document']['needs_save'] = False
        elif change == 'source':
            Path(e.source['path']).write_bytes(b'changed')
        elif change == 'pin':
            Path(e.evidence['path']).write_bytes(b'changed')
        elif change == 'binding':
            e.state['native_id'] = 999
        else:
            e.state[change + '_ok'] = False
    g = finish.make()
    if phase == 'entry':
        mutate()
    with pytest.raises(ValueError):
        with g:
            g.read(finish.op, 'SideCutAmt')
            if phase == 'exit':
                mutate()
    with pytest.raises(ValueError):
        g.require_complete()

def test_event_immediately_after_getter_stops_next_read(finish):
    finish.env.state['on_native'] = lambda : finish.env.state.update(event_ok=False)
    with pytest.raises(ValueError):
        with finish.make() as g:
            g.read(finish.op, 'SideCutAmt')
    assert finish.env.counts['native'] == 1

def test_same_full_tool_helper_and_profile_decoder_match_direct(finish, probe, monkeypatch):
    expected = probe.run()
    probe.calls.clear()
    probe.qies.clear()
    finish.env.state['result'] = probe.tool
    original = m._member
    monkeypatch.setattr(m, '_member', lambda obj, name, *args: original(obj, name, *args) if obj is finish.op else probe.read(obj, name, *args))
    monkeypatch.setattr(m, '_typed', lambda obj, name, path: probe.typed(obj, name))
    with finish.make(max_native_calls=900) as g:
        tool = g.read(finish.op, 'IGetTool')
        actual = m.read_full_mill_tool(tool, generic=probe.generic, read=g.read, typed=g.typed, diagnostic={})
    assert g.require_complete() and actual == expected
    assert actual['profile_budget'] == dict(curves=5, chains=3, islands=0)
    assert g.summary()['getter_calls'] > 30

@pytest.mark.parametrize('action', ['save', 'gtp'])
@pytest.mark.parametrize('section', ['rough_payload', 'finish_payload'])
def test_full_payload_mismatch_stops_before_save_or_gtp(tmp_path, monkeypatch, action, section):
    (loaded, args, calls) = install_native_fakes(monkeypatch, tmp_path, action)
    capture = continuation.capture_finish_recipe

    def changed(*a, **kw):
        result = capture(*a, **kw)
        result[section]['unexpected'] = 1
        return result
    monkeypatch.setattr(continuation, 'capture_finish_recipe', changed)
    result = continuation._native_action(action, None, None, None, checkpoint_receipt_path=loaded['pin']['path'], checkpoint_receipt_sha256=loaded['pin']['sha256'], checkpoint_action='save' if action == 'gtp' else 'recipe', **args)
    assert calls == [] and result['readback_verified'] is False and (not result['mutation_attempted'])
    assert not result['snapshot_diagnostics'][0].get('finish_current_checkpoint_match_verified', False)

def test_first_save_records_current_strong_parent_match_separately(tmp_path, monkeypatch):
    (loaded, args, calls) = install_native_fakes(monkeypatch, tmp_path, 'save')
    result = continuation._native_action('save', None, None, None, checkpoint_receipt_path=loaded['pin']['path'], checkpoint_receipt_sha256=loaded['pin']['sha256'], checkpoint_action='recipe', **args)
    assert calls == ['SaveActiveDocument'] and result['readback_verified']
    for diagnostic in result['snapshot_diagnostics']:
        assert diagnostic['finish_current_checkpoint_match_verified']
        assert diagnostic['finish_comparison_reference_pin'] == loaded['pin']
        assert diagnostic['original_route_qualification_extended'] is False
