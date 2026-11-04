from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib,json
import pytest
from scripts import sw_cam_turn_holder_stl as cam
from scripts import sw_cam_turn_tool as single
from scripts import sw_cam_turn_feature_attribute as attribute
from scripts import sw_cam_operation_profile as profile
from scripts import sw_cam_dispatch_guard as dispatch

def ref(si,oi,oid,fid):return dict(setup_index=si,operation_index=oi,expected_operation_type=6,operation_native_id=oid,linked_feature_ids=[fid])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

@pytest.fixture
def graph(tmp_path,monkeypatch):
    source=tmp_path/'work.sldprt';source.write_bytes(b'saved part')
    stl=tmp_path/'holder.stl';stl.write_bytes(b'candidate'+b'\0'*92)
    receipt=tmp_path/'apply.json';document=dict(path=str(source),title=source.name,type=1,needs_save=False)
    sessions=[];writes=[];hooks={};getters=[]
    class Session:
        def __init__(self,*a):self.data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],disconnect_errors=[]);sessions.append(self)
        def __enter__(self):self.data.update(subscribed=True,active=True);return self
        def __exit__(self,*a):
            self.data.update(active=False,disconnected=True)
            if hooks.get('cleanup'):hooks['cleanup']()
        def summary(self):return deepcopy(self.data)
    def holder():return NS(GetHolderType=2,GetHolderId=4,GetToolOrientationForOperation=lambda op:5,HolderShape=0,
        HolderShapeFilePath='',HolderShapeFileUnit=0,GetHolderThickness=20.,ShankLength=200.,LeadAngle=-10.,BackClearAngle=0.,
        FrontClearAngle=0.,ZInsertOffset=0.,XInsertOffset=0.,Protrusion=50.,BoringBarDiameter=20.)
    h=holder();other_h=holder()
    def tool(tid,hd):
        base=NS(native_id=tid,ToolType=15,identity=object());turn=NS(native_id=tid,ToolType=1,InsertType=1,NoseRadius=.4,Thickness=4.7625,InscribedCircle=12.7,IncludedAngle=55.,IGetTurnToolHolder=hd)
        base.turn=turn;base.GetToolInfoString=lambda:f'raw tool {tid} shape {hd.HolderShape}';return base
    target=tool(330,h);other=tool(322,other_h)
    def op(oid,tid,fid,kind):return NS(native_id=oid,OpernType=kind,IGetTool=lambda:tid,IGetAllFeatures=[NS(native_id=fid)])
    a=op(329,target,76,6);b=op(562,target,513,6);old=op(328,other,76,5)
    operations=[a,old,b];setups=[NS(IGetEnumOperations=[a,old]),NS(IGetEnumOperations=[b])];machine=NS(IGetEnumOpSetups=setups)
    station_copy=NS(**vars(target));station_copy.identity=object()
    station=NS(GetStationId='',GetTool=station_copy,OperationsUsingThisTool=[a,b]);target.GetToolStation=station
    native_doc=NS(GetCWObjectID=lambda obj:(obj.native_id,True),GetCWObjectFromID=lambda *args:(None,False))
    inventory=dict(operation_count=3,operations=[dict(setup_index=0,operation_index=0,turn_operation_type=6,toolpath_generated=False,toolpath_record_counts=[]),
        dict(setup_index=0,operation_index=1,turn_operation_type=5,toolpath_generated=True,toolpath_record_counts=[7]),
        dict(setup_index=1,operation_index=0,turn_operation_type=6,toolpath_generated=False,toolpath_record_counts=[])])
    def typed(raw,name,*args):return raw.turn if name=='ICWTurnTool' else raw
    def context(*args):return deepcopy(document),native_doc,object(),machine,object()
    def items(raw,*args,**kwargs):return list(raw)
    def read_profile(raw,typelib,read,budget,result,**kw):result.update(name='known bore profile',feature_type_raw=2,turn_feature_type_raw=2,segments=[dict(start_native=[1.,2.,3.])])
    for obj in (cam,single,profile):monkeypatch.setattr(obj,'_typed',typed)
    monkeypatch.setattr(single,'_identity',lambda obj:obj.identity)
    monkeypatch.setattr(single,'_read_profile',read_profile)
    monkeypatch.setattr(attribute,'_context',context);monkeypatch.setattr(cam,'_context',context)
    for obj in (attribute,cam):
        monkeypatch.setattr(obj,'_items',items);monkeypatch.setattr(obj,'_inventory',lambda *args:deepcopy(inventory))
    for obj in (cam,single):monkeypatch.setattr(obj,'document_snapshot',lambda *args:deepcopy(document))
    monkeypatch.setattr(dispatch,'raw_part_identity',lambda *args:deepcopy(document))
    monkeypatch.setattr(cam.policy,'_process_identity',lambda pid:dict(alive=True,process_id=pid,create_time=100.25,executable='C:/app/SLDWORKS.exe'))
    monkeypatch.setattr(cam,'CamMessageSession',Session);monkeypatch.setattr(cam,'_bootstrap',lambda *args:object())
    monkeypatch.setattr(cam,'holder_abi',lambda *args:None);monkeypatch.setattr(cam,'local_evidence_root',lambda:tmp_path)
    original_member=cam._member
    def member(obj,name,*args):
        getters.append(name)
        if hooks.get('read'):hooks['read'](name)
        return original_member(obj,name,*args)
    monkeypatch.setattr(cam,'_member',member)
    def setter(name,value):
        durable=json.loads(receipt.read_text());assert durable['mutation_attempted'] and durable['native_dispatch_pending']
        assert durable['setters'][-1]['intent_persisted'] and not durable['setters'][-1]['returned']
        assert Path(durable['marker_path']).is_file();writes.append((name,value))
        if name=='SetTurnHolderSTLFile':h.HolderShape=1;h.HolderShapeFilePath=value
        else:h.HolderShapeFileUnit=value
        document['needs_save']=True
        if hooks.get('setter'):hooks['setter'](name,value)
        return None
    target.turn.SetTurnHolderSTLFile=lambda value:setter('SetTurnHolderSTLFile',value)
    target.turn.SetTurnHolderSTLFileUnit=lambda value:setter('SetTurnHolderSTLFileUnit',value)
    sw=NS(GetProcessID=lambda:731,GetDocuments=lambda:[NS(GetPathName=lambda:str(source))])
    defaults=dict(process_id=731,expected_process_create_time=100.25,expected_document_path=str(source),expected_source_sha256=sha(source),
        setup_index=1,operation_index=0,expected_operation_type=6,expected_operation_native_id=562,expected_tool_native_id=330,
        expected_holder_id=4,expected_holder_shape_raw=0,expected_holder_orientation_raw=5,affected_operations=[ref(0,0,329,76),ref(1,0,562,513)],
        holder_stl_path=str(stl),holder_stl_sha256=sha(stl),holder_file_unit_raw=2,qualification_only=True,message_policy='vendor_default')
    def prepare(**kw):return cam.qualify_turn_holder_stl(sw,'clsid','metadata.tlb',**(defaults|kw))
    def apply(digest,**kw):return prepare(action='apply',expected_state_sha256=digest,receipt_path=str(receipt),**kw)
    return NS(**locals())

