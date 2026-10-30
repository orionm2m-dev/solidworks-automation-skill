"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast,inspect,json
import pytest
from scripts import sw_cam_raw_mill_face_feature as m

def circle(z):return dict(curve_type=2,centre_native=[0.,0.,z],radius_native=32.5,normal_native=[0.,0.,1.],direction_raw=1)
def geometry():return dict(native_id=701,volume_type=5,suppressed=False,depth_native=2.,axis_native=[0.,0.,-1.],start_native=[0.,0.,28.],
    bounds_native=[65.,65.,2.],taper_enabled=False,island_count=0,top_curves_native=[circle(28.)],bottom_curves_native=[circle(26.)])
def sketch_circle():return dict(center_model_m=[0.,0.,.028],radius_m=.0325,normal_model=[0.,0.,1.])
def states():
    rows=[]
    for si,(sid,count) in enumerate([(69,14),(71,5),(73,1)]):
        for fi in range(count):rows.append(dict(setup_index=si,feature_index=fi,setup_native_id=sid,geometry=dict(native_id=100+len(rows),value='kept')))
    before=dict(features=rows,feature_setups=[dict(native_id=s,feature_count=c,axis_native=[0.,0.,-1.]) for s,c in [(69,14),(71,5),(73,1)]],
        document=dict(needs_save=True),operations=[dict(native_id=i) for i in range(6)],
        stock=dict(type_raw=4,length_units_raw=0,bounds_native=[-.0325,-.0325,-.032,.0325,.0325,.028]),sw_reference={'kept':True,'solids':[dict(mass_raw=[1.0]*12)]})
    after=deepcopy(before);after['features'].insert(14,dict(setup_index=0,feature_index=14,setup_native_id=69,geometry=dict(native_id=701,value='new')))
    after['feature_setups'][0]['feature_count']+=1
    return before,after

@pytest.mark.parametrize('z',[26.,28.])
def test_configuration_accepts_raw_coplanar_without_fabricating_z(z):
    g=geometry();g['bottom_curves_native']=[circle(z)]
    r=m.verify_face_geometry(g,sketch_circle(),701)
    assert r['native_configuration_verified'] and r['raw_profiles_coplanar']==(z==28.)
    assert r['raw_bottom_center_native']==[0,0,z]
    assert not r['coordinate_frame_qualified'] and not r['geometric_depth_verified'] and not r['physical_stock_removal_proved']
    assert not r['production_route_changed'] and not r['lower_world_boundary_synthesized']

@pytest.mark.parametrize('key,value',[('volume_type',2),('volume_type',True),('native_id',True),('suppressed',1),('depth_native',0.2),
    ('depth_native',float('nan')),('start_native',[0,0,26]),('axis_native',[0,0,1]),('bounds_native',[65,65,1]),('taper_enabled',0),('taper_enabled',True),('island_count',True),('island_count',1)])
def test_bad_header_rejected(key,value):
    g=geometry();g[key]=value
    with pytest.raises(ValueError):m.verify_face_geometry(g,sketch_circle(),701)

@pytest.mark.parametrize('change',['radius','center','normal','missing','extra','measured_scale'])
def test_bad_contour_or_sketch_rejected(change):
    g=geometry();s=sketch_circle()
    if change=='radius':g['bottom_curves_native'][0]['radius_native']=32.4
    elif change=='center':g['bottom_curves_native'][0]['centre_native']=[0,0,27]
    elif change=='normal':g['top_curves_native'][0]['normal_native']=[0,1,0]
    elif change=='missing':g['bottom_curves_native']=[]
    elif change=='extra':g['bottom_curves_native'].append(circle(26))
    else:s['radius_m']=32.5
    with pytest.raises(ValueError):m.verify_face_geometry(g,s,701)

@pytest.mark.parametrize('change',['scope','z','radius','name','extra'])
def test_only_exact_raw_target(change):
    spec=deepcopy(m.FACE_SPEC);scope=m.ROUTE_SCOPE
    if change=='scope':scope='PRODUCTION'
    elif change=='z':spec['plane_offset_mm']=26
    elif change=='radius':spec['profile']['radius_mm']=32.4
    elif change=='name':spec['sketch_name']='Other'
    else:spec['feature_type']=6
    with pytest.raises(ValueError):m.validate_face_spec(spec,scope)

