"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,sys,types
import pytest

from scripts import sw_cam_raw_mill_face_operation as m


@pytest.fixture
def before():
    from cam_face_test_fixtures import state
    return state(21)


def after(s,tool=None):
    out=deepcopy(s);out['document']['needs_save']=True;out['operation_count']=7
    out['operation_counts'][0]=7;out['operation_setups'][0]['operation_count']=7
    for row in out['operations'][4:]:row['operation_index']+=1
    out['operations'].insert(4,dict(setup_index=0,setup_native_id=93,operation_index=4,native_id=266,
        mill_operation_type=20,base_operation_type=0,suppressed=False,toolpath_generated=False,
        linked_feature_ids=[265],toolpath_record_counts=[],assigned_tool=deepcopy(tool)))
    return out


def test_nullable_new_tool_delta(before):
    a=after(before);assert m.verify_insert_delta(before,a,266,265)['assigned_tool'] is None
    assert before['document']['needs_save'] is False


def test_existing_default_tool_observed_only(before):
    tool=before['operations'][-1]['assigned_tool'];a=after(before,tool)
    assert m.verify_insert_delta(before,a,266,265)['assigned_tool']==tool


@pytest.mark.parametrize('change',[
 lambda a:a['operations'][0].update(suppressed=True),
 lambda a:a['operations'][5].update(toolpath_record_counts=[192]),
 lambda a:a['operations'][6].update(toolpath_generated=False),
 lambda a:a['operations'][6]['assigned_tool'].update(protrusion_native=24.0),
 lambda a:a['operations'][4].update(linked_feature_ids=[264]),
 lambda a:a['operations'][4].update(mill_operation_type=0),
 lambda a:a['operations'][4].update(toolpath_generated=True),
 lambda a:a['operations'][4].update(toolpath_record_counts=[0]),
 lambda a:a['operations'][4].update(suppressed=True),
 lambda a:a['operations'][5].update(operation_index=4),
 lambda a:a['operations'][4].update(setup_native_id=94),
 lambda a:a['document'].update(needs_save=False),
 lambda a:a.update(saved_file_sha256='0'*64),
 lambda a:a['features'][-1]['geometry'].update(depth_native=3.0),
 lambda a:a['operation_counts'].__setitem__(1,1),
 lambda a:a['operations'][4].update(assigned_tool={}),
 lambda a:a['operations'][4].update(extra=1),
])
def test_unrelated_or_invalid_changes_fail(before,change):
    a=after(before);change(a)
    with pytest.raises((ValueError,KeyError,TypeError)):m.verify_insert_delta(before,a,266,265)


def test_only_mass_roundoff_allowed(before):
    a=after(before);a['sw_reference']['solids'][0]['mass_raw'][0]*=(1+1e-14)
    diag={};m.verify_insert_delta(before,a,266,265,diagnostic=diag)
    assert diag['accepted_numeric_deltas']
    a['sw_reference']['solids'][0]['mass_raw'][0]*=1.01
    with pytest.raises(ValueError):m.verify_insert_delta(before,a,266,265)


def test_marker_independent_of_receipt_name(tmp_path):
    a=m.insert_marker(tmp_path/'part.sldprt','a'*64,265)
    assert a==m.insert_marker(tmp_path/'part.sldprt','a'*64,265)
    assert a!=m.insert_marker(tmp_path/'part.sldprt','b'*64,265)


def test_existing_output_preserved(tmp_path):
    p=tmp_path/'receipt.json';p.write_text('prior',encoding='utf-8')
    with pytest.raises(ValueError):m._fresh_output({'pins':[]},p,tmp_path/'marker.json',tmp_path/'part.sldprt')
    assert p.read_text()=='prior'


def test_existing_attempt_blocks_new_receipt(tmp_path):
    marker=tmp_path/'marker.json';marker.write_text('uncertain')
    with pytest.raises(ValueError):m._fresh_output({'pins':[]},tmp_path/'new.json',marker,tmp_path/'part.sldprt')
    assert not (tmp_path/'new.json').exists()


