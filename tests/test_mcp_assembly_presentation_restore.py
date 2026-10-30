"""Isolated schema and route checks for presentation restoration."""
import ast
from enum import Enum
from pathlib import Path
import sys
from types import ModuleType
from typing import Literal, Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]


def source(fragment, names):
    path = ROOT / fragment
    if path.is_file():
        return path.read_text(encoding="utf-8")
    text = (ROOT / "mcp-server/server.py").read_text(encoding="utf-8")
    return "\n\n".join(ast.unparse(n) for n in ast.parse(text).body if getattr(n,"name",None) in names)


class ResponseFormat(str,Enum):
    JSON = "json"


class MCP:
    def tool(self, **kwargs):
        return lambda function:function


def namespace():
    ns = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, field_validator=field_validator,
              model_validator=model_validator, Path=Path, Literal=Literal, Optional=Optional,
              ResponseFormat=ResponseFormat, absolute_document_path=lambda value:Path(value).is_absolute())
    names=["BaseInput","ActiveDocumentInput","SolidWorksNativeAssemblyAuditInput","_native_audit_target"]
    exec(source("server_test_support_fragment.py",names),ns)
    names.append("SolidWorksRestoreAssemblyPresentationInput")
    exec(source("server_schema_fragment.py",names[-1:]),ns)
    for name in names:
        if isinstance(ns[name],type) and issubclass(ns[name],BaseModel):
            ns[name].model_rebuild(_types_namespace=ns)
    return ns


@pytest.fixture
def request_data(tmp_path):
    top=tmp_path/"Top.SLDASM"; top.write_bytes(b"saved")
    prior=tmp_path/"prior.json"; prior.write_text("{}")
    return dict(process_id=42,expected_document_path=str(top),expected_file_sha256="a"*64,
                receipt_path=str(tmp_path/"new.json"),action="prepare",
                prior_rebind_receipt_path=str(prior),prior_rebind_receipt_sha256="b"*64,
                explode_view_name="Exact Existing View")


@pytest.mark.parametrize("value",[True,42.0,"42",0])
def test_pid_is_strict(request_data,value):
    request_data["process_id"]=value
    with pytest.raises(ValidationError):
        namespace()["SolidWorksRestoreAssemblyPresentationInput"](**request_data)


@pytest.mark.parametrize("change",[
    {"action":"collapse"},{"action":"apply"},{"action":True},{"explode_view_name":True},
    {"explode_view_name":b"Name"},{"explode_view_name":""},{"prior_rebind_receipt_sha256":"bad"},
    {"expected_state_sha256":"a"*64},{"prior_rebind_receipt_path":"relative.json"},
    {"prior_rebind_receipt_path":None},{"expected_document_path":"relative.SLDASM"},
])
def test_scope_and_credentials_rejected(request_data,change):
    request_data.update(change)
    with pytest.raises(ValidationError):
        namespace()["SolidWorksRestoreAssemblyPresentationInput"](**request_data)


def test_complete_apply_preserves_exact_name(request_data,tmp_path):
    prep=tmp_path/"prepare.json"; prep.write_text("{}")
    request_data.update(action="apply",expected_state_sha256="c"*64,
                        prepare_receipt_path=str(prep),prepare_receipt_sha256="d"*64,
                        explode_view_name=" Existing View ")
    value=namespace()["SolidWorksRestoreAssemblyPresentationInput"](**request_data)
    assert value.explode_view_name == " Existing View "


@pytest.mark.parametrize("pid",[None,43,True,42.0])
def test_wrong_selected_pid_blocks_route_before_native(request_data,monkeypatch,pid):
    ns=namespace(); calls=[]
    module=ModuleType("scripts.sw_assembly_presentation_restore")
    module.restore_assembly_presentation=lambda *a,**k:calls.append("backend")
    monkeypatch.setitem(sys.modules,module.__name__,module)
    ns.update(mcp=MCP(),_selected_process_id=pid,_active_model_required=lambda p:calls.append("active"),
              _run_locked=lambda op,fmt:op())
    exec(source("server_route_fragment.py",["solidworks_restore_assembly_presentation"]),ns)
    with pytest.raises(ValueError,match="exact explicit PID"):
        ns["solidworks_restore_assembly_presentation"](ns["SolidWorksRestoreAssemblyPresentationInput"](**request_data))
    assert calls == []


def test_route_pins_pid_locks_and_forwards_exact_fields(request_data,monkeypatch):
    ns=namespace(); calls=[]; sw=object()
    module=ModuleType("scripts.sw_assembly_presentation_restore")
    def backend(session,**params):
        calls.append(("backend",session,params)); return {"phase":"prepared"}
    module.restore_assembly_presentation=backend
    monkeypatch.setitem(sys.modules,module.__name__,module)
    def active(params):
        calls.append(("active",params.process_id,params.expected_document_path)); return sw,object()
    def locked(op,fmt):
        calls.append(("locked",fmt)); return op()
    ns.update(mcp=MCP(),_selected_process_id=42,_active_model_required=active,_run_locked=locked)
    exec(source("server_route_fragment.py",["solidworks_restore_assembly_presentation"]),ns)
    params=ns["SolidWorksRestoreAssemblyPresentationInput"](**request_data,expected_document_title="Top.SLDASM")
    assert ns["solidworks_restore_assembly_presentation"](params) == {"phase":"prepared"}
    assert calls[0] == ("locked",ResponseFormat.JSON)
    assert calls[1] == ("active",42,request_data["expected_document_path"])
    assert calls[2] == ("backend",sw,params.model_dump(exclude={"response_format","expected_document_title"}))
