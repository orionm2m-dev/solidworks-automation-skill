"""Historical resume continuation, reusing the verified flow/terminal fixture."""
import importlib.util
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
PRIOR=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
spec=importlib.util.spec_from_file_location('historical_resume_terminal_fixture',PRIOR/'tests/test_taper_resume_terminal.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
case=t.case
terminal=t.terminal


@pytest.fixture
def historical(terminal,monkeypatch):
    c=terminal
    archive=c.j.receipt.parent/'tool_save_archive.SLDPRT';archive.write_bytes(c.source.read_bytes())
    c.tool_archive=archive
    def load_prior(params,*,check_current=True):
        assert check_current is False and params['expected_source_sha256']==c.oldsha
        assert t.m._file_hash(c.archive)==c.oldsha
        t.m.exports._check([c.r['failure_pin'],c.r['creation_marker_pin']])
        return deepcopy(c.parent)
    monkeypatch.setattr(t.m,'load_inputs',load_prior)
    c.canonical=t.load(c)
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_taper_tool_resume',t.m)
    spec=importlib.util.spec_from_file_location('historical_cam_parent_under_test',STAGE/'scripts/sw_cam_chamfer_parent.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);c.h=m
    # Bind the fixture module explicitly even when another suite loaded the package attribute first.
    monkeypatch.setattr(m, 'resume', t.m)
    c.source.write_bytes(b'later inserted operation saved source')
    assert t.m._file_hash(c.source)!=c.newsha
    return c


def load(c,**overrides):
    params=dict(process_id=123,expected_document_path=str(c.source),expected_source_sha256=c.newsha,
        historical_source_path=str(c.tool_archive))
    params.update(overrides)
    return c.h.load_historical_resume_parent(str(c.j.receipt),t.m._file_hash(c.j.receipt),**params)


def test_historical_loader_uses_archive_when_current_source_has_changed(historical):
    c=historical;r=load(c)
    assert r['source_sha256']==c.newsha and len(r['pins'])==63
    assert r['pins']==c.canonical['pins'] and r['offline_export_proof_pins']==c.canonical['offline_export_proof_pins']
    assert r['tool_source_archive_pin']['sha256']==c.newsha
    assert r['current_source_bytes_verified'] is False and r['historical_source_only'] is True
    for k in c.canonical:assert r[k]==c.canonical[k]


def test_historical_loader_does_not_need_current_file(historical):
    c=historical;c.source.unlink()
    assert load(c)['source_sha256']==c.newsha


def test_archive_cannot_alias_current_source(historical):
    c=historical
    with pytest.raises(ValueError,match='Separate actual'):load(c,historical_source_path=str(c.source))


def test_archive_must_exist(historical):
    c=historical;c.tool_archive.unlink()
    with pytest.raises(ValueError,match='Separate actual'):load(c)


def test_archive_wrong_bytes_rejected(historical):
    c=historical;c.tool_archive.write_bytes(b'wrong tool model')
    with pytest.raises(ValueError,match='archive hash'):load(c)


def test_expected_historical_tool_hash_must_match(historical):
    c=historical
    with pytest.raises(ValueError,match='archive hash'):load(c,expected_source_sha256=c.oldsha)


def test_changed_terminal_not_accepted_as_historical(historical):
    c=historical;d=json.loads(c.j.receipt.read_text());d['readback_verified']=False;c.j.receipt.write_text(json.dumps(d))
    with pytest.raises(ValueError):load(c)


def test_changed_original_creation_marker_rejected(historical):
    c=historical;Path(c.r['creation_marker_pin']['path']).write_bytes(b'changed original marker')
    with pytest.raises(ValueError):load(c)


def test_changed_completed_resume_marker_rejected(historical):
    c=historical;c.j.marker.write_bytes(b'changed completed marker')
    with pytest.raises(ValueError):load(c)


def test_changed_live_closure_dependency_rejected(historical):
    c=historical;Path(c.parent['pins'][-1]['path']).write_bytes(b'changed dependency')
    with pytest.raises(ValueError):load(c)


def test_archive_change_during_validation_rejected(historical,monkeypatch):
    c=historical
    monkeypatch.setattr(c.h.exports,'operation_contract',lambda value:c.tool_archive.write_bytes(b'changed archive during read'))
    with pytest.raises(ValueError,match='archive changed during'):load(c)