def test_exact20_21_delta():
    a,b=states();assert m.verify_face_delta(a,b,701)['geometry']['native_id']==701

@pytest.mark.parametrize('change',['old_feature','operations','stock','second','duplicate','owner','dirty','order','body'])
def test_protected_state_not_changed(change):
    a,b=states()
    if change=='old_feature':b['features'][0]['geometry']['value']='changed'
    elif change=='operations':b['operations'][0]['native_id']=999
    elif change=='stock':b['stock']['bounds_native'][-1]=.027
    elif change=='second':b['features'].append(dict(geometry=dict(native_id=702)))
    elif change=='duplicate':b['features'][14]['geometry']['native_id']=100
    elif change=='owner':b['features'][14]['setup_native_id']=71
    elif change=='dirty':b['document']['needs_save']=False
    elif change=='order':b['features'][0],b['features'][1]=b['features'][1],b['features'][0]
    else:b['sw_reference']['kept']=False
    with pytest.raises(ValueError):m.verify_face_delta(a,b,701)

def test_parent_retires_only_completed_sketch_and_keeps64_limit(tmp_path,monkeypatch):
    pins=[]
    for i in range(63):
        p=tmp_path/('pending100.json' if i==1 else str(i)+'.json');p.write_text('{}');pins.append(m._pin(p))
    hist=[]
    for i in range(2):
        p=tmp_path/('old'+str(i)+'.json');p.write_text('{}');hist.append(m._pin(p))
    state,_=states();state['document']['needs_save']=False
    loaded=dict(state=state,pins=pins,lineage_pins=hist,sketch_receipt_pin=pins[0])
    monkeypatch.setattr(m.saved,'load_completed_upper_cone_save',lambda *a,**kw:deepcopy(loaded))
    out=m.load_face_parent('unused','1'*64,process_id=12,expected_document_path='unused',expected_source_sha256='2'*64,expected_feature_native_id=700)
    assert len(out['pins'])==63 and len(out['lineage_pins'])==3
    assert pins[0] not in out['pins'] and pins[0] in out['lineage_pins'] and pins[1] in out['pins']
    new=tmp_path/'new_sketch.json';new.write_text('{}')
    out['pins']=m.canonical_evidence_pins(out['pins'],[m._pin(new)]);assert len(out['pins'])==64
    extra=tmp_path/'extra.json';extra.write_text('{}')
    with pytest.raises(ValueError):m.canonical_evidence_pins(out['pins'],[m._pin(extra)])

@pytest.fixture
def native_case(tmp_path,monkeypatch):
    import scripts.sw_cam_events as events
    before,after=states();source=tmp_path/'part.sldprt';source.write_bytes(b'saved20')
    doc=dict(path=str(source),title=source.name,type=1,needs_save=True)
    before['document']=deepcopy(doc);after['document']=deepcopy(doc)
    before['saved_file_sha256']=after['saved_file_sha256']=m._file_hash(source)
    base=tmp_path/'save20.json';base.write_text('{}');sketch=tmp_path/'sketch.json';sketch.write_text('{}')
    loaded=dict(state=deepcopy(before),payload={'r':1},finish_payload={'f':2},pins=[m._pin(base)],parent_pin=m._pin(base),
        ids={k:i+1 for i,k in enumerate(m.cone.IDS)},ownership={},lineage_pins=[],sketch_spec={'old':True},cone_observation={'old':True})
    setup=object();docobj=object();newobj=object();calls=[];flags={};native=dict(setups=[setup,object(),object()],doc=docobj)
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def typed(self,obj,name):return obj
        def read(self,*a):return None
        def dispatch_once(self,fn,*,persist_pending):
            persist_pending();flags['claimed']=m.face_marker(source,m._file_hash(source)).exists();return fn()
        def summary(self):return dict(claimed=True,native_call_attempted=True,native_call_returned=True,invalid=False)
    class Context:
        def __init__(self,*a):self.app=None
        def files(self):pass
        def identity(self):return doc
        def guard(self):return Guard()
    class Session:
        def __init__(self,*a):self.active=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=not self.active,event_count=0)
    monkeypatch.setattr(m,'load_face_parent',lambda *a,**kw:deepcopy(loaded))
    expected=deepcopy(before)
    monkeypatch.setattr(m.cone,'load_sketch_prerequisite',lambda *a:(dict(),m._pin(sketch),deepcopy(expected)))
    monkeypatch.setattr(m.saved,'UpperConeSaveContext',Context);monkeypatch.setattr(m.cone,'_bootstrap',lambda *a:object());monkeypatch.setattr(events,'CamMessageSession',Session)
    monkeypatch.setattr(m,'_capture_headers',lambda ctx,clsid,ref,count,diag:(deepcopy(before if count==20 else after),native))
    monkeypatch.setattr(m.cone,'_capture_payload',lambda *a:dict(rough={'r':1},finish={'f':2}))
    monkeypatch.setattr(m.cone,'_read_sketch_and_cone',lambda *a:{'old':True})
    def read_face(*a,diagnostic=None,persist=lambda:None):
        diagnostic.update(sketch={},sketch_circle_m=sketch_circle(),feature=geometry());persist();return diagnostic
    monkeypatch.setattr(m,'_read_face',read_face)
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:69 if obj is setup else 701)
    monkeypatch.setattr(m,'_is_comtypes_pointer',lambda obj:obj is newobj)
    def native_call(obj,name,*args):calls.append((name,args));assert flags['claimed'];return newobj
    monkeypatch.setattr(m,'_member',native_call)
    kwargs=dict(saved_cone_receipt_path=str(base),saved_cone_receipt_sha256=m._file_hash(base),sketch_receipt_path=str(sketch),sketch_receipt_sha256=m._file_hash(sketch),
        process_id=123,expected_document_path=str(source),expected_source_sha256=m._file_hash(source),expected_feature_native_id=700,
        sketch_spec=deepcopy(m.FACE_SPEC),route_scope=m.ROUTE_SCOPE,receipt_path=str(tmp_path/'result.json'),qualification_only=True,acknowledge_disposable_copy=True)
    return SimpleNamespace(kwargs=kwargs,calls=calls,flags=flags,after=after,before=before,newobj=newobj)

