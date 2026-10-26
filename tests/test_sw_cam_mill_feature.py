from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sw_cam_mill_feature as cam
from scripts import sw_cam_events as events

@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/'MILL.sldprt';path.write_bytes(b'part')
    receipt=tmp_path/'receipt.json';unitfile=tmp_path/'unit.json'
    spec=dict(kind='hole',expected_tip_angle_native=180.,sketch_name='BASE_SOCKET',depth_native=1.6,expected_start_native=[28.5,0.,1.65],expected_bounds_native=[2.7,2.7,1.6])
    docstate=dict(path=str(path),title=path.name,type=1,needs_save=False)
    initial=dict(document=docstate,saved_file_sha256=cam._file_hash(path),unit_record_raw='raw_record',feature_setups=[dict(native_id=42,axis_native=[1.,0.,0.],feature_count=0)],operation_counts=[],extend_holes_to_stock=False,stock={'type_raw':4},features=[],sketch_sha256='s',sketch={'name':'BASE_SOCKET'})
    state=dict(current=deepcopy(initial),writes=[],on_write=None,on_exit=None)
    eventdata=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],disconnect_errors=[])
    class Session:
        def __enter__(self):eventdata.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            eventdata.update(active=False,disconnected=True)
            if state['on_exit']:state['on_exit']()
        def summary(self):return deepcopy(eventdata)
    def put(*args):
        durable=json.loads(receipt.read_text());assert durable['mutation_attempted'] and not durable['native_call_returned']
        assert args==(4,'BASE_SOCKET',False,1.6,False,False,False,False,0.,-1,False,0,0)
        state['writes'].append(args);state['current']['document']['needs_save']=True
        state['current']['feature_setups'][0]['feature_count']+=1
        state['current']['features'].append(dict(native_id=99,name='Native hole',setup_index=0,axis_native=[1.,0.,0.],suppressed=False,volume_type=1,subtype=0,depth_native=1.6,bounds_native=[2.7,2.7,1.6],start_native=[28.5,0.,1.65],taper_angle_native=0.,tip_angle_native=180.))
        if state['on_write']:state['on_write']()
        return SimpleNamespace(native_id=99)
    setup=SimpleNamespace(CreateMillFeature2=Mock(side_effect=put))
    doc=SimpleNamespace(GetCWObjectID=Mock(side_effect=lambda x:(x.native_id,True)))
    def snap(*_,**kw):kw.get('check',lambda:None)();return deepcopy(state['current']),dict(app=object(),doc=doc,setup_handles=[setup])
    snapshots=Mock(side_effect=snap)
    monkeypatch.setattr(cam,'_snapshot',snapshots);monkeypatch.setattr(cam,'_typed',lambda o,*_:o)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(state['current']['document']))
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    monkeypatch.setattr(cam,'_bootstrap',lambda *_:object())
    def units(**extra):
        data=dict(status='qualified',interface='ICWSetup.CreateMillFeature2',document_path=str(path),unit_record_raw='raw_record',native_length_unit='mm',method='two measured native observations',observations=[dict(native=1.,interpreted_mm=1.),dict(native=2.,interpreted_mm=2.)])|extra
        unitfile.write_text(json.dumps(data));return dict(path=str(unitfile),sha256=cam._file_hash(unitfile))
    def run(action='apply',**extra):
        args=dict(expected_document_path=str(path),action=action,setup_index=0,expected_setup_native_id=42,feature_spec=spec,qualification_only=True,message_policy='vendor_default')
        if action=='apply':args.update(expected_state_sha256=cam._digest(state['current']),unit_evidence=units(),receipt_path=str(receipt))
        return cam.create_mill_feature(object(),'clsid','tlb',**(args|extra))
    return SimpleNamespace(**locals())


