"""Schema extraction never imports or starts the MCP server."""
import ast
from enum import Enum
from pathlib import Path
from typing import Optional, Literal
import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from test_sandvik_phase1 import ROOT, STAGE
from scripts.sw_operation_guard import absolute_document_path

def schema():
    source=(ROOT/"mcp-server/server.py").read_text(encoding="utf-8")
    names={"ResponseFormat","BaseInput","ActiveDocumentInput","SolidWorksCamTargetInput",
           "SolidWorksCamSavedMillPlanToolsInput"}
    nodes=[n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name in names]
    snippet=STAGE/"snippets/sandvik_phase1_server.py"
    source_new=snippet.read_text(encoding="utf-8") if snippet.exists() else source
    nodes += [n for n in ast.parse(source_new).body if isinstance(n,ast.ClassDef) and n.name=="SolidWorksCamSandvikQualificationInput"]
    scope=dict(globals())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),"exec"),scope)
    return scope["SolidWorksCamSandvikQualificationInput"]

def request(tmp_path):
    part=tmp_path/"qualification.sldprt";part.write_bytes(b"source")
    saved=tmp_path/"saved.json";saved.write_text("{}")
    d=dict(addin_clsid="{12345678-1234-1234-1234-123456789012}",process_id=23824,
        expected_document_path=str(part),expected_source_sha256="a"*64,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145,
        qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(tmp_path/"output.json"),
        saved_plan_receipt_path=str(saved),saved_plan_receipt_sha256="b"*64,
        expected_sw_document_units_raw=[0,1,0,2,0],expected_cam_use_document_units=True,acknowledge_experimental=True)
    for key in ["candidate_contract","source_cad","reference_mt","profile_analysis","holder_file","holder_recipe","firstcut_receipt"]:
        d[key+"_path"]=str(saved);d[key+"_sha256"]="b"*64
    for key in ["candidate_mt_path","cutting_stl_path","noncutting_stl_path"]:d[key]=str(tmp_path/key)
    return d

def test_schema_accepts_exact_bounded_parameters(tmp_path):
    result=schema()(**request(tmp_path))
    assert result.expected_sw_document_units_raw==[0,1,0,2,0]

@pytest.mark.parametrize("change",[
    dict(acknowledge_experimental=1),dict(expected_cam_use_document_units=1),
    dict(expected_sw_document_units_raw=[False,1,0,2,0]),
    dict(expected_sw_document_units_raw=[3,1,0,2,0]),dict(firstcut_receipt_sha256="<PENDING>"),
    dict(save_after_verified=True),dict(GTP=True),dict(tool_assignment=True),
    dict(session_rebind_receipt_sha256="b"*64)])
def test_schema_rejects_unsafe_or_unscoped_arguments(tmp_path,change):
    with pytest.raises(ValueError):schema()(**(request(tmp_path)|change))

