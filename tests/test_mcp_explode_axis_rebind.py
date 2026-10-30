"""Isolated schema and dispatch checks for bounded axis repair."""
from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path
import sys
from types import ModuleType
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
import pytest

ROOT = Path(__file__).resolve().parents[1]


def source(fragment, names):
    path = ROOT / fragment
    if path.is_file():
        return path.read_text(encoding="utf-8")
    text = (ROOT / "mcp-server/server.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    return "\n\n".join(ast.unparse(node) for node in tree.body if getattr(node, "name", None) in names)


class ResponseFormat(str, Enum):
    JSON = "json"


class MCP:
    def tool(self, **_kwargs):
        return lambda function: function


def namespace():
    ns = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
              field_validator=field_validator, model_validator=model_validator,
              Path=Path, Literal=Literal, Optional=Optional, ResponseFormat=ResponseFormat,
              absolute_document_path=lambda value: isinstance(value, str) and Path(value).is_absolute())
    names = ["BaseInput", "ActiveDocumentInput", "SolidWorksNativeAssemblyAuditInput",
             "SolidWorksNativeAssemblyInspectionInput", "_native_audit_target"]
    exec(source("server_test_support_fragment.py", names), ns)
    names += ["SolidWorksExplodeAxisTargetInput", "SolidWorksExplodeAxisFaceInput", "SolidWorksExplodeAxisRebindInput"]
    exec(source("server_schema_fragment.py", names[-3:]), ns)
    for name in names:
        if isinstance(ns[name], type) and issubclass(ns[name], BaseModel):
            ns[name].model_rebuild(_types_namespace=ns)
    return ns


@pytest.fixture
def request_data(tmp_path):
    assembly = tmp_path / "Top.SLDASM"; assembly.write_bytes(b"saved top")
    part = tmp_path / "Part.SLDPRT"; part.write_bytes(b"saved owner")
    baseline = tmp_path / "snapshot.json"; baseline.write_text("{}")
    return dict(process_id=42, expected_document_path=str(assembly),
                expected_file_sha256="a"*64, receipt_path=str(tmp_path/"new.json"),
                action="prepare", expected_snapshot_path=str(baseline),
                expected_snapshot_sha256="b"*64, path_replacements={},
                owner_name="Exact-1/Owner-1", owner_reference="BASE", owner_path=str(part),
                owner_sha256="c"*64, cylinder_parameters_native=[0,0,-0.01,0,0,-1,0.02565],
                target_steps=[{"index":1,"name":"Exact Step"}])


@pytest.mark.parametrize("cylinder", [
    [True,0,0,0,0,-1,1], ["0",0,0,0,0,-1,1], [b"0",0,0,0,0,-1,1],
    [float("nan"),0,0,0,0,-1,1], [float("inf"),0,0,0,0,-1,1], [0]*6, tuple([0]*7),
])
def test_cylinder_types_rejected_before_coercion(request_data, cylinder):
    request_data["cylinder_parameters_native"] = cylinder
    with pytest.raises(ValidationError):
        namespace()["SolidWorksExplodeAxisRebindInput"](**request_data)


@pytest.mark.parametrize("index", [True, 1.0, "1", -1, 512])
def test_step_index_is_strict(request_data, index):
    request_data["target_steps"][0]["index"] = index
    with pytest.raises(ValidationError):
        namespace()["SolidWorksExplodeAxisRebindInput"](**request_data)


@pytest.mark.parametrize("value", [True, "42", 42.0, 0])
def test_process_id_is_strict(request_data, value):
    request_data["process_id"] = value
    with pytest.raises(ValidationError):
        namespace()["SolidWorksExplodeAxisRebindInput"](**request_data)


@pytest.mark.parametrize("change", [
    {"target_steps":[]}, {"target_steps":({"index":1,"name":"Exact Step"},)},
    {"target_steps":[{"index":1,"name":"x"},{"index":1,"name":"y"}]},
    {"target_steps":[{"index":1,"name":"x"},{"index":2,"name":"x"}]},
    {"target_steps":[{"index":1,"name":b"Step"}]},
    {"path_replacements":{b"C:/old.SLDPRT":"C:/new.SLDPRT"}},
    {"path_replacements":{"C:/old.SLDPRT":b"C:/new.SLDPRT"}},
    {"action":"apply"},
    {"expected_state_sha256":"d"*64},
    {"action":"apply","expected_state_sha256":"d"*64},
])
def test_scope_and_credentials_are_exact(request_data, change):
    request_data.update(change)
    with pytest.raises(ValidationError):
        namespace()["SolidWorksExplodeAxisRebindInput"](**request_data)


def test_names_are_preserved_and_complete_apply_contract_accepted(request_data, tmp_path):
    request_data["owner_name"] = " Owner-1 "
    request_data["target_steps"][0]["name"] = " Step "
    prep = tmp_path/"prepare.json"; prep.write_text("{}")
    request_data.update(action="apply", expected_state_sha256="d"*64,
                        prepare_receipt_path=str(prep), prepare_receipt_sha256="e"*64)
    value = namespace()["SolidWorksExplodeAxisRebindInput"](**request_data)
    assert value.owner_name == " Owner-1 " and value.target_steps[0].name == " Step "
    assert value.model_dump()["target_steps"] == [{"index":1,"name":" Step "}]


