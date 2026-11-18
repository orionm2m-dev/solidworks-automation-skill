"""Portable pure/fake tests; no application connection or activation."""
import os,sys,importlib.util,math
from pathlib import Path
from copy import deepcopy
import pytest
rt=Path(os.environ['SWMCP_RUNTIME_ROOT']);sys.path.insert(0,str(rt))
p=Path(__file__).resolve().parents[1]/'scripts/sw_cam_recovered_pocket_lengths.py'
spec=importlib.util.spec_from_file_location('length_extension_under_test',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def bundle():
    row=dict(native_id=69,mill_operation_type=0,suppressed=False,toolpath_generated=True,linked_feature_ids=[66],toolpath_record_counts=[21016],assigned_tool=dict(native_id=86))
    return dict(protected_generated={69:[21016]},state=dict(selected_feature=dict(native_id=66),operations=[row]),context=dict(pins=[]),pins=[])

class Batch:
    def __init__(self,values):self.values=iter(values);self.calls=[]
    def read(self,obj,name,*args):
        self.calls.append(name);v=next(self.values)
        if isinstance(v,BaseException):raise v
        return v
    def typed(self,obj,name):return obj

@pytest.fixture
def observe_env(monkeypatch):
    calls=[]
    def binding(*a,**kw):calls.append('binding');return dict(identity=1),object(),object()
    monkeypatch.setattr(m.lengths.protected,'binding',binding)
    b=bundle();return b,m.initial_observation(b),calls


def test_exact_parent_schema_and_scope():
    assert m.KEYS==m.parent.KEYS and m.SCOPE!=m.parent.SCOPE
    assert m.selection(bundle())==dict(operation_native_id=69,feature_native_id=66,tool_native_id=86,record_counts=[21016])

@pytest.mark.parametrize('change',[('mill_operation_type',1),('mill_operation_type',False),('suppressed',True),('toolpath_generated',False),('linked_feature_ids',[77]),('toolpath_record_counts',[1]),('assigned_tool',dict(native_id=True))])
def test_wrong_selected_context(change):
    b=bundle();b['state']['operations'][0][change[0]]=change[1]
    with pytest.raises(ValueError):m.selection(b)

@pytest.mark.parametrize('generated',[{}, {69:[21016],70:[1]}, {True:[1]}, {69:[True]}, {69:[0]}, {69:[100001]}])
def test_generated_scope_reject(generated):
    b=bundle();b['protected_generated']=generated
    with pytest.raises(ValueError):m.selection(b)


def test_six_exact_reads_and_signed_delta(observe_env):
    b,r,calls=observe_env;batch=Batch([2.,3.,4.]*2);m.observe_lengths(batch,object(),b['state'],m.selection(b),r,lambda:None)
    assert calls==['binding','binding'] and len(batch.calls)==6
    assert r['repeat_equal']and r['binding_unchanged']and r['scalar_getters_returned']==6
    assert r['total_minus_feed_minus_rapid_native']==-1 and not r['additivity_semantics_verified']
    assert r['readback_verified']is False and r['parent_terminal_verified']is False

@pytest.mark.parametrize('v',[True,1,'1',None,float('nan'),float('inf'),-1.])
def test_bad_float_durable_before_reject(observe_env,v):
    b,r,calls=observe_env;batch=Batch([v]);saved=[]
    with pytest.raises(ValueError):m.observe_lengths(batch,object(),b['state'],m.selection(b),r,lambda:saved.append(deepcopy(r)))
    assert r['scalar_getters_returned']==1 and len(r['scalar_observations'])==1 and saved
    assert r['readback_verified']is False


def test_second_read_mismatch_no_admission(observe_env):
    b,r,calls=observe_env
    with pytest.raises(ValueError):m.observe_lengths(Batch([2.,3.,5.,2.,3.,6.]),object(),b['state'],m.selection(b),r,lambda:None)
    assert r['scalar_getters_returned']==6 and calls==['binding'] and r['repeat_equal']is False


def test_native_getter_error_not_replayed(observe_env):
    b,r,calls=observe_env;batch=Batch([RuntimeError('read failed')])
    with pytest.raises(RuntimeError):m.observe_lengths(batch,object(),b['state'],m.selection(b),r,lambda:None)
    assert len(batch.calls)==1 and r['scalar_getters_returned']==0


def test_binding_after_changed(observe_env,monkeypatch):
    b,r,_=observe_env;values=iter([1,2]);monkeypatch.setattr(m.lengths.protected,'binding',lambda *a,**kw:(dict(identity=next(values)),object(),object()))
    with pytest.raises(ValueError):m.observe_lengths(Batch([2.,3.,5.]*2),object(),b['state'],m.selection(b),r,lambda:None)
    assert r['scalar_getters_returned']==6 and r['binding_unchanged']is False


def completed():
    observation=m.initial_observation(bundle());observation.update(reads_verified=True,binding_unchanged=True,repeat_equal=True,scalar_getters_returned=6)
    return dict(scope=m.parent.SCOPE,status='observed',phase='finished',receipt_path='unused.json',**{k:True for k in m.parent.FLAGS},**{m.OBSERVATION:observation})


def test_finalization_is_subordinate_and_scope_preserved():
    r=completed();m.finalize(r)
    assert r['scope']==m.parent.SCOPE and r[m.OBSERVATION]['readback_verified']is True

@pytest.mark.parametrize('flag',list(m.parent.FLAGS))
def test_late_parent_failure_revokes_extension(flag):
    r=completed();r[flag]=False;m.finalize(r);assert r[m.OBSERVATION]['readback_verified']is False

@pytest.mark.parametrize('change',[('status','error'),('scope','foreign'),('phase','running')])
def test_parent_terminal_shape_required(change):
    r=completed();r[change[0]]=change[1];m.finalize(r);assert r[m.OBSERVATION]['readback_verified']is False

@pytest.mark.parametrize('change',[('reads_verified',False),('binding_unchanged',False),('repeat_equal',False),('scalar_getters_returned',5),('native_dispatch_pending',True)])
def test_incomplete_lengths_not_promoted(change):
    r=completed();r[m.OBSERVATION][change[0]]=change[1];m.finalize(r);assert r[m.OBSERVATION]['readback_verified']is False


def test_run_reuses_parent_once_and_fixed_child(monkeypatch):
    seen=[];r=completed();data=dict(consumed=False)
    def run(*args,**kw):seen.append(kw);return r
    monkeypatch.setattr(m.parent,'run_read',run);monkeypatch.setattr(m.parent.reader,'_write_receipt',lambda *a,**kw:None)
    result=m.run_read(None,None,None,{},prepared=data)
    assert len(seen)==1 and seen[0]['prepared']is data and seen[0]['_context_factory']is m.Context
    assert result is r and result[m.OBSERVATION]['readback_verified']is True


def test_revoke_clears_subordinate_flags(monkeypatch):
    r=completed();m.finalize(r);called=[]
    monkeypatch.setattr(m.parent,'revoke',lambda r,e:called.append(e)or r)
    m.revoke(r,RuntimeError('runtime drift'))
    assert len(called)==1 and not r[m.OBSERVATION]['readback_verified'] and not r[m.OBSERVATION]['parent_terminal_verified']


def test_late_write_failure_revokes(monkeypatch):
    r=completed();monkeypatch.setattr(m.parent,'run_read',lambda *a,**kw:r)
    monkeypatch.setattr(m.parent.reader,'_write_receipt',lambda *a,**kw:(_ for _ in ()).throw(OSError('disk full')))
    monkeypatch.setattr(m.parent,'revoke',lambda r,e:r)
    with pytest.raises(OSError):m.run_read(None,None,None,{},prepared={})
    assert r[m.OBSERVATION]['readback_verified']is False


@pytest.mark.parametrize('wrong_doc',[False,True])
def test_child_full_reader_then_bounded_length_batch(monkeypatch,wrong_doc):
    ctx=object.__new__(m.Context);b=bundle();ctx.bundle=b;ctx.r={m.OBSERVATION:m.initial_observation(b)};ctx.d=dict(pins=[dict(path='fixed',sha256='a'*64)])
    ctx.sw=object();ctx.tlb='fixed.tlb';ctx.v=dict(process_id=12,expected_source_sha256='b'*64);ctx.expected=dict(document=dict(path='fixed.sldprt'));ctx.abi=dict(generated_pin={})
    ctx.persist=lambda:None;ctx.runtime_check=lambda:None;ctx.events=lambda:None;ctx.identity=lambda:ctx.expected
    native=dict(doc=object(),machine=object(),selected_feature=object());order=[];seen=[]
    monkeypatch.setattr(m.parent.Context,'observe',lambda *a:order.append('full_pair'))
    monkeypatch.setattr(m.lengths,'audit',lambda *a:order.append('abi')or dict(abi_verified=True))
    monkeypatch.setattr(m.parent,'_member',lambda obj,name,*args:2 if wrong_doc and name=='GetDocType'else 1)
    monkeypatch.setattr(m.parent,'_object_id',lambda *args:66)
    monkeypatch.setattr(m.lengths.protected,'binding',lambda *a,**kw:(dict(identity=1),object(),object()))
    class B(Batch):
        def __init__(self,*a,**kw):super().__init__([2.,3.,5.]*2);self.kw=kw;self.complete=False;seen.append(self)
        def __enter__(self):self.kw['verify_owned_process']();self.kw['verify_retained_binding']();return self
        def __exit__(self,*a):self.kw['verify_owned_process']();self.kw['verify_retained_binding']();self.complete=True
        def require_complete(self):assert self.complete
        def summary(self):return dict(complete=self.complete)
    monkeypatch.setattr(m.lengths,'ReadBatch',B)
    if wrong_doc:
        with pytest.raises(ValueError):ctx.observe(b['state'],native)
        assert seen[0].calls==[] and ctx.r[m.OBSERVATION]['reads_verified']is False
    else:
        ctx.observe(b['state'],native)
        assert len(seen[0].calls)==6 and ctx.r[m.OBSERVATION]['reads_verified']is True
    assert order==['full_pair','abi'] and seen[0].kw['evidence_pin_limit']==128
    assert seen[0].kw['max_native_calls']==128 and seen[0].kw['retained_objects']==tuple(native.values())
