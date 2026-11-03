"""Bounded own-tool contours share the existing bore identity/event captures."""
from ctypes import HRESULT, POINTER, c_int
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_sw_cam_turn_variable_allowance import env
from test_sw_cam_turn_bore_options import bore
from scripts import sw_cam_turn_variable_allowance as cam
from scripts import sw_cam_qualification_context as decoder
from scripts import sw_cam_operation_profile as profiles
from scripts import sw_cam_comtypes as bridge


@pytest.fixture
def contours(bore, monkeypatch):
    def position(x, y, z):
        return {"GetCoordinates": (x, y, z)}
    def chain(x):
        line = {"GetTypeOfCurve": 0, "GetStart": lambda: position(x, 0., 0.),
                "GetEnd": lambda: position(x, 0., 2.)}
        arc = {"GetTypeOfCurve": 1, "GetStart": lambda: position(x, 0., 2.),
               "GetEnd": lambda: position(x+1., 0., 3.), "GetMid": lambda: position(x+.3, 0., 2.7),
               "CenterPoint": lambda: position(x+1., 0., 2.), "IGetRadius": 1., "IGetSense": -1}
        curves = [line, arc]
        def at_index(pointer):
            # The decoder must pass the native integer pointer, never a Python index.
            index = __import__("ctypes").cast(pointer, POINTER(c_int)).contents.value
            return curves[index]
        result = {"IGetNumChains": 1, "GetNumOfCurves": 2,
                  "GetCurveAtIndex": at_index, "IGetNextChain": None}
        return result, curves
    insert_chain, insert_curves = chain(1.)
    holder_chain, holder_curves = chain(10.)
    holder_getter = Mock(return_value=holder_chain)
    orientation_getter = Mock(return_value=3)
    insert_getter = Mock(return_value=insert_chain)
    holder = {"GetHolderType": 2, "GetHolderId": 7,
              "GetToolOrientationForOperation": orientation_getter,
              "XInsertOffset": .4, "ZInsertOffset": -.4, "GetHolderProfile": holder_getter}
    turn = {"ToolType": 1, "InsertType": 1, "IncludedAngle": 80., "NoseRadius": .4,
            "InscribedCircle": 9.525, "Thickness": 3.97, "IGetTurnToolHolder": lambda: holder}
    tool = {"native_id": 322, "ToolType": 15, "GetToolProfile": insert_getter}
    raw_tool = {"_types": {"ICWTool": tool, "ICWTurnTool": turn}}
    bore["operation"]["IGetTool"] = lambda: raw_tool
    def typed(raw, name, path):
        return raw.get("_types", {}).get(name, raw)
    for module in (cam, decoder, profiles):
        monkeypatch.setattr(module, "_typed", typed)
    monkeypatch.setattr(cam, "_tool_contour_abi", lambda path: {"native_calls": 0})
    run = bore["run"]
    bore.update(tool=tool, turn=turn, holder=holder, insert_chain=insert_chain,
                holder_chain=holder_chain, insert_curves=insert_curves, holder_curves=holder_curves,
                insert_getter=insert_getter, holder_getter=holder_getter,
                orientation_getter=orientation_getter)
    bore["run"] = lambda **kw: run(**dict(include_tool_contours=True, expected_tool_native_id=322, **kw))
    return bore


def test_two_exact_profiles_and_operation_arguments_in_each_capture(contours):
    result = contours["run"]()
    assert result["status"] == "ok" and result["readback_verified"]
    assert result["before"] == result["after"]
    assert result["tool_readers_used"] and result["tool_contours_requested"]
    data = result["before"]["tool_contours"]
    assert data["complete"] and data["tool_native_id"] == 322
    assert data["orientation_for_operation_raw"] == 3
    for label, first in (("insert_profile", 1.), ("holder_profile", 10.)):
        profile = data[label]
        assert profile["available"] and profile["parameters_complete"]
        assert profile["chain_count"] == 1 and profile["curve_count"] == 2
        assert profile["chains"][0]["curves"][0]["start_native"] == [first, 0., 0.]
        assert profile["chains"][0]["curves"][1]["radius_native"] == 1.
    assert contours["insert_getter"].call_count == 2
    assert all(call.args == () and not call.kwargs for call in contours["insert_getter"].call_args_list)
    for getter in (contours["holder_getter"], contours["orientation_getter"]):
        assert getter.call_count == 2
        assert all(call.args == (contours["operation"],) for call in getter.call_args_list)
        assert all(call.args[0] is contours["operation"] for call in getter.call_args_list)
    assert contours["calls"].count("inventory") == 4
    assert contours["calls"].count("IGetTool") == 2
    assert not set(contours["calls"]) & {"profile", "IGetAllDefaultOperations", "GetTdbIdForDefaultOperation",
        "GetToolProfileInDownLeftOrientation", "GetAllVariableAllowances", "SetTool", "GenerateToolpath", "Save"}
    assert not any(data[name] for name in ("coordinate_frame_verified", "program_point_verified", "units_verified",
        "solid_geometry_verified", "physical_holder_verified"))
    assert not any(result[name] for name in ("mutation_attempted", "GTP_attempted", "GOP_attempted", "model_saved",
        "production_qualified", "tool_geometry_verified", "CL_read_attempted"))
    assert result["messages"]["disconnected"] and not result["messages"]["active"]


