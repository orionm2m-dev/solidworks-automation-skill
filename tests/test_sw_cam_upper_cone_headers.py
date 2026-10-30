"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import pytest
from scripts import sw_cam_upper_cone_feature as m
from scripts import sw_cam_dispatch_guard as guard_module

from cam_face_test_fixtures import state as synthetic_state
class Node:
    def __init__(self,kind,oid=0,**values):self.kind=kind;self.oid=oid;self.values=values


def environment(monkeypatch,tmp_path,count=19):
    ref=synthetic_state()
    src=tmp_path/'part.SLDPRT';src.write_bytes(b'unchanged source')
    evidence=tmp_path/'baseline.json';evidence.write_bytes(b'unchanged baseline')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    docinfo=dict(path=str(src),title=src.name,type=1,needs_save=True)
    ref['document']=docinfo;ref['saved_file_sha256']=digest(src)
    state=deepcopy(ref)
    if count==20:
        row=deepcopy(state['features'][12]);row['feature_index']=13;row['geometry']['native_id']=700
        row['geometry'].update(name='New cone',depth_native=.2,start_native=[0.,0.,26.],bounds_native=[47.1,47.1,.2])
        state['features'].insert(13,row);state['feature_setups'][0]['feature_count']=14
    objects={};calls=[];checks=dict(files=0,events=0,owned=0);fault={'event':False,'owned':False,'identity':False,'last_header':False}
    doc=Node('doc');machine=Node('machine');sw=Node('sw');model=Node('model')
    setups=[]
    for row in state['feature_setups']:
        obj=Node('setup',row['native_id'],row=row);setups.append(obj);objects[obj.oid]=obj
    for row in state['features']:
        obj=Node('feature',row['geometry']['native_id'],row=row);objects[obj.oid]=obj
    for row in state['operations']:
        obj=Node('operation',row['native_id'],row=row);objects[obj.oid]=obj
        tool=row['assigned_tool'];objects[tool['native_id']]=Node('tool',tool['native_id'],row=tool)
    opsetups=[]
    for row in state['operation_setups']:
        obj=Node('opsetup',row['native_id'],row=row);opsetups.append(obj);objects[obj.oid]=obj
    def collection(values):return Node('collection',items=values)
    def read(obj,name,*args):
        calls.append((obj.kind,name,args))
        if obj.kind=='sw':
            if name=='GetProcessID':return 17
            if name=='ActiveDoc':return model
        if obj.kind=='model' and name=='GetBodies2':return [Node('solid')]
        if obj.kind=='doc':
            if name=='GetDocType':return 1
            if name=='GetCWObjectID':return args[0].oid,True
            if name=='GetCWObjectFromID':return objects[args[1]],True
            if name=='FeatureCreationStyle':return ref['recognition_method']['value']
            if name in ('EMFHoleMaxDiameter','EMFHoleMinimumIncludedAngle'):return ref['recognition_options'][name]
            if name in ('GetEMFFeatTypeOptions','GetEMFPartPeriTypeOptions','GetEMFTypeOptions'):
                return ref['recognition_options'][name][args[0]]['enabled']
        if obj.kind=='machine':
            if name=='MachType':return 1
            if name=='IGetWorkpiece':return Node('workpiece')
            if name=='IGetEnumOpSetups':return collection(opsetups)
        if obj.kind=='collection':
            if name=='Count':return len(obj.values['items'])
            if name=='Item':return obj.values['items'][args[0]]
        if obj.kind=='setup' and name=='IGetEnumFeatures':
            return collection([objects[r['geometry']['native_id']] for r in state['features'] if r['setup_native_id']==obj.oid])
        if obj.kind=='feature':
            row=obj.values['row'];g=row['geometry']
            field={'VolumeType':'volume_type','SubType':'subtype_raw','Shape':'shape_raw','Suppressed':'suppressed',
                'FeatureName':'name','Axis':'axis_native','Depth':'depth_native','GetBoundParams':'bounds_native','GetStartPosition':'start_native'}
            if name in field:return deepcopy(g[field[name]])
            if name=='GetOwner':return objects[row['setup_native_id']]
            profile=ref['selected_profile_headers']
            if name=='IGetIslandCount':return profile['island_count']
            if name=='GetSketchCount':return profile['sketch_count']
            if name=='GetSketchNameList':return tuple(profile['sketch_names']['value'])
            if name in ('GetEndCondition1','GetEndCondition2'):
                v=profile['end_conditions'][name];return v['depth_native'],v['type_raw'],v['name'],v['is_reversed']
        if obj.kind=='opsetup' and name=='IGetEnumOperations':
            return collection([objects[r['native_id']] for r in state['operations'] if r['setup_native_id']==obj.oid])
        if obj.kind in ('operation','milloperation'):
            row=obj.values['row']
            if name=='OpernType':return row['mill_operation_type' if obj.kind=='milloperation' else 'base_operation_type']
            if name=='Suppressed':return row['suppressed']
            if name=='GetIsToolpathGenerated':return row['toolpath_generated']
            if name=='IGetAllFeatures':return collection([objects[i] for i in row['linked_feature_ids']])
            if name=='IGetEnumToolpaths':return collection([Node('toolpath',records=n) for n in row['toolpath_record_counts']])
            if name=='IGetTool':return objects[row['assigned_tool']['native_id']]
        if obj.kind=='toolpath' and name=='RecordCount':return obj.values['records']
        if obj.kind=='tool':
            row=obj.values['row'];field={'IsMillTool':'is_mill_tool','ToolType':'tool_type_raw','CutDiameter':'cut_diameter_native','Protrusion':'protrusion_native'}
            if name in field:return row[field[name]]
        pytest.fail('Unexpected read '+obj.kind+'.'+name)
    def typed(obj,name,tlb):
        if obj.kind=='operation' and name=='ICWMillOperation':return Node('milloperation',obj.oid,**obj.values)
        return obj
    monkeypatch.setattr(m,'_member',read);monkeypatch.setattr(m,'_typed',typed)
    monkeypatch.setattr(guard_module,'_member',read)
    monkeypatch.setattr(guard_module,'raw_part_identity',lambda sw:{**docinfo,'needs_save':False} if fault['identity'] else deepcopy(docinfo))
    monkeypatch.setattr(m,'_export_stock',lambda *a,**kw:(deepcopy(ref['stock']),Node('workpiece')))
    monkeypatch.setattr(m,'_features',lambda obj:(deepcopy(ref['sw_reference']['feature_tree']),None))
    monkeypatch.setattr(m,'_bodies',lambda obj:deepcopy(ref['sw_reference']['solids']))
    headerkeys=('document','saved_file_sha256','current_machine','mill_catalogue','feature_setups','operation_counts','material_raw',
        'extend_holes_to_stock','unit_record_raw','unit_record_status')
    snapshots=[]
    def snapshot(*args,check,**kwargs):
        check();result={k:deepcopy(state[k]) for k in headerkeys};snapshots.append(result)
        if len(snapshots)>1 and fault['last_header']:result['material_raw']='changed'
        return result,dict(doc=doc,machine=machine,setups=setups)
    monkeypatch.setattr(m,'_snapshot',snapshot)
    pins=[dict(path=str(evidence),sha256=digest(evidence))]
    args=dict(process_id=17,expected_document_path=str(src),expected_source_sha256=digest(src))
    def files():
        checks['files']+=1
        if digest(evidence)!=pins[0]['sha256']:raise ValueError('Evidence changed')
    def events():
        checks['events']+=1
        if fault['event']:raise ValueError('Event changed')
    def owned():
        checks['owned']+=1
        if fault['owned']:raise ValueError('PID reused')
    ctx=SimpleNamespace(args=args,sw=sw,typelib_path='offline',loaded=dict(pins=pins),files=files,events=events,
        owned=owned,identity=lambda:deepcopy(docinfo))
    ctx.guard=lambda:guard_module.ScopedCamDispatchGuard(sw,'offline',process_id=17,expected_document=docinfo,
        source_sha256=args['expected_source_sha256'],evidence_pins=pins,verify_evidence=files,verify_owned_process=owned,check_events=events)
    def batch():return m.ScopedUpperHeaderReadBatch(sw,'offline',native_context=dict(doc=doc,machine=machine,setups=setups),
        reference_state=state,process_id=17,expected_document=docinfo,source_sha256=args['expected_source_sha256'],
        evidence_pins=pins,verify_evidence=files,verify_owned_process=owned,check_events=events)
    return SimpleNamespace(ctx=ctx,ref=ref,state=state,doc=doc,machine=machine,setups=setups,objects=objects,batch=batch,
        source=src,evidence=evidence,read=read,calls=calls,checks=checks,fault=fault,snapshots=snapshots)


