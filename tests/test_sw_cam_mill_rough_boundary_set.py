from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest
from scripts import sw_cam_events as events

_staged = Path(__file__).resolve().parents[1] / "scripts/sw_cam_mill_rough_boundary_set.py"
if _staged.exists():
    _spec = importlib.util.spec_from_file_location("staged_mill_rough_boundary_set", _staged)
    cam = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(cam)
else:
    from scripts import sw_cam_mill_rough_boundary_set as cam

READS = [
    "QueryInterface.IDispatch.feature", "QueryInterface.ICWRghMillOp",
    "ICWRghMillOp.GetToolDiameterPercent", "ICWRghMillOp.SideAllow",
    "ICWRghMillOp.GetStepOver", "ICWRghMillOp.PocketMethod",
    "ICWRghMillOp.GetContainType", "ICWRghMillOp.GetContainAllowance",
]


def operation(native_id=114, index=0, **kw):
    return dict(native_id=native_id, setup_index=0, operation_index=index,
        mill_operation_type=index, base_operation_type=1, suppressed=False,
        linked_feature_ids=[111], toolpath_generated=index == 0,
        toolpath_record_counts=[68] if index == 0 else []) | kw


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path = tmp_path / "qualification.sldprt"
    path.write_bytes(b"saved single-feature MILL qualification")
    receipt = tmp_path / "prepare.json"
    sha = cam._file_hash(path)
    current = dict(
        document=dict(path=str(path), title=path.name, type=1, needs_save=False),
        saved_file_sha256=sha, current_machine=dict(machine_type=1, name="Mill"),
        mill_catalogue=[dict(machine_type=1, name="Mill")],
        feature_setups=[dict(native_id=64, feature_count=1)],
        operation_counts=[2], operation_setup_count=1, material_raw="6061-T6",
        selected_feature=dict(native_id=111, volume_type=6, depth_native=3.),
        operations=[operation(), operation(115, 1)])
    control = dict(on_call=None, on_capture=None, on_exit=None, values={}, receipt=receipt, percent=75., invalidate=False, setter_return=0, hold_percent=False)
    data = dict(subscribed=False, active=False, disconnected=False, event_count=0,
        overflow=0, callback_errors=[], callback_error_count=0,
        subscription_error=None, disconnect_errors=[])
    seen = []

    class Session:
        def __enter__(self):
            data.update(subscribed=True, active=True, disconnected=False)
            return self

        def __exit__(self, *_):
            data.update(active=False, disconnected=True)
            if control["on_exit"]:
                control["on_exit"]()

        def summary(self):
            return deepcopy(data)

    def called(label, default):
        assert data["active"]
        durable = json.loads(control["receipt"].read_text())
        assert durable["phase"] == label
        assert durable["native_dispatch_pending"] is True
        assert durable["native_reads"][-1]["attempted"] is True
        assert durable["native_reads"][-1]["returned"] is False
        assert all(row["returned"] and row["validated"] for row in durable["native_reads"][:-1])
        seen.append(label)
        if control["on_call"]:
            control["on_call"](label)
        return control["values"].get(label, default)

    feature, dispatch, raw_op, other = (object() for _ in range(4))

    class Rough:
        def __init__(self):
            self.GetToolDiameterPercent = Mock(side_effect=lambda f: called(
                "ICWRghMillOp.GetToolDiameterPercent", control["percent"]))
            self.GetStepOver = Mock(side_effect=lambda: called("ICWRghMillOp.GetStepOver", (True, 40.)))
            self.GetContainType = Mock(side_effect=lambda: called("ICWRghMillOp.GetContainType", 0))
            self.GetContainAllowance = Mock(side_effect=lambda: called("ICWRghMillOp.GetContainAllowance", .1))

        @property
        def SideAllow(self):
            return called("ICWRghMillOp.SideAllow", .25)

        @property
        def PocketMethod(self):
            return called("ICWRghMillOp.PocketMethod", 2)

    rough = Rough()
    def set_percent(feature_arg, value):
        assert data["active"] and feature_arg is dispatch and value == 0.
        durable = json.loads(control["receipt"].read_text())
        assert durable["phase"] == "SetToolDiameterPercent"
        assert durable["mutation_attempted"] is True
        assert durable["native_setter_attempted"] is True
        assert durable["native_setter_returned"] is False
        assert durable["native_dispatch_pending"] is True
        assert Path(str(receipt)+".apply_attempt.json").is_file()
        seen.append("SetToolDiameterPercent")
        if control["on_call"]:control["on_call"]("SetToolDiameterPercent")
        if not control["hold_percent"]:control["percent"] = value
        current["document"]["needs_save"] = True
        if control["invalidate"]:
            current["operations"][0]["toolpath_generated"] = False
            current["operations"][0]["toolpath_record_counts"] = []
        return control["setter_return"]
    rough.SetToolDiameterPercent = Mock(side_effect=set_percent)

    typed_objects = {"ICWRghMillOp": rough}
    expected_raw = {"ICWRghMillOp": raw_op}

    def typed(raw, name, _):
        assert raw is expected_raw[name]
        return called("QueryInterface." + name, typed_objects[name])

    def capture(*_, **kw):
        assert data["active"]
        kw["check"]()
        if control["on_capture"]:
            control["on_capture"]()
        kw["check"]()
        kw["diagnostic"].update(state=deepcopy(current))
        return deepcopy(current), dict(selected_feature=feature, operations={114: raw_op, 115: other})

    captures = Mock(side_effect=capture)
    bootstrap = Mock(return_value=object())
    model = N(
        GetPathName=Mock(side_effect=lambda: current["document"]["path"]),
        GetTitle=Mock(side_effect=lambda: current["document"]["title"]),
        GetType=Mock(side_effect=lambda: current["document"]["type"]),
        GetSaveFlag=Mock(side_effect=lambda: current["document"]["needs_save"]))
    sw = N(GetProcessID=Mock(return_value=62876), ActiveDoc=model)
    monkeypatch.setattr(cam, "capture_mill_feature_state", captures)
    monkeypatch.setattr(cam, "_bootstrap", bootstrap)
    monkeypatch.setattr(cam, "_typed", typed)
    monkeypatch.setattr(cam, "_dispatch_feature", lambda f: called("QueryInterface.IDispatch.feature", dispatch) if f is feature else None)
    monkeypatch.setattr(events, "CamMessageSession", lambda *_: Session())

    def run(**kw):
        args = dict(process_id=62876, expected_document_path=str(path), expected_source_sha256=sha,
            expected_feature_native_id=111, expected_operation_native_id=114,
            expected_mill_operation_type=0, expected_toolpath_record_counts=[68],
            expected_ungenerated_operation_ids=[115],
            qualification_only=True, acknowledge_disposable_copy=True, receipt_path=str(receipt),
            action="prepare",expected_tool_diameter_percent=75.,new_tool_diameter_percent=0.)
        args.update(kw)
        control["receipt"]=Path(args["receipt_path"])
        return cam.configure_mill_rough_boundary(sw,"clsid","tlb",**args)

    def prepared():
        result=run()
        assert result["status"]=="ok",result
        seen.clear();captures.reset_mock()
        return dict(action="apply",receipt_path=str(tmp_path/"apply.json"),
                    expected_state_sha256=result["state_sha256"],
                    prepare_receipt_path=str(receipt),prepare_receipt_sha256=cam._file_hash(receipt))

    return N(**locals())


