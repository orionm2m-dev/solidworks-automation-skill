from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module
R=add_runtime()
required_module('sw_cam_root_microtool_nc')
integrated=required_module('sw_cam_local_operation_nc')
Journal=required_test_module('test_local_operation_group').Journal


def backend_fixture(cnc=1,spindle=4000.,feed=500.):
    value=dict(GetTlpComp=1,GetCNCComp=cnc,GetSpndlSpeed=spindle,GetRetractType=0,XYFeed=feed)
    tool=dict(native_id=700,cut_diameter_native=.8,protrusion_native=19.,tool_type_raw=1)
    targets=[dict(operation_native_id=1000+i,feature_native_id=900+i//2,operation_setup_native_id=93,
        operation_type=i%2,assigned_tool=deepcopy(tool))for i in range(4)]
    b=SimpleNamespace(args=dict(expected_source_sha256='a'*64,process_id=1),baseline=dict(binding=dict(operations=[{'native_id':100+i}for i in range(17)])),
        loaded=dict(configuration_tool=tool),learned=targets,report={},value=value,calls=[])
    b.read_nc=lambda t:deepcopy(b.value);b.refresh_dirty=lambda:None
    def set_nc(t,expected,pending):assert expected==b.value;pending();b.calls.append('CNC0');b.value['GetCNCComp']=0;return 0
    b.set_nc=set_nc
    return b,targets[0]


def install_fake_setters(monkeypatch,b,drift=None):
    def read(backend,target,scope):integrated.micro.validate_scope(backend,target,scope);return deepcopy(b.value)
    monkeypatch.setattr(integrated.micro,'read_fields',read)
    def spindle(backend,target,scope,expected,pending):
        assert expected==b.value;pending();b.calls.append('spindle');b.value.update(GetSpndlSpeed=7100.,XYFeed=70.)
        if drift:b.value[drift]=9
        return 0
    def feed(backend,target,scope,expected,pending):
        assert expected==b.value;pending();b.calls.append('feed');b.value['XYFeed']=35.;return 0
    monkeypatch.setattr(integrated.micro,'set_spindle_once',spindle);monkeypatch.setattr(integrated.micro,'set_xy_feed_once',feed)


def test_cnc_then_spindle_coupled_feed_then_explicit35(monkeypatch):
    b,t=backend_fixture();install_fake_setters(monkeypatch,b);j=Journal();j.report['actions']={};b.report=j.report
    integrated.configure_nc(b,j,t,b.loaded)
    assert b.calls==['CNC0','spindle','feed'] and b.value['XYFeed']==35.
    assert not j.report['nc_readbacks']['1000']['verification']['feed_units_verified']
    integrated.before_generate(b,t)


def test_already_correct_values_reused_without_mutation(monkeypatch):
    b,t=backend_fixture(0,7100.,35.);install_fake_setters(monkeypatch,b);j=Journal();j.report['actions']={};b.report=j.report
    integrated.configure_nc(b,j,t,b.loaded)
    assert b.calls==[] and all(v['attempted']is False for v in j.report['actions'].values())


def test_spindle_cannot_change_compensation(monkeypatch):
    b,t=backend_fixture();install_fake_setters(monkeypatch,b,drift='GetCNCComp');j=Journal();j.report['actions']={};b.report=j.report
    with pytest.raises(ValueError):integrated.configure_nc(b,j,t,b.loaded)
    assert b.calls==['CNC0','spindle'] and 'nc_readbacks'not in j.report


def test_pre_gtp_rejects_later_nc_change(monkeypatch):
    b,t=backend_fixture();install_fake_setters(monkeypatch,b);j=Journal();j.report['actions']={};b.report=j.report
    integrated.configure_nc(b,j,t,b.loaded);b.value['XYFeed']=36.
    with pytest.raises(ValueError):integrated.before_generate(b,t)
