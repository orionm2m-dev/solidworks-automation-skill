"""单次 Pitch 写入与 16 标量回读；禁止误写角度、Z、工具与保存。"""
from copy import deepcopy
import json
import math
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_sw_cam_feature_plan import probe as plan_probe
from test_sw_cam_turn_feature_attribute import probe as attribute_probe
from scripts import sw_cam_thread_parameters as cam


@pytest.fixture
def probe(plan_probe,monkeypatch):
    p=plan_probe;p.add();p.state["document"]["needs_save"]=False
    operation=p.operation_setup.IGetEnumOperations.return_value[-1]
    values={name:0. for name in cam._DOUBLE_METHODS}
    values.update(GetPitchValue=.4,GetDepthPerCutValue=1.,GetLastDepthPerCutValue=1.,
        GetStartLengthValue=3.,GetEntryAngleValue=math.pi/2,GetWithdrawAngleValue=math.pi/2)
    values.update({name:0 for name in cam._INT_METHODS})
    for name in values:setattr(operation,name,Mock(side_effect=lambda name=name:values[name]))
    blocked={name:Mock(side_effect=AssertionError("Unqualified native getter/mutation")) for name in
        ("IGetTool","GetMinZLimit","GetMaxZLimit","GetMaxZTurnMethod","ReverseCut","GetIsLicensed","GenerateToolpath","SetEntryAngleValue")}
    for name,method in blocked.items():setattr(operation,name,method)
    p.state["on_pitch"]=None
    def set_pitch(value):
        durable=json.loads(p.receipt.read_text())
        assert durable["phase"]=="SetPitchValue" and durable["mutation_attempted"]
        assert p.session.data["active"]
        values["GetPitchValue"]=value;values["GetActualPitchValue"]=value
        p.state["document"]["needs_save"]=True
        if p.state["on_pitch"]:p.state["on_pitch"]()
    operation.SetPitchValue=Mock(side_effect=set_pitch)
    monkeypatch.setattr(cam,"document_snapshot",p.documents)
    monkeypatch.setattr(cam,"_context",p.contexts)
    monkeypatch.setattr(cam,"_items",lambda value,*_,**kwargs:list(value))
    monkeypatch.setattr(cam,"_inventory",lambda *_:deepcopy(p.inventory))
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj)
    defaults=p.defaults|dict(expected_feature_count=2,expected_operation_count=2,expected_operation_setup_count=1,
        setup_index=0,operation_index=1,expected_operation_native_id=383)
    def call(action="inspect",**changes):
        args=defaults|dict(action=action)
        if action!="inspect":args.update(expected_old_pitch=.4,new_pitch=1.5)
        return cam.configure_thread_pitch(p.sw,"clsid","registered/camworks.tlb",**(args|changes))
    def apply(**changes):
        before=call("prepare");assert before["status"]=="ok",before
        return call("apply",**(dict(expected_state_sha256=before["state_sha256"],receipt_path=str(p.receipt))|changes))
    return N(parent=p,operation=operation,values=values,blocked=blocked,call=call,apply=apply)


def test_inspect_and_prepare_never_mutate_or_probe_unqualified_tail(probe):
    result=probe.call()
    assert result["status"]=="ok" and len(result["before"]["thread_parameters_native"])==16
    prepared=probe.call("prepare");assert prepared["apply_eligible"]
    assert not probe.parent.receipt.exists()
    probe.operation.SetPitchValue.assert_not_called()
    for method in probe.blocked.values():method.assert_not_called()
    probe.parent.target.GenerateOpPlan.assert_not_called()


def test_apply_one_native_pitch_preserves_every_other_observed_field(probe):
    result=probe.apply()
    assert result["status"]=="review_required" and result["readback_verified"]
    assert result["scalar_readback_verified"] and result["pitch_readback_native"]==1.5
    assert result["actual_pitch_native"]==1.5
    assert not result["thread_depth_verified"] and not result["units_verified"]
    assert not result["model_saved"] and not result["toolpath_generation_attempted"]
    assert result["post_cleanup_cam_read_performed"] is False
    assert result["messages"]["disconnected"] and len(result["snapshot_diagnostics"])==3
    assert json.loads(probe.parent.receipt.read_text())["readback_verified"]
    probe.operation.SetPitchValue.assert_called_once_with(1.5)
    for method in probe.blocked.values():method.assert_not_called()
    for method in probe.parent.forbidden:method.assert_not_called()


