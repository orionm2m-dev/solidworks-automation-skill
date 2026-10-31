"""Portable callback graph tests for fixed Contour defaults readback."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))))
spec=importlib.util.spec_from_file_location('chamfer_defaults_under_test',ROOT/'scripts/sw_cam_chamfer_defaults.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Graph:
    def __init__(self):
        self.calls=[];self.saved=[];self.diagnostic={};self.override={};self.fail=None;self.fail_persist=False
    def persist(self):
        self.saved.append(deepcopy(self.diagnostic))
        if self.fail_persist and self.diagnostic.get('calls'):raise OSError('injected storage failure')
    def typed(self,obj,name):
        assert self.saved[-1]['calls'][-1]['name']==name
        self.calls.append(('QI',name))
        if self.fail==name:raise RuntimeError('injected QI failure')
        if name in self.override:return self.override[name]
        return name,obj
    def read(self,obj,name,*args):
        assert name in m.GETTERS
        assert self.saved[-1]['calls'][-1]['name']==name
        self.calls.append(('GET',name))
        if self.fail==name:raise RuntimeError('injected getter failure')
        if name in self.override:return self.override[name]
        if name in ('GetPreviousAllowance','GetMachiningDepth','GetOverrideMachiningDepth','GetMachiningDepthValue'):
            assert args==(('IDispatch','feature'),)
        if name=='GetToolpathParam':return 'toolpath_parameters'
        if name=='GetSetupParameters':return 'transform','origin','axis'
        if name=='GetToolpathParameters':return True,False,False,0,True,26.,26.
        if name=='GetCoordinates':return (0.,0.,0.) if obj[0]=='ICWPosition' else (0.,0.,-1.)
        if name=='GetOverrideMachiningDepth' or name in m.BOOL_FIELDS:return False
        if name in m.INT_FIELDS:return 0
        return 0.
    def run(self):
        return m.read_defaults('operation','feature',read=self.read,typed=self.typed,
                              persist=self.persist,diagnostic=self.diagnostic)


def test_complete_read_exact_budget_and_no_tool_profile():
    g=Graph();result=g.run()
    assert result['complete'] is True and g.diagnostic['read_complete'] is True
    assert len(g.calls)==g.diagnostic['native_call_count']==m.MAX_NATIVE_CALLS==45
    assert result['tool_profile_read'] is False and result['production_qualified'] is False
    assert result['level_state']['setup']['axis_native']==[0.,0.,-1.]
    assert 'GetChamferAngle' in result['finish'] and 'GetChamferClearance' in result['finish']
    assert result['level_state']['levels']['machining_depth_value_native']==0.
    assert all(name in m.GETTERS for kind,name in g.calls if kind=='GET')
    assert not any('Tool' in name and name!='ICWToolpathParam' for kind,name in g.calls if kind=='QI')
    assert all(row['returned'] and row['validated'] for row in g.diagnostic['calls'])
    result['finish'].clear();assert g.diagnostic['partial_values']['finish']


@pytest.mark.parametrize('name,value', [('SpringPass',True),('DepthMethod',1.),('GetChamferType',2**31),
    ('GetIsChamferMachining',1),('SideAllow',False),('GetChamferAngle',90),
    ('GetChamferLength',float('nan')),('GetChamferClearance',float('inf'))])
def test_exact_scalar_shapes_and_finite_values_required(name,value):
    g=Graph();g.override[name]=value
    with pytest.raises(ValueError):g.run()
    assert g.diagnostic['partial_values']['complete'] is False
    assert g.diagnostic['calls'][-1]['name']==name and g.diagnostic['calls'][-1]['returned'] is True
    assert g.diagnostic['calls'][-1]['validated'] is False
    assert g.saved[-1]['calls'][-1]['issue_type']=='ValueError'


@pytest.mark.parametrize('name',['ICWFinishMillOp3','GetChamferClearance','GetMachiningDepthValue'])
def test_failed_callback_stops_and_keeps_earlier_results(name):
    g=Graph();g.fail=name
    with pytest.raises(RuntimeError):g.run()
    assert g.calls.count(('QI' if name.startswith('ICW') else 'GET',name))==1
    assert g.diagnostic['calls'][-1]['returned'] is False
    assert g.diagnostic['partial_values']['complete'] is False
    assert g.saved[-1]['calls'][-1]['issue_type']=='RuntimeError'
    assert g.diagnostic['partial_values']['finish']


@pytest.mark.parametrize('name',['IDispatch','ICWFinishMillOp','ICWToolpathParam'])
def test_null_required_interface_stops(name):
    g=Graph();g.override[name]=None
    with pytest.raises(ValueError):g.run()
    assert g.diagnostic['calls'][-1]['name']==name


def test_zero_setup_axis_rejected():
    g=Graph();g.override['GetCoordinates']=(0.,0.,0.)
    with pytest.raises(ValueError):g.run()
    assert g.diagnostic['partial_values']['complete'] is False
    assert not any(name=='GetMachiningDepthValue' for kind,name in g.calls)


def test_persistence_failure_prevents_first_native_callback():
    g=Graph();g.fail_persist=True
    with pytest.raises(OSError):g.run()
    assert not g.calls


def test_existing_diagnostic_prevents_replay():
    g=Graph();g.diagnostic['prior']=True
    with pytest.raises(ValueError):g.run()
    assert not g.calls


def test_no_default_tool_is_required():
    g=Graph();result=g.run()
    assert result['complete'] is True
    assert not any(name in ('IGetTool','IGetMillToolHolder','GetToolProfile','GetShankProfile') for _,name in g.calls)


@pytest.mark.parametrize('mutate', [
    lambda v: v['finish'].pop('GetChamferClearance'),
    lambda v: v['finish'].update(GetChamferType=True),
    lambda v: v['level_state']['levels'].update(override_machining_depth=1),
    lambda v: v['level_state']['setup'].update(axis_magnitude=2.),
    lambda v: v.update(complete=1),
])
def test_saved_defaults_reject_tampering(mutate):
    value=Graph().run();mutate(value)
    with pytest.raises(ValueError):m.validate_defaults(value)