def native_graph(s,new_tool=None):
    class Obj:
        def __init__(self,oid,**values):self.oid=oid;self.values=values
        def __bool__(self):return True
    features={r['geometry']['native_id']:Obj(r['geometry']['native_id']) for r in s['features']}
    tools={}
    ops=[]
    for row in s['operations']:
        tr=row['assigned_tool']
        tool=None if tr is None else tools.setdefault(tr['native_id'],Obj(tr['native_id'],IsMillTool=True,ToolType=tr['tool_type_raw'],CutDiameter=tr['cut_diameter_native'],Protrusion=tr['protrusion_native']))
        paths=[Obj(800+i,RecordCount=n) for i,n in enumerate(row['toolpath_record_counts'])]
        ops.append(Obj(row['native_id'],OpernType=row['mill_operation_type'],Suppressed=row['suppressed'],
            GetIsToolpathGenerated=row['toolpath_generated'],IGetAllFeatures=[features[f] for f in row['linked_feature_ids']],
            IGetEnumToolpaths=paths,IGetTool=tool))
    setups=[Obj(93,IGetEnumOperations=ops),Obj(94,IGetEnumOperations=[]),Obj(95,IGetEnumOperations=[])]
    machine=Obj(42,IGetEnumOpSetups=setups);doc=Obj(40)
    def read(obj,name,*args):return obj.values[name]
    def typed(obj,name):
        if obj is None:raise ValueError('null QI')
        if name=='ICWOperation':
            class Base:
                oid=obj.oid
                values=dict(obj.values,OpernType=0)
            return Base()
        return obj
    return Obj,dict(doc=doc,machine=machine),read,typed


@pytest.mark.parametrize('tool_mode',['null','existing'])
def test_nullable_route_inventory(before,monkeypatch,tool_mode):
    a=after(before,None if tool_mode=='null' else before['operations'][-1]['assigned_tool'])
    Obj,native,read,typed=native_graph(a)
    monkeypatch.setattr(m,'_items',lambda values,typed,read,max_count:list(values))
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:obj.oid)
    monkeypatch.setattr(m,'_is_comtypes_pointer',lambda obj:isinstance(obj,Obj))
    monkeypatch.setattr(m,'read_generic_tool',lambda raw,doc,read,typed:(deepcopy(next(r['assigned_tool'] for r in a['operations'] if r['native_id']==raw.oid)),raw.values['IGetTool']) if raw.values['IGetTool'] is not None else (_ for _ in ()).throw(ValueError('strict null')))
    got=deepcopy(a);diag={};m.read_route_operations(got,native,read,typed,nullable_operation_id=266,diagnostic=diag)
    assert got['operations']==a['operations'] and diag['operation_capture_complete']
    assert tuple(native['operations'])==(143,144,195,196,266,247,248)


def test_old_null_tool_is_not_accepted(before,monkeypatch):
    a=after(before);a['operations'][0]['assigned_tool']=None
    Obj,native,read,typed=native_graph(a)
    monkeypatch.setattr(m,'_items',lambda values,typed,read,max_count:list(values))
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:obj.oid)
    monkeypatch.setattr(m,'_is_comtypes_pointer',lambda obj:isinstance(obj,Obj))
    monkeypatch.setattr(m,'read_generic_tool',lambda *args:(_ for _ in ()).throw(ValueError('strict null')))
    with pytest.raises(ValueError,match='strict null'):m.read_route_operations(a,native,read,typed,nullable_operation_id=266)


