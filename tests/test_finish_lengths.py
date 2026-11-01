import importlib.util
from pathlib import Path
from copy import deepcopy
import pytest

spec=importlib.util.spec_from_file_location('finish_lengths_under_test',Path(__file__).parents[1]/'scripts/sw_cam_finish_lengths.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def context():
    row=dict(setup_index=0,setup_native_id=93,operation_index=8,native_id=320,mill_operation_type=1,suppressed=False,toolpath_generated=True,linked_feature_ids=[79],toolpath_record_counts=[2284],assigned_tool={'native_id':273})
    return {'fresh_finish_result':dict(native_id=320,feature_native_id=79,generated=True,record_counts=[2284]),'state':dict(operation_setups=[dict(index=0,native_id=93,operation_count=1)],operations=[row])}


def test_exact_three_native_scalars_recorded_before_validation():
    calls=[];observed=[]
    def read(op,name):calls.append(name);return {'ToolpathFeedLength':10.,'ToolpathRapidLength':20.,'ToolpathTotalLength':30.}[name]
    result=m.read_lengths(object(),read=read,record=lambda k,v:observed.append((k,v)))
    assert calls==[r[1] for r in m.FIELDS] and len(observed)==3
    assert result==dict(feed_length_native=10.,rapid_length_native=20.,total_length_native=30.)


@pytest.mark.parametrize('bad',[True,None,'12',float('nan'),float('inf'),-1.,[],{}])
def test_unsupported_length_is_preserved_and_stops_next_getter(bad):
    calls=[];observed=[]
    def read(op,name):calls.append(name);return bad
    with pytest.raises(ValueError):m.read_lengths(None,read=read,record=lambda k,v:observed.append((k,v)))
    assert calls==['ToolpathFeedLength'] and observed[0][1] is bad


@pytest.mark.parametrize('change',[{'operation_native_id':319},{'feature_native_id':80}])
def test_wrong_target_refused(change):
    p=dict(operation_native_id=320,feature_native_id=79);p.update(change)
    with pytest.raises(ValueError):m.authority(context(),p)


@pytest.mark.parametrize('generated,count',[(False,[]),(True,[]),(True,[0]),(True,[True]),(True,[1,2])])
def test_ungenerated_or_invalid_count_cannot_authorize(generated,count):
    c=context();c['fresh_finish_result'].update(generated=generated,record_counts=count)
    with pytest.raises(ValueError):m.authority(c,dict(operation_native_id=320,feature_native_id=79))


def test_generated_authority_matches_saved_inventory():
    c=context();assert m.authority(c,dict(operation_native_id=320,feature_native_id=79))['record_counts']==[2284]
    c['state']['operations'][0]['toolpath_record_counts']=[2283]
    with pytest.raises(ValueError):m.authority(c,dict(operation_native_id=320,feature_native_id=79))


def test_projection_keeps_all_ordered_inventory_and_tool_ids():
    c=context();r=m.projected_inventory(c['state']);assert r['operations'][0]['tool_native_id']==273
    c['state']['operations'][0]['assigned_tool']=None
    assert m.projected_inventory(c['state'])['operations'][0]['tool_native_id'] is None


def fake_observation(monkeypatch,*,drift=False,bad=False):
    c=context();expected=m.projected_inventory(c['state']);snapshots=[deepcopy(expected),deepcopy(expected)]
    if drift:snapshots[1]['operations'][0]['toolpath_record_counts']=[2]
    calls=[]
    def inventory(*a,**kw):calls.append('inventory');return snapshots.pop(0)
    def binding(*a,**kw):calls.append('binding');return {'native_id':320},object(),object()
    monkeypatch.setattr(m,'inventory',inventory);monkeypatch.setattr(m.protected,'binding',binding)
    class Batch:
        def read(self,obj,name):calls.append(name);return float('nan') if bad else 1.
        def typed(self,*a):raise AssertionError('unexpected typed call in isolated orchestration test')
    report={'scalar_observations':[]};p=dict(operation_native_id=320,feature_native_id=79)
    return lambda:m.observe(Batch(),None,None,c,p,report,lambda:None),calls,report


def test_before_after_inventory_and_exact_three_scalars(monkeypatch):
    call,calls,report=fake_observation(monkeypatch);call()
    assert calls==['inventory','binding']+[r[1] for r in m.FIELDS]+['binding','inventory']
    assert report['inventory_before']==report['inventory_after'] and len(report['scalar_observations'])==3


def test_changed_inventory_cannot_be_success(monkeypatch):
    call,_,report=fake_observation(monkeypatch,drift=True)
    with pytest.raises(ValueError):call()
    assert report['inventory_before']!=report['inventory_after']


def test_bad_native_scalar_prevents_following_reads(monkeypatch):
    call,calls,report=fake_observation(monkeypatch,bad=True)
    with pytest.raises(ValueError):call()
    assert calls==['inventory','binding','ToolpathFeedLength'] and len(report['scalar_observations'])==1


@pytest.mark.parametrize('name',['GenerateToolpath','SetTool','Save','Save3','IGetAllTools','GetRecordAtIndex','GetEnumRecords'])
def test_mutators_and_expensive_unrelated_getters_not_allowed(name):
    assert name not in m.MEMBERS


def request(tmp_path):
    p=dict(process_id=47168,operation_native_id=320,feature_native_id=79,addin_clsid='{00000000-0000-0000-0000-000000000000}',module_sha256=m._file_hash(m.__file__))
    for k in m.PARAMS:
        if k.endswith('_path'):p[k]=str(tmp_path/k)
        if k.endswith('_sha256') and k not in p:p[k]='a'*64
    return {'action':'read_saved_finish_lengths','params':p}


@pytest.mark.parametrize('key,value',[('process_id',True),('process_id',0),('operation_native_id',-1),('feature_native_id','79'),('expected_source_sha256','bad'),('module_sha256','0'*64)])
def test_bad_request_rejected_before_loader(tmp_path,key,value):
    r=request(tmp_path);r['params'][key]=value
    with pytest.raises(ValueError):m.validate_request(r)


def test_source_drift_loader_failure_prevents_native_connection(tmp_path,monkeypatch):
    r=request(tmp_path)
    def failed(*a,**kw):raise ValueError('source bytes changed')
    monkeypatch.setattr(m.saved,'load_completed',failed)
    with pytest.raises(ValueError,match='source bytes changed'):m.dispatch_request(r)


def test_real_batch_constructor_accepts64_refuses66(tmp_path):
    files=[]
    for i in range(66):
        f=tmp_path/(str(i)+'.txt');f.write_text('test');files.append(dict(path=str(f),sha256=m._file_hash(f)))
    kw=dict(generated_pin=files[0],progress=lambda *a:None,process_id=47168,expected_document=dict(path=files[0]['path'],title='test',type=1,needs_save=False),source_sha256=files[0]['sha256'],verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None,retained_objects=(object(),),verify_retained_binding=lambda:None,max_native_calls=600)
    batch=m.ReadBatch(object(),'unused',evidence_pins=files[:64],**kw)
    assert not batch._entered
    with pytest.raises(ValueError,match='bounded complete evidence pin list'):m.ReadBatch(object(),'unused',evidence_pins=files,**kw)


def test_completed_writer_retired_but_proof_not_dropped(tmp_path):
    pins=[dict(path=str(tmp_path/name),sha256='a'*64) for name in ['sw_cam_fresh_finish_recipe.py','sw_cam_fresh_finish_field_batch.py','native_read.py']]
    loaded=dict(pins=deepcopy(pins),offline_export_proof_pins=[])
    retired=m.scope_pins(loaded,[])
    assert len(retired)==2 and loaded['pins']==pins[2:] and loaded['offline_export_proof_pins']==pins[:2]


def test_scope_rejects_more_than64_even_after_retirement(tmp_path):
    names=['sw_cam_fresh_finish_recipe.py','sw_cam_fresh_finish_field_batch.py']+[str(i)+'.py' for i in range(66)]
    loaded=dict(pins=[dict(path=str(tmp_path/n),sha256='a'*64) for n in names],offline_export_proof_pins=[])
    with pytest.raises(ValueError,match='Bounded read-only closure'):m.scope_pins(loaded,[])
