"""Focused one-shot and readback tests; no native application is used."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys

import pytest

R = Path(os.environ.get("SOLIDWORKS_SKILL_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(R))
spec = importlib.util.spec_from_file_location("firstcut_test_module",
    Path(__file__).resolve().parents[1] / "scripts/sw_cam_rough_firstcut.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def settings(value):
    return dict(direct_type=value, toolpath_parameters=dict(
        use_setup_definition_for_top_Z=False, use_minimum_Z=False,
        adjust_feature_height=False, first_cut_Z_type_raw=value,
        use_setup_definition_for_bottom_Z=False, minimum_Z_native=0.0, start_Z_native=0.0))


def test_exact_transition_changes_only_one_field():
    assert m.verify_transition(settings(1), settings(0))


@pytest.mark.parametrize("key,value", [
    ("use_setup_definition_for_top_Z", True),
    ("use_minimum_Z", True),
    ("adjust_feature_height", True),
    ("use_setup_definition_for_bottom_Z", True),
    ("minimum_Z_native", -1),
    ("start_Z_native", 28),
])
def test_each_other_parameter_must_be_preserved(key, value):
    after = settings(0); after["toolpath_parameters"][key] = value
    with pytest.raises(ValueError):
        m.verify_transition(settings(1), after)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, 2])
def test_direct_enum_is_strict_and_exact(value):
    before = settings(1); before["direct_type"] = value
    with pytest.raises(ValueError):
        m.verify_transition(before, settings(0))


def test_direct_and_aggregate_getters_must_agree():
    before = settings(1); before["toolpath_parameters"]["first_cut_Z_type_raw"] = 0
    with pytest.raises(ValueError):
        m.verify_transition(before, settings(0))


def test_exact_documented_getter_sequence():
    calls = []
    op = object(); param = object()
    def typed(raw, interface):
        calls.append(("QI", interface))
        return raw
    def read(raw, name):
        calls.append(name)
        return {"GetTypeOfFirstCutZ":1, "GetToolpathParam":param,
                "GetToolpathParameters":(False, False, False, 1, False, 0.0, 0.0)}[name]
    assert m.read_firstcut_settings(op, read, typed) == settings(1)
    assert calls == [("QI","ICWMillOperation3"), "GetTypeOfFirstCutZ", "GetToolpathParam",
                     ("QI","ICWToolpathParam"), "GetToolpathParameters"]


def test_one_dispatch_with_before_and_after_readback():
    events=[]; report={}
    def observe(phase):
        events.append(phase)
        return settings(1 if phase=="before" else 0)
    def dispatch():
        events.append("one_native_setter"); return 0
    m.run_firstcut_change(observe=observe, dispatch=dispatch,
                         persist=lambda:events.append("persist"), report=report)
    assert events == ["before","persist","one_native_setter","persist","after","persist"]
    assert report["setter_returned"] is True
    assert report["after_settings"] == settings(0)


@pytest.mark.parametrize("failure", ["before", "persist", "dispatch", "after", "readback_mismatch"])
def test_failure_never_replays_dispatch(failure):
    report={}; calls=[]
    def observe(phase):
        if failure==phase: raise RuntimeError(phase)
        return settings(1 if phase=="before" or failure=="readback_mismatch" else 0)
    def persist():
        if failure=="persist": raise OSError("disk")
    def dispatch():
        calls.append(1)
        if failure=="dispatch": raise RuntimeError("native")
        return 0
    with pytest.raises((RuntimeError, OSError, ValueError)):
        m.run_firstcut_change(observe=observe, dispatch=dispatch, persist=persist, report=report)
    assert len(calls) == (0 if failure in ("before","persist") else 1)


@pytest.mark.parametrize("result", [None, False, True, 0.0, 1, -1, (), "success"])
def test_no_out_hresult_return_shape_must_be_exact_integer_zero(result):
    observations=[];calls=[]
    def observe(phase):
        observations.append(phase);return settings(1)
    def dispatch():
        calls.append(1);return result
    with pytest.raises(ValueError, match="integer S_OK"):
        m.run_firstcut_change(observe=observe, dispatch=dispatch, persist=lambda:None, report={})
    assert calls == [1]
    assert observations == ["before"]


def test_attempt_key_is_source_and_action_scoped_not_receipt_scoped(tmp_path):
    source=tmp_path/"copy.SLDPRT"
    first=m.attempt_marker(str(source), "1"*64,247)
    assert first == m.attempt_marker(str(source), "1"*64,247)
    assert first != m.attempt_marker(str(source), "2"*64,247)
    assert first != m.attempt_marker(str(source), "1"*64,248)
    assert first.parent == tmp_path


def test_setup_top_override_is_not_silently_cleared():
    before=settings(1); before["toolpath_parameters"]["use_setup_definition_for_top_Z"]=True
    with pytest.raises(ValueError):
        m.verify_transition(before, settings(0))


@pytest.fixture
def emulated(tmp_path, monkeypatch):
    """Exercise the native wrapper's receipt/dirty/one-shot flow with explicit test doubles."""
    import hashlib
    from types import SimpleNamespace
    import scripts.sw_cam_events as event_module
    source=tmp_path/"part.SLDPRT"; source.write_bytes(b"saved part")
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    pins=[]
    for name in ("anchor.json","levels.json","primary.json"):
        p=tmp_path/name;p.write_text("{}")
        pins.append(dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    state=dict(saved_file_sha256=sha,document=dict(path=str(source),title=source.name,type=1,needs_save=False),
               operations=[dict(native_id=i,toolpath_generated=False) for i in [143,144,195,196,247,248]],
               stock=dict(top=28),features=[244],sw_reference=dict(solids=[]))
    values=dict(current=1,dirty=False,dirty_after=False,calls=0,raise_setter=False,alter_other=False)
    level_values=dict(machining_depth_native=13.2,override_machining_depth=False,
                      toolpath_parameters=deepcopy(settings(1)["toolpath_parameters"]))
    setup=dict(origin_native=[0,0,26],axis_native=[0,0,-1])
    levels=dict(before=deepcopy(state),levels=deepcopy(level_values),setup=deepcopy(setup))
    class Anchor:
        def check_files(self):pass
        def check_runtime_identity(self):pass
        def summary(self):return {"scope":"test_double"}
        def verify(self,observed):
            assert observed==state
    anchor=Anchor(); anchor.pins=[pins[0]]
    class Op:
        def GetTypeOfFirstCutZ(self):return values["current"]
        def GetToolpathParam(self):return self
        def GetToolpathParameters(self):
            return (False,False,False,values["current"],False,
                    1.0 if values["alter_other"] and values["calls"] else 0.0,0.0)
        def SetTypeOfFirstCutZ(self,value):
            values["calls"]+=1;values["current"]=value;values["dirty"]=values["dirty_after"]
            if values["raise_setter"]:raise RuntimeError("native failure after possible mutation")
            return 0
    op=Op();sw=SimpleNamespace(GetProcessID=lambda:23824)
    def identity(_):
        doc=deepcopy(state["document"]);doc["needs_save"]=values["dirty"];return doc
    monkeypatch.setattr(m,"raw_part_identity",identity)
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *a,**k:anchor)
    monkeypatch.setattr(m,"load_levels_anchor",lambda *a,**k:(levels,pins[1]))
    monkeypatch.setattr(m,"load_primary_contract",lambda *a,**k:[pins[2]])
    monkeypatch.setattr(m,"validate_defined_rough",lambda *a,**k:dict(native_id=247))
    monkeypatch.setattr(m,"_bootstrap",lambda *a,**k:object())
    monkeypatch.setattr(m,"_object_id",lambda *a,**k:247)
    class Session:
        def __init__(self,*a):self.active=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False
        def summary(self):
            return dict(subscribed=True,active=self.active,disconnected=not self.active,
                        event_count=0,overflow=0,callback_errors=[],callback_error_count=0,
                        subscription_error=None,disconnect_errors=[])
    monkeypatch.setattr(event_module,"CamMessageSession",Session)
    class Guard:
        def __init__(self,*a,**kw):self.kw=kw
        def __enter__(self):
            self.kw["verify_evidence"]();self.kw["verify_owned_process"]();self.kw["check_events"]();return self
        def __exit__(self,*a):pass
        def read(self,obj,name,*a):return m._member(obj,name,*a)
        def typed(self,obj,name):return obj
        def dispatch_once(self,invoke,*,persist_pending):
            persist_pending();return invoke()
        def summary(self):return {"native_call_attempted":True,"native_call_returned":True}
    monkeypatch.setattr(m,"ScopedCamDispatchGuard",Guard)
    def capture(*a,**kw):
        observed=deepcopy(state);observed["document"]=identity(sw)
        detail=deepcopy(level_values);detail["toolpath_parameters"]=settings(values["current"])["toolpath_parameters"]
        if values["alter_other"] and values["calls"]:detail["toolpath_parameters"]["minimum_Z_native"]=1.0
        kw["diagnostic"]["operation_details"]=dict(
            levels_observation=dict(levels=detail,setup=deepcopy(setup)),
            firstcut_settings=dict(direct_type=values["current"],toolpath_parameters=deepcopy(detail["toolpath_parameters"])))
        return observed,dict(doc=object(),operations={247:op})
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    args=dict(process_id=23824,expected_document_path=str(source),expected_source_sha256=sha,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145,
        saved_plan_receipt_path=pins[0]["path"],saved_plan_receipt_sha256=pins[0]["sha256"],
        levels_receipt_path=pins[1]["path"],levels_receipt_sha256=pins[1]["sha256"],
        primary_contract_path=pins[2]["path"],primary_contract_sha256=pins[2]["sha256"],
        qualification_only=True,acknowledge_disposable_copy=True,message_policy="vendor_default",
        target_feature_native_id=244,target_operation_native_id=247,target_operation_setup_native_id=93,
        receipt_path=str(tmp_path/"result.json"))
    def run():return m.set_rough_first_cut_to_stock(sw,"unused","unused",**args)
    return dict(run=run,values=values,args=args,source=source)


