"""Compile schema nodes only; the MCP server is never started."""
import ast
from enum import Enum
from pathlib import Path
from typing import Optional, Literal
import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from test_sandvik_save import ROOT, STAGE
from scripts.sw_operation_guard import absolute_document_path

def schema():
    source=(ROOT/"mcp-server/server.py").read_text(encoding="utf-8")
    names={"ResponseFormat","BaseInput","ActiveDocumentInput","SolidWorksCamTargetInput",
           "SolidWorksCamSavedMillPlanToolsInput"}
    nodes=[n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name in names]
    snippet=STAGE/"snippets/sandvik_save_server.py"
    source_new=snippet.read_text(encoding="utf-8-sig") if snippet.exists() else source
    nodes += [n for n in ast.parse(source_new).body if isinstance(n,ast.ClassDef) and n.name=="SolidWorksCamSandvikDraftSaveInput"]
    scope=dict(globals())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),"exec"),scope)
    return scope["SolidWorksCamSandvikDraftSaveInput"]

def request(tmp_path):
    part=tmp_path/"qualification.sldprt";part.write_bytes(b"source")
    saved=tmp_path/"saved.json";saved.write_text("{}")
    return dict(addin_clsid="{12345678-1234-1234-1234-123456789012}",process_id=23824,
        expected_document_path=str(part),expected_source_sha256="a"*64,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145,
        qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(tmp_path/"out.json"),
        saved_plan_receipt_path=str(saved),saved_plan_receipt_sha256="b"*64,
        phase1_receipt_path=str(saved),phase1_receipt_sha256="c"*64,expected_candidate_tool_native_id=250)

def test_exact_save_schema(tmp_path):
    assert schema()(**request(tmp_path)).expected_candidate_tool_native_id==250

@pytest.mark.parametrize("change",[
    {"expected_candidate_tool_native_id":True},{"expected_candidate_tool_native_id":0},
    {"expected_candidate_tool_native_id":250.0},{"phase1_receipt_sha256":"<PENDING>"},
    {"GTP":True},{"assignment":True},{"save_after_verified":True},
    {"session_rebind_receipt_sha256":"b"*64}])
def test_save_schema_rejects_unsafe_or_implicit_scope(tmp_path,change):
    with pytest.raises(ValueError):schema()(**(request(tmp_path)|change))

