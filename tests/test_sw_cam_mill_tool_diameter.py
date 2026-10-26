from copy import deepcopy
import json, math
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_events as events
from scripts import sw_cam_mill_tool_diameter as cam

@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/'B.sldprt';path.write_bytes(b'saved diameter fixture');receipt=tmp_path/'diameter.json'
    ops=[dict(native_id=i,setup_index=0,operation_index=n,mill_operation_type=n,base_operation_type=0,
        suppressed=False,linked_feature_ids=[111],toolpath_generated=False,toolpath_record_counts=[]) for n,i in enumerate([114,115])]
    current=dict(document=dict(path=str(path),title=path.name,type=1,needs_save=False),saved_file_sha256=cam._file_hash(path),
        current_machine=dict(machine_type=1),feature_setups=[dict(native_id=64,feature_count=1)],operation_counts=[2],
        operation_setup_count=1,selected_feature=dict(native_id=111,volume_type=6,depth_native=3.),operations=ops)
    tools={116:dict(native_id=116,native_read_complete=True,is_mill_tool=True,tool_type_raw=1,cut_diameter_native=6.,
        protrusion_native=25.,units_verified=False,holder_geometry_verified=False)};refs={114:116,115:116}
    controls=dict(on_capture=None,on_set=None,on_exit=None,on_tool=None,set_calls=0)
    messages=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    class Session:
        def __enter__(self):messages.update(active=True,subscribed=True,disconnected=False);return self
        def __exit__(self,*_):
            messages.update(active=False,disconnected=True)
            if controls['on_exit']:controls['on_exit']()
        def summary(self):return deepcopy(messages)
    class Tool:
        native_id=116
        @property
        def CutDiameter(self):return tools[116]['cut_diameter_native']
        @CutDiameter.setter
        def CutDiameter(self,value):
            assert messages['active']
            durable=json.loads(receipt.read_text());assert durable['native_dispatch_pending'] and durable['phase']=='put_CutDiameter'
            controls['set_calls']+=1;tools[116]['cut_diameter_native']=value;current['document']['needs_save']=True
            if controls['on_set']:controls['on_set']()
    target=Tool();native_ops={i:N(IGetTool=Mock(return_value=target)) for i in [114,115]}
    def capture(*_,**kw):
        assert messages['active'];kw['check']()
        if controls['on_capture']:controls['on_capture']()
        kw['check']();kw['diagnostic'].update(state=deepcopy(current))
        return deepcopy(current),dict(doc=object(),operations=native_ops)
    captures=Mock(side_effect=capture)
    def read_tool(native,op_id,tlb,check,detail):
        assert messages['active'];check()
        if controls['on_tool']:controls['on_tool'](op_id)
        check();row=deepcopy(tools[refs[op_id]]);detail['selected_tool']=row;return row
    monkeypatch.setattr(cam,'capture_mill_feature_state',captures);monkeypatch.setattr(cam,'_read_assigned_tool',read_tool)
    monkeypatch.setattr(cam,'_bootstrap',lambda *_:object());monkeypatch.setattr(cam,'_typed',lambda x,*_:x)
    monkeypatch.setattr(cam,'_object_id',lambda doc,obj,read:obj.native_id)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(current['document']))
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    sw=N(GetProcessID=Mock(return_value=62876))
    def snapshot():
        result=deepcopy(current);result['assigned_tools']=[dict(operation_native_id=i,tool=deepcopy(tools[refs[i]])) for i in [114,115]]
        result['affected_operation_native_ids']=[i for i in [114,115] if refs[i]==116];return result
    def digest():return cam._digest(dict(snapshot=snapshot(),process_id=62876,expected_feature_native_id=111,
        expected_operation_native_ids=[114,115],expected_tool_native_id=116,expected_tool_type_raw=1,
        expected_cut_diameter_native=6.,new_cut_diameter_native=2.,scope='MILL_SHARED_TOOL_DIAMETER_ONLY'))
    def run(action='apply',**kw):
        args=dict(process_id=62876,expected_document_path=str(path),expected_source_sha256=cam._file_hash(path),
            expected_feature_native_id=111,expected_operation_native_ids=[114,115],expected_tool_native_id=116,
            expected_tool_type_raw=1,expected_cut_diameter_native=6.,new_cut_diameter_native=2.,
            action=action,qualification_only=True,acknowledge_disposable_copy=True)
        if action=='apply':args.update(expected_state_sha256=digest(),receipt_path=str(receipt))
        return cam.qualify_mill_tool_diameter(sw,'clsid','tlb',**(args|kw))
    return N(**locals())

def test_shared_tool_one_property_write_affects_exact_both_references(probe):
    out=probe.run();assert out['status']=='review_required' and out['diameter_readback_verified'] and out['readback_verified']
    assert probe.controls['set_calls']==1 and out['affected_operation_native_ids']==[114,115]
    assert [r['tool']['cut_diameter_native'] for r in out['after']['assigned_tools']]==[2.,2.]
    assert not out['GTP_attempted'] and not out['GOP_attempted'] and not out['model_saved'] and not out['units_verified']
    assert not out['native_hresult_observable'] and out['messages']['disconnected']
    assert json.loads(probe.receipt.read_text())==out

