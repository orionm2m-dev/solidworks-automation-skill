"""MILL lifecycle regressions: native objects replaced; no CAD connection."""
from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_events as events
from scripts import sw_cam_mill_lifecycle as cam
from scripts import sw_cam_lifecycle as entry
from scripts import sw_cam_mill_qualification as mill


@pytest.fixture
def probe(monkeypatch, tmp_path):
    path = tmp_path/'MILL_QUAL.sldprt'; path.write_bytes(b'checkpoint')
    receipt = tmp_path/'save.json'
    document = dict(path=str(path), title=path.name, type=1, needs_save=True)
    machine = dict(machine_type=1, name='Mill - Metric', machine_id='shared ID', description='Sample mill')
    current = dict(document=document, saved_file_sha256=cam._file_hash(path), current_machine=machine,
        mill_catalogue=[deepcopy(machine),dict(machine, name='Mill 4axis - Metric')],
        feature_setups=[], operation_counts=[], material_raw='6061-T6', extend_holes_to_stock=False,
        unit_record_raw=None, unit_record_status='disabled')
    state = dict(current=current, on_capture=None, on_native=None, on_exit=None, returned=0)
    data = dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
                callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    class Session:
        def __enter__(self):data.update(subscribed=True,active=True,disconnected=False);return self
        def __exit__(self,*_):
            data.update(active=False,disconnected=True)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(data)
    sw = N(GetProcessID=Mock(return_value=123), UserControl=True, GetDocuments=Mock(return_value=[]))
    app = N()
    def native(action):
        assert data['active']
        durable=json.loads(receipt.read_text())
        assert durable['native_dispatch_pending'] is True and durable['native_call_returned'] is False
        if action=='save':
            current['document']['needs_save']=False
            path.write_bytes(b'saved native mock')
            current['saved_file_sha256']=cam._file_hash(path)
        if state['on_native']:state['on_native']()
        return state['returned']
    app.SaveActiveDocument=Mock(side_effect=lambda:native('save'))
    app.CloseActiveDocument=Mock(side_effect=lambda:native('close'))
    def snapshot(*_,**kw):
        assert data['active'] and kw['required_machine_type']==1
        kw['check']()
        if state['on_capture']:state['on_capture']()
        kw['check']()
        kw['diagnostic'].update(capture_complete=True)
        return deepcopy(current),dict(app=app)
    snapshots=Mock(side_effect=snapshot)
    bootstrap=Mock(return_value=app)
    monkeypatch.setattr(cam,'_bootstrap',bootstrap)
    monkeypatch.setattr(cam,'_mill_snapshot',snapshots)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(current['document']))
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    monkeypatch.setattr(entry,'_snapshot',Mock(side_effect=AssertionError('TURN snapshot forbidden')))
    def digest():return cam._digest(dict(deepcopy(current),machine_kind='mill_qualification',process_id=123))
    def run(action='save',**extra):
        args=dict(machine_kind='mill_qualification',process_id=123,acknowledge_qualification_copy=True,
            expected_document_path=str(path),action=action)
        if action!='prepare':args.update(expected_state_sha256=digest(),receipt_path=str(receipt))
        return entry.document_lifecycle(sw,'clsid','tlb',**(args|extra))
    return N(**locals())


def test_dirty_empty_mill_saves_once_with_full_readback(probe):
    out=probe.run()
    assert out['save_readback_verified'] and out['native_save_call_returned']
    assert out['native_return_type']=='int' and out['native_return_value']==0
    assert out['after']['document']['needs_save'] is False and out['saved_file_changed']
    assert out['status']=='review_required' and not out['persistence_verified'] and not out['may_continue']
    assert probe.snapshots.call_count==3 and out['messages']['disconnected']
    assert not out['post_cleanup_CAM_getters'] and not out['generation_attempted']
    probe.app.SaveActiveDocument.assert_called_once_with();probe.app.CloseActiveDocument.assert_not_called()
    assert json.loads(probe.receipt.read_text())==out


def test_one_setup_one_feature_save_preserves_configuration(probe):
    probe.current['feature_setups']=[dict(native_id=7,name='Setup',feature_count=1,
        axis_native=[0.,0.,1.],origin_native=[0.,0.,0.],origin_type_raw=0)]
    probe.current['operation_counts']=[0]
    out=probe.run()
    assert out['save_readback_verified']
    assert out['before']['feature_setups']==out['after']['feature_setups']


def test_prepare_dirty_runs_all_snapshots_under_session_and_no_receipt(probe):
    out=probe.run('prepare')
    assert out['status']=='ok' and out['state_sha256']==probe.digest()
    assert out['before']['document']['needs_save'] and probe.snapshots.call_count==1
    assert not probe.receipt.exists() and out['messages']['disconnected']
    probe.app.SaveActiveDocument.assert_not_called()


@pytest.mark.parametrize('case',['operations','non_mill','stale','wrong_pid','ack','scope_hash','second_capture'])
def test_preconditions_never_dispatch(probe,case):
    extra={}
    if case=='operations':probe.current['operation_counts']=[0,1]
    if case=='non_mill':probe.current['current_machine']['machine_type']=3
    if case=='stale':extra['expected_state_sha256']='0'*64
    if case=='wrong_pid':probe.sw.GetProcessID.return_value=124
    if case=='ack':extra['acknowledge_qualification_copy']=False
    if case=='scope_hash':extra['expected_state_sha256']=cam._digest(probe.current)
    if case=='second_capture':
        def change():
            if probe.snapshots.call_count==2:probe.current['material_raw']='other'
        probe.state['on_capture']=change
    out=probe.run(**extra)
    assert not out['mutation_attempted'] and not out['save_readback_verified']
    probe.app.SaveActiveDocument.assert_not_called();probe.app.CloseActiveDocument.assert_not_called()