def test_exact_blind_feature_no_other_steps(probe):
    out=probe.run();assert out['readback_verified'] and out['new_feature_native_id']==99
    assert out['status']=='review_required' and not out['GOP_attempted'] and not out['sketch_edit_attempted'] and not out['geometry_match_independently_qualified']
    assert len(probe.state['writes'])==1 and json.loads(probe.receipt.read_text())==out

@pytest.mark.parametrize('action',['inspect','prepare'])
def test_read_only(probe,action):
    assert probe.run(action)['status']=='ok' and not probe.state['writes'] and not probe.receipt.exists()

@pytest.mark.parametrize('change',['setup_index','setup_id','stock','extend','ops','dirty','stale'])
def test_precondition_failures_before_mutation(probe,change):
    s=probe.state['current'];extra={}
    if change=='setup_index':extra['setup_index']=1
    if change=='setup_id':extra['expected_setup_native_id']=43
    if change=='stock':s['stock']['type_raw']=1
    if change=='extend':s['extend_holes_to_stock']=True
    if change=='ops':s['operation_counts']=[0]
    if change=='dirty':s['document']['needs_save']=True
    if change=='stale':extra['expected_state_sha256']='0'*64
    out=probe.run(**extra);assert out['status']=='error' and not probe.state['writes']

@pytest.mark.parametrize('key,value',[('kind','boss'),('sketch_name',''),('depth_native',0),('depth_native',True),('expected_start_native',[0,0]),('expected_bounds_native',[2.7,2.7,2.])])
def test_invalid_spec_rejected_before_read(probe,key,value):
    with pytest.raises(ValueError):probe.run(feature_spec=probe.spec|{key:value})
    probe.snapshots.assert_not_called()

@pytest.mark.parametrize('field,value',[('axis_native',[-1.,0.,0.]),('subtype',1),('depth_native',1.7),('bounds_native',[2.7,2.7,1.7]),('start_native',[28.4,0,1.65]),('volume_type',2),('taper_angle_native',.1),('tip_angle_native',130.),('tip_angle_native',None),('suppressed',True)])
def test_native_feature_mismatch_stays_uncertain(probe,field,value):
    probe.state['on_write']=lambda:probe.state['current']['features'][-1].update({field:value})
    out=probe.run();assert out['status']=='uncertain' and not out['readback_verified']


def test_event_stops_before_id_or_readback(probe):
    probe.state['on_write']=lambda:probe.eventdata.update(event_count=1)
    out=probe.run();assert out['status']=='uncertain' and probe.snapshots.call_count==2
    probe.doc.GetCWObjectID.assert_not_called()

@pytest.mark.parametrize('change',['extra_feature','prior_sketch','extra_operation','file'])
def test_unexpected_secondary_changes(probe,change):
    def callback():
        s=probe.state['current']
        if change=='extra_feature':s['features'].append(s['features'][-1]|{'native_id':100})
        if change=='prior_sketch':s['sketch_sha256']='other'
        if change=='extra_operation':s['operation_counts']=[1]
        if change=='file':probe.path.write_bytes(b'changed')
    probe.state['on_write']=callback
    out=probe.run();assert out['status']=='uncertain' and not out['readback_verified']

@pytest.mark.parametrize('key,value',[('status','draft'),('interface','wrong'),('document_path','other'),('unit_record_raw','other'),('native_length_unit',''),('method',''),('observations',[])])
def test_unit_evidence_gate(probe,key,value):
    probe.units(**{key:value});other=probe.tmp_path/'invalid.json';other.write_bytes(probe.unitfile.read_bytes())
    out=probe.run(unit_evidence={'path':str(other),'sha256':cam._file_hash(other)})
    assert out['status']=='error' and not probe.state['writes']

@pytest.mark.parametrize('change',['event','file','document','disconnect'])
def test_cleanup_no_CAM_calls(probe,change):
    def callback():
        if change=='event':probe.eventdata['event_count']=1
        if change=='file':probe.path.write_bytes(b'changed')
        if change=='document':probe.state['current']['document']['title']='other'
        if change=='disconnect':probe.eventdata['disconnected']=False
    probe.state['on_exit']=callback
    out=probe.run();assert out['status']=='uncertain' and probe.snapshots.call_count==4 and not out['post_cleanup_CAM_getters']


