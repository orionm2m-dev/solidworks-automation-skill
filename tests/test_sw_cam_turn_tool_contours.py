"""Both native-shaped contour captures for rough and finish; no CAM activation."""
from unittest.mock import Mock
import pytest
from test_sw_cam_turn_variable_allowance import env
from test_sw_cam_turn_bore_options import bore
from test_sw_cam_turn_bore_tool_contours import contours
from scripts import sw_cam_turn_variable_allowance as cam


@pytest.fixture(params=[5, 6])
def selected(contours, request, monkeypatch):
    e = contours
    e["operation"]["OpernType"] = request.param
    e["args"].update(expected_operation_type=request.param, expected_tool_native_id=322)
    e["run"] = lambda **kw: cam.inspect_turn_tool_contours(e["sw"], "clsid", "fixture.tlb", **dict(e["args"], **kw))
    e["rough_abi"] = Mock(side_effect=AssertionError("No rough-bore ABI in contour-only scope"))
    monkeypatch.setattr(cam, "_bore_options_abi", e["rough_abi"])
    return e


def test_two_complete_contours_without_rough_options_or_feature_profiles(selected):
    r = selected["run"]()
    assert r["status"] == "ok" and r["readback_verified"]
    assert r["before"] == r["after"] and r["inspection_scope"] == "tool_contours"
    assert r["before"]["selected_operation"]["turn_operation_type"] == selected["args"]["expected_operation_type"]
    assert r["before"]["tool_contours"]["complete"]
    assert "bore_options_native" not in r["before"] and "getter_abi" not in r
    assert r["before"]["linked_features"] == []
    assert selected["calls"].count("inventory") == 4
    for getter in (selected["insert_getter"], selected["holder_getter"], selected["orientation_getter"]):
        assert getter.call_count == 2
    assert all(call.args == () for call in selected["insert_getter"].call_args_list)
    for getter in (selected["holder_getter"], selected["orientation_getter"]):
        assert all(call.args == (selected["operation"],) and call.args[0] is selected["operation"] for call in getter.call_args_list)
    assert not set(selected["calls"]) & set(cam._BORE_BOOL) | set(selected["calls"]) & set(cam._BORE_NUMBER)
    assert not set(selected["calls"]) & {"profile", "IGetAllDefaultOperations", "GetTdbIdForDefaultOperation",
        "GetAllowanceMethodVariable", "GetAllVariableAllowances", "SetTool", "GenerateToolpath", "Save"}
    selected["rough_abi"].assert_not_called()
    assert not any(r[k] for k in ("mutation_attempted", "GOP_attempted", "GTP_attempted", "model_saved", "CL_read_attempted", "production_qualified"))
    assert not any(r["before"]["tool_contours"][k] for k in ("coordinate_frame_verified", "program_point_verified", "units_verified", "solid_geometry_verified", "physical_holder_verified"))
    assert r["messages"]["disconnected"] and not r["messages"]["active"]


@pytest.mark.parametrize("field,value", [
    ("process_id", True), ("expected_process_create_time", None), ("expected_process_create_time", True),
    ("expected_process_create_time", 0), ("expected_process_create_time", float("nan")),
    ("expected_operation_type", 1), ("expected_operation_type", 7), ("expected_operation_type", True),
    ("expected_operation_type", 6.), ("expected_operation_native_id", None),
    ("expected_tool_native_id", None), ("expected_tool_native_id", True),
    ("expected_tool_native_id", 322.), ("expected_tool_native_id", 0), ("expected_tool_native_id", 2**32),
    ("expected_source_sha256", "bad"), ("expected_linked_feature_ids", None),
    ("expected_linked_feature_ids", [True]), ("expected_linked_feature_ids", [11, 11]),
    ("action", "identify"), ("action", "apply"), ("message_policy", "auto_accept")])
def test_invalid_pin_or_scope_never_reaches_native(selected, field, value):
    r = selected["run"](**{field: value})
    assert r["status"] == "error" and not selected["calls"]


