from copy import deepcopy
from pathlib import Path
import os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,os.environ.get('SOLIDWORKS_SKILL_ROOT',str(ROOT)))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_turn_bore_catalogue as m

def catalogue_case(raw,ids=None):
    calls=[];observed=[]
    def read(obj,name,*args):
        calls.append((name,args))
        return raw[args[0]] if name=='IGetAllDefaultOperations' else (ids or {}).get((args[0],args[1]),args[0]*100)
    return read,calls,observed

def test_two_catalogues_preserve_type_and_exact_name_id():
    read,calls,observed=catalogue_case({1:['ID rough'],2:'ID finish'},{(1,'ID rough'):51,(2,'ID finish'):62})
    result=m.read_catalogues(object(),read=read,record=lambda k,v:observed.append((k,v)))
    assert result['1']['operation_type']==1 and result['2']['operation_type']==2
    assert result['1']['entries']==[{'name':'ID rough','default_operation_id':51}]
    assert result['2']['entries']==[{'name':'ID finish','default_operation_id':62}]
    assert len(calls)==4 and len(observed)==4 and all(not x['selection_performed'] for x in result.values())

@pytest.mark.parametrize('empty',[[],()])
def test_empty_catalogue_is_observed_not_invented(empty):
    read,calls,observed=catalogue_case({1:empty,2:empty})
    result=m.read_catalogues(object(),read=read,record=lambda k,v:observed.append((k,v)))
    assert all(not x['entries'] and not x['unique_default_available'] for x in result.values()) and len(calls)==2

@pytest.mark.parametrize('raw',[None,42,True,['same','same'],[''],['x']*33,['a',3]])
def test_invalid_catalogue_stops_without_insert(raw):
    read,calls,observed=catalogue_case({1:raw,2:['other']})
    with pytest.raises(ValueError):m.read_catalogues(object(),read=read,record=lambda k,v:observed.append((k,v)))
    assert calls==[('IGetAllDefaultOperations',(1,))] and observed[0][1]==raw

@pytest.mark.parametrize('identity',[0,-1,True,1.0,'1'])
def test_invalid_default_id_recorded_and_rejected(identity):
    read,calls,observed=catalogue_case({1:['rough'],2:['finish']},{(1,'rough'):identity})
    with pytest.raises(ValueError):m.read_catalogues(object(),read=read,record=lambda k,v:observed.append((k,v)))
    assert observed[-1][1] is identity and len(calls)==2

@pytest.mark.parametrize('fault',[None,'binding','inventory','event','read','disconnect'])
def test_native_engine_no_mutation_and_always_cleanup(monkeypatch,fault):
    token=object();doc={'path':'C:/example/part.SLDPRT','title':'part.SLDPRT','type':1,'needs_save':False}
    p=dict(process_id=7,expected_document_path=doc['path'],expected_source_sha256='a'*64,addin_clsid='x',typelib_path='x',setup_index=0,operation_index=0,expected_operation_native_id=40,expected_operation_type=9)
    ref={'inventory':{'operation_count':9},'feature_header':{}};report={'status':'prepared','phase':'prepared','observations':[],'readback_verified':False};copies=[];count={'binding':0,'inventory':0}
    class Session:
        active=False;disconnected=False
        def __init__(self,*a):pass
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False;self.disconnected=True
        def summary(self):return dict(active=self.active,disconnected=self.disconnected,subscribed=True,event_count=int(fault=='event' and self.active),disconnect_errors=['x'] if fault=='disconnect' and self.disconnected else [])
    def member(obj,name,*a):
        if name=='GetProcessID':return 7
        if name in ('GetAddInObject','GetCWApp'):return token
        if fault=='read':raise RuntimeError('read failed')
        if name=='IGetAllDefaultOperations':return ['default']
        if name=='GetTdbIdForDefaultOperation':return 5
        raise AssertionError(name)
    def selected(*a):
        count['binding']+=1
        return {'id':2 if fault=='binding' and count['binding']==2 else 1},token
    def inventory(*a):
        count['inventory']+=1
        return {'operation_count':10 if fault=='inventory' and count['inventory']==2 else 9}
    monkeypatch.setattr(m,'_member',member);monkeypatch.setattr(m,'_typed',lambda *a:token)
    monkeypatch.setattr(m,'document_snapshot',lambda x:deepcopy(doc));monkeypatch.setattr(m,'check_document_target',lambda *a,**kw:None)
    monkeypatch.setattr(m,'_file_hash',lambda x:'a'*64);monkeypatch.setattr(m.common,'_check',lambda p:None)
    monkeypatch.setattr(m,'CamMessageSession',Session);monkeypatch.setattr(m,'selected',selected)
    monkeypatch.setattr(m.turn_context,'_context',lambda *a:(doc,token,token,token,token));monkeypatch.setattr(m.turn_context,'_inventory',inventory)
    result=m.inspect(token,p,ref,[],report,lambda:copies.append(deepcopy(report)))
    assert result['readback_verified'] is (fault is None)
    assert not result['messages']['active'] and result['messages']['disconnected']
    assert copies[-1]==result

def test_no_mutation_member_is_callable():
    assert not {'InsertOperation','GenerateToolpath','GenerateOpPlan','SetTool','SaveActiveDocument'}&m.READ_MEMBERS
