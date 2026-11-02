from copy import deepcopy
import importlib.util
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from cam_optional_test_evidence import evidence_root, required_evidence
from scripts import sw_cam_mixed_profile as m
from scripts import sw_cam_mixed_profile_sketch as a


def arc(center,r,start,sweep):
    def point(t):return [center[0]+r*math.cos(t),center[1]+r*math.sin(t),center[2]]
    return dict(kind='arc',start_model_mm=point(start),end_model_mm=point(start+sweep),mid_model_mm=point(start+sweep/2),center_model_mm=center,radius_mm=r,sweep_radians=sweep)


def sample():
    curves=[arc([0.,0.,10.9],1.,0.,math.pi/2)]
    x=curves[0]['end_model_mm'];y=[0.,0.,10.9];z=curves[0]['start_model_mm']
    for p,q in ((x,y),(y,z)):
        curves.append(dict(kind='line',start_model_mm=p,end_model_mm=q,mid_model_mm=[(u+v)/2 for u,v in zip(p,q)]))
    return dict(plane_axis='Z',plane_offset_mm=10.9,sketch_name='RootProfile',plane_name='RootPlane',profile={'kind':'closed_mixed','segments':curves})


def rows(spec):
    result=[]
    for s in spec['profile']['segments']:
        r={'type':s['kind'],'points_model_m':[[v/1000 for v in s[k]] for k in ('start_model_mm','end_model_mm')],'mid_model_m':[v/1000 for v in s['mid_model_mm']],'length_m':m.length(s)/1000}
        if s['kind']=='arc':r.update(center_model_m=[v/1000 for v in s['center_model_mm']],radius_m=s['radius_mm']/1000)
        result.append(r)
    return result


@pytest.fixture(scope='session')
def actual():
    root=evidence_root('SW_CAM_MIXED_ROOT_EVIDENCE_ROOT')
    return json.loads(required_evidence(root,'EXPECTED_NATIVE_SKETCH_SPECS.json').read_text(encoding='utf-8-sig'))['specifications']


def test_actual_profiles(actual):
    assert [len(a._input(s)['profile']['segments']) for s in actual]==[13,13]
    assert min(m.length(x) for s in actual for x in s['profile']['segments'])>.018


@pytest.mark.parametrize('side',[0,1])
def test_actual_full_readback_projection(actual,side):
    spec=a._input(actual[side]);r=rows(spec)
    for item in r:item['points_model_m'].reverse()
    assert len(m.match_rows(spec['profile']['segments'],r[::-1],1e-8))==13


def test_valid():assert len(a._input(sample())['profile']['segments'])==3


@pytest.mark.parametrize('fault',['sweep','midpoint','center','radius','closure','nan','bool','plane','axis','unknown','tiny','fullcircle','count','duplicate'])
def test_invalid_input(fault):
    s=sample();p=s['profile'];q=p['segments'][0]
    if fault=='sweep':q['sweep_radians']*=-1
    if fault=='midpoint':q['mid_model_mm'][0]+=.01
    if fault=='center':q['center_model_mm'][0]+=.1
    if fault=='radius':q['radius_mm']+=.01
    if fault=='closure':p['segments'][1]['start_model_mm']=[0,1.1,10.9]
    if fault=='nan':q['radius_mm']=float('nan')
    if fault=='bool':q['radius_mm']=True
    if fault=='plane':q['mid_model_mm'][2]+=1
    if fault=='axis':s['plane_axis']='X'
    if fault=='unknown':q['direction']=1
    if fault=='tiny':q['sweep_radians']=1e-8
    if fault=='fullcircle':q['sweep_radians']=2*math.pi
    if fault=='count':p['segments']*=11
    if fault=='duplicate':p['segments']=p['segments']*2
    with pytest.raises(ValueError):a._input(s)


