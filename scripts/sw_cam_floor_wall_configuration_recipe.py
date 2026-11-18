"""Pure explicit Rough-floor/Finish-wall recipe; no native dispatch or authority grant."""
from copy import deepcopy
from dataclasses import replace
from scripts import sw_cam_finish_configuration_recipe as finish
from scripts import sw_cam_current_saved_parameter_fields as rough_fields
from scripts import sw_cam_rough_entry_parameters as decoder

require=finish.require
exact=finish.exact
SCOPE='SAVED_FLOOR_WALL_CONFIGURATION_V1'
COMMON_KEYS=('depth_override','machining_depth','link_to_tool','spindle','xy_feed','leadin_feed')
ROUGH_COMMON={key:replace(finish.FIELDS[key],path=(('modes','level_state')+finish.FIELDS[key].path[2:] if key in('depth_override','machining_depth')else finish.FIELDS[key].path),echoes=((('modes','level_state','levels','machining_depth_native'),)if key=='machining_depth'else()))for key in COMMON_KEYS}
ROUGH_DECODERS=dict(decoder.ENTRY_FIELDS+decoder.DEPTH_FIELDS+decoder.BOUNDARY_FIELDS)


def compact_target(target):
    require(type(target.get('operation_kind'))is int and target['operation_kind']in(0,1)and target.get('capture_complete')is True,'Complete explicit target kind required')
    if target['operation_kind']==1:return finish.compact_observation(target['defaults'],target)
    require(target['rough'].get('parameter_reads_complete')is True and target['rough_diagnostic'].get('read_complete')is True,'Complete Rough observations required')
    modes={k:deepcopy(v)for k,v in target.items()if k not in('rough_diagnostic','leadin_pointer_diagnostic','inventory','observation_groups','reused_from_terminal','fresh_observation_groups')}
    return dict(operation_native_id=target['operation_native_id'],feature_native_id=target['feature_native_id'],tool_native_id=target['tool_native_id'],modes=modes)


def expected_observation(before,row):
    kind=row['operation_kind'];require(type(kind)is int and kind in(0,1),'Explicit operation kind required')
    if kind==1:return finish.expected_observation(before,row)
    out=deepcopy(before)
    for change in row['changes']:
        key=change['field']
        if key in ROUGH_COMMON:
            spec=ROUGH_COMMON[key];finish.checked(spec,change['expected']);require(exact(finish.value_at(out,spec.path),change['expected']),'Expected common field differs');value=finish.checked(spec,change['new']);finish.put(out,spec.path,value)
            for path in spec.echoes:finish.put(out,path,value)
        else:
            require(key in rough_fields.FIELDS,'Unknown Rough field');spec=rough_fields.FIELDS[key];path=('modes','rough',spec.area,spec.getter);observed=finish.value_at(out,path)
            require(exact(observed,decoder.decode_parameter(observed['raw'],ROUGH_DECODERS[spec.getter]))and exact(observed['raw'],change['expected']),'Expected Rough decoded field differs')
            rough_fields.checked_value(spec,change['expected']);value=rough_fields.checked_value(spec,change['new']);finish.put(out,path,decoder.decode_parameter(value,ROUGH_DECODERS[spec.getter]))
            if key=='floor_allowance':
                alias=('modes','rough','depth','DepthAllow');require(exact(finish.value_at(out,alias)['raw'],change['expected']),'Established floor allowance echo differs');finish.put(out,alias,decoder.decode_parameter(value,ROUGH_DECODERS['DepthAllow']))
            if spec.alias:
                alias=('modes','rough',spec.area,spec.alias);require(exact(finish.value_at(out,alias)['raw'],change['expected'][1]),'Established Rough depth echo differs');finish.put(out,alias,decoder.decode_parameter(value[1],ROUGH_DECODERS[spec.alias]))
    out['tool_native_id']=row['existing_tool_native_id'];out['modes']['tool_native_id']=row['existing_tool_native_id'];return out