def test_unshared_other_tool_is_exactly_preserved(probe):
    probe.tools[117]=dict(probe.tools[116],native_id=117,cut_diameter_native=4.);probe.refs[115]=117
    out=probe.run();assert out['readback_verified'] and out['affected_operation_native_ids']==[114]
    assert out['before']['assigned_tools'][1]==out['after']['assigned_tools'][1]

@pytest.mark.parametrize('action',['inspect','prepare'])
def test_readonly_actions_no_property_write_or_receipt(probe,action):
    out=probe.run(action);assert out['status']=='ok' and out['apply_eligible'];assert probe.controls['set_calls']==0 and not probe.receipt.exists()

@pytest.mark.parametrize('case',['stale','wrong_order','duplicate_ids','wrong_tool','wrong_type','old','dirty','generated','records','wrong_link','changed_before','event','nan','bool','equal'])
def test_preflight_or_precall_failures_never_write(probe,case):
    kw={}
    if case=='stale':kw['expected_state_sha256']='0'*64
    if case=='wrong_order':kw['expected_operation_native_ids']=[115,114]
    if case=='duplicate_ids':kw['expected_operation_native_ids']=[114,114]
    if case=='wrong_tool':kw['expected_tool_native_id']=999
    if case=='wrong_type':probe.tools[116]['tool_type_raw']=15
    if case=='old':kw['expected_cut_diameter_native']=5.
    if case=='dirty':probe.current['document']['needs_save']=True
    if case=='generated':probe.current['operations'][1]['toolpath_generated']=True
    if case=='records':probe.current['operations'][1]['toolpath_record_counts']=[5]
    if case=='wrong_link':probe.current['operations'][1]['linked_feature_ids']=[112]
    if case=='changed_before':
        def change():
            if probe.captures.call_count==2:probe.tools[116]['protrusion_native']=30.
        probe.controls['on_capture']=change
    if case=='event':probe.controls['on_capture']=lambda:probe.messages.update(event_count=1)
    if case=='nan':kw['new_cut_diameter_native']=float('nan')
    if case=='bool':kw['new_cut_diameter_native']=True
    if case=='equal':kw['new_cut_diameter_native']=6.
    out=probe.run(**kw);assert not out['mutation_attempted'] and not out['readback_verified'] and probe.controls['set_calls']==0

@pytest.mark.parametrize('case',['unchanged','wrong_value','other_scalar','other_tool','feature','operation','file','exception','event'])
def test_partial_write_retained_no_replay(probe,case):
    if case=='other_tool':probe.tools[117]=dict(probe.tools[116],native_id=117);probe.refs[115]=117
    def changed():
        if case=='unchanged':probe.tools[116]['cut_diameter_native']=6.
        if case=='wrong_value':probe.tools[116]['cut_diameter_native']=2.1
        if case=='other_scalar':probe.tools[116]['protrusion_native']=30.
        if case=='other_tool':probe.tools[117]['cut_diameter_native']=2.
        if case=='feature':probe.current['selected_feature']['depth_native']=4.
        if case=='operation':probe.current['operations'][1]['toolpath_record_counts']=[9]
        if case=='file':probe.path.write_bytes(b'changed disk')
        if case=='exception':raise RuntimeError('setter raised after changing model')
        if case=='event':probe.messages['event_count']=1
    probe.controls['on_set']=changed;out=probe.run()
    assert out['status']=='uncertain' and not out['readback_verified'] and probe.controls['set_calls']==1
    if case not in ('file','exception','event'):assert 'after' in json.loads(probe.receipt.read_text())
    probe.run();assert probe.controls['set_calls']==1

@pytest.mark.parametrize('case',['event','disconnect','document'])
def test_cleanup_failure_invalidates_without_CAM_after(probe,case):
    def changed():
        if case=='event':probe.messages['event_count']=1
        if case=='disconnect':probe.messages['disconnected']=False
        if case=='document':probe.current['document']['title']='different'
    probe.controls['on_exit']=changed;out=probe.run();assert out['status']=='uncertain' and not out['readback_verified']
    assert probe.captures.call_count==3 and not out['post_cleanup_CAM_getters']

def test_intent_receipt_failure_blocks_property_write(probe,monkeypatch):
    writer=cam._write_receipt
    def write(path,report,**kw):
        if report['native_dispatch_pending']:raise OSError('cannot persist intent')
        return writer(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',write);out=probe.run();assert not out['mutation_attempted'] and probe.controls['set_calls']==0

def test_after_snapshot_persisted_before_verification(probe,monkeypatch):
    def verify(before,after,*_):
        assert json.loads(probe.receipt.read_text())['after']==after
        raise ValueError('independent rejection')
    monkeypatch.setattr(cam,'_verify_diameter_delta',verify);out=probe.run();assert not out['readback_verified'] and out['status']=='uncertain'

def test_inconsistent_shared_tool_reads_fail_before_write(probe):
    def changed(op_id):
        if op_id==115:probe.tools[116]['cut_diameter_native']=5.
    probe.controls['on_tool']=changed;out=probe.run();assert not out['mutation_attempted'] and probe.controls['set_calls']==0