def test_actual_snapshot_traversal_prepare_then_two_hresult_only_calls(graph):
    g=graph;p=g.prepare();assert p['status']=='prepared',p
    assert not p['mutation_attempted'] and p['apply_eligible'] and len(p['captures'])==2
    assert p['before']['station_usage_operation_ids']==[329,562]
    assert all(c['diagnostic']['station_wrapper_equals_selected'] is False for c in p['captures'])
    assert not g.receipt.exists() and not g.writes
    r=g.apply(p['state_sha256']);assert r['readback_verified'],r
    assert r['status']=='review_required' and g.writes==[('SetTurnHolderSTLFile',str(g.stl)),('SetTurnHolderSTLFileUnit',2)]
    assert all(s['returned'] and s['return_type']=='NoneType' for s in r['setters'])
    assert r['before']['inventory']==r['after']['inventory'] and r['before']['tool_groups']==r['after']['tool_groups']
    old=lambda state:next(x for x in state['observed_operation_tools'] if x['operation_native_id']==328)
    assert old(r['before'])==old(r['after'])
    assert r==json.loads(g.receipt.read_text())
    assert not any(r[k] for k in ['geometry_scale_verified','coordinate_frame_verified','native_units_semantics_verified','production_qualified','model_saved','GTP_attempted','TechDB_write_attempted','insert_change_attempted'])
    assert g.sessions[-1].data['disconnected']
    assert all(not row['active'] for row in r['guards'])
    assert not {'Save','GenerateToolpath','SetTool','AddNewTurnTool3'}&set(g.getters)

