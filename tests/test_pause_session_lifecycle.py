"""Critical pause lifecycle checks; fake native calls, real durable files."""
from copy import deepcopy
from pathlib import Path
import json
import sys
from types import SimpleNamespace
import pytest
import scripts
scripts.__path__.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from scripts import sw_cam_pause_session as m


class Backend:
    def __init__(self,p):
        self.p=p;self.pid=p['process_id'];self.calls=[];self.saved=False
        self.document=dict(path=p['expected_document_path'],title=Path(p['expected_document_path']).name,type=1,needs_save=True)
        self.foreign=[];self.save_result=0;self.close_result=0;self.save_exception=False;self.drift=False
    def start(self):self.calls.append('start')
    def capture(self,label):
        ids=self.p['expected_operation_ids']
        ops=[dict(id=oid,setup_id=93,generated=(i<4 or oid==143),suppressed=False,
                  tool_id=273 if oid==144 else 145,record_counts=[10] if i<4 or oid==143 else [],feature_ids=[79])
             for i,oid in enumerate(ids)]
        snap=dict(document=deepcopy(self.document),saved_file_sha256=m._file_hash(self.p['expected_document_path']),
            machine_type=1,feature_ids=list(range(1,21))+[79],feature_setup_ids=[5],operations=ops,
            operation_ids=ids[:],operation_setup_ids=[93],tool_ids=list(range(1,19))+[273],finish_fields=deepcopy(m.FIELDS))
        if self.saved and self.drift:snap['tool_ids'][0]=999
        return snap
    def boundary(self,doc,sha):
        self.calls.append('boundary')
        m.require(self.pid==self.p['process_id'],'Owned PID changed')
        m.require(m.exact(self.document,doc),'Active document changed')
        m.require(m._file_hash(self.p['expected_document_path'])==sha,'Source changed')
    def save(self):
        self.calls.append('save')
        if self.save_exception:raise OSError('native save failed')
        if self.save_result==0 and type(self.save_result) is int:
            Path(self.p['expected_document_path']).write_bytes(b'new saved CAM bytes')
            self.saved=True;self.document['needs_save']=False
        return self.save_result
    def close_target(self,doc,sha):
        self.boundary(doc,sha)
        assert doc['path']==self.p['expected_document_path']
        self.calls.append(('close_target',doc['path']))
        return self.close_result
    def documents_after(self):self.calls.append('documents');return deepcopy(self.foreign)
    def stop_events(self):self.calls.append('stop_events')
    def exit_owned(self):
        assert self.pid==self.p['process_id'] and not self.foreign
        self.calls.append('exit');return None


@pytest.fixture
def env(tmp_path):
    source=tmp_path/'owned.SLDPRT';source.write_bytes(b'prior saved source')
    tlb=tmp_path/'camworks.tlb';tlb.write_bytes(b'test metadata')
    p=dict(process_id=123,expected_document_path=str(source),expected_source_sha256=m._file_hash(source),
        addin_clsid='{00000000-0000-0000-0000-000000000000}',typelib_path=str(tlb),
        receipt_path=str(tmp_path/'receipt.json'),backup_before_path=str(tmp_path/'before.SLDPRT'),
        backup_after_path=str(tmp_path/'after.SLDPRT'),module_sha256=m._file_hash(m.__file__),
        acknowledgement=m.ACK,expected_finish_fields=deepcopy(m.FIELDS),
        expected_operation_ids=[195,196,267,247,248,271,143,144],expected_tool_count=19,
        expected_feature_count=21,expected_generated_path_count=5)
    m.validate_request(dict(action='save_close_owned',params=p))
    return SimpleNamespace(p=p,b=Backend(p),j=m.Journal(p),tmp=tmp_path,source=source)


def close_calls(b):return [v for v in b.calls if type(v) is tuple and v[0]=='close_target']


def test_success_preserves_both_backups_and_saves_closes_exits_once(env):
    m.run_steps(env.b,env.j,env.p)
    r=env.j.report
    assert r['save_verified'] and r['close_verified'] and r['exit_returned']
    assert env.b.calls.count('save')==1 and len(close_calls(env.b))==1 and env.b.calls.count('exit')==1
    assert Path(env.p['backup_before_path']).read_bytes()==b'prior saved source'
    assert Path(env.p['backup_after_path']).read_bytes()==env.source.read_bytes()==b'new saved CAM bytes'
    assert set(r['actions'])=={'SaveActiveDocument','CloseActiveDocument','ExitApp'}
    assert r['status']=='paused_saved_closed' and not r['reopen_verified']
    assert not r['GTP_attempted'] and not r['parameter_setter_attempted']
    assert json.loads(Path(env.p['receipt_path']).read_text())['saved_source_sha256']==m._file_hash(env.source)


