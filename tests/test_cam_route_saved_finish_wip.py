"""移植的离线回归测试；不连接 CAD 进程。"""
from cam_route_test_fixtures import REPO, state as synthetic_state, payload as synthetic_payload, arguments
from scripts import sw_cam_saved_finish_wip as m
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util, json, sys
from unittest.mock import Mock
import pytest
'移植的离线回归测试；只使用合成数据和模拟接口。'
K = Path.cwd()
SAVED = K / 'synthetic_checkpoint.json'
SAVED_SHA = 'b' * 64
ARGS = arguments()
A = dict(ARGS, addin_clsid='{00000000-0000-0000-0000-000000000001}', module_sha256='c' * 64)
DATA = dict(after_context=synthetic_state(True), after_payload=synthetic_payload())
read = lambda p: json.loads(Path(p).read_text(encoding='utf-8-sig'))
ARGS = {k: v for (k, v) in A.items() if k not in {'addin_clsid', 'module_sha256', 'checkpoint_receipt_path', 'checkpoint_receipt_sha256'}}

@pytest.mark.parametrize('change', ['rough_count', 'finish_count', 'extra_generated', 'suppressed', 'order', 'dirty', 'bool_count'])
def test_route_delta_refused(change):
    state = deepcopy(DATA['after_context'])
    rows = state['operations']
    if change == 'rough_count':
        rows[-2]['toolpath_record_counts'] = [190]
    if change == 'finish_count':
        rows[-1]['toolpath_record_counts'] = [75]
    if change == 'extra_generated':
        rows[0].update(toolpath_generated=True, toolpath_record_counts=[1])
    if change == 'suppressed':
        rows[0]['suppressed'] = True
    if change == 'order':
        rows.reverse()
    if change == 'dirty':
        state['document']['needs_save'] = True
    if change == 'bool_count':
        rows[-1]['toolpath_record_counts'] = [True]
    with pytest.raises(ValueError):
        m.route_scope(state, ARGS)

def test_marker_not_reset_by_new_receipt_path():
    assert m.wip_marker(ARGS) == m.wip_marker(dict(ARGS, receipt_path=str(K / 'new_receipt.json'), checkpoint_receipt_sha256='f' * 64))
    assert m.wip_marker(ARGS) != m.wip_marker(dict(ARGS, expected_source_sha256='f' * 64))

