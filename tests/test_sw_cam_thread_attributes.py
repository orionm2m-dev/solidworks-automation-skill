"""离线原生属性探针：精确绑定、首次异常停止和订阅范围。"""
from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace as N
from unittest.mock import Mock
import hashlib
import json
import pytest
from scripts import sw_cam_thread_attributes as cam
from scripts import sw_cam_turn_feature_attribute as guards
from scripts import sw_cam_events as events


@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/"part.sldprt";path.write_bytes(b"saved checkpoint")
    sha=hashlib.sha256(path.read_bytes()).hexdigest();receipt=tmp_path/"read.json"
    document=dict(path=str(path),title=path.name,type=1,needs_save=False)
    state=dict(event_on=None,change=None,on_exit=None,calls=[])
    feature=N(native_id=382,FeatureName="Thread source",FeatType=1,GetTurnFeatureType=Mock(return_value=1),
        Attribute=18,GetAttributeName=Mock(return_value="Thread"),GetFeatureAttributes=Mock(return_value=("condition",(1,1.5,None))))
    def collection(items):return N(Count=len(items),Item=Mock(side_effect=lambda index:items[index]))
    linked=collection([feature])
    operation=N(native_id=474,OpernType=12,Suppressed=False,GetIsToolpathGenerated=Mock(return_value=False),
        IGetAllFeatures=Mock(return_value=linked))
    operations=collection([operation]);op_setup=N(IGetEnumOperations=Mock(return_value=operations))
    setups=collection([op_setup]);feature_setup=N(IGetEnumFeatures=Mock(return_value=collection([feature])))
    machine=N(MachType=3,IGetEnumOpSetups=Mock(return_value=setups),
        IGetEnumSetups=Mock(return_value=collection([feature_setup])),IGetWorkpiece=Mock(return_value=N(GetTurnWorkpieceType=Mock(return_value=1))))
    doc=N(GetDocType=Mock(return_value=1),IGetMachine=Mock(return_value=machine),
        GetCWObjectID=Mock(side_effect=lambda obj:(obj.native_id,True)))
    app=N(IGetActiveDoc=Mock(return_value=doc));addin=N(GetCWApp=Mock(return_value=app))
    sw=N(GetProcessID=Mock(return_value=731),GetAddInObject=Mock(return_value=addin))
    class Session:
        def __init__(self):self.data=dict(active=False,subscribed=False,disconnected=False,event_count=0)
        def __enter__(self):self.data.update(active=True,subscribed=True);return self
        def __exit__(self,*_):
            self.data.update(active=False,disconnected=True)
            if state["on_exit"]:state["on_exit"]()
        def summary(self):return deepcopy(self.data)
    session=Session();factory=Mock(return_value=session)
    native_member=cam._member
    def member(obj,name,*args):
        if name not in ("GetProcessID","GetAddInObject","GetCWApp"):
            assert session.data["active"],"No CAM getter after disconnect"
        state["calls"].append(name)
        value=native_member(obj,name,*args)
        if name==state["event_on"]:session.data["event_count"]=1
        if name=="GetFeatureAttributes" and state["change"]:state["change"]()
        return value
    monkeypatch.setattr(cam,"_member",member)
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj);monkeypatch.setattr(guards,"_typed",lambda obj,*_:obj)
    monkeypatch.setattr(cam,"document_snapshot",lambda *_:deepcopy(document))
    monkeypatch.setattr(guards,"document_snapshot",lambda *_:deepcopy(document))
    monkeypatch.setattr(events,"CamMessageSession",factory)
    monkeypatch.setattr(cam,"solidworks_operation_lock",lambda **_:nullcontext())
    def call(**changes):
        values=dict(process_id=731,expected_document_path=str(path),setup_index=0,operation_index=0,
            expected_operation_native_id=474,expected_feature_native_id=382,expected_source_sha256=sha,receipt_path=str(receipt))
        return cam.inspect_thread_feature_attributes(sw,"clsid","registered/camworks.tlb",**(values|changes))
    return N(**locals())


def test_success_reads_once_and_persists_bounded_payload_without_claimed_semantics(probe):
    result=probe.call()
    assert result["status"]=="review_required" and result["readback_verified"]
    assert result["before"]==result["after"] and result["before"]["feature"]["native_id"]==382
    assert result["attributes"]["payload"]["tree"]["python_type"]=="tuple"
    assert not any(result[k] for k in ("mutation_attempted","GOP_attempted","GTP_attempted","model_saved",
        "tool_readers_used","CL_read_attempted","units_verified","thread_condition_verified","total_thread_depth_verified"))
    assert result["messages"]["disconnected"] and result["post_cleanup_document_file_verified"]
    probe.feature.GetFeatureAttributes.assert_called_once_with()
    assert json.loads(probe.receipt.read_text(encoding="utf-8"))==result


def test_existing_dirty_ram_is_not_saved_or_disallowed_if_unchanged(probe):
    probe.document["needs_save"]=True
    result=probe.call();assert result["readback_verified"] and result["unsaved_memory_present"]
    assert probe.path.read_bytes()==b"saved checkpoint"


