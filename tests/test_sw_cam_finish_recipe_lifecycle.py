"""验证一次批次的持久化边界、部分失败及完整恢复检查，不连接应用。"""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from scripts import sw_cam_finish_recipe as recipe
from cam_finish_recipe_test_fixture import RecipeCase, TARGET, OLD, sha, write_json


@pytest.mark.parametrize('holder_current', [False, True])
@pytest.mark.parametrize('dirty_after', [False, True])
def test_completed_batch_is_reloadable_and_preserves_protected_state(tmp_path, monkeypatch, holder_current, dirty_after):
    case = RecipeCase(tmp_path, monkeypatch, holder_current=holder_current, dirty_after=dirty_after)
    result = case.run()
    assert result['status'] == 'review_required', result.get('issue')
    assert result['phase'] == 'finished' and result['readback_verified'] is True
    assert result['native_hresult_observable'] is False
    assert result['native_dispatch_pending'] is False
    assert result['checkpoint']['state']['document']['needs_save'] is dirty_after
    assert len(case.calls) == (9 if holder_current else 10)
    assert len({(x[0], x[1]) for x in case.calls}) == len(case.calls)
    assert case.capture_count == 2 and case.bootstrap_count == 1
    assert case.data == TARGET
    assert len(result['field_attempts']) == 10
    assert all(row['readback_verified'] for row in result['field_attempts'])
    assert sum(row['setter_attempted'] for row in result['field_attempts']) == 9
    assert result['before']['rough_payload'] == result['checkpoint']['rough_payload']
    assert result['before']['state']['operations'][:-1] == result['checkpoint']['state']['operations'][:-1]
    for key in ('levels', 'leads', 'unit_record'):
        assert result['before']['finish_payload'][key] == result['checkpoint']['finish_payload'][key]
    for key in ('save_attempted', 'GTP_attempted', 'GOP_attempted', 'AFR_attempted',
                'tool_assignment_attempted', 'export_attempted', 'metadata_write_attempted',
                'automatic_replay', 'automatic_retry', 'automatic_rollback', 'production_qualified'):
        assert result[key] is False
    loaded = case.load()
    assert loaded['state'] == result['checkpoint']['state']
    assert loaded['finish_payload'] == result['checkpoint']['finish_payload']
    assert loaded['payload'] == result['checkpoint']['rough_payload']
    assert loaded['historical_only'] is False
    assert sha(case.source) == case.source_sha
    assert loaded['parent_pin']['sha256'] == sha(case.active_receipt)
    assert result['profile_comparison']['production_qualified'] is False
    assert len(loaded['pins']) == 6


def test_target_coupling_skips_second_write_without_skipping_final_proof(tmp_path, monkeypatch):
    case = RecipeCase(tmp_path, monkeypatch)
    case.mode = 'coupled_target'
    result = case.run()
    assert result['status'] == 'review_required', result.get('issue')
    assert len([x for x in case.calls if x[0] == 'scalar']) == 8
    assert not any(x[1] == 'ShoulderLength' for x in case.calls)
    assert case.capture_count == 2
    assert case.load()['finish_payload'] == result['checkpoint']['finish_payload']


@pytest.mark.parametrize('mode,scalar_calls,pending', [
    ('setter_throw', 2, True), ('no_effect', 2, False), ('coupled_bad', 1, False),
    ('source_drift', 1, False), ('holder_pin_drift', 1, False),
    ('identity_drift', 1, False), ('event', 1, False)])
def test_partial_batch_stops_with_durable_attempt_and_no_rollback(tmp_path, monkeypatch, mode, scalar_calls, pending):
    case = RecipeCase(tmp_path, monkeypatch)
    case.mode = mode
    result = case.run()
    assert result['status'] == 'uncertain'
    assert result['native_dispatch_pending'] is pending
    assert result['readback_verified'] is False and result['recipe_configuration_verified'] is False
    assert len(case.calls) == scalar_calls and all(x[0] == 'scalar' for x in case.calls)
    assert case.capture_count == 1
    assert case.data['EffCutlength'] == TARGET['EffCutlength']
    assert case.data['OverallLen'] == OLD['OverallLen']
    persisted = json.loads(case.active_receipt.read_text(encoding='utf-8'))
    assert persisted['issue'] == result['issue']
    marker = json.loads(Path(result['marker_path']).read_text(encoding='utf-8'))
    assert marker['status'] == 'uncertain' and marker['mutation_attempted'] is True
    with pytest.raises(ValueError, match='Completed recipe'):
        case.load()


@pytest.mark.parametrize('mode,pending', [
    ('holder_none', False), ('holder_bool', False), ('holder_nonzero', False),
    ('holder_no_effect', False), ('holder_throw', True)])
def test_holder_failure_never_replays_completed_scalar_writes(tmp_path, monkeypatch, mode, pending):
    case = RecipeCase(tmp_path, monkeypatch)
    case.mode = mode
    result = case.run()
    assert result['status'] == 'uncertain' and result['native_dispatch_pending'] is pending
    assert case.data == TARGET
    assert len(case.calls) == 10 and case.calls[-1][0] == 'holder'
    assert case.capture_count == 1
    assert 'checkpoint' not in result and result['readback_verified'] is False
    if mode == 'holder_throw':
        assert 'return_type' not in result['holder_reference']
    else:
        expected = {'holder_none':'NoneType', 'holder_bool':'bool', 'holder_nonzero':'int', 'holder_no_effect':'int'}[mode]
        assert result['holder_reference']['return_type'] == expected
    with pytest.raises(ValueError): case.load()