@pytest.mark.parametrize("change",["old_value","dirty","generated","wrong_id","wrong_link","wrong_type","count","wrong_hash","existing_receipt"])
def test_preflight_stops_before_pitch_write(probe,change):
    p=probe.parent;changes={}
    if change=="wrong_hash":changes["expected_state_sha256"]="e"*64
    elif change=="existing_receipt":p.receipt.write_bytes(b"immutable")
    else:
        if change=="old_value":probe.values["GetPitchValue"]=.5
        elif change=="dirty":p.state["document"]["needs_save"]=True
        elif change=="generated":p.inventory["operations"][-1].update(toolpath_generated=True,toolpath_record_counts=[10])
        elif change=="wrong_id":changes["expected_operation_native_id"]=474
        elif change=="wrong_link":probe.operation.IGetAllFeatures.return_value=[p.old]
        elif change=="wrong_type":p.inventory["operations"][-1]["turn_operation_type"]=3
        elif change=="count":changes["expected_operation_count"]=3
        result=probe.call("prepare",**changes)
        assert result["status"]=="error";probe.operation.SetPitchValue.assert_not_called();return
    result=probe.apply(**changes)
    assert result["status"]=="error" and not result["mutation_attempted"]
    probe.operation.SetPitchValue.assert_not_called()
    if change=="existing_receipt":assert p.receipt.read_bytes()==b"immutable"


@pytest.mark.parametrize("change",["other_scalar","other_record","profile","file","wrong_pitch","native_error"])
def test_unexpected_write_effect_is_uncertain_without_retry(probe,change):
    p=probe.parent
    def changed():
        if change=="other_scalar":probe.values["GetStartLengthValue"]=4.
        elif change=="other_record":p.inventory["operations"][0]["toolpath_record_counts"]=[78]
        elif change=="profile":p.old.profile["segments"][0]["end_native"][2]=4.
        elif change=="file":p.path.write_bytes(b"saved unexpectedly")
        elif change=="wrong_pitch":probe.values["GetPitchValue"]=.4
        else:raise RuntimeError("uncertain native return")
    p.state["on_pitch"]=changed
    result=probe.apply()
    assert result["status"]=="uncertain" and not result["readback_verified"]
    probe.operation.SetPitchValue.assert_called_once_with(1.5)
    assert result["messages"]["disconnected"]


def test_unknown_outcome_can_be_inspected_without_replay_or_receipt_change(probe):
    def fault():raise RuntimeError("after mutation")
    probe.parent.state["on_pitch"]=fault
    assert probe.apply()["status"]=="uncertain"
    durable=probe.parent.receipt.read_bytes()
    result=probe.call()
    assert result["status"]=="ok" and result["before"]["thread_parameters_native"]["GetPitchValue"]==1.5
    assert not result["mutation_attempted"]
    assert probe.parent.receipt.read_bytes()==durable
    probe.operation.SetPitchValue.assert_called_once_with(1.5)


@pytest.mark.parametrize("when",["enter","pitch","exit"])
def test_events_stop_subsequent_native_calls(probe,when):
    def event():probe.parent.session.data["event_count"]=1
    probe.parent.state["on_"+when]=event
    result=probe.apply();assert not result["readback_verified"]
    if when=="enter":probe.operation.SetPitchValue.assert_not_called()
    else:probe.operation.SetPitchValue.assert_called_once_with(1.5)
    if when=="pitch":assert len(result["snapshot_diagnostics"])==2


@pytest.mark.parametrize("field,value",[("new_pitch",True),("new_pitch",0),("new_pitch",-1),("new_pitch",float("nan")),
    ("new_pitch",float("inf")),("new_pitch","1.5"),("expected_old_pitch",False),
    ("expected_operation_native_id",True),("operation_index",1.0),("qualification_only",1)])
def test_strict_inputs_fail_before_any_capture(probe,field,value):
    result=probe.call("prepare",**{field:value})
    assert result["status"]=="error";probe.parent.contexts.assert_not_called()
    probe.operation.SetPitchValue.assert_not_called()


def test_apply_binds_requested_new_pitch_in_state_hash(probe):
    before=probe.call("prepare")
    result=probe.call("apply",new_pitch=2.,expected_state_sha256=before["state_sha256"],receipt_path=str(probe.parent.receipt))
    assert result["status"]=="error";probe.operation.SetPitchValue.assert_not_called()


def test_initial_scalar_exception_retains_partial_and_never_reads_z(probe):
    probe.operation.GetStartLengthValue.side_effect=RuntimeError("native scalar failed")
    result=probe.call()
    assert result["status"]=="error" and result["snapshot_diagnostics"][-1]["stage"]=="GetStartLengthValue"
    assert result["snapshot_diagnostics"][-1]["thread_parameters_native"]["GetPitchValue"]==.4
    probe.operation.GetEndLengthValue.assert_not_called()
    for method in probe.blocked.values():method.assert_not_called()
