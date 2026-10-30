"""移植的离线回归测试；不连接 CAD 进程。"""
from copy import deepcopy
from pathlib import Path
import hashlib
import pytest
from scripts import sw_cam_finish_continuation_evidence as ev
from scripts import sw_cam_finish_continuation as sut
from test_cam_route_finish_continuation import data
'移植的离线回归测试；只使用合成数据和模拟接口。'

def report(action, loaded, args, parent_action, new_sha=None):
    loaded = deepcopy(loaded)
    loaded['pins'] = ev.canonical_evidence_pins(loaded['pins'], loaded['implementation_pins'])
    r = sut._report(action, loaded, parent_action, args)
    after = deepcopy(loaded['state'])
    if action == 'gtp':
        row = ev.selected(after, args)
        row['toolpath_generated'] = True
        row['toolpath_record_counts'] = [201]
        after['document']['needs_save'] = True
    elif action == 'save':
        after['saved_file_sha256'] = new_sha
        after['document']['needs_save'] = False
    r.update(native_call_attempted=True, native_call_returned=True, native_return_type='int', native_return_value=0)
    if action == 'gtp':
        r.update(GTP_attempted=True, GTP_call_count=1, GTP_returned=True)
    elif action == 'save':
        r.update(save_attempted=True, save_readback_verified=True, model_saved=True, saved_file_sha256=new_sha)
    else:
        r.update(output_verified=True, native_hresult=0, output=dict(path=str(Path(args['receipt_path']).with_suffix('.cl')), sha256='e' * 64))
    r['messages'] = dict(subscribed=True, active=False, disconnected=True, event_count=0)
    r['dispatch_guard'] = dict(claimed=True, native_call_attempted=True, native_call_returned=True, invalid=False)
    r['snapshot_diagnostics'] = [dict(capture_complete=True)] * (3 if action == 'cl' else 2)
    r['after_cleanup_document'] = deepcopy(after['document'])
    sut._finished(r, after, dict(rough=loaded['payload'], finish=loaded['finish_payload']))
    return r

@pytest.fixture
def chain(tmp_path, monkeypatch):
    (base, args) = data(tmp_path)
    base['state']['document']['needs_save'] = True
    records = {}
    seq = []
    base_calls = []
    monkeypatch.setattr(ev, 'implementation_paths', lambda : {str(Path(p['path']).resolve()).casefold() for p in base['implementation_pins']})

    def store(r):
        pin = dict(path=r['receipt_path'], sha256=ev._digest(r))
        records[pin['path']] = (deepcopy(r), pin)
        marker = ev.marker_state(r)
        mp = dict(path=r['marker_path'], sha256=ev._digest(marker))
        records[mp['path']] = (marker, mp)
        return (pin, mp)

    def advance(loaded, action, parent_action, index, new_sha=None):
        aa = dict(args, expected_source_sha256=loaded['state']['saved_file_sha256'], receipt_path=str(tmp_path / (str(index) + '.json')))
        r = report(action, loaded, aa, parent_action, new_sha)
        (pin, mp) = store(r)
        seq.append(r)
        own = ev.canonical_evidence_pins([pin, mp], [r['output']] if action == 'cl' else [])
        (live, lineage) = ev.advance_pin_sets(loaded, loaded['implementation_pins'], own)
        result = dict(loaded, state=deepcopy(r['after_context']), pin=pin, pins=live, lineage_pins=lineage, active_continuation_pins=own)
        return result
    saved = advance(base, 'save', 'recipe', 1, 'c' * 64)
    generated = advance(saved, 'gtp', 'save', 2)
    exported = advance(generated, 'cl', 'gtp', 3)
    final = advance(exported, 'save', 'cl', 4, 'd' * 64)

    def read(path, sha):
        (d, p) = records[str(path)]
        if sha != p['sha256']:
            raise ValueError('Changed test pin')
        return (deepcopy(d), deepcopy(p))

    def filehash(path):
        if str(path) == args['expected_document_path']:
            return 'd' * 64
        if str(path) in records:
            return records[str(path)][1]['sha256']
        if str(path).endswith('.cl'):
            return 'e' * 64
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def base_loader(path, sha, **kw):
        base_calls.append(kw)
        assert path == base['pin']['path'] and sha == base['pin']['sha256']
        assert kw['check_current_source'] is False
        assert kw['expected_source_sha256'] == 'a' * 64
        return deepcopy(base)
    monkeypatch.setattr(ev, 'read_pin', read)
    monkeypatch.setattr(ev, '_file_hash', filehash)
    monkeypatch.setattr(ev, 'load_completed_finish_recipe', base_loader)
    return dict(base=base, args=args, records=records, seq=seq, final=final, base_calls=base_calls, store=store)

