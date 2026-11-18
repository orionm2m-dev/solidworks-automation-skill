"""Pure contracts for a saved pair of Finish operations; no native dispatcher."""
from copy import deepcopy
from dataclasses import dataclass
import math
from types import MappingProxyType
from scripts import sw_cam_circular_reconfigure as writer
from scripts import sw_cam_append_finish_definitions as appended

SCOPE='SAVED_FINISH_PAIR_CONFIGURATION_V1'
PRODUCER_SCOPES=frozenset({'SAVED_CIRCULAR_APPEND_FINISH_DEFINITIONS_V1','SAVED_CIRCULAR_APPEND_FINISH_RECOVERY_V1'})
require=writer.require
exact=writer.fields.equal

@dataclass(frozen=True)
class Field:
    interface:str
    getter:str
    setter:str
    mode:str
    kind:str
    path:tuple
    echoes:tuple=()

FIELDS=MappingProxyType({
 'bottom_finish':Field('ICWFinishMillOp','BottomFinOpt','BottomFinOpt','property','bool',('defaults','finish','BottomFinOpt')),
 'side_allowance':Field('ICWFinishMillOp','SideAllow','SideAllow','property','double',('defaults','finish','SideAllow')),
 'floor_allowance':Field('ICWFinishMillOp','DepthAllow','DepthAllow','property','double',('defaults','finish','DepthAllow'),(('defaults','finish','GetZAllowance'),)),
 'final_side':Field('ICWFinishMillOp','FinalSideCutAmt','FinalSideCutAmt','property','double',('defaults','finish','FinalSideCutAmt')),
 'final_depth':Field('ICWFinishMillOp','FinalDepthCut','FinalDepthCut','property','double',('defaults','finish','FinalDepthCut')),
 'spring_passes':Field('ICWFinishMillOp','SpringPass','SpringPass','property','count',('defaults','finish','SpringPass')),
 'first_depth':Field('ICWFinishMillOp3','GetFirstDepthCut','SetFirstDepthCut','depth_pair','absolute_pair',('modes','depth_and_side_pairs','GetFirstDepthCut'),(('defaults','finish','FirstDepthCut'),)),
 'max_depth':Field('ICWFinishMillOp3','GetMaxDepthCut','SetMaxDepthCut','depth_pair','absolute_pair',('modes','depth_and_side_pairs','GetMaxDepthCut'),(('defaults','finish','MaxDepthCut'),)),
 'side_step':Field('ICWFinishMillOp3','GetSideCutAmt','SetSideCutAmt','depth_pair','absolute_pair',('modes','depth_and_side_pairs','GetSideCutAmt'),(('defaults','finish','SideCutAmt'),)),
 'previous_allowance':Field('ICWFinishMillOp2','GetPreviousAllowance','SetPreviousAllowance','feature','double',('defaults','finish','GetPreviousAllowance')),
 'override_previous':Field('ICWFinishMillOp','OverridePrevAllow','OverridePrevAllow','property','bool',('defaults','finish','OverridePrevAllow')),
 'perimeter':Field('ICWFinishMillOp','PerimeterPassType','PerimeterPassType','property','enum',('defaults','finish','PerimeterPassType')),
 'gouge_check':Field('ICWFinishMillOp3','GougeCheck','GougeCheck','property','bool',('modes','finish_scope','GougeCheck')),
 'depth_override':Field('ICWMillOperation3','GetOverrideMachiningDepth','SetOverrideMachiningDepth','feature','bool',('defaults','level_state','levels','override_machining_depth')),
 'machining_depth':Field('ICWMillOperation3','GetMachiningDepthValue','SetMachiningDepthValue','feature','double',('defaults','level_state','levels','machining_depth_value_native'),(('defaults','level_state','levels','machining_depth_native'),)),
 'link_to_tool':Field('ICWNCParam4','LinkToTool','LinkToTool','property','bool',('modes','nc','LinkToTool')),
 'spindle':Field('ICWNCParam','GetSpndlSpeed','SetSpndlSpeed','scalar','positive',('modes','nc','GetSpndlSpeed')),
 'xy_feed':Field('ICWNCParam2','XYFeed','XYFeed','property','positive',('modes','nc','XYFeed')),
 'leadin_feed':Field('ICWNCParam','GetLeadinFeedrate','SetLeadinFeedrate','absolute_feed','absolute_feed',('modes','nc','leadin_feed')),
})


def value_at(obj,path):
    for key in path:obj=obj[key]
    return obj


def put(obj,path,value):
    for key in path[:-1]:obj=obj[key]
    require(path[-1]in obj,'Observed field missing');obj[path[-1]]=deepcopy(value)


