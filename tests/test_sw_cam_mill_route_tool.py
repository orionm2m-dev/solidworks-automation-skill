from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import json
import pytest
from scripts import sw_cam_mill_route_context as c
from scripts import sw_cam_mill_route_tool as w
from scripts import sw_cam_events as events


class Collection:
    def __init__(self,items):self.items=items
    @property
    def Count(self):return len(self.items)
    def Item(self,index):return self.items[index]


@pytest.fixture
def route(monkeypatch):
    tool=N(id=801,IsMillTool=True,ToolType=1,CutDiameter=2.,Protrusion=9.)
    other_tool=N(id=802,IsMillTool=True,ToolType=1,CutDiameter=4.,Protrusion=11.)
    features=[N(id=101),N(id=102),N(id=103)]
    def op(oid,feature,tool):
        return N(id=oid,OpernType=0,Suppressed=False,GetIsToolpathGenerated=False,
            IGetAllFeatures=lambda:Collection([feature]),IGetEnumToolpaths=lambda:Collection([]),
            IGetTool=lambda:tool)
    ops=[op(201,features[0],tool),op(202,features[1],other_tool),op(203,features[2],tool)]
    setups=[N(id=301,IGetEnumOperations=lambda:Collection(ops[:2])),
            N(id=302,IGetEnumOperations=lambda:Collection(ops[2:]))]
    native=dict(doc=object(),machine=N(IGetEnumOpSetups=lambda:Collection(setups)))
    state=dict(features=[dict(geometry=dict(native_id=f.id)) for f in features],
        feature_setups=[dict(native_id=401),dict(native_id=402)],operation_counts=[2,1])
    calls=[]
    def read(obj,name,*args):
        calls.append(name);value=getattr(obj,name)
        return value(*args) if callable(value) else value
    def typed(raw,name):assert raw is not None;calls.append('QI '+name);return raw
    monkeypatch.setattr(c,'_object_id',lambda doc,item,read:item.id)
    full=Mock(return_value=dict(geometry_read_complete=True,profile_complete=False,
        units_verified=False,holder_clearance_verified=False))
    monkeypatch.setattr(c,'read_full_mill_tool',full)
    selected=dict(feature_native_id=101,operation_native_id=201,mill_operation_type=0)
    diag={}
    def run(selected=selected):return c.read_route_operations(state,native,read,typed,selected=selected,diagnostic=diag)
    return N(**locals())


def test_two_setups_preserve_siblings_and_read_full_geometry_only_selected(route):
    route.run()
    assert [r['native_id'] for r in route.state['operations']]==[201,202,203]
    assert [r['setup_native_id'] for r in route.state['operations']]==[301,301,302]
    assert route.state['operation_count']==3 and len(route.state['operation_setups'])==2
    assert [r['assigned_tool']['native_id'] for r in route.state['operations']]==[801,802,801]
    assert route.full.call_count==1 and route.full.call_args.args[0] is route.tool
    assert 'full_tool' not in route.state['operations'][1]
    assert route.native['operations'][203] is route.ops[2]
    assert not any('Generate' in s and s!='GetIsToolpathGenerated' or s.startswith('Set') for s in route.calls)


@pytest.mark.parametrize('mode',['unknown_link','duplicate_link','duplicate_operation','op_feature_collision',
    'tool_operation_collision','setup_feature_collision','bad_count','setup_bound','total_bound',
    'bool_flag','negative_record','record_bound','nonmill_tool','negative_diameter','bool_diameter',
    'wrong_feature','wrong_type','suppressed_selected','missing_operation'])
def test_invalid_route_stops_without_mutation(route,mode):
    if mode=='unknown_link':route.ops[1].IGetAllFeatures=lambda:Collection([N(id=999)])
    if mode=='duplicate_link':route.ops[1].IGetAllFeatures=lambda:Collection([route.features[1]]*2)
    if mode=='duplicate_operation':route.ops[1].id=201
    if mode=='op_feature_collision':route.ops[1].id=102
    if mode=='tool_operation_collision':route.other_tool.id=203
    if mode=='setup_feature_collision':route.setups[0].id=101
    if mode=='bad_count':route.state['operation_counts']=[1,2]
    if mode=='setup_bound':route.state['operation_counts']=[0]*9
    if mode=='total_bound':route.state['operation_counts']=[32,1]
    if mode=='bool_flag':route.ops[1].Suppressed=0
    if mode=='negative_record':route.ops[1].IGetEnumToolpaths=lambda:Collection([N(RecordCount=-1)])
    if mode=='record_bound':route.ops[1].IGetEnumToolpaths=lambda:Collection([N(RecordCount=100001)])
    if mode=='nonmill_tool':route.other_tool.IsMillTool=False
    if mode=='negative_diameter':route.other_tool.CutDiameter=-2.
    if mode=='bool_diameter':route.other_tool.CutDiameter=True
    if mode=='wrong_feature':route.selected['feature_native_id']=102
    if mode=='wrong_type':route.selected['mill_operation_type']=1
    if mode=='suppressed_selected':route.ops[0].Suppressed=True
    if mode=='missing_operation':route.selected['operation_native_id']=299
    with pytest.raises(ValueError):route.run()
    assert not route.diag['operation_capture_complete']


def test_zero_operations_allowed_for_shared_context_but_not_selected_tool(route):
    route.ops.clear();route.state['operation_counts']=[0,0]
    route.run(selected=None)
    assert route.state['operations']==[] and not route.full.called


