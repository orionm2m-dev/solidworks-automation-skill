"""公开延续输入保持窄范围；不连接 CAD。"""
import pytest
from test_mcp_cam_operation_diagnostics import context
from test_mcp_cam_turn_holder_dimensions import params,native


def pins(tmp_path):
    return dict(marker_path=str(tmp_path/"marker.json"),marker_sha256="a"*64,receipt_path=str(tmp_path/"old.json"),receipt_sha256="b"*64)


def test_public_explicit_pins_accept_new_Lead_only(context,native,tmp_path):
    p=params(context,tmp_path,values_native={"LeadAngle":-32.},completed_length_probe=pins(tmp_path))
    assert p.completed_length_probe==pins(tmp_path)

@pytest.mark.parametrize("which",["same_field","extra_field","bad_sha","extra_key","relative","coerced"])
def test_public_invalid_continuation_never_calls(context,native,tmp_path,which):
    p=pins(tmp_path);values={"LeadAngle":-32.}
    if which=="same_field":values={"ShankLength":190.}
    elif which=="extra_field":values["BoringBarDiameter"]=20.
    elif which=="bad_sha":p["marker_sha256"]="x"*64
    elif which=="extra_key":p["allow_retry"]=True
    elif which=="relative":p["receipt_path"]="old.json"
    else:p["marker_sha256"]=123
    with pytest.raises(ValueError):params(context,tmp_path,values_native=values,completed_length_probe=p)
    native.assert_not_called();context.connect.assert_not_called()
