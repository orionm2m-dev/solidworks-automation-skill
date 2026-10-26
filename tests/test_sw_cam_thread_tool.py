"""THREAD12 真实 getter 包装：精确 ID、事件、可调用 COM 属性和失败保留。"""
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_sw_cam_thread_records import probe as records_probe
from scripts import sw_cam_thread_tool as cam
from scripts import sw_cam_operation_profile as profile

@pytest.fixture
def probe(records_probe,monkeypatch):
    p=records_probe
    feature=N(native_id=382)
    p.operation.IGetAllFeatures=Mock(return_value=[feature])
    holder=N(GetHolderType=Mock(return_value=1),GetHolderId=Mock(return_value=10),
        GetToolOrientationForOperation=Mock(return_value=4),HolderShape=0,
        GetHolderThickness=Mock(return_value=12.),ShankLength=100.,LeadAngle=0.,BackClearAngle=0.,
        FrontClearAngle=0.,ZInsertOffset=0.,XInsertOffset=0.,Protrusion=20.,ShankWidth=12.,
        GetHolderProfile=Mock(return_value=object()))
    class CallableTool:
        def __init__(self):
            self._dispobj_=object();self.native_id=888;self.ToolType=1;self.InsertType=3
            self.Thickness=3.;self.Width=2.;self.length=10.;self.IncludedAngle=60.;self.NoseRadius=.1
            self.IGetTurnToolHolder=Mock(return_value=holder)
        def __call__(self):raise AssertionError("COM default DISPID0 must not be invoked")
    tool=CallableTool()
    generic=N(native_id=888,ToolType=15,GetToolInfoString=Mock(return_value="Native Thread tool"))
    p.operation.IGetTool=tool
    def typed(obj,name,*_):
        if obj is tool and name=="ICWTool":return generic
        return obj
    monkeypatch.setattr(cam,"_typed",typed);monkeypatch.setattr(profile,"_typed",typed)
    monkeypatch.setattr(cam,"_context",p.context);monkeypatch.setattr(cam,"_items",p.items)
    monkeypatch.setattr(cam,"_inventory",p.inv)
    monkeypatch.setattr(cam,"document_snapshot",lambda *_:deepcopy(p.document))
    def read_profile(raw,path,read,budget,result,collection_reader):
        assert p.session.data["active"]
        result.update(native_feature_id=raw.native_id,segment_count=1,segments=[dict(curve_type_raw=0)])
        assert collection_reader([],10)==[]
    def holder_profile(raw,op,path,choice,read,result):
        assert p.session.data["active"] and choice=="operation" and op is p.operation
        read(raw,"GetHolderProfile",op)
        result.update(available=True,chain_count=1,curve_count=7,parameters_complete=True)
    monkeypatch.setattr(cam,"_read_profile",read_profile)
    monkeypatch.setattr(cam,"_holder_profile",holder_profile)
    def call(**changes):
        args=dict(process_id=26552,expected_document_path=str(p.path),setup_index=0,operation_index=0,
            expected_operation_native_id=474,expected_feature_native_id=382,holder_profile="operation")
        return cam.inspect_thread_tool(p.sw,"clsid","registered/camworks.tlb",**(args|changes))
    return N(parent=p,tool=tool,generic=generic,holder=holder,feature=feature,call=call)


def test_type12_reads_thread_insert_fields_holder_and_callable_property_once(probe):
    result=probe.call()
    assert result["status"]=="ok" and result["readback_verified"]
    assert result["selected_operation"]["native_id"]==474 and result["linked_feature_ids"]==[382]
    assert result["tool"]["native_id"]==888 and result["tool"]["insert_type_raw"]==3
    dims=result["tool"]["dimensions_native"]
    assert dims==dict(Thickness=3.,Width=2.,length=10.,IncludedAngle=60.,NoseRadius=.1)
    assert result["holder_profile"]["curve_count"]==7
    assert result["tool"]["holder"]["orientation_for_operation_raw"]==4
    assert result["messages"]["disconnected"] and not result["post_cleanup_cam_read_performed"]
    assert not result["units_verified"] and not result["holder_fit_verified"]
    for method in probe.parent.forbidden:method.assert_not_called()


def test_explicit_no_holder_outline_does_not_call_profile_api(probe):
    assert probe.call(holder_profile="none")["status"]=="ok"
    probe.holder.GetHolderProfile.assert_not_called()


@pytest.mark.parametrize("field,value",[("process_id",True),("setup_index",1.0),("expected_operation_native_id",0),
    ("expected_feature_native_id",False),("holder_profile","down_left"),("message_policy","accept")])
def test_bad_inputs_stop_before_cam_bootstrap(probe,field,value):
    assert probe.call(**{field:value})["status"]=="error"
    probe.parent.sw.GetAddInObject.assert_not_called()


@pytest.mark.parametrize("change",["operation_id","feature_id","type","tool_type"])
def test_wrong_native_identity_or_type_does_not_read_tool_dimensions(probe,change):
    if change=="operation_id":result=probe.call(expected_operation_native_id=475)
    elif change=="feature_id":result=probe.call(expected_feature_native_id=383)
    elif change=="type":
        probe.parent.inventory["operations"][0]["turn_operation_type"]=3;result=probe.call()
    else:probe.generic.ToolType=1;result=probe.call()
    assert result["status"]=="error"
    probe.tool.IGetTurnToolHolder.assert_not_called()


def test_gettool_exception_is_not_claimed_as_absence_and_partial_feature_is_retained(probe):
    probe.parent.operation.IGetTool=Mock(side_effect=RuntimeError("Native tool unavailable"))
    result=probe.call()
    assert result["status"]=="error" and result["failed_phase"]=="IGetTool"
    assert result["linked_features"][0]["native_feature_id"]==382
    assert "present" not in result["tool"] and not result.get("tool_presence_verified",False)
    probe.parent.operation.IGetTool.assert_called_once_with()


def test_native_null_tool_is_recorded_without_fabricated_dimensions(probe):
    probe.parent.operation.IGetTool=None
    result=probe.call()
    assert result["status"]=="review_required" and result["tool"]=={"present":False}
    assert result["tool_presence_verified"]
    probe.holder.GetHolderProfile.assert_not_called()


@pytest.mark.parametrize("when",["enter","tool","exit"])
def test_event_stops_next_getter_and_no_getters_after_disconnect(probe,when):
    p=probe.parent
    def event():p.session.data["event_count"]=1
    if when=="tool":
        def tool_read():event();return probe.tool
        p.operation.IGetTool=Mock(side_effect=tool_read)
    else:p.state["on_"+when]=event
    result=probe.call();assert result["status"]=="error" and not result["readback_verified"]
    if when in {"enter","tool"}:probe.generic.GetToolInfoString.assert_not_called()
    assert result["messages"]["disconnected"]


def test_changed_file_during_outline_is_detected(probe):
    def change(*_):probe.parent.path.write_bytes(b"changed");return object()
    probe.holder.GetHolderProfile.side_effect=change
    result=probe.call();assert result["status"]=="error" and not result["readback_verified"]
