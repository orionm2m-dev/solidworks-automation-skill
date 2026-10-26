from copy import deepcopy
import json
import pytest
from scripts import sw_cam_profile_sketch as m

def circle(axis='X',offset=28.5):
 c=[0.,0.,0.];c['XYZ'.index(axis)]=offset
 return dict(plane_axis=axis,plane_offset_mm=offset,sketch_name='CAM_PROFILE_01',plane_name='CAM_PLANE_01',profile=dict(kind='circle',center_model_mm=c,radius_mm=1.35))
def polygon():return dict(plane_axis='Z',plane_offset_mm=26.,sketch_name='CAM_FLAT',plane_name='CAM_FLAT_PLANE',profile=dict(kind='closed_polyline',points_model_mm=[[-20,30,26],[20,30,26],[20,35,26],[-20,35,26]]))
@pytest.mark.parametrize('axis',['X','Y','Z'])
@pytest.mark.parametrize('offset',[-58.,0.,28.5])
def test_cardinal_input(axis,offset):assert m._input(circle(axis,offset))['plane_offset_mm']==offset
@pytest.mark.parametrize('key,value',[('plane_axis','XY'),('plane_offset_mm',float('nan')),('plane_offset_mm',1001),('sketch_name','bad/name'),('plane_name','CAM_PROFILE_01'),('plane_offset_mm',True)])
def test_bad_spec(key,value):
 s=circle();s[key]=value
 with pytest.raises(ValueError):m._input(s)
@pytest.mark.parametrize('radius',[0,-1,True,float('inf'),501,.00001])
def test_bad_circle_radius(radius):
 s=circle();s['profile']['radius_mm']=radius
 with pytest.raises(ValueError):m._input(s)
def test_circle_not_on_plane():
 s=circle();s['profile']['center_model_mm'][0]+=1
 with pytest.raises(ValueError):m._input(s)
def test_polygon_valid():assert len(m._input(polygon())['profile']['points_model_mm'])==4
@pytest.mark.parametrize('points',[[[0,0,26],[1,1,26],[0,1,26],[1,0,26]],[[0,0,26],[1,0,26],[2,0,26]],[[0,0,26],[1,0,26],[0,0,26]],[[0,0,26],[1,0,26]]])
def test_bad_polygon(points):
 s=polygon();s['profile']['points_model_mm']=points
 with pytest.raises(ValueError):m._input(s)
def test_polygon_bound():
 s=polygon();s['profile']['points_model_mm']=[[i,i*i,26] for i in range(33)]
 with pytest.raises(ValueError):m._input(s)
def state(spec=None):
 return {'pid':100,'path':'part','saved_file_sha256':'a'*64,'needs_save':False,'features':[{'name':'OriginX','type':'RefPlane'}],'planes':[{'name':'OriginX','origin_m':[0,0,0],'normal':[1,0,0],'plane_to_model':[0]*16}],'solids':[{'box_m':[0]*6,'mass_raw':[1.,2.,3.,4.]}],'spec':spec or circle()}
def test_select_offset_plane():assert m._select_plane(state())[1] is True
def test_select_existing_plane():
 s=state(circle(offset=0));assert m._select_plane(s)[1] is False
def test_ambiguous_plane():
 s=state();s['planes']*=2
 with pytest.raises(ValueError):m._select_plane(s)
def test_exact_box_mass_policy():
 a=state()['solids'];b=deepcopy(a);b[0]['mass_raw'][0]+=1e-12
 assert m._same_bodies(a,b)
 b[0]['box_m'][0]+=1e-12
 assert not m._same_bodies(a,b)
def test_mass_change_blocked():
 a=state()['solids'];b=deepcopy(a);b[0]['mass_raw'][0]+=.01
 assert not m._same_bodies(a,b)
def test_saved_sha_in_digest():
 a=state();b=deepcopy(a);b['saved_file_sha256']='b'*64
 assert m._state_digest(a)!=m._state_digest(b)

@pytest.fixture
def env(monkeypatch,tmp_path):
 p=tmp_path/'part.SLDPRT';p.write_bytes(b'qualified copy')
 class C:
  def __enter__(self):return self
  def __exit__(self,*args):pass
 monkeypatch.setattr(m,'solidworks_operation_lock',lambda **kw:C())
 before=state();before['path']=str(p.resolve());before['saved_file_sha256']=m._sha(p)
 calls=[]
 def snap(sw,pid,path,spec):calls.append('snapshot');s=deepcopy(before);s['spec']=spec;return s,object(),[]
 monkeypatch.setattr(m,'_snapshot',snap)
 monkeypatch.setattr(m,'_identity',lambda *a:object())
 return p,before,calls,tmp_path

