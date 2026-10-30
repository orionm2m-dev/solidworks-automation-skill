"""Offline historical-lineage tests; actual file bytes are never substituted."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest

STAGE = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ['SOLIDWORKS_SKILL_ROOT']).resolve()
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(RUNTIME / 'tests'))

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

base = module('historical_parent_fixture', RUNTIME / 'tests/test_checkpoint_reconfigure.py')
h = module('historical_parent_under_test', STAGE / 'scripts/sw_cam_taper_tool_checkpoint.py')
fixture, case, terminal = base.fixture, base.case, base.terminal

@pytest.fixture
def historical(terminal, monkeypatch):
    c = terminal
    archive = c.f.root / 'historical_saved.SLDPRT'
    archive.write_bytes(c.f.source.read_bytes())
    c.archive = archive
    monkeypatch.setattr(h, 'prior', base.m)
    return c

def load(c, **overrides):
    args = dict(c.identity, historical_source_path=str(c.archive))
    args.update(overrides)
    return h.load_historical_parent(str(c.j.receipt), base.m._file_hash(c.j.receipt), **args)

@pytest.mark.parametrize('current', ['changed', 'missing'])
def test_history_valid_with_replaced_or_missing_current_file(historical, current):
    c = historical
    if current == 'changed':
        c.f.source.write_bytes(b'newer tool-only saved source, not old checkpoint')
    else:
        c.f.source.unlink()
    value = load(c)
    assert value['source_sha256'] == c.identity['expected_source_sha256']
    assert value['historical_source_pin'] == dict(path=str(c.archive), sha256=base.m._file_hash(c.archive))
    assert value['historical_source_only'] is True
    assert value['current_source_bytes_verified'] is False
    assert len(value['pins']) == 64
    assert value['settings']['face'][base.m.GETTER] == [8.0, False]
    assert all(base.m.key(p['path']) != base.m.key(c.f.source) for p in value['pins'])

@pytest.mark.parametrize('change', ['wrong_bytes', 'missing', 'alias'])
def test_historical_archive_must_exist_and_match(historical, change):
    c = historical
    if change == 'wrong_bytes': c.archive.write_bytes(b'not saved historical bytes')
    if change == 'missing': c.archive.unlink()
    if change == 'alias': c.archive = c.f.source
    with pytest.raises(ValueError): load(c)

@pytest.mark.parametrize('field,value', [('expected_source_sha256', 'f'*64), ('expected_source_sha256', 'invalid'), ('process_id', True), ('process_id', 999), ('expected_document_path', 'relative.SLDPRT')])
def test_exact_historical_identity_required(historical, field, value):
    with pytest.raises(ValueError): load(historical, **{field:value})

@pytest.mark.parametrize('field,value', [('readback_verified', False), ('model_saved', False), ('status', 'uncertain'), ('native_dispatch_pending', True)])
def test_incomplete_terminal_rejected(historical, field, value):
    c=historical; data=json.loads(c.j.receipt.read_text());data[field]=value
    c.j.receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError): load(c)

def test_false_is_not_strict_save_zero(historical):
    c=historical; data=json.loads(c.j.receipt.read_text());data['source_transition']['strict_save_return']=False
    c.j.receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError): load(c)

def test_dirty_terminal_events_rejected(historical):
    c=historical; data=json.loads(c.j.receipt.read_text());data['messages']['event_count']=1
    c.j.receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError): load(c)

@pytest.mark.parametrize('which', ['marker', 'retired', 'live'])
def test_pinned_evidence_changes_rejected(historical, which):
    c=historical
    if which == 'marker': path=c.j.marker
    elif which == 'retired': path=Path(c.retired[0]['path'])
    else: path=Path(next(p['path'] for p in c.j.report['live_pins'] if Path(p['path']).name=='evidence0.txt'))
    path.write_bytes(b'changed actual evidence')
    with pytest.raises(ValueError): load(c)

def test_valid_hash_with_wrong_live_role_rejected(historical):
    c=historical; data=json.loads(c.j.receipt.read_text()); foreign=c.f.root/'unrelated.txt';foreign.write_text('valid bytes wrong role')
    index=next(i for i,p in enumerate(data['live_pins']) if Path(p['path']).name=='evidence0.txt')
    data['live_pins'][index]=base.m.pin(foreign);c.j.receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='derived'): load(c)

@pytest.mark.parametrize('field,value', [('read_only',False),('native_mutation_calls',True),('status','uncertain')])
def test_parent_authority_flags_remain_strict(historical,field,value):
    c=historical; data=deepcopy(c.parent);data[field]=value;c.parent_path.write_text(json.dumps(data))
    receipt=json.loads(c.j.receipt.read_text()); newpin=base.m.pin(c.parent_path);receipt['parent_pin']=newpin
    for row in receipt['live_pins']:
        if base.m.key(row['path'])==base.m.key(c.parent_path):row.update(newpin)
    c.j.receipt.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):load(c)

def test_legacy_loader_still_rejects_new_source(historical):
    c=historical;c.f.source.write_bytes(b'newer current source')
    with pytest.raises(ValueError):base.m.load_completed(str(c.j.receipt),base.m._file_hash(c.j.receipt),**c.identity)
    assert load(c)['current_source_bytes_verified'] is False

def test_archive_change_during_lineage_read_rejected(historical, monkeypatch):
    c = historical
    original = base.m.exports.operation_contract
    def changed(loaded):
        value = original(loaded)
        c.archive.write_bytes(b'archive changed after its initial hash read')
        return value
    monkeypatch.setattr(base.m.exports, 'operation_contract', changed)
    with pytest.raises(ValueError): load(c)
