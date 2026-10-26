from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_events as events
from scripts import sw_cam_mill_feature_process as cam
from scripts import sw_cam_turn_feature_attribute as collections


def operation(native_id=201, index=0, **changes):
    return dict(setup_index=0, operation_index=index, native_id=native_id,
        mill_operation_type=3, base_operation_type=1, suppressed=False,
        linked_feature_ids=[111], toolpath_generated=False, toolpath_record_counts=[]) | changes


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path=tmp_path/'B.sldprt';path.write_bytes(b'clean saved B fixture')
    receipt=tmp_path/'gop.json'
    current=dict(document=dict(path=str(path),title=path.name,type=1,needs_save=False),
        saved_file_sha256=cam._file_hash(path),current_machine=dict(machine_type=1,name='Mill'),
        mill_catalogue=[dict(machine_type=1,name='Mill')],
        feature_setups=[dict(native_id=64,name='Setup',feature_count=1,axis_native=[0.,0.,1.],origin_native=[0.,0.,0.],origin_type_raw=6)],
        operation_counts=[0],material_raw='6061-T6',extend_holes_to_stock=False,
        selected_feature=dict(native_id=111,volume_type=6,suppressed=False,name='Pocket',depth_native=3.,
            axis_native=[0.,0.,1.],bounds_native=[5.,3.,3.],start_native=[1.,1.,22.],
            top_segments_native=[[[1.,1.,22.],[4.,1.,22.]]],bottom_segments_native=[[[1.,1.,22.],[4.,1.,22.]]]),
        operation_setup_count=1,operations=[])
    state=dict(current=current,on_snapshot=None,on_native=None,on_exit=None,returned=0)
    data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    class Session:
        def __enter__(self):data.update(subscribed=True,active=True,disconnected=False);return self
        def __exit__(self,*_):
            data.update(active=False,disconnected=True)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(data)
    def generate(pref):
        assert pref==1 and data['active']
        durable=json.loads(receipt.read_text())
        assert durable['native_dispatch_pending'] is True and durable['native_call_returned'] is False
        current['operations']=[operation(201),operation(202,1)]
        current['operation_counts']=[2];current['document']['needs_save']=True
        if state['on_native']:state['on_native']()
        return state['returned']
    feature=N(GenerateOpPlan=Mock(side_effect=generate))
    app=object();sw=N(GetProcessID=Mock(return_value=62876))
    def capture(*_,**kw):
        assert data['active'];kw['check']()
        if state['on_snapshot']:state['on_snapshot']()
        kw['check']();kw['diagnostic'].update(state=deepcopy(current),capture_complete=True)
        return deepcopy(current),dict(app=app,selected_feature=feature)
    captures=Mock(side_effect=capture)
    monkeypatch.setattr(cam,'capture_mill_feature_state',captures)
    monkeypatch.setattr(cam,'_bootstrap',Mock(return_value=app))
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(current['document']))
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    def digest():return cam._digest(dict(snapshot=current,process_id=62876,expected_feature_native_id=111,scope='MILL_SINGLE_FEATURE_GOP_RETAIN1'))
    def run(action='apply',**extra):
        args=dict(process_id=62876,expected_document_path=str(path),expected_source_sha256=cam._file_hash(path),
            expected_feature_native_id=111,action=action,qualification_only=True,acknowledge_disposable_copy=True)
        if action=='apply':args.update(expected_state_sha256=digest(),receipt_path=str(receipt))
        return cam.qualify_mill_feature_operation_plan(sw,'clsid','tlb',**(args|extra))
    return N(**locals())


def test_one_GOP_returns_two_exact_linked_operation_definitions(probe):
    out=probe.run()
    assert out['status']=='review_required' and out['readback_verified'] and out['insertion_delta_verified']
    assert [x['native_id'] for x in out['new_operations']]==[201,202]
    assert out['before']['document']['needs_save'] is False and out['after']['document']['needs_save'] is True
    assert not out['GTP_attempted'] and not out['model_saved'] and not out['physical_depth_verified']
    assert out['native_hresult']==0 and probe.captures.call_count==3 and out['messages']['disconnected']
    assert all(x['completed'] and x['elapsed_seconds']>=0 for x in out['phase_timings'])
    probe.feature.GenerateOpPlan.assert_called_once_with(1)
    assert json.loads(probe.receipt.read_text())==out


@pytest.mark.parametrize('action',['inspect','prepare'])
def test_read_actions_subscribe_and_do_not_create_receipt(probe,action):
    out=probe.run(action)
    assert out['status']=='ok' and out['apply_eligible']
    assert out['state_sha256']==probe.digest() and not probe.receipt.exists()
    assert probe.captures.call_count==1 and out['messages']['disconnected']
    probe.feature.GenerateOpPlan.assert_not_called()


