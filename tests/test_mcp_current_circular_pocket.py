"""Actual MCP schema/wrapper tests; all application access is mocked."""
import ast
import inspect
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID,context,server
from scripts import sw_cam_current_circular_pocket as core

SOURCE=Path(__file__).resolve().parents[1]/"server_nodes.py"
if SOURCE.is_file():
    tree=ast.parse(SOURCE.read_text(encoding="utf-8"))
    assert len(tree.body)==2
    server.mcp._tool_manager._tools.pop("solidworks_cam_add_circular_pocket_plan",None)
    exec(compile(tree,str(SOURCE),"exec"),server.__dict__)

@pytest.fixture
def fake(context,monkeypatch):
    monkeypatch.setattr(core,"validate",Mock(return_value={}))
    signature=inspect.signature(core.run_current_circular_pocket)
    result=dict(status="review_required",phase="finished",mutation_attempted=True,
        receipt_created=True,readback_verified=True,geometry_delta_verified=True,
        operation_delta_verified=True,save_readback_verified=True,model_saved=True,
        source_update_verified=True,runtime_unchanged=True,may_apply=True,
        before={"raw":"before"},after_insert={"raw":"after"},saved={"raw":"saved"},
        actions=[{"kind":"SaveActiveDocument","returned":True,"native_result":{"hresult":0}}])
    def run(*args,**kwargs):
        signature.bind(*args,**kwargs)
        return deepcopy(result)
    fn=Mock(side_effect=run)
    monkeypatch.setattr(core,"run_current_circular_pocket",fn)
    write=Mock();monkeypatch.setattr(core,"_write_receipt",write)
    runtime=Mock(return_value=None)
    monkeypatch.setattr(server,"_runtime_identity",SimpleNamespace(assert_current=runtime))
    return SimpleNamespace(fn=fn,result=result,write=write,runtime=runtime)

def params(context,**changes):
    values=dict(addin_clsid=CLSID,mode="current_saved",action="prepare",process_id=731,
        expected_process_create_time=100.25,expected_document_path=context.document,
        expected_source_sha256="a"*64,configuration_receipt_path="authority.json",
        configuration_receipt_sha256="b"*64,anchor_operation_native_id=10,
        owner_setup_native_id=40,operation_setup_native_id=50,
        insert_after_operation_native_id=12,expected_setup_axis=[0.,0.,1.],
        sketch_spec=dict(plane_axis="Z",plane_offset_mm=-12.6,sketch_name="PocketSketch",
            plane_name="PocketPlane",profile=dict(kind="circle",center_model_mm=[0.,0.,-12.6],radius_mm=8.5)),
        depth_native=7.4,reverse_direction=False,
        rough_definition=dict(default_operation_name="Cavity",default_operation_id=135),
        expected_default_tool=dict(tool_type_raw=1,cut_diameter_native=12.,protrusion_native=50.),
        candidate_tool_native_id=80,expected_candidate_consumer_ids=[10],
        receipt_path=str(Path(context.document).with_suffix(".json")),
        attempt_registry_path=str(Path(context.document).parent))
    values.update(changes)
    return server.SolidWorksCamCurrentCircularPocketInput(**values)

def test_actual_schema_required_addin_union_catalogue_and_wrapper_kwargs(context,fake):
    p=params(context)
    result=json.loads(server.solidworks_cam_add_circular_pocket_plan(p))
    assert result["readback_verified"] and fake.fn.call_count==1
    values=p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"})
    core.validate.assert_called_once_with(values,CLSID)
    args,kwargs=fake.fn.call_args
    assert args==(context.sw,CLSID,str(context.dll.parent/"camworks.tlb"))
    assert kwargs==dict(values,runtime_check=server._runtime_identity.assert_current)
    context.connect.assert_called_once_with(wait_seconds=1)
    registered=server.mcp._tool_manager._tools["solidworks_cam_add_circular_pocket_plan"]
    schema=json.dumps(registered.parameters)
    assert "SolidWorksCamAddCircularPocketInput" in schema
    assert "SolidWorksCamCurrentCircularPocketInput" in schema
    assert registered.annotations.readOnlyHint is False and registered.annotations.idempotentHint is False
    missing=p.model_dump();missing.pop("addin_clsid")
    with pytest.raises(ValueError):server.SolidWorksCamCurrentCircularPocketInput(**missing)

