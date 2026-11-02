"""Bounded raw spindle/feed setters for four explicitly selected local operations.

Engineering intent is 7100 rpm and 35 mm/min. Native scalar readback is distinct
from unit, cutting-condition, and production qualification.
"""
from math import isfinite
from scripts import sw_cam_guide_finish_compensation as existing
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _member
from scripts.sw_cam_face_interfaces import query_face_interface

generation,group=existing.generation,existing.group
FIELDS={'GetTlpComp','GetCNCComp','GetSpndlSpeed','GetRetractType','XYFeed'}
TARGET_VALUES={'GetSpndlSpeed':7100.,'XYFeed':35.}


def validate_scope(backend,target,scope):
    require(type(scope)is dict and set(scope)=={'source_sha256','process_id','protected_operation_ids','targets','tool'},'Explicit bounded NC scope required')
    require(scope['source_sha256']==backend.args['expected_source_sha256'] and type(scope['process_id'])is int and scope['process_id']==backend.args['process_id'],'Source/process NC scope differs')
    rows=scope['targets'];old=scope['protected_operation_ids'];tool=scope['tool']
    require(type(rows)is list and len(rows)==4 and type(old)is list and len(old)==17 and len(set(old))==17 and all(type(v)is int and v>0 for v in old),'Four new targets and seventeen protected IDs required')
    ids=[];pairs=[];setups=[]
    for row in rows:
        require(all(type(row.get(k))is int and row[k]>0 for k in ('operation_native_id','feature_native_id','operation_setup_native_id')) and type(row.get('operation_type'))is int and row['operation_type']in(0,1),'Strict actual operation/feature/setup identities required')
        ids.append(row['operation_native_id']);pairs.append((row['feature_native_id'],row['operation_type']));setups.append(row['operation_setup_native_id'])
    fids={p[0]for p in pairs}
    require(len(set(ids))==4 and not set(ids)&set(old) and len(fids)==2 and set(pairs)=={(f,k)for f in fids for k in (0,1)} and len(set(setups))==1,'Exactly two actual rough/finish pairs outside protected route required')
    require(type(tool)is dict and type(tool.get('native_id'))is int and tool['native_id']>0 and tool.get('cut_diameter_native')==.8 and tool.get('protrusion_native')==19. and tool.get('tool_type_raw')==1,'Observed serial microtool projection required')
    require(group.exact(tool,backend.loaded['configuration_tool']),'Loaded selected tool differs')
    chosen=[row for row in rows if row['operation_native_id']==target.get('operation_native_id')]
    require(len(chosen)==1 and group.exact(chosen[0],target) and group.exact(target.get('assigned_tool'),tool),'Target is outside learned NC scope')
    return target


def _owner(backend,guard,target,scope):
    validate_scope(backend,target,scope)
    raw,_=backend.target(guard,target)
    tool,_=generation.read_generic_tool(raw,backend.doc,guard.read,guard.typed)
    require(group.exact(tool,scope['tool']),'Actual assigned tool changed')
    op=guard.typed(raw,'ICWOperation')
    require(guard.read(op,'GetIsToolpathGenerated')is False,'NC configuration requires an ungenerated new operation')
    paths=generation._items(guard.read(op,'IGetEnumToolpaths'),guard.typed,guard.read,1)
    require(paths==[],'New operation unexpectedly contains a prior toolpath')
    raw_nc=guard.read(guard.typed(raw,'ICWMillOperation'),'IGetNCParam')
    owner=guard.typed(raw_nc,'ICWNCParam')
    owner2=guard._observe(lambda:query_face_interface(raw_nc,'ICWNCParam2',backend.typelib_path,generated_pin=backend.loaded['generated_pin']))
    return owner,owner2


def values(value):
    require(type(value)is dict and set(value)==FIELDS,'Exact raw NC projection required')
    require(all(type(value[k])is int for k in ('GetTlpComp','GetCNCComp','GetRetractType')),'Strict raw NC integers required')
    require(all(type(value[k])in(int,float) and isfinite(value[k])and value[k]>0 for k in ('GetSpndlSpeed','XYFeed')),'Finite positive raw spindle/feed required')
    return value


