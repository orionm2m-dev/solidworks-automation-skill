"""Closed circular MILL qualification mocks; no native application activation."""
from copy import deepcopy
from ctypes import POINTER,c_int,cast
from types import SimpleNamespace as N
from unittest.mock import Mock
import json, math
import pytest
import test_sw_cam_mill_units_qualification as legacy
from scripts import sw_cam_mill_units_qualification as cam
from scripts import sw_cam_comtypes as bridge

@pytest.fixture
def case(tmp_path,monkeypatch):
    monkeypatch.setattr(legacy,'cam',cam)
    c=legacy.case.__wrapped__(tmp_path,monkeypatch)
    c.base.update(feature_kind='circular_pocket',depth_native=4.1)
    spec=dict(plane_axis='Z',plane_offset_mm=10.9,sketch_name='CircleProfile',plane_name='CirclePlane',
              profile=dict(kind='circle',center_model_mm=[0.,0.,10.9],radius_mm=2.65))
    c.base['sketch_spec']=spec
    c.sketch.clear();c.sketch.update(entities=[dict(type='circle',center_model_m=[0.,0.,.0109],radius_m=.00265)],
        model_to_sketch_transform=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,-.0109,1.,0.,0.,0.])
    c.state.update(depth_scalar=4.1,separation=4.1,curve_type=2,rad=2.65,direction=1,
        axis=[0.,0.,1.],normal=[0.,0.,1.],center=[10.,20.,30.],arc_count=2)
    c.model.GetPathName=lambda:c.document['path']
    c.model.GetTitle=lambda:c.document['title']
    c.model.GetType=lambda:c.document['type']
    c.model.GetSaveFlag=lambda:c.document['needs_save']
    c.state['tree']=[dict(name='CircleProfile',type='ProfileFeature')]
    def circle_chain(label):
        def curve_at(index):
            assert type(index._obj) is c_int
            i=cast(index,POINTER(c_int)).contents.value
            c.indices.append((label,i))
            offset=c.state['separation'] if label=='bottom' else 0.
            center=list(c.state['center']);center[2]+=offset
            def pt(angle):return [center[0]+c.state['rad']*math.cos(angle),center[1]+c.state['rad']*math.sin(angle),center[2]]
            def position(value):return N(GetCoordinates=lambda:value)
            curve=N(GetTypeOfCurve=lambda:c.state['curve_type'],
                CenterPoint=lambda:position(center),GetRadius=lambda:c.state['rad'],
                IGetRadius=lambda:c.state['rad'],IGetNormal=lambda:position(c.state['normal']),
                GetDirection=lambda:c.state['direction'],IGetSense=lambda:c.state['direction'])
            count=c.state['arc_count']
            curve.GetStart=lambda:position(pt(i*2*math.pi/count))
            curve.GetEnd=lambda:position(pt((i+1)*2*math.pi/count))
            curve.GetMid=lambda:position(pt((i+.5)*2*math.pi/count))
            return curve
        return N(IGetNumChains=lambda:1,GetNumOfCurves=lambda:1 if c.state['curve_type']==2 else c.state['arc_count'],
                 GetCurveAtIndex=curve_at)
    c.feature.VolumeType=2
    c.feature.Axis=c.state['axis']
    c.feature.IGetTopSegChain=lambda:circle_chain('top')
    c.feature.IGetBottomSegChain=lambda:circle_chain('bottom')
    def creator(*args):
        durable=json.loads(c.receipt.read_text())
        assert durable['mutation_attempted'] and not durable['native_call_returned']
        assert args==(0,'CircleProfile',False,4.1,c.state.get('reverse',False),False,False,False,0.,-1,False,0,0)
        assert type(args[3]) is float
        c.state['writes'].append(args);c.state['features']=[c.feature];c.document['needs_save']=True
        if c.state['callbacks'].get('creator'):c.state['callbacks']['creator']()
        return c.state.get('creator_return',c.feature)
    c.setup.CreateMillFeature2.side_effect=creator
    typed=cam._typed
    snapshot=cam._mill_snapshot
    def full_snapshot(*args,**kwargs):
        state,native=snapshot(*args,**kwargs)
        state.update(mill_catalogue=[],extend_holes_to_stock=False,unit_record_raw=None,
                     unit_record_status='disabled')
        return state,native
    monkeypatch.setattr(cam,'_mill_snapshot',full_snapshot)
    c.qis=[]
    def track(raw,name,tlb):
        c.qis.append(name)
        return typed(raw,name,tlb)
    monkeypatch.setattr(cam,'_typed',track)
    return c

def test_circle_exact_double_creator_and_type_specific_readback(case):
    p=case.prepare()
    assert p['before']['feature_kind']=='circular_pocket' and not case.state['writes']
    out=case.run('apply',expected_state_sha256=p['state_sha256'],receipt_path=str(case.receipt))
    assert out['status']=='review_required',out
    assert out['readback_verified'] and out['creation_delta_verified'] and out['contour_readback_verified']
    assert out['observed_feature']['volume_type']==2
    assert out['dimensional_evidence']['depth_matches_requested_native']
    assert out['observed_native_units_per_mm']==pytest.approx(1)
    assert not out['physical_depth_verified'] and not out['absolute_native_frame_verified']
    assert 'ICWCircle' in case.qis and 'ICWArc' not in case.qis
    assert case.indices==[('top',0),('bottom',0)]
    assert json.loads(case.receipt.read_text())==out

def test_arc_chain_uses_only_arc_interface(case):
    case.state['curve_type']=1
    out=case.apply()
    assert out['status']=='review_required',out
    assert out['contour_readback_verified'] and 'ICWArc' in case.qis and 'ICWCircle' not in case.qis
    assert case.indices==[('top',0),('top',1),('bottom',0),('bottom',1)]

