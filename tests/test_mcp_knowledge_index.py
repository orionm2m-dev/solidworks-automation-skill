"""Knowledge-index MCP contract; full server import, no CAD or backend IO."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import types
from unittest.mock import Mock
import pytest
from pydantic import ValidationError

@pytest.fixture(scope="module")
def server():
    runtime = Path(__file__).resolve().parents[1] / "mcp-server/server.py"
    name = "knowledge_index_full_server_qualification"
    module = types.ModuleType(name)
    module.__file__ = str(runtime)
    sys.modules[name] = module
    try:
        exec(compile(runtime.read_text(encoding="utf-8"), str(runtime), "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(name, None)

def request(server, tmp_path, **changes):
    values = dict(index_path=str(tmp_path / "index.json"), action="summary")
    values.update(changes)
    return server.SolidWorksKnowledgeIndexInput(**values)

@pytest.mark.parametrize("changes", [
    {"action":"search"}, {"action":"get"}, {"action":"unknown"},
    {"action":"search","query":""}, {"action":"search","query":"   "},
    {"action":"search","query":7}, {"action":"search","query":"a\x00b"},
    {"action":"get","topic_id":""}, {"action":"get","topic_id":"\t"},
    {"action":"get","topic_id":7}, {"query":"extra"}, {"topic_id":"extra"},
    {"query":None}, {"action":"search","query":"q","topic_id":None},
    {"action":"get","topic_id":"id","query":None},
    {"limit":True}, {"limit":1.0}, {"limit":"1"}, {"limit":0}, {"limit":21},
    {"detail":1}, {"verify_sources":"false"}, {"process_id":123},
    {"index_path":"relative.json"}, {"index_path":"C:index.json"},
    {"index_path":None}, {"index_path":42}, {"index_path":""},
])
def test_invalid_input_before_backend(server, tmp_path, changes):
    with pytest.raises(ValidationError):
        request(server, tmp_path, **changes)

@pytest.mark.parametrize("suffix", [".txt", ".json.bak", ".json\x00"])
def test_bad_absolute_path_suffix(server, tmp_path, suffix):
    with pytest.raises(ValidationError):
        request(server, tmp_path, index_path=str(tmp_path / ("index"+suffix)))

@pytest.mark.parametrize("action,extra", [
    ("summary",{}), ("search",{"query":"  native CAM  "}), ("get",{"topic_id":"mill.gop"}),
])
def test_direct_file_route_exact_kwargs_and_preserves_status(server, tmp_path, monkeypatch, action, extra):
    payload = {"status":"partial", "proof_level":"pilot", "missing_sources":["x"], "native_verified":False}
    backend = types.ModuleType("scripts.sw_knowledge_index")
    backend.query_knowledge_index = Mock(return_value=payload)
    monkeypatch.setitem(sys.modules, "scripts.sw_knowledge_index", backend)
    forbidden = Mock(side_effect=AssertionError("No CAD calls permitted"))
    for name in ("_run_locked", "_cam_target", "connect_solidworks", "_load_automation_modules"):
        monkeypatch.setattr(server, name, forbidden, raising=False)
    monkeypatch.setattr(server, "pythoncom", None)
    params = request(server, tmp_path, action=action, detail=True, verify_sources=True, limit=20, **extra)
    result = json.loads(server.solidworks_query_knowledge_index(params))
    assert result == payload
    backend.query_knowledge_index.assert_called_once_with(
        index_path=params.index_path, action=action, limit=20, detail=True, verify_sources=True, **extra)
    forbidden.assert_not_called()
    assert server.pythoncom is None

def test_backend_failure_is_error_no_retry(server, tmp_path, monkeypatch):
    backend = types.ModuleType("scripts.sw_knowledge_index")
    backend.query_knowledge_index = Mock(side_effect=ValueError("index exceeds bounded size"))
    monkeypatch.setitem(sys.modules, "scripts.sw_knowledge_index", backend)
    result = json.loads(server.solidworks_query_knowledge_index(request(server,tmp_path)))
    assert result["status"] == "error" and result["error_type"] == "ValueError"
    assert "bounded size" in result["message"]
    backend.query_knowledge_index.assert_called_once()

def test_full_server_registration_and_defaults(server, tmp_path):
    tool = server.mcp._tool_manager._tools["solidworks_query_knowledge_index"]
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert server.SolidWorksKnowledgeIndexInput.__mro__[1] is server.BaseInput
    fields = server.SolidWorksKnowledgeIndexInput.model_fields
    assert set(fields) == {"index_path","action","query","topic_id","limit","detail","verify_sources","response_format"}
    params=request(server,tmp_path)
    assert params.limit==5 and params.detail is False and params.verify_sources is False
    assert params.response_format is server.ResponseFormat.JSON
    assert server.pythoncom is None and server._automation_loaded is False
    schema=json.dumps(tool.parameters)
    assert '"additionalProperties": false' in schema
    for field in fields:
        assert field in schema
