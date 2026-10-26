"""Actual permanent schema/route AST, with all native/bootstrap names trapped."""
import ast,json
from enum import Enum
from pathlib import Path
from typing import Optional
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import sw_resume_checkpoint as core

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/"mcp-server/server.py").read_text(encoding="utf-8"))
NODES=[n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name in {"BaseInput","ResponseFormat"}]
NS=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,Path=Path,Enum=Enum)
exec(compile(ast.Module(body=NODES,type_ignores=[]),"base_schemas","exec"),NS)
SCHEMA=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=="SolidWorksResumeCheckpointInput")
ROUTE=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=="solidworks_read_resume_checkpoint")
exec(compile(ast.Module(body=[SCHEMA],type_ignores=[]),"resume_schema","exec"),NS)

@pytest.fixture
def probe(tmp_path,monkeypatch):
    backend=Mock(return_value={"status":"ok","continuation_ready_by_saved_evidence":True,"live_state_verified":False,"native_mutation_authorized":False})
    monkeypatch.setattr(core,"read_resume_checkpoint",backend)
    forbidden=Mock(side_effect=AssertionError("No native bootstrap/COM/lock/target/authorization"))
    registry={}
    def tool(**metadata):
        def decorate(fn):registry[metadata["name"]]=metadata;return fn
        return decorate
    namespace=dict(NS,mcp=N(tool=tool),_result=lambda payload,fmt:json.dumps(payload),_tool_error=lambda exc,fmt:json.dumps({"status":"error","message":str(exc)}))
    for name in ("_run_locked","_coinitialize","_load_automation_modules","connect_solidworks","_cam_target","solidworks_operation_lock"):
        namespace[name]=forbidden
    namespace["_runtime_identity"]=N(assert_current=forbidden)
    exec(compile(ast.Module(body=[ROUTE],type_ignores=[]),"resume_route","exec"),namespace)
    model=namespace["SolidWorksResumeCheckpointInput"]
    params=model(status_path=str(tmp_path/"STATUS.json"))
    call=namespace["solidworks_read_resume_checkpoint"]
    return N(**locals())


def test_file_only_route_no_connection_or_COM_initialization(probe):
    assert json.loads(probe.call(probe.params))==probe.backend.return_value
    probe.backend.assert_called_once_with(probe.params.status_path)
    probe.forbidden.assert_not_called()
    annotations=probe.registry["solidworks_read_resume_checkpoint"]["annotations"]
    assert annotations==dict(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=False)


@pytest.mark.parametrize("value",[True,1,None,"relative.json","C:/Folder/file.sldprt","C:/folder/STATUS.json\x00"])
def test_strict_absolute_STATUS_input(probe,value):
    with pytest.raises(ValueError):probe.model(status_path=value)
    probe.backend.assert_not_called();probe.forbidden.assert_not_called()


@pytest.mark.parametrize("field",["process_id","expected_document_path","execute","next_action","recompute","save","max_file_bytes"])
def test_no_native_or_policy_override_inputs(probe,field):
    with pytest.raises(ValueError):probe.model(status_path=probe.params.status_path,**{field:1})
    probe.backend.assert_not_called();probe.forbidden.assert_not_called()


def test_file_failure_does_not_invoke_recovery_or_native_actions(probe):
    probe.backend.side_effect=OSError("missing checkpoint")
    assert json.loads(probe.call(probe.params))["status"]=="error"
    probe.forbidden.assert_not_called()
