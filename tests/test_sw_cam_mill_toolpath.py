from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_events as events
from scripts import sw_cam_mill_toolpath as cam


def operation(native_id=114, index=0, **kw):
    return dict(native_id=native_id,setup_index=0,operation_index=index,mill_operation_type=index,
        base_operation_type=1,suppressed=False,linked_feature_ids=[111],
        toolpath_generated=False,toolpath_record_counts=[]) | kw


@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/'B.sldprt';path.write_bytes(b'saved fixture with two MILL operations')
    receipt=tmp_path/'gtp.json'
    current=dict(document=dict(path=str(path),title=path.name,type=1,needs_save=False),
        saved_file_sha256=cam._file_hash(path),current_machine=dict(machine_type=1,name='Mill'),
        mill_catalogue=[dict(machine_type=1,name='Mill')],feature_setups=[dict(native_id=64,feature_count=1)],
        operation_counts=[2],operation_setup_count=1,material_raw='6061-T6',
        selected_feature=dict(native_id=111,volume_type=6,depth_native=3.,start_native=[1.,1.,22.]),
        operations=[operation(),operation(115,1)])
    tool=dict(native_read_complete=True,native_id=500,is_mill_tool=True,tool_type_raw=1,
        cut_diameter_native=2.,protrusion_native=10.,units_verified=False,holder_geometry_verified=False)
    state=dict(on_capture=None,on_native=None,on_exit=None,on_tool=None,returned=0)
    data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    class Session:
        def __enter__(self):data.update(subscribed=True,active=True,disconnected=False);return self
        def __exit__(self,*_):
            data.update(active=False,disconnected=True)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(data)
    def generate():
        assert data['active']
        durable=json.loads(receipt.read_text())
        assert durable['phase']=='GenerateToolpath' and durable['native_dispatch_pending'] is True
        assert durable['native_call_returned'] is False
        current['operations'][0].update(toolpath_generated=True,toolpath_record_counts=[37])
        current['document']['needs_save']=True
        if state['on_native']:state['on_native']()
        return state['returned']
    op=N(GenerateToolpath=Mock(side_effect=generate));other=N(GenerateToolpath=Mock(side_effect=AssertionError('other GTP forbidden')))
    sw=N(GetProcessID=Mock(return_value=62876));app=object()
    def capture(*_,**kw):
        assert data['active'];kw['check']()
        if state['on_capture']:state['on_capture']()
        kw['check']();kw['diagnostic'].update(state=deepcopy(current))
        return deepcopy(current),dict(app=app,doc=object(),operations={114:op,115:other})
    def read_tool(*args):
        assert data['active'];args[3]()
        if state['on_tool']:state['on_tool']()
        args[3]();return deepcopy(tool)
    captures=Mock(side_effect=capture)
    monkeypatch.setattr(cam,'capture_mill_feature_state',captures)
    monkeypatch.setattr(cam,'_read_assigned_tool',Mock(side_effect=read_tool))
    monkeypatch.setattr(cam,'_bootstrap',Mock(return_value=app))
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(current['document']))
    monkeypatch.setattr(cam,'_typed',lambda x,*_:x)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    def digest():return cam._digest(dict(snapshot=deepcopy(current)|dict(selected_tool=tool),process_id=62876,
        expected_feature_native_id=111,expected_operation_native_id=114,expected_mill_operation_type=0,
        scope='MILL_SELECTED_OPERATION_GTP'))
    def run(action='apply',**kw):
        args=dict(process_id=62876,expected_document_path=str(path),expected_source_sha256=cam._file_hash(path),
            expected_feature_native_id=111,expected_operation_native_id=114,expected_mill_operation_type=0,
            action=action,qualification_only=True,acknowledge_disposable_copy=True)
        if action=='apply':args.update(expected_state_sha256=digest(),receipt_path=str(receipt))
        return cam.qualify_mill_operation_toolpath(sw,'clsid','tlb',**(args|kw))
    return N(**locals())


