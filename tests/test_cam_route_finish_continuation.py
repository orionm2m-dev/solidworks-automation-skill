"""移植的离线回归测试；不连接 CAD 进程。"""
from cam_route_test_fixtures import REPO, state as synthetic_state, payload as synthetic_payload
from copy import deepcopy
from pathlib import Path
import json, types
import pytest
from scripts import sw_cam_finish_continuation_evidence as ev
from scripts import sw_cam_finish_continuation as sut
'移植的离线回归测试；只使用合成数据和模拟接口。'

def data(tmp_path):
    state = synthetic_state()
    state['document']['path'] = str(tmp_path / 'part.SLDPRT')
    state['saved_file_sha256'] = 'a' * 64
    payload = synthetic_payload()['rough']
    args = dict(process_id=23824, expected_document_path=state['document']['path'], expected_source_sha256='a' * 64, finish_operation_native_id=248, finish_tool_native_id=249, expected_candidate_tool_native_id=263, target_feature_native_id=244, target_operation_native_id=247, target_operation_setup_native_id=93, qualification_only=True, acknowledge_disposable_copy=True, software_only_experiment=True, message_policy='vendor_default', receipt_path=str(tmp_path / 'result.json'))
    runtime = REPO / 'scripts'
    implementation = [dict(path=str(runtime / n), sha256=ev._file_hash(runtime / n)) for n in ev.IMPLEMENTATION]
    loaded = dict(source_sha256='a' * 64, state=state, payload=payload, finish_payload=dict(details='protected', levels='protected', leads='protected', full_tool='protected', unit_record='protected'), holder_recipe={}, implementation_pins=implementation, pin=dict(path=str(tmp_path / 'parent.json'), sha256='b' * 64), pins=[])
    return (loaded, args)

@pytest.mark.parametrize('key,value', [('toolpath_record_counts', [201]), ('toolpath_record_counts', [1]), ('toolpath_record_counts', [121])])
def test_gtp_allows_only_fresh_target_path_delta(tmp_path, key, value):
    (l, a) = data(tmp_path)
    after = deepcopy(l['state'])
    ev.selected(after, a)[key] = value
    next((r for r in after['operations'] if r['native_id'] == 248))['toolpath_generated'] = True
    after['document']['needs_save'] = True
    ev.verify_gtp_delta(l['state'], after, a)

@pytest.mark.parametrize('change', ['sibling', 'candidate', 'feature', 'source', 'entry_depth', 'empty_path', 'bool_count', 'dirty_int'])
def test_gtp_rejects_protected_or_invalid_delta(tmp_path, change):
    (l, a) = data(tmp_path)
    after = deepcopy(l['state'])
    target = ev.selected(after, a)
    target['toolpath_generated'] = True
    target['toolpath_record_counts'] = [201]
    if change == 'sibling':
        after['operations'][0]['name'] = 'changed'
    if change == 'candidate':
        target['assigned_tool']['native_id'] = 264
    if change == 'feature':
        after['features'][0]['unexpected'] = 1
    if change == 'source':
        after['saved_file_sha256'] = 'c' * 64
    if change == 'entry_depth':
        after['operation_setups'][0]['unexpected'] = 1
    if change == 'empty_path':
        target['toolpath_record_counts'] = []
    if change == 'bool_count':
        target['toolpath_record_counts'] = [True]
    if change == 'dirty_int':
        after['document']['needs_save'] = 0
    with pytest.raises(ValueError):
        ev.verify_gtp_delta(l['state'], after, a)

def test_save_only_clean_and_new_sha(tmp_path):
    (l, a) = data(tmp_path)
    before = l['state']
    before['document']['needs_save'] = True
    after = deepcopy(before)
    after['document']['needs_save'] = False
    after['saved_file_sha256'] = 'c' * 64
    ev.verify_save_delta(before, after, a, 'c' * 64)
    after['operations'][0]['name'] = 'changed'
    with pytest.raises(ValueError):
        ev.verify_save_delta(before, after, a, 'c' * 64)