def test_inspect_existing_dirty_generated_operation_is_read_only(probe):
    probe.current.update(operations=[operation(toolpath_generated=True,toolpath_record_counts=[15])],operation_counts=[1])
    probe.current['document']['needs_save']=True
    out=probe.run('inspect')
    assert out['status']=='ok' and not out['apply_eligible']
    probe.feature.GenerateOpPlan.assert_not_called()


@pytest.mark.parametrize('case',['stale','source','pid','dirty','existing','event','second_capture'])
def test_pre_dispatch_failures_never_GOP(probe,case):
    extra={}
    if case=='stale':extra['expected_state_sha256']='0'*64
    if case=='source':extra['expected_source_sha256']='0'*64
    if case=='pid':probe.sw.GetProcessID.return_value=2
    if case=='dirty':probe.current['document']['needs_save']=True
    if case=='existing':probe.current.update(operations=[operation()],operation_counts=[1])
    if case=='event':probe.state['on_snapshot']=lambda:probe.data.update(event_count=1)
    if case=='second_capture':
        def change():
            if probe.captures.call_count==2:probe.current['selected_feature']['depth_native']=4.
        probe.state['on_snapshot']=change
    out=probe.run(**extra)
    assert not out['mutation_attempted'] and not out['readback_verified']
    probe.feature.GenerateOpPlan.assert_not_called()


@pytest.mark.parametrize('case',['zero','too_many','wrong_link','duplicate_id','generated','records','suppressed','feature','file','event','exception'])
def test_partial_GOP_never_replayed_and_readback_not_promoted(probe,case):
    def change():
        ops=probe.current['operations']
        if case=='zero':probe.current.update(operations=[],operation_counts=[0])
        if case=='too_many':probe.current.update(operations=[operation(200+i,i) for i in range(33)],operation_counts=[33])
        if case=='wrong_link':ops[0]['linked_feature_ids']=[112]
        if case=='duplicate_id':ops[1]['native_id']=ops[0]['native_id']
        if case=='generated':ops[0]['toolpath_generated']=True
        if case=='records':ops[0]['toolpath_record_counts']=[5]
        if case=='suppressed':ops[0]['suppressed']=True
        if case=='feature':probe.current['selected_feature']['depth_native']=4.
        if case=='file':probe.path.write_bytes(b'unexpected save')
        if case=='event':probe.data['event_count']=1
        if case=='exception':raise RuntimeError('native failed after partial change')
    probe.state['on_native']=change
    out=probe.run()
    assert out['status']=='uncertain' and not out['insertion_delta_verified'] and not out['readback_verified']
    probe.feature.GenerateOpPlan.assert_called_once_with(1)
    if case not in ('file','event','exception'):
        assert out['after']==json.loads(probe.receipt.read_text())['after']
    second=probe.run()
    assert not second['mutation_attempted'] and probe.feature.GenerateOpPlan.call_count==1


def test_false_generated_with_actual_zero_record_containers_is_accepted(probe):
    probe.state['on_native']=lambda:probe.current['operations'][0].update(toolpath_record_counts=[0,0])
    out=probe.run();assert out['readback_verified']
    assert out['new_operations'][0]['toolpath_record_counts']==[0,0]


@pytest.mark.parametrize('value',[None,False,True,1,0.0])
def test_unexpected_hresult_preserved_no_followup_CAM(probe,value):
    probe.state['returned']=value
    out=probe.run()
    assert out['status']=='uncertain' and not out['readback_verified'] and out['native_call_returned']
    assert out['native_return_type']==type(value).__name__ and probe.captures.call_count==2


@pytest.mark.parametrize('case',['event','disconnect','doc','file'])
def test_cleanup_failures_no_CAM_reads_after_unsubscribe(probe,case):
    def changed():
        if case=='event':probe.data['event_count']=1
        if case=='disconnect':probe.data['disconnect_errors']=[dict(type='failure')]
        if case=='doc':probe.current['document']['needs_save']=False
        if case=='file':probe.path.write_bytes(b'changed')
    probe.state['on_exit']=changed
    out=probe.run()
    assert out['status']=='uncertain' and not out['readback_verified']
    assert probe.captures.call_count==3 and not out['post_cleanup_CAM_getters']


