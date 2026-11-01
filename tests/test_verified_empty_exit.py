import json,os,time
from pathlib import Path
import pytest
from test_owned_empty_exit import evidence,Fake,rewrite,m

@pytest.fixture
def empty(evidence):
    p={k:v for k,v in evidence.items() if k not in ('save_receipt_path','save_receipt_sha256','close_receipt_path','close_receipt_sha256')}
    p['acknowledge_restored_checkpoint_exit']=True
    result=dict(status='ok',process_id=p['process_id'],active_document=None,documents=[],document_count=0,user_control=True,mutation_attempted=False)
    path=Path(p['receipt_path']).with_name('empty.json');path.write_text(json.dumps(result))
    p.update(empty_receipt_path=str(path),empty_receipt_sha256=m.digest(path));return p


def test_restored_source_and_fresh_empty_proof_exit_without_save_receipts(empty):
    b=Fake(empty);r=m.run_verified_empty_exit(empty,backend=b)
    assert r['status']=='exited' and r['process_exit_verified'] and r['readback_verified']
    assert r['scope']==m.VERIFIED_EMPTY_SCOPE and r['evidence_mode']=='verified_empty_session_after_checkpoint_restore'
    assert r['save_close_evidence_required'] is False and r['save_attempted'] is False and r['close_document_attempted'] is False
    assert b.calls==1 and b.log[b.log.index('ExitApp')+1:]==['OSwait','OSclose']


def test_actual_batch_inspection_receipt_shape_accepted(empty):
    path=Path(empty['empty_receipt_path']);value=json.loads(path.read_text())
    batch=dict(schema_version=1,status='success',request_count=2,results=[dict(index=0,name='solidworks_connect',result={}),dict(index=1,name='solidworks_inspect_open_documents',result=dict(content=[dict(type='text',parsed_json=value)]))])
    path.write_text(json.dumps(batch));empty['empty_receipt_sha256']=m.digest(path)
    assert m.run_verified_empty_exit(empty,backend=Fake(empty))['status']=='exited'

@pytest.mark.parametrize('change',[
 lambda v:v.update(status='error'),lambda v:v.update(process_id=124),lambda v:v.update(process_id=True),
 lambda v:v.update(active_document={'path':'other'}),lambda v:v.update(documents=['other']),lambda v:v.update(document_count=1),
 lambda v:v.update(document_count=False),lambda v:v.update(user_control=False),lambda v:v.update(mutation_attempted=True),
 lambda v:v.pop('active_document'),lambda v:v.update(issue={'type':'error'}),
])
def test_bad_inspection_never_connects(empty,change):
    rewrite(empty,'empty',change);b=Fake(empty)
    with pytest.raises((ValueError,KeyError)):m.run_verified_empty_exit(empty,backend=b)
    assert b.started==0 and b.calls==0

@pytest.mark.parametrize('delta',[301,-1])
def test_stale_or_future_artifact_rejected(empty,delta):
    stamp=time.time()-delta;os.utime(empty['empty_receipt_path'],(stamp,stamp));b=Fake(empty)
    with pytest.raises(ValueError):m.run_verified_empty_exit(empty,backend=b)
    assert b.started==0

@pytest.mark.parametrize('field',['acknowledge_restored_checkpoint_exit','acknowledge_exit_owned_empty_session'])
def test_both_explicit_acknowledgements_required(empty,field):
    empty[field]=False;b=Fake(empty)
    with pytest.raises(ValueError):m.run_verified_empty_exit(empty,backend=b)
    assert b.started==0


def test_saved_branch_still_requires_real_save_and_close(empty):
    with pytest.raises(ValueError):m.run_exit(empty,backend=Fake(empty))


def test_live_document_or_changed_owner_blocks_even_with_good_receipt(empty):
    b=Fake(empty);b.docs=['other'];r=m.run_verified_empty_exit(empty,backend=b)
    assert r['status']=='error' and b.calls==0


def test_exact_process_lifetime_not_pid_alone(empty):
    b=Fake(empty);b.owner_change=True;r=m.run_verified_empty_exit(empty,backend=b)
    assert r['status']=='error' and b.calls==0


def test_same_once_marker_no_cross_branch_replay(empty):
    b=Fake(empty);b.signalled=False;r=m.run_verified_empty_exit(empty,backend=b)
    assert r['status']=='exit_not_observed' and b.calls==1
    empty['receipt_path']=str(Path(empty['receipt_path']).with_name('exit_second.json'))
    with pytest.raises(ValueError):m.run_verified_empty_exit(empty,backend=b)
    assert b.calls==1


def test_source_changed_before_start_rejected(empty):
    Path(empty['expected_document_path']).write_bytes(b'changed');b=Fake(empty)
    with pytest.raises(ValueError):m.run_verified_empty_exit(empty,backend=b)
    assert b.started==0


def test_new_source_change_after_exit_never_claimed_preserved(empty):
    b=Fake(empty);base=b.wait_exit
    def wait(ms):Path(empty['expected_document_path']).write_bytes(b'changed');return base(ms)
    b.wait_exit=wait;r=m.run_verified_empty_exit(empty,backend=b)
    assert r['status']=='uncertain' and r['saved_files_preserved'] is None and r['process_exit_verified']


def test_malformed_or_duplicate_batch_rejected(empty):
    value=json.loads(Path(empty['empty_receipt_path']).read_text())
    row=dict(name='solidworks_inspect_open_documents',result=dict(content=[dict(parsed_json=value)]))
    for batch in [dict(schema_version=1,status='timeout',request_count=1,results=[row]),dict(schema_version=1,status='success',request_count=2,results=[row,row])]:
        with pytest.raises(ValueError):m.validate_empty_observation(batch,empty)


def test_second_live_empty_check_still_blocks(empty):
    b=Fake(empty);calls=0
    def check():
        nonlocal calls
        calls+=1
        if calls==2:raise ValueError('User opened another document')
        return []
    b.empty=check;r=m.run_verified_empty_exit(empty,backend=b)
    assert r['status']=='error' and b.calls==0 and calls==2


def test_verified_mcp_model_strict_fields_and_ack(empty):
    from pydantic import BaseModel,ConfigDict,Field,model_validator
    from enum import Enum
    import sys
    class BaseInput(BaseModel):model_config=ConfigDict(extra='forbid')
    class ResponseFormat(str,Enum):JSON='json'
    class Decorator:
        def tool(self,**kwargs):return lambda f:f
    sys.modules['scripts.sw_owned_empty_exit']=m
    ns=dict(BaseInput=BaseInput,Field=Field,model_validator=model_validator,ResponseFormat=ResponseFormat,mcp=Decorator())
    fixture=Path(__file__).with_name('mcp_verified_empty_fixture.py')
    exec(compile(fixture.read_text(encoding='utf-8'),str(fixture),'exec'),ns)
    cls=ns['SolidWorksVerifiedEmptyExitInput'];cls(**empty)
    for field,value in [('process_id',True),('wait_milliseconds','10'),('expected_creation_filetime',True),('acknowledge_exit_owned_empty_session',False),('acknowledge_restored_checkpoint_exit',False)]:
        with pytest.raises(ValueError):cls(**dict(empty,**{field:value}))
    with pytest.raises(ValueError):cls(**dict(empty,save_receipt_path='unexpected'))
    called=[]
    def run(op,fmt,**kwargs):
        called.append(kwargs);return op()
    ns.update(_selected_process_id=999,_run_locked=run)
    with pytest.raises(ValueError):ns['solidworks_exit_verified_empty_session'](cls(**empty))
    assert called==[dict(load_automation=False,desktop_guard=True)]