def test_one_native_call_exact_args_and_no_replay(native_case):
    n=native_case;r=m.create_raw_mill_face(None,None,None,**n.kwargs)
    assert r['readback_verified'] and r['creator_call_count']==1 and r['status']=='review_required'
    assert n.calls==[('CreateMillFeature2',(6,'FaceStockCircle',False,2.,False,False,False,False,0.,-1,False,0,0))]
    assert all(r[k] is False for k in ('GOP_attempted','GTP_attempted','save_attempted','model_saved','production_route_changed','CAD_solid_edit_attempted'))
    with pytest.raises(ValueError):m.create_raw_mill_face(None,None,None,**dict(n.kwargs,receipt_path=str(Path(n.kwargs['receipt_path']).with_name('retry.json'))))
    assert len(n.calls)==1

@pytest.mark.parametrize('change',['before','old_operation','scalar_return','geometry','old_cone'])
def test_pre_or_post_failure_never_replays(native_case,monkeypatch,change):
    n=native_case
    if change=='before':
        n.before['operations'][0]['native_id']=999
    elif change=='old_operation':n.after['operations'][0]['native_id']=999
    elif change=='scalar_return':monkeypatch.setattr(m,'_is_comtypes_pointer',lambda *a:False)
    elif change=='old_cone':monkeypatch.setattr(m.cone,'_read_sketch_and_cone',lambda *a:{'old':False})
    else:
        def bad(*a,diagnostic=None,persist=lambda:None):
            g=geometry();g['depth_native']=1.;diagnostic.update(sketch={},sketch_circle_m=sketch_circle(),feature=g);persist();return diagnostic
        monkeypatch.setattr(m,'_read_face',bad)
    r=m.create_raw_mill_face(None,None,None,**n.kwargs)
    pre=change in ('before','old_cone')
    assert r['status']==('error' if pre else 'uncertain') and not r['readback_verified'] and len(n.calls)==(0 if pre else 1)
    assert not r['GOP_attempted'] and not r['GTP_attempted'] and not r['save_attempted']
    disk=json.loads(Path(n.kwargs['receipt_path']).read_text())
    if change=='old_cone':assert disk['before_cone_observation']=={'old':False}
    if change=='geometry':assert disk['face_observation']['feature']['depth_native']==1.