def test_scalar_null_imitation_rejected(before,monkeypatch):
    a=after(before);Obj,native,read,typed=native_graph(a)
    setup=native['machine'].values['IGetEnumOpSetups'][0]
    setup.values['IGetEnumOperations'][4].values['IGetTool']=0
    monkeypatch.setattr(m,'_items',lambda values,typed,read,max_count:list(values))
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:obj.oid)
    monkeypatch.setattr(m,'_is_comtypes_pointer',lambda obj:isinstance(obj,Obj))
    monkeypatch.setattr(m,'read_generic_tool',lambda raw,doc,read,typed:(deepcopy(next(r['assigned_tool'] for r in a['operations'] if r['native_id']==raw.oid)),raw.values['IGetTool']))
    with pytest.raises(ValueError,match='real COM pointer'):m.read_route_operations(deepcopy(a),native,read,typed,nullable_operation_id=266)


def request(tmp_path):
    return dict(action='insert_raw_mill_face_operation',params=dict(saved_face_receipt_path=str(tmp_path/'save.json'),
        saved_face_receipt_sha256='a'*64,process_id=23824,expected_document_path=str(tmp_path/'part.sldprt'),
        expected_source_sha256='b'*64,expected_feature_native_id=265,receipt_path=str(tmp_path/'new.json'),
        qualification_only=True,acknowledge_disposable_copy=True,message_policy='vendor_default',
        addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',module_sha256=m._self_pin()['sha256']))


def test_request_exact_scope(tmp_path):assert m.validate_request(request(tmp_path))['process_id']==23824

@pytest.mark.parametrize('key,value',[('process_id',True),('expected_feature_native_id',True),('qualification_only',False),('module_sha256','a'*64),('message_policy','answer_all')])
def test_request_rejects_broadening(tmp_path,key,value):
    r=request(tmp_path);r['params'][key]=value
    with pytest.raises(ValueError):m.validate_request(r)


def test_request_forbids_extra_mutation(tmp_path):
    r=request(tmp_path);r['params']['assign_tool']=249
    with pytest.raises(ValueError):m.validate_request(r)


@pytest.mark.parametrize('bad_after',[False,True])
def test_single_creator_no_replay_and_raw_after_persist(before,tmp_path,monkeypatch,bad_after):
    source=tmp_path/'part.sldprt';source.write_bytes(b'saved21');source_sha=m._file_hash(source)
    before['document']['path']=str(source);before['saved_file_sha256']=source_sha
    a=after(before);payload={'rough':{'stable':247},'finish':{'stable':248}}
    loaded=dict(state=before,payload=payload['rough'],finish_payload=payload['finish'],ids={},
        parent_pin={'path':str(tmp_path/'saved21.json'),'sha256':'a'*64},pins=[],lineage_pins=[],
        retired_save_marker_pin={'path':str(tmp_path/'oldmarker.json'),'sha256':'b'*64},
        cone_sketch_spec={},cone_feature_native_id=264,cone_observation={'cone':264},
        face_sketch_spec={},face_observation={'face':265})
    class Obj:
        def __init__(self,oid):self.oid=oid
        def __bool__(self):return True
    feature=Obj(265);anchor=Obj(196);created=Obj(266);calls=[]
    native={'doc':Obj(1),'operations':{196:anchor}}
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def typed(self,obj,name):return obj
        def read(self,obj,name,*args):return (feature,True)
        def dispatch_once(self,invoke,*,persist_pending):persist_pending();return invoke()
        def summary(self):return {'native_call_returned':True}
    class Context:
        def __init__(self,loaded,args,sw,typelib,app,events,state):self.loaded=loaded;self.args=args;self.expected_document=deepcopy(state['document']);self.app=None
        def files(self):pass
        def identity(self):return self.expected_document
        def guard(self):return Guard()
    class Session:
        def __init__(self,*args):self.active=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*args):self.active=False
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=not self.active,event_count=0)
    import scripts.sw_cam_events as eventmod
    monkeypatch.setattr(eventmod,'CamMessageSession',Session)
    monkeypatch.setattr(m,'FaceOperationContext',Context)
    monkeypatch.setattr(m,'load_face_operation_parent',lambda *args,**kw:deepcopy(loaded))
    monkeypatch.setattr(m.cone,'_bootstrap',lambda *args:Obj(2))
    monkeypatch.setattr(m.cone,'_read_sketch_and_cone',lambda *args,**kw:{'cone':264})
    monkeypatch.setattr(m.face,'_read_face',lambda *args,**kw:{'face':265})
    monkeypatch.setattr(m,'_capture_headers',lambda ctx,clsid,ref,count,diag,nullable_operation_id=None:(deepcopy(before if nullable_operation_id is None else a),native))
    def capture_payload(ctx,state,native,diag,nullable_operation_id=None):
        result=deepcopy(payload)
        if bad_after and nullable_operation_id is not None:result['rough']['stable']=999
        return result
    monkeypatch.setattr(m,'_capture_payload',capture_payload)
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:obj.oid)
    monkeypatch.setattr(m,'_is_comtypes_pointer',lambda obj:isinstance(obj,Obj))
    monkeypatch.setattr(m,'raw_part_identity',lambda sw:deepcopy(a['document']))
    def member(obj,name,*args):
        calls.append((obj.oid,name,args));return created
    monkeypatch.setattr(m,'_member',member)
    params=dict(saved_face_receipt_path=str(tmp_path/'saved21.json'),saved_face_receipt_sha256='a'*64,
        process_id=23824,expected_document_path=str(source),expected_source_sha256=source_sha,
        expected_feature_native_id=265,receipt_path=str(tmp_path/'result.json'),qualification_only=True,
        acknowledge_disposable_copy=True,message_policy='vendor_default')
    result=m.insert_raw_mill_face_operation(None,'clsid','type.tlb',**params)
    assert len(calls)==1 and calls[0][0:2]==(265,'InsertOperation') and calls[0][2]==(20,anchor)
    assert result['status']==('uncertain' if bad_after else 'review_required')
    assert result['after_context']==a and result['after_payload']['rough']['stable']==(999 if bad_after else 247)
    assert result['creator_call_count']==1 and result['tool_assignment_attempted'] is False and result['GTP_attempted'] is False
    disk=json.loads(Path(params['receipt_path']).read_text());assert disk['after_context']==a
    original=Path(params['receipt_path']).read_bytes();params['receipt_path']=str(tmp_path/'replay.json')
    with pytest.raises(ValueError,match='never-attempted'):m.insert_raw_mill_face_operation(None,'clsid','type.tlb',**params)
    assert len(calls)==1 and not Path(params['receipt_path']).exists()
    assert (tmp_path/'result.json').read_bytes()==original