@pytest.mark.parametrize("changes",[
    {"process_id":True},{"expected_process_create_time":float("nan")},
    {"expected_document_path":"relative.sldprt"},{"unknown":True},
    {"expected_document_title":"other.sldprt"},{"expected_setup_axis":[0.,0.,float("nan")]},
    {"expected_setup_axis":[0.,1.,0.]},{"expected_setup_axis":[False,0.,1.]},
    {"depth_native":"7.4"},{"reverse_direction":True},{"save_after_verified":False},
    {"qualification_only":1},{"action":"apply"},{"prepare_receipt_path":"unexpected.json"},
    {"expected_candidate_consumer_ids":[True]},
])
def test_schema_rejects_bad_inputs_before_wrapper(context,fake,changes):
    with pytest.raises(ValueError):params(context,**changes)
    context.connect.assert_not_called();fake.fn.assert_not_called()

@pytest.mark.parametrize("pid",[None,True,732])
def test_selected_process_guard_precedes_authority_target_core(context,fake,monkeypatch,pid):
    monkeypatch.setattr(server,"_selected_process_id",pid)
    result=json.loads(server.solidworks_cam_add_circular_pocket_plan(params(context)))
    assert result["status"]=="error"
    core.validate.assert_not_called();context.connect.assert_not_called();fake.fn.assert_not_called()

def test_bad_pinned_authority_precedes_target(context,fake,monkeypatch):
    core.validate.side_effect=ValueError("invalid pinned authority")
    target=Mock();monkeypatch.setattr(server,"_cam_target",target)
    result=json.loads(server.solidworks_cam_add_circular_pocket_plan(params(context)))
    assert result["status"]=="error"
    target.assert_not_called();context.connect.assert_not_called();fake.fn.assert_not_called()

@pytest.mark.parametrize("mutated,owned",[(True,True),(False,False)])
def test_post_runtime_drift_preserves_actual_result_and_revokes_summary(context,fake,mutated,owned):
    fake.result.update(mutation_attempted=mutated,receipt_created=owned)
    fake.runtime.side_effect=[None,ValueError("runtime changed")]
    p=params(context)
    result=json.loads(server.solidworks_cam_add_circular_pocket_plan(p))
    assert result["status"]==("uncertain" if mutated else "error")
    for key in ("before","after_insert","saved","actions"):assert result[key]==fake.result[key]
    for key in ("readback_verified","geometry_delta_verified","operation_delta_verified",
        "save_readback_verified","model_saved","source_update_verified","runtime_unchanged","may_apply"):
        assert result[key] is False
    assert fake.fn.call_count==1
    if owned:fake.write.assert_called_once_with(Path(p.receipt_path),result)
    else:fake.write.assert_not_called()

def test_post_runtime_drift_durable_write_failure_is_explicit_without_replay(context,fake):
    fake.runtime.side_effect=[None,ValueError("runtime changed")]
    fake.write.side_effect=OSError("receipt unavailable")
    result=json.loads(server.solidworks_cam_add_circular_pocket_plan(params(context)))
    assert result["status"]=="uncertain" and "receipt_write_error" in result
    assert result["saved"]==fake.result["saved"] and not result["readback_verified"]
    assert fake.fn.call_count==1 and fake.write.call_count==1

def test_legacy_branch_ast_is_preserved():
    if not SOURCE.is_file():pytest.skip("Staging-only AST baseline; installed legacy regression runs separately")
    old=ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    old_fn=next(x for x in old.body if isinstance(x,ast.FunctionDef) and x.name=="solidworks_cam_add_circular_pocket_plan")
    new_fn=next(x for x in ast.parse(SOURCE.read_text(encoding="utf-8")).body if isinstance(x,ast.FunctionDef))
    old_op=next(x for x in old_fn.body if isinstance(x,ast.FunctionDef) and x.name=="op")
    new_op=next(x for x in new_fn.body if isinstance(x,ast.FunctionDef) and x.name=="op")
    expected=old_op.body
    if isinstance(expected[0],ast.If) and "SolidWorksCamCurrentCircularPocketInput" in ast.dump(expected[0]):expected=expected[1:]
    assert ast.dump(ast.Module(body=expected,type_ignores=[]),include_attributes=False)==ast.dump(ast.Module(body=new_op.body[1:],type_ignores=[]),include_attributes=False)
