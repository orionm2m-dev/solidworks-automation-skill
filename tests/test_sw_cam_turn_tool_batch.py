"""多字段刀片更新的状态绑定、逐项凭据与首错停止；不连接 CAD。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


from scripts import sw_cam_turn_tool_batch as cam


def ref(index, kind=2):
    return dict(setup_index=0, operation_index=index, expected_operation_type=kind)


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path = tmp_path / "working.sldprt"
    path.write_bytes(b"saved fixture")
    receipt = tmp_path / "batch.json"
    before = dict(document=dict(path=str(path), title=path.name, type=1, needs_save=False),
        inventory={"operations": [dict(setup_index=0, operation_index=i,
            turn_operation_type=2 if i < 2 else 1, toolpath_generated=i == 2) for i in range(3)]},
        selected_operation=ref(0), selected_tool_group=0, station_id="",
        station_tool_native_id=239, station_usage_operation_ids=[89,95],
        affected_operations=[ref(0),ref(1)],
        operation_tools=[dict(operation=ref(0),operation_native_id=89,tool_group=0,tool_native_id=239),
            dict(operation=ref(1),operation_native_id=95,tool_group=0,tool_native_id=239),
            dict(operation=ref(2,1),operation_native_id=99,tool_group=1,tool_native_id=240)],
        tool_groups=[dict(cam_object_id=239,tool_type_raw=15,insert_type_raw=1,
            dimensions_native=dict(NoseRadius=.8,Thickness=4.7625,InscribedCircle=12.7)),
            dict(cam_object_id=240,tool_type_raw=14,insert_type_raw=None,dimensions_native={})],
        linked_features=[dict(name="full contour",segments=[dict(start_native=[1.,2.,3.])])],
        selected_tool=dict(info_raw="native T03",insert_type_raw=1,
            dimensions_native=dict(NoseRadius=.8,Thickness=4.7625,InscribedCircle=12.7,IncludedAngle=55.),
            holder=dict(shape_raw=0,dimensions_native=dict(ShankWidth=16.))))
    state = dict(current=deepcopy(before),writes=[],on_write=None,on_snapshot=None,on_exit=None,
                 on_read=None,current_tool_id=239,operation_id=89,pid=624)
    class Session:
        def __init__(self):
            self.data = dict(subscribed=False,active=False,disconnected=False,event_count=0,
                             overflow=0,callback_errors=[],disconnect_errors=[])
        def __enter__(self):
            self.data.update(subscribed=True,active=True)
            return self
        def __exit__(self,*args):
            self.data.update(active=False,disconnected=True)
            if state["on_exit"]:state["on_exit"]()
        def summary(self):return deepcopy(self.data)
    sessions=[]
    def session_factory(*args):
        value=Session();sessions.append(value);return value
    class Tool:
        def __getattr__(self,name):
            assert sessions[-1].data["active"], "CAM getter after cleanup"
            if state["on_read"]:state["on_read"](name)
            return state["current"]["tool_groups"][0]["dimensions_native"][name]
        def __setattr__(self,name,value):
            assert sessions[-1].data["active"]
            durable=json.loads(receipt.read_text(encoding="utf-8"))
            step=durable["setters"][-1]
            assert durable["phase"]=="property_put" and step["field"]==name
            assert step["attempted"] and not step["returned"]
            state["writes"].append((name,value))
            if state["on_write"]:state["on_write"](name,value)
            state["current"]["tool_groups"][0]["dimensions_native"][name]=value
            state["current"]["selected_tool"]["dimensions_native"][name]=value
            state["current"]["selected_tool"]["info_raw"]="updated"
            state["current"]["document"]["needs_save"]=True
    tool=Tool()
    current_tool=object()
    operation=SimpleNamespace(IGetTool=lambda:current_tool)
    class Doc:
        def GetCWObjectID(self,obj):
            assert sessions[-1].data["active"]
            return (state["operation_id"] if obj is operation else state["current_tool_id"],True)
    native=dict(app=object(),turn_tool=tool,native_doc=Doc(),operation=operation,tool=tool)
    def snapshot(*args,**kwargs):
        assert kwargs["guarded_readers"] is True
        assert sessions[-1].data["active"]
        kwargs["check"]()
        if state["on_snapshot"]:state["on_snapshot"]()
        kwargs["check"]()
        return deepcopy(state["current"]),native
    snapshots=Mock(side_effect=snapshot)
    monkeypatch.setattr(cam.single,"_snapshot",snapshots)
    monkeypatch.setattr(cam,"document_snapshot",lambda *_:deepcopy(state["current"]["document"]))
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj)
    monkeypatch.setattr(cam,"_bootstrap",Mock(return_value=object()))
    monkeypatch.setattr(cam,"CamMessageSession",session_factory)
    sw=SimpleNamespace(GetProcessID=lambda:state["pid"])
    defaults=dict(process_id=624,expected_document_path=str(path),setup_index=0,operation_index=0,
        expected_operation_type=2,values_native=dict(NoseRadius=.1,InscribedCircle=9.525,Thickness=3.9688),
        qualification_only=True,message_policy="vendor_default")
    def digest(values=None):
        return cam.single._digest(dict(process_id=624,state=before,
            saved_file_sha256=hashlib.sha256(b"saved fixture").hexdigest(),
            values_native=cam._values(values or defaults["values_native"])))
    def prepare(**changes):
        return cam.configure_turn_tool_dimensions(sw,"clsid","verified.tlb",**(defaults|dict(action="prepare")|changes))
    def apply(**changes):
        args=dict(action="apply",expected_state_sha256=digest(),
                  allowed_affected_operations=[ref(0),ref(1)],receipt_path=str(receipt))
        return cam.configure_turn_tool_dimensions(sw,"clsid","verified.tlb",**(defaults|args|changes))
    return SimpleNamespace(**locals())


def test_prepare_binds_full_state_exact_recipe_file_and_pid_once_under_events(probe):
    result=probe.prepare()
    assert result["status"]=="ok" and result["apply_eligible"]
    assert result["state_sha256"]==probe.digest()
    assert result["changed_fields"]==["InscribedCircle","NoseRadius","Thickness"]
    assert result["affected_operations"]==[ref(0),ref(1)]
    assert result["messages"]["disconnected"] and not result["mutation_attempted"]
    assert probe.snapshots.call_count==1 and not probe.receipt.exists() and probe.state["writes"]==[]


def test_three_setters_have_durable_per_step_markers_and_one_full_readback(probe):
    result=probe.apply()
    assert result["status"]=="review_required" and result["readback_verified"]
    assert result["native_calls_returned_count"]==3 and result["scalar_readback_verified"]
    assert probe.state["writes"]==[("InscribedCircle",9.525),("NoseRadius",.1),("Thickness",3.9688)]
    assert all(x["attempted"] and x["returned"] and x["scalar_readback_verified"] for x in result["setters"])
    assert probe.snapshots.call_count==2
    assert result["after"]["tool_groups"][1]==probe.before["tool_groups"][1]
    assert result["after"]["selected_tool"]["holder"]==probe.before["selected_tool"]["holder"]
    assert not result["generation_attempted"] and not result["model_saved"] and not result["may_continue"]
    assert result["snapshot_scope"]=="full_CAM_state_before_event_disconnect"
    assert json.loads(probe.receipt.read_text(encoding="utf-8"))==result


def test_matching_dimensions_are_skipped_without_property_put(probe):
    values=dict(NoseRadius=.8,Thickness=3.9688,InscribedCircle=12.7)
    result=probe.apply(values_native=values,expected_state_sha256=probe.digest(values))
    assert result["readback_verified"] and result["unchanged_fields"]==["InscribedCircle","NoseRadius"]
    assert probe.state["writes"]==[("Thickness",3.9688)] and probe.snapshots.call_count==2


def test_entire_noop_writes_nothing_and_does_not_repeat_snapshot(probe):
    values=dict(NoseRadius=.8,Thickness=4.7625)
    result=probe.apply(values_native=values,expected_state_sha256=probe.digest(values))
    assert result["no_changes_required"] and result["readback_verified"]
    assert not result["mutation_attempted"] and result["setters"]==[]
    assert probe.snapshots.call_count==1 and probe.state["writes"]==[]


def test_second_native_failure_keeps_first_commit_and_stops_without_rollback(probe):
    def fail(field,value):
        if field=="NoseRadius":raise RuntimeError("native failure")
    probe.state["on_write"]=fail
    result=probe.apply()
    assert result["status"]=="uncertain" and not result["readback_verified"]
    assert probe.state["writes"]==[("InscribedCircle",9.525),("NoseRadius",.1)]
    assert result["setters"][0]["returned"] and not result["setters"][1]["returned"]
    assert result["native_calls_returned_count"]==1 and probe.snapshots.call_count==1
    assert probe.state["current"]["tool_groups"][0]["dimensions_native"]["InscribedCircle"]==9.525
    assert result["messages"]["disconnected"]
    with pytest.raises(ValueError):probe.apply()
    assert len(probe.state["writes"])==2


def test_failure_after_setter_return_publishes_returned_before_scalar_read(probe):
    def on_read(field):
        if probe.state["writes"]:
            durable=json.loads(probe.receipt.read_text(encoding="utf-8"))
            assert durable["setters"][0]["returned"]
            raise RuntimeError("readback unavailable")
    probe.state["on_read"]=on_read
    result=probe.apply()
    assert result["status"]=="uncertain" and len(probe.state["writes"])==1
    assert result["setters"][0]["returned"] and not result["setters"][0]["scalar_readback_verified"]


@pytest.mark.parametrize("change",["profile","holder","tool_id","operation_id","inventory","file","recipe"])
def test_stale_state_or_recipe_blocks_all_writes(probe,change):
    kwargs={}
    if change=="profile":probe.state["current"]["linked_features"][0]["name"]="new contour"
    elif change=="holder":probe.state["current"]["selected_tool"]["holder"]["shape_raw"]=3
    elif change=="tool_id":probe.state["current"]["station_tool_native_id"]=777
    elif change=="operation_id":probe.state["current"]["operation_tools"][0]["operation_native_id"]=777
    elif change=="inventory":probe.state["current"]["inventory"]["new"]=True
    elif change=="file":probe.path.write_bytes(b"changed")
    else:kwargs["values_native"]=dict(NoseRadius=.2)
    result=probe.apply(**kwargs)
    assert result["status"]=="error" and not result["mutation_attempted"] and probe.state["writes"]==[]


@pytest.mark.parametrize("allowed",[[ref(0)],[ref(0),ref(1),ref(2,1)]])
def test_exact_shared_reference_allowlist_required(probe,allowed):
    assert probe.apply(allowed_affected_operations=allowed)["status"]=="error"
    assert probe.state["writes"]==[]


def test_generated_shared_operation_blocks_but_unrelated_generated_is_preserved(probe):
    probe.state["current"]["inventory"]["operations"][1]["toolpath_generated"]=True
    prepared=probe.prepare()
    assert not prepared["apply_eligible"]
    result=probe.apply(expected_state_sha256=prepared["state_sha256"])
    assert result["status"]=="error" and probe.state["writes"]==[]


@pytest.mark.parametrize("which",["operation_id","current_tool_id"])
def test_native_identity_mismatch_immediately_before_put_blocks(probe,which):
    probe.state[which]=888
    result=probe.apply()
    assert result["status"]=="error" and not result["mutation_attempted"] and probe.state["writes"]==[]


def test_message_after_first_put_stops_remaining_setters_and_full_snapshot(probe):
    probe.state["on_write"]=lambda *_:probe.sessions[-1].data.update(event_count=1)
    result=probe.apply()
    assert result["status"]=="uncertain" and len(probe.state["writes"])==1
    assert result["setters"][0]["returned"] and probe.snapshots.call_count==1


def test_coupled_unrequested_dimension_change_rejected_in_full_readback(probe):
    probe.state["on_write"]=lambda *_:probe.state["current"]["selected_tool"]["dimensions_native"].update(IncludedAngle=35.)
    result=probe.apply()
    assert result["status"]=="uncertain" and not result["readback_verified"]
    assert probe.snapshots.call_count==2


def test_coupled_future_requested_field_stops_before_next_write(probe):
    probe.state["on_write"]=lambda *_:probe.state["current"]["tool_groups"][0]["dimensions_native"].update(NoseRadius=.3)
    result=probe.apply()
    assert result["status"]=="uncertain" and len(probe.state["writes"])==1


def test_receipt_failure_before_second_put_stops_at_first_field(probe,monkeypatch):
    real=cam._write_receipt
    def writer(path,report,**kw):
        if report["phase"]=="property_put" and len(report["setters"])==2:raise OSError("disk error")
        return real(path,report,**kw)
    monkeypatch.setattr(cam,"_write_receipt",writer)
    result=probe.apply()
    assert result["status"]=="uncertain" and len(probe.state["writes"])==1
    assert result["setters"][0]["returned"] and not result["setters"][1]["returned"]


def test_receipt_failure_after_return_prevents_next_native_call(probe,monkeypatch):
    real=cam._write_receipt
    def writer(path,report,**kw):
        if report["phase"]=="property_put_returned":raise OSError("disk error")
        return real(path,report,**kw)
    monkeypatch.setattr(cam,"_write_receipt",writer)
    result=probe.apply()
    assert result["status"]=="uncertain" and len(probe.state["writes"])==1
    assert result["setters"][0]["returned"]


@pytest.mark.parametrize("change",["file","document","disconnect","callback"])
def test_cleanup_failure_does_not_trigger_more_cam_reads_or_claim_success(probe,change):
    def on_exit():
        if change=="file":probe.path.write_bytes(b"unexpected save")
        elif change=="document":probe.state["current"]["document"]["path"]+=".changed"
        elif change=="disconnect":probe.sessions[-1].data["disconnected"]=False
        else:probe.sessions[-1].data["callback_errors"]=[{"type":"error"}]
    probe.state["on_exit"]=on_exit
    result=probe.apply()
    assert result["status"]=="uncertain" and not result["readback_verified"]
    assert probe.snapshots.call_count==2


@pytest.mark.parametrize("values",[{},[],{"HolderShape":1},{"IncludedAngle":35},
    {"NoseRadius":True},{"NoseRadius":".1"},{"NoseRadius":float("nan")},
    {"NoseRadius":float("inf")},{"NoseRadius":-1},{"Width":0},{"Thickness":0},{"InscribedCircle":0}])
def test_invalid_recipe_rejected_before_any_native_or_receipt(probe,values):
    with pytest.raises(ValueError):probe.prepare(values_native=values)
    probe.snapshots.assert_not_called();cam._bootstrap.assert_not_called()
    assert not probe.receipt.exists()


@pytest.mark.parametrize("case",["pid","dirty","wrong_doc","inapplicable","reused_receipt"])
def test_basic_guards(probe,case):
    kwargs={}
    if case=="pid":probe.state["pid"]=999
    elif case=="dirty":probe.state["current"]["document"]["needs_save"]=True
    elif case=="wrong_doc":probe.state["current"]["document"]["path"]+=".other"
    elif case=="inapplicable":kwargs["values_native"]={"Width":1.}
    else:
        probe.receipt.write_text("prior",encoding="utf-8")
        with pytest.raises(ValueError):probe.apply()
        assert probe.receipt.read_text()=="prior"
        return
    result=probe.apply(**kwargs)
    assert result["status"]=="error" and not result["mutation_attempted"] and probe.state["writes"]==[]


def test_duplicate_reference_different_type_rejected_before_read(probe):
    with pytest.raises(ValueError):probe.apply(allowed_affected_operations=[ref(0),ref(1),ref(1,4)])
    probe.snapshots.assert_not_called()


def test_event_during_initial_capture_stops_without_setter(probe):
    probe.state["on_snapshot"]=lambda:probe.sessions[-1].data.update(event_count=1)
    result=probe.prepare()
    assert result["status"]=="error" and probe.state["writes"]==[]
    assert result["messages"]["disconnected"]


def test_guarded_snapshot_routes_context_and_stops_on_its_first_event(monkeypatch):
    from scripts import sw_cam_turn_feature_attribute as guarded
    called=[]
    def check():
        if called:raise ValueError("event")
    def member(*args):called.append(args[1]);return object()
    def context(sw,clsid,typelib,read):
        read(object(),"first")
        read(object(),"must_not_run")
    monkeypatch.setattr(cam.single,"_member",member)
    monkeypatch.setattr(guarded,"_context",context)
    with pytest.raises(ValueError,match="event"):
        cam.single._snapshot(object(),"clsid","type",ref(0),check=check,guarded_readers=True)
    assert called==["first"]


@pytest.mark.parametrize("stage",["last_getter","attempt_receipt"])
@pytest.mark.parametrize("change",["document","file"])
def test_scope_race_after_scalar_reads_stops_before_native_put(probe,monkeypatch,stage,change):
    def alter():
        if change=="file":probe.path.write_bytes(b"changed at gate")
        else:probe.state["current"]["document"]["path"]+=".other"
    if stage=="last_getter":
        probe.state["on_read"]=lambda field:alter() if field=="Thickness" else None
    else:
        real=cam._write_receipt
        def writer(path,report,**kw):
            result=real(path,report,**kw)
            if report["phase"]=="property_put":alter()
            return result
        monkeypatch.setattr(cam,"_write_receipt",writer)
    result=probe.apply()
    assert not result["readback_verified"] and probe.state["writes"]==[]
    assert result["native_calls_returned_count"]==0


def test_guarded_snapshot_rejects_drill_before_insert_or_thickness(monkeypatch):
    from scripts import sw_cam_turn_feature_attribute as guarded
    calls=[]
    class Drill:
        ToolType=2
        def __getattr__(self,name):
            raise AssertionError("Unsupported drill getter: "+name)
    drill=Drill()
    generic=SimpleNamespace(ToolType=15)
    raw_tool=object()
    operation=SimpleNamespace(IGetTool=lambda:raw_tool,OpernType=9)
    setup=SimpleNamespace(IGetEnumOperations=lambda:[operation])
    machine=SimpleNamespace(IGetEnumOpSetups=lambda:[setup])
    native_doc=SimpleNamespace(GetCWObjectID=lambda obj:(10 if obj is operation else 20,True))
    monkeypatch.setattr(guarded,"_context",lambda *_:({},native_doc,None,machine,None))
    monkeypatch.setattr(guarded,"_inventory",lambda *_:{})
    monkeypatch.setattr(guarded,"_items",lambda raw,*args,**kwargs:raw)
    def typed(obj,name,*args):
        calls.append(name)
        if obj is raw_tool:return generic if name=="ICWTool" else drill
        return obj
    monkeypatch.setattr(cam.single,"_typed",typed)
    with pytest.raises(ValueError,match="selected tool must"):
        cam.single._snapshot(object(),"clsid","tlb",ref(0,9),guarded_readers=True)
    assert "ICWTurnTool" in calls
