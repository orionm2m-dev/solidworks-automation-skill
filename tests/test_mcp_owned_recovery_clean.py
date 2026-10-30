"""The recovery MCP accepts empty discard acknowledgement; core must prove clean state."""
from __future__ import annotations
import ast
from enum import Enum
from pathlib import Path
import re
from typing import Literal,Optional
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
import pytest

ROOT=Path(__file__).resolve().parents[1]
class ResponseFormat(str,Enum):
    JSON="json"

def model():
    p=ROOT/"server_schema_fragment.py"
    if p.is_file():text=p.read_text(encoding="utf-8")
    else:
        source=(ROOT/"mcp-server/server.py").read_text(encoding="utf-8")
        names={"BaseInput","SolidWorksOwnedRecoveryEvidenceInput","SolidWorksOwnedRecoverySpecInput","SolidWorksOwnedProcessRecoveryInput"}
        text="\n\n".join(ast.unparse(n) for n in ast.parse(source).body if getattr(n,"name",None) in names)
    ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
        model_validator=model_validator,Path=Path,re=re,Literal=Literal,Optional=Optional,ResponseFormat=ResponseFormat)
    exec(text,ns)
    for name,value in ns.copy().items():
        if isinstance(value,type) and value is not BaseModel and issubclass(value,BaseModel):value.model_rebuild(_types_namespace=ns)
    return ns["SolidWorksOwnedProcessRecoveryInput"]

def request(tmp_path):
    ref={"path":str(tmp_path/"evidence.json"),"sha256":"a"*64}
    return dict(action="apply",spec=dict(process_id=123,expected_executable_path="C:/Vendor/SLDWORKS.exe",
        expected_creation_filetime=134374603574011237,ownership_receipt=ref,
        process_identity_evidence=ref,recovery_manifest=ref),expected_state_sha256="b"*64,
        acknowledge_terminate_owned_process=True,acknowledged_discard_ids=[],
        receipt_path=str(tmp_path/"new.json"))

@pytest.mark.parametrize("ids",[[],["unsaved-item"]])
def test_exact_empty_or_nonempty_ack_reaches_core_contract(tmp_path,ids):
    data=request(tmp_path);data["acknowledged_discard_ids"]=ids
    assert model()(**data).model_dump()["acknowledged_discard_ids"]==ids

@pytest.mark.parametrize("ids",[None,(),[True],[1],[b"item"],["item","item"],["bad id"]])
def test_invalid_ack_remains_rejected(tmp_path,ids):
    data=request(tmp_path);data["acknowledged_discard_ids"]=ids
    with pytest.raises(ValueError):model()(**data)

def test_prepare_still_refuses_empty_apply_ack(tmp_path):
    data=request(tmp_path);data["action"]="prepare"
    with pytest.raises(ValueError):model()(**data)
