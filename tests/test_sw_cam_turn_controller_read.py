"""Read-only TURN controller contract tests; no CAD connection."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sw_cam_turn_controller_read as reader


@pytest.fixture
def graph(monkeypatch):
    document = dict(path="C:/qualification/collar.sldprt", title="collar.sldprt", type=1, needs_save=False)
    inventory = dict(machine_type=3, operation_count=2, operations=[dict(toolpath_generated=True, toolpath_record_counts=[19])])
    state = dict(document=document, inventory=inventory, sha="a"*64)
    sw = SimpleNamespace(GetProcessID=Mock(return_value=120))
    machine = object()
    target = SimpleNamespace(GetController=Mock(return_value="Turn controller"))
    def typed(raw, name, path):
        assert raw is machine and name == "ICWTurnMachine" and path == "verified.tlb"
        return target
    monkeypatch.setattr(reader, "_typed", typed)
    monkeypatch.setattr(reader, "document_snapshot", lambda sw: deepcopy(state["document"]))
    monkeypatch.setattr(reader, "_context", lambda *a: (deepcopy(state["document"]),None,None,machine,None))
    monkeypatch.setattr(reader, "_inventory", lambda *a: deepcopy(state["inventory"]))
    monkeypatch.setattr(reader, "_file_hash", lambda path: state["sha"])
    def member(obj, name, *args):
        assert name in {"GetProcessID", "GetController"}, "No other native method is allowed"
        return getattr(obj, name)(*args)
    monkeypatch.setattr(reader, "_member", member)
    args=dict(process_id=120,expected_document_path=document["path"],expected_source_sha256="a"*64)
    return state,sw,target,args


def run(graph, **changes):
    state,sw,target,args=graph
    return reader.inspect_turn_controller(sw,"verified-clsid","verified.tlb",**{**args,**changes})


def test_exact_name_is_read_once_without_granting_preset_authority(graph):
    report=run(graph)
    assert report["status"]=="ok" and report["controller_name_raw"]=="Turn controller"
    assert report["getter_call_count"]==1 and report["inventory_unchanged"] and report["active_document_unchanged"]
    assert not any(report[k] for k in ("may_continue","mutation_attempted","model_saved","generation_attempted","controller_parameters_read","preset_values_verified","production_process_qualified"))
    graph[2].GetController.assert_called_once_with()


@pytest.mark.parametrize("name",["", "   "])
def test_empty_name_requires_review_without_another_getter(graph,name):
    graph[2].GetController.return_value=name
    report=run(graph)
    assert report["reason"]=="TURN_CONTROLLER_NAME_EMPTY"
    assert report["controller_name_raw"]==name and report["controller_name_available"] is False
    graph[2].GetController.assert_called_once_with()


@pytest.mark.parametrize("name",[None,False,4,("name",True),"x"*1025,"name\n"])
def test_invalid_bstr_is_not_a_controller(graph,name):
    graph[2].GetController.return_value=name
    report=run(graph)
    assert report["status"]=="error" and report["failed_stage"]=="GetController"
    assert not report.get("controller_name_available",False)


@pytest.mark.parametrize("change",["pid","sha","dirty","machine","path"])
def test_changed_or_wrong_target_rejected_before_getter(graph,change):
    state,sw,target,args=graph
    if change=="pid":sw.GetProcessID.return_value=121
    if change=="sha":state["sha"]="b"*64
    if change=="dirty":state["document"]["needs_save"]=True
    if change=="machine":state["inventory"]["machine_type"]=1
    if change=="path":args["expected_document_path"]="C:/qualification/other.sldprt"
    assert run(graph)["status"]=="error"
    target.GetController.assert_not_called()


@pytest.mark.parametrize("change",["inventory","document","sha","pid"])
def test_changes_during_getter_invalidate_readback(graph,change):
    state,sw,target,args=graph
    def getter():
        if change=="inventory":state["inventory"]["operation_count"]+=1
        if change=="document":state["document"]["title"]="changed.sldprt"
        if change=="sha":state["sha"]="b"*64
        if change=="pid":sw.GetProcessID.return_value=121
        return "Turn controller"
    target.GetController.side_effect=getter
    assert run(graph)["status"]=="error"
    target.GetController.assert_called_once_with()


def test_native_exception_does_not_retry(graph):
    graph[2].GetController.side_effect=RuntimeError("read failed")
    result=run(graph)
    assert result["status"]=="error" and result["getter_call_count"]==1
    graph[2].GetController.assert_called_once_with()


@pytest.mark.parametrize("value",[True,0,-1,"120"])
def test_bad_pid_rejected(graph,value):
    assert run(graph,process_id=value)["status"]=="error"
    graph[2].GetController.assert_not_called()


@pytest.mark.parametrize("success",[True, False])
def test_parameters_use_only_observed_non_apt_name(graph,monkeypatch,success):
    graph[2].GetController.return_value="Example.ctl"
    params=SimpleNamespace(GetControllerParameters=Mock(return_value=(["x preset"],[0.1],success)))
    prior=reader._typed
    monkeypatch.setattr(reader,"_typed",lambda raw,name,path: params if name=="ICWMachine5" else prior(raw,name,path))
    prior_member=reader._member
    monkeypatch.setattr(reader,"_member",lambda obj,name,*args: params.GetControllerParameters(*args) if name=="GetControllerParameters" else prior_member(obj,name,*args))
    result=run(graph,include_parameters=True,expected_controller_name="Example.ctl")
    params.GetControllerParameters.assert_called_once_with(False,"Example.ctl")
    assert result["controller_parameters_read"] is success
    assert result["status"] == ("ok" if success else "review_required")
    assert not result["preset_values_verified"]


def test_wrong_observed_name_never_queries_parameters(graph):
    result=run(graph,include_parameters=True,expected_controller_name="Other.ctl")
    assert result["status"]=="error" and not result.get("parameter_lookup_attempted",False)


@pytest.mark.parametrize("name",[None,"","Example.aptctl","Example",42,"bad\n.ctl"])
def test_unobserved_or_apt_input_is_rejected_before_native(graph,name):
    result=run(graph,include_parameters=True,expected_controller_name=name)
    assert result["status"]=="error"
    graph[2].GetController.assert_not_called()


def test_unsupported_output_is_preserved_without_retry(graph,monkeypatch):
    graph[2].GetController.return_value="Example.ctl"
    params=SimpleNamespace(GetControllerParameters=Mock(return_value=(None,None,True)))
    prior=reader._typed
    monkeypatch.setattr(reader,"_typed",lambda raw,name,path: params if name=="ICWMachine5" else prior(raw,name,path))
    prior_member=reader._member
    monkeypatch.setattr(reader,"_member",lambda obj,name,*args: params.GetControllerParameters(*args) if name=="GetControllerParameters" else prior_member(obj,name,*args))
    result=run(graph,include_parameters=True,expected_controller_name="Example.ctl")
    assert result["status"]=="review_required" and result["inventory_unchanged"]
    assert result["parameter_output_shape"]["items"][0]==dict(python_type="NoneType",value=None)
    assert result["parameter_shape_issue"]
    params.GetControllerParameters.assert_called_once_with(False,"Example.ctl")


def test_output_snapshot_bounds_and_unknown_objects():
    assert reader._bounded_output(list(range(600)))["truncated"]
    assert reader._bounded_output("x"*5000)["truncated"]
    class Unknown:
        def __str__(self):raise AssertionError("Native objects must not be stringified")
    assert reader._bounded_output(Unknown())["unsupported_type"]


def test_nonfinite_diagnostics_are_json_safe_and_deep_arrays_are_bounded():
    import json
    raw=[float("nan"),float("inf"),float("-inf")]
    serialized=json.dumps(reader._bounded_output(raw),allow_nan=False)
    assert "non_finite" in serialized
    nested=[list(range(600))]*600
    result=reader._bounded_output([nested]*600)
    assert len(json.dumps(result,allow_nan=False)) < 2000000
