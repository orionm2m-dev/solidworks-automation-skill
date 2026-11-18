"""Narrow finite absolute-depth comparison regression; no native/context execution."""
from copy import deepcopy
import importlib,math,os,sys
from pathlib import Path
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE))
sys.path.insert(0,str(RUNTIME))
import scripts
if str(STAGE/'scripts') not in scripts.__path__:scripts.__path__.insert(0,str(STAGE/'scripts'))
core=importlib.import_module('scripts.sw_cam_autodetected_pocket')
def inputs(observed):
    before=dict(feature_count=0,operation_count=0,generated_operation_count=0,total_record_count=0,features=[],feature_setups=[dict(native_id=64,feature_ids=[])],sw_reference=dict(feature_tree=[],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.,2.,3.,4.])]))
    after=deepcopy(before);after['feature_count']=1;after['features']=[dict(native_id=999,setup_native_id=64)];after['feature_setups'][0]['feature_ids']=[999]
    header=dict(native_id=999,owner_setup_native_id=64,volume_type=2,suppressed=False,axis_native=[0.,0.,-1.],depth_native=observed,island_count=4)
    request=dict(owner_setup_native_id=64,expected_axis_native=[0.,0.,-1.],depth_native=13.2)
    return before,after,header,request
@pytest.mark.parametrize('observed',[13.2,25.8-12.6,math.nextafter(13.2,math.inf),13.2+5e-9])
def test_tiny_native_scalar_roundoff_accepts_only_definition(observed):
    args=inputs(observed);unchanged=deepcopy(args);r=core.verify_delta(*args)
    assert r['requested_depth_readback'] and r['definition_only']
    assert not r['physical_depth_verified'] and not r['island_geometry_verified'] and not r['production_qualified']
    assert args==unchanged
@pytest.mark.parametrize('observed',[13.2+2e-8,13.2-2e-8,13.201,.0132,13200.,13.2/25.4,float('nan'),float('inf'),float('-inf'),True,'13.2',None])
def test_scale_drift_nonfinite_and_coercion_rejected(observed):
    with pytest.raises(ValueError):core.verify_delta(*inputs(observed))
@pytest.mark.parametrize('observed',[0.,-1e-9,-5e-9])
def test_positive_requested_depth_never_accepts_zero_or_negative_readback(observed):
    args=inputs(observed);args[3]['depth_native']=1e-9
    with pytest.raises(ValueError):core.verify_delta(*args)
