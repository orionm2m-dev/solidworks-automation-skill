"""选定 THREAD 后处理：独占输出、意图收据、事件停止与零重放。"""
from copy import deepcopy
import hashlib,json
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_sw_cam_thread_records import probe as records_probe
from scripts import sw_cam_thread_postprocess as cam

@pytest.fixture
def probe(records_probe,monkeypatch):
    p=records_probe
    for name,value in [("_context",p.context),("_items",p.items),("_inventory",p.inv),("_typed",lambda obj,*_:obj),("document_snapshot",lambda *_:deepcopy(p.document))]:monkeypatch.setattr(cam,name,value)
    p.machine.GetController2=Mock(return_value=(False,"GENERIC_TURN",True))
    output=p.path.parent/"post-output"/"thread.nc";receipt=p.path.parent/"post-receipt.json";p.state["on_post"]=None
    def post(path):
        assert p.session.data["active"]
        intent=json.loads(receipt.read_text());assert intent["native_call_attempted"] and intent["phase"]=="PostProcess"
        assert path==str(output) and not output.exists()
        if p.state["on_post"]:return p.state["on_post"]()
        output.write_text("(QUALIFICATION ONLY)\nG32 X58.0479 Z9.9 F1.5\n")
    p.operation.PostProcess=Mock(side_effect=post)
    forbidden=[Mock(side_effect=AssertionError("No controller setter/GTP/save")) for _ in range(4)]
    p.machine.SetController2,p.operation.GenerateToolpath,p.app.SaveActiveDocument,p.app.ActiveDocGTP=forbidden
    def call(action="inspect",**changes):
        args=dict(process_id=26552,expected_document_path=str(p.path),setup_index=0,operation_index=0,expected_operation_native_id=474,
            expected_record_count=4,expected_source_sha256=hashlib.sha256(b"saved").hexdigest(),action=action,qualification_only=True,message_policy="vendor_default")
        if action!="inspect":args["output_path"]=str(output)
        return cam.qualify_thread_postprocess(p.sw,"clsid","registered/camworks.tlb",**(args|changes))
    def apply(**changes):
        prepared=call("prepare");assert prepared["status"]=="ok",prepared
        return call("apply",**(dict(expected_state_sha256=prepared["state_sha256"],receipt_path=str(receipt))|changes))
    return N(**p.__dict__,output=output,receipt=receipt,post_call=call,post_apply=apply,post_forbidden=forbidden)

def test_readonly_prepare_and_single_void_post_require_actual_file(probe):
    assert probe.post_call()["controller"]==dict(is_apt=False,name="GENERIC_TURN",success=True)
    assert probe.post_call("prepare")["apply_eligible"]
    assert not probe.output.parent.exists() and not probe.receipt.exists()
    r=probe.post_apply()
    assert r["status"]=="review_required" and r["output_verified"] and r["readback_verified"] and r["native_call_returned"]
    assert not r["productionNC"] and not r["pitch_verified"] and not r["geometry_verified"] and not r["post_cleanup_cam_read_performed"]
    assert json.loads(probe.receipt.read_text())["output_verified"]
    probe.operation.PostProcess.assert_called_once_with(str(probe.output))
    for method in probe.post_forbidden:method.assert_not_called()

@pytest.mark.parametrize("field,value",[("process_id",True),("setup_index",1.0),("expected_operation_native_id",0),("expected_record_count",0),
    ("expected_record_count",True),("expected_source_sha256","bad"),("expected_document_path","relative.sldprt"),("qualification_only",1),("message_policy","yes"),("action","replay"),("output_path","C:/unrelated.nc")])
def test_invalid_inputs_stop_before_cam(probe,field,value):
    assert probe.post_call(**{field:value})["status"]=="error"
    probe.sw.GetAddInObject.assert_not_called();probe.operation.PostProcess.assert_not_called()

@pytest.mark.parametrize("change",["pid","dirty","source","type","generated","native_id","records","controller_false","controller_blank"])
def test_preconditions_block_write(probe,change):
    args={}
    if change=="pid":probe.sw.GetProcessID.return_value=1
    elif change=="dirty":probe.document["needs_save"]=True
    elif change=="source":probe.path.write_bytes(b"changed")
    elif change=="type":probe.inventory["operations"][0]["turn_operation_type"]=1
    elif change=="generated":probe.inventory["operations"][0]["toolpath_generated"]=False
    elif change=="native_id":args["expected_operation_native_id"]=475
    elif change=="records":args["expected_record_count"]=34
    elif change=="controller_false":probe.machine.GetController2.return_value=(False,"controller",False)
    else:probe.machine.GetController2.return_value=(False,"",True)
    assert probe.post_call("prepare",**args)["status"]=="error"
    probe.operation.PostProcess.assert_not_called()

