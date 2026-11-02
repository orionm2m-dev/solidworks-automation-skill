from copy import deepcopy
from pathlib import Path
import pytest
from cam_public_test_support import add_runtime, required_module
R=add_runtime()
recipe=required_module('sw_cam_local_operation_recipe')


def rough_row():
    row=dict(operation_native_id=1000,feature_native_id=900,read_complete=True,levels={'depth':3.4},tool={'generic':{'native_id':700}},
        rough=dict(entry={},depth={},boundary={}),startpoints=dict(entry_type=4,read_complete=True,collection_interface_verified=True,
        list_is_null=False,count=0,rows=[],hole_center_entry=True,coordinate_frame='unknown_native'),
        nc=dict(feeds_compensation=dict(GetSpndlSpeed=4000.,XYFeed=500.,GetCNCComp=1,GetTlpComp=1,GetRetractType=0),
        z_feed=dict(value_native=25.,percentage=True),planes={'rapid':25.}))
    for spec in recipe.config.ROUGH_FIELDS:
        area={'entry_type':'entry','spiral_radius':'entry','spiral_pitch':'entry','first_depth':'depth','subsequent_depth':'depth'}.get(spec[0],'boundary')
        row['rough'][area][spec[2]]={'raw':0}
    row['rough']['depth'].update(FirstDepthAmt={'raw':0},SbsqDepthAmt={'raw':0},unselected={'raw':88})
    row['rough']['entry'].update(GetHoleCentreEntry={'raw':True},GetEntryStartPtX={'raw':0.},GetEntryStartPtY={'raw':0.})
    return row


def test_recipe_projection_retains_unselected_parameters():
    a=rough_row();b=deepcopy(a);b['nc']['feeds_compensation'].update(GetSpndlSpeed=7100.,XYFeed=35.,GetCNCComp=0)
    b['rough']['entry']['GetEntryStartPtX']={'raw':-8.};b['startpoints'].update(count=1,rows=[{}],hole_center_entry=False)
    assert recipe.controlled_projection(a,entry_initialized=True)==recipe.controlled_projection(b,entry_initialized=True)
    b['nc']['z_feed']['value_native']=26.
    assert recipe.controlled_projection(a,entry_initialized=True)!=recipe.controlled_projection(b,entry_initialized=True)


def test_assignment_rejects_changed_depth_or_start_list():
    a=rough_row();b=deepcopy(a);loaded={'local_tool_dimensions':b['tool']}
    recipe.verify_assignment(a,b,{},loaded)
    b['levels']['depth']=4.
    with pytest.raises(ValueError):recipe.verify_assignment(a,b,{},loaded)


def test_assignment_rejects_unrequested_z_feed_change():
    a=rough_row();b=deepcopy(a);b['nc']['z_feed']['value_native']=26.
    with pytest.raises(ValueError):recipe.verify_assignment(a,b,{},dict(local_tool_dimensions=b['tool']))


def test_assignment_rejects_tool_dimensions_mismatch():
    a=rough_row();b=deepcopy(a)
    with pytest.raises(ValueError):recipe.verify_assignment(a,b,{},dict(local_tool_dimensions={'generic':{'native_id':701}}))