@pytest.mark.parametrize('count',[19,20])
def test_real_complete_headers_equal_reference(monkeypatch,tmp_path,count):
    e=environment(monkeypatch,tmp_path,count);diag={}
    state,native=m._capture_headers(e.ctx,'offline',e.ref,count,diag)
    assert state==e.state
    assert tuple(native['operations'])==(143,144,195,196,247,248)
    assert len(e.snapshots)==2 and diag['capture_complete'] is True
    b=diag['header_read_batch'];assert b['read_scope_complete'] and b['complete_boundary_checks']==2
    assert b['getter_calls']>300 and b['query_interface_calls']>40
    assert b['metadata_checks']==6*b['unique_file_count']
    assert b['metadata_checks']<2*b['unique_file_count']*(b['getter_calls']+b['query_interface_calls'])
    assert diag['observed_state']==e.state
    assert diag['header_strong_before']['complete_boundary_checks']==1
    assert diag['header_strong_after']['complete_boundary_checks']==1
    assert not b['original_route_qualification_extended'] and not b['header_native_equivalence_verified']


@pytest.mark.parametrize('name,args',[
    ('ActiveDoc',()),('GetAddInObject',('x',)),('CreateMillFeature2',()),('SaveCLFile',()),
    ('GetUnitRecordParam',()),('QueryInterface',(object(),)),('Item',(True,)),('Item',(65,)),
    ('GetCWObjectID',(object(),)),('GetCWObjectFromID',(True,244)),('GetCWObjectFromID',(1,True)),
    ('GetEMFFeatTypeOptions',(6,)),('GetEMFTypeOptions',(-1,)),('GetSketchNameList',(1,)),
])
def test_forbidden_getters_or_arguments_block_without_callback(monkeypatch,tmp_path,name,args):
    e=environment(monkeypatch,tmp_path);b=e.batch()
    with pytest.raises(ValueError):
        with b:
            calls=len(e.calls);b.read(e.doc,name,*args)
    assert len(e.calls)==calls and not b.summary()['read_scope_complete']


