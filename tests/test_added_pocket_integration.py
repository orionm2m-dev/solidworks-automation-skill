import ast,os,json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sw_cam_added_pocket_evidence as saved
from scripts import sw_cam_mill_appended_plan_evidence as appended
from scripts import sw_cam_mill_saved_plan_tools as common
from scripts.sw_cam_mill_selected_plan_context import resolve_expected_feature_count
from test_add_circular_pocket import engine,run,SOURCE,SKETCH,SAVED

def test_common_loader_continues_added_pocket_and_protected_tool(engine,monkeypatch):
    data=run(engine);assert data["model_saved"]
    previous=engine.original_anchor
    pin=dict(path="pocket",sha256="d"*64)
    original=common.load_saved_plan_tools_evidence
    def read_pin(path,sha):
        if path=="pocket":return deepcopy(data),deepcopy(pin)
        if path=="saved":return deepcopy(previous.data),deepcopy(previous.receipt_pin)
        if path=="sketch":return deepcopy(engine.sketch_result),dict(path="sketch",sha256="d"*64)
        if path=="profile":return {},deepcopy(previous.profile["pin"])
        raise AssertionError(path)
    for module in (saved,appended,common):monkeypatch.setattr(module,"read_pin",read_pin)
    monkeypatch.setattr(saved,"load_circle_route",lambda *a:engine.route)
    monkeypatch.setattr(saved,"check_circle_route",lambda *a:None)
    def load(path,sha,**args):
        if path=="saved":
            assert args["expected_source_sha256"]==SOURCE
            return previous
        return original(path,sha,**args)
    monkeypatch.setattr(common,"load_saved_plan_tools_evidence",load)
    binding=dict(process_id=17848,expected_document_path="C:/test/part.sldprt",expected_source_sha256=SAVED,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145)
    sketch_anchor=common.load_saved_plan_tools_evidence("sketch","d"*64,
        **{**binding,"expected_source_sha256":SKETCH})
    assert sketch_anchor.data["scope"]=="MILL_ADDED_CIRCLE_SKETCH_V1"
    assert resolve_expected_feature_count(sketch_anchor)==18
    assert sketch_anchor.verify(engine.sketch_result["saved"])
    obj=common.load_saved_plan_tools_evidence("pocket","d"*64,**binding)
    assert isinstance(obj,saved.AddedPocketEvidence) and obj.verify(data["saved"])
    assert resolve_expected_feature_count(obj)==19
    assert obj.operation_ids==[143,144] and obj.tool_id==145
    assert obj.summary()["added_operation_native_ids"]==[220,221]
    assert [r["native_id"] for r in obj.state["operations"]]==[143,144,195,196,220,221]
    with pytest.raises(ValueError):
        common.load_saved_plan_tools_evidence("pocket","d"*64,
            **{**binding,"expected_operation_native_ids":[220,221]})
    data["save_readback_verified"]=False
    with pytest.raises(ValueError):common.load_saved_plan_tools_evidence("pocket","d"*64,**binding)

def test_capture_count_preserves_old_and_new_anchor_bounds():
    assert resolve_expected_feature_count(SimpleNamespace(context=dict(features=[{}]*18)))==18
    assert resolve_expected_feature_count(SimpleNamespace(state=dict(features=[{}]*19),data=dict(scope="MILL_ADDED_CIRCULAR_POCKET_PLAN_V1")))==19
    assert resolve_expected_feature_count(SimpleNamespace(state=dict(features=[{}]*18)),19)==19
    for bad in (True,0,17,20,65,19.0):
        with pytest.raises(ValueError):resolve_expected_feature_count(SimpleNamespace(),bad)
    with pytest.raises(ValueError):resolve_expected_feature_count(SimpleNamespace(state=dict(features=[])))
    with pytest.raises(ValueError):resolve_expected_feature_count(SimpleNamespace(state=dict(features=[{}]*19)))

def test_old_appended_scope_remains_selected(monkeypatch):
    called=[]
    monkeypatch.setattr(common,"read_pin",lambda *a:({"scope":"MILL_APPEND_OPERATIONS_V1"},{}))
    monkeypatch.setattr(appended,"load_appended_plan_evidence",lambda *a,**k:called.append(k) or "old")
    result=common.load_saved_plan_tools_evidence("old",SOURCE,process_id=1,
        expected_document_path="C:/test/part.sldprt",expected_source_sha256=SOURCE,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145)
    assert result=="old" and called

def schema_class():
    from enum import Enum
    from typing import Optional,Literal,Annotated
    from pydantic import BaseModel,Field,ConfigDict,model_validator,field_validator
    from scripts.sw_operation_guard import absolute_document_path
    root=Path(__file__).resolve().parents[1]
    runtime=Path(os.environ.get("SW_SKILL_RUNTIME_ROOT",str(root)))
    tree=ast.parse((runtime/"mcp-server/server.py").read_text(encoding="utf-8-sig"))
    names=("ResponseFormat","BaseInput","ActiveDocumentInput","SolidWorksCamTargetInput","SolidWorksCamSavedMillPlanToolsInput")
    body=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in names]
    snippet=root/"snippets/add_circular_pocket_server.py"
    own=ast.parse(snippet.read_text(encoding="utf-8")) if snippet.is_file() else tree
    body.extend(n for n in own.body if isinstance(n,ast.ClassDef) and n.name=="SolidWorksCamAddCircularPocketInput")
    namespace=dict(Enum=Enum,Optional=Optional,Literal=Literal,Annotated=Annotated,Path=Path,
        BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,model_validator=model_validator,
        field_validator=field_validator,absolute_document_path=absolute_document_path)
    exec(compile(ast.Module(body=body,type_ignores=[]),"pocket_schema","exec"),namespace)
    return namespace["SolidWorksCamAddCircularPocketInput"]

def test_schema_forbids_unbound_parameters():
    cls=schema_class()
    assert cls.model_config["extra"]=="forbid"
    assert set(("sketch_spec","depth_native","reference_feature_native_id","route_receipt_sha256")).issubset(cls.model_fields)
