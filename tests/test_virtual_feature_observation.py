from ctypes import POINTER,cast,c_void_p,c_int,c_ulong,pointer
from comtypes import COMObject,IUnknown,COMError,GUID
from comtypes.automation import IDispatch
from comtypes.typeinfo import ITypeInfo,TYPEATTR
from copy import deepcopy
import importlib
import pytest
from test_mill_operation_geometry import env,LocalDispatch,set_pointer
from scripts import sw_cam_mill_operation_geometry as core
from scripts import sw_cam_virtual_feature_observation as v
from scripts import sw_cam_comtypes as bridge

class LocalInfo(COMObject):_com_interfaces_=[ITypeInfo]

def address(p):return cast(p,c_void_p).value

def put(output,value,cls):
    value.AddRef();cast(output,POINTER(POINTER(cls)))[0]=value

@pytest.fixture
def virtual_env(env,monkeypatch):
    e=env;e.update(virtual_status=0,virtual_null=False,info_count=1,collection_count=2,unknown_guid=False,
        raw_fail=None,raw_status=None,member_null=None,attr_null=False,info_null=False,releases=0,info_fail=False)
    collection=e['keepalive'][1];member_object=LocalDispatch();member=member_object.QueryInterface(IDispatch)
    info_objects=[LocalInfo(),LocalInfo()];infos=[x.QueryInterface(ITypeInfo) for x in info_objects]
    attrs=[TYPEATTR(),TYPEATTR()]
    for i,a in enumerate(attrs):a.guid=GUID(v.COLLECTION_IID if i==0 else '{11111111-2222-3333-4444-555555555555}');a.typekind=4
    e['virtual_keepalive']=(member_object,member,info_objects,infos,attrs)
    original=core._member;old_typed=core._typed
    def read(obj,name,*args):
        if name not in v.RAW_READS+(v.RAW_RELEASE,):return original(obj,name,*args)
        e['calls'].append(name)
        if name==v.RAW_VIRTUAL:
            if not e['virtual_null']:set_pointer(args[0],collection)
            result=e['virtual_status']
        elif name==v.RAW_INFO_COUNT:cast(args[0],POINTER(c_ulong))[0]=e['info_count'];result=0
        elif name==v.RAW_INFO:
            if not e['info_null']:put(args[2],infos[0 if address(obj)==address(collection) else 1],IUnknown)
            result=0
        elif name==v.RAW_ATTR:
            i=0 if address(obj)==address(infos[0]) else 1
            attrs[i].guid=GUID('{99999999-2222-3333-4444-555555555555}' if e['unknown_guid'] and i==0 else v.COLLECTION_IID if i==0 else '{11111111-2222-3333-4444-555555555555}')
            if not e['attr_null']:cast(args[0],POINTER(POINTER(TYPEATTR)))[0]=pointer(attrs[i])
            result=0
        elif name==v.RAW_RELEASE:e['releases']+=1;return None
        elif name==v.RAW_DOC:result=0
        elif name==v.RAW_COUNT:cast(args[0],POINTER(c_int))[0]=e['collection_count'];result=0
        elif name==v.RAW_ITEM:
            if args[0]!=e['member_null']:set_pointer(args[1],member)
            result=0
        else:raise AssertionError(name)
        e['hook'](name)
        if e['raw_fail']==name:raise COMError(-2147467259,'synthetic',None)
        if e['raw_status'] and e['raw_status'][0]==name:return e['raw_status'][1]
        return result
    def typed(raw,name,tlb):
        if name=='ICWDispatchCollection' and isinstance(raw,IDispatch):return dict(_virtual=True)
        return old_typed(raw,name,tlb)
    monkeypatch.setattr(core,'_member',read);monkeypatch.setattr(v,'_member',read);monkeypatch.setattr(core,'_typed',typed)
    monkeypatch.setattr(v,'preflight',lambda tlb:dict(native_calls=0))
    e['run_virtual']=lambda **kw:e['run'](observation_mode='virtual_features',targets=[e['args']['targets'][0]],**kw)
    return e


def test_actual_synthetic_inventory_then_raw_virtual_members_twice(virtual_env):
    e=virtual_env;r=e['run_virtual']();assert r['readback_verified'],r
    assert r['before']==r['after'] and r['virtual_collection_complete'] and not r['parameters_complete']
    row=r['before']['selected'][0];assert row['count']==2 and [x['index'] for x in row['members']]==[0,1]
    assert all(x['metadata']['guid']=='{11111111-2222-3333-4444-555555555555}' for x in row['members'])
    assert e['releases']==6 and e['calls'].count(v.RAW_VIRTUAL)==2 and e['calls'].count(v.RAW_ITEM)==4
    assert core.RAW_BASE not in e['calls'] and core.RAW_PARAMS not in e['calls']
    assert not any(x.startswith(('Set','Save','Generate','Insert')) for x in e['calls'])
    assert not r['empty_toolpath_cause_proven'] and r['messages']['disconnected']

@pytest.mark.parametrize('key,value,outcome',[
 ('virtual_null',True,'null_virtual_collection'),('virtual_status',1,'virtual_getter_diagnostic'),
 ('info_count',0,'virtual_collection_metadata_unavailable'),('unknown_guid',True,'unadmitted_collection_guid'),
 ('info_null',True,'virtual_collection_metadata_unavailable'),('attr_null',True,'virtual_collection_metadata_unavailable'),
 ('collection_count',0,'observed_empty_virtual_collection'),('member_null',0,'null_virtual_member')])
def test_bounded_diagnostic_is_retained_without_guessed_cast(virtual_env,key,value,outcome):
    e=virtual_env;e[key]=value;r=e['run_virtual']();assert r['readback_verified'],r
    row=r['before']['selected'][0];assert row['outcome']==outcome
    if key in ('virtual_null','virtual_status','info_count','unknown_guid','info_null','attr_null'):assert v.RAW_COUNT not in e['calls']
    if key=='collection_count':assert r['virtual_collection_complete'] and v.RAW_ITEM not in e['calls']

