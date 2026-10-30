"""Independent native-boundary and publication-failure checks with synthetic state."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from test_checkpoint_reconfigure import m, case, fixture, run, Backend


def bind_real_native_methods(c, monkeypatch):
    from scripts import sw_cam, sw_cam_mill_route_context
    controls = SimpleNamespace(read_override=None, tool_override=None, events=[], calls=[])
    op, feature, face, dispatch, mill, doc = (object() for _ in range(6))

    class Guard:
        def __enter__(self):
            c.b.boundary()
            return self
        def __exit__(self, *args):
            c.b.boundary()
        def read(self, obj, name, *args):
            assert obj is face and name == m.GETTER and args == (dispatch,)
            controls.events.append(('get', name))
            value = controls.read_override
            return deepcopy(c.b.settings['face'][m.GETTER] if value is None else value)
        def typed(self, obj, name):
            assert obj is op and name == 'ICWMillOperation'
            return mill
        def dispatch_once(self, call, *, persist_pending):
            c.b.boundary()
            persist_pending()
            controls.events.append(('pending', c.j.report['current_action']))
            name = c.j.report['current_action']
            for p in (c.j.receipt, c.j.marker):
                r = json.loads(p.read_text())
                assert r['actions'][name]['native_dispatch_pending'] is True
            return call()

    native = SimpleNamespace(ctx=SimpleNamespace(guard=Guard),
        _resolve=lambda guard:(op, feature), _face=lambda guard, value:face,
        _feature_dispatch=lambda guard, value:dispatch, report=c.j.report,
        native={'doc':doc}, expected_tool=deepcopy(c.b.expected_tool))

    def member(obj, name, *args):
        controls.calls.append((name,args));controls.events.append(('native',name))
        c.b.calls[name] += 1
        if name == m.MEMBER:
            assert obj is face and len(args) == 3 and args[0] is dispatch
            assert type(args[1]) is float and args[1] == 8.0 and args[2] is False
            c.b.settings['face'][m.GETTER] = [args[1],args[2]]
            if c.b.invalidate:
                row=next(x for x in c.b.state['operations'] if x['native_id']==267)
                row.update(toolpath_generated=False,toolpath_record_counts=[])
        else:
            assert obj is mill and name == 'GenerateToolpath' and not args
            row=next(x for x in c.b.state['operations'] if x['native_id']==267)
            row.update(toolpath_generated=True,toolpath_record_counts=[101])
        return c.b.returns.get(name,0)

    def tool_reader(value, owner, read, typed):
        assert value is op and owner is doc
        return deepcopy(controls.tool_override if controls.tool_override is not None else c.b.expected_tool), None

    monkeypatch.setattr(sw_cam,'_member',member)
    monkeypatch.setattr(sw_cam_mill_route_context,'read_generic_tool',tool_reader)
    c.b.write_lead=lambda pending:m.NativeBackend.write_lead(native,pending)
    c.b.generate=lambda pending:m.NativeBackend.generate(native,pending)
    return controls


@pytest.mark.parametrize('invalidate',[False,True])
def test_real_native_writer_and_gtp_dispatch_bind_feature_and_pending(case,monkeypatch,invalidate):
    c=case;c.b.invalidate=invalidate;control=bind_real_native_methods(c,monkeypatch)
    result=run(c)
    assert result['readback_verified'] is True
    assert [row[0] for row in control.calls]==[m.MEMBER,'GenerateToolpath']
    for name in (m.MEMBER,'GenerateToolpath'):
        assert control.events.index(('pending',name)) < control.events.index(('native',name))
    assert all(c.b.calls[name]==1 for name in m.ACTIONS)


@pytest.mark.parametrize('value',[[3.0,False],[2.0,True],[2,False],None])
def test_real_setter_rejects_stale_or_untyped_immediate_lead(case,monkeypatch,value):
    control=bind_real_native_methods(case,monkeypatch)
    control.read_override=value if value is not None else ['invalid',False]
    result=run(case)
    assert result['readback_verified'] is False
    assert all(case.b.calls[name]==0 for name in m.ACTIONS)
    assert not case.j.marker.exists()


@pytest.mark.parametrize('kind',['lead','tool','readback'])
def test_real_gtp_rechecks_new_lead_tool_and_setter_receipt(case,monkeypatch,kind):
    control=bind_real_native_methods(case,monkeypatch)
    original=case.b.read_narrow
    def observe(label):
        value=original(label)
        if label=='configured':
            if kind=='lead':control.read_override=[2.0,False]
            elif kind=='tool':control.tool_override=dict(case.b.expected_tool,native_id=999)
            else:case.j.report['actions'][m.MEMBER]['readback_verified']=False
        return value
    case.b.read_narrow=observe
    result=run(case)
    assert result['readback_verified'] is False
    assert case.b.calls[m.MEMBER]==1
    assert case.b.calls['GenerateToolpath']==case.b.calls['SaveActiveDocument']==0
    assert [x[0] for x in control.calls]==[m.MEMBER]


@pytest.mark.parametrize('stage',['source_transition','terminal'])
def test_save_publication_failure_never_replays_saved_mutation(case,stage):
    original=case.j.persist;fired=False
    def persist():
        nonlocal fired
        r=case.j.report
        trigger=('source_transition' in r if stage=='source_transition' else r.get('readback_verified') is True)
        if trigger and not fired:
            fired=True
            raise PermissionError('Synthetic publication contention after native Save')
        return original()
    case.j.persist=persist
    source_before=case.f.source.read_bytes()
    result=run(case)
    assert fired and result['readback_verified'] is False and result['status']=='uncertain'
    assert case.f.source.read_bytes()!=source_before
    assert all(case.b.calls[name]==1 for name in m.ACTIONS)
    assert result['save_stage']['native_return_type']=='int' and result['save_stage']['native_return_value']==0
    assert result['save_stage']['native_call_returned'] is True
    assert result['save_stage']['save_pending'] is False
    persisted=json.loads(case.j.receipt.read_text())
    assert persisted['readback_verified'] is False
    marker_before=case.j.marker.read_bytes()
    renamed=m.Journal(dict(result,actions={}),case.f.root/'renamed-after-save.json',case.j.marker)
    other=Backend(case.f,renamed)
    retry=m.run_backend(other,renamed,case.f.loaded)
    assert retry['readback_verified'] is False and other.calls['start']==0
    assert case.j.marker.read_bytes()==marker_before


def test_unchanged_observation_publication_does_not_rewrite_terminal_marker(case,monkeypatch):
    result=run(case);assert result['readback_verified']
    original=m._write_receipt;writes=[]
    def record(path,*args,**kwargs):
        writes.append(Path(path))
        return original(path,*args,**kwargs)
    monkeypatch.setattr(m,'_write_receipt',record)
    before=case.j.marker.read_bytes()
    case.j.persist();case.j.persist()
    assert case.j.marker not in writes
    assert writes==[case.j.receipt,case.j.receipt]
    assert case.j.marker.read_bytes()==before


def test_changed_marker_after_native_return_stops_following_actions(case):
    original=case.b.write_lead
    def mutate(pending):
        result=original(pending)
        case.j.marker.write_bytes(b'external marker alteration')
        return result
    case.b.write_lead=mutate
    result=run(case)
    assert result['readback_verified'] is False and result['status']=='uncertain'
    assert case.b.calls[m.MEMBER]==1
    assert case.b.calls['GenerateToolpath']==case.b.calls['SaveActiveDocument']==0
    assert case.j.marker.read_bytes()==b'external marker alteration'


@pytest.mark.parametrize('field', ['count_before','save_transition'])
def test_terminal_provenance_rejects_booleans_for_integer_observations(case,field):
    result=run(case);assert result['readback_verified']
    bad=deepcopy(result)
    if field=='count_before':bad['automatic_count_observation']['before']=True
    else:bad['source_transition']['strict_save_return']=False
    with pytest.raises(ValueError):m.validate_terminal(bad)