"""Offline guards for existing explode-step matrix reads."""
from copy import deepcopy
import hashlib
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("staged_explode_step_transforms",
                                            ROOT / "scripts/sw_explode_step_transforms.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    source = tmp_path / "TOP.SLDASM"; source.write_bytes(b"saved-top")
    child = tmp_path / "COLLAR.SLDPRT"; child.write_bytes(b"saved-child")
    target = dict(index=49, name="COLLAR_UNSCREW_01", component_name="CLOSURE-1/COLLAR-1")
    document = dict(path=str(source), needs_save=False, active_configuration="Default")
    row = dict(index=49, name=target["name"], distance_m=0.000375,
               angle_rad=-math.pi / 2, components=[target["component_name"]], axes={})
    flag = dict(index=49, name=target["name"], reverse_translation=True, reverse_rotation=False)
    snapshot = dict(document_path=str(source), active_configuration="Default",
                    components=[dict(path=str(child), name=target["component_name"])],
                    native_step_sequence=[row])
    identity = [1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.000375,1.,0.,0.,0.]
    calls = []
    callbacks = {}
    values = dict(count=1, name=target["component_name"],
                  whole=identity[:], specific=identity[:])
    def dispatch(method, value, *args):
        calls.append((method, args))
        if method in callbacks: callbacks[method]()
        result = values[value]
        if isinstance(result, Exception): raise result
        return result
    step = SimpleNamespace(
        GetNumOfComponents=lambda: dispatch("GetNumOfComponents", "count"),
        GetComponentName=lambda index: dispatch("GetComponentName", "name", index),
        GetComponentXform=lambda: dispatch("GetComponentXform", "whole"),
        GetSpecificComponentXForm=lambda index: dispatch("GetSpecificComponentXForm", "specific", index))
    model, sw = object(), object()
    capture_count = [0]
    def structure(actual):
        assert actual is model
        capture_count[0] += 1
        result = deepcopy(snapshot)
        flags = [deepcopy(flag)]
        if capture_count[0] == 2 and "after" in callbacks: callbacks["after"](result, flags)
        return result, flags, {49: step}
    def document_guard(actual_sw, pid, path, *, clean=False, configuration_name=None):
        assert actual_sw is sw
        if type(pid) is not int or pid != 123 or path != source:
            raise ValueError("PID/path differs")
        if clean and document["needs_save"]: raise ValueError("dirty")
        if configuration_name is not None and configuration_name != document["active_configuration"]:
            raise ValueError("configuration differs")
        return model, deepcopy(document)
    monkeypatch.setattr(m.axes, "_document_guard", document_guard)
    monkeypatch.setattr(m.axes, "_structure", structure)
    monkeypatch.setattr(m.audit, "call", lambda obj, name, *args: getattr(obj, name)(*args))
    params = dict(process_id=123, expected_document_path=str(source),
                  expected_file_sha256=sha(source), targets=[target],
                  receipt_path=str(tmp_path / "receipt.json"))
    return SimpleNamespace(source=source, child=child, params=params, sw=sw,
        calls=calls, callbacks=callbacks, values=values, snapshot=snapshot,
        document=document, flag=flag, capture_count=capture_count)


def run(case, **changes):
    return m.read_explode_step_transforms(case.sw, **dict(case.params, **changes))


def test_captures_only_four_read_only_calls_and_preserves_all_state(case):
    out = run(case)
    assert out["readback_complete"] and out["state_unchanged"]
    assert out["status"] == "review_required"
    assert out["before_state_sha256"] == out["after_state_sha256"]
    assert out["results"][0]["reverse_flags"]["reverse_translation"] is True
    assert case.calls == [("GetNumOfComponents",()),("GetComponentName",(0,)),
                         ("GetComponentXform",()),("GetSpecificComponentXForm",(0,))]
    assert out["mutation_attempted"] is False and out["model_saved"] is False
    assert not any(out[x] for x in ("motion_verified","collision_verified","native_direction_verified"))


@pytest.mark.parametrize("count",[None,False,True,1.,0,2,-1])
def test_bad_count_stops_before_index_or_matrix(case,count):
    case.values["count"]=count
    out=run(case)
    assert not out["readback_complete"] and len(case.calls)==1


@pytest.mark.parametrize("name",[None,False,"wrong",""])
def test_identity_mismatch_never_probes_alternate_index(case,name):
    case.values["name"]=name
    out=run(case)
    assert not out["readback_complete"] and len(case.calls)==2


@pytest.mark.parametrize("value",[None,False,0,[],[0.]*15,[0.]*17,
    [False]*16,[float("nan")]*16,[float("inf")]*16,["1"]*16])
@pytest.mark.parametrize("getter",["whole","specific"])
def test_invalid_matrix_is_never_motion_success(case,value,getter):
    case.values[getter]=value
    out=run(case)
    assert not out["readback_complete"]
    assert out["phase"]=="failed" and not out["native_direction_verified"]


def test_distinct_valid_arrays_are_recorded_without_equivalence_claim(case):
    case.values["specific"][9]=0.1
    out=run(case)
    assert out["readback_complete"]
    assert out["results"][0]["getter_arrays_identical"] is False
    assert out["results"][0]["maximum_getter_array_difference"]==0.1
    assert not out["native_direction_verified"]


@pytest.mark.parametrize("pid",[True,0,-1,123.,None,124])
def test_pid_guard(case,pid):
    out=run(case,process_id=pid)
    assert not out["readback_complete"] and case.calls==[]


@pytest.mark.parametrize("targets",[
    [],[dict(index=True,name="x",component_name="y")],
    [dict(index=512,name="x",component_name="y")],
    [dict(index=1,name="",component_name="y")],
    [dict(index=1,name="x",component_name="")],
    [dict(index=1,name="x",component_name="y",extra=1)],
    [dict(index=1,name="x",component_name="y")]*2,
    [dict(index=i,name=str(i),component_name="y") for i in range(33)]
])
def test_target_validation_before_getters(case,targets):
    out=run(case,targets=targets)
    assert not out["readback_complete"] and case.calls==[]


@pytest.mark.parametrize("field,value",[("index",50),("name","other"),("component_name","OTHER")])
def test_exact_target_match(case,field,value):
    targets=deepcopy(case.params["targets"]);targets[0][field]=value
    out=run(case,targets=targets)
    assert not out["readback_complete"] and case.calls==[]


def test_multiple_components_forbidden(case):
    case.snapshot["native_step_sequence"][0]["components"].append("OTHER")
    out=run(case)
    assert not out["readback_complete"] and case.calls==[]


def test_initial_dirty_forbidden(case):
    case.document["needs_save"]=True
    out=run(case)
    assert not out["readback_complete"] and case.calls==[]


@pytest.mark.parametrize("kind",["dirty","configuration","source"])
def test_change_during_getter_stops_following_getter(case,kind):
    def change():
        if kind=="dirty":case.document["needs_save"]=True
        elif kind=="configuration":case.document["active_configuration"]="other"
        else:case.source.write_bytes(b"changed")
    case.callbacks["GetComponentXform"]=change
    out=run(case)
    assert not out["readback_complete"] and len(case.calls)==3


@pytest.mark.parametrize("kind",["matrix","axis","reverse","dependency"])
def test_full_after_capture_changes_are_rejected(case,kind):
    def change(snapshot,flags):
        if kind=="matrix":snapshot["components"][0]["matrix"]=[0.]*16
        elif kind=="axis":snapshot["native_step_sequence"][0]["axes"]={"changed":True}
        elif kind=="reverse":flags[0]["reverse_translation"]=False
        else:case.child.write_bytes(b"changed")
    case.callbacks["after"]=change
    out=run(case)
    assert not out["readback_complete"] and not out["state_unchanged"]


def test_wrong_source_hash_before_getters(case):
    out=run(case,expected_file_sha256="f"*64)
    assert not out["readback_complete"] and case.calls==[]


def test_new_receipt_is_required(case):
    path=Path(case.params["receipt_path"]);path.write_text("do not overwrite")
    out=run(case)
    assert not out["readback_complete"] and case.calls==[]
    assert path.read_text()=="do not overwrite"


def test_final_receipt_failure_revokes_completed_flag(case,monkeypatch):
    original=m._write_receipt
    def fail(path,report,**kwargs):
        if report.get("phase")=="complete": raise OSError("durable receipt unavailable")
        return original(path,report,**kwargs)
    monkeypatch.setattr(m,"_write_receipt",fail)
    out=run(case)
    assert out["status"]=="uncertain" and not out["readback_complete"]


def test_getter_exception_does_not_retry(case):
    case.values["whole"]=RuntimeError("native read error")
    out=run(case)
    assert not out["readback_complete"] and len(case.calls)==3


def test_count_read_change_stops_before_name(case):
    case.callbacks["GetNumOfComponents"]=lambda:case.document.update(needs_save=True)
    out=run(case)
    assert not out["readback_complete"] and len(case.calls)==1
    assert out["current_target"]==case.params["targets"][0]


def test_second_matrix_failure_preserves_first_readback(case):
    case.values["specific"]=RuntimeError("second getter failed")
    out=run(case)
    assert not out["readback_complete"]
    assert out["results"][0]["step_transform"]==case.values["whole"]
    assert out["results"][0]["component_transform"] is None
    assert out["results"][0]["readback_complete"] is False
