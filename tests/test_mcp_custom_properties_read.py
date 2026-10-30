"""Schema and dispatch checks for the custom-property read endpoint."""
from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path
import sys
from types import ModuleType

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
import pytest

ROOT = Path(__file__).resolve().parents[1]


def source(fragment, node_name):
    path = ROOT / fragment
    if path.is_file():
        return path.read_text(encoding="utf-8")
    tree = ast.parse((ROOT / "mcp-server/server.py").read_text(encoding="utf-8"))
    node = next(item for item in tree.body if getattr(item, "name", None) == node_name)
    return ast.unparse(node)


class ActiveDocumentInput(BaseModel):
    expected_document_path: str | None = None
    expected_document_title: str | None = None


class ResponseFormat(str, Enum):
    JSON = "json"


class MCP:
    def tool(self, **_kwargs):
        return lambda function: function


def namespace():
    ns = dict(ActiveDocumentInput=ActiveDocumentInput, ConfigDict=ConfigDict,
              Field=Field, field_validator=field_validator, ResponseFormat=ResponseFormat)
    exec(source("server_schema_fragment.py", "SolidWorksReadCustomPropertiesInput"), ns)
    ns["SolidWorksReadCustomPropertiesInput"].model_rebuild(_types_namespace=ns)
    return ns


@pytest.mark.parametrize("names", [
    b"Revision", ("Revision",), [b"Revision"], [1], [True], ["Revision", "revision"], [" "],
])
def test_names_are_validated_before_coercion(names):
    cls = namespace()["SolidWorksReadCustomPropertiesInput"]
    with pytest.raises(ValidationError):
        cls(process_id=42, expected_document_path=r"C:\project\part.SLDPRT", names=names)


@pytest.mark.parametrize("pid", [True, "42", 42.0, 0])
def test_pid_is_strict(pid):
    cls = namespace()["SolidWorksReadCustomPropertiesInput"]
    with pytest.raises(ValidationError):
        cls(process_id=pid, expected_document_path=r"C:\project\part.SLDPRT", names=["Revision"])


@pytest.mark.parametrize("selected_pid", [None, 43, True])
def test_route_blocks_wrong_selected_pid_before_model_access(monkeypatch, selected_pid):
    ns = namespace()
    calls = []
    ns.update(mcp=MCP(), _selected_process_id=selected_pid,
              _active_model_required=lambda params: calls.append("active"),
              _run_locked=lambda operation, response_format: operation())
    exec(source("server_route_fragment.py", "solidworks_read_custom_properties"), ns)
    params = ns["SolidWorksReadCustomPropertiesInput"](
        process_id=42, expected_document_path=r"C:\project\part.SLDPRT", names=["Revision"])
    with pytest.raises(ValueError, match="selected SOLIDWORKS"):
        ns["solidworks_read_custom_properties"](params)
    assert calls == []


def test_route_forwards_only_backend_contract(monkeypatch):
    ns = namespace()
    calls = []
    session = object()
    module = ModuleType("scripts.sw_custom_properties_read")
    def read(sw, **params):
        calls.append((sw, params))
        return {"status": "ok", "read_complete": True}
    module.read_custom_properties = read
    monkeypatch.setitem(sys.modules, module.__name__, module)
    ns.update(mcp=MCP(), _selected_process_id=42,
              _active_model_required=lambda params: (session, object()),
              _run_locked=lambda operation, response_format: operation())
    exec(source("server_route_fragment.py", "solidworks_read_custom_properties"), ns)
    params = ns["SolidWorksReadCustomPropertiesInput"](
        process_id=42, expected_document_path=r"C:\project\part.SLDPRT",
        expected_document_title="part.SLDPRT", names=["Revision"], configuration_name="Default")
    assert ns["solidworks_read_custom_properties"](params)["read_complete"]
    assert calls == [(session, {
        "process_id": 42, "expected_document_path": r"C:\project\part.SLDPRT",
        "names": ["Revision"], "configuration_name": "Default",
    })]