def test_durable_intent_failure_prevents_dispatch(probe,monkeypatch):
    writer=cam._write_receipt
    def fail(path,report,**kw):
        if report['native_dispatch_pending']:raise OSError('intent persistence failed')
        return writer(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    out=probe.run();assert not out['mutation_attempted']
    probe.feature.GenerateOpPlan.assert_not_called()


def test_after_snapshot_is_durable_before_verifier(probe,monkeypatch):
    verify=cam._verify_gop_delta
    def wrapped(before,after,*a):
        assert json.loads(probe.receipt.read_text())['after']==after
        return verify(before,after,*a)
    monkeypatch.setattr(cam,'_verify_gop_delta',wrapped)
    assert probe.run()['readback_verified']


@pytest.fixture
def reader(monkeypatch,tmp_path):
    path=tmp_path/'reader.sldprt';path.write_bytes(b'fixture')
    document=dict(path=str(path),title=path.name,type=1,needs_save=False)
    state=dict(document=document,saved_file_sha256=cam._file_hash(path),current_machine=dict(machine_type=1),
        feature_setups=[dict(native_id=64,feature_count=1)],operation_counts=[1])
    calls=[];blocked=[False]
    class Collection:
        def __init__(self,items,label):self.items=items;self.label=label;self.event=False
        def Count(self):
            calls.append(self.label+'.Count')
            if self.event:blocked[0]=True
            return len(self.items)
        def Item(self,index):calls.append(self.label+'.Item');return self.items[index]
    feature=N(native_id=111)
    paths=Collection([N(RecordCount=Mock(return_value=0))],'paths')
    op=N(native_id=201,OpernType=Mock(return_value=3),Suppressed=False,GetIsToolpathGenerated=Mock(return_value=False),
        IGetAllFeatures=Mock(return_value=Collection([feature],'links')),IGetEnumToolpaths=Mock(return_value=paths),
        IGetTool=Mock(side_effect=AssertionError('tool reader forbidden')))
    ops=Collection([op],'operations');feat_collection=Collection([feature],'features')
    setup=N(IGetEnumFeatures=Mock(return_value=feat_collection))
    machine=N(IGetEnumOpSetups=Mock(return_value=Collection([N(IGetEnumOperations=Mock(return_value=ops))],'opsetups')))
    doc=N(GetCWObjectID=Mock(side_effect=lambda obj:(obj.native_id,True)))
    native=dict(app=object(),doc=doc,machine=machine,setups=[setup])
    def check():
        if blocked[0]:raise ValueError('event stop')
    def initial(*_,**kw):kw['check']();return deepcopy(state),dict(native)
    monkeypatch.setattr(cam,'_mill_snapshot',initial)
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj);monkeypatch.setattr(collections,'_typed',lambda obj,*_:obj)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(document))
    monkeypatch.setattr(cam,'_feature',lambda obj,*_:dict(native_id=obj.native_id,volume_type=6,suppressed=False))
    diagnostic={}
    def run():return cam.capture_mill_feature_state(object(),'clsid','tlb',str(path),expected_feature_native_id=111,check=check,diagnostic=diagnostic)
    return N(**locals())


def test_real_snapshot_reads_false_generated_native_counts_and_ids(reader):
    state,native=reader.run()
    assert state['operations'][0]['toolpath_record_counts']==[0]
    assert state['operations'][0]['linked_feature_ids']==[111] and list(native['operations'])==[201]
    reader.op.IGetEnumToolpaths.assert_called_once_with();reader.op.IGetTool.assert_not_called()


def test_snapshot_does_not_invent_empty_counts_on_false_flag(reader):
    reader.paths.items[0].RecordCount.return_value=9
    state,_=reader.run()
    assert state['operations'][0]['toolpath_generated'] is False
    assert state['operations'][0]['toolpath_record_counts']==[9]


def test_nested_collection_event_blocks_next_Item(reader):
    reader.feat_collection.event=True
    with pytest.raises(ValueError,match='event stop'):reader.run()
    assert 'features.Count' in reader.calls and 'features.Item' not in reader.calls


def test_operation_bound_checked_before_any_operation_Item(reader):
    reader.ops.items=[reader.op]*33
    with pytest.raises(ValueError):reader.run()
    assert 'operations.Count' in reader.calls and 'operations.Item' not in reader.calls


def test_first_native_exception_retains_partial_snapshot_and_stops(reader):
    reader.op.IGetEnumToolpaths.side_effect=RuntimeError('native failure')
    with pytest.raises(RuntimeError):reader.run()
    partial=reader.diagnostic['state']['operations'][0]
    assert partial['native_id']==201 and partial['linked_feature_ids']==[111]
    assert reader.diagnostic['capture_complete'] is False and 'paths.Count' not in reader.calls
