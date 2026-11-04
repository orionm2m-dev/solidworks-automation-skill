"""精镗读取复用公开工具，并在运行时漂移时保留实际双快照。"""
import json
from unittest.mock import Mock
from types import SimpleNamespace
import pytest
from test_mcp_cam_operation_diagnostics import context,server
from test_mcp_cam_turn_bore_options import params,core


def test_existing_public_tool_routes_finish_two_control_flag(context,core):
    p=params(context,expected_operation_type=6,include_leftover_control=True)
    r=json.loads(server.solidworks_cam_inspect_turn_bore_options(p))
    assert r["readback_verified"] and core.call_args.kwargs["expected_operation_type"]==6
    assert core.call_args.kwargs["include_leftover_control"] is True
    assert core.call_args.kwargs["include_tool_contours"] is False
    core.assert_called_once()

@pytest.mark.parametrize("changes",[{"include_leftover_control":False},{"include_leftover_control":1},
 {"include_tool_contours":True,"expected_tool_native_id":77},{"expected_tool_native_id":77},{"expected_operation_type":7}])
def test_finish_schema_rejects_broader_scope(context,core,changes):
    values=dict(expected_operation_type=6,include_leftover_control=True);values.update(changes)
    with pytest.raises(ValueError):params(context,**values)
    core.assert_not_called();context.connect.assert_not_called()


def test_post_read_runtime_drift_preserves_two_captures_without_replay(context,core,monkeypatch):
    core.return_value.update(before={"bore_options_native":{"GenerateLeftOver":True,"LEFTOVER_TYPE":1}},
        after={"bore_options_native":{"GenerateLeftOver":True,"LEFTOVER_TYPE":1}})
    monkeypatch.setattr(server,"_runtime_identity",SimpleNamespace(assert_current=Mock(side_effect=[None,ValueError("changed")])))
    r=json.loads(server.solidworks_cam_inspect_turn_bore_options(params(context,expected_operation_type=6,include_leftover_control=True)))
    assert r["status"]=="error" and not r["readback_verified"] and not r["may_continue"] and not r["runtime_unchanged"]
    assert r["before"]==r["after"]==core.return_value["before"]
    assert r["runtime_error"]["type"]=="ValueError";core.assert_called_once()
