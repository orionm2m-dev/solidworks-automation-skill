"""Isolated schema and unchanged locked route for explicit MILL regeneration."""
import ast
from enum import Enum
from pathlib import Path
import sys
from types import ModuleType
from typing import Literal, Optional
import pytest
from pydantic import BaseModel,ConfigDict,Field,ValidationError,field_validator,model_validator

ROOT=Path(__file__).resolve().parents[1]
SUPPORT=["BaseInput","SolidWorksCamSelectedFeatureContextInput","ActiveDocumentInput","SolidWorksCamTargetInput",
         "SolidWorksCamMaterialCatalogueInput","SolidWorksCamMillFeaturePlanInput"]
CLASS="SolidWorksCamMillOperationToolpathInput"
ROUTE="solidworks_cam_qualify_mill_operation_toolpath"

def source(fragment,names):
    p=ROOT/fragment
    if p.is_file():return p.read_text(encoding="utf-8")
    text=(ROOT/"mcp-server/server.py").read_text(encoding="utf-8")
    return "\n\n".join(ast.unparse(n) for n in ast.parse(text).body if getattr(n,"name",None) in names)

class ResponseFormat(str,Enum):JSON="json"
class MCP:
    def tool(self,**kwargs):return lambda function:function

def namespace():
    ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
        model_validator=model_validator,Literal=Literal,Optional=Optional,Path=Path,
        ResponseFormat=ResponseFormat,absolute_document_path=lambda v:Path(v).is_absolute())
    exec(source("server_test_support_fragment.py",SUPPORT),ns)
    exec(source("server_schema_fragment.py",[CLASS]),ns)
    for name in SUPPORT+[CLASS]:ns[name].model_rebuild(_types_namespace=ns)
    return ns

@pytest.fixture
def data(tmp_path):
    p=tmp_path/"Qualification.SLDPRT";p.write_bytes(b"saved")
    return dict(addin_clsid="{11111111-2222-3333-4444-555555555555}",process_id=123,
        expected_document_path=str(p),expected_source_sha256="a"*64,
        expected_feature_native_id=10,expected_operation_native_id=20,
        expected_mill_operation_type=0,qualification_only=True,acknowledge_disposable_copy=True,
        action="prepare",generation_mode="regenerate",expected_toolpath_record_counts=[68],
        expected_tool_diameter_percent=0.,receipt_path=str(tmp_path/"new.json"))

def model(data):return namespace()[CLASS](**data)

@pytest.mark.parametrize("value",[True,False,"0",float("inf"),float("nan"),-1,151,None])
def test_percentage_strict_finite_bounded_required(data,value):
    data["expected_tool_diameter_percent"]=value
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("value",[[],[0],[True],[1.],(68,),None,[100001],[50001,50000]])
def test_counts_exact_native_list(data,value):
    data["expected_toolpath_record_counts"]=value
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("changes",[
    {"generation_mode":"all"},{"generation_mode":True},{"process_id":True},{"process_id":123.},
    {"expected_feature_native_id":"10"},{"expected_operation_native_id":True},
    {"expected_mill_operation_type":1},{"expected_mill_operation_type":False},
    {"qualification_only":False},{"qualification_only":1},{"acknowledge_disposable_copy":False},
    {"message_policy":"suppress"},{"expected_source_sha256":"bad"},{"expected_document_title":"name"},
    {"expected_document_path":"relative.SLDPRT"},{"save":True},{"delete":True},{"retry":True},
    {"receipt_path":None},{"receipt_path":"relative.json"},{"receipt_path":"C:/x.txt"},
])
def test_no_scope_widening(data,changes):
    data.update(changes)
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("field",["expected_state_sha256","prepare_receipt_path","prepare_receipt_sha256"])
def test_prepare_rejects_apply_credentials(data,field,tmp_path):
    p=tmp_path/"prior.json";p.write_text("{}")
    data[field]=str(p) if field=="prepare_receipt_path" else "b"*64
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("field",["expected_state_sha256","prepare_receipt_path","prepare_receipt_sha256"])
def test_apply_requires_complete_credentials(data,field,tmp_path):
    p=tmp_path/"prior.json";p.write_text("{}")
    data.update(action="apply",expected_state_sha256="b"*64,prepare_receipt_path=str(p),prepare_receipt_sha256="c"*64)
    data.pop(field)
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("kind",["relative","missing","suffix","directory"])
def test_apply_prior_receipt_existing_json(data,kind,tmp_path):
    p=tmp_path/"prior.json"
    if kind=="relative":p=Path("prior.json")
    elif kind=="suffix":p=tmp_path/"prior.txt";p.write_text("{}")
    elif kind=="directory":p.mkdir()
    data.update(action="apply",expected_state_sha256="b"*64,prepare_receipt_path=str(p),prepare_receipt_sha256="c"*64)
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("value",[0,0.,150,150.])
def test_valid_regenerate_prepare(data,value):
    data["expected_tool_diameter_percent"]=value
    assert model(data).generation_mode=="regenerate"