def checked(spec,value):
    kind=spec.kind
    if kind=='bool':require(type(value)is bool,'Strict Boolean required')
    elif kind in ('count','enum'):require(type(value)is int and 0<=value<=(20 if kind=='count'else 4),'Bounded strict integer required')
    elif kind=='absolute_pair':require(type(value)is list and len(value)==2 and type(value[0])is float and math.isfinite(value[0]) and 0<=value[0]<=1000 and value[1]is False,'Absolute DOUBLE/BOOL pair required')
    elif kind=='absolute_feed':require(type(value)is dict and set(value)=={'value_native','is_percent','physical_units_verified'} and type(value['value_native'])is float and math.isfinite(value['value_native']) and 0<value['value_native']<=100000 and value['is_percent']is False and value['physical_units_verified']is False,'Explicit positive absolute feed required')
    else:require(type(value)is float and math.isfinite(value) and 0<=value<=100000 and (kind!='positive'or value>0),'Finite explicit native double required')
    return deepcopy(value)


def validate_completed_payload(receipt,original_state,*,expected_scope,source_sha256):
    """Check common payload only. A separately pinned producer lineage is mandatory."""
    require(expected_scope in PRODUCER_SCOPES and receipt.get('scope')==expected_scope,'Exact producer scope required')
    require(receipt.get('status')=='review_required'and receipt.get('phase')=='finished','Terminal successful definition receipt required')
    for k in ('definitions_verified','model_saved','save_readback_verified','source_update_verified','readback_verified','runtime_unchanged'):require(receipt.get(k)is True,'Completed definition proof required: '+k)
    for k in ('GTP_attempted','GOP_attempted','AFR_attempted','parameter_setter_attempted','tool_assignment_attempted','tool_edit_attempted','automatic_replay'):require(receipt.get(k)is False,'Definition producer has forbidden action: '+k)
    require(receipt['source_after_sha256']==receipt['saved_file_sha256']==source_sha256,'Actual saved source transition required')
    action=receipt['actions']['SaveActiveDocument'];require(action.get('attempted')is True and action.get('returned')is True and action.get('native_dispatch_pending')is False and action.get('native_return_type')=='int'and type(action.get('native_return_value'))is int and action['native_return_value']==0,'One returned native Save0 required')
    stage=receipt['save_stage'];require(stage.get('native_call_returned')is True and stage.get('save_pending')is False and stage.get('native_return_type')=='int'and type(stage.get('native_return_value'))is int and stage['native_return_value']==0,'Durable returned Save stage required')
    added=receipt['new_operations'];require(len(added)==2 and len({r['native_id']for r in added})==2,'Two actual definitions required')
    saved=receipt['saved'];require(writer.same(saved,receipt['confirm_saved']),'Two final saved states differ')
    require(saved['document']['needs_save']is False and saved['sketch_state']['needs_save']is False and saved['sketch_state']['saved_file_sha256']==source_sha256,'Clean exact saved snapshot required')
    projected=deepcopy(saved);projected['sketch_state']['saved_file_sha256']=original_state['sketch_state']['saved_file_sha256']
    appended.verify_appended(original_state,projected,added)
    defs=receipt['recipe']['definitions'];values=receipt['saved_defaults'];require(len(defs)==len(values)==2 and [d['role']for d in defs]==['floor','wall'],'Exact definition roles required')
    for row,definition,defaults in zip(added,defs,values):
        require(row['linked_feature_ids']==[definition['feature_native_id']]and row['setup_native_id']==definition['operation_setup_native_id'],'Saved actual feature/setup binding differs')
        require(defaults.get('complete')is True and type(defaults['finish']['BottomFinOpt'])is bool,'Strict observed bottom mode required; role is not inferred from TechDB name')
    return dict(payload_verified=True,producer_lineage_verified=False,mutation_authorized=False,operations=deepcopy(added),state=deepcopy(saved),defaults=deepcopy(values),role_defaults_verified=all(d['finish']['BottomFinOpt']is(r['role']=='floor')for d,r in zip(values,defs)))


