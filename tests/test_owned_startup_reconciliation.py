"""Owned startup reconciliation tests with no COM or live process access."""
import json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp-server'))
import server
from scripts import sw_owned_startup_reconciliation as m
from scripts import sw_owned_empty_exit as exit_core

@pytest.fixture
def case(tmp_path):
    source=tmp_path/'startup.json';exe=str(tmp_path/'SLDWORKS.exe')
    original=dict(status='uncertain',phase='waiting_for_exact_pid_rot',launch_mode='executable',
        launch_attempted=True,new_process_verified=True,process_id=123,known_process_ids_before=[0,122],
        executable=exe,launch_intent_time=1699999999.0,process_identity=dict(process_id=123,
        create_time=1700000000.0,executable=exe,alive=True),user_control_verified=False,visible_verified=False,
        automatic_retry=False,termination_attempted=False,startup_receipt_path=str(source),
        error=dict(type='SolidWorksConnectionError',message='[SW_PROCESS_NOT_FOUND] attach: exact PID not ready'))
    source.write_text(json.dumps(original))
    p=dict(process_id=123,expected_creation_filetime=m._EPOCH+1700000000*10000000,expected_executable_path=exe,
        startup_receipt_path=str(source),startup_receipt_sha256=exit_core.digest(source),receipt_path=str(tmp_path/'reconciled.json'))
    class Fake:
        def __init__(self):self.started=0;self.closed=0;self.snapshots=0;self.visible=False;self.docs=[];self.user=True;self.owner_change=False
        def start(self):self.started+=1
        def owner(self):return dict(process_id=123,creation_filetime=p['expected_creation_filetime']+int(self.owner_change),executable=exe,alive=True)
        def snapshot(self):
            self.snapshots+=1
            return dict(process_id=123,documents=self.docs,document_count=len(self.docs),active_document=None,user_control=self.user,visible=self.visible)
        def close(self):self.closed+=1
    b=Fake()
    def rewrite(fn):
        obj=json.loads(source.read_text());fn(obj);source.write_text(json.dumps(obj));p['startup_receipt_sha256']=exit_core.digest(source)
    return SimpleNamespace(**locals())

@pytest.mark.parametrize('visible',[True,False,None])
def test_reconciles_into_separate_ownership_without_altering_original(case,visible):
    c=case;c.b.visible=visible;before=c.source.read_bytes()
    out=m.run_reconciliation(c.p,backend=c.b)
    assert out['status']=='ok' and out['phase']=='connected' and out['ownership_verified']
    assert out['readback_verified'] and out['original_receipt_preserved'] and out['visible_observed'] is visible
    assert out['launch_attempted'] is True and out['launch_attempted_by_reconciliation'] is False
    assert out['mutation_attempted'] is False and not out['exit_attempted']
    assert c.b.started==1 and c.b.snapshots==2 and c.b.closed==1
    assert c.source.read_bytes()==before
    assert json.loads(Path(c.p['receipt_path']).read_text())==out
    exit_core.validate_ownership(out,c.p)

@pytest.mark.parametrize('change',[
    lambda v:v.update(status='ok'),lambda v:v.update(phase='visible_intent'),
    lambda v:v.update(new_process_verified=False),lambda v:v.update(launch_attempted=False),
    lambda v:v.update(launch_mode='com'),lambda v:v.update(known_process_ids_before=[123]),
    lambda v:v.update(known_process_ids_before=[True]),lambda v:v.update(known_process_ids_before=[1,1]),
    lambda v:v.update(known_process_ids_before=list(range(8193))),lambda v:v.update(process_id=124),
    lambda v:v.update(automatic_retry=True),lambda v:v.update(termination_attempted=True),
    lambda v:v.update(user_control_verified=True),lambda v:v.update(visible_verified=True),
    lambda v:v.update(startup_receipt_path='C:/other.json'),lambda v:v.update(error={'type':'ValueError','message':'x'}),
    lambda v:v['error'].update(message='[OTHER] different stage'),lambda v:v['process_identity'].update(alive=False),
    lambda v:v['process_identity'].update(create_time=1700000001.0),lambda v:v.update(launch_intent_time=1700000001.0),
    lambda v:v['process_identity'].update(executable='C:/other/SLDWORKS.exe'),
])
def test_unproven_launch_never_opens_process(case,change):
    case.rewrite(change)
    with pytest.raises((ValueError,KeyError)):m.run_reconciliation(case.p,backend=case.b)
    assert case.b.started==0

@pytest.mark.parametrize('field,value',[
    ('process_id',True),('expected_creation_filetime',True),('expected_creation_filetime',0),
    ('expected_executable_path','relative/SLDWORKS.exe'),('startup_receipt_path','relative.json'),
    ('startup_receipt_sha256','wrong'),('receipt_path','relative.json'),
])
def test_strict_inputs(case,field,value):
    p=case.p|{field:value}
    with pytest.raises(ValueError):m.run_reconciliation(p,backend=case.b)
    assert case.b.started==0


def test_source_hash_change_rejected_before_attach(case):
    case.source.write_text('{}')
    with pytest.raises(ValueError):m.run_reconciliation(case.p,backend=case.b)
    assert not case.b.started


