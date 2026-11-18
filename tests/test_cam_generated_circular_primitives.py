from copy import deepcopy
from types import SimpleNamespace
import pytest
from scripts import sw_cam_circular_reconfigure as m


def read(obj,name,*args):
    value=getattr(obj,name);return value(*args) if callable(value) else value


@pytest.mark.parametrize('field',[*m.ROUGH_ORDER,*m.NC_ORDER])
def test_actual_adapter_calls_fixed_primitive_once_after_pending(monkeypatch,field):
    kind='rough' if field in m.ROUGH_ORDER else 'nc';trace=[];values={'first_depth':[False,.3],'subsequent_depth':[False,.3],'spiral_pitch':.1,'LinkToTool':True,'GetSpndlSpeed':200.,'XYFeed':1000.,'leadin_feed':dict(value_native=2.,is_percent=False,physical_units_verified=False)}
    new={'first_depth':[False,7.4],'subsequent_depth':[False,7.4],'spiral_pitch':.6,'LinkToTool':False,'GetSpndlSpeed':2000.,'XYFeed':150.,'leadin_feed':dict(value_native=75.,is_percent=False,physical_units_verified=False)}[field]
    change=dict(field=field,expected=deepcopy(values[field]),new=new)
    feature=SimpleNamespace(QueryInterface=lambda cls:'IDISPATCH_FEATURE');doc=SimpleNamespace(GetCWObjectFromID=lambda *a:(feature,True));owner=SimpleNamespace();mill=SimpleNamespace(IGetNCParam=lambda:owner)
    def write(key,*args):
        assert trace[-1]=='pending';trace.append(('native',key,args))
        if key=='spiral_pitch':assert args[0]=='IDISPATCH_FEATURE';values[key]=args[1]
        elif key in ('first_depth','subsequent_depth'):values[key]=list(args)
        elif key=='leadin_feed':values[key]=dict(value_native=args[0],is_percent=args[1],physical_units_verified=False)
        else:values[key]=args[0]
        return 0
    for key in m.ROUGH_ORDER:
        spec=m.fields.FIELDS[key];setattr(owner,spec.getter,lambda *a,k=key:tuple(values[k]) if type(values[k]) is list else values[k]);setattr(owner,spec.setter,lambda *a,k=key:write(k,*a))
    owner.GetSpndlSpeed=lambda:values['GetSpndlSpeed'];owner.SetSpndlSpeed=lambda v:write('GetSpndlSpeed',v)
    owner.LinkToTool=True;owner.XYFeed=1000.
    setattr(owner,'_ICWNCParam4__com__set_LinkToTool',lambda v:write('LinkToTool',v));setattr(owner,'_ICWNCParam2__com__set_XYFeed',lambda v:write('XYFeed',v));setattr(owner,'_ICWNCParam__com_SetLeadinFeedrate',lambda a,b:write('leadin_feed',a,b))
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        read=staticmethod(read)
        def typed(self,obj,name):return owner
        def _observe(self,call):return call()
        def dispatch_once(self,call,*,persist_pending):persist_pending();return call()
    ctx=m.RevisionContext.__new__(m.RevisionContext);ctx.guard=lambda:Guard();ctx._target=lambda *a:(owner,mill);ctx._typed_nc4=lambda *a:owner;ctx.native={'doc':doc};ctx.recipe={'feature_native_id':359};ctx.read=read;ctx.typed=lambda *a:owner;ctx.report={};ctx.persist=lambda:None;ctx.boundary=lambda:None;ctx.read_cutting=lambda:dict(nc=deepcopy(values))
    monkeypatch.setattr(m,'_member',read);monkeypatch.setattr(m.nc_read,'lead_pointer_value',lambda *a:deepcopy(values['leadin_feed']))
    observed=ctx.set_change(kind,change,pending=lambda:trace.append('pending'),returned=lambda value:trace.append(('returned',value)))
    assert observed==new and trace[0]=='pending' and trace[-1]==('returned',0)
    assert len([v for v in trace if isinstance(v,tuple) and v[0]=='native'])==1


@pytest.mark.parametrize('cached_generated',[True,False])
def test_generated_status_is_observed_for_capture_not_used_as_generation_proof(monkeypatch,cached_generated):
    ctx=m.RevisionContext.__new__(m.RevisionContext);ctx.native={'doc':object()};ctx.oid=361;ctx.report={};ctx.persist=lambda:None;ctx.read=lambda *a:cached_generated;ctx.typed=lambda *a:None;ctx._target=lambda *a:(object(),object());ctx.read_cutting=lambda:{'nc':{},'local_planes':{}}
    seen=[]
    def base(self,label,partial):seen.append(list(self.attempted));return {'test':True}
    monkeypatch.setattr(m.CircularGenerationContext,'capture',base);partial={};result=ctx.capture('test',partial)
    assert seen==[[361] if cached_generated else []] and partial==result