@pytest.fixture
def fixture(tmp_path, monkeypatch):
    source = tmp_path / 'part.SLDPRT'
    source.write_bytes(b'saved')
    args = dict(ARGS, expected_document_path=str(source), receipt_path=str(tmp_path / 'receipt.json'), expected_source_sha256=m._file_hash(source))
    state = deepcopy(DATA['after_context'])
    state['saved_file_sha256'] = args['expected_source_sha256']
    payload = deepcopy(DATA['after_payload'])
    loaded = dict(state=state, payload=payload['rough'], finish_payload=payload['finish'], pins=[], lineage_pins=[], pin={'path': str(SAVED), 'sha256': SAVED_SHA}, holder_recipe={}, checkpoint_action='save', historical_only=False)
    monkeypatch.setattr(m, 'load_saved_finish', lambda *a, **kw: loaded)
    observed = dict(state=state, native={'machine': object()}, rough_payload=payload['rough'], finish_payload=payload['finish'])
    control = SimpleNamespace(calls=0, captures=0, return_value=True, raise_native=False, before_mutation=None, after_mutation=None, event_error=False, pin_changed=False, output_mutation=False, compensation_change=False)

    class Guard:

        def __enter__(self):
            if control.pin_changed:
                raise ValueError('changed history pin')
            return self

        def __exit__(self, *a):
            return False

        def typed(self, obj, name):
            assert name == 'ICWMachine5'
            return obj

        def dispatch_once(self, invoke, persist_pending):
            ctx.files()
            ctx.events()
            persist_pending()
            return invoke()

        def summary(self):
            return dict(claimed=True, invalid=False)

    class Context:

        def __init__(self, *a):
            self.loaded = loaded
            self.app = None
            self.events = a[-1]

        def files(self):
            if control.pin_changed:
                raise ValueError('changed history pin')

        def identity(self):
            return state['document']

        def guard(self):
            return Guard()
    ctx = None

    def context(*a):
        nonlocal ctx
        ctx = Context(*a)
        return ctx
    monkeypatch.setattr(m, 'FinishContinuationContext', context)
    monkeypatch.setattr(m, '_bootstrap', lambda *a: object())

    class Session:

        def __init__(self, *a):
            self.active = False

        def __enter__(self):
            self.active = True
            return self

        def __exit__(self, *a):
            self.active = False

        def summary(self):
            return dict(subscribed=True, active=self.active, disconnected=not self.active, event_count=1 if control.event_error else 0)
    import scripts.sw_cam_events as ev
    monkeypatch.setattr(ev, 'CamMessageSession', Session)

    def capture(*a, **kw):
        control.captures += 1
        x = deepcopy(observed)
        cb = control.before_mutation if control.captures == 1 else control.after_mutation
        if cb:
            cb(x)
        if control.output_mutation and control.captures == 2:
            (tmp_path / 'wip' / 'wip.stl').write_bytes(b'changed output')
        return x
    monkeypatch.setattr(m, 'capture_finish_recipe_batch', capture)

    def compensation(ctx, native, args, diagnostic, persist):
        diagnostic['raw_compensation'] = [dict(operation_native_id=247, raw_values={'GetTlpComp': 0, 'GetCNCComp': 1}), dict(operation_native_id=248, raw_values={'GetTlpComp': 0, 'GetCNCComp': 1})]
        if control.compensation_change and control.captures == 2:
            diagnostic['raw_compensation'][1]['raw_values']['GetCNCComp'] = 2
        diagnostic['compensation_complete'] = True
        persist()
        return diagnostic['raw_compensation']
    monkeypatch.setattr(m, 'read_compensation', compensation)

    def member(obj, name, *params):
        assert name == 'CreateSTLOfWIPs2'
        assert list(params) == [str(tmp_path / 'wip') + '\\', 'wip.stl', '', 0, 0]
        control.calls += 1
        if control.raise_native:
            raise RuntimeError('native failure')
        (tmp_path / 'wip' / 'wip.stl').write_bytes(b'software stock mesh')
        return control.return_value
    monkeypatch.setattr(m, '_member', member)

    def run():
        return m.export_saved_finish_wip(object(), 'clsid', 'typelib', checkpoint_receipt_path=str(SAVED), checkpoint_receipt_sha256=SAVED_SHA, project_root=str(tmp_path), output_dir=str(tmp_path / 'wip'), acknowledge_machine_scope=True, **args)
    return SimpleNamespace(args=args, state=state, payload=payload, loaded=loaded, observed=observed, control=control, run=run, root=tmp_path)

def test_success_reuses_core_without_generation_or_save(fixture):
    r = fixture.run()
    assert r['status'] == 'review_required' and r['readback_verified'] and r['export_files_verified']
    assert fixture.control.calls == 1 and fixture.control.captures == 2 and (r['native_return_type'] == 'bool')
    assert r['compensation_readback_verified'] is True
    assert r['native_scope'] == 'all_wip_parts_all_setups' and r['single_operation_scope_claimed'] is False
    assert all((r[k] is False for k in ('GTP_attempted', 'GOP_attempted', 'AFR_attempted', 'tool_edit_attempted', 'model_saved', 'NC_export_attempted', 'material_removal_verified', 'full_circle_semantics_verified', 'mesh_resolution_qualified', 'production_qualified')))
    assert all((d['observed_payload'] == fixture.payload and d['saved_checkpoint_match_verified'] for d in r['capture_diagnostics']))

