"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast,hashlib,inspect,json
import pytest
from scripts import sw_cam_raw_mill_face_save as m

from cam_face_test_fixtures import state as synthetic_state

def put(path,data):
    path.write_text(json.dumps(data),encoding='utf-8');return m._pin(path)
def circle(z):return dict(curve_type=2,centre_native=[0.,0.,z],radius_native=32.5,normal_native=[0.,0.,1.],direction_raw=1)


@pytest.fixture
def chain(tmp_path,monkeypatch):
    cp=dict(state=synthetic_state(20),payload=dict(rough={'fixture':'rough'},finish={'fixture':'finish'}),sketch_spec={},cone_observation={'fixture':'cone'})
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'clean saved20')
    source_sha=m._file_hash(source);pid=17;cone_id=264;face_id=265
    state=deepcopy(cp['state']);state['document']=dict(path=str(source),title=source.name,type=1,needs_save=False);state['saved_file_sha256']=source_sha
    parent=put(tmp_path/'saved20.json',{});parentmark=put(tmp_path/'saved20_marker.json',{})
    baseline=put(tmp_path/'branch_baseline.json',dict(scope=m.cone.BASELINE_SCOPE,status='verified_offline_terminal_branch',old_loader_verified=True,runtime_rebind_explicit=True))
    live=[parent,parentmark,m._pin(m.face.__file__),baseline]
    for i in range(59):live.append(put(tmp_path/('pending100.json' if i==0 else 'critical'+str(i)+'.json'),{}))
    history=[put(tmp_path/('completed'+str(i)+'.json'),{}) for i in range(3)]
    ids=dict(target_feature_native_id=244,target_operation_native_id=247,target_operation_setup_native_id=93,
        expected_candidate_tool_native_id=263,finish_operation_native_id=248,finish_tool_native_id=249)
    loaded=dict(state=state,payload=deepcopy(cp['payload']['rough']),finish_payload=deepcopy(cp['payload']['finish']),
        pins=live,lineage_pins=history,parent_pin=parent,pin=baseline,save_receipt={'marker_path':parentmark['path']},
        sketch_spec=deepcopy(cp['sketch_spec']),cone_observation=deepcopy(cp['cone_observation']),
        ids=ids,ownership=dict(create_time='offline-owned',executable='offline'),qualification=None,observation_pin=live[-1],
        read_mode='bounded',base_saved_pin=live[-2],holder_recipe={})
    spec=deepcopy(m.face.FACE_SPEC)
    oldsketch=dict(pid=pid,path=str(source),saved_file_sha256=source_sha,spec=spec,needs_save=False,
        features=deepcopy(state['sw_reference']['feature_tree']),solids=deepcopy(state['sw_reference']['solids']))
    newsketch=deepcopy(oldsketch);newsketch['needs_save']=True
    created=[dict(name=spec['plane_name'],type='RefPlane'),dict(name=spec['sketch_name'],type='ProfileFeature')]
    newsketch['features']+=created
    sketchreport=dict(status='ok',phase='finished',native_readback_verified=True,mutation_attempted=True,saved=False,CAD_solid_edit_attempted=False,CAM_calls=0,
        before=oldsketch,after=newsketch,state_sha256=m.cone._state_digest(oldsketch),after_state_sha256=m.cone._state_digest(newsketch),created_features=created)
    sketchpin=put(tmp_path/'face_sketch.json',sketchreport)
    _,sketchpin,before=m.cone.load_sketch_prerequisite(sketchpin['path'],sketchpin['sha256'],loaded,spec,pid)
    header=dict(native_id=face_id,volume_type=5,subtype_raw=0,shape_raw=0,suppressed=False,name='FaceStockCircle',axis_native=[0.,0.,-1.],
        depth_native=2.,bounds_native=[65.,65.,2.],start_native=[32.5,0.,28.])
    after=deepcopy(before);index=next(i for i,x in enumerate(after['feature_setups']) if x['native_id']==69)
    n=after['feature_setups'][index]['feature_count'];row=dict(setup_index=index,feature_index=n,setup_native_id=69,geometry=deepcopy(header))
    at=max(i for i,x in enumerate(after['features']) if x['setup_index']==index)+1;after['features'].insert(at,row);after['feature_setups'][index]['feature_count']+=1
    rawsketch=dict(entities=[dict(type='circle',center_model_m=[0.,0.,.028],radius_m=.0325)],
        model_to_sketch_transform=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.])
    sc=m.face._circle_sketch(rawsketch,spec)
    geom=dict(header,taper_enabled=False,island_count=0,top_curves_native=[circle(28.)],bottom_curves_native=[circle(28.)])
    obs=dict(sketch=rawsketch,sketch_circle_m=sc,feature=geom)
    data=dict(scope=m.face.SCOPE,route_scope=m.face.ROUTE_SCOPE,status='uncertain',phase='finished',failed_phase='after',issue=dict(type='ValueError',locations=[dict(file='sw_cam_raw_mill_face_feature.py',function='verify_face_geometry',line=93)]),process_id=pid,new_feature_native_id=face_id,
        expected_document_path=str(source),expected_source_sha256=source_sha,source_after_sha256=source_sha,face_module_pin=m._pin(m.face.__file__),
        creator_call_count=1,before=before,after=after,new_feature=row,before_payload=m._payload(loaded),after_payload=m._payload(loaded),
        before_cone_observation=deepcopy(cp['cone_observation']),after_cone_observation=deepcopy(cp['cone_observation']),
        face_sketch_before=dict(sketch=rawsketch,sketch_circle_m=sc),face_observation=obs,
        parent_pin=parent,parent_cone_feature_native_id=cone_id,sketch_spec=spec,sketch_receipt_pin=sketchpin,
        evidence_pins=m.canonical_evidence_pins(live,[sketchpin]),lineage_pins=history,
        messages=dict(subscribed=True,active=False,disconnected=True,event_count=0))
    for name in ('mutation_attempted','native_call_attempted','native_call_returned'):data[name]=True
    for name in ('readback_verified','native_dispatch_pending','GOP_attempted','GTP_attempted','save_attempted','model_saved','sketch_edit_attempted','CAD_solid_edit_attempted',
        'automatic_retry','automatic_replay','automatic_rollback','production_route_changed'):data[name]=False
    marker=m.face.face_marker(str(source),source_sha);data['marker_path']=str(marker)
    facepin=put(tmp_path/'face_completed.json',data)
    put(marker,dict(scope=m.face.SCOPE,status='uncertain',source=str(source),source_sha256=source_sha,receipt_path=facepin['path'],receipt_sha256=facepin['sha256'],
        native_call_attempted=True,native_call_returned=True,readback_verified=False,automatic_replay=False))
    monkeypatch.setattr(m.face,'load_face_parent',lambda *a,**kw:deepcopy(loaded))
    args=dict(process_id=pid,expected_document_path=str(source),expected_source_sha256=source_sha,expected_feature_native_id=face_id)
    return SimpleNamespace(source=source,source_sha=source_sha,pid=pid,face_id=face_id,facepin=facepin,marker=marker,data=data,
        loaded=loaded,args=args,sketchpin=sketchpin,parent=parent,parentmark=parentmark,history=history,baseline=baseline)

