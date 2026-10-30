"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,ast
import pytest
from scripts import sw_cam_upper_cone_feature as m

SPEC=dict(plane_axis='Z',plane_offset_mm=26.,sketch_name='UpperConeCircle',plane_name='UpperConePlane',
    profile=dict(kind='circle',center_model_mm=[0.,0.,26.],radius_mm=23.55))

def circle(z,r):return dict(curve_type=2,centre_native=[0.,0.,z],radius_native=r,normal_native=[0.,0.,1.],direction_raw=1)
def geometry():return dict(native_id=700,volume_type=2,suppressed=False,depth_native=.2,axis_native=[0.,0.,-1.],start_native=[0.,0.,26.],
    bounds_native=[47.1,47.1,.2],taper_enabled=True,taper_angle_readback=45.,top_curves_native=[circle(26.,23.55)],bottom_curves_native=[circle(25.8,23.35)])
def sketch_circle():return dict(center_model_m=[0.,0.,.026],radius_m=.02355,normal_model=[0.,0.,1.])
def states():
    rows=[]
    for si,(sid,count) in enumerate([(69,13),(71,5),(73,1)]):
        for fi in range(count):rows.append(dict(setup_index=si,feature_index=fi,setup_native_id=sid,geometry=dict(native_id=100+len(rows),value='kept')))
    before=dict(features=rows,feature_setups=[dict(native_id=s,feature_count=c,axis_native=[0.,0.,-1.]) for s,c in [(69,13),(71,5),(73,1)]],
        document=dict(needs_save=True),operations=[dict(native_id=i) for i in range(6)],stock={'kept':True},sw_reference={'kept':True,'solids':[{'box_m':[0.,0.,0.,1.,1.,1.],'mass_raw':[float(i+1) for i in range(12)]}]})
    after=deepcopy(before);after['features'].insert(13,dict(setup_index=0,feature_index=13,setup_native_id=69,geometry=dict(native_id=700,value='new')))
    after['feature_setups'][0]['feature_count']+=1
    return before,after

def test_exact_end_circles():
    got=m.verify_cone_geometry(geometry(),sketch_circle(),700)
    assert got['native_configuration_verified'] and got['distinct_native_planes_observed']
    assert not got['taper_api_units_qualified'] and not got['geometric_depth_verified'] and not got['complete_conical_surface_proved']

@pytest.mark.parametrize('key,value',[('native_id',True),('volume_type',11),('suppressed',True),('depth_native',.3),('axis_native',[0,0,1]),
    ('start_native',[0,0,25.8]),('bounds_native',[46.7,46.7,.2]),('taper_enabled',1),('taper_angle_readback',0),('taper_angle_readback',float('nan'))])
def test_wrong_native_header_rejected(key,value):
    g=geometry();g[key]=value
    with pytest.raises(ValueError):m.verify_cone_geometry(g,sketch_circle(),700)

@pytest.mark.parametrize('where,field,value',[('bottom_curves_native','centre_native',[0,0,25.9]),('top_curves_native','radius_native',23.35),
    ('bottom_curves_native','radius_native',23.55),('bottom_curves_native','normal_native',[0,1,0]),('bottom_curves_native','centre_native',[.001,0,25.8])])
def test_bad_or_coplanar_native_contour_rejected(where,field,value):
    g=geometry();g[where][0][field]=value
    with pytest.raises(ValueError):m.verify_cone_geometry(g,sketch_circle(),700)

@pytest.mark.parametrize('change',['source_radius','sketch_center','sketch_scale','missing_curve','extra_curve'])
def test_sketch_or_native_topology_mismatch(change):
    g=geometry();s=sketch_circle()
    if change=='source_radius':s['radius_m']=.02335
    elif change=='sketch_center':s['center_model_m'][2]=.0258
    elif change=='sketch_scale':s['radius_m']=23.55
    elif change=='missing_curve':g['bottom_curves_native']=[]
    else:g['top_curves_native'].append(circle(26,23.55))
    with pytest.raises(ValueError):m.verify_cone_geometry(g,s,700)

