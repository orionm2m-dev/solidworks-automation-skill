"""Isolated MCP schema and route tests for native explode-step matrix reads."""
import ast
from enum import Enum
from pathlib import Path
import sys
from types import ModuleType
from typing import Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT=Path(__file__).resolve().parents[1]

def source(fragment,names):
    p=ROOT/fragment
    if p.is_file(): return p.read_text(encoding="utf-8")
    text=(ROOT/"mcp-server/server.py").read_text(encoding="utf-8")
    return "\n\n".join(ast.unparse(n) for n in ast.parse(text).body if getattr(n,"name",None) in names)

class ResponseFormat(str,Enum):
    JSON="json"

class MCP:
    def tool(self,**kwargs):
        return lambda function:function

def namespace():
    ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,
        field_validator=field_validator,model_validator=model_validator,Path=Path,Optional=Optional,
        ResponseFormat=ResponseFormat,absolute_document_path=lambda value:Path(value).is_absolute())
    support=["BaseInput","ActiveDocumentInput","SolidWorksNativeAssemblyAuditInput","_native_audit_target"]
    names=["SolidWorksExplodeStepTransformTargetInput","SolidWorksExplodeStepTransformsInput"]
    exec(source("server_test_support_fragment.py",support),ns)
    exec(source("server_schema_fragment.py",names),ns)
    for name in support+names:
        if isinstance(ns[name],type) and issubclass(ns[name],BaseModel):
            ns[name].model_rebuild(_types_namespace=ns)
    return ns

@pytest.fixture
def data(tmp_path):
    p=tmp_path/"TOP.SLDASM";p.write_bytes(b"saved")
    return dict(process_id=42,expected_document_path=str(p),expected_file_sha256="a"*64,
                receipt_path=str(tmp_path/"new.json"),
                targets=[dict(index=49,name="TURN_01",component_name="GROUP-1/RING-1")])

@pytest.mark.parametrize("pid",[None,True,42.0,"42",0,-1])
def test_strict_pid(data,pid):
    data["process_id"]=pid
    with pytest.raises(ValidationError): namespace()["SolidWorksExplodeStepTransformsInput"](**data)

@pytest.mark.parametrize("changes",[
    {"targets":[]},{"targets":({"index":49,"name":"n","component_name":"c"},)},
    {"expected_file_sha256":"bad"},{"expected_document_path":"relative.SLDASM"},
    {"expected_document_title":"TOP.SLDASM"},{"action":"apply"},{"save":True},
    {"set_time":1.0},{"rebuild":True},{"activate":True},
])
def test_invalid_or_mutating_options(data,changes):
    data.update(changes)
    with pytest.raises(ValidationError): namespace()["SolidWorksExplodeStepTransformsInput"](**data)

@pytest.mark.parametrize("field,value",[
    ("index",True),("index",49.0),("index","49"),("index",-1),("index",512),
    ("name",""),("name",None),("name",49),("component_name",""),("component_name",None),
    ("component_name",True),("extra","value")
])
def test_exact_strict_target(data,field,value):
    data["targets"][0][field]=value
    with pytest.raises(ValidationError): namespace()["SolidWorksExplodeStepTransformsInput"](**data)

@pytest.mark.parametrize("kind",["index","name","too_many"])
def test_duplicates_and_bounds(data,kind):
    if kind=="too_many":
        data["targets"]=[dict(index=i,name=str(i),component_name="c") for i in range(33)]
    else:
        row=dict(data["targets"][0])
        row["name" if kind=="index" else "index"]="other" if kind=="index" else 50
        data["targets"].append(row)
    with pytest.raises(ValidationError): namespace()["SolidWorksExplodeStepTransformsInput"](**data)

def test_exact_names_and_new_receipt(data):
    data["targets"][0]["name"]="  Exact name  "
    schema=namespace()["SolidWorksExplodeStepTransformsInput"]
    result=schema(**data)
    assert result.model_dump(exclude={"response_format","expected_document_title"})==data
    Path(data["receipt_path"]).write_text("existing")
    with pytest.raises(ValidationError):schema(**data)

@pytest.mark.parametrize("pid",[None,True,42.0,43])
def test_selected_pid_guard_blocks_backend(data,monkeypatch,pid):
    ns=namespace();calls=[]
    module=ModuleType("scripts.sw_explode_step_transforms")
    module.read_explode_step_transforms=lambda *a,**k:calls.append("backend")
    monkeypatch.setitem(sys.modules,module.__name__,module)
    ns.update(mcp=MCP(),_selected_process_id=pid,_active_model_required=lambda p:calls.append("active"),
              _run_locked=lambda op,fmt:op())
    exec(source("server_route_fragment.py",["solidworks_read_explode_step_transforms"]),ns)
    with pytest.raises(ValueError,match="exact explicit PID"):
        ns["solidworks_read_explode_step_transforms"](ns["SolidWorksExplodeStepTransformsInput"](**data))
    assert calls==[]

def test_route_lock_and_exact_payload(data,monkeypatch):
    ns=namespace();calls=[];sw=object()
    module=ModuleType("scripts.sw_explode_step_transforms")
    def backend(session,**params):
        calls.append(("backend",session,params));return {"readback_complete":True}
    module.read_explode_step_transforms=backend
    monkeypatch.setitem(sys.modules,module.__name__,module)
    def active(params):calls.append(("active",params.process_id,params.expected_document_path));return sw,object()
    def locked(op,fmt):calls.append(("locked",fmt));return op()
    ns.update(mcp=MCP(),_selected_process_id=42,_active_model_required=active,_run_locked=locked)
    exec(source("server_route_fragment.py",["solidworks_read_explode_step_transforms"]),ns)
    params=ns["SolidWorksExplodeStepTransformsInput"](**data)
    assert ns["solidworks_read_explode_step_transforms"](params)=={"readback_complete":True}
    assert calls==[("locked",ResponseFormat.JSON),("active",42,data["expected_document_path"]),
                   ("backend",sw,data)]