@pytest.mark.parametrize('count',[-1,9,100000])
def test_count_bound_stops_before_items(virtual_env,count):
    e=virtual_env;e['collection_count']=count;r=e['run_virtual']()
    assert r['status']=='error' and not r['readback_verified'] and v.RAW_ITEM not in e['calls']
    assert r['before']['selected'][0]['count_call']['outputs']['count']==count

@pytest.mark.parametrize('count',[2,0xFFFFFFFF])
def test_invalid_typeinfo_count_stops(virtual_env,count):
    e=virtual_env;e['info_count']=count;r=e['run_virtual']();assert r['status']=='error'
    assert v.RAW_INFO not in e['calls'] and r['messages']['disconnected']

@pytest.mark.parametrize('name',[v.RAW_VIRTUAL,v.RAW_INFO_COUNT,v.RAW_INFO,v.RAW_ATTR,v.RAW_DOC,v.RAW_COUNT,v.RAW_ITEM])
def test_com_failures_keep_partial_outputs_and_release_attributes(virtual_env,name):
    e=virtual_env;e['raw_fail']=name;r=e['run_virtual']();assert r['readback_verified'],r
    assert not r['virtual_collection_complete']
    if name in (v.RAW_ATTR,v.RAW_DOC,v.RAW_COUNT,v.RAW_ITEM):assert e['releases']==2
    assert r['messages']['disconnected']

@pytest.mark.parametrize('name',[v.RAW_INFO_COUNT,v.RAW_INFO,v.RAW_ATTR,v.RAW_DOC,v.RAW_COUNT,v.RAW_ITEM])
def test_status1_never_promotes_outputs_to_complete(virtual_env,name):
    e=virtual_env;e['raw_status']=(name,1);r=e['run_virtual']();assert r['readback_verified'],r
    assert not r['virtual_collection_complete']
    if name==v.RAW_ATTR:assert e['releases']==2

@pytest.mark.parametrize('status',[True,None,2,-2147467259])
def test_unsupported_status_stops_without_fallback(virtual_env,status):
    e=virtual_env;e['virtual_status']=status;r=e['run_virtual']();assert r['status']=='error'
    assert e['calls'].count(v.RAW_VIRTUAL)==1 and v.RAW_INFO_COUNT not in e['calls']

@pytest.mark.parametrize('kind',['event','source','runtime'])
def test_typeattr_release_even_after_unsafe_return_and_raw_evidence_kept(virtual_env,kind):
    e=virtual_env
    def hook(name):
        if name!=v.RAW_ATTR:return
        if kind=='event':e['session'].state['event_count']=1
        elif kind=='source':e['digest']='b'*64
        else:e['runtime_bad']=True
    e['hook']=hook
    def runtime():
        if e.get('runtime_bad'):raise ValueError('runtime drift')
    r=e['run_virtual'](runtime_check=runtime);assert r['status']=='error' and not r['readback_verified']
    row=r['before']['selected'][0]['collection_metadata']
    assert row['attribute_call']['returned'] and row['attribute_call']['outputs']['guid']==v.COLLECTION_IID
    assert row['attribute_release']['returned'] and e['releases']==1 and v.RAW_DOC not in e['calls']


def test_second_capture_mismatch_preserves_both(virtual_env):
    e=virtual_env
    def hook(name):
        if name==v.RAW_VIRTUAL and e['calls'].count(name)==2:e['collection_count']=1
    e['hook']=hook;r=e['run_virtual']();assert r['status']=='error' and not r['readback_verified']
    assert r['before']['selected'][0]['count']==2 and r['after']['selected'][0]['count']==1


def test_new_mode_requires_only_pinned_anchor_before_native(virtual_env):
    e=virtual_env;r=e['run'](observation_mode='virtual_features')
    assert r['status']=='error' and not e['calls']


def test_real_local_vendor_and_standard_metadata_preflight(monkeypatch):
    try:module=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    except ImportError:pytest.skip('Optional installed CAM metadata unavailable')
    monkeypatch.setattr(bridge,'_load_type_library',lambda p:module)
    assert v.preflight('metadata-only')['maximum_members']==8


def test_exact_eight_member_bound_is_complete(virtual_env):
    e=virtual_env;e['collection_count']=8;r=e['run_virtual']();assert r['readback_verified'] and r['virtual_collection_complete']
    assert [x['index'] for x in r['before']['selected'][0]['members']]==list(range(8))
    assert e['calls'].count(v.RAW_ITEM)==16 and e['releases']==18

def test_new_abi_rejection_precedes_bootstrap(virtual_env,monkeypatch):
    def reject(tlb):raise ValueError('declared getter ABI changed')
    monkeypatch.setattr(v,'preflight',reject);e=virtual_env;r=e['run_virtual']()
    assert r['status']=='error' and not e['calls']

def test_release_failure_is_retained_and_stops(virtual_env,monkeypatch):
    original=v._member
    def release_failure(obj,name,*args):
        if name==v.RAW_RELEASE:raise ValueError('release failed')
        return original(obj,name,*args)
    monkeypatch.setattr(v,'_member',release_failure);e=virtual_env;r=e['run_virtual']()
    assert r['status']=='error' and not r['readback_verified']
    row=r['before']['selected'][0]['collection_metadata']
    assert row['attribute_call']['outputs']['guid']==v.COLLECTION_IID
    assert row['attribute_release']['attempted'] and not row['attribute_release']['returned']
    assert 'issue' in row['attribute_release'] and v.RAW_DOC not in e['calls']
