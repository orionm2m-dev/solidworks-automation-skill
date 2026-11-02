from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import pytest
from cam_public_test_support import add_runtime, required_module
R=add_runtime()
m=required_module('sw_cam_root_microtool_nc')
P=Path(m.__file__)


def fixture():
    tool=dict(native_id=1000,is_mill_tool=True,native_read_complete=True,units_verified=False,holder_geometry_verified=False,tool_type_raw=1,cut_diameter_native=.8,protrusion_native=19.)
    targets=[dict(operation_native_id=2000+i,feature_native_id=100+i//2,operation_setup_native_id=69,operation_type=i%2,assigned_tool=deepcopy(tool))for i in range(4)]
    scope=dict(source_sha256='a'*64,process_id=123,protected_operation_ids=list(range(1,18)),targets=targets,tool=tool)
    b=SimpleNamespace(args=dict(expected_source_sha256='a'*64,process_id=123),loaded=dict(configuration_tool=deepcopy(tool),generated_pin={}))
    return b,targets[0],scope


def nc():return dict(GetTlpComp=1,GetCNCComp=0,GetSpndlSpeed=4000.,GetRetractType=0,XYFeed=500.)


def test_exact_learned_scope_and_final_raw_only():
    b,t,s=fixture();assert m.validate_scope(b,t,s)is t
    result=m.verify_final(dict(nc(),GetSpndlSpeed=7100.,XYFeed=35.))
    assert result['raw_NC_recipe_verified'] and not result['feed_units_verified'] and not result['spindle_units_verified'] and not result['production_qualified']

@pytest.mark.parametrize('fault',['pid','source','protected','duplicate','feature','setup','kind','tool','diameter','length','target'])
def test_scope_drift_is_rejected(fault):
    b,t,s=fixture()
    if fault=='pid':s['process_id']=124
    elif fault=='source':s['source_sha256']='b'*64
    elif fault=='protected':s['protected_operation_ids'][0]=2000
    elif fault=='duplicate':s['targets'][1]['operation_native_id']=2000
    elif fault=='feature':s['targets'][2]['feature_native_id']=999
    elif fault=='setup':s['targets'][2]['operation_setup_native_id']=70
    elif fault=='kind':s['targets'][2]['operation_type']=True
    elif fault=='tool':s['tool']['native_id']=999
    elif fault=='diameter':s['tool']['cut_diameter_native']=2
    elif fault=='length':s['tool']['protrusion_native']=22
    elif fault=='target':t=deepcopy(t);t['operation_native_id']=1
    with pytest.raises(ValueError):m.validate_scope(b,t,s)

@pytest.mark.parametrize('key,value',[('GetSpndlSpeed',True),('XYFeed',float('nan')),('XYFeed',float('inf')),('XYFeed',0),('GetCNCComp',False)])
def test_invalid_scalar_cannot_be_accepted(key,value):
    v=nc();v[key]=value
    with pytest.raises(ValueError):m.values(v)


def test_spindle_coupled_feed_is_observed_but_final_feed_explicit():
    before=nc();middle=dict(before,GetSpndlSpeed=7100.,XYFeed=887.5)
    out=m.verify_readback(before,middle,'GetSpndlSpeed');assert out['automatic_xy_feed_change']=={'before':500.,'after':887.5}
    final=dict(middle,XYFeed=35.)
    assert m.verify_readback(middle,final,'XYFeed')['raw_readback_verified']
    assert m.verify_final(final)['raw_NC_recipe_verified']
    with pytest.raises(ValueError):m.verify_final(middle)

@pytest.mark.parametrize('field,key',[('GetSpndlSpeed','GetCNCComp'),('GetSpndlSpeed','GetRetractType'),('XYFeed','GetSpndlSpeed'),('XYFeed','GetTlpComp')])
def test_other_nc_drift_cannot_be_normalized(field,key):
    before=nc();after=dict(before);after[field]=m.TARGET_VALUES[field];after[key]+=1
    with pytest.raises(ValueError):m.verify_readback(before,after,field)

@pytest.mark.parametrize('field',['GetSpndlSpeed','XYFeed'])
@pytest.mark.parametrize('returned',[0,False,1,None])
def test_actual_setter_with_real_guard_prebinds_and_never_replays(tmp_path,monkeypatch,field,returned):
    from scripts import sw_cam_dispatch_guard as gm
    b,t,s=fixture();order=[];v=nc();source=tmp_path/'part.SLDPRT';source.write_bytes(b'part');proof=tmp_path/'proof.py';proof.write_text('# proof')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setattr(gm.ScopedCamDispatchGuard,'_identity',lambda self:None)
    def typed(raw,name,path):order.append('QI:'+name);return raw
    monkeypatch.setattr(gm,'_typed',typed)
    g=gm.ScopedCamDispatchGuard(None,'metadata',process_id=123,expected_document=dict(path=str(source),title=source.name,type=1,needs_save=True),source_sha256=digest(source),evidence_pins=[dict(path=str(proof),sha256=digest(proof))],verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None)
    def vendor(value):order.append('setter');v[field]=value;return returned
    owner=SimpleNamespace(GetTlpComp=lambda:v['GetTlpComp'],GetCNCComp=lambda:v['GetCNCComp'],GetSpndlSpeed=lambda:v['GetSpndlSpeed'],GetRetractType=lambda:v['GetRetractType'],SetSpndlSpeed=vendor)
    extension=SimpleNamespace(XYFeed=v['XYFeed']);setattr(extension,'_ICWNCParam2__com__set_XYFeed',vendor)
    raw=SimpleNamespace(GetIsToolpathGenerated=lambda:False,IGetEnumToolpaths=lambda:object(),IGetNCParam=lambda:owner)
    b.boundary=lambda:None;b.ctx=SimpleNamespace(guard=lambda:g);b.doc=object();b.typelib_path='metadata';b.target=lambda guard,target:(raw,None)
    monkeypatch.setattr(m.generation,'read_generic_tool',lambda *args:(s['tool'],None));monkeypatch.setattr(m.generation,'_items',lambda *args:[])
    def qi(*args,**kwargs):order.append('QI:NC2');return extension
    monkeypatch.setattr(m,'query_face_interface',qi)
    setter=m.set_spindle_once if field=='GetSpndlSpeed'else m.set_xy_feed_once
    if type(returned)is int and returned==0:assert setter(b,t,s,nc(),lambda:order.append('pending'))==0
    else:
        with pytest.raises(ValueError):setter(b,t,s,nc(),lambda:order.append('pending'))
    assert order.count('setter')==1 and order[-2:]==['pending','setter']
    assert g.summary()['native_call_attempted'] and g.summary()['native_call_returned']
    with pytest.raises(ValueError):g.dispatch_once(lambda:vendor(1),persist_pending=lambda:None)
    assert order.count('setter')==1


def test_exact_typed_setters_declared_offline():
    import ast
    tree=ast.parse(P.read_text())
    assert not any(isinstance(n,ast.Attribute)and n.attr in ('Save','GenerateToolpath','CreateMillFeature2','SetTool')for n in ast.walk(tree))
