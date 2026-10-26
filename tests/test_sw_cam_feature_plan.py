"""单特征 GOP 的调用意图、精确增量、事件停止与只读恢复测试；无 CAD。"""
from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_sw_cam_turn_feature_attribute import probe as attribute_probe
from scripts import sw_cam_feature_plan as cam


@pytest.fixture
def probe(attribute_probe, monkeypatch):
    p=attribute_probe
    p.target.profile.update(attribute_id_raw=17,attribute_name="Thread")
    p.inventory["operations"][0].update(setup_index=0,operation_index=0)
    p.inventory["feature_setup_count"]=1
    p.state["on_generation"]=None
    def generate(preference):
        assert preference == 1
        durable=json.loads(p.receipt.read_text())
        assert durable["mutation_attempted"] and durable["phase"]=="GenerateOpPlan"
        assert p.session.data["active"]
        if p.state["on_generation"]:return p.state["on_generation"]()
        add()
        return None
    def add(native_id=383,kind=12,links=None):
        operation=N(native_id=native_id,IGetAllFeatures=Mock(return_value=links if links is not None else [p.target]))
        p.operation_setup.IGetEnumOperations.return_value.append(operation)
        p.inventory["operation_count"]+=1
        p.inventory["operations"].append(dict(setup_index=0,operation_index=p.inventory["operation_count"]-1,
            turn_operation_type=kind,toolpath_generated=False,toolpath_record_counts=[]))
        p.state["document"]["needs_save"]=True
    p.target.GenerateOpPlan=Mock(side_effect=generate)
    monkeypatch.setattr(cam,"document_snapshot",p.documents)
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj)
    defaults=p.defaults | dict(expected_feature_count=2,expected_operation_count=1,expected_operation_setup_count=1)
    def call(action="inspect",**changes):
        return cam.qualify_feature_operation_plan(p.sw,"clsid","registered/camworks.tlb",**(defaults|dict(action=action)|changes))
    def apply(**changes):
        before=call("prepare");assert before["status"]=="ok",before
        return call("apply",**(dict(expected_state_sha256=before["state_sha256"],receipt_path=str(p.receipt))|changes))
    return N(**p.__dict__,add=add,gop_call=call,gop_apply=apply)


def test_prepare_is_readonly_and_apply_records_void_return_then_exact_delta(probe):
    prepared=probe.gop_call("prepare")
    assert prepared["apply_eligible"] and not probe.receipt.exists()
    probe.target.GenerateOpPlan.assert_not_called()
    result=probe.gop_apply()
    assert result["status"]=="review_required" and result["readback_verified"]
    assert result["new_operation"]["native_id"]==383
    assert result["new_operation"]["turn_operation_type"]==12
    assert result["new_operation"]["linked_feature_ids"]==[382]
    assert result["native_call_returned"] and result["insertion_delta_verified"]
    assert result["messages"]["disconnected"] and not result["messages"]["active"]
    assert not result["model_saved"] and not result["toolpath_generation_attempted"]
    assert not result["thread_condition_verified"] and not result["thread_depth_verified"]
    assert result["post_cleanup_cam_read_performed"] is False
    assert len(result["snapshot_diagnostics"])==3
    assert json.loads(probe.receipt.read_text())["readback_verified"]
    probe.target.GenerateOpPlan.assert_called_once_with(1)
    for method in probe.forbidden:method.assert_not_called()


@pytest.mark.parametrize("change",["zero","two","wrong_type","wrong_links","changed_old_record","changed_file","changed_profile","changed_body"])
def test_exact_delta_failure_is_uncertain_and_never_replays(probe,change):
    def generation():
        if change=="zero":return None
        probe.add(kind=3 if change=="wrong_type" else 12,links=[probe.old] if change=="wrong_links" else None)
        if change=="two":probe.add(native_id=384)
        elif change=="changed_old_record":probe.inventory["operations"][0]["toolpath_record_counts"]=[78]
        elif change=="changed_file":probe.path.write_bytes(b"saved unexpectedly")
        elif change=="changed_profile":probe.old.profile["segments"][0]["end_native"][2]=4.
        elif change=="changed_body":probe.state["solids"][0]["box_model_m"][0]=.001
    probe.state["on_generation"]=generation
    result=probe.gop_apply()
    assert result["status"]=="uncertain" and not result["readback_verified"]
    probe.target.GenerateOpPlan.assert_called_once_with(1)
    assert result["messages"]["disconnected"]