def test_parent_retires_only_completed_save_marker(before,tmp_path,monkeypatch):
    receipt=tmp_path/'saved21.json';receipt.write_bytes(b'save21')
    marker=tmp_path/'completed_marker.json';marker.write_bytes(b'completed')
    uncertain=tmp_path/'uncertain_face_marker.json';uncertain.write_bytes(b'uncertain')
    prior=tmp_path/'past.json';prior.write_bytes(b'past')
    loaded=dict(state=before,face_feature_native_id=265,pins=[m._pin(receipt),m._pin(marker),m._pin(uncertain)],
        lineage_pins=[m._pin(prior)],save_marker_pin=m._pin(marker),parent_pin=m._pin(receipt))
    mod=types.ModuleType('scripts.sw_cam_raw_mill_face_save');mod.load_completed_face_save=lambda *args,**kw:deepcopy(loaded)
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_raw_mill_face_save',mod)
    got=m.load_face_operation_parent(str(receipt),m._file_hash(receipt),process_id=23824,
        expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,expected_feature_native_id=265)
    live={m._key(p['path']) for p in got['pins']};history={m._key(p['path']) for p in got['lineage_pins']}
    assert m._key(receipt) in live and m._key(uncertain) in live
    assert m._key(marker) not in live and m._key(marker) in history
    assert m._key(m.__file__) in live and m._key(prior) in history
