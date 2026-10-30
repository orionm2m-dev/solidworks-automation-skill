"""Offline schema acceptance only; never imports or starts the MCP server."""
import ast
from enum import Enum
from pathlib import Path
from typing import Optional, Literal
import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scripts import sw_cam
from scripts.sw_operation_guard import absolute_document_path

def schema():
    root=Path(sw_cam.__file__).parents[1]
    source=(root/"mcp-server/server.py").read_text(encoding="utf-8")
    names={"ResponseFormat","BaseInput","ActiveDocumentInput","SolidWorksCamTargetInput",
           "SolidWorksCamSavedMillPlanToolsInput"}
    nodes=[n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name in names]
    snippet=Path(__file__).parents[1]/"snippets/defined_rough_levels_server.py"
    source_new=snippet.read_text(encoding="utf-8") if snippet.exists() else source
    nodes += [n for n in ast.parse(source_new).body if isinstance(n,ast.ClassDef) and n.name=="SolidWorksCamDefinedRoughLevelsInput"]
    scope=dict(globals())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),"exec"),scope)
    return scope["SolidWorksCamDefinedRoughLevelsInput"]

def request(tmp_path):
    part=tmp_path/"qualification.sldprt";part.write_bytes(b"source")
    saved=tmp_path/"saved.json";saved.write_text("{}",encoding="utf-8")
    return dict(addin_clsid="{12345678-1234-1234-1234-123456789012}",process_id=23824,
        expected_document_path=str(part),expected_source_sha256="a"*64,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145,
        qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(tmp_path/"output.json"),
        saved_plan_receipt_path=str(saved),saved_plan_receipt_sha256="b"*64,
        target_feature_native_id=244,target_operation_native_id=247,target_operation_setup_native_id=93)

def test_exact_definitions_schema_accepts(tmp_path):
    out=schema()(**request(tmp_path))
    assert out.target_feature_native_id==244 and out.target_operation_native_id==247

@pytest.mark.parametrize("change",[
    dict(target_operation_native_id=True),dict(expected_operation_native_ids=[143,True]),
    dict(GTP=True),dict(session_rebind_receipt_sha256="b"*64)])
def test_schema_rejects_unsupported_fields(tmp_path,change):
    with pytest.raises(ValueError):schema()(**(request(tmp_path)|change))
