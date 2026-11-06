"""单次只读 capture 的历史 pin 合并；所有测试都不连接原生应用。"""
from copy import deepcopy
from types import MethodType
from unittest.mock import Mock
import pytest
from scripts import sw_cam_current_circular_context as core


def context(monkeypatch, *, body=None):
    c=core.NativeCircularContext.__new__(core.NativeCircularContext)
    pin=dict(path='C:/evidence/authority.json',sha256='a'*64,identity=[1,2,3],bytes=4)
    c.pins=[deepcopy(pin)];c.request={};c.report={};c.persist=Mock()
    observed=deepcopy(pin);reads=[];boundaries=[]
    def read(path,sha):
        reads.append((path,sha))
        return {},deepcopy(observed)
    monkeypatch.setattr(core,'read_pin',read)
    def boundary(self):
        boundaries.append(('identity','source','runtime','events'))
        self.verify_files()
        return {'path':'part','needs_save':True}
    c.boundary=MethodType(boundary,c)
    def capture(self,label,*args):
        state=dict(raw={'actual':[1,2,3]},capture_complete=False,extended_capture_complete=False)
        self.report[label]=state
        for _ in range(3):self.boundary()
        if body:body(self,state,observed)
        state.update(capture_complete=True,extended_capture_complete=True)
        return state
    c._capture_readonly=MethodType(capture,c)
    return c,pin,observed,reads,boundaries


def test_one_capture_keeps_all_boundaries_but_only_two_full_pin_reads(monkeypatch):
    c,p,o,reads,b=context(monkeypatch)
    actual=c.capture('first')
    assert actual is c.report['first'] and actual['raw']=={'actual':[1,2,3]}
    assert actual['capture_complete'] and actual['extended_capture_complete']
    assert len(b)==5 and reads==[(p['path'],p['sha256'])]*2
    assert c.report['capture_pin_checks']==[dict(label='first',entry_verified=True,exit_verified=True,nested_checks_deferred=3)]
    assert c._capture_pin_scope is False and c._capture_pin_episode is None


def test_no_cache_crosses_captures_or_outside_calls(monkeypatch):
    c,p,o,reads,b=context(monkeypatch)
    c.capture('first');c.capture('second');c.verify_files()
    assert len(reads)==5 and len(b)==10
    assert all(x['entry_verified'] and x['exit_verified'] for x in c.report['capture_pin_checks'])


@pytest.mark.parametrize('key,new',[('sha256','b'*64),('identity',[1,9,3]),('bytes',5),('path','C:/different.json')])
def test_change_during_capture_rejected_at_exit_with_raw_evidence(monkeypatch,key,new):
    c,p,o,reads,b=context(monkeypatch,body=lambda c,s,o:o.update({key:new}))
    with pytest.raises(ValueError,match='Immutable circular authority changed'):c.capture('actual')
    assert len(reads)==2 and c._capture_pin_scope is False and c._capture_pin_episode is None
    state=c.report['actual'];assert state['raw']=={'actual':[1,2,3]}
    assert state['capture_complete'] is False and state['extended_capture_complete'] is False
    assert c.report['capture_pin_checks'][0]['exit_verified'] is False


def test_entry_mismatch_runs_no_capture(monkeypatch):
    c,p,o,reads,b=context(monkeypatch);o['identity']=[9]
    c._capture_readonly=Mock(side_effect=AssertionError('body forbidden'))
    with pytest.raises(ValueError):c.capture('first')
    c._capture_readonly.assert_not_called()
    assert len(reads)==1 and getattr(c,'_capture_pin_scope',False) is False


def test_body_failure_still_verifies_exit_and_clears_scope(monkeypatch):
    error=RuntimeError('capture failed')
    def bad(c,s,o):raise error
    c,p,o,reads,b=context(monkeypatch,body=bad)
    with pytest.raises(RuntimeError) as caught:c.capture('first')
    assert caught.value is error and len(reads)==2
    assert c.report['capture_pin_checks'][0]['exit_verified'] is True
    assert c.report['first']['capture_complete'] is False and c.report['first']['extended_capture_complete'] is False
    assert c._capture_pin_scope is False


@pytest.mark.parametrize('which',['nested','guard','save'])
def test_no_nested_capture_or_mutation_entry_inside_scope(monkeypatch,which):
    called=Mock(side_effect=AssertionError('native forbidden'))
    monkeypatch.setattr(core.batch.NativeBatchContext,'save',called)
    def bad(c,s,o):
        if which=='nested':c.capture('nested')
        elif which=='guard':c.guard()
        else:c.save(Mock(),Mock())
    c,p,o,reads,b=context(monkeypatch,body=bad)
    with pytest.raises(ValueError,match='forbidden'):c.capture('first')
    called.assert_not_called()
    assert len(reads)==2 and c._capture_pin_scope is False
    assert len(c.report['capture_pin_checks'])==1


def test_save_outside_capture_forwards_existing_implementation(monkeypatch):
    c,p,o,reads,b=context(monkeypatch);pending=Mock();returned=Mock()
    actual=Mock(return_value=0);monkeypatch.setattr(core.batch.NativeBatchContext,'save',actual)
    assert c.save(pending,returned)==0
    actual.assert_called_once_with(pending,returned)


def test_exit_io_exhaustion_preserves_partial_and_retry_bound(monkeypatch):
    c,p,o,reads,b=context(monkeypatch)
    calls=[]
    def read(path,sha):
        calls.append((path,sha))
        if len(calls)==1:return {},deepcopy(p)
        error=ValueError('receipt unavailable');error.__cause__=OSError(5,'private');raise error
    monkeypatch.setattr(core,'read_pin',read)
    sleep=Mock();monkeypatch.setattr('time.sleep',sleep)
    with pytest.raises(ValueError):c.capture('first')
    assert len(calls)==4 and sleep.call_count==2 and c._capture_pin_scope is False
    assert c.report['first']['raw']=={'actual':[1,2,3]}
    assert not c.report['first']['capture_complete'] and not c.report['first']['extended_capture_complete']
    assert c.report['file_pin_read_retries'][0]['outcome']=='retry_budget_exhausted'


def test_failure_during_final_persist_cannot_leave_scope_active(monkeypatch):
    c,p,o,reads,b=context(monkeypatch)
    c.persist.side_effect=OSError('receipt failed')
    with pytest.raises(OSError):c.capture('first')
    assert c._capture_pin_scope is False and c._capture_pin_episode is None and len(reads)==2


def test_body_and_exit_errors_both_retained_as_bounded_types(monkeypatch):
    def bad(c,s,o):o['identity']=[9];raise RuntimeError('body error')
    c,p,o,reads,b=context(monkeypatch,body=bad)
    with pytest.raises(ValueError):c.capture('first')
    event=c.report['capture_pin_checks'][0]
    assert event['capture_error_type']=='RuntimeError' and event['exit_error_type'] in ('ValueError','CircularGuardError')
    assert not c.report['first']['capture_complete'] and not c.report['first']['extended_capture_complete']


def test_identity_runtime_event_boundaries_are_inherited_unchanged():
    assert core.NativeCircularContext.identity is core.batch.NativeBatchContext.identity
    assert core.NativeCircularContext.boundary is core.batch.NativeBatchContext.boundary
    assert core.NativeCircularContext.read is core.batch.NativeBatchContext.read
    assert core.NativeCircularContext.typed is core.batch.NativeBatchContext.typed