def test_failed_payload_persisted_before_raise(native_case,monkeypatch):
    n=native_case
    def fail(ctx,state,native,diag):
        v=dict(rough={'r':1},finish={'f':3 if diag['phase']=='after' else 2});diag['observed_payload']=v
        if diag['phase']=='after':raise ValueError('Protected payload changed')
        return v
    monkeypatch.setattr(m.cone,'_capture_payload',fail)
    r=m.create_raw_mill_face(None,None,None,**n.kwargs);disk=json.loads(Path(n.kwargs['receipt_path']).read_text())
    assert r['status']=='uncertain' and len(n.calls)==1
    assert disk['snapshot_diagnostics'][-1]['observed_payload']['finish']['f']==3
    assert disk['snapshot_diagnostics'][-1]['observed_state']==n.after

def request(tmp_path):
    p={k:1 for k in m.PARAMS}
    p.update({k:str(tmp_path/(k+'.json')) for k in p if k.endswith('path')})
    p.update({k:'1'*64 for k in p if k.endswith('sha256')})
    p.update(module_sha256=m._self_pin()['sha256'],sketch_spec=deepcopy(m.FACE_SPEC),route_scope=m.ROUTE_SCOPE,qualification_only=True,
        acknowledge_disposable_copy=True,message_policy='vendor_default',addin_clsid='{FE488661-0BD8-11D6-2012-2018CE99E55F}')
    return dict(action='create_raw_mill_face',params=p)

def test_actual_schema_binds_native_signature(tmp_path):
    p=m.validate_request(request(tmp_path));p.pop('module_sha256');p.pop('addin_clsid')
    inspect.signature(m.create_raw_mill_face).bind(None,None,None,**p)

@pytest.mark.parametrize('change',['extra','clSID','module','relative','production','boolPID','falseAck'])
def test_schema_rejects_before_connection(tmp_path,change):
    r=request(tmp_path);p=r['params']
    if change=='extra':p['extra']=1
    elif change=='clSID':p['addin_clsid']='{'+'-'*36+'}'
    elif change=='module':p['module_sha256']='2'*64
    elif change=='relative':p['receipt_path']='relative.json'
    elif change=='production':p['route_scope']='PRODUCTION'
    elif change=='boolPID':p['process_id']=True
    else:p['acknowledge_disposable_copy']=False
    with pytest.raises(ValueError):m.validate_request(r)

def test_dispatch_actual_request_no_missing_or_extra_params(tmp_path,monkeypatch):
    import scripts.sw_operation_guard as locking
    import scripts.sw_connect as connect
    import scripts.sw_cam_installation as installation
    import scripts.sw_cam as cam
    from contextlib import nullcontext
    seen=[]
    monkeypatch.setattr(m,'load_face_parent',lambda *a,**kw:seen.append('parent'))
    monkeypatch.setattr(locking,'solidworks_operation_lock',lambda **kw:nullcontext())
    monkeypatch.setattr(installation,'discover_cam_installations',lambda:{'errors':[]})
    monkeypatch.setattr(cam,'select_registration',lambda inv,clsid:dict(clsid=clsid,addin_path=str(tmp_path/'module.dll')))
    monkeypatch.setattr(connect,'connect_solidworks',lambda **kw:(object(),None))
    monkeypatch.setattr(m,'_member',lambda obj,name:1)
    signature=inspect.signature(m.create_raw_mill_face)
    def invoke(*a,**kw):signature.bind(*a,**kw);seen.append('invoke');return dict(readback_verified=False)
    monkeypatch.setattr(m,'create_raw_mill_face',invoke)
    m.dispatch_request(request(tmp_path));assert seen==['parent','invoke']

