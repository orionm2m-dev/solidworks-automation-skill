"""既有轮廓端点的 CutOff 严格参数和路由；不连接 CAD。"""
import json
import pytest
from test_mcp_cam_turn_tool_contours import context, core, params, server


def test_cutoff_pins_route_through_existing_read_endpoint(context,core):
    p=params(context,operation_index=10,expected_operation_type=13,expected_operation_native_id=135,
        expected_tool_native_id=141,expected_linked_feature_ids=[78])
    r=json.loads(server.solidworks_cam_inspect_turn_tool_contours(p))
    assert r==core.return_value
    core.assert_called_once_with(context.sw,p.addin_clsid,
        typelib_path=str(context.dll.parent/"camworks.tlb"),
        **p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))
    assert server._runtime_identity.assert_current.call_count==2

@pytest.mark.parametrize("value",[0,1,7,8,9,10,11,12,14,15,13.,True,"13"])
def test_only_exact_supported_operation_types(context,core,value):
    with pytest.raises(ValueError):params(context,expected_operation_type=value)
    core.assert_not_called();context.connect.assert_not_called()

def test_bore_options_remain_rough_only(context):
    values=params(context,expected_operation_type=13).model_dump(exclude={"expected_tool_native_id"})
    with pytest.raises(ValueError):server.SolidWorksCamTurnBoreOptionsInput(**values)


def test_post_read_runtime_drift_preserves_both_actual_captures(context,core):
    data=dict(selected_operation=dict(native_id=135),tool_contours=dict(tool_native_id=141,
        insert_profile=dict(curve_count=6),holder_profile=dict(curve_count=10)))
    core.return_value.update(before=data,after=data,may_continue=True,mutation_attempted=False)
    server._runtime_identity.assert_current.side_effect=[None,ValueError("runtime changed during read")]
    p=params(context,expected_operation_type=13,expected_operation_native_id=135,
        expected_tool_native_id=141,expected_linked_feature_ids=[78])
    r=json.loads(server.solidworks_cam_inspect_turn_tool_contours(p))
    assert r["status"]=="error" and r["reason"]=="RUNTIME_CHANGED_AFTER_READ"
    assert not r["readback_verified"] and not r["runtime_unchanged"] and not r["may_continue"]
    assert r["before"]==data and r["after"]==data and not r["mutation_attempted"]
    assert not r["units_verified"]
    core.assert_called_once();assert server._runtime_identity.assert_current.call_count==2