def load(c):return m.load_failed_face(c.facepin['path'],c.facepin['sha256'],**c.args)

@pytest.fixture
def native_case(chain,monkeypatch,tmp_path):
    import scripts.sw_cam_events as events
    c=chain;loaded=load(c);doc=deepcopy(loaded['state']['document']);calls=[];captures=[];flags={};mode={'return':0}
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def typed(self,obj,name):return obj
    class Context:
        def __init__(self,l,a,sw,typelib,app,event,state):self.loaded=l;self.args=a;self.sw=sw;self.typelib_path=typelib;self.app=app;self.expected_document=deepcopy(state['document'])
        def files(self):m._check_pins(self.loaded['pins']);m._check_pins(self.loaded['lineage_pins'])
        def identity(self):return deepcopy(doc)
        def owned(self):pass
        def guard(self):return Guard()
    class Session:
        def __init__(self,*a):self.active=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=not self.active,event_count=0)
    monkeypatch.setattr(m,'FaceSaveContext',Context);monkeypatch.setattr(m.cone,'_bootstrap',lambda *a:object());monkeypatch.setattr(events,'CamMessageSession',Session)
    def headers(ctx,clsid,reference,count,diag):
        assert count==21 and len(reference['features'])==20
        label=diag.get('phase','recovery');captures.append(label);state=deepcopy(loaded['state']);state['document']=deepcopy(doc);state['saved_file_sha256']=m._file_hash(c.source)
        if (flags.get('after_drift') and label=='after') or (flags.get('recovery_drift') and label=='recovery'):state['operations'][0]['suppressed']=not state['operations'][0]['suppressed']
        if flags.get('mass_roundoff'):state['sw_reference']['solids'][0]['mass_raw'][0]*=1+1e-13
        return state,{}
    monkeypatch.setattr(m.face,'_capture_headers',headers)
    def payload(ctx,state,native,diag):
        value=m._payload(loaded)
        if flags.get('payload_drift') and diag.get('phase')=='after':value['finish']={}
        diag['observed_payload']=deepcopy(value)
        if flags.get('payload_drift') and diag.get('phase')=='after':raise ValueError('payload changed')
        return value
    monkeypatch.setattr(m.cone,'_capture_payload',payload)
    monkeypatch.setattr(m.cone,'_read_sketch_and_cone',lambda *a:deepcopy(loaded['cone_observation']))
    def face_obs(*a,diagnostic,persist):
        diagnostic.update(deepcopy(loaded['face_observation']))
        if flags.get('face_drift'):diagnostic['feature']['depth_native']=1.
        persist();return diagnostic
    monkeypatch.setattr(m.face,'_read_face',face_obs)
    monkeypatch.setattr(m,'raw_part_identity',lambda sw:deepcopy(doc))
    def native(obj,name):
        assert name=='SaveActiveDocument';calls.append(name)
        marker=m.save_marker(str(c.source),c.source_sha,c.face_id,c.facepin['sha256']);assert marker.exists()
        pending=json.loads(marker.read_text());assert pending['save_pending'] is True
        c.source.write_bytes(b'new clean saved21');doc['needs_save']=False
        return mode['return']
    monkeypatch.setattr(m,'_member',native)
    kwargs=dict(face_receipt_path=c.facepin['path'],face_receipt_sha256=c.facepin['sha256'],**c.args,
        receipt_path=str(tmp_path/'save21.json'),qualification_only=True,acknowledge_disposable_copy=True)
    return SimpleNamespace(c=c,loaded=loaded,doc=doc,kwargs=kwargs,calls=calls,captures=captures,flags=flags,mode=mode)