@pytest.mark.parametrize('angle',[0,-45,True,float('nan'),float('inf'),91])
def test_taper_requires_explicit_finite_nonzero_candidate(angle):
    with pytest.raises(ValueError):m.validate_cone_request(sketch_spec=SPEC,taper_angle_native=angle,taper_type=0,acknowledge_unqualified_taper=True)

@pytest.mark.parametrize('kind',[-1,2,True,'0'])
def test_exact_taper_enum(kind):
    with pytest.raises(ValueError):m.validate_cone_request(sketch_spec=SPEC,taper_angle_native=45,taper_type=kind,acknowledge_unqualified_taper=True)

def test_acknowledgement_required_and_no_unit_assumption():
    with pytest.raises(ValueError):m.validate_cone_request(sketch_spec=SPEC,taper_angle_native=45,taper_type=0,acknowledge_unqualified_taper=False)
    assert m.validate_cone_request(sketch_spec=SPEC,taper_angle_native=.7853981633974483,taper_type=1,acknowledge_unqualified_taper=True)==SPEC

def test_only_one_feature_delta():
    a,b=states();assert m.verify_feature_delta(a,b,700,69)['geometry']['native_id']==700

@pytest.mark.parametrize('change',['old_feature','operation','stock','new_setup','missing_setup','second_feature','duplicate','owner','order'])
def test_unrelated_or_additional_delta_rejected(change):
    a,b=states()
    if change=='old_feature':b['features'][0]['geometry']['value']='changed'
    elif change=='operation':b['operations'][0]['native_id']=99
    elif change=='stock':b['stock']['kept']=False
    elif change=='new_setup':b['feature_setups'].append(dict(native_id=99,feature_count=0))
    elif change=='missing_setup':b['feature_setups'].pop()
    elif change=='second_feature':b['features'].append(dict(setup_index=0,feature_index=14,setup_native_id=69,geometry=dict(native_id=701)))
    elif change=='duplicate':b['features'][13]['geometry']['native_id']=100
    elif change=='owner':b['features'][13]['setup_native_id']=71
    elif change=='order':b['features'][0],b['features'][1]=b['features'][1],b['features'][0]
    with pytest.raises(ValueError):m.verify_feature_delta(a,b,700,69)

def test_marker_cannot_be_rearmed_by_recipe_or_receipt(tmp_path):
    assert m.cone_marker(tmp_path/'p.sldprt','1'*64)==m.cone_marker(tmp_path/'p.sldprt','1'*64)
    assert m.cone_marker(tmp_path/'p.sldprt','1'*64)!=m.cone_marker(tmp_path/'p.sldprt','2'*64)
    assert 'taper_angle_native' not in m.cone_marker.__code__.co_varnames