def test_existing_or_original_output_rejected(case):
    with pytest.raises(ValueError):m.run_reconciliation(case.p|{'receipt_path':str(case.source)},backend=case.b)
    Path(case.p['receipt_path']).write_text('previous')
    with pytest.raises(ValueError):m.run_reconciliation(case.p,backend=case.b)
    assert not case.b.started

@pytest.mark.parametrize('kind',['owner','documents','user','snapshot_error','snapshot_drift','source_drift','connect','cleanup'])
def test_live_failure_never_creates_verified_ownership(case,kind):
    c=case
    if kind=='owner':c.b.owner_change=True
    if kind=='documents':c.b.docs=['hidden']
    if kind=='user':c.b.user=False
    if kind=='snapshot_error':c.b.snapshot=Mock(side_effect=RuntimeError('unreadable'))
    if kind=='snapshot_drift':
        c.b.snapshot=Mock(side_effect=[dict(process_id=123,documents=[],document_count=0,active_document=None,user_control=True,visible=False),dict(process_id=123,documents=['other'],document_count=1,active_document=None,user_control=True,visible=False)])
    if kind=='source_drift':
        base=c.b.snapshot
        def snapshot():
            c.source.write_text('{}');return base()
        c.b.snapshot=snapshot
    if kind=='connect':c.b.start=Mock(side_effect=RuntimeError('no matching proxy'))
    if kind=='cleanup':c.b.close=Mock(side_effect=RuntimeError('handle close error'))
    out=m.run_reconciliation(c.p,backend=c.b)
    assert out['status']=='error' and not out['ownership_verified'] and not out['readback_verified']
    with pytest.raises(ValueError):exit_core.validate_ownership(out,c.p)


def test_final_write_failure_returns_error_and_leaves_non_authoritative_receipt(case,monkeypatch):
    real=m._write_receipt
    def write(path,value,**kw):
        if not kw.get('create'):raise OSError('disk')
        return real(path,value,**kw)
    monkeypatch.setattr(m,'_write_receipt',write)
    out=m.run_reconciliation(case.p,backend=case.b)
    assert out['status']=='error' and not out['ownership_verified']
    assert json.loads(Path(case.p['receipt_path']).read_text())['status']=='pending'


def test_reconciled_receipt_accepted_by_unchanged_verified_empty_exit(case):
    c=case;out=m.run_reconciliation(c.p,backend=c.b)
    source=c.tmp_path/'part.SLDPRT';source.write_bytes(b'saved')
    empty=c.tmp_path/'empty.json';empty.write_text(json.dumps(dict(status='ok',process_id=123,documents=[],document_count=0,active_document=None,user_control=True,mutation_attempted=False)))
    p={k:c.p[k] for k in ('process_id','expected_creation_filetime','expected_executable_path')}
    p.update(expected_document_path=str(source),expected_source_sha256=exit_core.digest(source),
        ownership_receipt_path=c.p['receipt_path'],ownership_receipt_sha256=exit_core.digest(c.p['receipt_path']),
        empty_receipt_path=str(empty),empty_receipt_sha256=exit_core.digest(empty),receipt_path=str(c.tmp_path/'exit.json'),
        wait_milliseconds=10000,acknowledge_exit_owned_empty_session=True,acknowledge_restored_checkpoint_exit=True)
    plan=exit_core.prepare_verified_empty(exit_core.verified_empty_parameters(p))
    assert plan['values']['ownership']['startup_ownership_reconciled'] is True
    assert plan['empty_observation']['document_count']==0


def test_mcp_schema_and_exact_selected_process(case,monkeypatch):
    cls=server.SolidWorksReconcileOwnedStartupInput;p=cls(**case.p)
    with pytest.raises(ValueError):cls(**(case.p|{'process_id':True}))
    with pytest.raises(ValueError):cls(**(case.p|{'unknown':1}))
    monkeypatch.setattr(server,'_selected_process_id',124)
    monkeypatch.setattr(server,'_run_locked',lambda op,fmt,**kw:op())
    run=Mock();monkeypatch.setattr(m,'reconcile_owned_startup',run)
    with pytest.raises(ValueError):server.solidworks_reconcile_owned_startup(p)
    run.assert_not_called()
    monkeypatch.setattr(server,'_selected_process_id',123)
    run.return_value={'status':'ok'}
    assert server.solidworks_reconcile_owned_startup(p)=={'status':'ok'}
    run.assert_called_once_with(case.p)


def test_native_backend_reads_only_no_setters_and_never_exits(case,monkeypatch):
    c=case;sw=SimpleNamespace(GetProcessID=Mock(return_value=123),GetDocuments=Mock(return_value=None),ActiveDoc=None,UserControl=True,Visible=False)
    b=m.NativeBackend(c.p);b.sw=sw
    assert b.snapshot()['visible'] is False
    sw.GetDocuments.return_value=[object()]
    with pytest.raises(ValueError):b.snapshot()
    assert not hasattr(b,'exit_once') and not hasattr(b,'load_once')
