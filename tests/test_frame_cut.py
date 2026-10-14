"""坐标系切除在写入之前验证几何和输入边界。"""
import math
import pytest
from scripts.sw_frame_cut import FrameCutSpec

def valid(**changes):
    data=dict(origin_mm=[0,0,0],width_mm=10,height_mm=4,radius_mm=1,depth_mm=3,feature_name="Pocket")
    data.update(changes)
    return FrameCutSpec(**data)

def test_tilted_frame_accepted():
    a=math.radians(2)
    assert valid(y_axis=[0,math.cos(a),-math.sin(a)]).depth_mm==3

@pytest.mark.parametrize("change",[dict(x_axis=[0,0,0]),dict(x_axis=[2,0,0]),dict(y_axis=[1,0,0]),dict(radius_mm=2),dict(depth_mm=0),dict(width_mm=float("nan")),dict(feature_name="../unsafe"),dict(overwrite=True)])
def test_invalid_geometry_rejected(change):
    with pytest.raises(ValueError):valid(**change)

def test_guarded_mcp_tool():
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"mcp-server"))
    import server
    assert issubclass(server.SolidWorksFrameCutInput,server.ActiveDocumentInput)
    assert "solidworks_create_frame_cut" in server.mcp._tool_manager._tools