@pytest.mark.parametrize('fault',['midpoint','center','radius','length','complement','nan','type','extra','missing','tolerance'])
def test_native_geometry_faults(fault):
    s=sample();r=rows(s);tol=1e-8
    if fault=='midpoint':r[0]['mid_model_m'][0]*=-1
    if fault=='center':r[0]['center_model_m'][0]+=.0001
    if fault=='radius':r[0]['radius_m']+=.0001
    if fault=='length':r[0]['length_m']+=.0001
    if fault=='complement':r[0]['length_m']=.001*3*math.pi/2
    if fault=='nan':r[0]['radius_m']=float('nan')
    if fault=='type':r[0]['type']='line'
    if fault=='extra':r.append(r[0])
    if fault=='missing':r.pop()
    if fault=='tolerance':tol=1e-7
    with pytest.raises(ValueError):m.match_rows(s['profile']['segments'],r,tol)


def test_short_same_circle_overlap():
    p=arc([0,0,0],1,0,.8);q=arc([0,0,0],1,.799,.1)
    with pytest.raises(ValueError,match='overlapping'):m.intersections(p,q,1e-5)


def test_wrap_same_circle_overlap():
    p=arc([0,0,0],1,6.2,.2);q=arc([0,0,0],1,0,.02)
    with pytest.raises(ValueError,match='overlapping'):m.intersections(p,q,1e-5)


def test_nonadjacent_line_touch():
    p=dict(kind='line',start_model_mm=[0,0,0],end_model_mm=[1,0,0])
    q=dict(kind='line',start_model_mm=[1,0,0],end_model_mm=[2,0,0])
    assert m.intersections(p,q,1e-5)==[[1.,0.]]


def test_creator_uses_only_three_point_arc_and_line():
    calls=[]
    m.create_segments(object(),sample()['profile'],local=lambda p:[v/1000 for v in p],mutate=lambda obj,name,*args:calls.append((name,args)) or object())
    assert [x[0] for x in calls]==['Create3PointArc','CreateLine','CreateLine']
    assert calls[0][1][6:]==tuple(v/1000 for v in sample()['profile']['segments'][0]['mid_model_mm'])


def test_null_creator_stops_no_replay():
    calls=[]
    def fail(obj,name,*args):calls.append(name);return None
    with pytest.raises(ValueError):m.create_segments(object(),sample()['profile'],local=lambda x:x,mutate=fail)
    assert calls==['Create3PointArc']