@pytest.mark.parametrize("owner,field,value", [("operation", "native_id", 999), ("operation", "OpernType", 1),
    ("feature", "native_id", 999), ("tool", "native_id", 999), ("turn", "InsertType", 2), ("holder", "GetHolderType", 1)])
def test_wrong_native_identity_or_geometry_category_stops_before_profiles(selected, owner, field, value):
    selected[owner][field] = value
    r = selected["run"]()
    assert r["status"] == "error" and not r["readback_verified"]
    selected["insert_getter"].assert_not_called()
    selected["holder_getter"].assert_not_called()


@pytest.mark.parametrize("getter", ["IGetTool", "GetToolOrientationForOperation", "GetToolProfile", "GetHolderProfile",
    "GetCurveAtIndex", "GetCoordinates", "CenterPoint", "IGetRadius", "IGetSense"])
def test_event_during_contour_stops_all_later_getters(selected, getter):
    def hook(name):
        if name == getter: selected["session"].state["event_count"] = 1
    selected["hook"] = hook
    r = selected["run"]()
    assert r["status"] == "error" and not r["readback_verified"]
    assert selected["calls"][-1] == getter and selected["calls"].count(getter) == 1
    assert "after" not in r and r["messages"]["disconnected"]


@pytest.mark.parametrize("drift", ["tool", "orientation", "insert", "holder"])
def test_second_complete_capture_detects_contour_drift(selected, drift):
    def hook(name):
        if name == "GetHolderProfile" and selected["calls"].count(name) == 1:
            if drift == "tool": selected["tool"]["native_id"] = 999
            elif drift == "orientation": selected["holder"]["GetToolOrientationForOperation"] = 4
            elif drift == "insert": selected["insert_curves"][1]["IGetRadius"] = 2.
            else: selected["holder_curves"][1]["IGetRadius"] = lambda: 1. if selected["calls"].count("GetHolderProfile") == 1 else 2.
    selected["hook"] = hook
    r = selected["run"]()
    assert r["status"] == "error" and not r["readback_verified"]
    assert r["before"]["capture_complete"] and "after" in r


@pytest.mark.parametrize("drift", ["inventory", "source", "process", "dirty"])
def test_capture_boundary_rechecks_identity_source_inventory(selected, drift):
    def hook(name):
        if name == "GetHolderProfile":
            if drift == "inventory": selected["inventory"]["operation_count"] += 1
            elif drift == "source": selected["digest"] = "b"*64
            elif drift == "process": selected["process"]["create_time"] += 1
            else: selected["dirty"] = True
    selected["hook"] = hook
    r = selected["run"]()
    assert r["status"] == "error" and "after" not in r
    assert not r["before"]["capture_complete"]


def test_abi_mismatch_stops_before_application_access(selected, monkeypatch):
    validator = Mock(side_effect=ValueError("Contour signature changed"))
    monkeypatch.setattr(cam, "_tool_contour_abi", validator)
    r = selected["run"]()
    assert r["status"] == "error" and not selected["calls"]
    validator.assert_called_once()


def test_source_drift_after_disconnect_is_not_accepted(selected, monkeypatch):
    exit_session = selected["Session"].__exit__
    def changed(self, *args):
        exit_session(self, *args)
        selected["digest"] = "b"*64
    monkeypatch.setattr(selected["Session"], "__exit__", changed)
    r = selected["run"]()
    assert r["status"] == "error" and not r["readback_verified"]
    assert r["before"]["capture_complete"] and r["after"]["capture_complete"]


def test_internal_contour_scope_cannot_disable_contours(selected):
    r = cam._inspect_turn_operation_parameters(selected["sw"], "clsid", "fixture.tlb",
        **dict(selected["args"], expected_tool_native_id=None), inspection_scope="tool_contours")
    assert r["status"] == "error" and not selected["calls"]
