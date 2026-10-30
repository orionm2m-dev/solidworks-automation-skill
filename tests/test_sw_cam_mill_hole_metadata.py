"""Synthetic hole-metadata contracts; no COM or CAD calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import ast
import json
import pytest
from scripts import sw_cam_mill_hole_metadata as m
from scripts import sw_cam_events as events


def native(oid, owner, kind, name=None, pattern=False):
    obj = N(id=oid, owner=owner, VolumeType=kind, SubType=1, Shape=2,
        Suppressed=False, FeatureName=name or 'Hole'+str(oid), Axis=(0.,0.,-1.),
        Depth=4., IsPatternFeature=lambda:pattern)
    obj.GetOwner=lambda:obj.owner
    obj.GetStartPosition=lambda:(0.,0.,10.)
    obj.GetNumOfSteps=lambda:3
    obj.GetDepth=lambda:4.
    obj.GetStartPoint=lambda:N(GetCoordinates=lambda:(0.,0.,10.))
    obj.diameter=5.3
    obj.GetTipAngle=lambda:118.
    obj.GetThread=lambda:None
    obj.GetDiameter=lambda:5.3
    obj.SinkDiameter=8.
    obj.SinkAngle=90.
    return obj


@pytest.fixture
def fixture():
    owner=N(id=69)
    compound=native(64,owner,11)
    simple=native(84,owner,1)
    sunk=native(74,owner,9)
    objects={x.id:x for x in (compound,simple,sunk)}
    doc=N(GetCWObjectFromID=lambda kind,oid:(objects[oid],True), GetCWObjectID=lambda obj:(obj.id,True))
    calls=[]
    def read(obj,name,*args):
        calls.append(name)
        v=getattr(obj,name)
        return v(*args) if callable(v) else v
    def typed(raw,name):
        calls.append('QI '+name)
        if name in ('ICWMSHoleFeat','ICWMSHoleCtrSunkFeat'):
            return N(**(vars(raw)|{'GetStartPosition':lambda:N(GetCoordinates=lambda:(0.,0.,10.))}))
        return raw
    def selected(ids=(64,84,74)):
        return [dict(feature_native_id=oid,owner_setup_native_id=69,volume_type=objects[oid].VolumeType,
            subtype_raw=1,shape_raw=2,name=objects[oid].FeatureName,axis_native=[0.,0.,-1.],
            start_native=[0.,0.,10.],depth_native=4.) for oid in ids]
    diagnostic={}
    boundary=Mock()
    progress=Mock()
    def run():return m.read_hole_metadata(doc,selected=selected(),read=read,typed=typed,
        boundary=boundary,diagnostic=diagnostic,progress=progress)
    return N(**locals())


def test_three_hole_types_without_index_or_contour_calls(fixture):
    out=fixture.run()
    assert out['metadata_complete'] and not out['full_geometry_complete']
    compound,simple,sunk=out['features']
    assert compound['parameters']['number_of_steps']==3
    assert simple['parameters']['diameter_native']['value']==5.3
    assert simple['parameters']['thread']==dict(status='observed_null',value=None,absence_semantics_verified=False)
    assert sunk['parameters']['sink_diameter_native']['value']==8.
    assert fixture.boundary.call_count==6
    assert not any(x.startswith(('Set','Add','Orient','Extend')) or 'SegChain' in x
                   or 'AtStep' in x or 'Params' in x or 'BoundParams' in x for x in fixture.calls)


def test_pattern_children_preserve_all_ids_positions_and_dimensions(fixture):
    fixture.sunk.IsPatternFeature=lambda:True
    child=native(101,fixture.sunk,9)
    child2=native(102,fixture.owner,9)
    children=[child,child2]
    fixture.sunk.IGetEnumChildFeatures=lambda:N(Count=2,Item=lambda i:children[i])
    out=fixture.run()
    group=out['features'][2]
    assert group['parameters']['status']=='pattern_parent_parameters_not_assumed'
    assert group['pattern_children']['read_complete']
    assert [x['native_id'] for x in group['pattern_children']['items']]==[101,102]
    assert all(x['parameters']['parameter_read_complete'] for x in group['pattern_children']['items'])
    assert fixture.boundary.call_count==10


@pytest.mark.parametrize('field,value',[
 ('diameter',None),('SinkAngle',None),('SinkDiameter',None)])
def test_nullable_numbers_are_observations_not_zero(fixture,field,value):
    setattr(fixture.sunk,field,value)
    out=fixture.run()['features'][2]['parameters']
    key={'diameter':'diameter_native','SinkAngle':'sink_angle_native','SinkDiameter':'sink_diameter_native'}[field]
    assert out[key]==dict(status='observed_null',value=None)


def test_nonnull_thread_values_and_nullable_strings(fixture):
    fixture.simple.GetThread=lambda:N(GetDepth=lambda:3.,GetTapForm=lambda:None,
        GetTapDesignation=lambda:'M6',GetIsMetric=lambda:True,GetTapType=lambda:2,GetThreadType=lambda:1)
    out=fixture.run()['features'][1]['parameters']['thread']
    assert out['tap_form']['value'] is None and out['tap_designation']['value']=='M6'
    assert out['GetTapType']==2 and out['is_metric'] is True


@pytest.mark.parametrize('mode',['lookup','owner','suppression','type','subtype','shape','axis','start','depth',
 'pattern_bool','step_count_bool','step_count_bound','diameter_nan','thread_boolean','thread_enum',
 'recursive_pattern','child_owner','child_duplicate','child_type','child_count','changed_child'])
def test_invalid_values_and_changed_identity_stop(fixture,mode):
    f=fixture
    if mode=='lookup':f.doc.GetCWObjectFromID=lambda *_:(f.compound,False)
    if mode=='owner':f.owner.id=70
    if mode=='suppression':f.compound.Suppressed=True
    if mode=='type':f.compound.VolumeType=2
    if mode=='subtype':f.compound.SubType=0
    if mode=='shape':f.compound.Shape=3
    if mode=='axis':f.compound.Axis=(0.,1.,0.)
    if mode=='start':f.compound.GetStartPosition=lambda:(1.,0.,10.)
    if mode=='depth':f.compound.Depth=5.
    if mode=='pattern_bool':f.compound.IsPatternFeature=lambda:1
    if mode=='step_count_bool':f.compound.GetNumOfSteps=lambda:True
    if mode=='step_count_bound':f.compound.GetNumOfSteps=lambda:65
    if mode=='diameter_nan':f.simple.diameter=float('nan')
    if mode.startswith('thread_'):
        f.simple.GetThread=lambda:N(GetDepth=lambda:3.,GetTapForm=lambda:'ISO',GetTapDesignation=lambda:'M6',
            GetIsMetric=lambda:1 if mode=='thread_boolean' else True,
            GetTapType=lambda:True if mode=='thread_enum' else 1,GetThreadType=lambda:0)
    if mode.startswith(('child_','recursive_','changed_child')):
        f.sunk.IsPatternFeature=lambda:True
        c=native(101,f.sunk,9)
        if mode=='recursive_pattern':c.IsPatternFeature=lambda:True
        if mode=='child_owner':c.owner=N(id=999)
        if mode=='child_type':c.VolumeType=1
        if mode=='changed_child':c.Depth=Mock()
        if mode=='changed_child':c.GetOwner=Mock(side_effect=[f.sunk,N(id=999)])
        f.sunk.IGetEnumChildFeatures=lambda:N(Count=65 if mode=='child_count' else 2,
            Item=lambda i:c)
    with pytest.raises((ValueError,TypeError)):f.run()
    assert not f.diagnostic['state']['metadata_complete']


def make_anchor(path,document,source):
    geometry=dict(native_id=64,volume_type=11,subtype_raw=1,shape_raw=2,suppressed=False,
        name='Compound',axis_native=[0.,0.,-1.],start_native=[0.,0.,26.],depth_native=13.7)
    state=dict(document=document,saved_file_sha256=source,operation_count=0,
        feature_setups=[dict(native_id=69,feature_count=1)],
        features=[dict(setup_native_id=69,geometry=geometry)],
        sw_reference=dict(solids=[]))
    flags=dict(subscribed=True,disconnected=True,active=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    result=dict(phase='finished',status='error',reason='DIAGNOSTIC_CAPABILITY_ERRORS_FULL_GEOMETRY_AND_REBIND_NOT_VERIFIED',
        diagnostic_enumeration_complete=True,read_only=True,process_id=731,
        messages=flags,before=deepcopy(state),after=deepcopy(state))
    for key in ('mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted',
        'model_saved','TechDB_write_attempted','post_cleanup_CAM_getters',
        'inventory_read_complete','readback_verified','saved_process_rebind_verified'):result[key]=False
    path.write_text(json.dumps(result),encoding='utf-8')
    return result


@pytest.fixture
def wrapper(tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'fixed hole')
    source=m._file_hash(part);receipt=tmp_path/'result.json';anchorpath=tmp_path/'inventory.json'
    doc=dict(path=str(part),title=part.name,type=1,needs_save=False)
    anchor=make_anchor(anchorpath,doc,source)
    kwargs=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=source,
        expected_feature_native_ids=[64],inventory_receipt_path=str(anchorpath),
        inventory_receipt_sha256=m._file_hash(anchorpath),qualification_only=True,
        acknowledge_disposable_copy=True,receipt_path=str(receipt))
    flags=dict(subscribed=False,disconnected=False,active=False,event_count=0,overflow=0,
        callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    knobs=dict(capture=None,exit=None)
    class Session:
        def __enter__(self):flags.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            flags.update(active=False,disconnected=True)
            if knobs['exit']:knobs['exit']()
        def summary(self):return deepcopy(flags)
    state=dict(features=[dict(id=64)],metadata_complete=True,full_geometry_complete=False)
    captures=[]
    def capture(*args,**kw):
        kw['check']();captures.append(True);kw['progress']()
        if knobs['capture']:knobs['capture']()
        kw['check']()
        return deepcopy(state)
    sw=N(GetProcessID=lambda:731)
    monkeypatch.setattr(m,'raw_part_identity',lambda *_:deepcopy(doc))
    bootstrap=Mock(return_value=object());monkeypatch.setattr(m,'_bootstrap',bootstrap)
    monkeypatch.setattr(m,'capture_hole_metadata',capture)
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    def run(**override):return m.inspect_mill_hole_metadata(sw,'clsid','tlb',**(kwargs|override))
    return N(**locals())


def test_wrapper_two_snapshots_no_geometry_rebind_or_production_promotion(wrapper):
    out=wrapper.run()
    assert out['status']=='review_required' and out['metadata_read_complete'] and out['readback_verified']
    assert len(wrapper.captures)==2 and out['messages']['disconnected']
    for key in ('full_inventory_verified','saved_process_rebind_verified','production_qualified',
        'may_continue','apply_eligible','full_geometry_complete','indexed_step_methods_called','model_saved'):
        assert out[key] is False
    assert json.loads(wrapper.receipt.read_text(encoding='utf-8'))==out


@pytest.mark.parametrize('mode',['pid','source','dirty','bool_id','duplicate_ids','too_many','unknown_id',
 'anchor_sha','anchor_pid','anchor_pid_bool','anchor_doc_bool','anchor_operation_bool','anchor_context','anchor_incomplete','anchor_cleanup','receipt','event',
 'capture_error','changed_state','changed_source','changed_anchor','cleanup','persist'])
def test_wrapper_rejects_invalid_anchor_or_runtime_changes(wrapper,mode,monkeypatch):
    w=wrapper;override={}
    if mode=='pid':override['process_id']=732
    if mode=='source':override['expected_source_sha256']='b'*64
    if mode=='dirty':w.doc['needs_save']=True
    if mode=='bool_id':override['expected_feature_native_ids']=[True]
    if mode=='duplicate_ids':override['expected_feature_native_ids']=[64,64]
    if mode=='too_many':override['expected_feature_native_ids']=list(range(1,7))
    if mode=='unknown_id':override['expected_feature_native_ids']=[99]
    if mode=='anchor_sha':override['inventory_receipt_sha256']='b'*64
    if mode.startswith('anchor_') and mode!='anchor_sha':
        if mode=='anchor_pid':w.anchor['process_id']=999
        if mode=='anchor_pid_bool':w.anchor['process_id']=True
        if mode=='anchor_doc_bool':
            w.anchor['before']['document']['type']=True
            w.anchor['after']['document']['type']=True
        if mode=='anchor_operation_bool':
            w.anchor['before']['operation_count']=False
            w.anchor['after']['operation_count']=False
        if mode=='anchor_context':w.anchor['after']['features'][0]['geometry']['subtype_raw']=0
        if mode=='anchor_incomplete':w.anchor['diagnostic_enumeration_complete']=False
        if mode=='anchor_cleanup':w.anchor['messages']['event_count']=1
        w.anchorpath.write_text(json.dumps(w.anchor),encoding='utf-8')
        override['inventory_receipt_sha256']=m._file_hash(w.anchorpath)
    if mode=='receipt':w.receipt.write_text('keep')
    if mode=='event':w.knobs['capture']=lambda:w.flags.update(event_count=1)
    if mode=='capture_error':
        def fail():raise ValueError('QI unsupported')
        w.knobs['capture']=fail
    if mode=='changed_state':
        w.knobs['capture']=lambda:w.state.update(sequence=len(w.captures))
    if mode=='changed_source':w.knobs['capture']=lambda:w.part.write_bytes(b'changed')
    if mode=='changed_anchor':w.knobs['capture']=lambda:w.anchorpath.write_bytes(b'changed')
    if mode=='cleanup':w.knobs['exit']=lambda:w.flags.update(disconnect_errors=['bad'])
    if mode=='persist':
        write=m._write_receipt
        def fail(path,report,**kw):
            if report.get('readback_verified'):raise OSError('cannot persist')
            return write(path,report,**kw)
        monkeypatch.setattr(m,'_write_receipt',fail)
    out=w.run(**override)
    assert out['status']=='error' and not out['metadata_read_complete'] and not out['readback_verified']
    assert not out['saved_process_rebind_verified']
    if mode=='receipt':assert w.receipt.read_text()=='keep'
    if mode not in ('event','capture_error','changed_state','changed_source','changed_anchor','cleanup','persist'):
        w.bootstrap.assert_not_called()


def actual_capture(fixture,tmp_path,monkeypatch,mode=None):
    part=tmp_path/'part.sldprt';part.write_bytes(b'fixed')
    anchor=tmp_path/'anchor.json';anchor.write_bytes(b'fixed anchor')
    baseline=dict(path=str(part),title=part.name,type=1,needs_save=False)
    dirty=N(value=False)
    sw=N(ActiveDoc=N(GetSaveFlag=lambda:dirty.value))
    app=N(IGetActiveDoc=lambda:fixture.doc)
    boundary=Mock();monkeypatch.setattr(m,'_check_capture_document',boundary)
    monkeypatch.setattr(m,'raw_part_identity',lambda *_:deepcopy(baseline))
    monkeypatch.setattr(m,'_typed',lambda raw,name,path:fixture.typed(raw,name))
    events_seen=N(value=0);check=Mock()
    if mode in ('source','anchor','dirty','event'):
        def altered():
            if mode=='source':part.write_bytes(b'changed')
            if mode=='anchor':anchor.write_bytes(b'changed')
            if mode=='dirty':dirty.value=True
            if mode=='event':events_seen.value=1
            return 3
        fixture.compound.GetNumOfSteps=altered
    if mode=='event':
        def check_event():
            if events_seen.value:raise ValueError('event observed')
        check=check_event
    if mode=='budget':monkeypatch.setattr(m,'MAX_READS',3)
    diagnostic={}
    result=m.capture_hole_metadata(sw,app,'tlb',process_id=731,expected_document_path=str(part),
        expected_source_sha256=m._file_hash(part),inventory_receipt_path=str(anchor),
        inventory_receipt_sha256=m._file_hash(anchor),baseline=baseline,selected=fixture.selected(),
        check=check,diagnostic=diagnostic,progress=Mock())
    return result,diagnostic,boundary,check


def test_batched_guards_and_counters_keep_full_metadata(fixture,tmp_path,monkeypatch):
    out,diag,boundary,check=actual_capture(fixture,tmp_path,monkeypatch)
    assert out['metadata_complete'] and diag['native_read_count']>50 and diag['native_qi_count']>10
    assert boundary.call_count==9
    assert check.call_count>2*(diag['native_read_count']+diag['native_qi_count'])


@pytest.mark.parametrize('mode',['source','anchor','dirty','event','budget'])
def test_actual_capture_detects_file_event_or_boundary_dirty_changes(fixture,tmp_path,monkeypatch,mode):
    with pytest.raises(ValueError):actual_capture(fixture,tmp_path,monkeypatch,mode)


def test_mcp_schema_strict_id_list_and_no_extra_scope(wrapper):
    from typing import Annotated,Literal
    from pydantic import BaseModel,ConfigDict,Field,model_validator,ValidationError
    class Target(BaseModel):
        expected_document_title: str | None=None
        addin_clsid: str | None=None
        response_format: str='json'
    ns=dict(SolidWorksCamTargetInput=Target,Annotated=Annotated,Literal=Literal,
            ConfigDict=ConfigDict,Field=Field,model_validator=model_validator)
    p=Path(__file__).resolve().parents[1]/'mcp-server/server.py'
    source=p.read_text(encoding='utf-8-sig')
    nodes=[node for node in ast.parse(source).body
           if isinstance(node,ast.ClassDef) and node.name=='SolidWorksCamMillHoleMetadataInput']
    assert len(nodes)==1, 'Exactly one installed request schema required'
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p),'exec'),ns)
    schema=ns['SolidWorksCamMillHoleMetadataInput']
    assert schema(**wrapper.kwargs).expected_feature_native_ids==[64]
    for ids in ([True],['64'],[64.0],(64,),[64,64]):
        with pytest.raises((ValidationError,ValueError)):schema(**(wrapper.kwargs|dict(expected_feature_native_ids=ids)))


def test_allowlist_iids_match_saved_contract():
    # Exact interfaces from the installed CAM 2026 type library, version 25.0.
    expected={'ICWMultiStepFeature': '{B18F74D1-3CCE-11D6-A9B1-00062999E55F}', 'ICWMSHoleFeat': '{B18F74D2-3CCE-11D6-A9B1-00062999E55F}', 'ICWMSHoleCtrSunkFeat': '{B18F74D3-3CCE-11D6-A9B1-00062999E55F}', 'ICWThread': '{378221F7-298B-4207-9F98-AA0828BF5929}', 'ICWPatternFeature': '{36B94FE4-41FB-42AF-A68B-345A708B8109}'}
    source=(Path(__file__).resolve().parents[1]/'scripts/sw_cam_comtypes.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    value=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and
               any(isinstance(t,ast.Name) and t.id=='_INTERFACES' for t in n.targets))
    for name in ('ICWMultiStepFeature','ICWMSHoleFeat','ICWMSHoleCtrSunkFeat','ICWThread','ICWPatternFeature'):
        assert value[name]==expected[name]


def test_full_server_import_registers_hole_tool_without_loading_automation():
    """Catch source-order/registration failures missed by isolated class tests."""
    import subprocess
    import sys
    import os
    import scripts
    server = Path(__file__).resolve().parents[1]/'mcp-server/server.py'
    program = """import asyncio, importlib.util, json, sys
import scripts
scripts.__path__[:]=json.loads(sys.argv[2])
spec=importlib.util.spec_from_file_location('hole_metadata_server_smoke',sys.argv[1])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
names=[tool.name for tool in asyncio.run(module.mcp.list_tools())]
result=dict(schema_loaded=issubclass(module.SolidWorksCamMillHoleMetadataInput,module.SolidWorksCamTargetInput),
 tool_registered='solidworks_cam_inspect_mill_hole_metadata' in names,
 automation_loaded=module._automation_loaded, selected_process_id=module._selected_process_id)
print(json.dumps(result))
"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    completed = subprocess.run([sys.executable,'-c',program,str(server),json.dumps(list(scripts.__path__))],
        cwd=str(server.parent.parent), env=env, text=True, encoding='utf-8',
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == dict(schema_loaded=True, tool_registered=True,
                         automation_loaded=False, selected_process_id=None)
