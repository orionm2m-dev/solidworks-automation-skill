import pytest
from scripts import sw_cam_mill_operation_geometry as m
from test_mill_operation_geometry import env


def alter_status(env,monkeypatch,*,base_status=0,param_status=0,null=True):
    env['base_null']=null;original=m._member;active={'first':False}
    def member(obj,name,*args):
        if name==m.RAW_BASE:active['first']=args[0] is env['f0']
        result=original(obj,name,*args)
        if name==m.RAW_BASE and active['first']:return base_status
        if name==m.RAW_PARAMS and active['first']:return param_status
        return result
    monkeypatch.setattr(m,'_member',member)


def test_status1_null_retained_then_independent_comparator_twice(env,monkeypatch):
    alter_status(env,monkeypatch,base_status=1)
    r=env['run']();assert r['readback_verified'] and r['before']==r['after'],r
    first,comparison=r['before']['selected']
    assert first['outcome']=='base_getter_status1_null' and first['base_call']['returned']
    assert first['base_call']['hresult']==1 and first['base_call']['outputs']['base_feature']['present'] is False
    assert first['parameter_call'] is None and 'base_interface_call' not in first and not first['parameters_complete']
    assert comparison['parameters_complete'] and comparison['outcome']=='typed_parameters_observed'
    assert env['calls'].count(m.RAW_BASE)==4 and env['calls'].count(m.RAW_PARAMS)==2
    assert not r['parameters_complete'] and not r['empty_toolpath_cause_proven'] and not r['read_pending']


def test_parameter_status1_keeps_outputs_diagnostic_then_comparator(env,monkeypatch):
    alter_status(env,monkeypatch,param_status=1,null=False)
    r=env['run']();assert r['readback_verified'] and r['before']==r['after'],r
    first,comparison=r['before']['selected'];assert first['outcome']=='parameter_getter_status1' and not first['parameters_complete']
    assert first['parameter_call']['hresult']==1 and first['parameter_call']['outputs']['machining_depth_native']['raw']==7.6
    assert 'parameters' not in first and comparison['parameters_complete']
    assert not r['empty_toolpath_cause_proven'] and env['calls'].count(m.RAW_PARAMS)==4

@pytest.mark.parametrize('value,null',[(1,False),(2,True),(-1,True),(True,True),(None,True)])
def test_unrecognized_or_nonnull_base_status_still_stops(env,monkeypatch,value,null):
    alter_status(env,monkeypatch,base_status=value,null=null);r=env['run']()
    assert r['status']=='error' and not r['readback_verified'] and len(r['before']['selected'])==1
    assert env['calls'].count(m.RAW_BASE)==1 and m.RAW_PARAMS not in env['calls']
    assert r['before']['selected'][0]['base_call']['returned']

@pytest.mark.parametrize('value',[2,-1,True,None])
def test_unrecognized_parameter_status_still_stops(env,monkeypatch,value):
    alter_status(env,monkeypatch,param_status=value,null=False);r=env['run']()
    assert r['status']=='error' and not r['readback_verified'] and len(r['before']['selected'])==1
    first=r['before']['selected'][0];assert first['parameter_call']['returned'] and 'parameters' not in first
    assert first['parameter_call']['outputs']['machining_depth_native']['raw']==7.6

@pytest.mark.parametrize('unsafe',['source','event'])
def test_status1_never_continues_after_unsafe_boundary(env,monkeypatch,unsafe):
    alter_status(env,monkeypatch,base_status=1)
    def hook(name):
        if name!=m.RAW_BASE:return
        if unsafe=='source':env['digest']='b'*64
        else:env['session'].state['event_count']=1
    env['hook']=hook;r=env['run']();assert r['status']=='error' and not r['readback_verified']
    assert env['calls'].count(m.RAW_BASE)==1 and m.RAW_PARAMS not in env['calls']
    assert r['before']['selected'][0]['base_call']['hresult']==1 and r['messages']['disconnected']
