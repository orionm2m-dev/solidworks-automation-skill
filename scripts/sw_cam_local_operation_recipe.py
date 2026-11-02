"""Strict recipe hooks around existing typed fields and explicit entry/NC adapters."""
from copy import deepcopy
from scripts import sw_cam_guide_group_configuration as config
from scripts import sw_cam_local_startpoint as entry
from scripts.sw_cam_rough_firstcut import require

group=config.group


def controlled_projection(row,*,entry_initialized):
    result=config.protected_parameters(row)
    values=result['nc']['feeds_compensation']
    for key in ('GetSpndlSpeed','XYFeed','GetCNCComp'):values.pop(key)
    if 'protected_finish'in result:result['protected_finish']['compensation'][1]=0
    if entry_initialized and 'rough'in result:
        # Established derived legacy aliases; the actual typed point collection is
        # verified independently, and physical frame/helix by the saved CL review.
        for key in ('GetHoleCentreEntry','GetEntryStartPtX','GetEntryStartPtY'):result['rough']['entry'].pop(key)
        for key in ('rows','count','hole_center_entry'):result['startpoints'].pop(key)
    return result


def verify_assignment(before,after,target,loaded):
    require(after['read_complete']is True and group.exact(after['tool'],loaded['local_tool_dimensions']),'Full actual assigned serial-tool dimensions differ')
    a=controlled_projection(before,entry_initialized=False);b=controlled_projection(after,entry_initialized=False)
    a.pop('tool');b.pop('tool')
    require(group.exact(a,b),'SetTool changed unrequested selected fields')
    require(after['nc']['feeds_compensation']['GetCNCComp']in(0,1)and after['nc']['feeds_compensation']['GetTlpComp']==1,'Only known CAM/CNC compensation state is eligible')
    config.verify_automatic_target(before,after)


def configure_selected(backend,journal,target,loaded,*,configure_nc,entry_adapter=entry.apply_entry):
    oid=target['operation_native_id']
    for spec in config.ROUGH_FIELDS if target['operation_type']==0 else config.FINISH_FIELDS:
        expected=target['fields'][spec[0]];label=str(oid)+':'+spec[0];old=backend.field(target,spec)
        if group.exact(old,expected):journal.entry(label);journal.verified(label,dict(already_satisfied=True,value=old));continue
        journal.execute(label,lambda pending,spec=spec,value=expected:backend.set_field(target,spec,value,pending));backend.refresh_dirty()
        observed=backend.field(target,spec);require(group.exact(observed,expected),'Immediate typed field readback differs: '+spec[0]);journal.verified(label,observed)
    configure_nc(backend,journal,target,loaded)
    if target['operation_type']==0:
        point=target['entry_point_native'];require(type(point)is list and len(point)==3 and point[2]==0.,'Declared planar point convention required')
        entry_adapter(backend,journal,target,point)


def verify_configured(before,after,targets,loaded):
    require(group.exact(before['binding'],after['binding']),'Recipe changed operation bindings or tools')
    byid={t['operation_native_id']:t for t in targets}
    require(len(before['parameters'])==len(after['parameters'])==12 and len(byid)==4,'Full protected8 plus selected4 readback required')
    for old,new in zip(before['parameters'],after['parameters']):
        oid=old['operation_native_id']
        if oid not in byid:require(group.exact(old,new),'Protected parameter changed');continue
        target=byid[oid];rough=target['operation_type']==0
        require(new['operation_native_id']==oid and new['read_complete']is True,'Complete selected readback required')
        require(group.exact(new['tool'],loaded['local_tool_dimensions']),'Qualified assigned full tool changed')
        require(group.exact(new['levels'],target['expected_levels']),'Actual feature depth/setup differs')
        require(group.exact(controlled_projection(old,entry_initialized=rough),controlled_projection(new,entry_initialized=rough)),'Unrequested selected parameter changed')
        for spec in config.ROUGH_FIELDS if rough else config.FINISH_FIELDS:
            require(group.exact(config.field_value(new,spec),target['fields'][spec[0]]),'Selected recipe readback differs: '+spec[0])
        values=new['nc']['feeds_compensation']
        require(type(values['GetSpndlSpeed'])is float and values['GetSpndlSpeed']==7100. and type(values['XYFeed'])is float and values['XYFeed']==35.,'Explicit provisional7100/35 raw values required')
        require(type(values['GetCNCComp'])is int and values['GetCNCComp']==0 and type(values['GetTlpComp'])is int and values['GetTlpComp']==1,'Explicit CAM1/CNC0 required')
        if rough:entry.verify_startpoint(new['startpoints'],target['entry_point_native'])