def validate_recipe(recipe,observations,operations,candidate):
    require(type(recipe)is dict and set(recipe)=={'scope','rows','qualification_only','save_after_verified'}and recipe['scope']==SCOPE and recipe['qualification_only']is True and recipe['save_after_verified']is True,'Exact mixed qualification recipe required')
    rows=recipe['rows'];require(type(rows)is list and len(rows)==len(observations)==len(operations)==2,'Exactly two observed selected operations required')
    require([(r.get('role'),r.get('operation_kind'))for r in rows]==[('floor',0),('wall',1)],'Explicit Rough floor then Finish wall required')
    cid=candidate['generic']['native_id'];require(type(cid)is int and cid>0 and candidate.get('dimension_read_complete')is True,'Existing observed candidate profile required')
    seen=set()
    for row,observed,op in zip(rows,observations,operations):
        require(set(row)=={'role','operation_kind','operation_native_id','feature_native_id','expected_tool_native_id','existing_tool_native_id','changes'},'Exact mixed row keys required');kind=row['operation_kind'];require(type(kind)is int,'Strict operation kind required')
        for key in('operation_native_id','feature_native_id','expected_tool_native_id','existing_tool_native_id'):require(type(row[key])is int and row[key]>0,'Explicit native identity required')
        oid=row['operation_native_id'];require(oid not in seen,'Unique selected operations required');seen.add(oid)
        require(op['native_id']==observed['operation_native_id']==oid and op['mill_operation_type']==kind and type(op['mill_operation_type'])is int and op['suppressed']is False and op['toolpath_generated']is False and op['toolpath_record_counts']==[],'Only actual ungenerated matching kind allowed')
        require(op['linked_feature_ids']==[row['feature_native_id']]and observed['feature_native_id']==row['feature_native_id'],'Selected feature differs')
        require(op['assigned_tool']['native_id']==observed['tool_native_id']==row['expected_tool_native_id']and row['existing_tool_native_id']==cid,'Assigned/candidate tool differs')
        modes=observed['modes'];require(modes.get('capture_complete')is True and modes.get('operation_kind')==kind and type(modes.get('operation_kind'))is int,'Complete matching kind observation required')
        if kind==0:require(modes['rough'].get('parameter_reads_complete')is True,'Complete Rough parameter set required')
        else:require(observed['defaults'].get('complete')is True,'Complete Finish defaults required')
        nc=modes['nc'];require(type(nc['GetSpeedFeedMethod'])is int and nc['GetSpeedFeedMethod']==0 and nc['GetIsLockSpindleSpeed']is False and type(nc['GetCNCComp'])is int and nc['GetCNCComp']==0 and type(nc['GetTlpComp'])is int and nc['GetTlpComp']==1,'Supported explicit operation NC mode required')
        changes=row['changes'];allowed=(set(ROUGH_COMMON)|set(rough_fields.FIELDS))if kind==0 else(set(finish.FIELDS)-{'bottom_finish'});require(type(changes)is list and 1<=len(changes)<=len(allowed),'Bounded explicit selected changes required');keys=set()
        for change in changes:
            require(type(change)is dict and set(change)=={'field','expected','new'}and change['field']in allowed and change['field']not in keys,'Unsupported or duplicate field');keys.add(change['field'])
            if kind==1:
                spec=finish.FIELDS[change['field']];finish.checked(spec,change['expected']);finish.checked(spec,change['new'])
        after=expected_observation(observed,row);mapping=ROUGH_COMMON if kind==0 else finish.FIELDS
        require(finish.value_at(after,mapping['depth_override'].path)is True and finish.value_at(after,mapping['machining_depth'].path)>0 and finish.value_at(after,mapping['link_to_tool'].path)is False,'Explicit positive override and independent feeds required')
        for key in('spindle','xy_feed','leadin_feed'):finish.checked(mapping[key],finish.value_at(after,mapping[key].path))
        if kind==0:
            for key in('side_allowance','floor_allowance'):
                spec=rough_fields.FIELDS[key];require(type(after['modes']['rough'][spec.area][spec.getter]['raw'])is float and after['modes']['rough'][spec.area][spec.getter]['raw']==0.,'Clearing Rough requires explicit zero stocks')
            for key in('first_depth','subsequent_depth','side_step'):
                spec=rough_fields.FIELDS[key];require(after['modes']['rough'][spec.area][spec.getter]['raw'][0]is False,'Explicit absolute Rough mode required')
        else:require(after['defaults']['finish']['BottomFinOpt']is False and after['modes']['finish_scope']['GougeCheck']is True,'Wall remains contour-only with explicit gouge check')
    return deepcopy(recipe)


def verify_observation_delta(before,after,row):
    require(exact(expected_observation(before,row),after),'Unrequested selected Rough/Finish/NC change')
    return dict(explicit_selected_fields_verified=True,full_state_preservation_verified=False,mutation_authorized=False,production_qualified=False)