def validate_recipe(recipe,observations,operation_rows,candidate):
    require(type(recipe)is dict and set(recipe)=={'scope','rows','qualification_only','save_after_verified'}and recipe['scope']==SCOPE and recipe['qualification_only']is True and recipe['save_after_verified']is True,'Exact qualification recipe required')
    require(type(recipe['rows'])is list and len(recipe['rows'])==len(observations)==len(operation_rows)==2,'Exactly two observed Finish rows required')
    require([r.get('role')for r in recipe['rows']]==['floor','wall'],'Floor then wall required')
    cid=candidate['generic']['native_id'];require(type(cid)is int and cid>0 and candidate.get('dimension_read_complete')is True,'Observed existing candidate profile required')
    seen=set()
    for row,observed,operation in zip(recipe['rows'],observations,operation_rows):
        require(set(row)=={'role','operation_native_id','feature_native_id','expected_tool_native_id','existing_tool_native_id','changes'},'Exact configuration row fields required')
        for k in ('operation_native_id','feature_native_id','expected_tool_native_id','existing_tool_native_id'):require(type(row[k])is int and row[k]>0,'Strict explicit identity required')
        oid=row['operation_native_id'];require(oid not in seen,'Duplicate selected operation');seen.add(oid)
        require(operation['native_id']==observed['operation_native_id']==oid and operation['mill_operation_type']==1 and operation['suppressed']is False and operation['toolpath_generated']is False and operation['toolpath_record_counts']==[],'Exact empty Finish required')
        require(operation['linked_feature_ids']==[row['feature_native_id']]and observed['feature_native_id']==row['feature_native_id'],'Exact observed feature required')
        require(operation['assigned_tool']['native_id']==observed['tool_native_id']==row['expected_tool_native_id']and row['existing_tool_native_id']==cid,'Exact existing source/candidate tool required')
        require(observed['defaults']['complete']is True and observed['modes']['capture_complete']is True and type(observed['defaults']['finish']['BottomFinOpt'])is bool,'Complete role-compatible current observation required')
        nc=observed['modes']['nc'];require(type(nc['GetSpeedFeedMethod'])is int and nc['GetSpeedFeedMethod']==0 and nc['GetIsLockSpindleSpeed']is False and nc['GetCNCComp']==0 and type(nc['GetCNCComp'])is int and nc['GetTlpComp']==1 and type(nc['GetTlpComp'])is int,'Explicit supported operation NC mode required')
        changes=row['changes'];require(type(changes)is list and 1<=len(changes)<=len(FIELDS),'Bounded explicit changes required');keys=set()
        for change in changes:
            require(type(change)is dict and set(change)=={'field','expected','new'},'Exact field change required');key=change['field'];require(key in FIELDS and key not in keys,'Unknown/duplicate fixed field');keys.add(key);spec=FIELDS[key]
            checked(spec,change['expected']);checked(spec,change['new']);require(exact(value_at(observed,spec.path),change['expected']),'Recorded expected field differs')
        expected=expected_observation(observed,row)
        require(value_at(expected,FIELDS['depth_override'].path)is True and value_at(expected,FIELDS['gouge_check'].path)is True and value_at(expected,FIELDS['link_to_tool'].path)is False,'Explicit override, gouge check and independent operation feeds required')
        require(expected['defaults']['finish']['BottomFinOpt']is(row['role']=='floor'),'Explicit final bottom mode must match requested role')
        require(value_at(expected,FIELDS['machining_depth'].path)>0,'Positive explicit operation depth required')
        for key in ('spindle','xy_feed','leadin_feed'):checked(FIELDS[key],value_at(expected,FIELDS[key].path))
    return deepcopy(recipe)


def compact_observation(defaults,modes):
    """Keep behavior values; full inventory is checked separately by the adapter."""
    require(defaults.get('complete')is True and modes.get('capture_complete')is True,'Complete recorded observations required')
    compact={k:deepcopy(v)for k,v in modes.items()if k not in ('inventory','leadin_pointer_diagnostic','observation_groups','defaults','defaults_diagnostic')}
    return dict(operation_native_id=modes['operation_native_id'],feature_native_id=modes['feature_native_id'],tool_native_id=modes['tool_native_id'],defaults=deepcopy(defaults),modes=compact)


def expected_observation(before,row):
    out=deepcopy(before)
    for change in row['changes']:
        spec=FIELDS[change['field']];require(exact(value_at(out,spec.path),change['expected']),'Expected field changed');value=checked(spec,change['new']);put(out,spec.path,value)
        for path in spec.echoes:put(out,path,value[0]if spec.kind=='absolute_pair'else value)
    out['tool_native_id']=row['existing_tool_native_id'];out['modes']['tool_native_id']=row['existing_tool_native_id']
    # Full inventory/tool and shared-consumer changes require separate full-state proof.
    return out


def verify_observation_delta(before,after,row):
    expected=expected_observation(before,row);require(exact(expected,after),'Unrequested Finish/NC/lead/plane change')
    return dict(explicit_selected_fields_verified=True,full_state_preservation_verified=False,production_qualified=False)
