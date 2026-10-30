"""Isolated input and route contracts for one rough-boundary percentage setter."""
import ast
from enum import Enum
from pathlib import Path
import sys
from types import ModuleType
from typing import Literal, Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT=Path(__file__).resolve().parents[1]
SUPPORT=["BaseInput","SolidWorksCamSelectedFeatureContextInput","ActiveDocumentInput","SolidWorksCamTargetInput",
         "SolidWorksCamMaterialCatalogueInput","SolidWorksCamMillOperationLevelsInput",
         "SolidWorksCamMillRoughBoundaryInput"]

def source(fragment,names):
    p=ROOT/fragment
    if p.is_file():return p.read_text(encoding="utf-8")
    text=(ROOT/"mcp-server/server.py").read_text(encoding="utf-8")
    return "\n\n".join(ast.unparse(n) for n in ast.parse(text).body if getattr(n,"name",None) in names)

class ResponseFormat(str,Enum):
    JSON="json"

class MCP:
    def tool(self,**kwargs):return lambda function:function

def namespace():
    ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
        model_validator=model_validator,Literal=Literal,Optional=Optional,Path=Path,
        ResponseFormat=ResponseFormat,absolute_document_path=lambda v:Path(v).is_absolute())
    exec(source("server_test_support_fragment.py",SUPPORT),ns)
    exec(source("server_schema_fragment.py",["SolidWorksCamMillRoughBoundarySetInput"]),ns)
    for name in SUPPORT+["SolidWorksCamMillRoughBoundarySetInput"]:
        ns[name].model_rebuild(_types_namespace=ns)
    return ns

@pytest.fixture
def data(tmp_path):
    p=tmp_path/"Qualification.SLDPRT";p.write_bytes(b"source")
    return dict(addin_clsid="{11111111-2222-3333-4444-555555555555}",process_id=123,
        expected_document_path=str(p),expected_source_sha256="a"*64,
        expected_feature_native_id=10,expected_operation_native_id=20,
        expected_mill_operation_type=0,expected_toolpath_record_counts=[12],
        expected_ungenerated_operation_ids=[21],qualification_only=True,
        acknowledge_disposable_copy=True,receipt_path=str(tmp_path/"new.json"),
        action="prepare",expected_tool_diameter_percent=80.,new_tool_diameter_percent=10.)

@pytest.mark.parametrize("field",["expected_tool_diameter_percent","new_tool_diameter_percent"])
@pytest.mark.parametrize("value",[True,False,"10",None,float("nan"),float("inf"),-0.1,150.1])
def test_percentages_are_finite_strict_bounded_numbers(data,field,value):
    data[field]=value
    with pytest.raises(ValidationError):namespace()["SolidWorksCamMillRoughBoundarySetInput"](**data)

@pytest.mark.parametrize("expected,new",[(0,150),(150,0),(0.,1.),(1,1.5)])
def test_boundary_numeric_values_are_accepted(data,expected,new):
    data.update(expected_tool_diameter_percent=expected,new_tool_diameter_percent=new)
    out=namespace()["SolidWorksCamMillRoughBoundarySetInput"](**data)
    assert out.expected_tool_diameter_percent==expected and out.new_tool_diameter_percent==new

@pytest.mark.parametrize("value",[0,80.,150])
def test_equal_value_is_not_mutation_request(data,value):
    data.update(expected_tool_diameter_percent=value,new_tool_diameter_percent=value)
    with pytest.raises(ValidationError):namespace()["SolidWorksCamMillRoughBoundarySetInput"](**data)

@pytest.mark.parametrize("change",[
    {"process_id":True},{"process_id":123.},{"expected_feature_native_id":True},
    {"expected_operation_native_id":"20"},{"expected_mill_operation_type":1},
    {"expected_toolpath_record_counts":[True]},{"expected_toolpath_record_counts":[0]},
    {"expected_toolpath_record_counts":(12,)},{"expected_ungenerated_operation_ids":[20]},
    {"expected_ungenerated_operation_ids":[21,21]},{"expected_ungenerated_operation_ids":[True]},
    {"qualification_only":False},{"qualification_only":1},{"acknowledge_disposable_copy":False},
    {"message_policy":"suppress"},{"expected_document_title":"Qualification.SLDPRT"},
    {"expected_document_path":"relative.SLDPRT"},{"save":True},{"generate":True},
    {"delete_operation":True},{"action":"inspect"},{"expected_source_sha256":"bad"},
])
def test_existing_scope_cannot_be_relaxed(data,change):
    data.update(change)
    with pytest.raises(ValidationError):namespace()["SolidWorksCamMillRoughBoundarySetInput"](**data)

