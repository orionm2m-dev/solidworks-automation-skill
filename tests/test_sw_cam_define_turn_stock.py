"""空 CAM 副本中显式 raw 棒料定义的门禁、回执和整数 ABI 测试。"""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_generation as cam
from scripts import sw_cam_events as events


@pytest.fixture
def probe(tmp_path,monkeypatch):
    part=tmp_path/"CAM_CHECK.sldprt"
    part.write_bytes(b"fixture")
    receipt=tmp_path/"define_stock.json"
    document=dict(path=str(part),title=part.name,type=1,needs_save=False)
    initial=dict(startZ=-30.9,length=30.9,odOff=70.2569,idOff=0.0,attribute=1)
    target=dict(startZ=-33.0,length=35.0,odOff=75.0,idOff=0.0,attribute=1)
    inventory=dict(feature_setup_count=0,feature_count=0,operation_setup_count=0,operation_count=0,
                   operations=[],stock={"type":3})
    state=dict(bar=deepcopy(initial),result=0,on_native=None,on_exit=None,update=True)
    class Session:
        def __init__(self):
            self.report=dict(subscribed=False,disconnected=False,event_count=0,overflow=0,
                             callback_errors=[],disconnect_errors=[])
        def __enter__(self):
            self.report["subscribed"]=True
            return self
        def __exit__(self,*args):
            self.report["disconnected"]=True
            if state["on_exit"]:
                state["on_exit"]()
        def summary(self):
            return deepcopy(self.report)
    session=Session()
    def define(*args):
        durable=json.loads(receipt.read_text(encoding="utf-8"))
        assert durable["mutation_attempted"] and durable["phase"]=="DefineTurnWorkpieceAsBarStock2"
        assert args==tuple(target.values())
        if state["on_native"]:
            state["on_native"]()
        if state["update"] and type(state["result"]) is int and state["result"]==0:
            state["bar"]=deepcopy(target)
        return state["result"]
    stock=SimpleNamespace(GetTurnWorkpieceType=Mock(return_value=3),
        GetBarStockParameters=Mock(side_effect=lambda:tuple(state["bar"].values())),
        DefineTurnWorkpieceAsBarStock2=Mock(side_effect=define))
    machine=SimpleNamespace(IGetWorkpiece=Mock(return_value=stock))
    context=Mock(side_effect=lambda *_:(deepcopy(document),object(),object(),machine,object()))
    monkeypatch.setattr(cam,"_context",context)
    monkeypatch.setattr(cam,"_inventory",Mock(side_effect=lambda *_:deepcopy(inventory)))
    monkeypatch.setattr(cam,"document_snapshot",Mock(side_effect=lambda *_:deepcopy(document)))
    monkeypatch.setattr(cam,"_typed",Mock(return_value=stock))
    monkeypatch.setattr(events,"CamMessageSession",Mock(return_value=session))
    def run(**changes):
        return cam.define_turn_stock(object(),"clsid","registered.tlb",**dict(expected_document_path=str(part),
            expected_bar_parameters_native=initial,bar_parameters_native=target,receipt_path=str(receipt),
            qualification_only=True,message_policy="vendor_default")|changes)
    return SimpleNamespace(run=run,initial=initial,target=target,state=state,stock=stock,document=document,
                           inventory=inventory,receipt=receipt,session=session,context=context)


def test_raw_definition_persists_integer_return_and_exact_readback(probe):
    report=probe.run()
    assert report["status"]=="review_required" and report["stock_definition_verified"]
    assert report["native_error_code"]==0 and report["native_return_contract_valid"]
    assert report["bar_parameters_after"]==probe.target and report["inventory_unchanged"]
    assert report["bar_parameters_after_cleanup"]==probe.target
    assert report["verification_scope"]=="after_event_cleanup"
    assert not report["native_units_and_offset_semantics_verified"] and not report["frame_orientation_verified"]
    assert not report["model_saved"] and not report["generation_attempted"] and not report["may_continue"]
    assert report["messages"]["disconnected"]
    assert json.loads(probe.receipt.read_text(encoding="utf-8"))==report
    probe.stock.DefineTurnWorkpieceAsBarStock2.assert_called_once_with(-33.0,35.0,75.0,0.0,1)


@pytest.mark.parametrize("key", ["feature_setup_count","feature_count","operation_setup_count","operation_count"])
def test_any_existing_cam_plan_prevents_definition(probe,key):
    probe.inventory[key]=1
    assert probe.run()["status"]=="error"
    probe.stock.DefineTurnWorkpieceAsBarStock2.assert_not_called()


def test_stale_expected_bar_values_prevent_definition(probe):
    probe.state["bar"]["length"]+=1
    assert probe.run()["status"]=="error"
    probe.stock.DefineTurnWorkpieceAsBarStock2.assert_not_called()


def test_dirty_part_prevents_definition(probe):
    probe.document["needs_save"]=True
    assert probe.run()["status"]=="error"
    probe.stock.DefineTurnWorkpieceAsBarStock2.assert_not_called()


