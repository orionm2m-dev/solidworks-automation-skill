"""Offline regression of reused append-only Finish and per-feature depth primitives."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import os,sys,pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT))
from scripts import sw_cam_chamfer_insert_defaults as insert
from scripts import sw_cam_chamfer_generate as depth


def before_state():
    ids=list(range(1,26))+[361]
    rows=[dict(native_id=oid,setup_index=0 if i<21 else 1,setup_native_id=93 if i<21 else 94,
        operation_index=i if i<21 else i-21,mill_operation_type=0,linked_feature_ids=[359]if oid==361 else[1000+oid],
        suppressed=False,toolpath_generated=True,toolpath_record_counts=[198]if oid==361 else[10],assigned_tool=dict(native_id=249,diameter=8.))for i,oid in enumerate(ids)]
    return dict(route=dict(operations=rows,operation_counts=[21,5,0],operation_setups=[dict(native_id=93,operation_count=21),dict(native_id=94,operation_count=5),dict(native_id=95,operation_count=0)],
        features=[dict(native_id=359,depth=7.4,radius=8.5),dict(native_id=70,depth=7.6)],units='MM'),
        tools=[dict(native_id=249,diameter=8.,effective_length=21.)],feature=dict(native_id=359,depth=7.4,radius=8.5))


def append(before,oid,fid):
    after=deepcopy(before);anchor=after['route']['operations'][-1]
    after['route']['operations'].append(dict(native_id=oid,setup_index=1,setup_native_id=94,
        operation_index=anchor['operation_index']+1,mill_operation_type=1,linked_feature_ids=[fid],
        suppressed=False,toolpath_generated=False,toolpath_record_counts=[],assigned_tool=dict(native_id=249,diameter=8.)))
    after['route']['operation_counts'][1]+=1;after['route']['operation_setups'][1]['operation_count']+=1
    return after


def test_two_appends_preserve_all26_rows_features_and_shared_tool():
    before=before_state();floor=append(before,800,359)
    assert insert.verify_added(before,floor,800,359,361)['native_id']==800
    wall_before=deepcopy(floor);wall_before['feature']=dict(native_id=70,depth=7.6)
    wall=append(wall_before,801,70)
    assert insert.verify_added(wall_before,wall,801,70,800)['native_id']==801
    assert wall['route']['operations'][:26]==before['route']['operations']
    assert wall['route']['features']==before['route']['features'] and wall['tools']==before['tools']
    assert len(wall['route']['operations'])==28


@pytest.mark.parametrize('fault',['old_path','old_nc','tool249','feature359','new_generated','wrong_link','wrong_setup','wrong_anchor','extra_addition'])
def test_append_rejects_protected_or_unrequested_change(fault):
    before=before_state();after=append(before,800,359)
    if fault=='old_path':after['route']['operations'][0]['toolpath_record_counts']=[11]
    elif fault=='old_nc':after['route']['operations'][0]['NC']=dict(feed=1000.)
    elif fault=='tool249':after['tools'][0]['diameter']=7.9
    elif fault=='feature359':after['route']['features'][0]['depth']=7.6
    elif fault=='new_generated':after['route']['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[1])
    elif fault=='wrong_link':after['route']['operations'][-1]['linked_feature_ids']=[70]
    elif fault=='wrong_setup':after['route']['operations'][-1]['setup_native_id']=93
    elif fault=='wrong_anchor':after['route']['operations'][-2],after['route']['operations'][-3]=after['route']['operations'][-3],after['route']['operations'][-2]
    elif fault=='extra_addition':after=append(after,801,70)
    with pytest.raises(ValueError):insert.verify_added(before,after,800,359,361)


@pytest.mark.parametrize('field,value,setter',[('depth_override',True,'SetOverrideMachiningDepth'),('machining_depth',7.6,'SetMachiningDepthValue'),('machining_depth',7.1,'SetMachiningDepthValue')])
def test_exact_per_operation_feature_depth_primitive(monkeypatch,field,value,setter):
    owner=object();feature=object();dispatch=object();calls=[]
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def typed(self,raw,name):assert raw is owner and name=='ICWMillOperation3';return raw
        def dispatch_once(self,call,*,persist_pending):persist_pending();return call()
    backend=object.__new__(depth.NativeBackend);backend.ctx=SimpleNamespace(guard=lambda:Guard())
    backend.target=lambda g:(owner,feature);backend.feature_dispatch=lambda g,f:dispatch if f is feature else None
    monkeypatch.setattr(depth,'_member',lambda *args:calls.append(args) or 0)
    spec=next(s for s in depth.FIELDS if s[0]==field)
    assert backend.write_field(spec,value,lambda:calls.append('pending'))==0
    assert calls==['pending',(owner,setter,dispatch,value)]


def test_depth_readback_requires_effective_override_and_stored_values():
    owner=object();feature=object();dispatch=object();reads=[]
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def typed(self,raw,name):assert raw is owner and name in ('ICWMillOperation','ICWMillOperation3');return raw
        def read(self,raw,name,arg):
            assert raw is owner and arg is dispatch;reads.append(name)
            return {'GetMachiningDepth':7.6,'GetOverrideMachiningDepth':True,'GetMachiningDepthValue':7.6}[name]
    backend=object.__new__(depth.NativeBackend);backend.ctx=SimpleNamespace(guard=lambda:Guard());backend.target=lambda g:(owner,feature);backend.feature_dispatch=lambda g,f:dispatch
    assert backend.depth_readback()==dict(machining_depth=7.6,override=True,stored_depth=7.6)
    assert reads==['GetMachiningDepth','GetOverrideMachiningDepth','GetMachiningDepthValue']