def recover(n,name='recovery.json'):
    path=Path(n.kwargs['receipt_path']).with_name(name)
    report=m.recover_existing_face_readonly(None,None,None,**dict(n.kwargs,receipt_path=str(path)))
    return report,path

def recovery_load(n,path):
    return m.load_completed_face_recovery(str(path),m._file_hash(path),**n.c.args)

def save(n,path):
    kwargs={k:v for k,v in n.kwargs.items() if k not in ('face_receipt_path','face_receipt_sha256')}
    return m.save_existing_raw_face(None,None,None,**dict(kwargs,recovery_receipt_path=str(path),recovery_receipt_sha256=m._file_hash(path)))

def terminal(n,report,check=True):
    return m.load_completed_face_save(n.kwargs['receipt_path'],m._file_hash(n.kwargs['receipt_path']),
        **dict(n.c.args,expected_source_sha256=report['saved_file_sha256']),check_current_source=check)

def test_actual_anchor_and_failed_loader64_6(chain):
    c=chain;l=load(c)
    assert len(l['pins'])==64 and len(l['lineage_pins'])==6 and l['baseline_verified']
    assert m._key(c.facepin['path']) in m._pin_map(l['pins']) and m._key(c.marker) in m._pin_map(l['pins'])
    assert m._key(c.sketchpin['path']) in m._pin_map(l['lineage_pins'])
    assert any(Path(p['path']).name=='pending100.json' for p in l['pins'])

