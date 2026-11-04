"""CutOff 槽刀与夹持器两次读取、边界、事件和禁止副作用测试；不连接 CAD。"""
from unittest.mock import Mock
import pytest
from test_sw_cam_turn_variable_allowance import env
from test_sw_cam_turn_bore_options import bore
from test_sw_cam_turn_bore_tool_contours import contours as bore_contours
from scripts import sw_cam_turn_variable_allowance as cam
from test_sw_cam_turn_tool_contours import (
    test_two_complete_contours_without_rough_options_or_feature_profiles,
    test_invalid_pin_or_scope_never_reaches_native,
    test_event_during_contour_stops_all_later_getters,
    test_capture_boundary_rechecks_identity_source_inventory,
    test_abi_mismatch_stops_before_application_access,
    test_source_drift_after_disconnect_is_not_accepted,
    test_internal_contour_scope_cannot_disable_contours)
from test_sw_cam_turn_bore_tool_contours import (
    test_bounded_shared_decoder_rejects_incomplete_contours,
    test_null_tool_holder_or_profile_fails_without_retry)

@pytest.fixture
def contours(bore_contours, monkeypatch):
    e=bore_contours
    e["operation"].update(OpernType=13,native_id=135)
    e["feature"]["native_id"]=78
    e["tool"]["native_id"]=141
    e["turn"].update(InsertType=2,Width=3.,length=12.7,Thickness=2.5,Radius1=.2,Radius2=.2)
    for key in ("IncludedAngle","NoseRadius","InscribedCircle"): del e["turn"][key]
    e["holder"].update(GetHolderType=1,GetHolderId=8,HolderShape=0,GetHolderThickness=26.,
        ShankLength=100.,ShankWidth=3.,Protrusion=9.52,LeadAngle=0.,BackClearAngle=0.,
        FrontClearAngle=0.,XInsertOffset=0.,ZInsertOffset=0.)
    e["orientation_getter"].return_value=4
    e["args"].update(expected_operation_type=13,expected_operation_native_id=135,
        expected_tool_native_id=141,expected_linked_feature_ids=[78])
    e["run"]=lambda **kw:cam.inspect_turn_tool_contours(e["sw"],"clsid","fixture.tlb",**dict(e["args"],**kw))
    e["rough_abi"]=Mock(side_effect=AssertionError("CutOff must not access bore option ABI"))
    monkeypatch.setattr(cam,"_bore_options_abi",e["rough_abi"])
    return e

@pytest.fixture
def selected(contours): return contours

def test_actual_groove_scalar_family_and_shank_dimensions_only(contours):
    r=contours["run"]();data=r["before"]["tool_contours"]
    assert r["readback_verified"] and data["tool_native_id"]==141
    assert data["insert_type_raw"]==2 and data["holder_type_raw"]==1
    assert data["orientation_for_operation_raw"]==4 and data["holder_shape_raw"]==0
    assert data["insert_dimensions_native"]==dict(Thickness=2.5,Width=3.,length=12.7,Radius1=.2,Radius2=.2)
    assert data["holder_dimensions_native"]["GetHolderThickness"]==26.
    assert data["holder_dimensions_native"]["ShankLength"]==100.
    assert data["insert_offsets_native"]==dict(XInsertOffset=0.,ZInsertOffset=0.)
    assert not set(contours["calls"]) & {"IncludedAngle","NoseRadius","InscribedCircle","BoringBarDiameter","GetToolProfileInDownLeftOrientation"}
    assert "Groove" in r["contour_scope"]

@pytest.mark.parametrize("owner,field,value",[("operation","native_id",999),("operation","OpernType",6),
    ("feature","native_id",999),("tool","native_id",9),("tool","ToolType",1),
    ("turn","ToolType",2),("turn","InsertType",1),("holder","GetHolderType",2),
    ("holder","GetHolderId",-1),("holder","HolderShape",True),
    ("turn","Width",True),("turn","length",float("nan")),("turn","Radius1",float("inf")),
    ("holder","GetHolderThickness",True),("holder","ShankLength",float("nan"))])
def test_exact_category_identity_and_scalar_fail_before_profiles(contours,owner,field,value):
    contours[owner][field]=value;r=contours["run"]()
    assert r["status"]=="error" and not r["readback_verified"]
    contours["insert_getter"].assert_not_called();contours["holder_getter"].assert_not_called()

@pytest.mark.parametrize("getter",["Width","length","Radius1","Radius2","HolderShape","GetHolderThickness","ShankLength","ShankWidth","Protrusion"])
def test_cutoff_specific_event_stops_at_that_getter(contours,getter):
    def hook(name):
        if name==getter:contours["session"].state["event_count"]=1
    contours["hook"]=hook;r=contours["run"]()
    assert r["status"]=="error" and contours["calls"][-1]==getter
    assert contours["calls"].count(getter)==1 and "after" not in r
    contours["insert_getter"].assert_not_called();contours["holder_getter"].assert_not_called()

@pytest.mark.parametrize("drift",["tool","orientation","insert","holder","width","thickness","shape"])
def test_second_cutoff_capture_detects_drift(contours,drift):
    def hook(name):
        if name=="GetHolderProfile" and contours["calls"].count(name)==1:
            if drift=="tool":contours["tool"]["native_id"]=142
            elif drift=="orientation":contours["holder"]["GetToolOrientationForOperation"]=5
            elif drift=="insert":contours["insert_curves"][1]["IGetRadius"]=2.
            elif drift=="holder":contours["holder_curves"][1]["IGetRadius"]=lambda:1. if contours["calls"].count("GetHolderProfile")==1 else 2.
            elif drift=="width":contours["turn"]["Width"]=4.
            elif drift=="thickness":contours["holder"]["GetHolderThickness"]=27.
            else:contours["holder"]["HolderShape"]=1
    contours["hook"]=hook;r=contours["run"]()
    assert r["status"]=="error" and not r["readback_verified"]
    assert r["before"]["capture_complete"] and "after" in r

def test_groove_contour_scope_does_not_extend_bore_options(contours):
    r=cam.inspect_turn_bore_options(contours["sw"],"clsid","fixture.tlb",**contours["args"],include_tool_contours=True)
    assert r["status"]=="error" and not contours["calls"]

@pytest.mark.parametrize("owner,field",[("tool","GetToolProfile"),("holder","GetHolderProfile")])
def test_native_cutoff_contour_failure_preserves_scalars_and_stops(contours,owner,field):
    def fail(*args):raise OSError("native contour getter failed")
    contours[owner][field]=fail;r=contours["run"]()
    assert r["status"]=="error" and contours["calls"][-1]==field
    data=r["before"]["tool_contours"]
    assert data["insert_dimensions_native"]["Width"]==3.
    assert data["holder_dimensions_native"]["GetHolderThickness"]==26.
    assert not data["complete"] and "after" not in r and "bore_options_native" not in r["before"]
    if owner=="holder":assert data["insert_profile"]["parameters_complete"]
    assert contours["calls"].count(field)==1 and r["messages"]["disconnected"]