def args(p,action='prepare',**kw):return dict(expected_process_id=100,expected_document_path=str(p),action=action,spec=circle(),**kw)
def test_prepare_no_mutation(env,monkeypatch):
 p,b,c,t=env;monkeypatch.setattr(m,'_create',lambda *a:pytest.fail('creation forbidden'))
 r=m.create_cam_profile_sketch(object(),**args(p));assert r['status']=='ok' and r['prepared'] and not r['mutation_attempted']
@pytest.mark.parametrize('action',['inspect','prepare'])
def test_readonly_rejects_mutation_fields(env,action):
 p,*_=env;r=m.create_cam_profile_sketch(object(),**args(p,action,expected_state_sha256='a'*64));assert r['status']=='error'
def test_stale_hash_no_mutation(env,monkeypatch):
 p,b,c,t=env;monkeypatch.setattr(m,'_create',lambda *a:pytest.fail('creation forbidden'))
 r=m.create_cam_profile_sketch(object(),**args(p,'apply',expected_state_sha256='f'*64,receipt_path=str(t/'receipt.json')))
 assert r['status']=='error' and not r['mutation_attempted'] and not (t/'receipt.json').exists()
def test_existing_receipt_no_mutation(env):
 p,b,c,t=env;q=t/'receipt.json';q.write_text('old')
 r=m.create_cam_profile_sketch(object(),**args(p,'apply',expected_state_sha256=m._state_digest(b),receipt_path=str(q)))
 assert r['status']=='error' and not r['mutation_attempted'] and q.read_text()=='old'
def test_dirty_copy_blocked(env):
 p,b,c,t=env;b['needs_save']=True
 r=m.create_cam_profile_sketch(object(),**args(p));assert r['status']=='error'
def test_existing_feature_name(env):
 p,b,c,t=env;b['features'].append({'name':'cam_profile_01','type':'ProfileFeature'})
 r=m.create_cam_profile_sketch(object(),**args(p));assert r['status']=='error'
@pytest.mark.parametrize('pid',[True,0,-1,'100'])
def test_bad_pid(env,pid):
 p,*_=env;a=args(p);a['expected_process_id']=pid
 assert m.create_cam_profile_sketch(object(),**a)['status']=='error'
@pytest.mark.parametrize('failure',['body','old_feature','file','dirty_flag','create_error'])
def test_apply_failure_uncertain_no_save(env,monkeypatch,failure):
 p,b,c,t=env
 def creator(sw,model,before,refs,check,report):
  check()
  if failure=='create_error':raise RuntimeError('native failed')
  b['features'] += [{'name':'CAM_PLANE_01','type':'RefPlane'},{'name':'CAM_PROFILE_01','type':'ProfileFeature'}];b['needs_save']=True
  if failure=='body':b['solids'][0]['mass_raw'][0]+=.1
  if failure=='old_feature':b['features'][0]['name']='Changed'
  if failure=='file':p.write_bytes(b'other file')
  if failure=='dirty_flag':b['needs_save']=False
  return ['CAM_PLANE_01','CAM_PROFILE_01']
 monkeypatch.setattr(m,'_create',creator)
 r=m.create_cam_profile_sketch(object(),**args(p,'apply',expected_state_sha256=m._state_digest(b),receipt_path=str(t/'receipt.json')))
 assert r['status']=='uncertain' and r['mutation_attempted'] and not r['saved'] and not r['native_readback_verified']
 assert json.loads((t/'receipt.json').read_text())['status']=='uncertain'
def test_apply_success_no_save(env,monkeypatch):
 p,b,c,t=env
 def creator(sw,model,before,refs,check,report):
  check();b['features'] += [{'name':'CAM_PLANE_01','type':'RefPlane'},{'name':'CAM_PROFILE_01','type':'ProfileFeature'}];b['needs_save']=True
  return ['CAM_PLANE_01','CAM_PROFILE_01']
 monkeypatch.setattr(m,'_create',creator)
 r=m.create_cam_profile_sketch(object(),**args(p,'apply',expected_state_sha256=m._state_digest(b),receipt_path=str(t/'receipt.json')))
 assert r['status']=='ok' and r['native_readback_verified'] and not r['saved'] and r['CAM_calls']==0
 assert p.read_bytes()==b'qualified copy'

def test_real_identity_pid_mismatch(monkeypatch):
 monkeypatch.setattr(m,'call',lambda obj,name,*args:101)
 with pytest.raises(ValueError,match='PID'):m._identity(object(),100,'part')

