"""Bounded raw CNC-compensation candidate for explicitly selected guide contours.

No enum meaning is assumed from raw zero. Qualification requires later CL
inspection and full parameter/route readback in the owning continuation.
"""
from math import isfinite
from scripts import sw_cam_guide_group_generation as generation
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _member

configuration,group=generation.configuration,generation.group
PAIRS={(324,82),(328,83)}


def audit(typelib,pin):
    from ctypes import POINTER,c_int
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _interface_class,_INTERFACES
    specs=(('ICWMillOperation','IGetNCParam',7,(POINTER(POINTER(IDispatch)),),(10,)),
        ('ICWNCParam','GetTlpComp',17,(POINTER(c_int),),(10,)),
        ('ICWNCParam','GetCNCComp',19,(POINTER(c_int),),(10,)),
        ('ICWNCParam','SetCNCComp',20,(c_int,),(1,)))
    rows=[]
    for owner,name,ident,args,flags in specs:
        cls=generation.reader.pocket._verify_generated_class(_interface_class(owner,str(typelib)),_INTERFACES[owner],pin)
        members=[v for v in cls._methods_ if v.name==name]
        require(len(members)==1,'Unique declared NC member required')
        configuration.finish.finish.prior.require_abi(members[0],ident,args,flags)
        rows.append(dict(interface=owner,member=name,dispid=ident))
    return dict(native_called=False,numeric_enum_meaning_qualified=False,members=rows)


def _owner(backend,guard,target,path_state):
    require((target['operation_native_id'],target['feature_native_id'])in PAIRS
        and type(target['operation_type'])is int and target['operation_type']==1,'Only the selected finish pair is allowed')
    raw,_=backend.target(guard,target)
    tool,_=generation.read_generic_tool(raw,backend.doc,guard.read,guard.typed)
    require(group.exact(tool,target['assigned_tool']),'Assigned finish tool changed')
    op=guard.typed(raw,'ICWOperation')
    expected=path_state if path_state is not None else dict(generated=False,record_counts=[])
    require(type(expected)is dict and set(expected)=={'generated','record_counts'} and type(expected['generated'])is bool
        and type(expected['record_counts'])is list and len(expected['record_counts'])<=1
        and all(type(x)is int and 0<x<=100000 for x in expected['record_counts']),'Exact bounded selected path observation required')
    actual=dict(generated=guard.read(op,'GetIsToolpathGenerated'),record_counts=[guard.read(guard.typed(x,'ICWToolpath'),'RecordCount')
        for x in generation._items(guard.read(op,'IGetEnumToolpaths'),guard.typed,guard.read,1)])
    require(type(actual['generated'])is bool and group.exact(actual,expected),'Selected path state changed before approved NC correction')
    nc=guard.read(guard.typed(raw,'ICWMillOperation'),'IGetNCParam')
    return guard.typed(nc,'ICWNCParam'),guard.typed(nc,'ICWNCParam2')


def _values(guard,owner,owner2):
    result={name:guard.read(owner,name)for name in ('GetTlpComp','GetCNCComp','GetSpndlSpeed','GetRetractType')}
    result['XYFeed']=guard.read(owner2,'XYFeed')
    require(all(type(result[k])is int for k in ('GetTlpComp','GetCNCComp','GetRetractType')),'Strict raw NC scalars required')
    require(all(type(result[k])in (int,float)and isfinite(result[k])for k in ('GetSpndlSpeed','XYFeed')),'Finite unchanged feed/spindle observations required')
    return result


def read_candidate_state(backend,target,path_state=None):
    backend.boundary()
    with backend.ctx.guard()as guard:
        owner,owner2=_owner(backend,guard,target,path_state)
        return _values(guard,owner,owner2)


def set_raw_zero_candidate(backend,target,expected,pending,path_state=None):
    require(type(expected)is dict and set(expected)=={'GetTlpComp','GetCNCComp','GetSpndlSpeed','GetRetractType','XYFeed'},'Exact fresh NC observation required')
    require(type(expected['GetTlpComp'])is int and expected['GetTlpComp']==1
        and type(expected['GetCNCComp'])is int and expected['GetCNCComp']==1,'Only observed raw1 to candidate0 transition is authorized')
    backend.boundary()
    with backend.ctx.guard()as guard:
        owner,owner2=_owner(backend,guard,target,path_state)
        require(group.exact(_values(guard,owner,owner2),expected),'NC state changed before candidate setter')
        return guard.dispatch_once(lambda:_member(owner,'SetCNCComp',0),persist_pending=pending)


def verify_candidate_readback(before,after):
    expected=dict(before,GetCNCComp=0)
    require(group.exact(after,expected),'Candidate setter changed compensation-offset, feed or spindle unexpectedly')
    return dict(raw_zero_readback_verified=True,numeric_enum_meaning_qualified=False,
        CAM_offset_semantics_qualified=False,CL_verification_required=True)