@pytest.mark.parametrize("field,value",[("process_id",True),("process_id",0),("setup_index",1.0),
    ("operation_index",512),("expected_operation_native_id",False),("expected_feature_native_id",0),
    ("expected_source_sha256","AB"*32),("expected_document_path","relative.sldprt"),
    ("receipt_path","relative.json"),("message_policy","accept")])
def test_strict_validation_before_bootstrap(probe,field,value):
    assert probe.call(**{field:value})["status"]=="error"
    probe.sw.GetAddInObject.assert_not_called();probe.feature.GetFeatureAttributes.assert_not_called()


@pytest.mark.parametrize("kind",["pid","path","sha","operation_id","feature_id","operation_type","multiple_links"])
def test_exact_bindings_block_attribute_getter(probe,kind):
    changes={}
    if kind=="pid":probe.sw.GetProcessID.return_value=732
    elif kind=="path":probe.document["path"]=str(probe.path.parent/"other.sldprt")
    elif kind=="sha":changes["expected_source_sha256"]="ab"*32
    elif kind=="operation_id":changes["expected_operation_native_id"]=475
    elif kind=="feature_id":changes["expected_feature_native_id"]=383
    elif kind=="operation_type":probe.operation.OpernType=2
    else:probe.linked.Count=2
    result=probe.call(**changes);assert result["status"]=="error" and not result["readback_verified"]
    probe.feature.GetFeatureAttributes.assert_not_called()


@pytest.mark.parametrize("getter",["GetDocType","Count","Item","GetFeatureAttributes"])
def test_event_at_each_nested_read_stops_next_cam_getter(probe,getter):
    probe.state["event_on"]=getter
    result=probe.call();assert result["status"]=="error" and result["messages"]["event_count"]==1
    assert probe.state["calls"][-1]==getter
    if getter!="GetFeatureAttributes":probe.feature.GetFeatureAttributes.assert_not_called()
    else:probe.feature.GetFeatureAttributes.assert_called_once_with()
    assert result["messages"]["disconnected"]


def test_first_native_exception_preserves_identity_intent_and_no_retry(probe):
    probe.feature.GetFeatureAttributes.side_effect=RuntimeError("native failure")
    result=probe.call();assert result["status"]=="error" and result["attribute_read_intent"]
    assert result["before"]["capture_complete"] and "after" not in result
    assert result["attribute_diagnostic"]["native_call_attempted"]
    probe.feature.GetFeatureAttributes.assert_called_once_with()
    assert json.loads(probe.receipt.read_text(encoding="utf-8"))==result


def test_unknown_dispatch_payload_is_never_expanded_or_stringified(probe):
    class Trap:
        def __str__(self):raise AssertionError("No stringify")
        def __repr__(self):raise AssertionError("No repr")
        def __getattr__(self,key):raise AssertionError("No getattr")
    probe.feature.GetFeatureAttributes.return_value=Trap()
    result=probe.call();assert result["status"]=="error" and result["attribute_diagnostic"]["native_call_succeeded"]
    assert not result["attribute_diagnostic"]["payload_copied"] and "after" not in result
    probe.feature.GetFeatureAttributes.assert_called_once_with()


@pytest.mark.parametrize("kind",["file","dirty","feature_id","attribute","inventory"])
def test_changes_during_read_never_claim_verified(probe,kind):
    def change():
        if kind=="file":probe.path.write_bytes(b"changed")
        elif kind=="dirty":probe.document["needs_save"]=True
        elif kind=="feature_id":probe.feature.native_id=383
        elif kind=="attribute":probe.feature.Attribute=19
        else:probe.operation.GetIsToolpathGenerated.return_value=True
    probe.state["change"]=change
    result=probe.call();assert result["status"]=="error" and not result["readback_verified"]
    probe.feature.GetFeatureAttributes.assert_called_once_with()


def test_cleanup_message_invalidates_read_without_more_cam_getters(probe):
    probe.state["on_exit"]=lambda:probe.session.data.update(event_count=1)
    result=probe.call();assert result["status"]=="error" and "after" in result and not result["readback_verified"]
    probe.feature.GetFeatureAttributes.assert_called_once_with()


def test_existing_receipt_is_not_overwritten_or_replayed(probe):
    probe.receipt.write_text("prior",encoding="utf-8")
    assert probe.call()["status"]=="error" and probe.receipt.read_text()=="prior"
    probe.sw.GetAddInObject.assert_not_called()


@pytest.mark.parametrize("when",["create","intent","final"])
def test_receipt_failures_do_not_replay_getter(probe,monkeypatch,when):
    original=cam._write_receipt
    def write(path,report,**kwargs):
        if ((when=="create" and kwargs.get("create")) or
            (when=="intent" and report["phase"]=="attribute_read_intent") or
            (when=="final" and report["phase"]=="finished")):
            raise OSError("receipt failure")
        return original(path,report,**kwargs)
    monkeypatch.setattr(cam,"_write_receipt",write)
    result=probe.call();assert result["status"]=="error" and not result["readback_verified"]
    if when=="final":probe.feature.GetFeatureAttributes.assert_called_once_with();assert result["receipt_persist_failed"]
    else:probe.feature.GetFeatureAttributes.assert_not_called()