@pytest.mark.parametrize("options", [
    {"include_tool_contours": 1}, {"include_tool_contours": "true"},
    {"include_tool_contours": True}, {"include_tool_contours": True, "expected_tool_native_id": True},
    {"include_tool_contours": True, "expected_tool_native_id": 0},
    {"include_tool_contours": True, "expected_tool_native_id": 2**32},
    {"include_tool_contours": True, "expected_tool_native_id": 322.},
    {"expected_tool_native_id": 322}])
def test_invalid_contour_request_precedes_native_calls(bore, options):
    result = bore["run"](**options)
    assert result["status"] == "error" and not bore["calls"]


@pytest.mark.parametrize("owner,field,value", [
    ("tool", "native_id", 323), ("tool", "ToolType", 2), ("tool", "ToolType", True),
    ("turn", "ToolType", 2), ("turn", "InsertType", 4), ("turn", "InsertType", True),
    ("turn", "IncludedAngle", float("nan")), ("turn", "NoseRadius", True),
    ("holder", "GetHolderType", 1), ("holder", "GetHolderId", -1),
    ("holder", "GetToolOrientationForOperation", True), ("holder", "XInsertOffset", float("inf"))])
def test_wrong_tool_or_invalid_scalar_stops_before_profiles(contours, owner, field, value):
    contours[owner][field] = value
    result = contours["run"]()
    assert result["status"] == "error" and not result["readback_verified"]
    contours["insert_getter"].assert_not_called()
    contours["holder_getter"].assert_not_called()
    assert contours["calls"][-1] == field
    assert result["before"]["tool_contours"]["complete"] is False


@pytest.mark.parametrize("getter", ["IGetTool", "IGetTurnToolHolder", "GetHolderType", "GetHolderId",
    "GetToolOrientationForOperation", "IncludedAngle", "XInsertOffset", "GetToolProfile", "GetHolderProfile",
    "IGetNumChains", "GetNumOfCurves", "GetCurveAtIndex", "GetTypeOfCurve", "GetStart", "GetCoordinates",
    "GetEnd", "GetMid", "CenterPoint", "IGetRadius", "IGetSense"])
def test_any_contour_event_stops_at_the_triggering_getter(contours, getter):
    def hook(name):
        if name == getter:
            contours["session"].state["event_count"] = 1
    contours["hook"] = hook
    result = contours["run"]()
    assert result["status"] == "error" and contours["calls"][-1] == getter
    assert contours["calls"].count(getter) == 1
    assert not result["readback_verified"] and result["messages"]["disconnected"]
    assert "after" not in result


@pytest.mark.parametrize("owner,field", [("operation", "IGetTool"), ("turn", "IGetTurnToolHolder"),
    ("tool", "GetToolProfile"), ("holder", "GetHolderProfile")])
def test_null_tool_holder_or_profile_fails_without_retry(contours, owner, field):
    contours[owner][field] = None
    result = contours["run"]()
    assert result["status"] == "error" and contours["calls"][-1] == field
    assert contours["calls"].count(field) == 1 and "after" not in result
    assert not result["before"]["tool_contours"]["complete"]


@pytest.mark.parametrize("owner,field", [("tool", "GetToolProfile"), ("holder", "GetHolderProfile")])
def test_native_contour_failure_preserves_scalars_and_stops(contours, owner, field):
    def fail(*args):
        raise OSError("native contour getter failed")
    contours[owner][field] = fail
    result = contours["run"]()
    assert result["status"] == "error" and contours["calls"][-1] == field
    assert result["before"]["bore_options_native"]["MaxCutAmt"] == 3.
    assert result["before"]["tool_contours"]["insert_dimensions_native"]["NoseRadius"] == .4
    if field == "GetHolderProfile":
        assert result["before"]["tool_contours"]["insert_profile"]["parameters_complete"]
    assert "after" not in result


@pytest.mark.parametrize("change", ["inventory", "source", "dirty", "process"])
def test_contour_capture_boundary_still_enforces_all_guards(contours, change):
    def hook(name):
        if name == "GetHolderProfile":
            if change == "inventory": contours["inventory"]["operation_count"] = 2
            elif change == "source": contours["digest"] = "b"*64
            elif change == "dirty": contours["dirty"] = True
            else: contours["process"]["create_time"] += 1
    contours["hook"] = hook
    result = contours["run"]()
    assert result["status"] == "error" and "after" not in result
    assert contours["calls"].count("GetToolProfile") == 1
    assert not result["before"]["capture_complete"]


