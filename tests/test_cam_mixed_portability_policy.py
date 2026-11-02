"""Optional actual evidence must never silently hide an invalid supplied path."""
import json
from pathlib import Path
import pytest
import cam_mixed_test_support as h

def test_absent_evidence_is_the_only_skip(monkeypatch):
    monkeypatch.delenv('TEST_MIXED_EVIDENCE',raising=False)
    with pytest.raises(pytest.skip.Exception):h.evidence_file('TEST_MIXED_EVIDENCE','data.json')
@pytest.mark.parametrize('value',['',' ','relative'])
def test_supplied_invalid_evidence_fails(monkeypatch,value):
    monkeypatch.setenv('TEST_MIXED_EVIDENCE',value)
    with pytest.raises(ValueError):h.evidence_file('TEST_MIXED_EVIDENCE','data.json')
def test_supplied_missing_directory_and_file_fail(monkeypatch,tmp_path):
    monkeypatch.setenv('TEST_MIXED_EVIDENCE',str(tmp_path/'absent'))
    with pytest.raises(ValueError):h.evidence_file('TEST_MIXED_EVIDENCE','data.json')
    monkeypatch.setenv('TEST_MIXED_EVIDENCE',str(tmp_path))
    with pytest.raises(ValueError):h.evidence_file('TEST_MIXED_EVIDENCE','data.json')
def test_supplied_invalid_json_fails(monkeypatch,tmp_path):
    monkeypatch.setenv('TEST_MIXED_EVIDENCE',str(tmp_path));(tmp_path/'data.json').write_text('{')
    with pytest.raises(json.JSONDecodeError):h.evidence_json('TEST_MIXED_EVIDENCE','data.json')
@pytest.mark.parametrize('value',['','relative'])
def test_invalid_repository_override_fails(monkeypatch,value):
    monkeypatch.setenv('SOLIDWORKS_SKILL_ROOT',value)
    with pytest.raises(ValueError):h.repository_root()
def test_repository_defaults_to_test_parent_without_environment(monkeypatch,tmp_path):
    (tmp_path/'tests').mkdir();(tmp_path/'scripts').mkdir();(tmp_path/'mcp-server').mkdir()
    (tmp_path/'mcp-server/server.py').write_text('# test repository')
    monkeypatch.delenv('SOLIDWORKS_SKILL_ROOT',raising=False)
    monkeypatch.setattr(h,'__file__',str(tmp_path/'tests/cam_mixed_test_support.py'))
    assert h.repository_root()==tmp_path