@pytest.mark.parametrize("dirty_after",[False,True])
def test_wrapper_preserves_actual_dirty_flag_and_finished_marker(emulated,dirty_after):
    import hashlib
    e=emulated;e["values"]["dirty_after"]=dirty_after
    report=e["run"]()
    assert report["status"]=="review_required",report.get("issue")
    assert report["readback_verified"] is True
    assert report["after_document"]["needs_save"] is dirty_after
    assert report["model_saved"] is False
    assert e["values"]["calls"]==1
    args=e["args"]
    p=Path(args["receipt_path"])
    loaded=m.load_firstcut_receipt(str(p),hashlib.sha256(p.read_bytes()).hexdigest(),
        **{k:args[k] for k in ("process_id","expected_document_path","expected_source_sha256",*m.TARGET_KEYS)})
    assert loaded["after_settings"]==settings(0)
    assert report["saved_file_sha256"]==hashlib.sha256(e["source"].read_bytes()).hexdigest()


def test_wrapper_native_failure_retains_marker_and_forbids_new_receipt_replay(emulated):
    e=emulated;e["values"]["raise_setter"]=True
    report=e["run"]()
    assert report["status"]=="error"
    assert report["native_dispatch_pending"] is True
    assert report["setter_returned"] is False
    assert e["values"]["calls"]==1
    e["args"]["receipt_path"]=str(Path(e["args"]["receipt_path"]).with_name("retry.json"))
    second=e["run"]()
    assert second["status"]=="error"
    assert second["failed_phase"]=="preflight"
    assert second["setter_attempted"] is False
    assert not Path(e["args"]["receipt_path"]).exists()
    assert e["values"]["calls"]==1


def test_wrapper_rejects_another_field_changed_by_native_call(emulated):
    e=emulated;e["values"]["alter_other"]=True
    report=e["run"]()
    assert report["status"]=="error"
    assert report["readback_verified"] is False
    assert report["setter_returned"] is True
    assert e["values"]["calls"]==1


@pytest.mark.parametrize("value", [None, True, False, 0.0, 1])
def test_continuation_rejects_non_integer_zero_hresult(emulated,value):
    import hashlib,json
    e=emulated;report=e["run"]()
    assert report["readback_verified"] is True
    report["setter_return_value"]=value
    p=Path(e["args"]["receipt_path"]);p.write_text(json.dumps(report),encoding="utf-8")
    with pytest.raises(ValueError,match="HRESULT"):
        m.load_firstcut_receipt(str(p),hashlib.sha256(p.read_bytes()).hexdigest(),
            **{k:e["args"][k] for k in ("process_id","expected_document_path","expected_source_sha256",*m.TARGET_KEYS)})