@pytest.mark.parametrize('native_result', [False, 0, 1, None, 'True'])
def test_non_boolean_true_stops_before_readback(fixture, native_result):
    fixture.control.return_value = native_result
    r = fixture.run()
    assert r['status'] == 'uncertain' and (not r['readback_verified'])
    assert fixture.control.calls == 1 and fixture.control.captures == 1
    with pytest.raises(ValueError):
        fixture.run()
    assert fixture.control.calls == 1

def test_native_exception_no_retry_no_readback(fixture):
    fixture.control.raise_native = True
    r = fixture.run()
    assert r['status'] == 'uncertain' and r['native_dispatch_pending']
    assert fixture.control.captures == 1 and fixture.control.calls == 1
    with pytest.raises(ValueError):
        fixture.run()

def test_before_payload_mismatch_persisted_blocks_dispatch(fixture):
    fixture.control.before_mutation = lambda x: x['finish_payload']['details']['finish']['SideCutAmt'].update(raw=99.0)
    r = fixture.run()
    assert r['status'] == 'error' and fixture.control.calls == 0
    saved = read(fixture.args['receipt_path'])
    assert saved['capture_diagnostics'][0]['observed_payload']['finish']['details']['finish']['SideCutAmt']['raw'] == 99.0
    assert saved['capture_diagnostics'][0]['saved_checkpoint_match_verified'] is False

def test_after_payload_mismatch_persisted_uncertain(fixture):
    fixture.control.after_mutation = lambda x: x['finish_payload']['details']['finish']['SideCutAmt'].update(raw=99.0)
    r = fixture.run()
    assert r['status'] == 'uncertain' and fixture.control.calls == 1
    saved = read(fixture.args['receipt_path'])
    assert saved['capture_diagnostics'][1]['observed_payload']['finish']['details']['finish']['SideCutAmt']['raw'] == 99.0
    assert not saved['readback_verified']

def test_output_change_after_readback_rejected(fixture):
    fixture.control.output_mutation = True
    r = fixture.run()
    assert r['status'] == 'uncertain' and (not r['readback_verified'])

def test_event_blocks_dispatch(fixture):
    fixture.control.event_error = True
    r = fixture.run()
    assert r['status'] == 'error' and fixture.control.calls == 0

def test_history_file_change_blocks_dispatch(fixture):
    fixture.control.pin_changed = True
    r = fixture.run()
    assert r['status'] == 'error' and fixture.control.calls == 0

def test_existing_receipt_not_overwritten(fixture):
    p = Path(fixture.args['receipt_path'])
    p.write_bytes(b'prior evidence')
    with pytest.raises(ValueError):
        fixture.run()
    assert p.read_bytes() == b'prior evidence' and fixture.control.calls == 0

def test_existing_marker_not_reset_by_new_output(fixture):
    p = m.wip_marker(fixture.args)
    p.write_bytes(b'uncertain prior attempt')
    with pytest.raises(ValueError):
        fixture.run()
    assert p.read_bytes() == b'uncertain prior attempt' and fixture.control.calls == 0

def valid_request():
    p = dict(A, expected_source_sha256=ARGS['expected_source_sha256'], module_sha256=m.self_pin()['sha256'], checkpoint_receipt_path=str(SAVED), checkpoint_receipt_sha256=SAVED_SHA, project_root=str(K), output_dir=str(K / 'future_wip'), acknowledge_machine_scope=True)
    return dict(action='export_wip', params=p)

@pytest.mark.parametrize('change', ['action', 'extra', 'pidbool', 'ack', 'module', 'relative', 'save'])
def test_cli_rejects_unsupported_input_before_native(change, monkeypatch):
    request = valid_request()
    if change == 'action':
        request['action'] = 'gtp'
    if change == 'save':
        request['action'] = 'save'
    if change == 'extra':
        request['params']['script'] = 'arbitrary'
    if change == 'pidbool':
        request['params']['process_id'] = True
    if change == 'ack':
        request['params']['acknowledge_machine_scope'] = False
    if change == 'module':
        request['params']['module_sha256'] = 'f' * 64
    if change == 'relative':
        request['params']['output_dir'] = 'relative'
    loader = Mock()
    monkeypatch.setattr(m, 'load_saved_finish', loader)
    with pytest.raises(ValueError):
        m.dispatch_request(request)
    loader.assert_not_called()