@pytest.mark.parametrize('interface',['ICWMachine5','ICWApp4','ICWMillWorkpiece','IUnknown','ICWFinishMillOp3'])
def test_foreign_interface_blocked(monkeypatch,tmp_path,interface):
    e=environment(monkeypatch,tmp_path);b=e.batch()
    with pytest.raises(ValueError):
        with b:b.typed(e.doc,interface)
    assert not b.summary()['read_scope_complete']


def test_foreign_owner_blocked(monkeypatch,tmp_path):
    e=environment(monkeypatch,tmp_path);b=e.batch()
    with pytest.raises(ValueError):
        with b:b.read(Node('collection',items=[]),'Count')


@pytest.mark.parametrize('fault',['source','evidence','event','owned','identity','setup'])
def test_boundary_change_invalidates_batch(monkeypatch,tmp_path,fault):
    e=environment(monkeypatch,tmp_path);b=e.batch()
    with pytest.raises(ValueError):
        with b:
            b.read(e.doc,'FeatureCreationStyle')
            if fault=='source':e.source.write_bytes(b'changed')
            elif fault=='evidence':e.evidence.write_bytes(b'changed')
            elif fault=='setup':e.setups[0].oid=999
            else:e.fault[fault]=True
    with pytest.raises(ValueError):b.require_complete()


def test_per_getter_event_stops_next_call(monkeypatch,tmp_path):
    e=environment(monkeypatch,tmp_path);b=e.batch()
    with pytest.raises(ValueError):
        with b:
            e.fault['event']=True;n=len(e.calls);b.read(e.doc,'FeatureCreationStyle')
    assert len(e.calls)==n


def test_batch_has_no_dispatch(monkeypatch,tmp_path):
    e=environment(monkeypatch,tmp_path);b=e.batch();called=[]
    with pytest.raises(ValueError):
        with b:b.dispatch_once(lambda:called.append(1),persist_pending=lambda:None)
    assert called==[]


def test_final_snapshot_mismatch_retains_full_raw(monkeypatch,tmp_path):
    e=environment(monkeypatch,tmp_path);e.fault['last_header']=True;diag={}
    with pytest.raises(ValueError,match='Native machine/header changed'):
        m._capture_headers(e.ctx,'offline',e.ref,19,diag)
    assert diag['observed_state']==e.state
    assert diag['header_final_snapshot']['material_raw']=='changed'
    assert not diag['capture_complete']
    assert diag['header_read_batch']['read_scope_complete']


def test_body_failure_retains_header_inventory(monkeypatch,tmp_path):
    e=environment(monkeypatch,tmp_path);diag={}
    monkeypatch.setattr(m,'_bodies',lambda *a:(_ for _ in ()).throw(ValueError('body failure')))
    with pytest.raises(ValueError,match='body failure'):m._capture_headers(e.ctx,'offline',e.ref,19,diag)
    assert len(diag['observed_state']['features'])==19
    assert len(diag['observed_state']['operations'])==6
    assert not diag['capture_complete']