@pytest.fixture(scope='module')
def legacy():
    root=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]))
    path=root/'tests/test_sw_cam_profile_sketch.py'
    if not path.is_file():raise RuntimeError('Required public profile test fixture is missing')
    spec=importlib.util.spec_from_file_location('mixed_legacy_fixtures',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


class Curve:
    def __init__(self,segment):self.s=segment
    def GetEndParams(self,low,high,closed,periodic):
        low.value=0.;high.value=abs(self.s.sweep);closed.value=False;periodic.value=True;return True
    def Evaluate2(self,t,derivatives):
        assert derivatives==0
        angle=self.s.angle+t*(1 if self.s.sweep>0 else -1)
        return [self.s.center[0]+self.s.r*math.cos(angle),self.s.center[1]+self.s.r*math.sin(angle),self.s.center[2]]


class Arc:
    ConstructionGeometry=False
    def __init__(self,start,end,mid):
        self.start,self.end=start,end
        x,y,z=start;u,v,_=end;p,q,_=mid;den=2*(x*(v-q)+u*(q-y)+p*(y-v))
        self.center=[((x*x+y*y)*(v-q)+(u*u+v*v)*(q-y)+(p*p+q*q)*(y-v))/den,((x*x+y*y)*(p-u)+(u*u+v*v)*(x-p)+(p*p+q*q)*(u-x))/den,z]
        self.r=math.dist(start,self.center);self.angle=math.atan2(y-self.center[1],x-self.center[0])
        endangle=math.atan2(v-self.center[1],u-self.center[0]);midangle=math.atan2(q-self.center[1],p-self.center[0]);ccw=(endangle-self.angle)%(2*math.pi)
        self.sweep=ccw if (midangle-self.angle)%(2*math.pi)<ccw else ccw-2*math.pi
    def GetType(self):return 1
    def IsCircle(self):return 0
    def GetCenterPoint2(self):return SimpleNamespace(**dict(zip('XYZ',self.center)))
    def GetStartPoint2(self):return SimpleNamespace(**dict(zip('XYZ',self.start)))
    def GetEndPoint2(self):return SimpleNamespace(**dict(zip('XYZ',self.end)))
    def GetRadius(self):return self.r
    def GetLength(self):return abs(self.sweep)*self.r
    def GetCurve(self):return Curve(self)


@pytest.fixture
def native(legacy,monkeypatch):
    monkeypatch.setattr(a,'_point',lambda mu,p,t:t.point(p))
    monkeypatch.setattr(a.core,'_point',lambda mu,p,t:t.point(p))
    monkeypatch.setattr(a.core,'_typed_segment',lambda seg,kind:seg)
    monkeypatch.setattr(a,'_features',lambda model:([{'name':f.Name,'type':f.kind} for f in model.features],model.features[:]))
    monkeypatch.setattr(legacy.NativeSegment,'GetLength',lambda self:math.dist(self.a,self.b),raising=False)
    def create(manager,*xyz):
        manager.calls.append(('arc3',*xyz));seg=Arc(list(xyz[:3]),list(xyz[3:6]),list(xyz[6:]));manager.ActiveSketch.segments.append(seg);return seg
    monkeypatch.setattr(legacy.NativeManager,'Create3PointArc',create,raising=False)
    return legacy.NativeSW(),legacy.NativeModel(2)


@pytest.mark.parametrize('which',['simple',0,1])
def test_shared_creator_full_curve_readback(native,legacy,actual,which):
    sw,model=native;s=sample() if which=='simple' else actual[which]
    state=legacy.state(a._input(s));state['planes'][0]['normal']=[0,0,1]
    report={};added=a._create(sw,model,state,model.features[:],lambda:None,report)
    assert added==[s['plane_name'],s['sketch_name']]
    assert report['sketch_readback']['arc_interval_midpoint_verified']
    assert report['sketch_readback']['native_rotation_direction_assumed'] is False
    assert len(report['sketch_readback']['entities'])==len(s['profile']['segments'])
    assert report['sketch_edit_exited'] and model.SketchManager.ActiveSketch is None and model.SketchManager.AddToDB is False


@pytest.mark.parametrize('fault',['closed','false_return','reversed','nonfinite','midpoint','endpoint'])
def test_native_interval_faults_cleanup(native,legacy,monkeypatch,fault):
    sw,model=native;s=sample();state=legacy.state(a._input(s));state['planes'][0]['normal']=[0,0,1]
    original=Curve.GetEndParams;evaluate=Curve.Evaluate2
    if fault in ('closed','false_return','reversed','nonfinite'):
        def broken(self,lo,hi,closed,periodic):
            original(self,lo,hi,closed,periodic)
            if fault=='closed':closed.value=True
            if fault=='reversed':hi.value=-1.
            if fault=='nonfinite':hi.value=float('nan')
            return False if fault=='false_return' else True
        monkeypatch.setattr(Curve,'GetEndParams',broken)
    else:
        def badpoint(self,t,n):
            p=evaluate(self,t,n)
            if (fault=='midpoint' and t>0 and t<abs(self.s.sweep)) or (fault=='endpoint' and t==0):p[0]+=.0001
            return p
        monkeypatch.setattr(Curve,'Evaluate2',badpoint)
    report={}
    with pytest.raises(ValueError):a._create(sw,model,state,model.features[:],lambda:None,report)
    assert report['sketch_edit_exited'] and model.SketchManager.ActiveSketch is None
    assert model.SketchManager.AddToDB is False