def test_marker_not_rearmed_by_output_name(tmp_path):
    (l, a) = data(tmp_path)
    one = ev.continuation_marker(a['expected_document_path'], 'gtp', l['pin'], 247)
    two = ev.continuation_marker(a['expected_document_path'], 'gtp', dict(l['pin'], path='copied.json'), 247)
    assert one == two
    assert one != ev.continuation_marker(a['expected_document_path'], 'save', l['pin'], 247)

def install_native_fakes(monkeypatch, tmp_path, action, returned=0, alter=None):
    (l, a) = data(tmp_path)
    calls = []
    if action == 'gtp':
        l['state']['document']['needs_save'] = False
        row = ev.selected(l['state'], a)
        row['toolpath_generated'] = False
        row['toolpath_record_counts'] = []
    else:
        l['state']['document']['needs_save'] = True
    after = deepcopy(l['state'])
    if action == 'gtp':
        row = ev.selected(after, a)
        row['toolpath_generated'] = True
        row['toolpath_record_counts'] = [201]
    else:
        after['document']['needs_save'] = False
        after['saved_file_sha256'] = 'c' * 64
    if alter:
        alter(after, l, a)

    class Session:

        def __init__(self, *a):
            self.active = False

        def __enter__(self):
            self.active = True
            return self

        def __exit__(self, *a):
            self.active = False

        def summary(self):
            return dict(subscribed=True, active=self.active, disconnected=not self.active, event_count=0)

    class Guard:

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def typed(self, o, t):
            return o

        def read(self, *a):
            return None

        def dispatch_once(self, call, persist_pending):
            persist_pending()
            return call()

        def summary(self):
            return dict(claimed=True, native_call_attempted=True, native_call_returned=True, invalid=False)

    class Context:

        def __init__(self, loaded, args, sw, tlb, app, events):
            (self.loaded, self.args, self.app, self.events) = (loaded, args, app, events)
            self.expected_document = deepcopy(loaded['state']['document'])
            self.allow_dirty_transition = False

        def files(self):
            pass

        def owned(self):
            pass

        def identity(self):
            return deepcopy(after['document'] if len(calls) > 0 else self.expected_document)

        def guard(self):
            return Guard()

    def capture(ctx, reference, *, holder_recipe, diagnostic):
        state = deepcopy(l['state'] if not calls else after)
        diagnostic['capture_complete'] = True
        return dict(state=state, native=dict(doc='doc', operations={248: 'op'}), rough_payload=deepcopy(l['payload']), finish_payload=deepcopy(l['finish_payload']))

    def member(obj, name, *a):
        calls.append(name)
        return returned
    monkeypatch.setattr(sut, '_load', lambda *x, **kw: deepcopy(l))
    monkeypatch.setattr(sut, '_preflight', lambda *x: None)
    monkeypatch.setattr(sut, 'FinishContinuationContext', Context)
    monkeypatch.setattr(sut, 'capture_finish_recipe', capture)
    monkeypatch.setattr(sut, '_bootstrap', lambda *x: 'app')
    monkeypatch.setattr(sut, '_member', member)
    monkeypatch.setattr(sut, '_object_id', lambda *x: 248)
    monkeypatch.setattr(sut, 'read_generic_tool', lambda *x: (ev.selected(l['state'], a)['assigned_tool'], None))
    monkeypatch.setattr(sut, '_file_hash', lambda *x: 'c' * 64)
    from scripts import sw_cam_events, sw_cam_circle_lifecycle_evidence
    monkeypatch.setattr(sw_cam_events, 'CamMessageSession', Session)
    monkeypatch.setattr(sw_cam_circle_lifecycle_evidence, 'raw_part_identity', lambda *x: deepcopy(after['document']))
    return (l, a, calls)

