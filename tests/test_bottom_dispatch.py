"""Offline protocol and fail-closed tests; no application object is created."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import json
import sys
import types
import pytest

# Test location is separate from the installed reusable implementation.
RUNTIME=Path(__import__('os').environ.get('SOLIDWORKS_SKILL_ROOT',
    str(Path.home()/'.codex/skills/solidworks-automation')))
sys.path.insert(0,str(RUNTIME))
MODULE=Path(__file__).parents[1]/'scripts'/'sw_cam_bottom_dispatch.py'
spec=importlib.util.spec_from_file_location('bottom_dispatch_staging',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Owner:
    def __init__(self,value=False,dispatch=None,ids=None,result=None,raises=False,apply=True):
        self.BottomFinOpt=value
        self.dispatch=dispatch
        self.ids=[65558] if ids is None else ids
        self.result=result;self.raises=raises;self.apply=apply;self.calls=[]
    def GetIDsOfNames(self,*args,**kw):
        self.calls.append(('names',args,kw));return self.ids
    def Invoke(self,*args,**kw):
        self.calls.append(('Invoke',args,kw))
        if kw['_invkind']==2:
            return self.BottomFinOpt if self.dispatch is None else self.dispatch
        assert args==(self.ids[0],True) and type(args[1]) is bool
        assert kw=={'_invkind':4,'_lcid':0}
        if self.raises:raise RuntimeError('simulated COM failure')
        if self.apply:self.BottomFinOpt=True
        return self.result

class Guard:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,obj,name,*args):
        v=getattr(obj,name);return v(*args) if callable(v) else v
    def dispatch_once(self,invoke,*,persist_pending):
        persist_pending();return invoke()

def report():
    return dict(source_path='part',initial_source_sha256='a'*64,process_id=7,
        failed_receipt_pin={'sha256':'b'*64},field_receipt_pin={'sha256':'c'*64},
        phase='prepared',status='prepared',actions={},readback_verified=False,
        mutation_attempted=False,GTP_attempted=False,model_saved=False)

def journal(tmp_path):
    r=report();j=m.Journal(r,tmp_path/'receipt.json',tmp_path/'once.json')
    j.persist();return j

class Backend(m.NativeBackend):
    def __init__(self,j,owner,expected,drift=False):
        self.report=j.report;self.persist=j.persist;self.obj=owner;self.expected=expected
        self.ctx=types.SimpleNamespace(identity=lambda:{'needs_save':True},guard=lambda:Guard())
        self.loaded={'offline_export_proof_pins':[],'bootstrap_export_pins':[],
            'approved_runtime_dispid':65558}
        self.drift=drift;self.closed=False
    def confirm_ungenerated(self,g):pass
    def start(self):pass
    def owner(self,g,spec):return self.obj,object(),'ICWFinishMillOp'
    def current_tool(self):return {'id':273}
    def all_fields(self,label):
        v=deepcopy(self.expected);v['bottom_finish']=self.obj.BottomFinOpt
        if self.drift and label=='dispatch_after':v['side_step']=[9.,False]
        return v
    def refresh_dirty(self):pass
    def boundary(self):pass
    def close(self):self.closed=True

@pytest.fixture
def expected(monkeypatch):
    monkeypatch.setattr(m.finish,'wanted_assignment',lambda _: {'id':273})
    monkeypatch.setattr(m.finish.common,'_check',lambda _:None)
    return {'bottom_finish':False,'side_step':[.25,False]}

def test_read_pair_uses_exact_named_public_dispatch():
    o=Owner();row={};snapshots=[]
    value,_=m.read_pair(Guard(),o,row,lambda:snapshots.append(deepcopy(row)))
    assert value is False and row['complete']
    assert o.calls==[('names',('BottomFinOpt',),{'lcid':0}),('Invoke',(65558,),{'_invkind':2,'_lcid':0})]
    assert snapshots[-1]['dispatch']['python_type']=='bool'

@pytest.mark.parametrize('owner,key',[ (Owner(ids=[0]),'resolved_names'),
    (Owner(value=0),'vtable'),(Owner(dispatch=0),'dispatch'),(Owner(dispatch=True),'dispatch')])
def test_failed_actual_value_is_persisted_before_validation(owner,key):
    row={};snapshots=[]
    with pytest.raises(ValueError):m.read_pair(Guard(),owner,row,lambda:snapshots.append(deepcopy(row)))
    assert key in snapshots[-1] and not row.get('complete',False)
    assert all(x[2].get('_invkind')!=4 for x in owner.calls)

def test_inspect_has_no_write_and_no_once_marker(tmp_path,expected):
    j=journal(tmp_path);o=Owner();b=Backend(j,o,expected)
    m.run_steps(b,j,'inspect',expected)
    assert j.report['status']=='inspected' and not j.marker.exists()
    assert j.report['actions']=={} and not j.report['mutation_attempted']
    assert not any(x[2].get('_invkind')==4 for x in o.calls)

def test_apply_none_return_is_success_only_with_both_readbacks(tmp_path,expected):
    j=journal(tmp_path);o=Owner();b=Backend(j,o,expected)
    m.run_steps(b,j,'apply',expected)
    action=j.report['actions']['IDispatch.PROPERTYPUT.BottomFinOpt']
    assert j.report['status']=='verified' and action['native_return_type']=='NoneType'
    assert action['native_return_value'] is None and action['readback_verified']
    assert sum(x[2].get('_invkind')==4 for x in o.calls)==1
    assert j.marker.exists()
    assert not j.report['GTP_attempted'] and not j.report['model_saved']

@pytest.mark.parametrize('owner',[Owner(result=0),Owner(result=True),Owner(raises=True),Owner(apply=False)])
def test_failed_write_never_retries_and_is_durably_marked(tmp_path,expected,owner):
    j=journal(tmp_path);b=Backend(j,owner,expected)
    with pytest.raises((ValueError,RuntimeError)):m.run_steps(b,j,'apply',expected)
    assert j.marker.exists() and j.report['mutation_attempted']
    assert sum(x[2].get('_invkind')==4 for x in owner.calls)==1
    assert not j.report['readback_verified']

def test_neighbor_field_change_rejected(tmp_path,expected):
    j=journal(tmp_path);b=Backend(j,Owner(),expected,drift=True)
    with pytest.raises(ValueError,match='Another recipe'):m.run_steps(b,j,'apply',expected)
    assert j.report['after_fields']['side_step']==[9.,False]
    assert not j.report['readback_verified']

def test_marker_prevents_replay_even_with_fresh_journal(tmp_path,expected):
    j=journal(tmp_path);m.run_steps(Backend(j,Owner(),expected),j,'apply',expected)
    other=m.Journal(report(),tmp_path/'other.json',j.marker)
    calls=[]
    with pytest.raises(ValueError,match='Existing attempt'):
        Guard().dispatch_once(lambda:calls.append(1),persist_pending=lambda:other.pending('IDispatch.PROPERTYPUT.BottomFinOpt'))
    assert calls==[]

def test_no_put_when_immediate_pair_changes(tmp_path,expected):
    j=journal(tmp_path);o=Owner();b=Backend(j,o,expected)
    original_compare=b.compare
    def compare(label):
        result=original_compare(label)
        if label=='before':o.BottomFinOpt=True
        return result
    b.compare=compare
    with pytest.raises(ValueError,match='still be false'):m.run_steps(b,j,'apply',expected)
    assert not j.marker.exists() and not any(x[2].get('_invkind')==4 for x in o.calls)

def test_failed_pending_persistence_prevents_native_put(tmp_path,expected):
    j=journal(tmp_path);o=Owner();b=Backend(j,o,expected)
    def fail(_):raise OSError('no disk space')
    j.pending=fail
    with pytest.raises(OSError):m.run_steps(b,j,'apply',expected)
    assert not any(x[2].get('_invkind')==4 for x in o.calls)

def test_generated_dual_contract_parses_without_importing_it():
    p=RUNTIME/'.venv/Lib/site-packages/comtypes/gen/_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0.py'
    result=m.audit_cached_dual(m.finish.common._pin(p))
    assert result['idlflags']==['dual','oleautomation'] and result['dispid']==22
    assert result['live_typeinfo_invoked'] is False

@pytest.mark.parametrize('old,new',[
    ("_idlflags_ = ['dual', 'oleautomation']","_idlflags_ = ['oleautomation']"),
    ("dispid(22), helpstring('property Bottom Fin Option')","dispid(23), helpstring('property Bottom Fin Option')"),
    ("(['in'], VARIANT_BOOL, 'pVal')","(['in'], c_int, 'pVal')")])
def test_changed_metadata_refuses_dispatch(tmp_path,old,new):
    p=RUNTIME/'.venv/Lib/site-packages/comtypes/gen/_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0.py'
    s=p.read_text(encoding='mbcs');start=s.index('class ICWFinishMillOp(')
    if old.startswith('_idlflags'):
        s=s[:start]+s[start:].replace(old,new,1)
    else:s=s.replace(old,new)
    f=tmp_path/'metadata.py';f.write_text(s,encoding='mbcs')
    with pytest.raises(ValueError):m.audit_cached_dual(m.finish.common._pin(f))

def test_apply_requires_reviewed_ack_before_any_input_load(monkeypatch):
    p={k:('a'*64 if k.endswith('sha256') else 'x') for k in m.COMMON|m.APPLY}
    p['module_sha256']=m.finish._file_hash(m.__file__);p['acknowledgement']='yes'
    for k in p:
        if k.endswith('_path'):p[k]=str(MODULE)
    with pytest.raises(ValueError,match='reviewed one-put'):m.load_inputs({'action':'apply','params':p})

def test_generated_finish_refuses_comparison_before_property_access(tmp_path,expected):
    j=journal(tmp_path);o=Owner();b=Backend(j,o,expected)
    b.confirm_ungenerated=lambda g: (_ for _ in ()).throw(ValueError("generated"))
    with pytest.raises(ValueError,match="generated"):m.run_steps(b,j,"apply",expected)
    assert o.calls==[] and not j.marker.exists()


def test_apply_allows_clean_to_dirty_and_preserves_actual_snapshots(tmp_path,expected):
    j=journal(tmp_path);b=Backend(j,Owner(),expected)
    state={'needs_save':False,'title':'target'}
    b.ctx.identity=lambda:deepcopy(state)
    b.refresh_dirty=lambda:state.update(needs_save=True)
    m.run_steps(b,j,'apply',expected)
    assert j.report['status']=='verified'
    assert j.report['before_document']=={'needs_save':False,'title':'target'}
    assert j.report['after_document']=={'needs_save':True,'title':'target'}


def test_apply_rejects_dirty_to_clean(tmp_path,expected):
    j=journal(tmp_path);b=Backend(j,Owner(),expected)
    state={'needs_save':True,'title':'target'}
    b.ctx.identity=lambda:deepcopy(state)
    b.refresh_dirty=lambda:state.update(needs_save=False)
    with pytest.raises(ValueError,match='cannot clear'):m.run_steps(b,j,'apply',expected)
    assert j.report['before_document']['needs_save'] is True
    assert j.report['after_document']['needs_save'] is False


@pytest.mark.parametrize('changed',[
    {'title':'other'}, {'path':'other'}, {'configuration':'other'}, {'type':2}])
def test_apply_rejects_every_other_document_change(tmp_path,expected,changed):
    j=journal(tmp_path);b=Backend(j,Owner(),expected)
    state={'needs_save':False,'title':'target','path':'part','configuration':'Default','type':1}
    b.ctx.identity=lambda:deepcopy(state)
    b.refresh_dirty=lambda:state.update(needs_save=True,**changed)
    with pytest.raises(ValueError,match='another document'):m.run_steps(b,j,'apply',expected)
    assert j.report['after_document']['needs_save'] is True
    assert not j.report['readback_verified']


def test_inspect_rejects_even_clean_to_dirty(tmp_path,expected):
    j=journal(tmp_path);b=Backend(j,Owner(),expected)
    identities=iter([{'needs_save':False},{'needs_save':True}])
    b.ctx.identity=lambda:next(identities)
    with pytest.raises(ValueError,match='Read-only document'):m.run_steps(b,j,'inspect',expected)
    assert j.report['actions']=={}


@pytest.mark.parametrize('resolved',[1,22,65558,2147483647])
def test_any_positive_int32_resolved_name_is_used_without_offset(resolved):
    o=Owner(ids=[resolved]);row={}
    value,access=m.read_pair(Guard(),o,row,lambda:None)
    assert value is False and access.dispid==resolved
    assert row['resolved_dispid']==resolved and row['cached_metadata_dispid']==22
    assert o.calls[-1]==('Invoke',(resolved,),{'_invkind':2,'_lcid':0})


@pytest.mark.parametrize('ids',[[0],[-1],[-3],[2147483648],[True],['65558'],[],[65558,22],65558,(65558,),[1.0]])
def test_invalid_runtime_name_binding_stops_before_invoke(ids):
    o=Owner(ids=ids);row={};snapshots=[]
    with pytest.raises(ValueError,match='positive int32'):
        m.read_pair(Guard(),o,row,lambda:snapshots.append(deepcopy(row)))
    assert snapshots[-1]['resolved_names']==m.fields.raw_observation(ids)
    assert o.calls==[('names',('BottomFinOpt',),{'lcid':0})]


def test_reviewed_id_mismatch_stops_before_any_invoke(tmp_path,expected):
    j=journal(tmp_path);o=Owner(ids=[22]);b=Backend(j,o,expected)
    with pytest.raises(ValueError,match='reviewed inspection'):m.run_steps(b,j,'apply',expected)
    assert j.report['comparisons']['before']['resolved_dispid']==22
    assert o.calls==[('names',('BottomFinOpt',),{'lcid':0})]
    assert not j.marker.exists() and not j.report['mutation_attempted']


def test_binding_drift_immediately_before_put_stops_without_marker(tmp_path,expected):
    j=journal(tmp_path);o=Owner();b=Backend(j,o,expected);original=b.compare
    def compare(label):
        result=original(label)
        if label=='before':o.ids=[65559]
        return result
    b.compare=compare
    with pytest.raises(ValueError,match='reviewed inspection'):m.run_steps(b,j,'apply',expected)
    assert j.report['comparisons']['immediately_before_put']['resolved_dispid']==65559
    assert not j.marker.exists() and not any(x[2].get('_invkind')==4 for x in o.calls)


def test_missing_reviewed_binding_stops_before_native_start(tmp_path,expected):
    j=journal(tmp_path);b=Backend(j,Owner(),expected);b.loaded['approved_runtime_dispid']=None
    b.start=lambda:pytest.fail('Native start must not happen')
    with pytest.raises(ValueError,match='Successful inspection'):m.run_steps(b,j,'apply',expected)
    assert b.obj.calls==[] and not j.marker.exists()


def test_inspect_does_not_assume_previously_seen_id(tmp_path,expected):
    j=journal(tmp_path);o=Owner(ids=[444]);b=Backend(j,o,expected)
    b.loaded['approved_runtime_dispid']=None
    m.run_steps(b,j,'inspect',expected)
    assert j.report['comparisons']['before']['resolved_dispid']==444
    assert j.report['status']=='inspected' and not j.marker.exists()


def test_post_put_binding_change_retains_actual_and_rejects_success(tmp_path,expected):
    j=journal(tmp_path);o=Owner();b=Backend(j,o,expected)
    b.refresh_dirty=lambda:setattr(o,'ids',[65559])
    with pytest.raises(ValueError,match='reviewed inspection'):m.run_steps(b,j,'apply',expected)
    assert j.report['comparisons']['after']['resolved_dispid']==65559
    assert j.marker.exists() and j.report['mutation_attempted']
    assert sum(x[2].get('_invkind')==4 for x in o.calls)==1
    assert not j.report['readback_verified']