@pytest.mark.parametrize("change", ["tool_id", "orientation", "insert", "holder"])
def test_changed_tool_or_contour_between_captures_is_rejected(contours, change):
    def hook(name):
        if name == "GetHolderProfile" and contours["calls"].count(name) == 1:
            if change == "tool_id": contours["tool"]["native_id"] = 323
            elif change == "orientation": contours["holder"]["GetToolOrientationForOperation"] = 4
            elif change == "insert": contours["insert_curves"][1]["IGetRadius"] = 1.1
            else: contours["holder_curves"][1]["IGetRadius"] = lambda: 1. if contours["calls"].count("GetHolderProfile") == 1 else 1.1
    contours["hook"] = hook
    result = contours["run"]()
    assert result["status"] == "error" and not result["readback_verified"]
    assert result["before"]["capture_complete"] and "after" in result


@pytest.mark.parametrize("profile", ["insert", "holder"])
@pytest.mark.parametrize("fault", ["zero_chains", "too_many_chains", "zero_curves", "too_many_curves", "unknown_curve", "nan_coordinate", "missing_next"])
def test_bounded_shared_decoder_rejects_incomplete_contours(contours, profile, fault):
    chain = contours[profile + "_chain"]
    curve = contours[profile + "_curves"][0]
    if fault == "zero_chains": chain["IGetNumChains"] = 0
    elif fault == "too_many_chains": chain["IGetNumChains"] = 33
    elif fault == "zero_curves": chain["GetNumOfCurves"] = 0
    elif fault == "too_many_curves": chain["GetNumOfCurves"] = 513
    elif fault == "unknown_curve": curve["GetTypeOfCurve"] = 3
    elif fault == "nan_coordinate": curve["GetStart"] = lambda: {"GetCoordinates": (float("nan"), 0., 0.)}
    else: chain["IGetNumChains"] = 2
    result = contours["run"]()
    assert result["status"] == "error" and not result["readback_verified"]
    assert not result["before"]["tool_contours"]["complete"] and "after" not in result
    if profile == "insert": contours["holder_getter"].assert_not_called()


def abi_interfaces():
    from comtypes.automation import IDispatch
    dispatch = POINTER(IDispatch)
    def method(name, dispid, args, flags):
        return SimpleNamespace(name=name, restype=HRESULT, idlflags=(dispid,),
            argtypes=args, paramflags=tuple((flag, "value") for flag in flags))
    return {"ICWTool": SimpleNamespace(_iid_=bridge._INTERFACES["ICWTool"], _methods_=[
        method("GetToolProfile", 12, (POINTER(dispatch),), (10,))]),
        "ICWTurnToolHolder": SimpleNamespace(_iid_=bridge._INTERFACES["ICWTurnToolHolder"], _methods_=[
        method("GetHolderProfile", 1, (dispatch, POINTER(dispatch)), (1, 10)),
        method("GetToolOrientationForOperation", 7, (dispatch, POINTER(c_int)), (1, 10))])}


def test_exact_contour_iids_and_metadata_only_abi(monkeypatch):
    interfaces = abi_interfaces()
    monkeypatch.setattr(bridge, "_load_type_library", lambda path: SimpleNamespace(**interfaces))
    result = cam._tool_contour_abi("fixture")
    assert result["native_calls"] == 0 and len(result["methods"]) == 3
    interfaces["ICWTool"]._iid_ = "{00000000-0000-0000-0000-000000000000}"
    with pytest.raises(ValueError): cam._tool_contour_abi("fixture")


@pytest.mark.parametrize("owner,index", [("ICWTool", 0), ("ICWTurnToolHolder", 0), ("ICWTurnToolHolder", 1)])
@pytest.mark.parametrize("fault", ["missing", "duplicate", "argument", "flags", "dispid", "return_type"])
def test_changed_contour_abi_is_rejected(monkeypatch, owner, index, fault):
    interfaces = abi_interfaces()
    interface = interfaces[owner]
    method = interface._methods_[index]
    if fault == "missing": interface._methods_.pop(index)
    elif fault == "duplicate": interface._methods_.append(method)
    elif fault == "argument": method.argtypes = (c_int,)
    elif fault == "flags": method.paramflags = ((1, "value"),)
    elif fault == "dispid": method.idlflags = (999,)
    else: method.restype = c_int
    monkeypatch.setattr(cam, "_interface_class", lambda name, path: interfaces[name])
    with pytest.raises(ValueError): cam._tool_contour_abi("fixture")



def test_contour_abi_failure_precedes_process_or_cam_access(bore, monkeypatch):
    validator = Mock(side_effect=ValueError("changed native contour contract"))
    monkeypatch.setattr(cam, "_tool_contour_abi", validator)
    result = bore["run"](include_tool_contours=True, expected_tool_native_id=322)
    assert result["status"] == "error" and not bore["calls"]
    validator.assert_called_once()


def test_default_scalar_read_does_not_check_contour_abi(bore, monkeypatch):
    validator = Mock(side_effect=AssertionError("optional metadata must stay unused"))
    monkeypatch.setattr(cam, "_tool_contour_abi", validator)
    result = bore["run"]()
    assert result["status"] == "ok" and not result["tool_readers_used"]
    assert "tool_contours" not in result["before"]
    validator.assert_not_called()
