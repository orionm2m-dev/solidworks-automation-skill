"""Focused component tests; no application or native mutation is invoked."""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import pytest

ROOT=Path(os.environ.get('SWMCP_RUNTIME_ROOT',str(Path.home()/'.codex/skills/solidworks-automation')))
sys.path.insert(0,str(ROOT))
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('explicit_feature',HERE/'scripts/sw_cam_explicit_island_feature.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)

def recipe():
    return dict(owner_setup_native_id=10,axis_native=[0.,0.,-1.],origin_native=[0.,0.,0.],
        outer_sketch_name='OUTER',island_sketch_names=['ISLAND_A','ISLAND_B','ISLAND_C','ISLAND_D'],
        depth_native=12.,expected_shape=2,expected_attribute_suffix=[])

def baseline():
    return dict(capture_complete=True,feature_count=0,operation_count=0,generated_operation_count=0,
        total_record_count=0,features=[],operations=[],feature_setups=[dict(index=0,native_id=10,
        axis_native=[0.,0.,-1.],origin_native=[0.,0.,0.],feature_ids=[])],
        operation_setups=[dict(index=0,native_id=11,operation_count=0)],unique_tool_count=0,
        sw_reference=dict(feature_tree=[dict(name='Sketch',type='ProfileFeature')],solids=[]))

def header(count=4):
    return dict(native_id=20,owner_setup_native_id=10,volume_type=2,shape=2,suppressed=False,
        axis_native=[0.,0.,-1.],depth_native=12.,taper_angle_native=0.,island_count=count)

def after():
    b=baseline();b['feature_count']=1;b['features']=[dict(native_id=20,setup_native_id=10,
        setup_index=0,feature_index=0,volume_type=2,subtype_raw=0,name='Pocket',suppressed=False)]
    b['feature_setups'][0]['feature_ids']=[20];return b

def test_exact_delta_and_no_promotion():
    p=core.verify_delta(baseline(),after(),header(),recipe())
    assert p['island_count']==4
    assert not p['physical_depth_verified'] and not p['world_profile_placement_verified']
    assert not p['machining_eligible'] and not p['production_qualified']

@pytest.mark.parametrize('key,value',[
    ('owner_setup_native_id',True),('expected_shape',False),('depth_native',True),
    ('depth_native',float('nan')),('depth_native',float('inf')),('depth_native',0),
    ('axis_native',[0,0,2]),('origin_native',[0,False,0]),
    ('island_sketch_names',['A','B','C']),('island_sketch_names',['A','B','C','a']),
    ('expected_attribute_suffix',[dict(name='x',type='Boss')])])
def test_invalid_plan(key,value):
    p=recipe();p[key]=value
    with pytest.raises(ValueError):core.plan(p)

@pytest.mark.parametrize('key,value',[
    ('owner_setup_native_id',21),('shape',0),('island_count',True),('island_count',3),
    ('depth_native',13),('suppressed',True),('axis_native',[0,0,1]),('taper_angle_native',.1)])
def test_scalar_change_rejected(key,value):
    h=header();h[key]=value
    with pytest.raises(ValueError):core.verify_delta(baseline(),after(),h,recipe())

@pytest.mark.parametrize('change',[
    lambda a:a.update(total_record_count=1),
    lambda a:a.update(generated_operation_count=1),
    lambda a:a.update(operation_count=1),
    lambda a:a['operation_setups'][0].update(native_id=12),
    lambda a:a['feature_setups'][0].update(origin_native=[0.,0.,26.]),
    lambda a:a['sw_reference']['feature_tree'].append(dict(name='Unexpected',type='Attribute')),
    lambda a:a['features'].append(copy.deepcopy(a['features'][0])),
    lambda a:a.update(capture_complete=False)])
def test_unrequested_inventory_delta(change):
    a=after();change(a)
    with pytest.raises(ValueError):core.verify_delta(baseline(),a,header(),recipe())

def test_declared_attributes_only():
    p=recipe();p['expected_attribute_suffix']=[dict(name='Declared',type='Attribute')]
    a=after();a['sw_reference']['feature_tree']+=p['expected_attribute_suffix']
    assert core.verify_delta(baseline(),a,header(),p)['exact_declared_attribute_suffix']==p['expected_attribute_suffix']
    with pytest.raises(ValueError):core.verify_delta(baseline(),after(),header(),p)

class FakeBackend:
    def __init__(self,fail=None):self.fail=fail;self.calls=[]
    def boundary(self):pass
    def capture(self,label):return baseline() if label.endswith('before') else after()
    def create(self,v,pending,returned):
        pending();self.calls.append('factory');returned(dict(native_return_type='native_object',native_return_is_object=True));return 20
    def add(self,v,fid,name,pending,returned):
        pending();self.calls.append(name)
        if self.fail==name:raise RuntimeError('uncertain native failure')
        returned(dict(native_return_type='bool',native_return_value=True))
    def read_header(self,v,fid,count,diagnostic,persist):
        if self.fail=='header':raise RuntimeError('read failure')
        return dict(scalars=header(count),headers={'count':count})
    def read_indexed(self,*args):return {'read_complete':True}

def flow(b,claim=lambda _:None,checker=lambda _:{'indexed_chain_binding_verified':True}):
    r={}
    core.create_one(b,recipe(),claim=claim,persist=lambda:None,report=r,verify_chains=checker)
    return r

def test_once_five_actions_and_two_full_captures():
    b=FakeBackend();r=flow(b)
    assert b.calls==['factory']+recipe()['island_sketch_names']
    assert len(r['actions'])==5 and all(a['returned'] and not a['pending'] for a in r['actions'])
    assert [x['scalars']['island_count']for x in r['header_readbacks']]==list(range(5))
    assert r['definition_readback_verified'] is True
    for flag in ('Save_attempted','GOP_attempted','GTP_attempted','AFR_attempted','model_saved','production_qualified'):
        assert r[flag]is False

def test_claim_failure_prevents_dispatch():
    b=FakeBackend()
    with pytest.raises(RuntimeError):flow(b,claim=lambda _:(_ for _ in ()).throw(RuntimeError('journal failure')))
    assert b.calls==[]

def test_uncertain_add_never_retried():
    b=FakeBackend('ISLAND_B');r={}
    with pytest.raises(RuntimeError):
        core.create_one(b,recipe(),claim=lambda _:None,persist=lambda:None,report=r,verify_chains=lambda _:{})
    assert b.calls==['factory','ISLAND_A','ISLAND_B']
    assert r['status']=='uncertain' and r['actions'][-1]['pending']is True
    assert not r['definition_readback_verified']

def test_returned_factory_fact_survives_header_failure():
    b=FakeBackend('header');r={}
    with pytest.raises(RuntimeError):
        core.create_one(b,recipe(),claim=lambda _:None,persist=lambda:None,report=r,verify_chains=lambda _:{})
    assert r['actions'][0]['returned']is True and r['new_feature_native_id']==20
    assert b.calls==['factory'] and r['status']=='uncertain'

def test_failed_chain_proof_cannot_promote():
    with pytest.raises(ValueError):flow(FakeBackend(),checker=lambda _:{})

class Guard:
    def __init__(self):self.closed=False
    def __enter__(self):return self
    def __exit__(self,*_):self.closed=True
    def dispatch_once(self,invoke,*,persist_pending):persist_pending();return invoke()
    def read(self,obj,name,*args):return 'owner'

class Context:
    def __init__(self):self.g=Guard()
    def guard(self):return self.g

@pytest.mark.parametrize('native_return',[False,0,1,None,'True'])
def test_actual_backend_rejects_truthy_nonbool(monkeypatch,native_return):
    ctx=Context();b=core.Backend(ctx);facts=[]
    monkeypatch.setattr(b,'_owner',lambda *args:('doc','setup'))
    monkeypatch.setattr(b,'_feature',lambda *args:('raw','base'))
    monkeypatch.setattr(core,'_object_id',lambda *args:10)
    monkeypatch.setattr(core,'_member',lambda *args:native_return)
    monkeypatch.setattr(b,'adopt',lambda:pytest.fail('invalid return cannot be adopted'))
    with pytest.raises(ValueError):b.add(recipe(),20,'ISLAND_A',lambda:None, facts.append)
    assert ctx.g.closed and facts[0]['native_return_type']==type(native_return).__name__

def test_actual_backend_adopts_strict_true_only_after_guard_closed(monkeypatch):
    ctx=Context();b=core.Backend(ctx);facts=[]
    monkeypatch.setattr(b,'_owner',lambda *args:('doc','setup'))
    monkeypatch.setattr(b,'_feature',lambda *args:('raw','base'))
    monkeypatch.setattr(core,'_object_id',lambda *args:10)
    monkeypatch.setattr(core,'_member',lambda *args:True)
    monkeypatch.setattr(b,'adopt',lambda: facts.append({'guard_closed':ctx.g.closed}))
    b.add(recipe(),20,'ISLAND_A',lambda:None,facts.append)
    assert facts==[dict(native_return_type='bool',native_return_value=True),dict(guard_closed=True)]

def test_terminal_persist_failure_revokes_readback_without_replay():
    b=FakeBackend();r={}
    def persist():
        if r.get('status')=='definition_observed':raise OSError('terminal write failed')
    with pytest.raises(OSError):
        core.create_one(b,recipe(),claim=lambda _:None,persist=persist,report=r,
                        verify_chains=lambda _:{'indexed_chain_binding_verified':True})
    assert r['status']=='uncertain' and r['receipt_write_failed']is True
    assert not r['definition_readback_verified'] and not r['inventory_delta_verified']
    assert not r['indexed_readback_complete']
    assert all(a['returned']for a in r['actions'])
    assert b.calls==['factory']+recipe()['island_sketch_names']


@pytest.mark.parametrize('key',['feature_count','operation_count','generated_operation_count','total_record_count'])
def test_empty_counter_bool_is_not_integer_zero(key):
    b=baseline();b[key]=False
    with pytest.raises(ValueError):core.empty_baseline(b,recipe())
