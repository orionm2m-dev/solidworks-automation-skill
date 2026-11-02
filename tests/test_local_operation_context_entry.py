from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module
R=add_runtime()
context=required_module('sw_cam_local_operation_context')
entry=required_module('sw_cam_local_startpoint')
_fixture=required_test_module('test_local_operation_group')
fixture,Journal=_fixture.fixture,_fixture.Journal


def context_fixture():
    baseline,plan,_,_=fixture();document=dict(path='part.sldprt',needs_save=False)
    for p in baseline['parameters']:
        p['levels']=dict(levels=dict(machining_depth_native=4.4,override_machining_depth=False,
            toolpath_parameters=dict(first_cut_Z_type_raw=1)),setup=dict(origin_native=[0.,0.,26.]))
    inventory=[dict(owner_setup_native_id=69,header=deepcopy(h))for h in baseline['binding']['features'].values()]
    features=[dict(owner_setup_native_id=69,header=dict(native_id=f,depth_native=3.4))for f in (900,901)]
    for f in features:
        next(x for x in inventory if x['header']['native_id']==f['header']['native_id'])['header']=deepcopy(f['header'])
    # Saved old parameter snapshot deliberately has only the previously selected headers.
    baseline['binding']['features'].pop('900');baseline['binding']['features'].pop('901')
    observations=[dict(feature_native_id=f['header']['native_id'],header=deepcopy(f['header']),
        defaults_catalogue=[dict(operation_type=k,entries=[dict(name='actual'+str(k),default_operation_id=10+k)])for k in (0,1)])for f in features]
    loaded=dict(guide_parameters=dict(expected_parameters=baseline,document=document),root_pocket_full_features=features,
        root_pocket_specs=[{'profile':'left'},{'profile':'right'}],root_pocket_native_inventory=inventory)
    c=dict(authority_kind='saved_serial_flat_tool_unassigned',deep_loaded=loaded,source_sha256='a'*64,
        state=dict(saved_file_sha256='a'*64,document=document),serial_flat_catalogue=[dict(native_id=680+i)for i in range(21)],
        serial_flat_tool_native_id=700,pins=[],offline_export_proof_pins=[],parent_pin={'sha256':'b'*64})
    recipe=dict(rows=[dict(r,startpoint_anchor_world_xy_mm=[-8.,10.]if i<2 else[8.,10.])for i,r in enumerate(plan['rows'])])
    choices={k:{'selection':'unique_native_default'}for k in context.engine.KEYS};feed={k:[]for k in context.engine.KEYS}
    return c,recipe,observations,choices,feed,plan['tool']


def project(monkeypatch,c,recipe,observed,choices,feed,tool):
    monkeypatch.setattr(context,'tool_dimensions',lambda c,b:dict(generic=tool))
    def verify(feature,spec,*,native_id):assert feature['header']['native_id']==native_id;return dict(full_native_profile_verified=True)
    return context.project_context(c,recipe,observed,choices,verify_feature=verify,feed_policy=feed)


def test_context_projects_actual_ids_without_modifying_parent(monkeypatch):
    args=context_fixture();original=deepcopy(args[0]);loaded=project(monkeypatch,*args)
    assert args[0]==original and not loaded['dispatch_ready']
    assert [r['feature_native_id']for r in loaded['local_plan']['rows']]==[900,900,901,901]
    assert loaded['configuration_tool']['native_id']==700
    assert all(r['expected_levels']['levels']['machining_depth_native']==3.4 for r in loaded['local_plan']['rows'])
    assert loaded['local_plan']['rows'][0]['entry_point_native']==[-8.,10.,0.]
    assert set(loaded['guide_parameters']['expected_parameters']['binding']['features'])=={'80','81','900','901'}


@pytest.mark.parametrize('problem',['partial','dirty','wrongsha','wrongtool','wrongheader','missingkind','ambiguous','override'])
def test_context_rejects_untrusted_or_ambiguous_inputs(monkeypatch,problem):
    c,r,o,ch,f,t=context_fixture()
    if problem=='partial':c['authority_kind']='uncertain'
    elif problem=='dirty':c['state']['document']['needs_save']=True
    elif problem=='wrongsha':c['source_sha256']='x'*64
    elif problem=='wrongtool':c['serial_flat_tool_native_id']=999
    elif problem=='wrongheader':o[0]['header']['depth_native']=4.4
    elif problem=='missingkind':o[0]['defaults_catalogue'].pop()
    elif problem=='ambiguous':o[0]['defaults_catalogue'][0]['entries'].append(dict(name='other',default_operation_id=88))
    else:c['deep_loaded']['guide_parameters']['expected_parameters']['parameters'][-2]['levels']['levels']['override_machining_depth']=True
    with pytest.raises(ValueError):project(monkeypatch,c,r,o,ch,f,t)


