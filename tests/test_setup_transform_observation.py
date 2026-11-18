from ctypes import POINTER,cast,c_double,c_short,c_void_p
from copy import deepcopy
import importlib
import pytest
from comtypes import COMError
from comtypes.automation import IDispatch
from test_mill_operation_geometry import env,LocalDispatch,set_pointer
from scripts import sw_cam_mill_operation_geometry as core
from scripts import sw_cam_setup_transform_observation as setup


def address(value):return cast(value,c_void_p).value


@pytest.fixture
def setup_env(env,monkeypatch):
    e=env;objects=[LocalDispatch() for _ in range(7)];ptrs=[x.QueryInterface(IDispatch) for x in objects]
    e['setup_keepalive']=(objects,ptrs);e.update(statuses={},null_role=None,wrong_guid=None,nan_role=None,scale=1.,rotate=-1,metadata_missing=None,setup_qis=[])
    roles=('transform','x_axis','y_axis','z_axis','translation','origin','axis')
    values={'x_axis':[1.,0.,0.],'y_axis':[0.,-1.,0.],'z_axis':[0.,0.,-1.],'translation':[0.,0.,-12.6],'origin':[0.,0.,-12.6],'axis':[0.,0.,1.]}
    rolemap={address(ptr):name for name,ptr in zip(roles,ptrs)}
    oldmember=core._member;oldtyped=core._typed
    def member(obj,name,*args):
        if name not in (setup.RAW_SETUP,setup.RAW_DATA,*setup.RAW_COORDS.values()):return oldmember(obj,name,*args)
        e['calls'].append(name)
        if name==setup.RAW_SETUP:
            for out,index in zip(args,[0,5,6]):
                if e['null_role']!=roles[index]:set_pointer(out,ptrs[index])
        elif name==setup.RAW_DATA:
            for out,index in zip(args[:4],[1,2,3,4]):
                if e['null_role']!=roles[index]:set_pointer(out,ptrs[index])
            cast(args[4],POINTER(c_double))[0]=e['scale'];cast(args[5],POINTER(c_short))[0]=e['rotate']
        else:
            role=rolemap[address(obj)]
            for i,(out,val) in enumerate(zip(args,values[role])):cast(out,POINTER(c_double))[0]=float('nan') if role==e['nan_role'] and i==1 else val
        e['hook'](name)
        if e.get('com_failure')==name:raise COMError(-2147467259,'synthetic',None)
        return e['statuses'].get(name,0)
    def metadata(obj,*,typed,raw_call,boundary,row):
        role=rolemap[address(obj)];kind='ICWTransform' if role=='transform' else 'ICWPosition' if role=='origin' else 'ICWUnitVector' if role=='axis' else 'ICWVector'
        if e['metadata_missing']==role:row.update(complete=False,outcome='type_info_unavailable');boundary();return False
        row.update(complete=True,guid='{99999999-2222-3333-4444-555555555555}' if role==e['wrong_guid'] else setup.IIDS[kind]);boundary();return True
    def typed(raw,name,tlb):
        if name in setup.INTERFACES:e['setup_qis'].append(name);return raw
        return oldtyped(raw,name,tlb)
    monkeypatch.setattr(core,'_member',member);monkeypatch.setattr(core,'_typed',typed)
    monkeypatch.setattr(setup,'preflight',lambda tlb:dict(native_calls=0))
    monkeypatch.setattr(setup.metadata_reader,'metadata',metadata)
    e['run_setup']=lambda **kw:e['run'](observation_mode='setup_transform',targets=[e['args']['targets'][0]],**kw)
    return e


def test_two_real_synthetic_inventory_captures_and_raw_component_outputs(setup_env):
    e=setup_env;r=e['run_setup']();assert r['readback_verified'],r
    assert r['before']==r['after'] and r['setup_transform_complete'] and not r['parameters_complete']
    row=r['after']['selected'][0];assert row['transform_components']['vectors']['translation']['coordinates_raw']==[0.,0.,-12.6]
    assert row['origin']['coordinates_raw']==[0.,0.,-12.6] and row['axis']['coordinates_raw']==[0.,0.,1.]
    assert row['transform_components']['rotate_raw'] is True and row['transform_components']['scale_raw']==1.
    assert e['calls'].count(setup.RAW_SETUP)==2 and e['calls'].count(setup.RAW_DATA)==2
    assert e['calls'].count(setup.RAW_COORDS['ICWVector'])==8 and r['raw_getter_attempts']==16
    assert core.RAW_BASE not in e['calls'] and core.RAW_PARAMS not in e['calls']
    assert not r['coordinate_frame_verified'] and not row['generic_CL_frame_verified'] and not row['units_verified']
    assert not any(x.startswith(('Set','Save','Insert','Generate')) for x in e['calls'])


@pytest.mark.parametrize('role',['transform','x_axis','y_axis','z_axis','translation','origin','axis'])
def test_null_output_stays_diagnostic_no_guessed_interface(setup_env,role):
    e=setup_env;e['null_role']=role;r=e['run_setup']();assert r['readback_verified'],r
    assert not r['setup_transform_complete'] and r['before']==r['after']
    if role=='transform':assert not e['setup_qis'] and setup.RAW_DATA not in e['calls']


@pytest.mark.parametrize('kind',['wrong_guid','metadata_missing'])
def test_unadmitted_vector_type_stops_before_coordinate_or_fallback(setup_env,kind):
    e=setup_env;e[kind]='x_axis';r=e['run_setup']();assert r['readback_verified'],r
    assert not r['setup_transform_complete'] and setup.RAW_COORDS['ICWVector'] not in e['calls']
    assert 'ICWVector' not in e['setup_qis']