def test_prepare_reads_twice_and_never_calls_setter(probe):
    out=probe.run()
    assert out["status"]=="ok" and out["readback_verified"] and out["apply_eligible"]
    assert out["before"]==out["after"]
    assert probe.seen==READS*2 and probe.captures.call_count==2
    assert not out["mutation_attempted"] and not out["native_setter_attempted"]
    probe.rough.SetToolDiameterPercent.assert_not_called()
    assert json.loads(probe.receipt.read_text())==out

@pytest.mark.parametrize("invalidate",[False,True])
def test_single_setter_strict_readback_known_generation_delta(probe,invalidate):
    args=probe.prepared();probe.control["invalidate"]=invalidate
    out=probe.run(**args)
    assert out["status"]=="review_required" and out["parameter_readback_verified"]
    assert out["readback_verified"] and out["native_setter_returned"]
    assert out["after"]["boundary_parameters"]["tool_diameter_percent_native"]==0.
    assert probe.seen==READS*2+["SetToolDiameterPercent"]+READS
    assert probe.captures.call_count==3 and probe.rough.SetToolDiameterPercent.call_count==1
    assert out["selected_toolpath_after"]["no_record_GTP_precondition_met"] is invalidate
    assert out["selected_toolpath_after"]["GTP_authorized"] is False
    assert probe.data["disconnected"] and not probe.data["active"]
    for key in ["model_saved","GTP_attempted","GOP_attempted","stock_edit_attempted",
                "tool_edit_attempted","export_attempted","automatic_path_deletion",
                "air_segment_semantics_verified","boundary_geometry_verified","production_qualified"]:
        assert out[key] is False
    assert json.loads(Path(args["receipt_path"]).read_text())==out
    replay=probe.run(**(args|{"receipt_path":str(probe.tmp_path/"replay.json")}))
    assert replay["status"]=="error" and probe.rough.SetToolDiameterPercent.call_count==1
    assert probe.captures.call_count==3