def test_full_recipe_save_gtp_cl_save_chain(chain):
    c = chain
    result = ev.load_finish_continuation(c['final']['pin']['path'], c['final']['pin']['sha256'], action='save', **dict(c['args'], expected_source_sha256='d' * 64))
    assert result['state'] == c['final']['state'] and result['historical_only'] is False
    assert ev.selected(result['state'], c['args'])['toolpath_record_counts'] == [201]
    assert len(c['base_calls']) == 1 and result['payload'] == c['base']['payload']
    assert len(result['lineage_pins']) == 7 and len(result['active_continuation_pins']) == 2

@pytest.mark.parametrize('change', ['pending', 'bool_return', 'two_gtp', 'rough_drift', 'finish_profile', 'wrong_source', 'checkpoint', 'marker', 'implementation', 'evidence', 'wrong_parent', 'wrong_pid', 'diagnostics', 'cl_hresult', 'foreign_implementation_path'])
def test_tampered_chain_rejected(chain, change):
    c = chain
    target = c['seq'][1] if change not in ('cl_hresult',) else c['seq'][2]
    if change == 'pending':
        target['native_dispatch_pending'] = True
    elif change == 'bool_return':
        target['native_return_value'] = True
    elif change == 'two_gtp':
        target['GTP_call_count'] = 2
    elif change == 'rough_drift':
        next((r for r in target['after_context']['operations'] if r['native_id'] == 247))['toolpath_record_counts'] = [192]
    elif change == 'finish_profile':
        target['after_payload']['finish']['full_tool'] = 'changed'
    elif change == 'wrong_source':
        target['source_after_sha256'] = 'f' * 64
    elif change == 'checkpoint':
        target['checkpoint_sha256'] = 'f' * 64
    elif change == 'implementation':
        target['implementation_pins'].pop()
    elif change == 'evidence':
        target['evidence_pins'].pop()
    elif change == 'wrong_parent':
        target['parent_action'] = 'recipe'
    elif change == 'wrong_pid':
        target['process_id'] = 1
    elif change == 'diagnostics':
        target['snapshot_diagnostics'].pop()
    elif change == 'cl_hresult':
        target['native_hresult'] = True
    elif change == 'foreign_implementation_path':
        target['implementation_pins'][0]['path'] = str(Path(target['implementation_pins'][0]['path']).parent / 'foreign' / Path(target['implementation_pins'][0]['path']).name)
    oldpin = c['records'][target['receipt_path']][1]
    if change == 'marker':
        c['records'][target['marker_path']][0]['phase'] = 'pending'
    else:
        c['records'][target['receipt_path']] = (deepcopy(target), oldpin)
    with pytest.raises((ValueError, KeyError)):
        ev.load_finish_continuation(c['final']['pin']['path'], c['final']['pin']['sha256'], action='save', **dict(c['args'], expected_source_sha256='d' * 64))

def test_history_is_readable_without_current_source_rebind(chain):
    c = chain
    first = c['seq'][0]
    pin = c['records'][first['receipt_path']][1]
    result = ev.load_finish_continuation(pin['path'], pin['sha256'], action='save', check_current_source=False, **dict(c['args'], expected_source_sha256='c' * 64))
    assert result['historical_only'] is True
    with pytest.raises(ValueError):
        ev.load_finish_continuation(pin['path'], pin['sha256'], action='save', **dict(c['args'], expected_source_sha256='c' * 64))

def test_bounded_lineage_refuses_unbounded_reentry(chain):
    c = chain
    with pytest.raises(ValueError):
        ev.load_finish_continuation(c['final']['pin']['path'], c['final']['pin']['sha256'], action='save', _depth=5, **dict(c['args'], expected_source_sha256='d' * 64))