def test_one_selected_GTP_preserves_other_operation_and_saved_source(probe):
    out=probe.run()
    assert out['status']=='review_required' and out['selected_toolpath_verified'] and out['readback_verified']
    assert out['selected_result']['native_id']==114 and out['selected_result']['toolpath_record_counts']==[37]
    assert out['before']['operations'][1]==out['after']['operations'][1]
    assert out['before']['selected_tool']==out['after']['selected_tool']
    assert out['native_hresult']==0 and out['native_call_seconds']>=0
    assert all(x['completed'] and x['elapsed_seconds']>=0 for x in out['phase_timings'])
    assert not out['model_saved'] and not out['physical_depth_verified'] and not out['units_verified']
    assert not out['GOP_attempted'] and not out['AFR_attempted']
    probe.op.GenerateToolpath.assert_called_once_with();probe.other.GenerateToolpath.assert_not_called()
    assert json.loads(probe.receipt.read_text())==out and out['messages']['disconnected']


@pytest.mark.parametrize('action',['inspect','prepare'])
def test_read_actions_capture_tool_and_do_not_generate(probe,action):
    out=probe.run(action)
    assert out['status']=='ok' and out['apply_eligible'] and out['before']['selected_tool']['native_id']==500
    assert not probe.receipt.exists() and probe.captures.call_count==1
    probe.op.GenerateToolpath.assert_not_called()


@pytest.mark.parametrize('case',['stale','dirty','already_generated','wrong_id','wrong_type','wrong_link','prewrite_change','tool_error','event'])
def test_before_dispatch_failure_has_no_GTP(probe,case):
    kw={}
    if case=='stale':kw['expected_state_sha256']='0'*64
    if case=='dirty':probe.current['document']['needs_save']=True
    if case=='already_generated':probe.current['operations'][0].update(toolpath_generated=True,toolpath_record_counts=[3])
    if case=='wrong_id':kw['expected_operation_native_id']=999
    if case=='wrong_type':kw['expected_mill_operation_type']=1
    if case=='wrong_link':probe.current['operations'][0]['linked_feature_ids']=[112]
    if case=='prewrite_change':
        def change():
            if probe.captures.call_count==2:probe.current['material_raw']='changed'
        probe.state['on_capture']=change
    if case=='tool_error':probe.state['on_tool']=lambda:(_ for _ in ()).throw(RuntimeError('native tool failure'))
    if case=='event':probe.state['on_capture']=lambda:probe.data.update(event_count=1)
    out=probe.run(**kw)
    assert out['status']=='error' and not out['mutation_attempted']
    probe.op.GenerateToolpath.assert_not_called()


@pytest.mark.parametrize('case',['not_generated','zero_records','other_op','selected_definition','tool_changed','feature_changed','file_changed','exception','event'])
def test_partial_or_unknown_GTP_is_not_replayed(probe,case):
    def change():
        if case=='not_generated':probe.current['operations'][0]['toolpath_generated']=False
        if case=='zero_records':probe.current['operations'][0]['toolpath_record_counts']=[0]
        if case=='other_op':probe.current['operations'][1]['toolpath_record_counts']=[9]
        if case=='selected_definition':probe.current['operations'][0]['base_operation_type']=9
        if case=='tool_changed':probe.tool['cut_diameter_native']=3.
        if case=='feature_changed':probe.current['selected_feature']['depth_native']=4.
        if case=='file_changed':probe.path.write_bytes(b'changed by unexpected save')
        if case=='exception':raise RuntimeError('COM returned exception after attempted generation')
        if case=='event':probe.data['event_count']=1
    probe.state['on_native']=change
    out=probe.run()
    assert out['status']=='uncertain' and out['mutation_attempted'] and not out['readback_verified']
    assert not out['selected_toolpath_verified'];probe.op.GenerateToolpath.assert_called_once()
    if case not in ('file_changed','exception','event'):assert 'after' in json.loads(probe.receipt.read_text())
    retry=probe.run();assert retry['status']=='error';probe.op.GenerateToolpath.assert_called_once()