@pytest.mark.parametrize('failure',['station_missing','station_extra','wrong_tool_id','linked_id','generated','source','stl','lifetime'])
def test_preflight_failures_never_mutate(graph,failure):
    g=graph
    if failure=='station_missing':g.station.OperationsUsingThisTool=[g.a]
    if failure=='station_extra':g.station.OperationsUsingThisTool=[g.a,g.b,g.old]
    if failure=='wrong_tool_id':g.station_copy.native_id=322
    if failure=='linked_id':g.b.IGetAllFeatures[0].native_id=99
    if failure=='generated':g.inventory['operations'][-1]['toolpath_generated']=True
    if failure=='source':g.source.write_bytes(b'drift')
    if failure=='stl':g.stl.write_bytes(b'drift')
    if failure=='lifetime':g.defaults['expected_process_create_time']=101.
    r=g.prepare();assert r['status']=='error' and not r['mutation_attempted'] and not g.writes

@pytest.mark.parametrize('change',['holder_scalar','old_tool','old_holder_file','old_path_count','profile'])
def test_post_write_unexpected_delta_stops_before_second_setter(graph,change):
    g=graph;p=g.prepare()
    def drift(*args):
        if change=='holder_scalar':g.h.BoringBarDiameter=21.
        if change=='old_tool':g.other.turn.NoseRadius=.7
        if change=='old_holder_file':g.other_h.HolderShapeFilePath='other.stl'
        if change=='old_path_count':g.inventory['operations'][1]['toolpath_record_counts']=[8]
        if change=='profile':g.a.IGetAllFeatures[0].native_id=88
    g.hooks['setter']=drift;r=g.apply(p['state_sha256'])
    assert r['status']=='uncertain' and len(g.writes)==1 and not r['readback_verified']
    assert g.sessions[-1].data['disconnected'] and json.loads(g.receipt.read_text())==r

@pytest.mark.parametrize('when',[1,2])
def test_native_exception_never_retries_rolls_back_or_replays(graph,when):
    g=graph;p=g.prepare()
    def fail(*args):
        if len(g.writes)==when:raise RuntimeError('native exception')
    g.hooks['setter']=fail;r=g.apply(p['state_sha256'])
    assert r['status']=='uncertain' and len(g.writes)==when and r['native_calls_returned_count']==when-1
    assert not r['readback_verified'] and not r['automatic_rollback']
    another=g.prepare(action='apply',expected_state_sha256=p['state_sha256'],receipt_path=str(g.tmp_path/'another.json'))
    assert another['status']=='error' and len(g.writes)==when and not (g.tmp_path/'another.json').exists()

@pytest.mark.parametrize('phase',['after_first','cleanup'])
def test_events_revoke_readback_and_stop_native_calls(graph,phase):
    g=graph;p=g.prepare()
    if phase=='after_first':g.hooks['setter']=lambda *a:g.sessions[-1].data.update(event_count=1)
    else:g.hooks['cleanup']=lambda:g.sessions[-1].data.update(disconnect_errors=['fixture'])
    r=g.apply(p['state_sha256']);assert r['status']=='uncertain' and not r['readback_verified']
    assert len(g.writes)==(1 if phase=='after_first' else 2)

@pytest.mark.parametrize('field,value',[('holder_file_unit_raw',True),('holder_file_unit_raw',0),('holder_file_unit_raw',2.),('expected_holder_shape_raw',1),('expected_operation_type',5),('expected_process_create_time',True),('qualification_only',1)])
def test_strict_contract_rejects_before_capture(graph,field,value):
    r=graph.prepare(**{field:value});assert r['status']=='error' and r['captures']==[] and graph.writes==[]

