"""Reopen acceptance boundaries using fake native reads and real evidence files."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import pytest

spec = importlib.util.spec_from_file_location('staged_pause_reopen', Path(__file__).resolve().parents[1] / 'scripts' / 'sw_cam_pause_reopen.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return m._file_hash(path)


@pytest.fixture
def env(tmp_path):
    source = tmp_path / 'owned.SLDPRT'; source.write_bytes(b'saved partial finish')
    tlb = tmp_path / 'camworks.tlb'; tlb.write_bytes(b'metadata')
    ids = [195, 196, 267, 247, 248, 271, 143, 144]
    counts = {267: 760, 247: 191, 248: 74, 271: 29, 143: 31196}
    snapshot = dict(document=dict(path=str(source), title=source.name, type=1, needs_save=False),
        saved_file_sha256=m._file_hash(source), machine_type=1, feature_ids=list(range(1, 21)) + [79],
        feature_setup_ids=[69, 71, 73], operation_setup_ids=[93, 94, 95], operation_ids=ids,
        tool_ids=list(range(1, 19)) + [273], finish_fields=deepcopy(m.pause.FIELDS),
        operations=[dict(id=oid, setup_id=93, generated=oid in counts, suppressed=False,
            tool_id=273 if oid == 144 else 145, record_counts=[counts[oid]] if oid in counts else [], feature_ids=[79]) for oid in ids])
    saved = dict(scope=m.pause.SCOPE, status='paused_saved_closed', process_id=123,
                 source_path=str(source), saved_source_sha256=m._file_hash(source), after=snapshot,
                 save_verified=True, close_verified=True)
    startup = dict(status='ok', phase='connected', process_id=456, new_process_verified=True,
                   user_control_verified=True, visible_verified=True, known_process_ids_before=[123, 999],
                   process_identity=dict(process_id=456, create_time=123456.0, executable='C:/SolidWorks.exe', alive=True))
    saved_path = tmp_path / 'pause.json'; startup_path = tmp_path / 'startup.json'
    p = dict(process_id=456, expected_document_path=str(source), expected_source_sha256=m._file_hash(source),
             addin_clsid='{00000000-0000-0000-0000-000000000000}', typelib_path=str(tlb),
             receipt_path=str(tmp_path / 'result.json'), module_sha256=m._file_hash(m.__file__),
             pause_receipt_path=str(saved_path), pause_receipt_sha256=write_json(saved_path, saved),
             startup_receipt_path=str(startup_path), startup_receipt_sha256=write_json(startup_path, startup))
    return SimpleNamespace(p=p, source=source, snapshot=snapshot, saved=saved, startup=startup, calls=[])


class Backend:
    def __init__(self, sw, p, journal):
        self.env=sw;self.p=p;self.journal=journal
    def start(self):
        self.env.calls.append('start')
        m.require(self.env.startup['process_id']==self.p['process_id'], 'Wrong live PID')
    def capture(self, label):
        self.env.calls.append('capture')
        self.journal.report['phase']=label
        return deepcopy(self.env.snapshot)
    def boundary(self, document, sha):
        self.env.calls.append('boundary')
        if getattr(self.env, 'drift_after_capture', False):self.env.source.write_bytes(b'changed')
        m.require(m._file_hash(self.env.source)==sha, 'Source drift after capture')
    def stop_events(self):
        self.env.calls.append('stop_events')
        if getattr(self.env, 'cleanup_error', False):raise RuntimeError('event unsubscribe failed')
        self.journal.report['messages']=dict(subscribed=True, disconnected=True, active=False,
            event_count=0, overflow=0, callback_errors=[], callback_error_count=0,
            subscription_error=None, disconnect_errors=[])
    def __getattr__(self, name):
        raise AssertionError('Unexpected backend operation: '+name)


def run(env):
    return m.execute(env, env.p, backend_factory=Backend)


def test_success_only_reads_and_preserves_clean_saved_state(env):
    m.validate_request(dict(action='verify_reopened_owned', params=env.p))
    original=env.source.read_bytes()
    result=run(env)
    assert result['status']=='reopen_verified' and result['reopen_verified'] is True
    assert env.calls==['start','capture','boundary','stop_events']
    assert env.source.read_bytes()==original and all(result[k] is False for k in m.FLAGS)
    loaded=m.load_verified_reopen(env.p['receipt_path'],m._file_hash(env.p['receipt_path']))
    assert loaded['actual']==env.snapshot and loaded['startup_identity']==env.startup['process_identity']


@pytest.mark.parametrize('change',['dirty','bottom','lead','record_count','tool','suppressed','feature','setup','order','source_hash'])
def test_actual_mismatch_is_durable_before_failure(env, change):
    if change=='dirty':env.snapshot['document']['needs_save']=True
    elif change=='bottom':env.snapshot['finish_fields']['bottom_finish']=True
    elif change=='lead':env.snapshot['finish_fields']['out_independent']=True
    elif change=='record_count':env.snapshot['operations'][2]['record_counts']=[761]
    elif change=='tool':env.snapshot['tool_ids'][0]=999
    elif change=='suppressed':env.snapshot['operations'][2]['suppressed']=True
    elif change=='feature':env.snapshot['feature_ids'][0]=999
    elif change=='setup':env.snapshot['feature_setup_ids'][0]=999
    elif change=='order':env.snapshot['operations'][0],env.snapshot['operations'][1]=env.snapshot['operations'][1],env.snapshot['operations'][0]
    else:env.snapshot['saved_file_sha256']='0'*64
    result=run(env)
    saved=json.loads(Path(env.p['receipt_path']).read_text())
    assert result['status']=='error' and result['reopen_verified'] is False
    assert saved['actual']==env.snapshot and 'stop_events' in env.calls
    with pytest.raises(ValueError):m.load_verified_reopen(env.p['receipt_path'],m._file_hash(env.p['receipt_path']))


@pytest.mark.parametrize('evidence',['pause','startup'])
def test_changed_evidence_rejected_before_native(env,evidence):
    Path(env.p[evidence+'_receipt_path']).write_text('{}')
    with pytest.raises(ValueError,match='Pinned evidence changed'):run(env)
    assert env.calls==[]


def test_source_drift_before_native_rejected(env):
    env.source.write_bytes(b'changed')
    result=run(env)
    assert result['status']=='error' and env.calls==['stop_events']


def test_source_drift_after_capture_preserves_actual_and_rejects(env):
    env.drift_after_capture=True
    result=run(env)
    assert result['status']=='error' and 'actual' in result and result['reopen_verified'] is False


def test_cleanup_failure_cannot_promote_verified(env):
    env.cleanup_error=True
    result=run(env)
    assert result['comparison_verified'] is True and result['status']=='error' and not result['reopen_verified']


@pytest.mark.parametrize('field,value',[('process_id',999),('new_process_verified',False),('user_control_verified',False),('visible_verified',False),('status','error')])
def test_unowned_startup_rejected_before_native(env,field,value):
    env.startup[field]=value
    env.p['startup_receipt_sha256']=write_json(Path(env.p['startup_receipt_path']),env.startup)
    with pytest.raises(ValueError):run(env)
    assert env.calls==[]


def test_preexisting_process_not_owned(env):
    env.startup['known_process_ids_before'].append(456)
    env.p['startup_receipt_sha256']=write_json(Path(env.p['startup_receipt_path']),env.startup)
    with pytest.raises(ValueError,match='preexisting'):run(env)
    assert env.calls==[]


def test_output_cannot_overwrite_old_receipt(env):
    Path(env.p['receipt_path']).write_text('old')
    with pytest.raises(ValueError,match='New receipt'):m.validate_request(dict(action='verify_reopened_owned',params=env.p))
    assert Path(env.p['receipt_path']).read_text()=='old'


@pytest.mark.parametrize('method',['save','close_target','exit_owned'])
def test_native_backend_explicitly_forbids_mutators(env,method):
    backend=m.NativeBackend(None,env.p,SimpleNamespace(report={}))
    with pytest.raises(RuntimeError,match='Read-only'):getattr(backend,method)()


@pytest.mark.parametrize('kind',['pid','create_time','executable','alive'])
def test_process_identity_guard_rejects_wrong_or_recycled_process(env,monkeypatch,kind):
    from scripts import sw_executable_launch
    identity=deepcopy(env.startup['process_identity'])
    if kind=='pid':sw=SimpleNamespace(GetProcessID=lambda:999)
    else:
        sw=SimpleNamespace(GetProcessID=lambda:456)
        identity[kind]={'create_time':987654.0,'executable':'C:/foreign.exe','alive':False}[kind]
    monkeypatch.setattr(sw_executable_launch,'_process_identity',lambda pid:identity)
    backend=m.NativeBackend(sw,env.p,SimpleNamespace(report={'startup_identity':env.startup['process_identity']}))
    with pytest.raises(ValueError):backend.owned()


def test_success_loader_rejects_source_changed_after_receipt(env):
    run(env);receipt_sha=m._file_hash(env.p['receipt_path'])
    env.source.write_bytes(b'later saved version')
    with pytest.raises(ValueError,match='since changed'):m.load_verified_reopen(env.p['receipt_path'],receipt_sha)


def test_success_loader_rejects_false_readonly_claim(env):
    r=run(env);r['save_attempted']=True
    sha=write_json(Path(env.p['receipt_path']),r)
    with pytest.raises(ValueError,match='Read-only'):m.load_verified_reopen(env.p['receipt_path'],sha)


def test_module_pin_prevents_unreviewed_code(env):
    env.p['module_sha256']='0'*64
    with pytest.raises(ValueError,match='module changed'):m.validate_request(dict(action='verify_reopened_owned',params=env.p))