def test_inspect_recovers_dirty_linked_state_without_replaying_unknown_mutation(probe):
    def generation():
        probe.add()
        raise RuntimeError("native call outcome unknown")
    probe.state["on_generation"]=generation
    failed=probe.gop_apply()
    assert failed["status"]=="uncertain" and not failed["native_call_returned"]
    original=probe.receipt.read_bytes()
    result=probe.gop_call(expected_operation_count=2)
    assert result["status"]=="ok" and result["linked_operations"][0]["native_id"]==383
    assert not result["mutation_attempted"] and not result["apply_eligible"]
    assert probe.receipt.read_bytes()==original
    assert probe.gop_call("prepare",expected_operation_count=2)["status"]=="error"
    probe.target.GenerateOpPlan.assert_called_once_with(1)


@pytest.mark.parametrize("change",["dirty","linked","wrong_id","wrong_name","count","wrong_hash","existing_receipt"])
def test_preconditions_stop_before_native_gop(probe,change):
    changes={}
    if change=="wrong_hash":changes["expected_state_sha256"]="f"*64
    elif change=="existing_receipt":probe.receipt.write_bytes(b"immutable")
    else:
        if change=="dirty":probe.state["document"]["needs_save"]=True
        elif change=="linked":probe.operation.IGetAllFeatures.return_value=[probe.target]
        elif change=="wrong_id":probe.target.profile["attribute_id_raw"]=18
        elif change=="wrong_name":probe.target.profile["attribute_name"]="Other"
        elif change=="count":changes["expected_operation_count"]=2
        result=probe.gop_call("prepare",**changes)
        assert result["status"]=="error"
        probe.target.GenerateOpPlan.assert_not_called();return
    result=probe.gop_apply(**changes)
    assert result["status"]=="error" and not result["mutation_attempted"]
    probe.target.GenerateOpPlan.assert_not_called()
    if change=="existing_receipt":assert probe.receipt.read_bytes()==b"immutable"


@pytest.mark.parametrize("when",["enter","generation","exit"])
def test_cam_message_stops_next_native_read_and_cleanup_is_required(probe,when):
    def event():probe.session.data["event_count"]=1
    if when=="generation":
        def generated():probe.add();event()
        probe.state["on_generation"]=generated
    else:probe.state["on_"+when]=event
    result=probe.gop_apply()
    assert not result["readback_verified"]
    if when=="enter":probe.target.GenerateOpPlan.assert_not_called()
    else:probe.target.GenerateOpPlan.assert_called_once_with(1)
    if when=="generation":assert len(result["snapshot_diagnostics"])==2


def test_intent_receipt_write_failure_prevents_native_call(probe,monkeypatch):
    original=cam._write_receipt
    def writer(path,data,**kwargs):
        if data["phase"]=="GenerateOpPlan":raise OSError("durable intent unavailable")
        return original(path,data,**kwargs)
    monkeypatch.setattr(cam,"_write_receipt",writer)
    result=probe.gop_apply()
    assert result["status"]=="uncertain"
    probe.target.GenerateOpPlan.assert_not_called()


@pytest.mark.parametrize("field,value",[("expected_feature_count",True),("expected_operation_count","1"),
    ("expected_operation_setup_count",0),("expected_feature_native_id",False),("qualification_only",1),
    ("message_policy","accept"),("attribute_name",None),("attribute_name","Rough-Finish"),("action","regenerate")])
def test_invalid_inputs_fail_before_any_native_snapshot(probe,field,value):
    result=probe.gop_call(**{field:value})
    assert result["status"]=="error"
    probe.contexts.assert_not_called();probe.target.GenerateOpPlan.assert_not_called()