@pytest.mark.parametrize("return_value",[None,True,False,0.,1,-1])
def test_setter_requires_exact_integer_s_ok_and_never_retries(probe,return_value):
    args=probe.prepared();probe.control["setter_return"]=return_value
    out=probe.run(**args)
    assert out["status"]=="uncertain" and out["native_setter_returned"]
    assert not out["parameter_readback_verified"] and not out["readback_verified"]
    assert probe.rough.SetToolDiameterPercent.call_count==1 and probe.captures.call_count==2
    replay=probe.run(**(args|{"receipt_path":str(probe.tmp_path/"retry.json")}))
    assert replay["status"]=="error" and probe.rough.SetToolDiameterPercent.call_count==1

def test_setter_exception_retains_durable_pending_intent(probe):
    args=probe.prepared()
    def fail(label):
        if label=="SetToolDiameterPercent":raise RuntimeError("unknown native outcome")
    probe.control["on_call"]=fail
    out=probe.run(**args)
    assert out["status"]=="uncertain" and out["native_dispatch_pending"]
    assert out["native_setter_attempted"] and not out["native_setter_returned"]
    assert probe.rough.SetToolDiameterPercent.call_count==1 and probe.captures.call_count==2
    assert Path(str(probe.receipt)+".apply_attempt.json").exists()
    replay=probe.run(**(args|{"receipt_path":str(probe.tmp_path/"retry.json")}))
    assert replay["status"]=="error" and probe.rough.SetToolDiameterPercent.call_count==1

def test_return_success_but_parameter_unchanged_stops(probe):
    args=probe.prepared();probe.control["hold_percent"]=True
    out=probe.run(**args)
    assert out["status"]=="uncertain" and not out["parameter_readback_verified"]
    assert probe.rough.SetToolDiameterPercent.call_count==1

@pytest.mark.parametrize("delta",[
    {"toolpath_generated":False,"toolpath_record_counts":[68]},
    {"toolpath_generated":True,"toolpath_record_counts":[]},
    {"toolpath_generated":True,"toolpath_record_counts":[67]},
    {"toolpath_generated":1,"toolpath_record_counts":[68]},
    {"toolpath_generated":False,"toolpath_record_counts":[False]},
])
def test_unknown_toolpath_delta_stops(probe,delta):
    args=probe.prepared()
    def change(label):
        if label=="SetToolDiameterPercent":probe.current["operations"][0].update(delta)
    probe.control["on_call"]=change
    out=probe.run(**args)
    assert out["status"]=="uncertain" and not out["readback_verified"]
    assert probe.rough.SetToolDiameterPercent.call_count==1

def test_other_parameter_change_stops(probe):
    args=probe.prepared()
    def change(label):
        if label=="SetToolDiameterPercent":
            probe.control["values"]["ICWRghMillOp.SideAllow"]=.5
    probe.control["on_call"]=change
    out=probe.run(**args)
    assert out["status"]=="uncertain" and not out["parameter_readback_verified"]

def test_sibling_change_stops(probe):
    args=probe.prepared()
    def change(label):
        if label=="SetToolDiameterPercent":
            probe.current["operations"][1]["suppressed"]=True
    probe.control["on_call"]=change
    out=probe.run(**args)
    assert out["status"]=="uncertain" and not out["readback_verified"]

def test_state_change_between_captures_prevents_setter(probe):
    args=probe.prepared()
    def change():
        if probe.captures.call_count==2:probe.current["selected_feature"]["depth_native"]=4.
    probe.control["on_capture"]=change
    out=probe.run(**args)
    assert out["status"]=="error" and not out["mutation_attempted"]
    probe.rough.SetToolDiameterPercent.assert_not_called()