def test_actual_tlb_contract_without_application_activation(monkeypatch):
    generated=pytest.importorskip('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    monkeypatch.setattr(cam,'_interface_class',lambda name,path:getattr(generated,name))
    cam.holder_abi('generated-metadata-only')

def test_stale_prepared_state_blocks_before_intent(graph):
    g=graph;p=g.prepare();g.other.turn.NoseRadius=.6
    r=g.apply(p['state_sha256']);assert r['status']=='error' and not r['mutation_attempted'] and not g.writes
    assert not Path(r['marker_path']).exists()

@pytest.mark.parametrize('target',['source','stl'])
def test_file_change_after_first_setter_stops_second(graph,target):
    g=graph;p=g.prepare();g.hooks['setter']=lambda *a:getattr(g,target).write_bytes(b'changed pinned bytes')
    r=g.apply(p['state_sha256']);assert r['status']=='uncertain' and len(g.writes)==1 and not r['readback_verified']

def test_failed_intent_persistence_never_enters_native_setter(graph,monkeypatch):
    g=graph;p=g.prepare();original=cam._write_receipt
    def fail(path,report,**kw):
        if str(path)==str(g.receipt) and report.get('mutation_attempted'):raise OSError('fixture storage failure')
        return original(path,report,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    r=g.apply(p['state_sha256']);assert r['status']=='uncertain' and not g.writes and not r['readback_verified']
    assert Path(r['marker_path']).exists()

@pytest.mark.parametrize('change',['holder_scalar','old_tool','old_holder_file','old_path_count'])
def test_unexpected_delta_retains_actual_complete_capture_durably(graph,change):
    g=graph;p=g.prepare()
    def mutate(*args):
        if change=='holder_scalar':g.h.BoringBarDiameter=21.
        elif change=='old_tool':g.other.turn.NoseRadius=.7
        elif change=='old_holder_file':g.other_h.HolderShapeFilePath='other.stl'
        else:g.inventory['operations'][1]['toolpath_record_counts']=[8]
    g.hooks['setter']=mutate;r=g.apply(p['state_sha256'])
    assert r['status']=='uncertain' and len(g.writes)==1 and r['setters'][0]['returned']
    durable=json.loads(g.receipt.read_text());last=durable['captures'][-1]
    assert last['capture_complete'] and last['label']=='after_SetTurnHolderSTLFile'
    actual=last['state'];assert actual['selected_holder_file']['path_raw']==str(g.stl) and actual['selected_holder_file']['shape_raw']==1
    old=next(x for x in actual['observed_operation_tools'] if x['operation_native_id']==328)
    if change=='holder_scalar':assert actual['selected_tool']['holder']['dimensions_native']['BoringBarDiameter']==21.
    elif change=='old_tool':assert old['observed_tool']['dimensions_native']['NoseRadius']==.7
    elif change=='old_holder_file':assert old['holder_file']['path_raw']=='other.stl'
    else:assert actual['inventory']['operations'][1]['toolpath_record_counts']==[8]
    second=g.prepare(action='apply',expected_state_sha256=p['state_sha256'],receipt_path=str(g.tmp_path/'again.json'))
    assert second['status']=='error' and len(g.writes)==1


def test_partial_extended_capture_preserves_actual_changed_link(graph):
    g=graph;p=g.prepare();g.hooks['setter']=lambda *args:setattr(g.a.IGetAllFeatures[0],'native_id',999)
    r=g.apply(p['state_sha256']);last=json.loads(g.receipt.read_text())['captures'][-1]
    assert r['status']=='uncertain' and len(g.writes)==1 and not last['capture_complete']
    rows=last['diagnostic']['extended_capture']['observed_operation_tools']
    assert rows[0]['operation_native_id']==329 and rows[0]['linked_feature_ids']==[999]
    assert rows[0]['holder_file']['path_raw']==str(g.stl)

@pytest.mark.parametrize('failure',['shape','unit'])
def test_path_only_or_wrong_unit_cannot_pass_readback(graph,failure):
    g=graph;p=g.prepare()
    def mutate(name,value):
        if failure=='shape':g.h.HolderShape=0
        elif name=='SetTurnHolderSTLFileUnit':g.h.HolderShapeFileUnit=0
    g.hooks['setter']=mutate;r=g.apply(p['state_sha256'])
    assert r['status']=='uncertain' and not r['readback_verified']
    assert len(g.writes)==(1 if failure=='shape' else 2)