def test_coplanar_is_contour_readback_only(case):
    case.state['separation']=0.
    out=case.apply()
    assert out['status']=='review_required' and out['readback_verified']
    assert out['contour_readback_verified'] and not out['geometric_readback_verified']
    assert out['dimensional_evidence']['relation']=='coplanar'
    assert out['dimensional_evidence']['measured_separation_native']==0
    assert not out['physical_depth_verified'] and 'interpreted_depth_mm' not in out

@pytest.mark.parametrize('value',[True,False,None,'4.1',float('nan'),float('inf'),0,-1,101])
def test_invalid_depth_before_native(case,value):
    out=case.run(depth_native=value)
    assert out['status']=='error';cam._bootstrap.assert_not_called();case.setup.CreateMillFeature2.assert_not_called()

@pytest.mark.parametrize('key,value',[('type',True),('type',1.),('needs_save',None),('needs_save',0),('needs_save',1),('needs_save',0.)])
def test_raw_identity_strict_before_bootstrap(case,key,value):
    case.document[key]=value
    out=case.run()
    assert out['status']=='error';cam._bootstrap.assert_not_called()

@pytest.mark.parametrize('value',[True,1.,None,'1'])
def test_direction_integer_not_coerced(case,value):
    case.state['direction']=value
    out=case.apply()
    assert out['status']=='uncertain' and not out['readback_verified']
    assert 'IGetBottomSegChain' not in case.state['calls']

@pytest.mark.parametrize('value',[True,0,4,6,2.])
def test_volume_must_exact_pocket_before_contours(case,value):
    case.feature.VolumeType=value
    out=case.apply()
    assert out['status']=='uncertain'
    assert 'IGetTopSegChain' not in case.state['calls']

@pytest.mark.parametrize('value',[True,0,3,None,2.])
def test_curve_type_must_exact_circle_or_arc(case,value):
    case.state['curve_type']=value
    out=case.apply()
    assert out['status']=='uncertain' and 'ICWCircle' not in case.qis and 'ICWArc' not in case.qis

@pytest.mark.parametrize('name',['ICWBaseSetup','ICWSetup','ICWFeature','ICWMillFeature','ICWSegChain','ICWCurve','ICWCircle','ICWPosition','ICWUnitVector'])
def test_null_qi_stops_before_next_native_getter(case,monkeypatch,name):
    original=cam._typed
    monkeypatch.setattr(cam,'_typed',lambda raw,n,tlb:None if n==name else original(raw,n,tlb))
    out=case.run() if name=='ICWBaseSetup' else case.apply()
    assert out['status'] in ('error','uncertain') and not out['readback_verified']
    if name=='ICWSetup':case.setup.CreateMillFeature2.assert_not_called()
    if name=='ICWCircle':assert 'CenterPoint' not in case.state['calls']
    if name=='ICWPosition':assert 'GetCoordinates' not in case.state['calls']

@pytest.mark.parametrize('value',[None,False,True,0,1,'interface'])
def test_creator_primitive_return_never_followed_by_object_id(case,value):
    case.state['creator_return']=value
    out=case.apply()
    assert out['status']=='uncertain' and out['native_call_returned'] and not out['readback_verified']
    assert 'new_feature_native_id' not in out
    case.setup.CreateMillFeature2.assert_called_once()

def test_event_keeps_returned_radius_before_stop(case):
    case.state['callbacks']['GetRadius']=lambda:case.status.update(event_count=1)
    out=case.apply()
    assert out['status']=='uncertain' and out['last_native_read']['method']=='GetRadius'
    assert out['last_native_read']['returned'] and out['last_native_read']['value']==2.65
    assert not out['last_native_read']['validated']
    assert 'IGetNormal' not in case.state['calls']

def test_wrong_measured_depth_is_not_promoted(case):
    case.state['separation']=5.
    out=case.apply()
    assert out['status']=='uncertain' and out['native_feature_readback_complete']
    assert not out['readback_verified'] and not out['physical_depth_verified']

def test_circle_radius_not_request_echo(case):
    case.sketch['entities'][0]['radius_m']=.003
    out=case.run()
    assert out['status']=='error';case.setup.CreateMillFeature2.assert_not_called()

def test_normal_must_parallel_native_axis(case):
    case.state['normal']=[1.,0.,0.]
    out=case.apply()
    assert out['status']=='uncertain' and not out['readback_verified']

def test_new_feature_kind_is_pinned(case):
    p=case.prepare()
    changed=deepcopy(case.base['sketch_spec'])
    changed['profile']=dict(kind='closed_polyline',points_model_mm=[[0,0,10.9],[2,0,10.9],[2,3,10.9],[0,3,10.9]])
    out=case.run('apply',feature_kind='open_pocket',depth_native=3,sketch_spec=changed,
                 expected_state_sha256=p['state_sha256'],receipt_path=str(case.receipt))
    assert out['status']=='error' and not out['mutation_attempted']

def test_circle_iid_exact():
    assert bridge._INTERFACES['ICWCircle']=='{2C8A5929-BA50-47EE-9CCE-90F379C68F1C}'

def test_circle_process_identity_part_of_prepared_hash(case):
    before=case.prepare()
    case.state['pid']=732
    changed=case.run(process_id=732)
    assert changed['status']=='ok'
    assert changed['state_sha256']!=before['state_sha256']
    assert changed['before']['process_id']==732
    out=case.run('apply',process_id=732,expected_state_sha256=before['state_sha256'],receipt_path=str(case.receipt))
    assert out['status']=='error' and not out['mutation_attempted']
    case.setup.CreateMillFeature2.assert_not_called()
