"""Saved single-operation generation receipts reject altered authority and claims."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest

STAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('chamfer_flow_fixture', STAGE/'tests/test_chamfer_generate_flow.py')
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
m = t.m
case = t.case


@pytest.fixture
def completed(case):
    t.complete(case)
    return case


def load(c, **overrides):
    params = dict(process_id=c.r['process_id'], expected_document_path=str(c.source),
        expected_source_sha256=c.r['saved_source_sha256'])
    params.update(overrides)
    return m.load_completed(c.p['receipt_path'], m._file_hash(c.p['receipt_path']), **params)


def rewrite(c, data):
    Path(c.p['receipt_path']).write_text(json.dumps(data), encoding='utf-8')


def test_saved_generated_checkpoint_preserves_pending_geometry_review(completed):
    c = completed
    value = load(c)
    assert value['state']['operation_count'] == 8
    assert value['source_sha256'] == c.r['saved_source_sha256']
    assert value['configured_contour']['native_id'] == 100
    assert value['configured_contour']['generated'] is True
    assert value['configured_contour']['record_counts'] == [32]
    assert value['configured_contour']['geometry_acceptance_complete'] is False
    assert value['authority_kind'] == 'saved_generated_contour_geometry_review_pending'
    assert value['toolpath_record_counts'] == c.loaded['toolpath_record_counts']
    assert value['insertion_checkpoint'] == c.loaded['operation_checkpoint']
    assert c.b.calls.count('generate') == c.b.calls.count('save') == 1


@pytest.mark.parametrize('field', ['readback_verified','model_saved','target_generated',
    'phase_proofs_verified_after_native'])
def test_incomplete_terminal_is_not_a_saved_checkpoint(completed, field):
    c = completed; data = deepcopy(c.r); data[field] = False
    rewrite(c, data)
    with pytest.raises(ValueError): load(c)


@pytest.mark.parametrize('field', ['production_qualified','geometry_acceptance_complete',
    'automatic_retry','automatic_replay','global_generation_attempted','tool_edit_attempted'])
def test_unsupported_claim_or_forbidden_action_cannot_be_inherited(completed, field):
    c = completed; data = deepcopy(c.r); data[field] = True
    rewrite(c, data)
    with pytest.raises(ValueError): load(c)


@pytest.mark.parametrize('change', ['pending','boolean_return','wrong_depth','saved_settings',
    'prior_counts','target_counts','save_projection','save_hash','transition_hash','checkpoint'])
def test_terminal_proofs_reject_edited_success_receipt(completed, change):
    c = completed; data = deepcopy(c.r)
    if change == 'pending': data['actions']['GenerateToolpath']['pending'] = True
    elif change == 'boolean_return': data['actions']['GenerateToolpath']['native_return_value'] = False
    elif change == 'wrong_depth': data['depth_readback']['machining_depth'] = .2
    elif change == 'saved_settings': data['final_defaults']['finish']['GetChamferLength'] = .3
    elif change == 'prior_counts': data['final_observation']['route']['operations'][0]['toolpath_record_counts'] = [999]
    elif change == 'target_counts': data['final_observation']['route']['operations'][-1]['toolpath_record_counts'] = [33]
    elif change == 'save_projection': data['save_stage']['after']['defaults']['finish']['GetChamferLength'] = .3
    elif change == 'save_hash': data['save_stage']['saved_file_sha256'] = '0'*64
    elif change == 'transition_hash': data['source_transition']['source_before_sha256'] = '0'*64
    else: data['checkpoint']['configured_contour']['record_counts'] = [33]
    rewrite(c, data)
    with pytest.raises(ValueError): load(c)


@pytest.mark.parametrize('change', ['source','process','path','runtime','parent','closure',
    'recipe','marker_bytes','marker_path'])
def test_loader_checks_exact_source_and_historical_provenance(completed, change):
    c = completed; data = deepcopy(c.r); extra = {}
    if change == 'source': c.source.write_bytes(b'different-current-model')
    elif change == 'process': extra['process_id'] = c.r['process_id'] + 1
    elif change == 'path': extra['expected_document_path'] = str(c.source.with_name('wrong.SLDPRT'))
    elif change == 'runtime': data['module_pin']['sha256'] = '0'*64
    elif change == 'parent': data['parent_pin']['sha256'] = '0'*64
    elif change == 'closure': data['live_pins'] = []
    elif change == 'recipe': data['recipe_pin']['sha256'] = '0'*64
    elif change == 'marker_bytes': c.j.marker.write_text('{}', encoding='utf-8')
    else: data['marker_pin']['path'] = str(c.j.marker.with_name('other-marker.json'))
    rewrite(c, data)
    with pytest.raises(ValueError): load(c, **extra)


def test_terminal_loader_performs_no_native_action(completed, monkeypatch):
    c = completed; previous = deepcopy(c.b.calls)
    def forbidden(*args, **kwargs): raise AssertionError('terminal load must not contact native CAM')
    monkeypatch.setattr(m.NativeBackend, '__init__', forbidden)
    for _ in range(2):
        value = load(c)
        assert value['configured_contour']['record_counts'] == [32]
    assert c.b.calls == previous


def test_historical_parent_loader_is_explicitly_not_current_source_loader(completed, monkeypatch):
    c = completed; calls = []
    def expected(params, *, check_current=True):
        calls.append((params, check_current))
        assert params['expected_source_sha256'] == c.r['initial_source_sha256']
        assert params['expected_document_path'] == str(c.source)
        assert check_current is False
        return deepcopy(c.loaded)
    monkeypatch.setattr(m, 'load_inputs', expected)
    assert load(c)['source_sha256'] == c.r['saved_source_sha256']
    assert len(calls) == 1