@pytest.mark.parametrize('action', ['gtp', 'save'])
def test_native_endpoints_one_explicit_action_and_complete_checkpoint(tmp_path, monkeypatch, action):
    (l, a, calls) = install_native_fakes(monkeypatch, tmp_path, action)
    r = sut._native_action(action, None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], checkpoint_action='save' if action == 'gtp' else 'recipe', **a)
    assert r.get('readback_verified') is True, r
    assert calls == ['GenerateToolpath' if action == 'gtp' else 'SaveActiveDocument']
    assert len(r['snapshot_diagnostics']) == 2
    assert r['checkpoint_sha256'] == ev._digest(r['checkpoint'])
    assert json.loads(Path(r['marker_path']).read_text()) == ev.marker_state(r)
    assert r['model_saved'] is (action == 'save')
    assert r['GTP_attempted'] is (action == 'gtp')

@pytest.mark.parametrize('action,returned', [(a, v) for a in ['gtp', 'save'] for v in [None, True, 1, -1]])
def test_native_nonzero_or_nonstrict_return_stops_no_after(tmp_path, monkeypatch, action, returned):
    (l, a, calls) = install_native_fakes(monkeypatch, tmp_path, action, returned)
    r = sut._native_action(action, None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], checkpoint_action='save' if action == 'gtp' else 'recipe', **a)
    assert r['readback_verified'] is False and r['status'] == 'uncertain'
    assert len(calls) == 1 and len(r['snapshot_diagnostics']) == 1 and ('checkpoint' not in r)
    assert Path(r['marker_path']).exists()

@pytest.mark.parametrize('action', ['gtp', 'save'])
def test_changed_sibling_after_native_fails_without_retry(tmp_path, monkeypatch, action):

    def alter(after, l, a):
        next((r for r in after['operations'] if r['native_id'] != 247))['name'] = 'changed'
    (l, a, calls) = install_native_fakes(monkeypatch, tmp_path, action, 0, alter)
    r = sut._native_action(action, None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], checkpoint_action='save' if action == 'gtp' else 'recipe', **a)
    assert r['status'] == 'uncertain' and r['readback_verified'] is False and (len(calls) == 1)

def test_export_adapter_never_invokes_generation_or_save(tmp_path, monkeypatch):
    (l, a) = data(tmp_path)
    events = []
    row = ev.selected(l['state'], a)
    row['toolpath_generated'] = True
    row['toolpath_record_counts'] = [201]
    monkeypatch.setattr(sut, '_load', lambda *x, **kw: l)

    class Context:

        def __init__(self, *x):
            pass
    monkeypatch.setattr(sut, 'FinishContinuationContext', Context)
    from scripts import sw_cam_mill_generic_cl

    def exporter(*pos, **kw):
        events.append(kw)
        r = kw['_context_adapter'].report_fields()
        r.update(phase='finished', status='error', readback_verified=False)
        return r
    monkeypatch.setattr(sw_cam_mill_generic_cl, 'export_mill_generic_cl', exporter)
    sut.export_finish_generic_cl(None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], project_root=str(tmp_path), output_path=str(tmp_path / 'cl/output.cl'), acknowledge_machine_scope=True, **a)
    assert len(events) == 1 and events[0]['action'] == 'apply'
    assert events[0]['expected_toolpath_record_counts'] == [201]
    assert events[0]['expected_generated_operations'] == [dict(operation_native_id=247, toolpath_record_counts=[191]), dict(operation_native_id=248, toolpath_record_counts=[201])]
    assert len(events[0]['expected_ungenerated_operation_ids']) == 4

def test_cl_finalize_identity_failure_is_persisted_without_reexport(tmp_path, monkeypatch):
    (l, a) = data(tmp_path)
    calls = []
    row = ev.selected(l['state'], a)
    row['toolpath_generated'] = True
    row['toolpath_record_counts'] = [201]
    monkeypatch.setattr(sut, '_load', lambda *x, **kw: l)

    class Context:

        def __init__(self, *x):
            pass

        def identity(self):
            raise ValueError('changed after core export')
    monkeypatch.setattr(sut, 'FinishContinuationContext', Context)
    from scripts import sw_cam_mill_generic_cl

    def export(*pos, **kw):
        calls.append(1)
        r = kw['_context_adapter'].report_fields()
        r.update(phase='finished', status='review_required', readback_verified=True, output_verified=True)
        return r
    monkeypatch.setattr(sw_cam_mill_generic_cl, 'export_mill_generic_cl', export)
    r = sut.export_finish_generic_cl(None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], project_root=str(tmp_path), output_path=str(tmp_path / 'cl/output.cl'), acknowledge_machine_scope=True, **a)
    assert len(calls) == 1 and r['status'] == 'uncertain' and (r['readback_verified'] is False)
    assert json.loads(Path(a['receipt_path']).read_text())['failed_phase'] == 'continuation_finalize'