@pytest.mark.parametrize('key,val',[('scale',float('nan')),('scale',float('inf')),('rotate',12345),('rotate',1),('nan_role','translation')])
def test_unpopulated_or_nonfinite_components_fail_with_actual_outputs(setup_env,key,val):
    e=setup_env;e[key]=val;r=e['run_setup']();assert r['status']=='error' and not r['setup_transform_complete']
    assert e['calls'].count(setup.RAW_DATA)==1 and r['before']['selected'][0]['data_call']['returned']
    assert r['messages']['disconnected'] and not r['readback_verified']


@pytest.mark.parametrize('raw',[setup.RAW_SETUP,setup.RAW_DATA,setup.RAW_COORDS['ICWVector']])
def test_status1_stops_only_observation_no_retry(setup_env,raw):
    e=setup_env;e['statuses'][raw]=1;r=e['run_setup']();assert r['readback_verified'],r
    assert not r['setup_transform_complete'] and e['calls'].count(raw)==2


@pytest.mark.parametrize('kind',['event','source','runtime','dirty'])
def test_context_failure_preserves_populated_raw_outputs_and_stops(setup_env,kind):
    e=setup_env
    def hook(name):
        if name!=setup.RAW_DATA:return
        if kind=='event':e['session'].state['event_count']=1
        elif kind=='source':e['digest']='b'*64
        elif kind=='dirty':e['dirty']=True
        else:e['runtime_bad']=True
    e['hook']=hook
    def runtime():
        if e.get('runtime_bad'):raise ValueError('runtime drift')
    r=e['run_setup'](runtime_check=runtime);assert r['status']=='error' and not r['setup_transform_complete']
    out=r['before']['selected'][0]['data_call'];assert out['returned'] and out['outputs']['scale_raw']==1.
    assert e['calls'].count(setup.RAW_DATA)==1 and setup.RAW_COORDS['ICWVector'] not in e['calls']


def test_setup_abi_failure_precedes_bootstrap(setup_env,monkeypatch):
    def fail(tlb):raise ValueError('ABI changed')
    monkeypatch.setattr(setup,'preflight',fail);r=setup_env['run_setup']()
    assert r['status']=='error' and not setup_env['calls']


def test_local_declared_metadata_exact_abi_without_native(monkeypatch):
    generated=pytest.importorskip('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    get=lambda name,tlb:getattr(generated,name)
    monkeypatch.setattr(setup,'_interface_class',get);monkeypatch.setattr(setup.metadata_reader,'_interface_class',get)
    assert setup.preflight('metadata-only')['native_calls']==0


def test_changed_second_snapshot_revokes_complete_result(setup_env):
    e=setup_env;seen=0
    def hook(name):
        nonlocal seen
        if name==setup.RAW_DATA:
            seen+=1
            if seen==1:e['scale']=2.
    e['hook']=hook;r=e['run_setup']()
    assert r['status']=='error' and not r['setup_transform_complete'] and not r['readback_verified']
    assert r['before']['selected'][0]['transform_components']['scale_raw']==1.
    assert r['after']['selected'][0]['transform_components']['scale_raw']==2.


def test_only_exact_vector_registration_added():
    from scripts.sw_cam_comtypes import _INTERFACES
    assert _INTERFACES['ICWVector']==setup.IIDS['ICWVector']


@pytest.mark.parametrize('bad_owner',[False,True])
def test_explicit_circular_saved_state_uses_generic_owner_capture_not_compound_cast(setup_env,monkeypatch,bad_owner):
    e=setup_env;state=e['loaded']['state'];machine=e['doc']['IGetMachine']
    feature_setup=machine['IGetEnumSetups']['Item'](0)
    operation_setup=machine['IGetEnumOpSetups']['Item'](0)
    feature_setup['_id']=71;operation_setup['_id']=94;e['f0']['_id']=359;e['op0']['_id']=361
    e['doc']['GetCWObjectFromID']=lambda kind,fid:(e['f0'] if fid==359 else machine['IGetEnumSetups']['Item'](1)['IGetEnumFeatures']['Item'](0),True)
    state['feature_setups'][0].update(native_id=71,feature_ids=[359])
    state['operation_setups'][0]['native_id']=94
    state['operations'][0].update(native_id=361,setup_native_id=94,linked_feature_ids=[359])
    state['target_header']=dict(native_id=359,volume_type=2,subtype_raw=0)
    e['loaded']['mode']='current_saved_circular';e['loaded']['binding']['configuration_mode']='current_saved_circular'
    e['args']['anchor_operation_native_id']=361
    e['args']['targets'][0]=dict(operation_native_id=361,feature_native_id=359,feature_setup_native_id=71,operation_setup_native_id=94,mill_operation_type=0)
    if bad_owner:e['f0']['GetOwner']=dict(_id=99)
    original=core._typed;interfaces=[]
    def typed(raw,name,tlb):interfaces.append(name);return original(raw,name,tlb)
    monkeypatch.setattr(core,'_typed',typed)
    result=e['run_setup']()
    assert 'ICWMultiStepFeature' not in interfaces and 'ICWMSHoleFeat' not in interfaces
    assert 'GetNumOfSteps' not in e['calls'] and 'GetTypeAtStep' not in e['calls']
    if bad_owner:
        assert result['status']=='error' and setup.RAW_SETUP not in e['calls']
    else:
        assert result['readback_verified'] and result['setup_transform_complete'],result
        assert result['before']['selected'][0]['target']==e['args']['targets'][0]
        assert result['before']==result['after']
