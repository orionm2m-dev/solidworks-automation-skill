from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from enum import Enum
import ast
import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator, ValidationError
import scripts


@pytest.fixture
def wrapper(monkeypatch):
    calls = []
    class ResponseFormat(str, Enum):
        JSON = "json"
    class Target(BaseModel):
        addin_clsid: str | None = None
        expected_document_title: str | None = None
        response_format: ResponseFormat = ResponseFormat.JSON
    class MCP:
        def tool(self, **metadata):
            calls.append(("registration", metadata))
            return lambda function: function
    def runtime():
        calls.append(("runtime", None))
    def target(params):
        calls.append(("target", params.process_id))
        return "owned_sw", {"clsid": "test_clsid", "addin_path": "C:/vendor/cam.dll"}
    def validate(values):
        calls.append(("validate", values.copy()))
    def dispatch(sw, clsid, tlb, *, runtime_check, **values):
        calls.append(("dispatch", (sw, clsid, tlb, values.copy())))
        return {"status": "review_required", "mutation_attempted": True,
                "model_saved": True, "save_stage": {"native_return_value": 0}}
    def failure(result, error):
        calls.append(("runtime_failure", str(error)))
        return {**result, "status": "uncertain", "runtime_unchanged": False}
    core = SimpleNamespace(validate=validate, dispatch=dispatch, finalize_runtime_failure=failure)
    monkeypatch.setattr(scripts, "sw_cam_circular_reconfigure", core, raising=False)
    env = dict(SolidWorksCamTargetInput=Target, ConfigDict=ConfigDict, Field=Field,
               Literal=Literal, model_validator=model_validator, mcp=MCP(), Path=Path,
               _runtime_identity=SimpleNamespace(assert_current=runtime), _selected_process_id=123,
               _cam_target=target, _run_locked=lambda op, fmt: op())
    source = Path(scripts.__file__).resolve().parents[1] / "mcp-server" / "server.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    wanted = {"SolidWorksCamCircularReconfigureInput", "solidworks_cam_reconfigure_generated_circular"}
    tree = ast.Module(body=[node for node in tree.body if getattr(node,"name",None) in wanted], type_ignores=[])
    assert len(tree.body) == 2
    exec(compile(tree, str(source), "exec"), env)
    values = dict(process_id=123, expected_process_create_time=1234.5,
        expected_document_path="C:/job/current.sldprt", expected_source_sha256="a"*64,
        nc_receipt_path="C:/job/read.json", nc_receipt_sha256="b"*64,
        recipe_path="C:/job/recipe.json", recipe_sha256="c"*64,
        receipt_path="C:/job/apply.json", saved_cl_path="C:/job/new.cl")
    return env, calls, core, values


def test_dispatch_validates_before_application_access(wrapper):
    env,calls,core,values=wrapper
    result=env["solidworks_cam_reconfigure_generated_circular"](env["SolidWorksCamCircularReconfigureInput"](**values))
    names=[c[0] for c in calls]
    assert names == ["registration", "runtime", "validate", "target", "dispatch", "runtime"]
    passed=next(c[1][3] for c in calls if c[0]=="dispatch")
    assert not {"addin_clsid","expected_document_title","response_format"}.intersection(passed)
    assert passed["qualification_only"] is True and passed["message_policy"] == "vendor_default"
    assert result["model_saved"] is True


@pytest.mark.parametrize("owner", [None, True, 124])
def test_wrong_owner_never_touches_application(wrapper, owner):
    env,calls,core,values=wrapper;env["_selected_process_id"]=owner
    with pytest.raises(ValueError):
        env["solidworks_cam_reconfigure_generated_circular"](env["SolidWorksCamCircularReconfigureInput"](**values))
    assert not any(c[0] in {"validate","target","dispatch"} for c in calls)


def test_rejected_pins_stop_before_application_access(wrapper):
    env,calls,core,values=wrapper
    core.validate=lambda values: (_ for _ in ()).throw(ValueError("changed recipe"))
    with pytest.raises(ValueError, match="changed recipe"):
        env["solidworks_cam_reconfigure_generated_circular"](env["SolidWorksCamCircularReconfigureInput"](**values))
    assert not any(c[0] in {"target","dispatch"} for c in calls)


def test_post_runtime_failure_is_durable_without_replay(wrapper):
    env,calls,core,values=wrapper;count=0
    def runtime():
        nonlocal count
        count+=1
        if count==2: raise RuntimeError("runtime changed")
    env["_runtime_identity"].assert_current=runtime
    result=env["solidworks_cam_reconfigure_generated_circular"](env["SolidWorksCamCircularReconfigureInput"](**values))
    assert result["status"]=="uncertain" and result["runtime_unchanged"] is False
    assert result["model_saved"] is True and result["save_stage"]["native_return_value"]==0
    assert sum(c[0]=="dispatch" for c in calls)==1
    assert sum(c[0]=="runtime_failure" for c in calls)==1


@pytest.mark.parametrize("change", [
    {"process_id":True}, {"expected_process_create_time":float("inf")},
    {"expected_source_sha256":"bad"}, {"recipe_sha256":"A"*64},
    {"qualification_only":False}, {"qualification_only":1},
    {"expected_document_title":"other"}, {"message_policy":"yes"},
    {"extra":1}, {"receipt_path":""},
])
def test_invalid_targets_rejected_before_dispatch(wrapper, change):
    env,calls,core,values=wrapper;values.update(change)
    with pytest.raises(ValidationError):env["SolidWorksCamCircularReconfigureInput"](**values)
    assert not any(c[0] in {"target","dispatch"} for c in calls)


def test_mutation_registration_does_not_claim_idempotence(wrapper):
    env,calls,core,values=wrapper
    data=calls[0][1]
    assert data["name"]=="solidworks_cam_reconfigure_generated_circular"
    assert data["annotations"]["readOnlyHint"] is False
    assert data["annotations"]["idempotentHint"] is False