@pytest.fixture
def baseline(tmp_path,monkeypatch):
    from scripts import sw_cam_finish_continuation_evidence as old
    root=tmp_path/'runtime';scripts=root/'scripts';scripts.mkdir(parents=True);server=root/'mcp-server/server.py';server.parent.mkdir();server.write_bytes(b'old-server')
    for name in m.EXTRA_RUNTIME:(scripts/name).write_bytes(b'dependency '+name.encode())
    source=tmp_path/'part.sldprt';source.write_bytes(b'saved-terminal');stock=tmp_path/'stock.stl';stock.write_bytes(b'stock')
    a,_=states();a['document']=dict(path=str(source),title=source.name,type=1,needs_save=False);a['saved_file_sha256']=m._file_hash(source)
    a['stock']=dict(stl_path=str(stock),stl_sha256=m._file_hash(stock))
    checkpoint=dict(state=a,payload=dict(rough={'r':1},finish={'f':2}),source_sha256=m._file_hash(source))
    terminal=tmp_path/'terminal.json';terminal.write_text(json.dumps(dict(action='save',parent_action='cl',checkpoint=checkpoint)))
    marker=tmp_path/'save_marker.json';marker.write_text('{}')
    unknown=tmp_path/'unknown_pending_marker.json';unknown.write_text('{"status":"uncertain"}')
    owned=tmp_path/'owned.json';owned.write_text('{}')
    pins=[m._pin(x) for x in (server,terminal,marker,unknown,owned)]
    lineage=[]
    for i in range(7):
        p=tmp_path/('old'+str(i)+'.json');p.write_text('{}');lineage.append(m._pin(p))
    loaded=dict(state=a,payload={'r':1},finish_payload={'f':2},source_sha256=m._file_hash(source),ownership={'owner':'kept'},
        qualification=None,observation_pin=m._pin(owned),read_mode='strong',pins=pins,lineage_pins=lineage,
        active_continuation_pins=[m._pin(terminal),m._pin(marker)])
    monkeypatch.setattr(old,'load_finish_continuation',lambda *a,**kw:deepcopy(loaded));monkeypatch.setattr(old,'selected',lambda *a,**kw:None)
    monkeypatch.setattr(m,'runtime_root',lambda:scripts)
    ids={k:i+1 for i,k in enumerate(m.IDS)};args=dict(process_id=123,expected_document_path=str(source),expected_source_sha256=m._file_hash(source),**ids)
    newserver=hashlib.sha256(b'new-server').hexdigest();out=tmp_path/'baseline.json'
    result=m.build_upper_cone_baseline(str(terminal),m._file_hash(terminal),output_path=str(out),new_server_sha256=newserver,**args)
    return SimpleNamespace(root=root,scripts=scripts,server=server,source=source,stock=stock,out=out,result=result,loaded=loaded,args=args,unknown=unknown)

def activate_baseline(b,monkeypatch):
    target=b.scripts/'sw_cam_upper_cone_feature.py';target.write_bytes(Path(m.__file__).read_bytes());monkeypatch.setattr(m,'__file__',str(target));b.server.write_bytes(b'new-server')