@pytest.mark.parametrize("returned", [1,2,3,True,False,None,(0,)])
def test_error_or_non_integer_return_stops_without_cad_readback(probe,returned):
    probe.state["result"]=returned
    def prohibit_readback():
        probe.stock.GetBarStockParameters.side_effect=AssertionError("No readback after failed native return")
    probe.state["on_native"]=prohibit_readback
    report=probe.run()
    assert report["status"]=="error" and not report["stock_definition_verified"]
    assert report["native_call_returned"] and report["messages"]["disconnected"]


def test_message_during_native_call_stops_before_readback(probe):
    def message():
        probe.session.report["event_count"]=1
        probe.stock.GetBarStockParameters.side_effect=AssertionError("No readback after CAM event")
    probe.state["on_native"]=message
    report=probe.run()
    assert report["reason"]=="CAM_MESSAGES_REQUIRE_REVIEW" and not report["stock_definition_verified"]


def test_readback_mismatch_is_not_verified(probe):
    probe.state["update"]=False
    assert not probe.run()["stock_definition_verified"]


def test_native_exception_is_uncertain_and_not_retried(probe):
    probe.stock.DefineTurnWorkpieceAsBarStock2.side_effect=RuntimeError("native failed")
    assert probe.run()["status"]=="uncertain"
    probe.stock.DefineTurnWorkpieceAsBarStock2.assert_called_once()


def test_before_call_receipt_failure_prevents_native_entry(probe,monkeypatch):
    original=cam._write_receipt
    def write(path,report,**kwargs):
        if report["mutation_attempted"]:
            raise OSError("No durable attempt")
        return original(path,report,**kwargs)
    monkeypatch.setattr(cam,"_write_receipt",write)
    assert probe.run()["status"]=="uncertain"
    probe.stock.DefineTurnWorkpieceAsBarStock2.assert_not_called()


def test_native_return_is_durable_before_readback(probe):
    def verify_return():
        durable=json.loads(probe.receipt.read_text(encoding="utf-8"))
        assert durable["native_call_returned"] and durable["native_error_code"]==0
        return tuple(probe.target.values())
    probe.state["on_native"]=lambda:setattr(probe.stock.GetBarStockParameters,"side_effect",verify_return)
    assert probe.run()["stock_definition_verified"]


def test_existing_receipt_is_never_overwritten(probe):
    probe.receipt.write_text("historical",encoding="utf-8")
    with pytest.raises(FileExistsError):probe.run()
    assert probe.receipt.read_text()=="historical"
    probe.context.assert_not_called()


@pytest.mark.parametrize("key,value", [("odOff",True),("length","35"),("startZ",float("inf")),("attribute",0),
                                       ("attribute",True),("attribute",3)])
def test_new_raw_values_are_strict_finite_and_documented_attributes(probe,key,value):
    with pytest.raises(ValueError):probe.run(bar_parameters_native={**probe.target,key:value})
    probe.context.assert_not_called()


def test_native_bar_setter_error_enum_abi_is_integer_not_boolean():
    from ctypes import HRESULT,POINTER,c_double,c_int
    from comtypes import COMObject,COMMETHOD,GUID,IUnknown
    class Contract(IUnknown):
        _iid_=GUID("{0DBDE659-2FC1-4272-88BD-C299D9930303}")
        _methods_=[COMMETHOD([],HRESULT,"DefineTurnWorkpieceAsBarStock2",
            (["in"],c_double,"startZ"),(["in"],c_double,"length"),(["in"],c_double,"odOff"),
            (["in"],c_double,"idOff"),(["in"],c_int,"attribute"),(["out","retval"],POINTER(c_int),"error"))]
    class Server(COMObject):
        _com_interfaces_=[Contract]
        def DefineTurnWorkpieceAsBarStock2(self,startZ,length,odOff,idOff,attribute):
            assert (startZ,length,odOff,idOff,attribute)==(-33.,35.,75.,0.,1)
            return 0
    owner=Server();result=owner.QueryInterface(Contract).DefineTurnWorkpieceAsBarStock2(-33.,35.,75.,0.,1)
    assert type(result) is int and result==0


@pytest.mark.parametrize("changed", ["document","inventory","stock"])
def test_cleanup_state_change_invalidates_final_stock_verification(probe,changed):
    def change():
        if changed=="document":probe.document["path"]="C:/OTHER.SLDPRT"
        elif changed=="inventory":probe.inventory["operation_count"]=1
        else:probe.state["bar"]["odOff"]+=1.0
    probe.state["on_exit"]=change
    report=probe.run()
    assert report["status"]=="error" and report["reason"]=="CAM_STOCK_STATE_CHANGED_AFTER_EVENT_CLEANUP"
    assert report["stock_readback_before_cleanup_verified"] and not report["stock_definition_verified"]
    assert not report["may_continue"] and report["verification_scope"]=="after_event_cleanup"
    probe.stock.DefineTurnWorkpieceAsBarStock2.assert_called_once()


def test_cleanup_failure_does_not_attempt_postcleanup_cad_readback(probe):
    def change():
        probe.session.report["disconnect_errors"]=[{"type":"fixture_error"}]
        probe.stock.GetBarStockParameters.side_effect=AssertionError("No CAD after cleanup failure")
    probe.state["on_exit"]=change
    report=probe.run()
    assert report["status"]=="error" and not report["stock_definition_verified"]
    assert report["verification_scope"]=="pending_event_cleanup"
    assert "bar_parameters_after_cleanup" not in report
