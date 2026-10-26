from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_events as events
from scripts import sw_cam_mill_geometry as cam


def operation(native_id=114,index=0,generated=True):
    return dict(native_id=native_id,setup_index=0,operation_index=index,mill_operation_type=index,
        base_operation_type=1,suppressed=False,linked_feature_ids=[111],
        toolpath_generated=generated,toolpath_record_counts=[37] if generated else [])


@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/'B.sldprt';path.write_bytes(b'saved MILL path fixture')
    directory=tmp_path/'new_geometry';receipt=tmp_path/'export.json'
    current=dict(document=dict(path=str(path),title=path.name,type=1,needs_save=False),
        saved_file_sha256=cam._file_hash(path),current_machine=dict(machine_type=1,name='Mill'),
        feature_setups=[dict(native_id=64,feature_count=1)],operation_counts=[2],operation_setup_count=1,
        selected_feature=dict(native_id=111,volume_type=6,depth_native=3.,start_native=[1.,1.,22.]),
        operations=[operation(),operation(115,1,False)])
    state=dict(on_capture=None,on_native=None,on_exit=None,returned=True,kind='wip',write_file=True)
    data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    class Session:
        def __enter__(self):data.update(subscribed=True,active=True,disconnected=False);return self
        def __exit__(self,*_):
            data.update(active=False,disconnected=True)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(data)
    def export(kind,*args):
        assert data['active'] and kind==state['kind']
        durable=json.loads(receipt.read_text());assert durable['native_dispatch_pending'] is True
        if kind=='wip':
            assert args==(str(directory)+cam.os.sep,'wip.stl','',0,0)
        elif kind=='stock':assert args==(str(directory/'stock.stl'),'',0)
        else:assert args==(str(directory/'target.stl'),0)
        if state['write_file']:(directory/(kind+'.stl')).write_bytes(b'raw native STL evidence; mesh not validated')
        if state['on_native']:state['on_native']()
        return state['returned']
    machine=N(CreateSTLOfWIPs2=Mock(side_effect=lambda *a:export('wip',*a)),
        CreateSTLOfStock=Mock(side_effect=lambda *a:export('stock',*a)),
        CreateSTLOfTargetInFCSSpace=Mock(side_effect=lambda *a:export('target',*a)))
    sw=N(GetProcessID=Mock(return_value=62876));app=object()
    def capture(*_,**kw):
        assert data['active'];kw['check']()
        if state['on_capture']:state['on_capture']()
        kw['check']();kw['diagnostic'].update(state=deepcopy(current))
        return deepcopy(current),dict(app=app,machine=machine)
    captures=Mock(side_effect=capture)
    monkeypatch.setattr(cam,'capture_mill_feature_state',captures)
    monkeypatch.setattr(cam,'_bootstrap',Mock(return_value=app))
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(current['document']))
    monkeypatch.setattr(cam,'_typed',lambda x,*_:x)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    def digest():return cam._digest(dict(snapshot=current,process_id=62876,expected_feature_native_id=111,
        expected_operation_native_ids=[114,115],expected_generated_operation_native_ids=[114],
        export_kind=state['kind'],output_dir=str(directory),canonical_output_dir=str(directory.resolve()),
        scope='MILL_SINGLE_FEATURE_MACHINE_GEOMETRY_EXPORT'))
    def run(action='apply',**kw):
        args=dict(process_id=62876,expected_document_path=str(path),expected_source_sha256=cam._file_hash(path),
            expected_feature_native_id=111,expected_operation_native_ids=[114,115],expected_generated_operation_native_ids=[114],
            export_kind=state['kind'],output_dir=str(directory),action=action,qualification_only=True,acknowledge_document_wide_export=True)
        if action=='apply':args.update(expected_state_sha256=digest(),receipt_path=str(receipt))
        return cam.export_mill_feature_geometry(sw,'clsid','tlb',**(args|kw))
    def calls():return sum(x.call_count for x in [machine.CreateSTLOfWIPs2,machine.CreateSTLOfStock,machine.CreateSTLOfTargetInFCSSpace])
    return N(**locals())


@pytest.mark.parametrize('kind',['target','stock','wip'])
def test_one_exact_native_export_preserves_inventory_and_only_verifies_bytes(probe,kind):
    probe.state['kind']=kind;out=probe.run()
    assert out['status']=='review_required' and out['export_files_verified'] and out['readback_verified']
    assert probe.calls()==1 and out['before']==out['after'] and out['native_return'] is True
    assert len(out['files'])==1 and out['files'][0]['sha256']==cam._file_hash(probe.directory/(kind+'.stl'))
    assert not out['mesh_content_verified'] and not out['physical_depth_verified'] and not out['frame_verified']
    assert not out['model_saved'] and not out['GTP_attempted'] and not out['simulation_attempted']
    assert all(x['completed'] for x in out['phase_timings'])
    assert out['messages']['disconnected'] and json.loads(probe.receipt.read_text())==out