def test_no_forbidden_native_operations_in_core():
 import inspect
 source=inspect.getsource(m)
 for name in ['FeatureExtrusion','SaveAs','Save3','GenerateToolpath','GetUnitRecordParam','GetCWApp','DeleteSelection','EditUndo']:
  assert name not in source

# Native method-flow tests use explicit fake geometries; no SW/COM is instantiated.
from types import SimpleNamespace
class Transform:
 def __init__(self,axis,offset,inverse=False,scale=1.):self.axis=axis;self.offset=offset;self.inv=inverse;self.scale=scale
 @property
 def ArrayData(self):return [1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,self.scale,0.,0.,0.]
 def Inverse(self):return Transform(self.axis,self.offset,not self.inv,self.scale)
 def point(self,p):
  i=self.axis;u=(i+1)%3;v=(i+2)%3
  if not self.inv:return [p[u],p[v],p[i]-self.offset]
  out=[0.,0.,0.];out[u]=p[0];out[v]=p[1];out[i]=p[2]+self.offset;return out
class NativeSegment:
 def __init__(self,kind,a,b=None,r=None):self.kind=kind;self.a=a;self.b=b;self.r=r;self.ConstructionGeometry=False
 def GetType(self):return self.kind
 def IsCircle(self):return self.kind==1
 def GetCenterPoint2(self):return SimpleNamespace(X=self.a[0],Y=self.a[1],Z=self.a[2])
 def GetRadius(self):return self.r
 def GetStartPoint2(self):return SimpleNamespace(X=self.a[0],Y=self.a[1],Z=self.a[2])
 def GetEndPoint2(self):return SimpleNamespace(X=self.b[0],Y=self.b[1],Z=self.b[2])
class NativeSketch:
 def __init__(self,t):self.ModelToSketchTransform=t;self.segments=[]
 def Is3D(self):return False
 def GetSketchSegments(self):return self.segments
class NativeFeature:
 def __init__(self,model,name,kind,obj):self.model=model;self.Name=name;self.kind=kind;self.obj=obj
 def GetTypeName2(self):return self.kind
 def GetSpecificFeature2(self):return self.obj
 def Select2(self,append,mark):assert append is False and mark==0;self.model.selected=self;return True
class NativeManager:
 def __init__(self,model):self.model=model;self.ActiveSketch=None;self.AddToDB=False;self.calls=[]
 def InsertSketch(self,rebuild):
  if self.ActiveSketch is not None:self.ActiveSketch=None;self.calls.append('exit');return
  t=self.model.selected.obj.Transform.Inverse();self.ActiveSketch=NativeSketch(t)
  self.model.features.append(NativeFeature(self.model,'SketchNew','ProfileFeature',self.ActiveSketch));self.calls.append('enter')
 def CreateCircleByRadius(self,x,y,z,r):
  self.calls.append(('circle',x,y,z,r));seg=NativeSegment(1,[x,y,z],r=r);self.ActiveSketch.segments.append(seg);return seg
 def CreateLine(self,*p):
  self.calls.append(('line',*p));seg=NativeSegment(0,list(p[:3]),list(p[3:]));self.ActiveSketch.segments.append(seg);return seg
class NativeModel:
 def __init__(self,axis):
  self.features=[];self.selected=None;self.axis=axis;self.SketchManager=NativeManager(self);self.FeatureManager=self
  self.features.append(NativeFeature(self,'OriginX','RefPlane',SimpleNamespace(Transform=Transform(axis,0,True))))
 def ClearSelection2(self,value):self.selected=None
 def InsertRefPlane(self,c,d,c2,d2,c3,d3):
  assert (c2,d2,c3,d3)==(0,0.,0,0.)
  assert c in (8,264)
  o=SimpleNamespace(Transform=Transform(self.axis,-d if c&256 else d,True))
  self.features.append(NativeFeature(self,'PlaneNew','RefPlane',o));return o
class NativeSW:
 def GetMathUtility(self):return object()
 def IsSame(self,a,b):return 1 if a is b else 0
@pytest.fixture
def native(monkeypatch):
 monkeypatch.setattr(m,'_point',lambda mu,p,t:t.point(p))
 monkeypatch.setattr(m,'_typed_segment',lambda seg,kind:seg)
 monkeypatch.setattr(m,'_features',lambda model:([{'name':f.Name,'type':f.kind} for f in model.features],model.features[:]))
 return NativeSW()