def test_readonly_single_capture_immutable_original64_7(native_case):
    n=native_case;old=m._file_hash(n.c.facepin['path']);marker=m._file_hash(n.c.marker)
    r,path=recover(n);assert r['readback_verified'] and r['full_capture_count']==1 and n.captures==['recovery'] and n.calls==[]
    assert m._file_hash(n.c.facepin['path'])==old and m._file_hash(n.c.marker)==marker and m._file_hash(n.c.source)==n.c.source_sha
    loaded=recovery_load(n,path);assert len(loaded['pins'])==64 and len(loaded['lineage_pins'])==7
    assert m._key(n.c.marker) in m._pin_map(loaded['pins']) and m._key(n.c.facepin['path']) in m._pin_map(loaded['lineage_pins'])
    assert r['geometry_acceptance']['raw_start_native']==[32.5,0.,28.] and not r['geometry_acceptance']['start_coordinate_semantics_qualified']

@pytest.mark.parametrize('fault',['recovery_drift','face_drift'])
def test_readonly_mismatch_preserves_raw_and_does_not_authorize_save(native_case,fault):
    n=native_case;n.flags[fault]=True;r,path=recover(n)
    assert r['status']=='error' and not r['readback_verified'] and n.calls==[] and n.captures==['recovery']
    disk=json.loads(path.read_text());assert 'observed_context' in disk and 'observed_face' in disk
    with pytest.raises(ValueError):recovery_load(n,path)

def test_recovery_then_save_terminal64_9_no_old_research(native_case,monkeypatch):
    n=native_case;r,path=recover(n);assert r['readback_verified']
    sr=save(n,path);assert sr['readback_verified'] and sr['status']=='review_required'
    assert n.calls==['SaveActiveDocument'] and n.captures==['recovery','before','after']
    assert len(sr['checkpoint']['fixed_live_pins'])==62 and len(sr['checkpoint']['lineage_pins'])==9
    def forbidden(*a,**kw):raise AssertionError('Earlier research loader called')
    monkeypatch.setattr(m.face,'load_face_parent',forbidden);monkeypatch.setattr(m,'load_failed_face',forbidden)
    loaded=terminal(n,sr);assert len(loaded['pins'])==64 and len(loaded['lineage_pins'])==9
    assert loaded['state']['document']['needs_save'] is False and loaded['source_sha256']==m._file_hash(n.c.source)
    assert m._key(n.c.marker) in m._pin_map(loaded['pins'])
    assert not loaded['checkpoint']['prior_receipts_embedded'] and not loaded['checkpoint']['recursive_legacy_loader_required']

@pytest.mark.parametrize('value',[False,1,0.])
def test_save_requires_strict_zero_and_stops_without_after_capture(native_case,value):
    n=native_case;r,path=recover(n);n.mode['return']=value;sr=save(n,path)
    assert sr['status']=='uncertain' and not sr['readback_verified'] and n.calls==['SaveActiveDocument']
    assert n.captures==['recovery','before'] and not sr['save_readback_verified']