def test_inspect_no_receipt_or_credentials(data):
    data.update(action="inspect");data.pop("receipt_path")
    assert model(data).action=="inspect"
    data["receipt_path"]=str(Path(data["expected_document_path"]).with_suffix(".json"))
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("action",["inspect","prepare","apply"])
def test_initial_legacy_contract(data,action,tmp_path):
    for key in ["generation_mode","expected_toolpath_record_counts","expected_tool_diameter_percent","receipt_path"]:
        data.pop(key,None)
    data["action"]=action
    if action=="apply":data.update(expected_state_sha256="b"*64,receipt_path=str(tmp_path/"apply.json"))
    assert model(data).generation_mode=="initial"

@pytest.mark.parametrize("field,value",[
    ("expected_toolpath_record_counts",[68]),("expected_tool_diameter_percent",0.),
    ("prepare_receipt_path","C:/old.json"),("prepare_receipt_sha256","a"*64)])
def test_initial_rejects_regenerate_fields(data,field,value):
    for key in ["expected_toolpath_record_counts","expected_tool_diameter_percent","receipt_path"]:
        data.pop(key,None)
    data.update(generation_mode="initial");data[field]=value
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("action",["inspect","prepare"])
def test_initial_read_actions_still_reject_receipt(data,action):
    for key in ["expected_toolpath_record_counts","expected_tool_diameter_percent"]:data.pop(key)
    data.update(generation_mode="initial",action=action)
    with pytest.raises(ValidationError):model(data)

def test_existing_output_receipt_is_never_overwritten(data):
    Path(data["receipt_path"]).write_text("do not overwrite")
    with pytest.raises(ValidationError):model(data)

@pytest.mark.parametrize("action",["inspect","prepare","apply"])
def test_route_forwards_mode_and_all_pins_under_lock(data,action,monkeypatch,tmp_path):
    ns=namespace();calls=[];sw=object()
    data["action"]=action
    if action=="inspect":data.pop("receipt_path")
    if action=="apply":
        p=tmp_path/"prior.json";p.write_text("{}")
        data.update(expected_state_sha256="b"*64,prepare_receipt_path=str(p),prepare_receipt_sha256="c"*64)
    module=ModuleType("scripts.sw_cam_mill_toolpath")
    def backend(session,clsid,**kw):calls.append(("backend",session,clsid,kw));return {"status":"ok"}
    module.qualify_mill_operation_toolpath=backend
    monkeypatch.setitem(sys.modules,module.__name__,module)
    addin=tmp_path/"cw.dll"
    def target(p):calls.append(("target",p.process_id));return sw,dict(clsid=data["addin_clsid"],addin_path=str(addin))
    def locked(op,fmt):calls.append(("locked",fmt));return op()
    ns.update(mcp=MCP(),_selected_process_id=123,_cam_target=target,_run_locked=locked)
    exec(source("server_route_fragment.py",[ROUTE]),ns)
    p=ns[CLASS](**data)
    assert ns[ROUTE](p)=={"status":"ok"}
    expected=p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"})
    expected["typelib_path"]=str(addin.parent/"camworks.tlb")
    assert calls==[("locked",ResponseFormat.JSON),("target",123),("backend",sw,data["addin_clsid"],expected)]

def test_route_different_pid_does_not_touch_target(data):
    ns=namespace();calls=[]
    ns.update(mcp=MCP(),_selected_process_id=124,_cam_target=lambda p:calls.append("target"),
        _run_locked=lambda op,fmt:op())
    exec(source("server_route_fragment.py",[ROUTE]),ns)
    with pytest.raises(ValueError):ns[ROUTE](ns[CLASS](**data))
    assert calls==[]
