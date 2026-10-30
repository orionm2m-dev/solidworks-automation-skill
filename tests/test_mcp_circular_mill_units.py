"""Explicit circular MCP schema and exact existing locked route; no CAD."""
from copy import deepcopy
import pytest
from test_mcp_cam_mill_units import params,core,context,server

def circle():
    return dict(plane_axis='Z',plane_offset_mm=10.9,sketch_name='CircleProfile',plane_name='CirclePlane',
                profile=dict(kind='circle',center_model_mm=[0.,0.,10.9],radius_mm=2.65))

@pytest.mark.parametrize('value',[4.1,1,0.001,100.])
def test_explicit_circle_depth(context,core,value):
    p=params(context,'prepare',feature_kind='circular_pocket',sketch_spec=circle(),depth_native=value)
    assert type(p.depth_native) is type(value)
    server.solidworks_cam_qualify_mill_feature_units(p)
    assert core.call_args.kwargs['feature_kind']=='circular_pocket'
    assert core.call_args.kwargs['depth_native']==value

@pytest.mark.parametrize('value',[True,False,'4.1',None,float('nan'),float('inf'),0,-1,101])
def test_bad_circle_depth(context,core,value):
    with pytest.raises(ValueError):
        params(context,feature_kind='circular_pocket',sketch_spec=circle(),depth_native=value)
    core.assert_not_called()

@pytest.mark.parametrize('kind',[None,True,0,'hole','circle','POCKET'])
def test_bad_kind(context,core,kind):
    with pytest.raises(ValueError):params(context,feature_kind=kind)
    core.assert_not_called()

def test_circle_mode_rejects_rectangle(context,core):
    with pytest.raises(ValueError):params(context,feature_kind='circular_pocket')
    core.assert_not_called()

def test_newmode_keeps_qualification_and_replay_guards(context,core):
    for changes in ({'qualification_only':False},{'acknowledge_disposable_copy':False},
                    {'expected_feature_native_id':99},{'save':True}):
        with pytest.raises(ValueError):
            params(context,'prepare',feature_kind='circular_pocket',sketch_spec=circle(),depth_native=4.1,**changes)
    core.assert_not_called()
