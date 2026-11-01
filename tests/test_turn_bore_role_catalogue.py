import importlib.util,os,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).parents[1])))
sys.path.insert(0,str(ROOT))
P=Path(__file__).parents[1]/'scripts/sw_cam_turn_bore_role_catalogue.py'
spec=importlib.util.spec_from_file_location('bore_role_catalogue_under_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def constants(rough=105,finish=106):
    return SimpleNamespace(CW_TURN_OP_ROUGH_BORE=rough,CW_TURN_OP_FINISH_BORE=finish,CW_TURN_OP_ROUGH_TURN=101,CW_TURN_OP_FINISH_TURN=102)


def test_uses_declared_bore_constants_not_numeric_literals():
    rows=m.resolve_roles(constants(),['rough_bore','finish_bore'])
    assert [x['resolved_native_value'] for x in rows]==[105,106]
    assert [x['enum_symbol'] for x in rows]==['CW_TURN_OP_ROUGH_BORE','CW_TURN_OP_FINISH_BORE']

@pytest.mark.parametrize('roles',[[1,2],['rough_turn','finish_turn'],['rough_bore'],['finish_bore','rough_bore'],['rough_bore','rough_bore'],('rough_bore','finish_bore')])
def test_bore_intent_rejects_wrong_roles_before_native(roles):
    with pytest.raises(ValueError):m.resolve_roles(constants(),roles)

@pytest.mark.parametrize('rough,finish',[(101,106),(105,102),(105,105),(True,106),(105,False),(0,106),(-1,106),(105,'106')])
def test_invalid_or_turn_alias_metadata_rejected(rough,finish):
    with pytest.raises(ValueError):m.resolve_roles(constants(rough,finish),list(m.ROLE_SYMBOLS))

@pytest.mark.parametrize('actual,role',[(101,'rough_bore'),(102,'finish_bore'),(106,'rough_bore'),(105,'finish_bore'),(True,'rough_bore')])
def test_wrong_operation_readback_blocks_progress(actual,role):
    with pytest.raises(ValueError):m.check_operation_role(actual,role,constants())


def test_matching_named_readback():
    m.check_operation_role(105,'rough_bore',constants());m.check_operation_role(106,'finish_bore',constants())


def test_catalogue_calls_use_resolved_values():
    log=[];records=[];owner=object();roles=m.resolve_roles(constants(),list(m.ROLE_SYMBOLS))
    def read(obj,name,*args):
        assert obj is owner;log.append((name,args))
        if name=='IGetAllDefaultOperations':return ['Default']
        if name=='GetTdbIdForDefaultOperation':return 51 if args[0]==105 else 52
        raise AssertionError(name)
    r=m.read_catalogues(owner,roles,read=read,record=lambda k,v:records.append((k,v)))
    assert [args[0] for name,args in log if name=='IGetAllDefaultOperations']==[105,106]
    assert r['rough_bore']['entries']==[{'name':'Default','default_operation_id':51}]
    assert r['finish_bore']['resolved_native_value']==106 and len(records)==4
    assert r['rough_bore']['operation_type']==105 and r['finish_bore']['operation_type']==106


def test_empty_catalogue_not_invented_or_looked_up():
    log=[]
    r=m.read_catalogues(object(),m.resolve_roles(constants(),list(m.ROLE_SYMBOLS)),read=lambda obj,n,*a:log.append(n) or [],record=lambda *_:None)
    assert all(not x['entries'] and not x['unique_default_available'] for x in r.values())
    assert log==['IGetAllDefaultOperations','IGetAllDefaultOperations']


class Session:
    def __init__(self,*_):self.active=False;self.disconnected=False
    def __enter__(self):self.active=True;return self
    def __exit__(self,*_):self.active=False;self.disconnected=True
    def summary(self):return dict(active=self.active,subscribed=True,disconnected=self.disconnected,event_count=0)


def lifecycle(monkeypatch,*,wrong_feature=False,drift=False,fail_catalogue=False):
    from copy import deepcopy
    log=[];saved=[];sw=object();owner=object()
    state=dict(type=1,needs_save=False,path='part',title='part')
    inv=dict(operations=[dict(type=7,counts=[40]),dict(type=8,counts=[19]),dict(type=1,counts=[97]),dict(type=2,counts=[43])])
    p=dict(process_id=7,expected_document_path='part',expected_source_sha256='sha',addin_clsid='clsid',typelib_path='tlb',expected_feature_native_id=8)
    plan=dict(pins=[],reference=dict(inventory=inv,feature_header={}),roles=m.resolve_roles(constants(),list(m.ROLE_SYMBOLS)))
    r=dict(phase='prepared',status='prepared',observations=[],mutation_attempted=False,readback_verified=False)
    monkeypatch.setattr(m,'document_snapshot',lambda _:deepcopy(state))
    monkeypatch.setattr(m,'check_document_target',lambda *a,**k:None)
    monkeypatch.setattr(m,'_file_hash',lambda _:'sha')
    monkeypatch.setattr(m.common,'_check',lambda _:None)
    monkeypatch.setattr(m,'CamMessageSession',Session)
    monkeypatch.setattr(m,'_typed',lambda x,*_:x)
    def member(obj,name,*args):
        log.append((name,args))
        if name=='GetProcessID':return 7
        if name in ('GetAddInObject','GetCWApp'):return object()
        if name=='IGetAllDefaultOperations':
            if fail_catalogue:raise RuntimeError('reader failed')
            return ['Default']
        if name=='GetTdbIdForDefaultOperation':return args[0]+100
        raise AssertionError(name)
    monkeypatch.setattr(m,'_member',member)
    monkeypatch.setattr(m.previous.turn_context,'_context',lambda *_:(None,object(),None,object(),None))
    inventories=[]
    def inventory(*_):
        value=deepcopy(inv)
        if inventories and drift:value['operations'][0]['counts']=[39]
        inventories.append(value);return value
    monkeypatch.setattr(m.previous.turn_context,'_inventory',inventory)
    monkeypatch.setattr(m.previous,'selected',lambda *a:(dict(feature_native_id=9 if wrong_feature else 8),owner))
    result=m.inspect(sw,p,plan,r,lambda:saved.append(deepcopy(r)))
    return result,log,saved


def test_native_lifecycle_is_read_only_and_closes_events(monkeypatch):
    r,log,saved=lifecycle(monkeypatch)
    assert r['status']=='observed' and r['readback_verified']
    assert r['messages']['disconnected'] and not r['messages']['active']
    assert [a[0] for n,a in log if n=='IGetAllDefaultOperations']==[105,106]
    assert not r['mutation_attempted'] and saved[-1]['status']=='observed'
    assert set(n for n,_ in log)<={'GetProcessID','GetAddInObject','GetCWApp','IGetAllDefaultOperations','GetTdbIdForDefaultOperation'}


def test_wrong_feature_stops_before_catalogue(monkeypatch):
    r,log,_=lifecycle(monkeypatch,wrong_feature=True)
    assert r['status']=='error' and not r['readback_verified']
    assert not any(n=='IGetAllDefaultOperations' for n,_ in log)
    assert r['messages']['disconnected']


def test_inventory_drift_blocks_observed_status(monkeypatch):
    r,_,_=lifecycle(monkeypatch,drift=True)
    assert r['status']=='error' and not r['readback_verified']
    assert r['messages']['disconnected']


def test_native_read_exception_keeps_failed_stage_and_cleanup(monkeypatch):
    r,log,saved=lifecycle(monkeypatch,fail_catalogue=True)
    assert r['status']=='error' and r['failed_phase']=='named_bore_catalogues'
    assert r['messages']['disconnected'] and saved[-1]['readback_verified'] is False
    assert sum(n=='IGetAllDefaultOperations' for n,_ in log)==1


def test_audit_uses_generated_metadata(monkeypatch):
    from scripts import sw_cam_comtypes
    monkeypatch.setattr(m.previous,'audit',lambda *a:dict(abi_verified=True,methods=[{'member':'IGetAllDefaultOperations'}]))
    monkeypatch.setattr(sw_cam_comtypes,'_load_type_library',lambda _:constants(205,206))
    a=m.audit('tlb',{'path':'p','sha256':'s'},list(m.ROLE_SYMBOLS))
    assert a['native_called'] is False
    assert [r['resolved_native_value'] for r in a['roles']]==[205,206]



def payload(legacy=False):
    roles=m.resolve_roles(constants(),list(m.ROLE_SYMBOLS));observations=[]
    def record(key,value):observations.append(dict(key=key,value=value,returned_type=type(value).__name__))
    def read(owner,name,*args):return ('Default',) if name=='IGetAllDefaultOperations' else args[0]+1
    cats=m.read_catalogues(object(),roles,read=read,record=record)
    if legacy:
        for row in cats.values():row['operation_type']=1
    return dict(abi=dict(roles=roles),request=dict(roles=list(m.ROLE_SYMBOLS)),catalogues=cats,observations=observations),roles


def test_new_payload_type_matches_each_declared_role():
    r,roles=payload();assert m.normalize_observed_catalogues(r,roles)==r['catalogues']


def test_legacy_normalization_is_explicit_and_does_not_rewrite_evidence():
    r,roles=payload(True)
    with pytest.raises(ValueError):m.normalize_observed_catalogues(r,roles)
    value=m.normalize_observed_catalogues(r,roles,allow_legacy_operation_type=True)
    assert [value[x]['operation_type'] for x in m.ROLE_SYMBOLS]==[105,106]
    assert all(x['operation_type']==1 for x in r['catalogues'].values())
    assert [value[x]['entries'][0]['default_operation_id'] for x in m.ROLE_SYMBOLS]==[106,107]

@pytest.mark.parametrize('change',['legacy_other','wrong_role','wrong_enum','wrong_resolved','wrong_id','wrong_observed_id','extra_observation','duplicate_observation','wrong_shape'])
def test_normalization_rejects_tampered_or_ambiguous_payload(change):
    r,roles=payload(True)
    row=r['catalogues']['rough_bore']
    if change=='legacy_other':row['operation_type']=2
    elif change=='wrong_role':row['role']='rough_turn'
    elif change=='wrong_enum':row['enum_symbol']='CW_TURN_OP_ROUGH_TURN'
    elif change=='wrong_resolved':row['resolved_native_value']=101
    elif change=='wrong_id':row['entries'][0]['default_operation_id']=999
    elif change=='wrong_observed_id':r['observations'][1]['value']=999
    elif change=='extra_observation':r['observations'].append(dict(key='extra',value=1,returned_type='int'))
    elif change=='duplicate_observation':r['observations'].append(r['observations'][0])
    elif change=='wrong_shape':r['observations'][0]['returned_type']='object'
    with pytest.raises(ValueError):m.normalize_observed_catalogues(r,roles,allow_legacy_operation_type=True)