def test_one_creator_static_no_generation_save_or_setter():
    t=ast.parse(Path(m.__file__).read_text(encoding='utf-8'));f=next(x for x in t.body if isinstance(x,ast.FunctionDef) and x.name=='create_raw_mill_face')
    direct=[n for n in ast.walk(f) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_member']
    assert len(direct)==1 and direct[0].args[1].value=='CreateMillFeature2' and len(direct[0].args)==15


def test_face_delta_uses_only_shared_mass_roundoff_rule():
    a,b=states();raw=deepcopy(b);b['sw_reference']['solids'][0]['mass_raw'][3]+=1e-13;before=deepcopy(b);diag={}
    m.verify_face_delta(a,b,701,diagnostic=diag)
    assert b==before and len(diag['accepted_numeric_deltas'])==1
    b['stock']['bounds_native'][-1]+=1e-15
    with pytest.raises(ValueError):m.verify_face_delta(a,b,701)

def test_actual_slab_read_chain_keeps_raw_contours(monkeypatch):
    feature={'kind':'feature'};mill=feature;base=feature;owner=object();doc={'kind':'doc'}
    model={'kind':'model'};sketch={'kind':'sketch'};sw={'kind':'sw'};calls=[];saved=[]
    raw=dict(entities=[dict(type='circle',center_model_m=[0.,0.,.028],radius_m=.0325)],
        model_to_sketch_transform=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.])
    geom=geometry()
    def read(obj,name,*args):
        calls.append(name);kind=obj['kind']
        if name=='GetCWObjectID':return (69 if args[0] is owner else 701),True
        if name=='GetCWObjectFromID':return feature,True
        if name=='ActiveDoc':return model
        if name=='FeatureByName':assert args==('FaceStockCircle',);return feature
        if name=='GetSpecificFeature2':return sketch
        if name=='GetOwner':return owner
        fields={'VolumeType':'volume_type','Suppressed':'suppressed','Depth':'depth_native','Axis':'axis_native',
            'GetBoundParams':'bounds_native','GetStartPosition':'start_native','Taper':'taper_enabled','IGetIslandCount':'island_count'}
        if name in fields:return geom[fields[name]]
        if name in ('SubType','Shape'):return 0
        if name=='FeatureName':return 'FaceStockCircle'
        if name in ('IGetTopSegChain','IGetBottomSegChain'):return dict(kind='chain',z=28. if name=='IGetTopSegChain' else 26.)
        if name in ('IGetNumChains','GetNumOfCurves'):return 1
        if name=='GetCurveAtIndex':assert args[0]._obj.value==0;return dict(kind='curve',z=obj['z'])
        if name=='GetTypeOfCurve':return 2
        if name=='CenterPoint':return dict(kind='position',xyz=[0.,0.,obj['z']])
        if name=='GetRadius':return 32.5
        if name=='IGetNormal':return dict(kind='normal',xyz=[0.,0.,1.])
        if name=='GetCoordinates':return obj['xyz']
        if name=='GetDirection':return 1
        pytest.fail('Unexpected call '+kind+'.'+name)
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,*a):return read(*a)
        def typed(self,obj,name):return obj
        def _fast(self):pass
    ctx=SimpleNamespace(sw=sw,typelib_path='offline',guard=lambda:Guard())
    monkeypatch.setattr(m,'_read_sketch',lambda *a:deepcopy(raw))
    diag={};result=m._read_face(ctx,{'doc':doc},m.FACE_SPEC,701,diagnostic=diag,persist=lambda:saved.append(deepcopy(diag)))
    accepted=m.verify_face_geometry(result['feature'],result['sketch_circle_m'],701)
    assert accepted['native_configuration_verified'] and result['feature']['island_count']==0
    assert calls.count('GetCurveAtIndex')==2 and 'IGetTopSegChain' in calls and 'IGetBottomSegChain' in calls
    assert any('feature' in v and 'bottom_curves_native' not in v['feature'] for v in saved)
    assert saved[-1]==result


def test_parent_read_pin_alias_matches_canonical_live_pin(tmp_path,monkeypatch):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    sub=tmp_path/'sub';sub.mkdir();path=tmp_path/'old_sketch.json';path.write_text('{}')
    _,old=read_pin(str(sub/'..'/'old_sketch.json'),m._file_hash(path))
    live=m.canonical_evidence_pins([old]);assert live[0]['path']!=old['path']
    state,_=states();state['document']['needs_save']=False
    loaded=dict(state=state,pins=live,lineage_pins=[],sketch_receipt_pin=old)
    monkeypatch.setattr(m.saved,'load_completed_upper_cone_save',lambda *a,**kw:deepcopy(loaded))
    out=m.load_face_parent('unused','1'*64,process_id=12,expected_document_path='unused',expected_source_sha256='2'*64,expected_feature_native_id=700)
    assert len(out['pins'])==1 and out['pins'][0]['sha256']==m._self_pin()['sha256']
    assert out['lineage_pins'][0]['path']==live[0]['path'] and out['lineage_pins'][0]['sha256']==old['sha256']
    loaded['pins'][0]['sha256']='f'*64
    with pytest.raises(ValueError):m.load_face_parent('unused','1'*64,process_id=12,expected_document_path='unused',expected_source_sha256='2'*64,expected_feature_native_id=700)
