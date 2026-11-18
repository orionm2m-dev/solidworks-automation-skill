"""Actual read_header selection plumbing with interface-sensitive fake objects."""
import importlib,os,sys
from pathlib import Path
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE));sys.path.insert(0,str(RUNTIME))
import scripts
if str(STAGE/'scripts')not in scripts.__path__:scripts.__path__.insert(0,str(STAGE/'scripts'))
core=importlib.import_module('scripts.sw_cam_autodetected_pocket_recovery')
class Obj:
    def __init__(self,name,oid=0):self.name,self.oid=name,oid
class View:
    def __init__(self,obj,iid):self.obj,self.iid=obj,iid
class Graph:
    def __init__(self,setup_id=501,feature_id=502):
        self.app=Obj('app');self.doc=Obj('doc');self.machine=Obj('machine');self.setup=Obj('setup',setup_id);self.feature=Obj('feature',feature_id)
        self.setups=Obj('setups');self.features=Obj('features');self.trace=[];self.boundaries=0
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def typed(self,obj,iid):
        raw=obj.obj if isinstance(obj,View)else obj;self.trace.append(('typed',raw.name,iid));return View(raw,iid)
    def read(self,obj,name,*args):
        raw=obj.obj if isinstance(obj,View)else obj;iid=obj.iid if isinstance(obj,View)else None;self.trace.append(('read',raw.name,iid,name))
        if name=='IGetActiveDoc'and raw is self.app:return self.doc
        if name=='IGetMachine'and iid=='ICWPartDoc':return self.machine
        if name=='IGetEnumSetups'and iid=='ICWMachine':return self.setups
        if name=='GetCWObjectID'and iid=='ICWDoc3':
            target=args[0].obj if isinstance(args[0],View)else args[0];return target.oid,True
        if name=='Count'and iid=='ICWDispatchCollection':return 1
        if name=='Item'and iid=='ICWDispatchCollection':
            assert args==(0,);return self.setup if raw is self.setups else self.feature
        if name=='IGetEnumFeatures':
            if iid!='ICWBaseSetup':raise AttributeError('IGetEnumFeatures belongs to ICWBaseSetup')
            assert raw is self.setup;return self.features
        if iid=='ICWFeature':
            return {'GetOwner':self.setup,'Suppressed':False,'Axis':(0.,0.,-1.)}[name]
        if iid=='ICWMillFeature':return {'VolumeType':2,'IGetIslandCount':4,'Depth':13.2,'IGetTaperAngle':0.}[name]
        raise AssertionError(('unqualified member',raw.name,iid,name))
    def _boundary(self):self.boundaries+=1

def context(graph):
    c=object.__new__(core.ReadContext);c.app=graph.app;c.v=dict(owner_setup_native_id=501);c.data=dict(header=dict(native_id=502));c.r={};c.persist=lambda:None;c.guard=lambda:graph;return c

def test_real_read_header_selects_base_setup_and_returns_header():
    g=Graph();c=context(g);r=c.read_header('header')
    assert r==dict(native_id=502,owner_setup_native_id=501,suppressed=False,axis_native=[0.,0.,-1.],volume_type=2,island_count=4,depth_native=13.2,taper_angle_native=0.)
    assert ('read','setup','ICWBaseSetup','IGetEnumFeatures')in g.trace
    assert not any(x[0]=='typed'and x[2]=='ICWSetup'for x in g.trace)
    assert g.boundaries==1 and c.r['header']==r

@pytest.mark.parametrize('where',['setup','feature'])
def test_selection_stops_on_wrong_native_identity(where):
    g=Graph(setup_id=999 if where=='setup' else 501,feature_id=999 if where=='feature' else 502)
    with pytest.raises(ValueError):context(g).read_header('header')
    assert not any(x[0]=='read'and x[-1]in('Depth','IGetIslandCount','IGetTaperAngle')for x in g.trace)
    if where=='setup':assert not any(x[0]=='read'and x[-1]=='IGetEnumFeatures'for x in g.trace)

def test_actual_public_base_setup_enumeration_abi():
    tlb=os.environ.get('SWMCP_CAM_TYPELIB_PATH')
    if not tlb:pytest.skip('Set SWMCP_CAM_TYPELIB_PATH for installed metadata')
    r=core.preflight(tlb)
    assert r['feature_enumeration_owner']=='ICWBaseSetup'and r['feature_enumeration_dispid']==1 and r['application_calls']==0