def test_bad_baseline_hash_fails_before_save_dispatch(native_case):
    n=native_case;r,path=recover(n);d=json.loads(path.read_text());d['checkpoint']['completed_baseline_pin']['sha256']='f'*64
    d['checkpoint_sha256']=m._digest(d['checkpoint']);put(path,d)
    with pytest.raises(ValueError):save(n,path)
    assert n.calls==[] and n.captures==['recovery']

def test_recovery_name_cannot_rearm_stable_save_marker(native_case):
    n=native_case;first,p1=recover(n,'r1.json');second,p2=recover(n,'r2.json')
    l1=recovery_load(n,p1);l2=recovery_load(n,p2)
    assert m.save_marker(str(n.c.source),n.c.source_sha,n.c.face_id,l1['face_receipt_pin']['sha256'])==m.save_marker(str(n.c.source),n.c.source_sha,n.c.face_id,l2['face_receipt_pin']['sha256'])
    marker=m.save_marker(str(n.c.source),n.c.source_sha,n.c.face_id,l1['face_receipt_pin']['sha256']);put(marker,{'status':'dispatch_pending'})
    with pytest.raises(ValueError):save(n,p2)
    assert n.calls==[]

@pytest.mark.parametrize('which',['unknown_marker','completed_history','source'])
def test_recovery_dependencies_fail_before_save(native_case,which):
    n=native_case;r,path=recover(n)
    if which=='unknown_marker':n.c.marker.write_text('{}')
    elif which=='completed_history':Path(n.c.sketchpin['path']).write_text('{}')
    else:n.c.source.write_bytes(b'changed saved source')
    with pytest.raises((ValueError,KeyError)):save(n,path)
    assert n.calls==[]

def test_payload_after_save_failure_retains_data(native_case):
    n=native_case;r,path=recover(n);n.flags['payload_drift']=True;sr=save(n,path)
    assert sr['status']=='uncertain' and n.calls==['SaveActiveDocument']
    disk=json.loads(Path(n.kwargs['receipt_path']).read_text());assert disk['snapshot_diagnostics'][-1]['observed_payload']['finish']=={}

def test_saved_historical_source_is_explicit(native_case):
    n=native_case;r,path=recover(n);sr=save(n,path);n.c.source.write_bytes(b'later file revision')
    with pytest.raises(ValueError):terminal(n,sr)
    assert terminal(n,sr,False)['historical_only']

def test_actual_cli_schemas_bind_only_correct_native_actions(native_case):
    n=native_case;p=dict(n.kwargs,module_sha256=m._self_pin()['sha256'],addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',message_policy='vendor_default')
    q=m.validate_request(dict(action='recover_readonly',params=p));q.pop('module_sha256');q.pop('addin_clsid')
    inspect.signature(m.recover_existing_face_readonly).bind(None,None,None,**q)
    p['recovery_receipt_path']=p.pop('face_receipt_path');p['recovery_receipt_sha256']=p.pop('face_receipt_sha256')
    q=m.validate_request(dict(action='save_existing_raw_face',params=p));q.pop('module_sha256');q.pop('addin_clsid')
    inspect.signature(m.save_existing_raw_face).bind(None,None,None,**q)
    with pytest.raises(ValueError):m.validate_request(dict(action='recover_readonly',params=p))

def test_readonly_has_no_native_mutation_and_terminal_no_legacy():
    t=ast.parse(Path(m.__file__).read_text(encoding='utf-8'));functions={n.name:n for n in t.body if isinstance(n,ast.FunctionDef)}
    calls=lambda f:[ast.unparse(n.func) for n in ast.walk(functions[f]) if isinstance(n,ast.Call)]
    assert '_member' not in calls('recover_existing_face_readonly')
    assert not {'load_failed_face','face.load_face_parent','saved.load_completed_upper_cone_save'} & set(calls('load_completed_face_save'))
    assert not {'load_failed_face','face.load_face_parent','saved.load_completed_upper_cone_save'} & set(calls('load_completed_face_recovery'))