@pytest.mark.parametrize('value',[None,False,True,1,0.0])
def test_unexpected_hresult_stops_before_followup_CAM(probe,value):
    probe.state['returned']=value;out=probe.run()
    assert out['status']=='uncertain' and out['native_call_returned'] and not out['readback_verified']
    assert probe.captures.call_count==2


@pytest.mark.parametrize('case',['event','disconnect','document'])
def test_cleanup_failure_never_runs_postcleanup_CAM(probe,case):
    def change():
        if case=='event':probe.data['event_count']=1
        if case=='disconnect':probe.data['disconnected']=False
        if case=='document':probe.current['document']['title']='different'
    probe.state['on_exit']=change;out=probe.run()
    assert out['status']=='uncertain' and not out['readback_verified'] and probe.captures.call_count==3


def test_receipt_intent_failure_blocks_dispatch(probe,monkeypatch):
    writer=cam._write_receipt
    def write(path,report,**kw):
        if report['native_dispatch_pending']:raise OSError('durable intent unavailable')
        return writer(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',write)
    out=probe.run();assert not out['mutation_attempted'];probe.op.GenerateToolpath.assert_not_called()


def test_after_evidence_persisted_before_verification(probe,monkeypatch):
    def reject(*args):
        durable=json.loads(probe.receipt.read_text());assert durable['after']['operations'][0]['toolpath_record_counts']==[37]
        raise ValueError('controlled verifier stop')
    monkeypatch.setattr(cam,'_verify_gtp_delta',reject)
    out=probe.run();assert out['status']=='uncertain' and not out['readback_verified']


@pytest.fixture
def tool_probe(monkeypatch):
    tool=N(IsMillTool=Mock(return_value=True),ToolType=1,CutDiameter=2.,Protrusion=10.)
    op=N(IGetTool=Mock(return_value=tool));seen=[];state=dict(block=False)
    def check():
        if state['block']:raise ValueError('event stop')
    native=dict(doc=object(),operations={114:op})
    monkeypatch.setattr(cam,'_typed',lambda x,*_:x)
    monkeypatch.setattr(cam,'_object_id',lambda *_:500)
    reader=cam._member
    def read(obj,name,*args):seen.append(name);return reader(obj,name,*args)
    monkeypatch.setattr(cam,'_member',read)
    diagnostic={}
    def run():return cam._read_assigned_tool(native,114,'tlb',check,diagnostic)
    return N(**locals())


def test_generic_tool_reader_uses_only_documented_bounded_scalars(tool_probe):
    row=tool_probe.run()
    assert row['native_id']==500 and row['cut_diameter_native']==2. and row['protrusion_native']==10.
    assert tool_probe.seen==['IGetTool','IsMillTool','ToolType','CutDiameter','Protrusion']
    assert row['native_read_complete'] and not row['units_verified'] and not row['holder_geometry_verified']


@pytest.mark.parametrize('case',['not_mill','tool_exception','event','invalid_dimension'])
def test_tool_reader_stops_once_preserves_partial_without_subtype_getters(tool_probe,case):
    if case=='not_mill':tool_probe.tool.IsMillTool.return_value=False
    if case=='tool_exception':tool_probe.op.IGetTool.side_effect=RuntimeError('native failure')
    if case=='event':
        def trigger():tool_probe.state['block']=True;return True
        tool_probe.tool.IsMillTool.side_effect=trigger
    if case=='invalid_dimension':tool_probe.tool.CutDiameter=float('nan')
    with pytest.raises((ValueError,RuntimeError)):tool_probe.run()
    assert tool_probe.diagnostic['selected_tool']['native_read_complete'] is False
    assert 'Protrusion' not in tool_probe.seen
    tool_probe.op.IGetTool.assert_called_once()
