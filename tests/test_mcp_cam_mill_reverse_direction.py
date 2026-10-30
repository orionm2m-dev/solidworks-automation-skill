"""Existing schema/route contract for one additional strict creator parameter."""
import ast
from enum import Enum
import json
from pathlib import Path
import sys
from types import SimpleNamespace as N
from typing import Optional, Literal, Any, Dict
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scripts.sw_operation_guard import absolute_document_path

ROOT=Path(__file__).resolve().parents[1]
candidate=ROOT/"server_proposed.py"
SOURCE=(candidate if candidate.is_file() else ROOT/"mcp-server/server.py").read_text(encoding="utf-8-sig")
TREE=ast.parse(SOURCE)
NAMES={"ResponseFormat","BaseInput","ActiveDocumentInput","SolidWorksCamTargetInput",
       "SolidWorksCamMaterialCatalogueInput","SolidWorksCamMillUnitsInput"}
NODES=[n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name in NAMES]
assert {n.name for n in NODES}==NAMES
NS=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
    model_validator=model_validator,Optional=Optional,Literal=Literal,Any=Any,Dict=Dict,Enum=Enum,Path=Path,
    absolute_document_path=absolute_document_path)
exec(compile(ast.Module(body=NODES,type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),"exec"),NS)
MODEL=NS["SolidWorksCamMillUnitsInput"]
TOOL="solidworks_cam_qualify_mill_feature_units"
NODE=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==TOOL)
SPEC=dict(plane_axis="Z",plane_offset_mm=22,sketch_name="RectangleZ22",plane_name="PlaneZ22",
    profile=dict(kind="closed_polyline",points_model_mm=[[1,1,22],[4,1,22],[4,6,22],[1,6,22]]))


@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/"fixture.sldprt";path.write_bytes(b"saved")
    core=Mock(return_value=dict(status="review_required",orientation_semantics_verified=False))
    monkeypatch.setitem(sys.modules,"scripts.sw_cam_mill_units_qualification",N(qualify_mill_feature_units=core))
    sw=object();registration=dict(clsid="{00000000-0000-0000-0000-000000000001}",addin_path=str(tmp_path/"cam.dll"))
    target=Mock(return_value=(sw,registration))
    def locked(fn,fmt):
        try:return json.dumps(fn())
        except Exception as exc:return json.dumps(dict(status="error",issue=str(exc)))
    ns=dict(NS,mcp=N(tool=lambda **kw:lambda fn:fn),_selected_process_id=731,
            _cam_target=target,_run_locked=locked)
    exec(compile(ast.Module(body=[NODE],type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),"exec"),ns)
    def params(**kw):
        values=dict(process_id=731,addin_clsid=registration["clsid"],expected_document_path=str(path),
            expected_source_sha256="a"*64,action="inspect",expected_setup_native_id=17,
            sketch_spec=SPEC,depth_native=3,qualification_only=True,acknowledge_disposable_copy=True)
        return MODEL(**(values|kw))
    return N(**locals())


@pytest.mark.parametrize("value",[None,0,1,0.,1.,"true","false",[]])
def test_schema_rejects_nonbool_reverse_before_native(probe,value):
    with pytest.raises(ValueError):probe.params(reverse_direction=value)
    probe.core.assert_not_called();probe.target.assert_not_called()


@pytest.mark.parametrize("changes",[{},{"reverse_direction":False},{"reverse_direction":True}])
def test_default_and_explicit_reverse_route_unchanged(probe,changes):
    request=probe.params(**changes)
    assert request.reverse_direction is changes.get("reverse_direction",False)
    assert json.loads(probe.ns[TOOL](request))["status"]=="review_required"
    probe.core.assert_called_once_with(probe.sw,probe.registration["clsid"],
        typelib_path=str(Path(probe.registration["addin_path"]).parent/"camworks.tlb"),
        **request.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))


def test_existing_selected_pid_guard_still_applies(probe):
    probe.ns["_selected_process_id"]=732
    assert json.loads(probe.ns[TOOL](probe.params(reverse_direction=True)))["status"]=="error"
    probe.target.assert_not_called();probe.core.assert_not_called()
