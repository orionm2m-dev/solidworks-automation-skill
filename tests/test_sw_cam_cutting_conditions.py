"""No-CAD regression for cutting-condition scope, evidence and fail-stop writes."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sw_cam_cutting_conditions as cam
from scripts import sw_cam_events as events


def ref(i, kind=2):
    return dict(setup_index=0, operation_index=i, expected_operation_type=kind)


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path=tmp_path/'working.sldprt';path.write_bytes(b'fixture')
    receipt=tmp_path/'change.json'
    values=dict(SMM=100.,MAXRPM=2500.,SpindleSpeed=700.,FPR=.1,FPM=70.,IsSMM=True,IsFPR=True,IsAssociateWithStockMaterial=False)
    initial={'document':{'path':str(path),'title':path.name,'type':1,'needs_save':False},
        'inventory':{'operations':[dict(setup_index=0,operation_index=i,turn_operation_type=2,toolpath_generated=False) for i in range(3)]},
        'unit_record_raw':'MM', 'material_raw':'304L','material_catalogue_raw':['304L','316L'],
        'operation_uses':[dict(operation=ref(i),operation_native_id=100+i,tool_native_id=200+i,tool_type_raw=15,cutting_group=0 if i<2 else 1) for i in range(3)],
        'cutting_groups':[dict(kind='turning',values_native=deepcopy(values),stock_material_raw='stainless') for _ in range(2)],
        'selected_group':0, 'identity_scope':'test'}
    state={'current':deepcopy(initial),'writes':[],'on_write':None,'on_exit':None,'on_snapshot':None}
    def put(field,value):
        durable=json.loads(receipt.read_text())
        assert durable['mutation_attempted'] and durable['phase']=='native_write' and not durable['native_call_returned']
        state['writes'].append((field,value))
        if state['on_write']:state['on_write']()
        if field=='Material':state['current']['material_raw']=value
        else:state['current']['cutting_groups'][0]['values_native'][field]=value
        state['current']['document']['needs_save']=True
    class Parameter:
        def __getattr__(self,name):
            assert name.startswith('Set')
            return lambda val:put(name[3:],val)
    class Workpiece:
        def __setattr__(self,name,value):
            assert name=='Material'
            put(name,value)
    class Session:
        def __init__(self):self.data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],disconnect_errors=[])
        def __enter__(self):self.data.update(subscribed=True,active=True);return self
        def __exit__(self,*args):
            self.data.update(disconnected=True,active=False)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(self.data)
    session=Session()
    def snapshot(*args,**kwargs):
        check=kwargs.get('check',lambda:None);check()
        if state['on_snapshot']:state['on_snapshot']()
        check()
        return deepcopy(state['current']),dict(app=object(),parameter=Parameter(),workpiece=Workpiece())
    snapshots=Mock(side_effect=snapshot)
    monkeypatch.setattr(cam,'_snapshot',snapshots)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(state['current']['document']))
    monkeypatch.setattr(events,'CamMessageSession',Mock(return_value=session))
    monkeypatch.setattr(cam,'_bootstrap',lambda *_:object())
    defaults=dict(expected_document_path=str(path),field='IsSMM',selected_operation=ref(0),qualification_only=True,message_policy='vendor_default')
    def prepare(**extra):return cam.configure_cutting_conditions(object(),'clsid','verified.tlb',**(defaults|dict(action='prepare')|extra))
    def apply(**extra):
        vals=dict(action='apply',value_native=False,expected_state_sha256=cam._digest(state['current']),allowed_affected_operations=[ref(0),ref(1),ref(2)],receipt_path=str(receipt))
        return cam.configure_cutting_conditions(object(),'clsid','verified.tlb',**(defaults|vals|extra))
    evidence=tmp_path/'units.json'
    def units(field='SMM',**extra):
        data=dict(status='qualified',interface='ICWTurnCuttingParam',field=field,unit_record_raw='MM',document_path=str(path),native_unit='m/min',method='native observed calibration',observations=[dict(native=100,interpreted=100),dict(native=120,interpreted=120)])|extra
        evidence.write_text(json.dumps(data))
        return dict(path=str(evidence),sha256=hashlib.sha256(evidence.read_bytes()).hexdigest())
    source=tmp_path/'native_catalogue.json';source.write_text('["304L","316L"]')
    mapping=tmp_path/'material_mapping.json'
    def material(target='316L',**extra):
        data=dict(status='qualified_mapping',native_material_name=target,document_path=str(path),required_alloy='1.4404/316L',material_condition='+AT',mapping_basis='reviewed native catalogue mapping',catalogue_source_path=str(source),catalogue_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),verified_native_material_names=['304L','316L'])|extra
        mapping.write_text(json.dumps(data))
        return dict(path=str(mapping),sha256=hashlib.sha256(mapping.read_bytes()).hexdigest())
    return SimpleNamespace(**locals())


@pytest.mark.parametrize('action',['inspect','prepare'])
def test_readonly_scope_and_no_events_or_write(probe,action):
    out=probe.prepare(action=action)
    assert out['status']=='ok' and out['apply_eligible']
    assert out['affected_operations']==[ref(0),ref(1),ref(2)]
    assert not out['may_continue'] and not probe.state['writes'] and not probe.receipt.exists()
    events.CamMessageSession.assert_called_once()
    assert out['messages']['disconnected']


@pytest.mark.parametrize('field,value',[('IsSMM',False),('IsFPR',False),('IsAssociateWithStockMaterial',True)])
def test_one_boolean_setter_and_cleanup_readback(probe,field,value):
    out=probe.apply(field=field,value_native=value)
    assert out['status']=='review_required' and out['readback_verified']
    assert out['native_call_returned'] and out['messages']['disconnected']
    assert probe.state['writes']==[(field,value)]
    assert not out['model_saved'] and not out['generation_attempted'] and not out['database_write_attempted']
    assert not out['physical_cutting_conditions_qualified'] and not out['native_units_independently_verified']
    assert json.loads(probe.receipt.read_text())==out


@pytest.mark.parametrize('field',['SMM','MAXRPM','SpindleSpeed','FPR','FPM'])
def test_numeric_requires_bound_per_field_evidence_and_no_conversion(probe,field):
    out=probe.apply(field=field,value_native=1.234,unit_evidence=probe.units(field))
    assert out['readback_verified'] and probe.state['writes']==[(field,1.234)]
    assert not out['native_units_independently_verified']


def test_material_full_document_scope_and_catalogue_match(probe):
    probe.state['current']['selected_group']=None
    out=probe.apply(field='Material',selected_operation=None,value_native='316L',material_evidence=probe.material(),allowed_affected_operations=[ref(0),ref(1),ref(2)])
    assert out['readback_verified'] and probe.state['writes']==[('Material','316L')]


@pytest.mark.parametrize('change',['catalogue','linked','scope'])
def test_material_refuses_unlisted_or_automatic_links_or_partial_scope(probe,change):
    probe.state['current']['selected_group']=None
    extra=dict(field='Material',selected_operation=None,value_native='316L',material_evidence=probe.material(),allowed_affected_operations=[ref(0),ref(1),ref(2)])
    if change=='catalogue':extra['value_native']='guess316'
    if change=='linked':probe.state['current']['cutting_groups'][1]['values_native']['IsAssociateWithStockMaterial']=True
    if change=='scope':extra['allowed_affected_operations']=[ref(0),ref(1)]
    if change=='empty_scope':probe.state['current']['operation_uses']=[]
    out=probe.apply(**extra)
    assert out['status']=='error' and not probe.state['writes']


@pytest.mark.parametrize('field,value',[('SMM',True),('SMM',0),('SMM',-1),('SMM',float('nan')),('SMM','1'),('IsSMM',1),('Material',''),('unexpected',1)])
def test_bad_scalar_fails_before_native_read_or_receipt(probe,field,value):
    with pytest.raises(ValueError):probe.apply(field=field,value_native=value)
    probe.snapshots.assert_not_called();assert not probe.receipt.exists()


@pytest.mark.parametrize('key',['value_native','receipt_path','expected_state_sha256','allowed_affected_operations','unit_evidence','material_evidence'])
def test_read_actions_reject_mutation_args(probe,key):
    with pytest.raises(ValueError):probe.prepare(**{key:'bad'})
    probe.snapshots.assert_not_called()


@pytest.mark.parametrize('change',['status','interface','field','unit_record_raw','document_path','native_unit','method','observations'])
def test_invalid_calibration_file_blocks_before_native_write(probe,change):
    invalid={'status':'draft','interface':'Other','field':'FPM','unit_record_raw':'IN','document_path':'C:/other.sldprt','native_unit':'','method':'','observations':[dict(native=1,interpreted=1)]}
    out=probe.apply(field='SMM',value_native=120.,unit_evidence=probe.units(**{change:invalid[change]}))
    assert out['status']=='error' and not probe.state['writes']


def test_calibration_hash_and_repeated_points_rejected(probe):
    evidence=probe.units();probe.evidence.write_text('{}')
    assert probe.apply(field='SMM',value_native=120.,unit_evidence=evidence)['status']=='error'
    assert not probe.state['writes']


@pytest.mark.parametrize('change',['dirty','path','fingerprint','shared_scope','generated','association','noop'])
def test_preflight_guards(probe,change):
    extra={}
    if change=='dirty':probe.state['current']['document']['needs_save']=True
    if change=='path':probe.state['current']['document']['path']+='other'
    if change=='fingerprint':extra['expected_state_sha256']='0'*64
    if change=='shared_scope':extra['allowed_affected_operations']=[ref(0)]
    if change=='generated':probe.state['current']['inventory']['operations'][1]['toolpath_generated']=True
    if change=='association':probe.state['current']['cutting_groups'][0]['values_native']['IsAssociateWithStockMaterial']=True
    if change=='noop':extra['value_native']=True
    out=probe.apply(**extra);assert out['status']=='error' and not probe.state['writes']


def test_even_different_wrapper_generated_operation_is_conservatively_blocked(probe):
    probe.state['current']['inventory']['operations'][2]['toolpath_generated']=True
    assert probe.apply()['status']=='error' and not probe.state['writes']


def test_receipt_replay_blocked(probe):
    probe.receipt.write_text('immutable')
    with pytest.raises(ValueError):probe.apply()
    probe.snapshots.assert_not_called()


def test_exception_after_attempt_no_retry_or_rollback(probe):
    def fail():raise RuntimeError('native exception')
    probe.state['on_write']=fail
    out=probe.apply()
    assert out['status']=='uncertain' and out['mutation_attempted'] and not out['native_call_returned']
    assert probe.snapshots.call_count==2 and len(probe.state['writes'])==1


def test_native_event_stops_readback(probe):
    probe.state['on_write']=lambda:probe.session.data.update(event_count=1)
    out=probe.apply();assert out['status']=='uncertain' and probe.snapshots.call_count==2


@pytest.mark.parametrize('when',['write'])
@pytest.mark.parametrize('change',['unrelated','unit','material','scope','derived'])
def test_unrequested_changes_are_not_hidden(probe,when,change):
    def drift():
        s=probe.state['current']
        if change=='unrelated':s['cutting_groups'][1]['values_native']['FPR']=123.
        if change=='unit':s['unit_record_raw']='IN'
        if change=='material':s['material_raw']='other'
        if change=='scope':s['operation_uses'][2]['cutting_group']=0
        if change=='derived':s['cutting_groups'][0]['values_native']['FPM']=999.
    probe.state['on_write' if when=='write' else 'on_exit']=drift
    out=probe.apply();assert out['status']=='uncertain' and not out['readback_verified']


def test_receipt_failure_prevents_write(probe,monkeypatch):
    original=cam._write_receipt
    def fail(path,data,**kw):
        if not kw.get('create'):raise OSError('storage')
        return original(path,data,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    out=probe.apply();assert out['status']=='uncertain' and not probe.state['writes']


@pytest.fixture
def graph(monkeypatch):
    document=dict(path='C:/test.sldprt',title='test.sldprt',type=1,needs_save=False)
    def parameter(identity):
        p=SimpleNamespace(identity=identity)
        for name,value in dict(SMM=100.,MAXRPM=2500.,SpindleSpeed=700.,FPR=.1,FPM=70.,IsSMM=True,IsFPR=True,IsAssociateWithStockMaterial=False).items():setattr(p,'Get'+name,Mock(return_value=value))
        p.GetCurrentTurnStockMaterial=Mock(return_value='')
        p.GetAllStockMaterialsList=Mock(return_value=['304L','316L'])
        return p
    pa=parameter('pa');pb=parameter('pb')
    tools=[SimpleNamespace(ToolType=15,native_id=201,IGetActiveTurnCuttingParam=Mock(return_value=pa)),SimpleNamespace(ToolType=15,native_id=202,IGetActiveTurnCuttingParam=Mock(return_value=pa)),SimpleNamespace(ToolType=15,native_id=203,IGetActiveTurnCuttingParam=Mock(return_value=pb))]
    ops=[SimpleNamespace(OpernType=2,native_id=101+i,IGetTool=Mock(return_value=t)) for i,t in enumerate(tools)]
    setup=SimpleNamespace(IGetEnumOperations=Mock(return_value=ops))
    wp=SimpleNamespace(Material='304L')
    machine=SimpleNamespace(MachType=3,IGetWorkpiece=Mock(return_value=wp),IGetEnumOpSetups=Mock(return_value=[setup]))
    doc=SimpleNamespace(GetUnitRecordParam=Mock(side_effect=AssertionError('Known unsafe getter must never be called')),GetCWObjectID=Mock(side_effect=lambda obj:(obj.native_id,True)))
    inv={'operations':[dict(setup_index=0,operation_index=i,toolpath_generated=False) for i in range(3)]}
    def typed(obj,interface,*_):
        if interface=='ICWTurnTool':return SimpleNamespace(**(vars(obj)|{'ToolType':getattr(obj,'turn_subtype',1)}))
        return obj
    monkeypatch.setattr(cam,'_typed',typed)
    monkeypatch.setattr(cam,'_identity',lambda obj:obj.identity)
    monkeypatch.setattr(cam,'_items',lambda obj,*_,**kw:obj)
    monkeypatch.setattr(cam,'_file_sha',lambda _: 'a'*64)
    monkeypatch.setattr(cam,'_context',lambda *_:(deepcopy(document),doc,object(),machine,object()))
    monkeypatch.setattr(cam,'_inventory',lambda *_:deepcopy(inv))
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(document))
    def snapshot():return cam._snapshot(object(),'clsid','tlb',ref(0))
    return SimpleNamespace(**locals())


def test_snapshot_detects_parameter_shared_between_different_tools(graph):
    state,handles=graph.snapshot()
    assert len(state['cutting_groups'])==2
    assert cam._affected(state,'SMM')==[ref(0),ref(1),ref(2)]
    assert len({x['tool_native_id'] for x in state['operation_uses']})==3
    assert handles['parameter'] is graph.pa
    assert state['cutting_groups'][0]['stock_material_raw']==''


def test_snapshot_alias_different_values_fails(graph):
    other=deepcopy(graph.pa);other.GetFPR=Mock(return_value=.5)
    graph.tools[1].IGetActiveTurnCuttingParam=Mock(return_value=other)
    with pytest.raises(ValueError,match='aliases'):graph.snapshot()


@pytest.mark.parametrize('change',['duplicate_op','invalid_id','wrong_machine','unknown_tool','number_type','boolean_type','catalogue_shape'])
def test_native_snapshot_contract_failures(graph,change):
    if change=='duplicate_op':graph.ops[1].native_id=graph.ops[0].native_id
    if change=='invalid_id':graph.doc.GetCWObjectID=Mock(return_value=(0,False))
    if change=='wrong_machine':graph.machine.MachType=1
    if change=='unknown_tool':graph.ops[0].IGetTool=Mock(return_value=None)
    if change=='number_type':graph.pa.GetSMM=Mock(return_value=True)
    if change=='boolean_type':graph.pa.GetIsSMM=Mock(return_value=1)
    if change=='catalogue_shape':graph.pa.GetAllStockMaterialsList=Mock(return_value=object())
    with pytest.raises(ValueError):graph.snapshot()


def test_snapshot_material_requires_all_scopes(graph):
    state,_=cam._snapshot(object(),'clsid','tlb',None)
    assert state['selected_group'] is None and cam._affected(state,'Material')==[ref(0),ref(1),ref(2)]


def test_zero_operation_material_assignment_before_AFR(probe):
    probe.state['current'].update(selected_group=None,operation_uses=[],cutting_groups=[],material_catalogue_raw=None)
    probe.state['current']['inventory']['operations']=[]
    out=probe.apply(field='Material',selected_operation=None,value_native='316L',allowed_affected_operations=[],material_evidence=probe.material())
    assert out['readback_verified'] and out['affected_operations']==[]


def test_no_CAM_getters_after_unsubscribe_and_final_file_check(probe):
    def verify_active():
        if probe.snapshots.call_count > 1:assert probe.session.data['active']
    probe.state['on_snapshot']=verify_active
    out=probe.apply()
    assert out['readback_verified'] and not out['post_cleanup_CAM_getters']
    assert probe.snapshots.call_count==4
    assert out['saved_file_sha256_before']==out['saved_file_sha256_after']


@pytest.mark.parametrize('change',['document','file','event','active'])
def test_cleanup_gate_no_CAM_readback(probe,change):
    def cleanup():
        if change=='document':probe.state['current']['document']['path']+='other'
        if change=='file':probe.path.write_bytes(b'changed')
        if change=='event':probe.session.data['event_count']=1
        if change=='active':probe.session.data['active']=True
    probe.state['on_exit']=cleanup
    out=probe.apply()
    assert out['status']=='uncertain' and not out['readback_verified']
    assert probe.snapshots.call_count==4


@pytest.mark.parametrize('key,value',[('status','draft'),('native_material_name','other'),('document_path','C:/other.sldprt'),('required_alloy',''),('material_condition',''),('mapping_basis',''),('catalogue_source_sha256','0'*64),('verified_native_material_names',['other'])])
def test_material_mapping_evidence_fail_closed(probe,key,value):
    probe.state['current']['selected_group']=None
    out=probe.apply(field='Material',selected_operation=None,value_native='316L',material_evidence=probe.material(**{key:value}))
    assert out['status']=='error' and not probe.state['writes']


@pytest.mark.parametrize('event_at',['Count','Item'])
def test_nested_collection_event_stops_before_next_native_read(graph,monkeypatch,event_at):
    from scripts import sw_cam_turn_feature_attribute as guarded
    calls=[]; triggered=[False]
    class Collection:
        def Count(self):
            calls.append('Count')
            if event_at=='Count':triggered[0]=True
            return 3
        def Item(self,index):
            calls.append('Item')
            if event_at=='Item':triggered[0]=True
            return graph.ops[index]
    monkeypatch.setattr(guarded,'_typed',lambda obj,*_:obj)
    monkeypatch.setattr(cam,'_items',guarded._items)
    graph.machine.IGetEnumOpSetups=Mock(return_value=Collection())
    def check():
        if triggered[0]:raise ValueError('native event')
    with pytest.raises(ValueError,match='native event'):
        cam._snapshot(object(),'clsid','tlb',ref(0),check=check)
    assert calls==(['Count'] if event_at=='Count' else ['Count','Item'])
    graph.doc.GetCWObjectID.assert_not_called()


def test_saved_file_hash_bound_and_change_detected(graph,monkeypatch):
    state,_=graph.snapshot()
    assert state['saved_file_sha256']=='a'*64
    monkeypatch.setattr(cam,'_file_sha',Mock(side_effect=['a'*64,'b'*64]))
    with pytest.raises(ValueError,match='Saved file changed'):graph.snapshot()


@pytest.mark.parametrize('action',['inspect','prepare'])
def test_initial_read_subscribed_message_stops(probe,action):
    def callback():
        assert probe.session.data['active']
        probe.session.data['event_count']=1
    probe.state['on_snapshot']=callback
    out=probe.prepare(action=action)
    assert out['status']=='error' and not probe.state['writes'] and probe.snapshots.call_count==1
    assert out['messages']['disconnected']

@pytest.mark.parametrize('action',['inspect','prepare'])
def test_readonly_cleanup_detects_disk_change(probe,action):
    probe.state['on_exit']=lambda:probe.path.write_bytes(b'changed at disconnect')
    out=probe.prepare(action=action)
    assert out['status']=='error' and not probe.state['writes'] and probe.snapshots.call_count==1


@pytest.mark.parametrize('material_only',[True,False])
def test_native_snapshot_never_calls_unsafe_unit_getter(graph,material_only):
    if material_only:
        graph.setup.IGetEnumOperations.return_value=[]
        graph.inv['operations']=[]
    state,_=cam._snapshot(object(),'clsid','tlb',None if material_only else ref(0))
    assert state['unit_record_raw'] is None
    assert state['unit_record_status']=='unavailable_native_getter_disabled_after_RPC_failure'
    graph.doc.GetUnitRecordParam.assert_not_called()


def test_unknown_native_unit_does_not_authorize_numeric_write(probe):
    probe.state['current']['unit_record_raw']=None
    result=probe.apply(field='SMM',value_native=120.,unit_evidence=probe.units())
    assert result['status']=='error' and not probe.state['writes']


@pytest.mark.parametrize("subtype",[0,2,3,99,True,"1"])
def test_unsupported_subtype_refuses_before_turn_cutting_accessor(graph,subtype):
    graph.tools[0].turn_subtype=subtype
    graph.tools[0].IGetActiveTurnCuttingParam.side_effect=AssertionError("Do not guess drill cutting interface")
    diagnostic={}
    with pytest.raises(cam.CamToolStateError) as failure:
        cam._snapshot(object(),'clsid','tlb',None,diagnostics=diagnostic)
    assert failure.value.reason=='CAM_CUTTING_TOOL_SUBTYPE_UNAVAILABLE'
    assert diagnostic['unavailable_tool_parameters']['status']=='unavailable'
    assert diagnostic['unavailable_tool_parameters']['operation_native_id']==101
    for tool in graph.tools:tool.IGetActiveTurnCuttingParam.assert_not_called()
    graph.ops[1].IGetTool.assert_not_called()