@pytest.mark.parametrize('axis',['X','Y','Z'])
@pytest.mark.parametrize('offset',[-28.5,0.,28.5])
def test_real_creator_circle_cardinal_and_offset(native,axis,offset):
 s=state(circle(axis,offset));idx='XYZ'.index(axis);s['planes'][0]['normal']=[1. if i==idx else 0. for i in range(3)]
 model=NativeModel(idx);report={};checks=[]
 added=m._create(native,model,s,model.features[:],lambda:checks.append(True),report)
 assert added==(['CAM_PLANE_01'] if offset else [])+['CAM_PROFILE_01']
 assert report['sketch_edit_exited'] and model.SketchManager.AddToDB is False
 assert report['sketch_readback']['entities']==[{'type':'circle','center_model_m':[v/1000 for v in s['spec']['profile']['center_model_mm']],'radius_m':.00135}]
 assert len(checks)>10
 if offset:assert report['created_plane']['origin_m'][idx]==offset/1000

def test_real_creator_closed_polyline(native):
 s=state(polygon());s['planes'][0]['normal']=[0,0,1];model=NativeModel(2);report={}
 m._create(native,model,s,model.features[:],lambda:None,report)
 assert len(report['sketch_readback']['entities'])==4 and report['sketch_edit_exited']
 assert all(x['type']=='line' for x in report['sketch_readback']['entities'])
 assert len([x for x in model.SketchManager.calls if isinstance(x,tuple) and x[0]=='line'])==4
@pytest.mark.parametrize('fault',['radius','center','construction','kind','count','scale'])
def test_real_circle_readback_rejects_wrong_geometry(native,fault):
 s=circle('Z',0);sk=NativeSketch(Transform(2,0));seg=NativeSegment(1,[0,0,0],r=.00135);sk.segments=[seg]
 if fault=='radius':seg.r=.0013
 if fault=='center':seg.a=[.001,0,0]
 if fault=='construction':seg.ConstructionGeometry=True
 if fault=='kind':seg.kind=0
 if fault=='count':sk.segments*=2
 if fault=='scale':sk.ModelToSketchTransform.scale=2
 with pytest.raises(ValueError):m._read_sketch(native,sk,s)

def test_real_create_failure_exits_own_sketch(native,monkeypatch):
 s=state(circle('X',0));model=NativeModel(0);report={}
 def fail(*args):raise RuntimeError('native creator failed')
 monkeypatch.setattr(model.SketchManager,'CreateCircleByRadius',fail)
 with pytest.raises(RuntimeError):m._create(native,model,s,model.features[:],lambda:None,report)
 assert report['sketch_edit_exited'] and model.SketchManager.ActiveSketch is None and model.SketchManager.AddToDB is False

def test_real_polyline_reader_allows_native_order_and_reversal(native):
 spec=polygon();sk=NativeSketch(Transform(2,.026));pts=[sk.ModelToSketchTransform.point([v/1000 for v in p]) for p in spec['profile']['points_model_mm']]
 sk.segments=[NativeSegment(0,b,a) for a,b in zip(pts,pts[1:]+pts[:1])][::-1]
 assert len(m._read_sketch(native,sk,spec)['entities'])==4

def test_transform_nonorthonormal_rejected():
 t=SimpleNamespace(ArrayData=[2.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.])
 with pytest.raises(ValueError,match='orthonormal'):m._rigid_transform(t)

@pytest.mark.parametrize('fail_after_mutation',[False,True])
def test_receipt_finalize_error_returns_structured_uncertain(env,monkeypatch,fail_after_mutation):
 p,b,c,t=env;count=[0]
 original=m._write_receipt
 def writer(path,report,create=False):
  count[0]+=1
  if not create and (not fail_after_mutation or count[0]>=3):raise OSError('receipt storage unavailable')
  return original(path,report,create=create)
 monkeypatch.setattr(m,'_write_receipt',writer)
 def creator(sw,model,before,refs,check,report):
  b['features'] += [{'name':'CAM_PLANE_01','type':'RefPlane'},{'name':'CAM_PROFILE_01','type':'ProfileFeature'}];b['needs_save']=True
  return ['CAM_PLANE_01','CAM_PROFILE_01']
 monkeypatch.setattr(m,'_create',creator)
 out=m.create_cam_profile_sketch(object(),**args(p,'apply',expected_state_sha256=m._state_digest(b),receipt_path=str(t/'receipt.json')))
 assert out['status']=='uncertain' and not out['native_readback_verified'] and out['receipt_write_error']['type']=='OSError'
 assert not out['saved']
