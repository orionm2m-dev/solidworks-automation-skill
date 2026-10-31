"""Saved contour continuation reusing the installed portable insertion fixture."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import pytest

STAGE = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', STAGE))
spec = importlib.util.spec_from_file_location('saved_insert_parent_fixture', RUNTIME/'tests/test_chamfer_insert_defaults.py')
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
case = t.case


@pytest.fixture
def historical(case, monkeypatch):
    c = case
    t.complete(c)
    c.newsha = c.r['saved_source_sha256']
    c.archive = c.source.with_name('insertion_archive.SLDPRT')
    c.archive.write_bytes(c.source.read_bytes())
    c.canonical = t.m.load_completed(c.p['receipt_path'], t.m._file_hash(c.p['receipt_path']),
        process_id=123, expected_document_path=str(c.source), expected_source_sha256=c.newsha)
    def load_prior(params, *, check_current=True):
        assert check_current is False and params['expected_source_sha256'] == c.loaded['source_sha256']
        t.m.exports._check(c.loaded['pins'] + [c.loaded['tool_source_archive_pin']])
        return deepcopy(c.loaded)
    monkeypatch.setattr(t.m, 'load_inputs', load_prior)
    spec = importlib.util.spec_from_file_location('saved_chamfer_parent_under_test', STAGE/'scripts/sw_cam_chamfer_saved_parent.py')
    c.h = importlib.util.module_from_spec(spec); spec.loader.exec_module(c.h)
    monkeypatch.setattr(c.h, 'parent', t.m)
    c.source.write_bytes(b'newer generated saved CAM')
    return c


def load(c, **overrides):
    params = dict(process_id=123, expected_document_path=str(c.source),
        expected_source_sha256=c.newsha, historical_source_path=str(c.archive))
    params.update(overrides)
    return c.h.load_historical_chamfer_parent(c.p['receipt_path'], t.m._file_hash(c.p['receipt_path']), **params)


def test_historical_insert_loader_uses_archive_not_current_source(historical):
    c = historical; result = load(c)
    assert result['state']['operation_count'] == 8 and result['inserted_contour']['native_id'] == 100
    for key in c.canonical: assert result[key] == c.canonical[key]
    assert result['insertion_source_archive_pin']['sha256'] == c.newsha
    assert result['tool_source_archive_pin'] == c.loaded['tool_source_archive_pin']
    assert result['historical_source_only'] is True and result['current_source_bytes_verified'] is False


def test_historical_insert_loader_does_not_require_current_file(historical):
    c = historical; c.source.unlink()
    assert load(c)['source_sha256'] == c.newsha


@pytest.mark.parametrize('change', ['absent', 'bytes', 'alias', 'wrong_expected_sha'])
def test_invalid_historical_archive_is_rejected(historical, change):
    c = historical; extra = {}
    if change == 'absent': c.archive.unlink()
    elif change == 'bytes': c.archive.write_bytes(b'wrong')
    elif change == 'alias': extra['historical_source_path'] = str(c.source)
    else: extra['expected_source_sha256'] = c.loaded['source_sha256']
    with pytest.raises(ValueError): load(c, **extra)


@pytest.mark.parametrize('change', ['terminal', 'parent', 'closure', 'marker', 'candidate'])
def test_historical_terminal_binding_is_not_bypassed(historical, change):
    c = historical; data = json.loads(Path(c.p['receipt_path']).read_text())
    if change == 'terminal': data['readback_verified'] = False
    elif change == 'parent': data['parent_pin']['sha256'] = '0'*64
    elif change == 'closure': data['live_pins'] = []
    elif change == 'marker': c.j.marker.write_text('{}')
    else: data['local_tool_candidate']['native_id'] += 1
    Path(c.p['receipt_path']).write_text(json.dumps(data))
    with pytest.raises(ValueError): load(c)


def test_historical_ancestor_file_change_rejected(historical):
    c = historical; Path(c.loaded['parent_pin']['path']).write_bytes(b'changed ancestor')
    with pytest.raises(ValueError): load(c)


def test_archive_changed_during_validation_rejected(historical, monkeypatch):
    c = historical; original = t.m.validate_terminal
    def validate(data, loaded):
        cp = original(data, loaded); c.archive.write_bytes(b'changed during validation'); return cp
    monkeypatch.setattr(t.m, 'validate_terminal', validate)
    with pytest.raises(ValueError, match='archive changed during'): load(c)
