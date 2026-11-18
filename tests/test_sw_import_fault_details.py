import importlib.util
from pathlib import Path
from types import SimpleNamespace as N
import pytest
from scripts import sw_import_fault_details as m

def test_face_metadata_is_readonly_and_keeps_vertices(monkeypatch):
    vertex=N(GetPoint=lambda:[1.,2.,3.])
    edge=N(GetStartVertex=lambda:vertex,GetEndVertex=lambda:None)
    face=N(GetType=lambda:2,GetBox=lambda:[0.,0.,0.,1.,1.,1.],GetArea=lambda:1e-12,
        GetSurface=lambda:N(Identity=lambda:4001),GetEdgeCount=lambda:1,GetEdges=lambda:[edge])
    monkeypatch.setattr(m,'_interface',lambda obj,iid:face)
    row=m._entity_details(face)
    assert row['face_interface_confirmed'] and row['entity_type']==2
    assert row['area_m2']==1e-12 and row['surface_identity']==4001
    assert row['edges']==[{'index':0,'start_m':[1.,2.,3.],'end_m':None}]


def test_entity_metadata_failure_preserves_fault(monkeypatch):
    def fail(*args):raise RuntimeError('no face interface')
    monkeypatch.setattr(m,'_interface',fail)
    row=m._entity_details(object())
    assert row['present'] and not row['face_interface_confirmed']
    assert 'face_query_issue' in row

@pytest.mark.parametrize('duplicate',[True,False])
def test_fault_entities_deduplicate_by_native_identity(monkeypatch,duplicate):
    import win32com.client
    entities=[object(),object()]
    if duplicate:entities[1]=entities[0]
    faults=N(Count=2,ErrorCode=lambda i:21,Entity2=lambda i:entities[i])
    body=N(Check3=faults);donor=N(GetBodies2=lambda kind,visible:[body] if kind==0 else [])
    sw=N(IsSame=lambda a,b:int(a is b));report={};saved=[]
    monkeypatch.setattr(win32com.client,'Dispatch',lambda x:x)
    monkeypatch.setattr(m,'_entity_details',lambda entity:{'present':True})
    m._read_faults(sw,donor,report,saved.append)
    assert report['total_fault_count']==2 and report['unique_fault_entity_count']==(1 if duplicate else 2)
    assert [x['unique_entity_index'] for x in report['bodies'][0]['faults']]==([0,0] if duplicate else [0,1])
    assert saved.count('fault_code_read')==2


def test_zero_fault_after_failed_repair_is_reported_without_retry():
    body=N(Check3=N(Count=0));donor=N(GetBodies2=lambda kind,visible:[body] if kind==0 else [])
    report={};m._read_faults(N(),donor,report,lambda phase:None)
    assert report['total_fault_count']==0 and not report['unique_fault_entities']


def test_null_entity_keeps_error_code():
    body=N(Check3=N(Count=1,ErrorCode=lambda i:21,Entity2=lambda i:None))
    donor=N(GetBodies2=lambda kind,visible:[body] if kind==0 else [])
    report={};m._read_faults(N(),donor,report,lambda phase:None)
    assert report['bodies'][0]['faults']==[{'index':0,'error_code':21,'entity_present':False}]

@pytest.mark.parametrize('count',[-1,33,True])
def test_unbounded_faults_rejected(count):
    body=N(Check3=N(Count=count));donor=N(GetBodies2=lambda kind,visible:[body] if kind==0 else [])
    with pytest.raises(ValueError):m._read_faults(N(),donor,{},lambda phase:None)
