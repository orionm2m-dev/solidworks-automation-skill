import ast,json,os
from copy import deepcopy
from pathlib import Path
import pytest
from scripts import sw_cam_replace_compound_plan as m
from scripts import sw_cam_replaced_plan_evidence as saved
from scripts import sw_cam_mill_appended_plan_evidence as appended
from scripts import sw_cam_mill_saved_plan_tools as common
from test_replace_compound_plan import engine,SOURCE,SAVED

def test_saved_common_loader_consumes_new_replacement_receipt(engine,monkeypatch):
    data=engine.run()
    pin={"path":"replacement","sha256":"c"*64}
    previous=engine.anchor
    original=common.load_saved_plan_tools_evidence
    def read_pin(path,sha):
        if path=="replacement":return deepcopy(data),deepcopy(pin)
        if path=="saved":return deepcopy(previous.data),deepcopy(previous.receipt_pin)
        if path=="profile":return {},deepcopy(previous.profile["pin"])
        raise AssertionError(path)
    monkeypatch.setattr(saved,"read_pin",read_pin)
    monkeypatch.setattr(appended,"read_pin",read_pin)
    monkeypatch.setattr(common,"read_pin",read_pin)
    monkeypatch.setattr(saved,"load_primary_route",lambda *a:engine.route)
    monkeypatch.setattr(saved,"check_primary_route",lambda *a:None)
    def load(path,sha,**args):
        if path=="saved":
            assert args["expected_source_sha256"]==SOURCE
            return previous
        return original(path,sha,**args)
    monkeypatch.setattr(common,"load_saved_plan_tools_evidence",load)
    binding=dict(process_id=17848,expected_document_path="C:/test/part.sldprt",
        expected_source_sha256=SAVED,expected_feature_native_id=79,
        expected_operation_native_ids=[143,144],expected_operation_setup_native_id=93,
        expected_tool_native_id=145)
    evidence=common.load_saved_plan_tools_evidence("replacement","c"*64,**binding)
    assert isinstance(evidence,saved.ReplacedPlanEvidence)
    assert evidence.verify(deepcopy(data["saved"]))
    assert evidence.operation_ids==[143,144] and evidence.tool_id==145
    assert evidence.summary()["replacement_operation_native_ids"]==[210,211]
    assert evidence.summary()["target_strategy"]["attribute_name"]=="Rough-Finish"
    assert evidence.data==data
    with pytest.raises(ValueError):
        common.load_saved_plan_tools_evidence("replacement","c"*64,
            **{**binding,"expected_operation_native_ids":[210,211]})
    with pytest.raises(ValueError):
        common.load_saved_plan_tools_evidence("replacement","c"*64,**binding,
            session_rebind_receipt_path="not-pinned",session_rebind_receipt_sha256=SOURCE)
    data["save_readback_verified"]=False
    with pytest.raises(ValueError):
        common.load_saved_plan_tools_evidence("replacement","c"*64,**binding)

@pytest.mark.parametrize("partial",[False,True])
def test_target_profiles_reuse_existing_capture_only_after_supported_milling(engine,monkeypatch,partial):
    calls=[]
    def tool_hook(state,native,read,typed,diag,*,feature_native_id,boundary):
        calls.append((engine.active_phase,feature_native_id))
        if feature_native_id==79:
            diag["selected_tool_details"]=deepcopy(engine.details["selected_tool_details"])
        else:
            rows=[r for r in state["operations"] if r["linked_feature_ids"]==[64]]
            diag["selected_tool_details"]=dict(metadata_read_complete=not partial,profile_complete=not partial,
                generic_operation_context_unchanged=True,canonical_state_changed=False,
                items=[dict(operation_native_id=r["native_id"],mill_operation_type=r["mill_operation_type"],
                    tool_metadata_complete=not partial,status="partial" if partial else "observed",
                    full_tool=dict(tool_native_id=r["assigned_tool"]["native_id"],
                                   geometry_read_complete=not partial,profile_complete=not partial)) for r in rows])
    def compound_hook(state,native,read,typed,diag,**kwargs):
        if kwargs["observation"]=="strategy":
            value=deepcopy(engine.details["strategy"]["compound_strategy"])
            value.update(attribute_id=engine.strategy_id,attribute_name=engine.strategy_name,active_attribute_name=engine.strategy_name)
        else:value=deepcopy(engine.details["three_step_profile"]["compound_strategy"])
        diag["compound_strategy"]=value
    def capture(*a,**k):
        phase=k["diagnostic"]["phase"];engine.active_phase=phase
        diag=k["diagnostic"].setdefault("operation_details",{})
        k["operation_details_reader"](engine.current,{},None,None,diag,boundary=lambda:None)
        return deepcopy(engine.current),{"app":"app"}
    monkeypatch.setattr(m,"read_selected_operation_tool_details",tool_hook)
    monkeypatch.setattr(m,"read_compound_strategy",compound_hook)
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    result=engine.run()
    assert result["model_saved"]
    assert [phase for phase,fid in calls if fid==64]==["after","saved"]
    assert result["target_tool_metadata_readback_verified"] is (not partial)
    assert result["target_tool_physical_geometry_qualified"] is False
    profile=m.validate_replacement_baseline(engine.anchor,**{k:result["request"][k] for k in m.TARGET_KEYS})
    assert saved.validate_saved_replacement(result,engine.anchor,profile,engine.route,
        process_id=17848,document_path="C:/test/part.sldprt",source_sha=SAVED)

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
    snippet=root/"mcp-server/replace_compound_plan_snippet.py"
    own=ast.parse(snippet.read_text(encoding="utf-8")) if snippet.is_file() else tree
    body.extend(n for n in own.body if isinstance(n,ast.ClassDef) and n.name=="SolidWorksCamReplaceCompoundPlanInput")
    namespace=dict(Enum=Enum,Optional=Optional,Literal=Literal,Annotated=Annotated,Path=Path,
        BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,model_validator=model_validator,
        field_validator=field_validator,absolute_document_path=absolute_document_path)
    exec(compile(ast.Module(body=body,type_ignores=[]),"replacement_schema","exec"),namespace)
    return namespace["SolidWorksCamReplaceCompoundPlanInput"]

def test_schema_exposes_only_exact_strategy_and_mutating_nonreplay_tool():
    root=Path(__file__).resolve().parents[1]
    path=root/"mcp-server/replace_compound_plan_snippet.py"
    if not path.is_file():path=root/"mcp-server/server.py"
    tree=ast.parse(path.read_text(encoding="utf-8-sig"))
    f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="solidworks_cam_replace_compound_strategy_plan")
    deco=next(n for n in f.decorator_list if isinstance(n,ast.Call))
    flags=next(ast.literal_eval(k.value) for k in deco.keywords if k.arg=="annotations")
    assert flags["readOnlyHint"] is False and flags["idempotentHint"] is False
    cls=schema_class()
    assert cls.model_config["extra"]=="forbid"
    assert cls.model_fields["requested_strategy_name"].default=="Rough-Finish"

def test_source_has_one_resolver_setter_and_regenerate_and_no_delete():
    root=Path(__file__).resolve().parents[1]
    source=(root/"scripts/sw_cam_replace_compound_plan.py").read_text(encoding="utf-8")
    assert source.count('"GetTdbIdForAttribute"')==1
    assert source.count('setattr(compound,"Attribute",resolved)')==1
    assert source.count('_member(target,"GenerateOpPlan",2)')==1
    for method in ("DeleteOperation","DeleteFeature","GenerateAll","GenerateToolpath"):
        assert method not in source