def test_durable_write_failure_prevents_first_native_setter(tmp_path, monkeypatch):
    case = RecipeCase(tmp_path, monkeypatch)
    case.fail_write_once = True
    result = case.run()
    assert result['status'] == 'uncertain' and result['native_dispatch_pending'] is True
    assert case.calls == [] and case.data == OLD
    assert Path(result['marker_path']).exists()
    assert result['issue']['type'] == 'OSError'
    assert result['issue']['locations'][0]['function'] == 'apply_property_batch'


@pytest.mark.parametrize('completed', [False, True])
def test_same_action_cannot_rearm_by_changing_receipt_name(tmp_path, monkeypatch, completed):
    case = RecipeCase(tmp_path, monkeypatch)
    if not completed: case.mode = 'setter_throw'
    result = case.run()
    marker = Path(result['marker_path'])
    original_marker, original_receipt = marker.read_bytes(), case.active_receipt.read_bytes()
    count = len(case.calls)
    old_receipt = case.active_receipt
    case.active_receipt = tmp_path/'renamed_receipt.json'
    with pytest.raises(ValueError, match='Fresh recipe'):
        case.run()
    assert len(case.calls) == count
    assert marker.read_bytes() == original_marker and old_receipt.read_bytes() == original_receipt
    assert not case.active_receipt.exists()


def test_existing_output_is_never_overwritten(tmp_path, monkeypatch):
    case = RecipeCase(tmp_path, monkeypatch)
    case.active_receipt.write_bytes(b'previous receipt')
    with pytest.raises(ValueError): case.run()
    assert case.calls == [] and case.bootstrap_count == 0
    assert case.active_receipt.read_bytes() == b'previous receipt'


def mutate_capture(value, kind):
    if kind == 'rough': value['rough_payload']['levels']['clearance'] += 1
    elif kind == 'settings': value['finish_payload']['details']['finish']['Step']['raw'] += .1
    elif kind in ('levels', 'leads', 'unit_record'): value['finish_payload'][kind]['unexpected'] = 1
    elif kind == 'sibling': value['state']['operations'][0]['suppressed'] = True
    elif kind == 'source': value['state']['saved_file_sha256'] = 'f'*64
    elif kind == 'metadata': value['finish_payload']['full_tool']['holder']['number'] = 'changed'
    elif kind == 'generated':
        value['state']['operations'][-1]['toolpath_generated'] = True
        value['state']['operations'][-1]['toolpath_record_counts'] = [1]
    elif kind == 'repeated': value['finish_payload']['details']['tool']['NoOfFlutes']['raw'] = 17
    elif kind == 'profile': value['finish_payload']['full_tool']['profiles']['tool']['chains'][0]['curves'][1]['end_native'][2] -= 1
    else: raise AssertionError(kind)


@pytest.mark.parametrize('kind', ['rough', 'settings', 'levels', 'leads', 'unit_record',
                                  'sibling', 'source', 'metadata', 'generated', 'repeated', 'profile'])
def test_final_proof_rejects_undeclared_drift_after_writes(tmp_path, monkeypatch, kind):
    case = RecipeCase(tmp_path, monkeypatch)
    case.after_mutation = lambda value: mutate_capture(value, kind)
    result = case.run()
    assert result['status'] == 'uncertain' and result['readback_verified'] is False
    assert result['failed_phase'] == 'after_capture' and case.capture_count == 2
    assert len(case.calls) == 10
    assert result['after_diagnostic']['raw_synthetic']
    assert not result.get('recipe_configuration_verified')
    with pytest.raises(ValueError): case.load()


@pytest.mark.parametrize('kind', ['rough', 'settings', 'levels', 'leads', 'unit_record',
                                  'sibling', 'source', 'generated', 'repeated'])
def test_bad_initial_capture_stops_before_marker_and_writes(tmp_path, monkeypatch, kind):
    case = RecipeCase(tmp_path, monkeypatch)
    case.before_mutation = lambda value: mutate_capture(value, kind)
    result = case.run()
    assert result['status'] == 'error' and result['mutation_attempted'] is False
    assert case.calls == [] and case.capture_count == 1
    assert not Path(result['marker_path']).exists()


@pytest.mark.parametrize('kind', ['digest', 'checkpoint', 'marker', 'flag', 'identity', 'source', 'event'])
def test_completed_loader_revalidates_receipt_and_binding(tmp_path, monkeypatch, kind):
    case = RecipeCase(tmp_path, monkeypatch)
    result = case.run()
    assert result['status'] == 'review_required', result.get('issue')
    if kind == 'digest': result['checkpoint_sha256'] = '0'*64
    elif kind == 'checkpoint': result['checkpoint']['rough_payload']['entry']['mode'] = 999
    elif kind == 'marker':
        marker = Path(result['marker_path'])
        data = json.loads(marker.read_text(encoding='utf-8')); data['readback_verified'] = False
        write_json(marker, data)
    elif kind == 'flag': result['GTP_attempted'] = True
    elif kind == 'identity': result['original_manifest_args']['finish_tool_native_id'] = 999
    elif kind == 'source': case.source.write_bytes(b'different saved source')
    elif kind == 'event': result['messages']['event_count'] = 1
    write_json(case.active_receipt, result)
    with pytest.raises(ValueError): case.load()
    assert len(case.calls) == 10
