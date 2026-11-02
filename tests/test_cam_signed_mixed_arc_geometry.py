from cam_mixed_test_support import ROOT, SCRIPTS, evidence_file, evidence_json, server_nodes, synthetic_specs, synthetic_context
import importlib.util
import math
import os
from pathlib import Path
import pytest
from scripts import sw_cam_signed_mixed_profile as m


@pytest.mark.parametrize('sweep',[math.pi/4,-math.pi/4,math.pi,-math.pi,1.5*math.pi,-1.5*math.pi,2*math.pi-.01,.01])
def test_actual_direction_and_length_choose_exact_arc(sweep):
    r=.001;a=.7;c=[.004,.006,0.]
    start=[c[0]+r*math.cos(a),c[1]+r*math.sin(a),0.]
    end=[c[0]+r*math.cos(a+sweep),c[1]+r*math.sin(a+sweep),0.]
    got=m.reconstruct_arc(start,end,c,r,r*abs(sweep),1 if sweep>0 else -1,[0.,0.,1. if sweep>0 else -1.])
    expected=[c[0]+r*math.cos(a+sweep/2),c[1]+r*math.sin(a+sweep/2),0.]
    assert math.dist(got['mid_sketch_m'],expected)<1e-12
    assert abs(got['signed_sweep_rad']-sweep)<1e-12
    assert got['independent_native_length_verified']is True and got['underlying_curve_trim_used']is False


def args():return [[.001,0.,0.],[0.,.001,0.],[0.,0.,0.],.001,.001*math.pi/2,1,[0.,0.,1.]]

@pytest.mark.parametrize('index,value',[(5,True),(5,0),(5,2),(6,[0.,0.,-1.]),(6,[0.,1.,0.]),(3,float('nan')),(4,.001*math.pi*1.5),(0,[.002,0.,0.]),(0,[.001,0.,.01]),(1,[.001,0.,0.])])
def test_ambiguous_or_mismatched_geometry_rejected(index,value):
    p=args();p[index]=value
    with pytest.raises(ValueError):m.reconstruct_arc(*p)


def test_opposite_direction_with_same_endpoints_fails_independent_length():
    p=args();p[5]=-1;p[6]=[0.,0.,-1.]
    with pytest.raises(ValueError):m.reconstruct_arc(*p)