def test_cli_exact_request_accepted_offline():
    assert m.validate_request(valid_request())['finish_operation_native_id'] == 248

@pytest.mark.parametrize('which', ['live', 'history'])
def test_real_context_hash_guards_changed_evidence(tmp_path, which):
    live = tmp_path / 'uncertain100_marker.json'
    history = tmp_path / 'completed_old_receipt.json'
    live.write_text('original')
    history.write_text('original')
    pins = [dict(path=str(live), sha256=m._file_hash(live))]
    historical = [dict(path=str(history), sha256=m._file_hash(history))]
    loaded = dict(state=deepcopy(DATA['after_context']), pins=pins, lineage_pins=historical, historical_only=False)
    ctx = m.FinishContinuationContext(loaded, dict(ARGS), None, 'typelib', None, lambda : None)
    ctx.files()
    (live if which == 'live' else history).write_text('changed')
    with pytest.raises(ValueError):
        ctx.files()

def test_real_context_source_hash_drift_refused(tmp_path, monkeypatch):
    import scripts.sw_cam_route_checkpoint as base
    p = tmp_path / 'part.SLDPRT'
    p.write_bytes(b'original')
    args = dict(ARGS, expected_document_path=str(p), expected_source_sha256=m._file_hash(p))
    loaded = dict(state=deepcopy(DATA['after_context']), historical_only=False)
    ctx = m.FinishContinuationContext(loaded, args, None, 'typelib', None, lambda : None)
    monkeypatch.setattr(ctx, 'owned', lambda : None)
    monkeypatch.setattr(base, '_member', lambda *a: args['process_id'])
    monkeypatch.setattr(base, 'raw_part_identity', lambda *a: deepcopy(loaded['state']['document']))
    ctx.identity()
    p.write_bytes(b'changed')
    with pytest.raises(ValueError):
        ctx.identity()

def test_compensation_change_after_export_rejected_and_persisted(fixture):
    fixture.control.compensation_change = True
    r = fixture.run()
    assert r['status'] == 'uncertain' and (not r['readback_verified']) and (not r['compensation_readback_verified'])
    assert fixture.control.calls == 1
    assert read(fixture.args['receipt_path'])['capture_diagnostics'][1]['raw_compensation'][1]['raw_values']['GetCNCComp'] == 2

@pytest.mark.parametrize('value', [0, 1, -1, True, None, 0.0, '0'])
def test_compensation_reader_strict_raw_integer_and_durable_observation(monkeypatch, value):
    ops = {247: object(), 248: object()}
    values = []
    diag = {}
    saved = []

    class Guard:

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def typed(self, obj, name):
            assert name in ('ICWMillOperation', 'ICWNCParam')
            return obj

        def read(self, obj, name):
            assert name in ('IGetNCParam', 'GetTlpComp', 'GetCNCComp')
            values.append(name)
            return obj if name == 'IGetNCParam' else value

        def summary(self):
            return {'calls': len(values)}
    ctx = SimpleNamespace(guard=lambda : Guard())
    monkeypatch.setattr(m, '_object_id', lambda doc, raw, read: next((k for (k, v) in ops.items() if raw is v)))
    invoke = lambda : m.read_compensation(ctx, dict(operations=ops, doc=object()), ARGS, diag, lambda : saved.append(deepcopy(diag)))
    if type(value) is int:
        result = invoke()
        assert len(result) == 2 and diag['compensation_complete']
        assert [x['operation_native_id'] for x in result] == [247, 248]
        assert all((x['raw_values']['GetTlpComp']['raw'] == value for x in result))
        assert all((x['raw_values']['GetCNCComp']['semantics_qualified'] is False for x in result))
    else:
        with pytest.raises(ValueError):
            invoke()
        assert saved[-1]['raw_compensation'][0]['raw_values']['GetTlpComp']['raw'] == value
        assert diag['compensation_complete'] is False