@pytest.mark.parametrize('returned',[None,False,True,1,0.0])
def test_unknown_native_return_recorded_without_false_success(probe,returned):
    probe.state['returned']=returned
    out=probe.run()
    assert out['status']=='uncertain' and out['native_call_returned'] and not out['save_readback_verified']
    assert out['native_return_type']==type(returned).__name__
    assert type(out['native_return_value']) is type(returned) and out['native_return_value']==returned
    assert probe.snapshots.call_count==2
    probe.app.SaveActiveDocument.assert_called_once_with()


@pytest.mark.parametrize('case',['inventory','document','dirty','event','exception'])
def test_post_save_unrequested_change_stops_verification(probe,case):
    def change():
        if case=='inventory':probe.current['feature_setups'].append(dict(native_id=1,name='Unexpected',feature_count=1))
        if case=='document':probe.current['document']['title']='Changed'
        if case=='dirty':probe.current['document']['needs_save']=True
        if case=='event':probe.data['event_count']=1
        if case=='exception':raise RuntimeError('native transport exception')
    probe.state['on_native']=change
    out=probe.run()
    assert out['status']=='uncertain' and not out['save_readback_verified']
    probe.app.SaveActiveDocument.assert_called_once_with()
    if case in ('event','exception'):assert probe.snapshots.call_count==2


@pytest.mark.parametrize('case',['event','disconnect','file','document'])
def test_cleanup_failures_clear_verified_without_CAM_reads(probe,case):
    def change():
        if case=='event':probe.data['event_count']=1
        if case=='disconnect':probe.data['disconnect_errors']=[{'type':'failure'}]
        if case=='file':probe.path.write_bytes(b'changed after disconnect')
        if case=='document':probe.current['document']['needs_save']=True
    probe.state['on_exit']=change
    out=probe.run()
    assert out['status']=='uncertain' and not out['save_readback_verified']
    assert probe.snapshots.call_count==3 and not out['post_cleanup_CAM_getters']


def test_event_during_initial_capture_stops_next_getter_and_dispatch(probe):
    probe.state['on_capture']=lambda:probe.data.update(event_count=1)
    out=probe.run()
    assert out['status']=='review_required' and not out['mutation_attempted']
    assert probe.snapshots.call_count==1
    probe.app.SaveActiveDocument.assert_not_called()


def test_close_clean_uses_SW_only_after_native_close(probe):
    probe.current['document']['needs_save']=False
    out=probe.run('close')
    assert out['close_verified'] and not out['save_readback_verified']
    assert probe.snapshots.call_count==2 and probe.sw.GetDocuments.call_count==2
    assert not out['persistence_verified']
    probe.app.CloseActiveDocument.assert_called_once_with();probe.app.SaveActiveDocument.assert_not_called()


@pytest.mark.parametrize('case',['dirty','background','still_open','file_changed'])
def test_close_guards(probe,case):
    probe.current['document']['needs_save']=case=='dirty'
    if case=='background':probe.sw.UserControl=False
    if case=='still_open':
        probe.sw.GetDocuments.return_value=[N(GetPathName=lambda:str(probe.path),GetTitle=lambda:probe.path.name,GetType=lambda:1)]
    if case=='file_changed':probe.state['on_native']=lambda:probe.path.write_bytes(b'changed on close')
    out=probe.run('close')
    assert not out['close_verified']
    assert probe.app.CloseActiveDocument.call_count==(case in ('still_open','file_changed'))


def test_consumed_receipt_never_replays(probe):
    probe.receipt.write_text('{}')
    out=probe.run()
    assert not out['mutation_attempted'] and probe.bootstrap.call_count==0
    assert probe.receipt.read_text()=='{}'


def test_pre_dispatch_receipt_failure_has_no_native_action(probe,monkeypatch):
    writer=cam._write_receipt
    def fail(path,report,**kw):
        if report['native_dispatch_pending']:raise OSError('durable intent failed')
        return writer(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    out=probe.run()
    assert not out['mutation_attempted']
    probe.app.SaveActiveDocument.assert_not_called()


def test_real_mill_snapshot_rejects_wrong_kind_before_subtype_getters(monkeypatch,tmp_path):
    path=tmp_path/'part.sldprt';path.write_bytes(b'part')
    docinfo=dict(path=str(path),title=path.name,type=1,needs_save=True)
    machine=N(MachType=Mock(return_value=3))
    doc=N(GetDocType=Mock(return_value=1),IGetMachine=Mock(return_value=machine))
    app=N(IGetActiveDoc=Mock(return_value=doc))
    sw=N(GetAddInObject=Mock(return_value=N(GetCWApp=Mock(return_value=app))))
    types=[]
    def typed(obj,name,*_):types.append(name);return obj
    monkeypatch.setattr(mill,'_typed',typed)
    monkeypatch.setattr(mill,'document_snapshot',lambda *_:docinfo)
    diagnostic={}
    with pytest.raises(ValueError,match='before subtype getters'):
        mill._snapshot(sw,'clsid','tlb',str(path),required_machine_type=1,diagnostic=diagnostic)
    assert 'ICWTurnMachine' not in types and 'ICWMillMachine' not in types
    assert diagnostic['document']==docinfo and diagnostic['error_code']=='MILL_REQUIRED_MACHINE_TYPE_MISMATCH'