def read_fields(backend,target,scope):
    backend.boundary()
    with backend.ctx.guard()as guard:
        owner,owner2=_owner(backend,guard,target,scope)
        return values(existing._values(guard,owner,owner2))


def _set_once(backend,target,scope,expected,pending,field):
    values(expected)
    require(expected['GetTlpComp']==1 and expected['GetCNCComp']==0,'Explicit CAM compensation1/CNC0 required before spindle/feed configuration')
    require(expected[field]!=TARGET_VALUES[field],'Already-correct scalar must be reused without a setter')
    backend.boundary()
    with backend.ctx.guard()as guard:
        owner,owner2=_owner(backend,guard,target,scope)
        require(group.exact(values(existing._values(guard,owner,owner2)),expected),'NC values changed before setter')
        if field=='GetSpndlSpeed':call=lambda:_member(owner,'SetSpndlSpeed',7100.)
        else:
            setter=getattr(owner2,'_ICWNCParam2__com__set_XYFeed')
            call=lambda:setter(35.)
        result=guard.dispatch_once(call,persist_pending=pending)
    require(type(result)is int and result==0,'Exact S_OK native setter return required; do not replay uncertain result')
    return result


def set_spindle_once(backend,target,scope,expected,pending):
    return _set_once(backend,target,scope,expected,pending,'GetSpndlSpeed')


def set_xy_feed_once(backend,target,scope,expected,pending):
    return _set_once(backend,target,scope,expected,pending,'XYFeed')


def verify_readback(before,after,field):
    values(before);values(after);require(field in TARGET_VALUES,'Only spindle or XY-feed readback supported')
    expected=dict(before);expected[field]=TARGET_VALUES[field]
    if field=='GetSpndlSpeed':expected['XYFeed']=after['XYFeed']
    require(group.exact(expected,after),'NC setter changed a protected scalar or failed exact target readback')
    return dict(field=field,raw_readback_verified=True,automatic_xy_feed_change=({'before':before['XYFeed'],'after':after['XYFeed']}if field=='GetSpndlSpeed'and before['XYFeed']!=after['XYFeed']else None),
      feed_units_verified=False,spindle_units_verified=False,physical_cutting_conditions_qualified=False,production_qualified=False)


def verify_final(value):
    values(value);require(value['GetTlpComp']==1 and value['GetCNCComp']==0 and value['GetSpndlSpeed']==7100. and value['XYFeed']==35.,'Exact final microtool raw NC recipe required')
    return dict(raw_NC_recipe_verified=True,feed_units_verified=False,spindle_units_verified=False,CL_FEDRAT_MMPM_confirmation_required=True,physical_cutting_conditions_qualified=False,production_qualified=False)


def audit(typelib,generated_pin):
    from ctypes import POINTER,c_double
    out=existing.audit(typelib,generated_pin);rows=[]
    for owner,name,ident,args,flags in (('ICWNCParam','SetSpndlSpeed',8,(c_double,),(0,)),('ICWNCParam2','_set_XYFeed',23,(c_double,),(1,))):
        cls=generation.reader.pocket.cam_class(owner,typelib,generated_pin)
        members=[v for v in cls._methods_ if v.name==name];require(len(members)==1,'Exact declared setter required')
        existing.configuration.finish.finish.prior.require_abi(members[0],ident,args,flags)
        rows.append(dict(interface=owner,member=name,dispid=ident))
        if name=='_set_XYFeed':require(hasattr(POINTER(cls),'_ICWNCParam2__com__set_XYFeed'),'Typed raw HRESULT feed property setter required')
    return dict(native_called=False,setters_native_qualified=False,prior_getter_audit=out,setters=rows,feed_units_verified=False,spindle_units_verified=False)