def protected_fixture():
    return dict(document=dict(path='x',needs_save=False),saved_file_sha256='a'*64,
        operation_counts=[0],operation_setups=[],operation_count=0,
        features=[dict(geometry=dict(native_id=101,island='keep'))],
        stock=dict(kind='raw'),material_raw='304L',recognition_options=dict(a=True),
        sw_reference=dict(feature_tree=['unchanged'],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[0.,0.,0.,1.])]))


def test_route_anchor_allows_only_operation_fields_and_dirty_flag():
    anchor=protected_fixture();current=deepcopy(anchor)
    current.update(operation_counts=[3],operation_count=3,operations=[dict(native_id=201)])
    current['document']['needs_save']=True
    assert c.verify_route_anchor(current,anchor)
    assert current['document']['needs_save'] is True and anchor['operation_counts']==[0]


@pytest.mark.parametrize('field',['features','material_raw','stock','recognition_options','saved_file_sha256','sw_reference'])
def test_route_anchor_rejects_any_protected_change(field):
    anchor=protected_fixture();current=deepcopy(anchor)
    if field=='features':current[field][0]['geometry']['island']='changed'
    elif field=='sw_reference':current[field]['solids'][0]['box_m'][5]=2.
    else:current[field]='changed'
    with pytest.raises(ValueError):c.verify_route_anchor(current,anchor)


@pytest.fixture
def wrapper(tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'immutable saved route')
    receipt=tmp_path/'tool.json';source=w._file_hash(part)
    doc=dict(path=str(part),title=part.name,type=1,needs_save=True)
    full=dict(geometry_read_complete=True,profile_complete=False,units_verified=False,
        holder_clearance_verified=False,physical_tool_identity_verified=False)
    state=protected_fixture()
    state.update(document=deepcopy(doc),saved_file_sha256=source,operation_counts=[1],operation_count=1,
        operations=[dict(native_id=201,full_tool=full)])
    flags=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    knobs=dict(capture=None,exit=None)
    class Session:
        def __enter__(self):flags.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            flags.update(active=False,disconnected=True)
            if knobs['exit']:knobs['exit']()
        def summary(self):return deepcopy(flags)
    class Anchor:
        state=dict(features=[dict(geometry=dict(native_id=101))])
        def check_files(self):return None
        def summary(self):return dict(kind='synthetic')
        def verify(self,value):return True
        def read_stock(self,*_):raise AssertionError('mock capture needs no stock')
    calls=[]
    def capture(*args,**kwargs):
        assert flags['active'];kwargs['check']();calls.append(True)
        kwargs['diagnostic']['partial']='entered'
        if knobs['capture']:knobs['capture']()
        kwargs['check']()
        return deepcopy(state),{}
    sw=N(GetProcessID=lambda:731)
    monkeypatch.setattr(w,'raw_part_identity',lambda *_:deepcopy(doc))
    bootstrap=Mock(return_value=object());monkeypatch.setattr(w,'_bootstrap',bootstrap)
    monkeypatch.setattr(w,'load_mill_route_anchor',lambda *a,**k:Anchor())
    monkeypatch.setattr(w,'capture_mill_route_state',capture)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    kwargs=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=source,
        inventory_receipt_path=str(tmp_path/'inventory.json'),inventory_receipt_sha256='a'*64,
        expected_feature_native_id=101,expected_operation_native_id=201,expected_mill_operation_type=0,
        qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(receipt))
    def run(**override):return w.inspect_mill_route_tool(sw,'clsid','tlb',**(kwargs|override))
    return N(**locals())


def test_wrapper_reads_twice_preserves_dirty_state_and_never_authorizes_apply(wrapper):
    result=wrapper.run()
    assert result['status']=='review_required' and result['readback_verified']
    assert len(wrapper.calls)==2 and result['before']['document']['needs_save'] is True
    assert result['tool_geometry_read_complete'] and result['tool_profile_complete'] is False
    for key in ('apply_eligible','may_continue','mutation_attempted','GOP_attempted','GTP_attempted',
                'model_saved','tool_assignment_attempted','production_qualified','post_cleanup_CAM_getters'):
        assert result[key] is False
    assert json.loads(wrapper.receipt.read_text())==result


@pytest.mark.parametrize('mode',['source','pid','feature','bool_operation','receipt','event','tool_change','cleanup'])
def test_wrapper_rejects_stale_or_incomplete_readback(wrapper,mode):
    overrides={}
    if mode=='source':overrides['expected_source_sha256']='b'*64
    if mode=='pid':overrides['process_id']=732
    if mode=='feature':overrides['expected_feature_native_id']=102
    if mode=='bool_operation':overrides['expected_operation_native_id']=True
    if mode=='receipt':wrapper.receipt.write_text('preserve')
    if mode=='event':wrapper.knobs['capture']=lambda:wrapper.flags.update(event_count=1)
    if mode=='tool_change':
        def change():
            if len(wrapper.calls)==2:wrapper.state['operations'][0]['full_tool']['profile_complete']=True
        wrapper.knobs['capture']=change
    if mode=='cleanup':wrapper.knobs['exit']=lambda:wrapper.flags['disconnect_errors'].append('bad cleanup')
    result=wrapper.run(**overrides)
    assert result['status']=='error' and not result['readback_verified']
    if mode=='receipt':assert wrapper.receipt.read_text()=='preserve'
    if mode in ('feature','bool_operation','receipt','source','pid'):assert not wrapper.bootstrap.called


def test_failed_capture_keeps_partial_evidence_without_replay(wrapper):
    def failed():raise ValueError('QI unsupported')
    wrapper.knobs['capture']=failed
    result=wrapper.run()
    assert len(wrapper.calls)==1 and not result['tool_geometry_read_complete']
    saved=json.loads(wrapper.receipt.read_text())
    assert saved['snapshot_diagnostics'][0]['partial']=='entered'
