import ast, json
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from scripts import sw_cam_mill_append_delta as delta
from scripts import sw_cam_mill_appended_plan_evidence as saved
from scripts import sw_cam_mill_saved_plan_tools as loader
from test_sw_cam_mill_append_operations import engine, state, added, SOURCE, SAVED

def test_synthetic_mass_readback_rounding_only():
    f=json.loads((Path(__file__).parent/"mass_rounding_fixture.json").read_text(encoding='utf-8'))
    before=state();after=added(before)
    before["sw_reference"]["solids"]=deepcopy(f["before"])
    after["sw_reference"]["solids"]=deepcopy(f["saved"])
    assert before["sw_reference"]["solids"] != after["sw_reference"]["solids"]
    assert len(delta.verify_added_plan(before,after,64,93))==1
    after["sw_reference"]["solids"][0]["mass_raw"][3] *= 1.001
    with pytest.raises(ValueError):delta.verify_added_plan(before,after,64,93)

def test_body_extra_properties_stay_strict():
    before=state();after=added(before)
    after["sw_reference"]["solids"][0]["unexpected_change"]=True
    with pytest.raises(ValueError):delta.verify_added_plan(before,after,64,93)

def test_complete_saved_loader_and_dispatch(engine,monkeypatch):
    data=engine.run()
    pin={"path":"appended","sha256":"c"*64}
    previous=engine.anchor
    original_loader=loader.load_saved_plan_tools_evidence
    def read_pin(path,sha):
        if path=="appended":return deepcopy(data),deepcopy(pin)
        if path=="saved":return deepcopy(previous.data),{"path":"saved","sha256":SOURCE}
        if path=="profile":return {},engine.profile["pin"]
        raise AssertionError(path)
    monkeypatch.setattr(saved,"read_pin",read_pin)
    monkeypatch.setattr(loader,"read_pin",read_pin)
    monkeypatch.setattr(saved,"load_target_profile",lambda *a,**k:deepcopy(engine.profile))
    def recursive(path,sha,**kwargs):
        if path=="saved":
            assert kwargs["expected_source_sha256"]==SOURCE
            return previous
        return original_loader(path,sha,**kwargs)
    monkeypatch.setattr(loader,"load_saved_plan_tools_evidence",recursive)
    args=dict(process_id=17848,expected_document_path="C:/test/part.sldprt",
        expected_source_sha256=SAVED,expected_feature_native_id=79,
        expected_operation_native_ids=[143,144],expected_operation_setup_native_id=93,
        expected_tool_native_id=145)
    evidence=loader.load_saved_plan_tools_evidence("appended","c"*64,**args)
    assert isinstance(evidence,saved.AppendedPlanEvidence)
    assert evidence.state==data["saved"] and evidence.operation_ids==[143,144]
    assert evidence.summary()["added_operation_native_ids"]==[200]
    assert evidence.baseline_tool_details==data["saved_details"]["selected_tool_details"]
    assert evidence.verify(deepcopy(data["saved"]))
    assert evidence.data==data
    with pytest.raises(ValueError):
        loader.load_saved_plan_tools_evidence("appended","c"*64,
            **{**args,"expected_operation_native_ids":[200]})
    with pytest.raises(ValueError):
        loader.load_saved_plan_tools_evidence("appended","c"*64,**args,
            session_rebind_receipt_path="unrequested",session_rebind_receipt_sha256=SOURCE)
    data["model_saved"]=False
    with pytest.raises(ValueError):
        loader.load_saved_plan_tools_evidence("appended","c"*64,**args)

def schema_class():
    import os
    from enum import Enum
    from typing import Optional, Literal
    from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
    from scripts.sw_operation_guard import absolute_document_path
    runtime=Path(os.environ.get("SW_SKILL_RUNTIME_ROOT", str(Path(__file__).resolve().parents[1])))
    tree=ast.parse((runtime/"mcp-server/server.py").read_text(encoding="utf-8-sig"))
    names=("ResponseFormat","BaseInput","ActiveDocumentInput",
           "SolidWorksCamTargetInput","SolidWorksCamSavedMillPlanToolsInput")
    body=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in names]
    stage=Path(__file__).resolve().parents[1]
    snippet_path=stage/"mcp-server/append_operations_snippet.py"
    snippet=ast.parse(snippet_path.read_text(encoding="utf-8")) if snippet_path.is_file() else tree
    body.extend(n for n in snippet.body if isinstance(n,ast.ClassDef)
                and n.name=="SolidWorksCamAppendMillOperationsInput")
    namespace=dict(Enum=Enum,Optional=Optional,Literal=Literal,Path=Path,
        BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,model_validator=model_validator,
        field_validator=field_validator,absolute_document_path=absolute_document_path)
    exec(compile(ast.Module(body=body,type_ignores=[]),"staged_schema","exec"),namespace)
    return namespace["SolidWorksCamAppendMillOperationsInput"]

def test_schema_has_nonidempotent_mutation_and_no_extra_parameters():
    root=Path(__file__).resolve().parents[1]
    path=root/"mcp-server/append_operations_snippet.py"
    if not path.is_file():path=root/"mcp-server/server.py"
    tree=ast.parse(path.read_text(encoding="utf-8-sig"))
    f=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
           and n.name=="solidworks_cam_append_mill_operations")
    decorator=next(d for d in f.decorator_list if isinstance(d,ast.Call))
    flags=next(ast.literal_eval(k.value) for k in decorator.keywords if k.arg=="annotations")
    assert flags["readOnlyHint"] is False and flags["idempotentHint"] is False
    cls=schema_class()
    assert cls.model_config["extra"]=="forbid"
    assert "save_after_verified" in cls.model_fields
    assert cls.model_fields["expected_strategy_id"].is_required()