def test_explicit_runtime_cutover_preserves_pending_marker_and_source(baseline,monkeypatch):
    b=baseline
    with pytest.raises(ValueError):m.load_upper_cone_baseline(str(b.out),m._file_hash(b.out),**{k:b.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
    activate_baseline(b,monkeypatch)
    got=m.load_upper_cone_baseline(str(b.out),m._file_hash(b.out),**{k:b.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
    assert any(m._key(x['path'])==m._key(b.unknown) for x in got['pins'])
    assert not any(Path(x['path']).name in ('terminal.json','save_marker.json') for x in got['pins'])
    assert got['state']==b.loaded['state'] and not got['historical_only']
    assert got['baseline']['cad_source_rebound'] is False and b.source.read_bytes()==b'saved-terminal'

@pytest.mark.parametrize('change',['source','pending','runtime','archive','context','pid'])
def test_branch_rejects_changes(baseline,monkeypatch,change):
    b=baseline;activate_baseline(b,monkeypatch);args={k:b.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    if change=='source':b.source.write_bytes(b'changed')
    elif change=='pending':b.unknown.write_bytes(b'changed')
    elif change=='runtime':b.server.write_bytes(b'unexpected-server')
    elif change=='pid':args['process_id']=999
    else:
        d=json.loads(b.out.read_text());
        if change=='archive':d['archived_inputs'][0]['base64']='eA=='
        else:d['context']['payload']['r']=3
        b.out.write_text(json.dumps(d))
    with pytest.raises(ValueError):m.load_upper_cone_baseline(str(b.out),m._file_hash(b.out),**args)

def test_native_core_never_contains_generation_or_save_dispatch():
    tree=ast.parse(Path(m.__file__).read_text());f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='create_upper_cone_feature')
    calls=[n for n in ast.walk(f) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_member']
    assert len(calls)==1 and calls[0].args[1].value=='CreateMillFeature2'
    assert len(calls[0].args)==15


@pytest.fixture
def native_case(tmp_path,monkeypatch):
    import scripts.sw_cam_events as events
    before,after=states();source=tmp_path/'part.sldprt';source.write_bytes(b'saved')
    doc=dict(path=str(source),title=source.name,type=1,needs_save=True)
    before['document']=deepcopy(doc);after['document']=deepcopy(doc)
    before['saved_file_sha256']=after['saved_file_sha256']=m._file_hash(source)
    base=tmp_path/'base.json';base.write_text('{}');sketch=tmp_path/'sketch.json';sketch.write_text('{}')
    loaded=dict(state=deepcopy(before),payload={'r':1},finish_payload={'f':2},pins=[m._pin(base)],pin=m._pin(base),
        ids={k:i+1 for i,k in enumerate(m.IDS)},ownership={})
    setup=object();docobj=object();newobj=object();calls=[];flags={}
    native=dict(setups=[setup,object(),object()],doc=docobj)
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def typed(self,obj,name):return obj
        def read(self,*a):return None
        def dispatch_once(self,fn,*,persist_pending):
            persist_pending();flags['marker_exists_before_dispatch']=m.cone_marker(source,m._file_hash(source)).exists();return fn()
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
    monkeypatch.setattr(m,'load_upper_cone_baseline',lambda *a,**kw:deepcopy(loaded))
    monkeypatch.setattr(m,'load_sketch_prerequisite',lambda *a:(dict(),m._pin(sketch),deepcopy(before)))
    monkeypatch.setattr(m,'UpperConeContext',Context);monkeypatch.setattr(m,'_bootstrap',lambda *a:object());monkeypatch.setattr(events,'CamMessageSession',Session)
    monkeypatch.setattr(m,'_capture_headers',lambda ctx,clsid,ref,count,diag:(deepcopy(before if count==19 else after),native))
    monkeypatch.setattr(m,'_capture_payload',lambda *a:dict(rough={'r':1},finish={'f':2}))
    monkeypatch.setattr(m,'_read_sketch_and_cone',lambda *a:dict(sketch={},sketch_circle_m=sketch_circle(),feature=geometry()))
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:69 if obj is setup else 700)
    monkeypatch.setattr(m,'_is_comtypes_pointer',lambda obj:obj is newobj)
    def native_call(obj,name,*args):
        calls.append((name,args));assert flags['marker_exists_before_dispatch'];return newobj
    monkeypatch.setattr(m,'_member',native_call)
    kwargs=dict(baseline_path=str(base),baseline_sha256=m._file_hash(base),sketch_receipt_path=str(sketch),sketch_receipt_sha256=m._file_hash(sketch),
        process_id=123,expected_document_path=str(source),expected_source_sha256=m._file_hash(source),sketch_spec=SPEC,
        taper_angle_native=45.,taper_type=0,acknowledge_unqualified_taper=True,receipt_path=str(tmp_path/'result.json'),qualification_only=True,acknowledge_disposable_copy=True)
    return SimpleNamespace(kwargs=kwargs,calls=calls,flags=flags,after=after,newobj=newobj)

def test_one_native_creator_no_gop_gtp_save(native_case):
    n=native_case;r=m.create_upper_cone_feature(None,None,None,**n.kwargs)
    assert r['readback_verified'] and r['creator_call_count']==1 and r['status']=='review_required'
    assert [x[0] for x in n.calls]==['CreateMillFeature2']
    assert n.calls[0][1]==(0,'UpperConeCircle',False,.2,False,False,False,False,45.,0,False,0,0)
    assert all(r[k] is False for k in ('GOP_attempted','GTP_attempted','save_attempted','model_saved','sketch_edit_attempted','CAD_solid_edit_attempted'))
    with pytest.raises(ValueError):m.create_upper_cone_feature(None,None,None,**dict(n.kwargs,receipt_path=str(Path(n.kwargs['receipt_path']).with_name('retry.json'))))
    assert len(n.calls)==1

@pytest.mark.parametrize('change',['second_feature','old_operation','geometry_wrong_radius','return_scalar'])
def test_native_mutation_outcome_uncertain_without_replay(native_case,monkeypatch,change):
    n=native_case
    if change=='second_feature':n.after['features'].append(dict(geometry=dict(native_id=701)))
    elif change=='old_operation':n.after['operations'][0]['native_id']=999
    elif change=='geometry_wrong_radius':
        g=geometry();g['bottom_curves_native'][0]['radius_native']=23.55
        monkeypatch.setattr(m,'_read_sketch_and_cone',lambda *a:dict(sketch={},sketch_circle_m=sketch_circle(),feature=g))
    else:monkeypatch.setattr(m,'_is_comtypes_pointer',lambda obj:False)
    r=m.create_upper_cone_feature(None,None,None,**n.kwargs)
    assert r['status']=='uncertain' and not r['readback_verified'] and r['creator_call_count']==1 and len(n.calls)==1
    assert not r['save_attempted'] and not r['GTP_attempted'] and not r['GOP_attempted']


def test_payload_failure_retains_fresh_state_and_payload(native_case,monkeypatch):
    n=native_case
    def fail_after(ctx,state,native,diagnostic):
        value=dict(rough={'r':1},finish={'f':3 if diagnostic['phase']=='after' else 2})
        diagnostic['observed_payload']=deepcopy(value)
        if diagnostic['phase']=='after':raise ValueError('Protected payload changed')
        return value
    monkeypatch.setattr(m,'_capture_payload',fail_after)
    r=m.create_upper_cone_feature(None,None,None,**n.kwargs)
    disk=json.loads(Path(n.kwargs['receipt_path']).read_text(encoding='utf-8'))
    assert r['status']=='uncertain' and r['creator_call_count']==1
    assert disk['snapshot_diagnostics'][-1]['observed_state']==n.after
    assert disk['snapshot_diagnostics'][-1]['observed_payload']['finish']=={'f':3}
    assert not disk['readback_verified']


def test_recovery_terminal_loader_explicit_before_cutover(baseline,monkeypatch):
    b=baseline
    module=b.scripts/'sw_cam_finish_recovery.py'
    module.write_text('def load_completed_recovery(*a,**kw):\n    assert kw["action"]=="save"\n    import json\n    from pathlib import Path\n    return json.loads(Path(__file__).with_suffix(".fixture.json").read_text())\n')
    terminal=Path(b.loaded['active_continuation_pins'][0]['path'])
    t=json.loads(terminal.read_text());t.update(scope='RECOVERED_FINISH_SAVE_V1',parent_action='export_cl',recovery_module_pin=m._pin(module));terminal.write_text(json.dumps(t))
    loaded=deepcopy(b.loaded);old=m._key(terminal)
    loaded['pins']=[m._pin(terminal) if m._key(v['path'])==old else v for v in loaded['pins']]
    loaded['active_continuation_pins'][0]=m._pin(terminal);loaded['pins'].append(m._pin(module))
    module.with_suffix('.fixture.json').write_text(json.dumps(loaded))
    out=b.out.with_name('recovery_baseline.json')
    result=m.build_upper_cone_baseline(str(terminal),m._file_hash(terminal),output_path=str(out),new_server_sha256=hashlib.sha256(b'new-server').hexdigest(),**b.args)
    assert result['native_calls']==0
    d=json.loads(out.read_text());assert d['terminal_checkpoint']==t['checkpoint']
    assert any(m._key(v['pin']['path'])==m._key(module) for v in d['archived_inputs'])


def test_archived_terminal_must_equal_context(baseline,monkeypatch):
    b=baseline;activate_baseline(b,monkeypatch)
    d=json.loads(b.out.read_text());d['terminal_checkpoint']['state']['document']['title']='different'
    d['context']['state']['document']['title']='different';d['context_sha256']=m._digest(d['context']);b.out.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='Archived terminal checkpoint'):
        m.load_upper_cone_baseline(str(b.out),m._file_hash(b.out),**{k:b.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')})


@pytest.fixture
def sketch_receipt(tmp_path):
    path=tmp_path/'part.sldprt';path.write_bytes(b'source');sha=m._file_hash(path)
    old=[dict(name='Body',type='Imported')];new=[dict(name='UpperConePlane',type='RefPlane'),dict(name='UpperConeCircle',type='ProfileFeature')]
    a=dict(pid=123,path=str(path),saved_file_sha256=sha,needs_save=False,features=old,solids=[],spec=SPEC)
    b=deepcopy(a);b.update(needs_save=True,features=deepcopy(old+new))
    state=dict(document=dict(path=str(path),needs_save=False),saved_file_sha256=sha,sw_reference=dict(feature_tree=old,solids=[]))
    receipt=dict(status='ok',phase='finished',native_readback_verified=True,mutation_attempted=True,saved=False,CAD_solid_edit_attempted=False,CAM_calls=0,
        before=a,after=b,state_sha256=m._state_digest(a),after_state_sha256=m._state_digest(b),created_features=new)
    return tmp_path/'sketch.json',receipt,dict(state=state)


def test_exact_sketch_receipt_changes_reference_tree_only(sketch_receipt):
    p,r,loaded=sketch_receipt;p.write_text(json.dumps(r))
    _,_,expected=m.load_sketch_prerequisite(str(p),m._file_hash(p),loaded,SPEC,123)
    assert expected['document']['needs_save'] and expected['sw_reference']['feature_tree']==r['after']['features']
    assert loaded['state']['document']['needs_save'] is False


@pytest.mark.parametrize('change',['saved','CAM_calls','source','pid','old_tree','extra_feature','wrong_kind','not_dirty'])
def test_sketch_receipt_rejects_unexpected_changes(sketch_receipt,change):
    p,r,loaded=sketch_receipt
    if change in ('saved','CAM_calls'):r[change]=True
    elif change=='source':r['after']['saved_file_sha256']='4'*64
    elif change=='pid':r['before']['pid']=999
    elif change=='old_tree':r['after']['features'][0]['name']='ChangedBody'
    elif change=='extra_feature':r['after']['features'].append(dict(name='Other',type='ProfileFeature'))
    elif change=='wrong_kind':r['created_features'][0]['type']='Cut'
    else:r['after']['needs_save']=False
    r.update(state_sha256=m._state_digest(r['before']),after_state_sha256=m._state_digest(r['after']))
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError):m.load_sketch_prerequisite(str(p),m._file_hash(p),loaded,SPEC,123)


def test_coplanar_raw_profiles_complete_configuration_without_fake_world_depth():
    g=geometry();g['bottom_curves_native'][0]['centre_native'][2]=26.
    r=m.verify_cone_geometry(g,sketch_circle(),700)
    assert r['native_configuration_verified'] and r['raw_profiles_coplanar'] and not r['distinct_native_planes_observed']
    assert r['raw_bottom_center_native']==[0,0,26] and r['raw_top_center_native']==[0,0,26]
    assert r['target_only']['bottom_z_mm']==25.8
    assert not any(r[k] for k in ('coordinate_frame_qualified','geometric_depth_verified','lower_world_boundary_synthesized','complete_conical_surface_proved'))


def test_exact_raw_taper_value_readback_is_required():
    g=geometry();g['taper_angle_readback']=.7853981633974483
    with pytest.raises(ValueError,match='Exact requested'):m.verify_cone_geometry(g,sketch_circle(),700)
    assert m.verify_cone_geometry(g,sketch_circle(),700,expected_taper_angle_native=.7853981633974483)['native_configuration_verified']