@pytest.mark.parametrize('failure',['nonzero','exception','bool'])
def test_save_failure_never_closes_or_exits(env,failure):
    if failure=='exception':env.b.save_exception=True
    else:env.b.save_result=1 if failure=='nonzero' else True
    with pytest.raises((ValueError,OSError)):m.run_steps(env.b,env.j,env.p)
    assert env.b.calls.count('save')==1 and not close_calls(env.b) and 'exit' not in env.b.calls
    assert not env.j.report['save_verified'] and not env.j.report['close_verified']


def test_snapshot_drift_after_save_prevents_close(env):
    env.b.drift=True
    with pytest.raises(ValueError,match='protected CAM state'):m.run_steps(env.b,env.j,env.p)
    assert env.b.calls.count('save')==1 and not close_calls(env.b) and 'exit' not in env.b.calls
    assert not env.j.report['save_verified']


def test_foreign_document_is_not_closed_and_forbids_exit(env):
    env.b.foreign=[dict(path='C:/other/user.SLDPRT',title='user.SLDPRT',type=1)]
    m.run_steps(env.b,env.j,env.p)
    assert close_calls(env.b)==[('close_target',env.p['expected_document_path'])]
    assert 'exit' not in env.b.calls and env.j.report['close_verified']
    assert env.j.report['exit_skipped_reason']=='other_documents_remain_in_owned_process'


@pytest.mark.parametrize('change',['pid','source','document'])
def test_guard_rechecked_after_pending_before_save(env,monkeypatch,change):
    claim=env.j.claim
    def changed(name):
        claim(name)
        if name=='SaveActiveDocument':
            if change=='pid':env.b.pid=999
            elif change=='source':env.source.write_bytes(b'foreign saved bytes')
            else:env.b.document['path']='C:/foreign.SLDPRT'
    monkeypatch.setattr(env.j,'claim',changed)
    with pytest.raises(ValueError):m.run_steps(env.b,env.j,env.p)
    assert 'save' not in env.b.calls and not close_calls(env.b) and 'exit' not in env.b.calls
    assert env.j.report['actions']['SaveActiveDocument']['pending'] is True


def test_pending_persistence_failure_prevents_save(env,monkeypatch):
    def fail(name):raise OSError('Cannot write durable pending')
    monkeypatch.setattr(env.j,'claim',fail)
    with pytest.raises(OSError):m.run_steps(env.b,env.j,env.p)
    assert 'save' not in env.b.calls and not close_calls(env.b) and 'exit' not in env.b.calls


def test_existing_once_marker_prevents_second_save(env):
    m.marker_path(env.p).write_text('{}')
    with pytest.raises((ValueError,FileExistsError)):m.run_steps(env.b,env.j,env.p)
    assert 'save' not in env.b.calls and not close_calls(env.b) and 'exit' not in env.b.calls


def test_close_failure_never_exits_or_claims_closed(env):
    env.b.close_result=1
    with pytest.raises(ValueError,match='Close'):m.run_steps(env.b,env.j,env.p)
    assert env.b.calls.count('save')==1 and len(close_calls(env.b))==1
    assert env.j.report['save_verified'] and not env.j.report['close_verified'] and 'exit' not in env.b.calls


def test_unchanged_saved_bytes_do_not_allow_close_or_exit(env,monkeypatch):
    def unchanged_save():
        env.b.calls.append('save');env.b.saved=True;env.b.document['needs_save']=False
        return 0
    monkeypatch.setattr(env.b,'save',unchanged_save)
    with pytest.raises(ValueError):m.run_steps(env.b,env.j,env.p)
    assert env.b.calls.count('save')==1 and not close_calls(env.b) and 'exit' not in env.b.calls
    assert not env.j.report['save_verified'] and not env.j.report['close_verified']
    assert m._file_hash(env.source)==env.p['expected_source_sha256']