@pytest.mark.parametrize("pid", [None, 43, True, 42.0])
def test_route_rejects_wrong_selected_pid_before_active_model(request_data, monkeypatch, pid):
    ns = namespace(); calls = []
    module = ModuleType("scripts.sw_explode_axis_rebind")
    module.rebind_explode_axes = lambda *a, **k: calls.append("backend")
    monkeypatch.setitem(sys.modules,module.__name__,module)
    ns.update(mcp=MCP(), _selected_process_id=pid,
              _active_model_required=lambda params: calls.append("active"),
              _run_locked=lambda op, fmt: op())
    exec(source("server_route_fragment.py",["solidworks_rebind_explode_axes"]),ns)
    params = ns["SolidWorksExplodeAxisRebindInput"](**request_data)
    with pytest.raises(ValueError,match="exact explicit PID"):
        ns["solidworks_rebind_explode_axes"](params)
    assert calls == []


def test_route_preserves_lock_target_and_exact_backend_contract(request_data, monkeypatch):
    ns = namespace(); calls = []; session = object()
    module = ModuleType("scripts.sw_explode_axis_rebind")
    def backend(sw, **params):
        calls.append(("backend",sw,params))
        return {"repair_verified":False,"phase":"prepared"}
    module.rebind_explode_axes = backend
    monkeypatch.setitem(sys.modules,module.__name__,module)
    def active(params):
        calls.append(("active",params.process_id,params.expected_document_path))
        return session, object()
    def locked(op,fmt):
        calls.append(("locked",fmt))
        return op()
    ns.update(mcp=MCP(),_selected_process_id=42,_active_model_required=active,_run_locked=locked)
    exec(source("server_route_fragment.py",["solidworks_rebind_explode_axes"]),ns)
    params = ns["SolidWorksExplodeAxisRebindInput"](**request_data,expected_document_title="Top.SLDASM")
    assert ns["solidworks_rebind_explode_axes"](params)["phase"] == "prepared"
    assert calls[0] == ("locked",ResponseFormat.JSON)
    assert calls[1] == ("active",42,request_data["expected_document_path"])
    forwarded = calls[2][2]
    assert calls[2][0:2] == ("backend",session)
    assert forwarded == params.model_dump(exclude={"response_format","expected_document_title"})
    assert type(forwarded["target_steps"][0]) is dict

@pytest.mark.parametrize("group", [
    [], [{"body_index":0,"face_index":1}],
    ({"body_index":0,"face_index":1},{"body_index":0,"face_index":2}),
    [{"body_index":0,"face_index":1},{"body_index":0,"face_index":1}],
    [{"body_index":True,"face_index":1},{"body_index":0,"face_index":2}],
    [{"body_index":0.0,"face_index":1},{"body_index":0,"face_index":2}],
    [{"body_index":0,"face_index":"1"},{"body_index":0,"face_index":2}],
    [{"body_index":0,"face_index":b"1"},{"body_index":0,"face_index":2}],
    [{"body_index":-1,"face_index":1},{"body_index":0,"face_index":2}],
    [{"body_index":64,"face_index":1},{"body_index":0,"face_index":2}],
    [{"body_index":0,"face_index":8192},{"body_index":0,"face_index":2}],
    [{"body_index":0,"face_index":1,"area":9},{"body_index":0,"face_index":2}],
    [{"body_index":0,"face_index":i} for i in range(33)],
])
def test_equivalent_group_schema_refuses_implicit_or_coercible_inputs(request_data, group):
    request_data["equivalent_face_group"] = group
    with pytest.raises(ValidationError):
        namespace()["SolidWorksExplodeAxisRebindInput"](**request_data)


def test_group_opt_in_preserves_exact_faces_and_default_none(request_data):
    model = namespace()["SolidWorksExplodeAxisRebindInput"]
    assert model(**request_data).equivalent_face_group is None
    group = [{"body_index":0,"face_index":8},{"body_index":0,"face_index":2}]
    params = model(**request_data, equivalent_face_group=group)
    assert params.model_dump()["equivalent_face_group"] == group


def test_route_forwards_explicit_group_unchanged(request_data, monkeypatch):
    ns = namespace(); calls = []; session = object()
    module = ModuleType("scripts.sw_explode_axis_rebind")
    def backend(sw, **params):
        calls.append((sw, params)); return {"phase":"prepared"}
    module.rebind_explode_axes = backend
    monkeypatch.setitem(sys.modules,module.__name__,module)
    ns.update(mcp=MCP(),_selected_process_id=42,
              _active_model_required=lambda params:(session,object()),
              _run_locked=lambda op,fmt:op())
    exec(source("server_route_fragment.py",["solidworks_rebind_explode_axes"]),ns)
    group = [{"body_index":0,"face_index":8},{"body_index":0,"face_index":2}]
    params = ns["SolidWorksExplodeAxisRebindInput"](**request_data,equivalent_face_group=group)
    assert ns["solidworks_rebind_explode_axes"](params)["phase"] == "prepared"
    assert calls[0][0] is session
    assert calls[0][1]["equivalent_face_group"] == group
