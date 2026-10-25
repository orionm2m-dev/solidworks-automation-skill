"""直线车削特征 MCP 严格输入、路由和目标门禁；不连接 CAD。"""
import json
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context, CLSID, server
from scripts import sw_cam_turn_feature as cam

TOOL = "solidworks_cam_qualify_turn_feature"


@pytest.fixture
def core(context, monkeypatch):
    native = Mock(return_value={"status":"review_required", "may_continue":False})
    monkeypatch.setattr(cam,"qualify_turn_feature",native)
    return native


def params(context, action="prepare", **changes):
    values = dict(addin_clsid=CLSID, expected_document_path=context.document, setup_index=0,
        operation_index=7, expected_operation_type=2, linked_feature_index=0, segment_index=18,
        feature_setup_index=0, candidate_feature_type=1, native_to_model_scale=.001,
        sketch_name="CAM_Line_Probe", action=action, qualification_only=True,
        acknowledge_unverified_type_mapping=True, message_policy="vendor_default")
    if action not in {"inspect", "prepare"}:
        values.update(expected_state_sha256="a"*64, receipt_path=str(context.dll.parent/"feature.json"))
    if action == "save_candidate":values["expected_new_feature_native_id"] = 99
    return server.SolidWorksCamTurnFeatureInput(**(values|changes))


@pytest.mark.parametrize("action",["inspect","prepare","apply","save_candidate"])
def test_exact_typed_route_and_explicit_action(context,core,action):
    p=params(context,action)
    assert json.loads(server.solidworks_cam_qualify_turn_feature(p)) == core.return_value
    expected=p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"})
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),**expected)
    assert context.runners == [{"format":server.ResponseFormat.JSON,"automation":True}]
    annotation=server.mcp._tool_manager._tools[TOOL].annotations
    assert annotation.readOnlyHint is False and annotation.idempotentHint is False
    from scripts.validate_mcp import REQUIRED_TOOLS
    assert TOOL in REQUIRED_TOOLS


@pytest.mark.parametrize("field",["segment_index","feature_setup_index","candidate_feature_type","linked_feature_index"])
@pytest.mark.parametrize("value",[True,False,"1",1.0,None,-1])
def test_strict_native_references(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field",["qualification_only","acknowledge_unverified_type_mapping"])
@pytest.mark.parametrize("value",[False,1,0,"true",None])
def test_explicit_experiment_acknowledgements(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called()


@pytest.mark.parametrize("value",[True,False,0,-.001,2,".001",float("nan"),float("inf"),None])
def test_scale_must_be_explicit_finite_positive_number(context,core,value):
    with pytest.raises(ValueError):params(context,native_to_model_scale=value)
    core.assert_not_called()


@pytest.mark.parametrize("value",["","bad/name","name@part","a"*81,1,None])
def test_exact_simple_sketch_name(context,core,value):
    with pytest.raises(ValueError):params(context,sketch_name=value)
    core.assert_not_called()


@pytest.mark.parametrize("action",["apply","save_candidate"])
@pytest.mark.parametrize("field",["expected_state_sha256","receipt_path"])
def test_mutation_requires_hash_and_receipt(context,core,action,field):
    with pytest.raises(ValueError):params(context,action,**{field:None})
    core.assert_not_called()


@pytest.mark.parametrize("field,value",[("receipt_path","unused.json"),("expected_state_sha256","a"*64),("expected_new_feature_native_id",99)])
@pytest.mark.parametrize("action",["inspect","prepare"])
def test_readonly_actions_have_no_mutation_inputs(context,core,field,value,action):
    with pytest.raises(ValueError):params(context,action,**{field:value})
    core.assert_not_called()


def test_save_requires_created_identity_and_apply_rejects_it(context,core):
    with pytest.raises(ValueError):params(context,"save_candidate",expected_new_feature_native_id=None)
    with pytest.raises(ValueError):params(context,"apply",expected_new_feature_native_id=99)
    core.assert_not_called()


def test_existing_receipt_is_never_overwritten(context,core):
    path=context.dll.parent/"old.json";path.write_text("unchanged",encoding="utf-8")
    with pytest.raises(ValueError):params(context,"apply",receipt_path=str(path))
    assert path.read_text()=="unchanged"
    core.assert_not_called()


@pytest.mark.parametrize("failure",["unbound","wrong_document","wrong_version","unknown_registration"])
def test_target_guard_precedes_all_core_calls(context,core,monkeypatch,failure):
    changes={}
    if failure=="unbound":monkeypatch.setattr(server,"_selected_process_id",None)
    elif failure=="wrong_document":context.model.GetPathName=str(context.dll.parent/"other.sldprt")
    elif failure=="wrong_version":context.sw.RevisionNumber="33.1.0"
    else:changes["addin_clsid"]="{00000000-0000-0000-0000-000000000002}"
    assert json.loads(server.solidworks_cam_qualify_turn_feature(params(context,**changes)))["status"]=="error"
    core.assert_not_called()


@pytest.mark.parametrize("field",["pitch","thread_depth","generate_toolpath","save","typelib_path","synthetic_endpoints"])
def test_no_extra_mutators_or_raw_geometry_override(context,core,field):
    with pytest.raises(ValueError):params(context,**{field:1})
    core.assert_not_called()
