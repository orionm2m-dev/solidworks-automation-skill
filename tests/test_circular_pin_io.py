"""圆形上下文的有界文件读取恢复；不调用原生接口。"""
from copy import deepcopy
import errno
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sw_cam_current_circular_context as core


def io_error(code=errno.EIO, winerror=64):
    cause=OSError(code,'private error text must not be journaled')
    cause.winerror=winerror
    error=ValueError('Export receipt unavailable')
    error.__cause__=cause
    return error


def context(monkeypatch, outcomes, *, prepare=False):
    pin=dict(path='C:/evidence/authority.json',sha256='a'*64,canonical_path='C:/evidence/authority.json',bytes=4,identity=[1,2,4,5,6,7])
    state=core.NativeCircularContext.__new__(core.NativeCircularContext)
    state.pins=[deepcopy(pin)];state.report={};state.request={}
    if prepare:state.request=dict(prepare_receipt_path='C:/evidence/prepare.json',prepare_receipt_sha256='b'*64)
    state.persist=Mock();state.read=Mock(side_effect=AssertionError('native read prohibited'));state.boundary=Mock(side_effect=AssertionError('native boundary prohibited'))
    calls=[];queue=list(outcomes)
    def read(path,sha):
        calls.append((path,sha))
        value=queue.pop(0)
        if isinstance(value,BaseException):raise value
        return {},deepcopy(pin if value=='ok' else value)
    monkeypatch.setattr(core,'read_pin',read)
    sleep=Mock();monkeypatch.setattr('time.sleep',sleep)
    return state,pin,calls,sleep


def test_normal_success_has_no_retry_or_native_call(monkeypatch):
    c,p,calls,sleep=context(monkeypatch,['ok']);c.verify_files()
    assert calls==[(p['path'],p['sha256'])] and c.report=={}
    sleep.assert_not_called();c.persist.assert_not_called();c.read.assert_not_called();c.boundary.assert_not_called()


@pytest.mark.parametrize('failures',[1,2])
def test_bounded_io_retry_same_full_pin(monkeypatch,failures):
    c,p,calls,sleep=context(monkeypatch,[io_error() for _ in range(failures)]+['ok'])
    original=deepcopy(c.pins);c.verify_files()
    assert calls==[(p['path'],p['sha256'])]*(failures+1) and c.pins==original
    assert [x.args for x in sleep.call_args_list]==[(.05,)]*failures
    e=c.report['file_pin_read_retries'][0]
    assert e['outcome']=='verified_after_retry' and e['completed_attempt']==failures+1
    assert [x['attempt'] for x in e['failures']]==list(range(1,failures+1))
    assert e['failures'][0]['errno']==errno.EIO and e['failures'][0]['winerror']==64
    assert 'private error text' not in json.dumps(c.report)
    c.read.assert_not_called();c.boundary.assert_not_called()


def test_exhaustion_retains_third_error_and_stops_later_pin(monkeypatch):
    errors=[io_error() for _ in range(3)]
    c,p,calls,sleep=context(monkeypatch,errors)
    c.pins.append(dict(p,path='C:/evidence/later.json'))
    with pytest.raises(ValueError) as caught:c.verify_files()
    assert caught.value is errors[-1] and len(calls)==3 and sleep.call_count==2
    assert c.report['file_pin_read_retries'][0]['outcome']=='retry_budget_exhausted'
    assert all(x[0]==p['path'] for x in calls)


def _guard_failure():
    e=ValueError('shape guard');e.__cause__=ValueError('not IO');return e


@pytest.mark.parametrize('error',[ValueError('Pinned receipt SHA differs'),_guard_failure(),OSError(errno.EIO,'direct IO'),TypeError('shape'),RuntimeError('other')])
def test_nonmatching_exception_never_retried(monkeypatch,error):
    c,p,calls,sleep=context(monkeypatch,[error])
    with pytest.raises(type(error)) as caught:c.verify_files()
    assert caught.value is error and len(calls)==1 and c.report=={}
    sleep.assert_not_called()


def test_valueerror_subclass_with_io_cause_is_not_retried(monkeypatch):
    class GuardError(ValueError):pass
    error=GuardError('guard');error.__cause__=OSError(errno.EIO,'not transport wrapper')
    c,p,calls,sleep=context(monkeypatch,[error])
    with pytest.raises(GuardError):c.verify_files()
    assert len(calls)==1 and not c.report;sleep.assert_not_called()


@pytest.mark.parametrize('key,value',[('identity',[1,3,4,5,6,7]),('sha256','c'*64),('canonical_path','C:/other.json'),('bytes',5)])
def test_full_pin_mismatch_after_io_is_not_retried(monkeypatch,key,value):
    c,p,calls,sleep=context(monkeypatch,[])
    changed=dict(p,**{key:value});outcomes=iter([io_error(),({},changed)])
    def read(*args):
        calls.append(args);value=next(outcomes)
        if isinstance(value,BaseException):raise value
        return value
    monkeypatch.setattr(core,'read_pin',read)
    with pytest.raises(ValueError,match='Immutable circular authority changed'):c.verify_files()
    assert len(calls)==2 and sleep.call_count==1
    assert c.report['file_pin_read_retries'][0]['outcome']=='pin_mismatch'


def test_sha_guard_after_transport_failure_stops(monkeypatch):
    c,p,calls,sleep=context(monkeypatch,[io_error(),ValueError('Pinned receipt SHA differs')])
    with pytest.raises(ValueError,match='Pinned receipt SHA differs'):c.verify_files()
    assert len(calls)==2 and sleep.call_count==1
    assert c.report['file_pin_read_retries'][0]['outcome']=='non_retryable_error'


def test_prepare_input_uses_same_bounded_read_policy(monkeypatch):
    c,p,calls,sleep=context(monkeypatch,['ok',io_error(),'ok'],prepare=True);c.verify_files()
    assert calls==[(p['path'],p['sha256']),('C:/evidence/prepare.json','b'*64),('C:/evidence/prepare.json','b'*64)]
    assert c.report['file_pin_read_retries'][0]['path']=='C:/evidence/prepare.json'


@pytest.mark.parametrize('number',[True,'secret',None])
def test_journal_numeric_codes_are_strict(monkeypatch,number):
    error=io_error();error.__cause__.errno=number;error.__cause__.winerror=number
    c,p,calls,sleep=context(monkeypatch,[error,'ok']);c.verify_files()
    assert c.report['file_pin_read_retries'][0]['failures']==[dict(attempt=1,errno=None,winerror=None)]


def test_journal_is_bounded_and_fails_closed(monkeypatch):
    error=io_error();c,p,calls,sleep=context(monkeypatch,[error])
    c.report['file_pin_read_retries']=[{} for _ in range(64)]
    with pytest.raises(ValueError) as caught:c.verify_files()
    assert caught.value is error and len(calls)==1
    assert len(c.report['file_pin_read_retries'])==64 and c.report['file_pin_retry_journal_limit_reached'] is True
    sleep.assert_not_called()


def test_persist_failure_prevents_retry(monkeypatch):
    c,p,calls,sleep=context(monkeypatch,[io_error()]);c.persist.side_effect=OSError('receipt unavailable')
    with pytest.raises(OSError):c.verify_files()
    assert len(calls)==1;sleep.assert_not_called()