@pytest.mark.parametrize('action',['inspect','prepare'])
def test_initial_read_is_subscribed_and_event_is_fail_stop(probe,action):
    original=probe.snapshots.side_effect
    def snapshot(*args,**kwargs):
        assert probe.eventdata['active'] and probe.eventdata['subscribed']
        result=original(*args,**kwargs)
        probe.eventdata['event_count']=1
        kwargs['check']()
        return result
    probe.snapshots.side_effect=snapshot
    extra={'machine_index':None} if action=='inspect' and hasattr(probe,'target') else {}
    out=probe.run(action,**extra)
    assert out['status']=='error' and not probe.state['writes']
    assert probe.snapshots.call_count==1 and out['messages']['disconnected']

@pytest.mark.parametrize('action',['inspect','prepare'])
def test_readonly_cleanup_file_change_is_detected(probe,action):
    probe.state['on_exit']=lambda:probe.path.write_bytes(b'changed during disconnect')
    extra={'machine_index':None} if action=='inspect' and hasattr(probe,'target') else {}
    out=probe.run(action,**extra)
    assert out['status']=='error' and not probe.state['writes']
    assert probe.snapshots.call_count==1


def test_hole_requires_tip_angle(probe):
    spec=probe.spec.copy();spec.pop('expected_tip_angle_native')
    with pytest.raises(ValueError,match='tip angle'):probe.run(feature_spec=spec)
    probe.snapshots.assert_not_called()

@pytest.mark.parametrize('value',[True,float('nan'),'180',None])
def test_invalid_tip_angle(probe,value):
    with pytest.raises(ValueError):probe.run(feature_spec=probe.spec|{'expected_tip_angle_native':value})

def test_open_pocket_rejects_tip_angle(probe):
    with pytest.raises(ValueError):cam._spec(probe.spec|{'kind':'open_pocket'})
    spec=probe.spec|{'kind':'open_pocket'};spec.pop('expected_tip_angle_native')
    assert 'expected_tip_angle_native' not in cam._spec(spec)

@pytest.mark.parametrize('volume',[1,6])
def test_feature_tip_read_only_on_hole(monkeypatch,volume):
    seen=[]
    native=object()
    monkeypatch.setattr(cam,'_typed',lambda raw,name,*args:seen.append(('QI',name)) or raw)
    monkeypatch.setattr(cam,'_object_id',lambda *args:4)
    fields={'Suppressed':False,'VolumeType':volume,'GetTipAngle':180.,'FeatureName':'hole','Axis':[1.,0.,0.],'SubType':0,'Depth':1.6,'GetBoundParams':[2.7,2.7,1.6],'GetStartPosition':[28.5,0.,1.2],'IGetTaperAngle':0.}
    def read(obj,name,*args):seen.append(('read',name));return fields[name]
    row=cam._feature(native,object(),'tlb',read)
    assert row['tip_angle_native']==(180. if volume==1 else None)
    assert (('QI','ICWMSHoleFeat') in seen)==(volume==1)
    assert (('read','GetTipAngle') in seen)==(volume==1)

def test_tip_reader_event_stops_remaining_getters(monkeypatch):
    monkeypatch.setattr(cam,'_typed',lambda raw,*args:raw)
    monkeypatch.setattr(cam,'_object_id',lambda *args:pytest.fail('ID read after event'))
    seen=[]
    def read(obj,name,*args):
        seen.append(name)
        if name=='GetTipAngle':raise ValueError('native event fail stop')
        return {'Suppressed':False,'VolumeType':1}[name]
    with pytest.raises(ValueError,match='event'):cam._feature(object(),object(),'tlb',read)
    assert seen==['Suppressed','VolumeType','GetTipAngle']
