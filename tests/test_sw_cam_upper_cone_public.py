"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
import ast
from copy import deepcopy
from enum import Enum
import inspect
import json
from pathlib import Path
import re
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import pytest
from scripts.sw_operation_guard import absolute_document_path
from scripts import sw_cam_upper_cone_feature as implementation

STAGE = Path(implementation.__file__).resolve().parents[1]
CLSID = "{CCAC6208-0E19-6455-2022-2026CEB541FA}"


def public_namespace():
    source = (STAGE / "mcp-server/server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"ResponseFormat", "BaseInput", "ActiveDocumentInput", "SolidWorksCamTargetInput",
             "SolidWorksCamUpperConeFeatureInput", "_cam_target", "solidworks_cam_create_upper_cone_feature"}
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == names
    registered = {}
    class MCP:
        def tool(self, **metadata):
            def decorator(function):
                registered[metadata["name"]] = function
                return function
            return decorator
    namespace = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
        field_validator=field_validator, model_validator=model_validator, Enum=Enum,
        Dict=Dict, Any=Any, Literal=Literal, Optional=Optional, Path=Path, re=re,
        absolute_document_path=absolute_document_path, mcp=MCP())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(STAGE/"mcp-server/server.py"), "exec"), namespace)
    assert "solidworks_cam_create_upper_cone_feature" in registered
    return namespace


def request_params(filename=None):
    base=Path.cwd().resolve()
    return dict(process_id=17,expected_document_path=str(base/'fixture.SLDPRT'),expected_source_sha256='a'*64,addin_clsid=CLSID,baseline_path=str(base/'baseline.json'),baseline_sha256='b'*64,sketch_receipt_path=str(base/'sketch.json'),sketch_receipt_sha256='c'*64,sketch_spec=dict(plane_axis='Z',plane_offset_mm=26.,sketch_name='UpperConeCircle',plane_name='UpperConePlane',profile=dict(kind='circle',center_model_mm=[0.,0.,26.],radius_mm=23.55)),taper_angle_native=45.,taper_type=0,acknowledge_unqualified_taper=True,receipt_path=str(base/'result.json'),qualification_only=True,acknowledge_disposable_copy=True)



def test_actual_public_request_reaches_exact_target_and_native_validator(tmp_path, monkeypatch):
    namespace = public_namespace()
    values = request_params()
    params = namespace["SolidWorksCamUpperConeFeatureInput"].model_validate(values)
    assert params.addin_clsid == CLSID
    # Use the actual registry selector against a synthetic offline discovery result.
    dll = tmp_path / "cam.dll"
    dll.write_bytes(b"offline registration fixture; never loaded")
    inventory = dict(errors=[], addin_registrations=[dict(clsid=CLSID, registry_key="SOLIDWORKS 2026")],
        com_registrations=[dict(clsid=CLSID, view="64", progid="CAM", typelib_id="offline",
            servers=[dict(kind="inproc", path=str(dll), exists=True)])])
    from scripts import sw_cam_installation
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", lambda: inventory)
    sw = object()
    namespace["_selected_process_id"] = values["process_id"]
    namespace["_active_model_required"] = lambda received: (sw, object()) if received is params else pytest.fail("Wrong target model")
    namespace["get_com_member"] = lambda target, name: "34.0.0" if target is sw and name == "RevisionNumber" else pytest.fail("Unexpected COM access")
    namespace["_run_locked"] = lambda operation, response_format: operation()
    original_signature = inspect.signature(implementation.create_upper_cone_feature)
    calls = []
    def invoke_native_validator(target, clsid, typelib_path, **arguments):
        assert target is sw and clsid == CLSID
        original_signature.bind(target, clsid, typelib_path, **arguments)
        assert "addin_clsid" not in arguments and "response_format" not in arguments
        assert "expected_document_title" not in arguments
        implementation.validate_cone_request(**{key: arguments[key] for key in
            ("sketch_spec", "taper_angle_native", "taper_type", "acknowledge_unqualified_taper")})
        calls.append(arguments)
        return {"offline_validation_only": True}
    monkeypatch.setattr(implementation, "create_upper_cone_feature", invoke_native_validator)
    result = namespace["solidworks_cam_create_upper_cone_feature"](params)
    assert result == {"offline_validation_only": True} and len(calls) == 1


@pytest.mark.parametrize("change", ["missing_clsid", "malformed_clsid", "unknown_parameter", "relative_document", "unqualified_not_acknowledged", "title_target"])
def test_actual_public_model_rejects_invalid_inputs(change):
    namespace = public_namespace()
    values = request_params()
    if change == "missing_clsid": values.pop("addin_clsid")
    elif change == "malformed_clsid": values["addin_clsid"] = "CAM"
    elif change == "unknown_parameter": values["unrecognized"] = True
    elif change == "relative_document": values["expected_document_path"] = "part.sldprt"
    elif change == "unqualified_not_acknowledged": values["acknowledge_unqualified_taper"] = False
    else: values["expected_document_title"] = "Other.SLDPRT"
    with pytest.raises(ValueError): namespace["SolidWorksCamUpperConeFeatureInput"].model_validate(values)


def test_wrong_owned_pid_stops_before_discovery(monkeypatch):
    namespace = public_namespace()
    params = namespace["SolidWorksCamUpperConeFeatureInput"].model_validate(request_params())
    namespace["_selected_process_id"] = params.process_id + 1
    namespace["_run_locked"] = lambda operation, response_format: operation()
    from scripts import sw_cam_installation
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", lambda: pytest.fail("Discovery must not run"))
    with pytest.raises(ValueError, match="Explicitly connected owned process"):
        namespace["solidworks_cam_create_upper_cone_feature"](params)