def test_wrong_finish_native_id_stops_before_gtp(tmp_path, monkeypatch):
    (l, a, calls) = install_native_fakes(monkeypatch, tmp_path, 'gtp')
    monkeypatch.setattr(sut, '_object_id', lambda *x: 247)
    r = sut._native_action('gtp', None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], checkpoint_action='save', **a)
    assert not calls and r['status'] == 'error' and (not r['native_call_attempted'])

@pytest.mark.parametrize('action', ['gtp', 'save'])
def test_changed_finish_payload_after_native_is_uncertain(tmp_path, monkeypatch, action):
    (l, a, calls) = install_native_fakes(monkeypatch, tmp_path, action)
    capture = sut.capture_finish_recipe

    def changed(*x, **kw):
        result = capture(*x, **kw)
        if calls:
            result['finish_payload']['leads'] = 'changed'
        return result
    monkeypatch.setattr(sut, 'capture_finish_recipe', changed)
    r = sut._native_action(action, None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], checkpoint_action='save' if action == 'gtp' else 'recipe', **a)
    assert len(calls) == 1 and r['status'] == 'uncertain' and (not r['readback_verified'])

@pytest.mark.parametrize('action', ['gtp', 'save'])
def test_attempt_marker_is_durable_before_native_dispatch(tmp_path, monkeypatch, action):
    (l, a, calls) = install_native_fakes(monkeypatch, tmp_path, action)
    original = sut._member

    def checked(*x):
        disk = json.loads(Path(a['receipt_path']).read_text())
        marker = json.loads(Path(disk['marker_path']).read_text())
        assert marker['native_call_attempted'] is True
        assert marker['native_dispatch_pending'] is True if action == 'gtp' else marker['save_pending'] is True
        return original(*x)
    monkeypatch.setattr(sut, '_member', checked)
    r = sut._native_action(action, None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], checkpoint_action='save' if action == 'gtp' else 'recipe', **a)
    assert r['readback_verified'] and len(calls) == 1, r

def test_changed_completed_lineage_file_stops_before_dispatch(tmp_path, monkeypatch):
    original_context = sut.FinishContinuationContext
    (l, a, calls) = install_native_fakes(monkeypatch, tmp_path, 'gtp')
    artifact = tmp_path / 'older_completed.json'
    artifact.write_text('saved evidence')
    from hashlib import sha256
    pin = dict(path=str(artifact.resolve()), sha256=sha256(artifact.read_bytes()).hexdigest())
    l['lineage_pins'] = [pin]
    artifact.write_text('unexpected change')
    fake_context = sut.FinishContinuationContext

    def files(self):
        shell = original_context.__new__(original_context)
        shell.loaded = self.loaded
        original_context.files(shell)
    monkeypatch.setattr(fake_context, 'files', files)
    monkeypatch.setattr(sut, '_file_hash', lambda p: sha256(Path(p).read_bytes()).hexdigest())
    r = sut._native_action('gtp', None, None, None, checkpoint_receipt_path=l['pin']['path'], checkpoint_receipt_sha256=l['pin']['sha256'], checkpoint_action='save', **a)
    assert not calls and r['status'] == 'error' and (not r['native_call_attempted'])
    assert r['issue']['type'] == 'ValueError'
    assert any((v['file'] == 'sw_cam_finish_continuation.py' and v['function'] == 'files' for v in r['issue']['locations']))

def test_completed_lineage_cannot_exceed_sixteen(tmp_path):
    pins = [dict(path=str((tmp_path / (str(i) + '.json')).resolve()), sha256='a' * 64) for i in range(17)]
    with pytest.raises(ValueError):
        ev.checked_lineage_pins(pins)