@pytest.mark.parametrize("value",[(0,"post",True),(True,"post",1),(True,None,True),(True,"x"*4097,True),(True,"p")])
def test_exact_controller_out(probe,value):
    probe.machine.GetController2.return_value=value
    assert probe.post_call()["status"]=="error"

@pytest.mark.parametrize("change",["controller","source","inventory","selected_id","hash"])
def test_prepared_hash_binds_actual_scope(probe,change):
    p=probe.post_call("prepare")
    if change=="controller":probe.machine.GetController2.return_value=(True,"APT",True)
    elif change=="source":probe.path.write_bytes(b"different")
    elif change=="inventory":probe.inventory["feature_count"]+=1
    elif change=="selected_id":probe.operation.native_id=475
    r=probe.post_call("apply",receipt_path=str(probe.receipt),expected_state_sha256="f"*64 if change=="hash" else p["state_sha256"])
    assert r["status"]=="error";probe.operation.PostProcess.assert_not_called()

@pytest.mark.parametrize("change",["missing","empty","sidecar","dirty","source","controller","inventory","exception"])
def test_uncertain_output_never_replays(probe,change):
    def post():
        if change=="exception":raise RuntimeError("native outcome unknown")
        if change!="missing":probe.output.write_text("" if change=="empty" else "raw output")
        if change=="sidecar":(probe.output.parent/"extra.txt").write_text("sidecar")
        elif change=="dirty":probe.document["needs_save"]=True
        elif change=="source":probe.path.write_bytes(b"changed")
        elif change=="controller":probe.machine.GetController2.return_value=(True,"other",True)
        elif change=="inventory":probe.inventory["operation_count"]+=1
    probe.state["on_post"]=post;r=probe.post_apply()
    assert r["status"]=="uncertain" and not r["readback_verified"]
    old=probe.receipt.read_bytes()
    assert probe.post_call("apply",expected_state_sha256="a"*64,receipt_path=str(probe.receipt))["status"]=="error"
    assert probe.receipt.read_bytes()==old;probe.operation.PostProcess.assert_called_once()

@pytest.mark.parametrize("when",["enter","post","exit"])
def test_event_stops_read_and_cleanup_has_no_cam_calls(probe,when):
    prepared=probe.post_call("prepare")
    def event():probe.session.data["event_count"]=1
    if when=="post":probe.state["on_post"]=event
    else:probe.state["on_"+when]=event
    r=probe.post_call("apply",receipt_path=str(probe.receipt),expected_state_sha256=prepared["state_sha256"])
    assert not r["readback_verified"] and probe.session.data["disconnected"]
    if when=="enter":probe.operation.PostProcess.assert_not_called()
    else:probe.operation.PostProcess.assert_called_once()

def test_existing_receipt_is_immutable(probe):
    probe.receipt.write_bytes(b"old");r=probe.post_apply()
    assert r["status"]=="error" and probe.receipt.read_bytes()==b"old";probe.operation.PostProcess.assert_not_called()

def test_intent_write_failure_prevents_native_post(probe,monkeypatch):
    original=cam._write_receipt
    def writer(path,report,**kwargs):
        if report["phase"]=="PostProcess":raise OSError("No durable intent")
        return original(path,report,**kwargs)
    monkeypatch.setattr(cam,"_write_receipt",writer)
    assert probe.post_apply()["status"]=="uncertain";probe.operation.PostProcess.assert_not_called()


def test_output_changed_during_cleanup_is_not_finally_verified(probe):
    prepared=probe.post_call("prepare")
    probe.state["on_exit"]=lambda:probe.output.write_text("changed during cleanup")
    result=probe.post_call("apply",receipt_path=str(probe.receipt),expected_state_sha256=prepared["state_sha256"])
    assert result["status"]=="uncertain" and not result["readback_verified"] and not result["output_verified"]
    probe.operation.PostProcess.assert_called_once()
