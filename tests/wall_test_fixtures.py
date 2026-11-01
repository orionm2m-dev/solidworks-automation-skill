"""Small synthetic wall receipts; no local project files or CAD application.

Reuse the checked-in finish parameter sample. State, action history and captures
are constructed here; this data is never a native or manufacturing result.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path

_BASE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wall_unit_baseline", _BASE / "test_sw_cam_pocket_wall_continue.py")
_unit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_unit)


def failed_wall_receipt():
    wall = _unit.m
    loaded = _unit.baseline()
    old_tool_id = loaded["neck_tool_candidate"]["native_id"]
    loaded["neck_tool_candidate"]["native_id"] = 273
    for item in loaded["neck_tool_checkpoint"]["catalogue"]:
        if item["native_id"] == old_tool_id:
            item["native_id"] = 273
    state = loaded["state"]
    state["current_machine"] = {"machine_type": 1}
    state["selected_profile_headers"] = {
        "native_id": 79, "representation": "ICWProfileFeature metadata"
    }
    state["operations"][-1].update(
        assigned_tool=wall.original.wanted_assignment(loaded),
        mill_operation_type=1, base_operation_type=0,
    )
    loaded["pocket_parameters"]["144"]["finish"]["PerimeterPassType"] = 1
    configured = _unit.capture(loaded, configured=True)
    actions = {}
    for spec in wall.FIELDS:
        actions["field:" + spec[0]] = dict(
            attempted=True, returned=True, pending=False,
            native_return_type="int", native_return_value=0,
            readback_verified=True, observed=deepcopy(spec[6]),
        )
    actions["GenerateToolpath"] = dict(
        attempted=True, returned=True, pending=False,
        native_return_type="int", native_return_value=0,
        readback_verified=False,
    )
    return dict(
        scope=wall.SCOPE, status="uncertain", failed_phase="GenerateToolpath",
        phase="finished", model_saved=False,
        configuration_readback_verified=True, initial_full_capture_verified=True,
        actions=actions, loaded_context_before=loaded,
        initial=_unit.capture(loaded), configured=configured,
        generated=deepcopy(configured),
        issue={"type": "ValueError", "locations": [{"function": "verify_capture", "line": 45}]},
        messages={"subscribed": True, "disconnected": True, "active": False},
        **{key: False for key in wall.FORBIDDEN},
    )