def test_explicit_default_selects_only_observed_pair():
    catalog=[dict(operation_type=0,entries=[dict(name='a',default_operation_id=1),dict(name='b',default_operation_id=2)])]
    assert context.select_default(catalog,0,dict(name='b',default_operation_id=2))==dict(default_operation_name='b',default_operation_id=2)
    with pytest.raises(ValueError):context.select_default(catalog,0,dict(name='a',default_operation_id=2))


class PointBackend:
    def __init__(self):
        self.ctx=object();self.typelib_path='metadata';self.loaded={};self.calls=[]
        self.startpoints=dict(read_complete=True,collection_interface_verified=True,list_is_null=False,count=0,rows=[],entry_type=4)
    def refresh_dirty(self):pass
    def capture_snapshot(self,*a,**k):return dict(binding={'unchanged':True},parameters=[dict(startpoints=deepcopy(self.startpoints))])

class FakeEntry:
    def __init__(self,b,t,xyz):self.backend=b;self.xyz=xyz;self.point=object();self.position=object();self.value=[0.,0.,0.]
    def mutate(self,name,pending):pending();self.backend.calls.append(name);return 0
    def create_point(self,pending):return self.mutate('create_point',pending)
    def created_type(self):return 1
    def create_position(self,pending):return self.mutate('create_position',pending)
    def position_state(self):return self.value
    def set_point_coordinates(self,pending):v=self.mutate('coordinates',pending);self.value=deepcopy(self.xyz);return v
    def set_point_position(self,pending):return self.mutate('position',pending)
    def point_state(self):return self.value
    def attach_point(self,member,pending):
        v=self.mutate(member,pending)
        if member=='SetStartPointList':self.backend.startpoints.update(count=1,rows=[dict(type_raw=1,position_is_null=False,position_native=self.value)])
        return v
    def collection_state(self):return dict(count=1,type_raw=1,position_native=self.xyz)


def test_six_entry_actions_exact_then_fresh_readback(monkeypatch):
    b=PointBackend();j=Journal();j.report['actions']={};t=dict(operation_native_id=1000,operation_type=0)
    monkeypatch.setattr(entry,'_is_comtypes_pointer',lambda value:True)
    result=entry.apply_entry(b,j,t,[-8.,10.,0.],adapter_class=FakeEntry)
    assert b.calls==['create_point','create_position','coordinates','position','Add','SetStartPointList']
    assert len(j.report['actions'])==6 and result['startpoints']['count']==1


def test_nonempty_list_cannot_be_reinitialized(monkeypatch):
    b=PointBackend();b.startpoints.update(count=1,rows=[{}]);j=Journal();j.report['actions']={}
    with pytest.raises(ValueError):entry.apply_entry(b,j,dict(operation_native_id=1000),[0.,0.,0.],adapter_class=FakeEntry)
    assert b.calls==[] and not j.report['actions']


@pytest.mark.parametrize('point',[[0,0,float('nan')],[True,0,0],[0,0]])
def test_strict_native_point_validation(point):
    with pytest.raises(ValueError):entry.EntryAdapter(PointBackend(),dict(operation_type=0),point)


def test_entry_uses_actual_groupjournal_return_contract(tmp_path,monkeypatch):
    from scripts import sw_cam_deep_guide_group as writer
    b=PointBackend();report=dict(scope='test',status='pending',phase='entry',source_path=str(tmp_path/'source.sldprt'),source_sha256='a'*64,actions={})
    j=writer.Journal(report,tmp_path/'receipt.json',tmp_path/'once.json');j.create()
    monkeypatch.setattr(entry,'_is_comtypes_pointer',lambda value:True)
    result=entry.apply_entry(b,j,dict(operation_native_id=1000,operation_type=0),[-8.,10.,0.],adapter_class=FakeEntry)
    assert result['startpoints']['count']==1 and len(report['actions'])==6 and j.claimed
    assert all(x['native_return']['python_type']=='int' for x in report['actions'].values())


def test_baseline_projection_precedes_native_default_read(monkeypatch):
    c,r,o,ch,f,t=context_fixture();original=deepcopy(c)
    monkeypatch.setattr(context,'tool_dimensions',lambda *a:dict(generic=t))
    loaded=context.project_context(c,r,None,ch,verify_feature=lambda *a,**k:{'checked':True},feed_policy=f)
    assert c==original and 'local_plan'not in loaded and loaded['dispatch_ready']is False
    assert len(loaded['guide_parameters']['expected_parameters']['binding']['features'])==4