@pytest.mark.parametrize("missing",[
    ("expected_state_sha256",),("prepare_receipt_path",),("prepare_receipt_sha256",),
    ("expected_state_sha256","prepare_receipt_path"),
    ("expected_state_sha256","prepare_receipt_sha256"),
    ("prepare_receipt_path","prepare_receipt_sha256"),
    ("expected_state_sha256","prepare_receipt_path","prepare_receipt_sha256"),
])
def test_apply_requires_all_credentials(data,tmp_path,missing):
    p=tmp_path/"prepare.json";p.write_text("{}")
    data.update(action="apply",expected_state_sha256="b"*64,prepare_receipt_path=str(p),prepare_receipt_sha256="c"*64)
    for key in missing:data.pop(key)
    with pytest.raises(ValidationError):namespace()["SolidWorksCamMillRoughBoundarySetInput"](**data)

@pytest.mark.parametrize("field",["expected_state_sha256","prepare_receipt_path","prepare_receipt_sha256"])
def test_prepare_rejects_any_apply_credentials(data,tmp_path,field):
    p=tmp_path/"prepare.json";p.write_text("{}")
    data[field]=str(p) if field=="prepare_receipt_path" else "b"*64
    with pytest.raises(ValidationError):namespace()["SolidWorksCamMillRoughBoundarySetInput"](**data)

@pytest.mark.parametrize("kind",["relative","missing","suffix","directory"])
def test_prepare_receipt_must_be_existing_exact_json(data,tmp_path,kind):
    p=tmp_path/"prepare.json"
    if kind=="relative":p=Path("prepare.json")
    elif kind=="suffix":p=tmp_path/"prepare.txt";p.write_text("{}")
    elif kind=="directory":p.mkdir()
    data.update(action="apply",expected_state_sha256="b"*64,prepare_receipt_path=str(p),prepare_receipt_sha256="c"*64)
    with pytest.raises(ValidationError):namespace()["SolidWorksCamMillRoughBoundarySetInput"](**data)

def test_valid_apply_and_new_receipt(data,tmp_path):
    p=tmp_path/"prepare.json";p.write_text("{}")
    data.update(action="apply",expected_state_sha256="b"*64,prepare_receipt_path=str(p),prepare_receipt_sha256="c"*64)
    cls=namespace()["SolidWorksCamMillRoughBoundarySetInput"]
    out=cls(**data)
    assert out.action=="apply"
    Path(data["receipt_path"]).write_text("do not overwrite")
    with pytest.raises(ValidationError):cls(**data)

@pytest.mark.parametrize("pid",[None,True,123.,124])
def test_selected_pid_blocks_route_before_target(data,monkeypatch,pid):
    ns=namespace();calls=[]
    module=ModuleType("scripts.sw_cam_mill_rough_boundary_set")
    module.configure_mill_rough_boundary=lambda *a,**k:calls.append("backend")
    monkeypatch.setitem(sys.modules,module.__name__,module)
    ns.update(mcp=MCP(),_selected_process_id=pid,_cam_target=lambda p:calls.append("target"),_run_locked=lambda op,fmt:op())
    exec(source("server_route_fragment.py",["solidworks_cam_configure_mill_rough_boundary"]),ns)
    with pytest.raises(ValueError,match="explicitly connected"):
        ns["solidworks_cam_configure_mill_rough_boundary"](ns["SolidWorksCamMillRoughBoundarySetInput"](**data))
    assert calls==[]

def test_route_forwards_all_inventory_and_credentials_under_lock(data,monkeypatch,tmp_path):
    ns=namespace();calls=[];sw=object()
    module=ModuleType("scripts.sw_cam_mill_rough_boundary_set")
    def backend(session,clsid,**params):
        calls.append(("backend",session,clsid,params));return {"phase":"prepared"}
    module.configure_mill_rough_boundary=backend
    monkeypatch.setitem(sys.modules,module.__name__,module)
    addin=tmp_path/"CAM"/"cw.dll"
    def target(params):calls.append(("target",params.process_id));return sw,dict(clsid=data["addin_clsid"],addin_path=str(addin))
    def locked(op,fmt):calls.append(("locked",fmt));return op()
    ns.update(mcp=MCP(),_selected_process_id=123,_cam_target=target,_run_locked=locked)
    exec(source("server_route_fragment.py",["solidworks_cam_configure_mill_rough_boundary"]),ns)
    params=ns["SolidWorksCamMillRoughBoundarySetInput"](**data)
    assert ns["solidworks_cam_configure_mill_rough_boundary"](params)=={"phase":"prepared"}
    expected=params.model_dump(exclude={"addin_clsid","expected_document_title","response_format"})
    expected["typelib_path"]=str(addin.parent/"camworks.tlb")
    assert calls==[("locked",ResponseFormat.JSON),("target",123),("backend",sw,data["addin_clsid"],expected)]