@pytest.mark.parametrize("point",["before","setter","after"])
def test_CAM_event_stops_at_bounded_boundary(probe,point):
    args=probe.prepared()
    def event(label):
        if (point=="before" and label==READS[0]
            or point=="setter" and label=="SetToolDiameterPercent"
            or point=="after" and label==READS[0] and probe.rough.SetToolDiameterPercent.call_count):
            probe.data["event_count"]=1
    probe.control["on_call"]=event
    out=probe.run(**args)
    assert out["status"]==("error" if point=="before" else "uncertain")
    assert not out["readback_verified"]
    assert probe.rough.SetToolDiameterPercent.call_count==(0 if point=="before" else 1)

def test_failed_intent_write_prevents_setter_and_consumes_prepare(probe,monkeypatch):
    args=probe.prepared();original=cam._write_receipt
    def write(path,report,**kw):
        if report.get("phase")=="SetToolDiameterPercent":raise OSError("cannot publish intent")
        return original(path,report,**kw)
    monkeypatch.setattr(cam,"_write_receipt",write)
    out=probe.run(**args)
    assert out["status"]=="uncertain" and out["native_dispatch_pending"]
    probe.rough.SetToolDiameterPercent.assert_not_called()
    assert Path(str(probe.receipt)+".apply_attempt.json").exists()

@pytest.mark.parametrize("which,value",[
    ("expected_tool_diameter_percent",True),("new_tool_diameter_percent",False),
    ("expected_tool_diameter_percent","75"),("new_tool_diameter_percent","0"),
    ("new_tool_diameter_percent",float("nan")),("new_tool_diameter_percent",float("inf")),
    ("new_tool_diameter_percent",-1),("new_tool_diameter_percent",151),
    ("new_tool_diameter_percent",75.),("action","inspect"),
    ("process_id",False),("expected_feature_native_id",1.),
    ("qualification_only",1),("acknowledge_disposable_copy",1),
])
def test_invalid_inputs_never_reach_native(probe,which,value):
    out=probe.run(**{which:value})
    assert out["status"]=="error"
    probe.bootstrap.assert_not_called();probe.captures.assert_not_called()
    probe.rough.SetToolDiameterPercent.assert_not_called()

@pytest.mark.parametrize("key,value",[("type",True),("type",1.),("needs_save",None),("needs_save",0),("needs_save",True)])
def test_raw_identity_requires_clean_strict_initial_part(probe,key,value):
    probe.current["document"][key]=value
    out=probe.run()
    assert out["status"]=="error" and not out["mutation_attempted"]
    probe.bootstrap.assert_not_called()

def test_changed_prepare_bytes_prevent_any_native_call(probe):
    args=probe.prepared();probe.receipt.write_text("{}")
    out=probe.run(**args)
    assert out["status"]=="error"
    assert probe.captures.call_count==0 and probe.rough.SetToolDiameterPercent.call_count==0

def test_request_change_cannot_reuse_prepared_digest(probe):
    args=probe.prepared()
    out=probe.run(**(args|{"new_tool_diameter_percent":10.}))
    assert out["status"]=="error" and not out["mutation_attempted"]
    probe.rough.SetToolDiameterPercent.assert_not_called()

def test_file_hash_change_during_setter_is_uncertain(probe):
    args=probe.prepared()
    def change(label):
        if label=="SetToolDiameterPercent":probe.path.write_bytes(b"unexpected disk write")
    probe.control["on_call"]=change
    out=probe.run(**args)
    assert out["status"]=="uncertain" and not out["readback_verified"]

def test_cleanup_failure_rejects_otherwise_verified_parameter(probe):
    args=probe.prepared()
    probe.control["on_exit"]=lambda:probe.data.update(disconnect_errors=["transport"])
    out=probe.run(**args)
    assert out["status"]=="uncertain" and not out["readback_verified"] and not out["parameter_readback_verified"]


def test_initial_raw_bool_count_cannot_equal_requested_zero(probe):
    probe.current["operations"][0]["toolpath_record_counts"]=[68,False]
    out=probe.run(expected_toolpath_record_counts=[68,0])
    assert out["status"]=="error" and not probe.seen
    probe.rough.SetToolDiameterPercent.assert_not_called()

@pytest.mark.parametrize("label",READS)
def test_first_preflight_native_failure_never_reaches_setter(probe,label):
    args=probe.prepared()
    def fail(name):
        if name==label:raise RuntimeError("native preflight read failure")
    probe.control["on_call"]=fail
    out=probe.run(**args)
    assert out["status"]=="error" and not out["mutation_attempted"]
    assert probe.seen==READS[:READS.index(label)+1]
    probe.rough.SetToolDiameterPercent.assert_not_called()
    assert not Path(str(probe.receipt)+".apply_attempt.json").exists()