@pytest.mark.parametrize('action',['inspect','prepare'])
def test_read_actions_do_not_create_output_or_receipt(probe,action):
    out=probe.run(action)
    assert out['status']=='ok' and out['state_sha256']==probe.digest() and not probe.calls()
    assert not probe.directory.exists() and not probe.receipt.exists()


@pytest.mark.parametrize('case',['stale','dirty','wrong_order','wrong_generated','no_generated','wrong_link','prewrite_change','event','source','existing_output'])
def test_preflight_error_never_dispatches_export(probe,case):
    kw={}
    if case=='stale':kw['expected_state_sha256']='0'*64
    if case=='dirty':probe.current['document']['needs_save']=True
    if case=='wrong_order':kw['expected_operation_native_ids']=[115,114]
    if case=='wrong_generated':kw['expected_generated_operation_native_ids']=[115]
    if case=='no_generated':kw['expected_generated_operation_native_ids']=[]
    if case=='wrong_link':probe.current['operations'][0]['linked_feature_ids']=[112]
    if case=='prewrite_change':
        def change():
            if probe.captures.call_count==2:probe.current['selected_feature']['depth_native']=4.
        probe.state['on_capture']=change
    if case=='event':probe.state['on_capture']=lambda:probe.data.update(event_count=1)
    if case=='source':kw['expected_source_sha256']='0'*64
    if case=='existing_output':probe.directory.mkdir()
    out=probe.run(**kw);assert out['status']=='error' and not out['mutation_attempted'] and not probe.calls()


@pytest.mark.parametrize('value',[False,None,0,1])
def test_false_or_nonbool_export_retains_raw_file_and_stops_CAM(probe,value):
    probe.state['returned']=value;out=probe.run()
    assert out['status']=='uncertain' and not out['export_files_verified'] and len(out['files'])==1
    assert probe.captures.call_count==2 and probe.calls()==1
    retry=probe.run();assert retry['status']=='error' and probe.calls()==1


@pytest.mark.parametrize('case',['missing','empty','sidecar','huge','exception','event','inventory','source','dirty'])
def test_partial_export_stops_without_replay(probe,monkeypatch,case):
    if case=='missing':probe.state['write_file']=False
    if case=='huge':monkeypatch.setattr(cam,'MAX_FILE_BYTES',2)
    def change():
        if case=='empty':(probe.directory/'wip.stl').write_bytes(b'')
        if case=='sidecar':(probe.directory/'unexpected.txt').write_bytes(b'extra')
        if case=='exception':raise RuntimeError('native error after output')
        if case=='event':probe.data['event_count']=1
        if case=='inventory':probe.current['operations'][1].update(toolpath_generated=True,toolpath_record_counts=[9])
        if case=='source':probe.path.write_bytes(b'unexpected native save')
        if case=='dirty':probe.current['document']['needs_save']=True
    probe.state['on_native']=change;out=probe.run()
    assert out['status']=='uncertain' and not out['readback_verified'] and not out['export_files_verified']
    assert probe.calls()==1
    if case in ('inventory','dirty'):
        saved=json.loads(probe.receipt.read_text());assert 'after' in saved
    retry=probe.run();assert retry['status']=='error' and probe.calls()==1


@pytest.mark.parametrize('case',['event','disconnect','file','new_file','document'])
def test_cleanup_failure_keeps_bytes_but_not_success_and_no_CAM_calls(probe,case):
    def change():
        if case=='event':probe.data['event_count']=1
        if case=='disconnect':probe.data['disconnected']=False
        if case=='file':(probe.directory/'wip.stl').write_bytes(b'changed')
        if case=='new_file':(probe.directory/'extra.stl').write_bytes(b'new')
        if case=='document':probe.current['document']['title']='changed'
    probe.state['on_exit']=change;out=probe.run()
    assert out['status']=='uncertain' and not out['export_files_verified'] and probe.captures.call_count==3


def test_export_interface_QI_is_qualified_during_prepare(probe,monkeypatch):
    def deny(*_):raise RuntimeError('unsupported export interface')
    monkeypatch.setattr(cam,'_typed',deny);out=probe.run('prepare')
    assert out['status']=='error' and not probe.directory.exists() and not probe.receipt.exists() and not probe.calls()


def test_durable_intent_failure_prevents_native_export(probe,monkeypatch):
    writer=cam._write_receipt
    def write(path,report,**kw):
        if report['native_dispatch_pending']:raise OSError('intent unavailable')
        return writer(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',write);out=probe.run()
    assert not out['mutation_attempted'] and not probe.calls()


def test_target_and_stock_can_export_before_any_GTP(probe):
    probe.state['kind']='stock'
    probe.current['operations'][0].update(toolpath_generated=False,toolpath_record_counts=[])
    out=probe.run('prepare',expected_generated_operation_native_ids=[])
    assert out['status']=='ok' and out['apply_eligible'] and not probe.calls()
