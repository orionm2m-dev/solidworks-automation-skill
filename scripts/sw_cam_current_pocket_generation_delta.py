"""Pure first-path proof for one selected Rough in a protected current pair.

No file writes or native calls. Inputs are actual complete snapshots and a
truthful native return observation; the caller binds their receipt provenance.
"""
from copy import deepcopy
import math
import re
from scripts import sw_cam_current_saved_generation_delta as existing
from scripts.sw_cam_generic_cl_reader_bounded import SCOPE as CL_SCOPE

AGGREGATES=('generated_operation_count','total_record_count')
require=existing.require


def _json(value,depth=0,budget=None):
    if budget is None:budget=[200000]
    budget[0]-=1
    require(depth<=48 and budget[0]>=0,'Bounded JSON snapshot required')
    kind=type(value)
    if kind is dict:
        require(all(type(k)is str for k in value),'JSON string keys required')
        for item in value.values():_json(item,depth+1,budget)
    elif kind is list:
        for item in value:_json(item,depth+1,budget)
    elif kind is float:require(math.isfinite(value),'Finite JSON numbers required')
    else:require(value is None or kind in (str,int,bool),'Exact JSON values required')


def flatten(snapshot):
    """Validate a complete actual pair and adapt it without dropping any fields."""
    require(type(snapshot)is dict and set(snapshot)=={'inventory','parameters'},'Exact current pair snapshot required')
    _json(snapshot)
    state=deepcopy(snapshot['inventory']);params=deepcopy(snapshot['parameters'])
    require(type(state)is dict and not {'operation_parameters','parameter_capture_complete'}&set(state),'Inventory must not shadow parameter observations')
    info=existing.inventory(state);rows=info['rows']
    require(len(rows)==2 and tuple(r.get('mill_operation_type')for r in rows)==(0,1)
        and all(type(r.get('mill_operation_type'))is int for r in rows),'One ordered Rough/Contour pair required')
    require(state.get('operation_setup_count')==1 and type(state.get('operation_setup_count'))is int
        and state['operation_counts']==[2],'One exact two-operation setup required')
    require(type(params)is list and len(params)==2,'Two complete parameter rows required')
    for row,param in zip(rows,params):
        require(type(param)is dict and param.get('read_complete')is True and type(param.get('operation_native_id'))is int
            and param['operation_native_id']==row['native_id'] and type(param.get('operation_type'))is int
            and param['operation_type']==row['mill_operation_type'],'Ordered own parameter identity/type differs')
        require(row['suppressed']is False and row.get('all_linked_features_observed')is True
            and row.get('linked_feature_ids')==[param.get('feature_native_id')],'Unsuppressed fully observed own feature link required')
        require(type(param.get('feature_native_id'))is int and param['feature_native_id']>0,'Strict feature ID required')
        tool=row.get('assigned_tool')
        require(type(tool)is dict and type(tool.get('native_id'))is int and tool['native_id']>0
            and type(param.get('tool'))is dict and existing.equal(tool,param['tool'].get('generic')),'Actual inventory/parameter tool binding differs')
    require(rows[0]['linked_feature_ids']==rows[1]['linked_feature_ids'] and type(rows[0].get('setup_native_id'))is int
        and rows[0]['setup_native_id']>0 and type(rows[1].get('setup_native_id'))is int and rows[0]['setup_native_id']==rows[1]['setup_native_id'],'Pair must retain one setup and feature')
    require(type(state.get('document',{}).get('needs_save'))is bool,'Actual strict document dirty flag required')
    expected=(len(info['generated']),info['total_record_count'])
    for name,value in zip(AGGREGATES,expected):
        require(type(state.get(name))is int and state[name]==value,'Actual derived aggregate differs: '+name)
    state['operation_parameters']=params;state['parameter_capture_complete']=True
    return state


def verify_generation(before,after,selected_id,native_generation):
    """Admit one first Rough path and only its two validated aggregate counters."""
    require(type(selected_id)is int and 0<selected_id<2**32,'Strict selected operation ID required')
    require(type(native_generation)is dict,'Actual native generation observation required')
    for key in ('attempted','returned'):require(native_generation.get(key)is True,'Generation must actually return: '+key)
    require(native_generation.get('native_dispatch_pending')is False and native_generation.get('native_return_type')=='int'
        and type(native_generation.get('native_return_value'))is int and native_generation['native_return_value']==0,'Exact completed native GTP int0 required')
    a,b=flatten(before),flatten(after)
    require(selected_id==a['operations'][0]['native_id'],'Only the explicitly selected Rough may generate')
    require(a['generated_operation_count']==a['total_record_count']==0,'First-path authority must contain no prior generated path')
    require(b['generated_operation_count']==1 and b['operations'][0]['native_id']==selected_id
        and b['operations'][0]['toolpath_generated']is True and len(b['operations'][0]['toolpath_record_counts'])==1,'Exactly one positive selected Rough path required')
    count=b['operations'][0]['toolpath_record_counts'][0]
    require(b['total_record_count']==count and b['operations'][1]['toolpath_generated']is False
        and b['operations'][1]['toolpath_record_counts']==[],'Protected Contour must remain empty')
    # Both actual aggregates were derived above. Only this comparison projection
    # omits them; raw snapshots and their generation flags remain untouched.
    left,right=deepcopy(a),deepcopy(b)
    for key in AGGREGATES:left.pop(key);right.pop(key)
    proof=existing.verify_generation(left,right,[selected_id],[selected_id])
    return dict(**proof,scope='CURRENT_PAIR_FIRST_SELECTED_GENERATION_DELTA_V1',selected_operation_native_id=selected_id,
        selected_record_count=count,protected_operation_native_ids=[a['operations'][1]['native_id']],
        before_aggregates={k:a[k]for k in AGGREGATES},after_aggregates={k:b[k]for k in AGGREGATES},
        aggregate_counts_verified=True,first_path_only=True,native_generation_return_verified=True,
        generated_current_context_readable_by_old_loader=False,world_geometry_verified=False,production_qualified=False)


def verify_first_cl(parsed,expected_operation_native_id,expected_count):
    """Check one complete metric block; native identity comes from sole inventory.

The caller must pin the exported bytes and bind this parser result to that file,
then bind the sole-generated inventory to verify_generation. A CL label does not
supply a native ID. This proof contains no world mapping or machining approval.
"""
    require(type(expected_operation_native_id)is int and 0<expected_operation_native_id<2**32,'Strict sole operation ID required')
    require(type(expected_count)is int and 0<expected_count<=existing.MAX_RECORDS,'Bounded positive native record count required')
    require(type(parsed)is dict and parsed.get('scope')==CL_SCOPE and parsed.get('status')=='review_required','Exact existing raw CL parser result required')
    require(parsed.get('parse_complete')is True and parsed.get('native_count_matches')is True
        and existing.equal(parsed.get('declared_units'),['MM']),'Complete native-count-matched metric CL required')
    for key in ('expected_block_record_counts','expected_native_record_counts','block_command_counts'):
        require(existing.equal(parsed.get(key),[expected_count]),'One exact observed native block count required: '+key)
    for key in ('unknown_commands','invalid_commands','structure_issues'):
        require(parsed.get(key)==[] and type(parsed.get(key))is list,'CL diagnostic prevents acceptance: '+key)
    blocks=parsed.get('operation_blocks')
    require(type(blocks)is list and len(blocks)==1 and type(blocks[0])is dict,'Exactly one complete CL block required')
    block=blocks[0]
    require(type(block.get('index'))is int and block['index']==0 and type(block.get('command_count'))is int
        and block['command_count']==expected_count and type(block.get('start_line'))is int and type(block.get('end_line'))is int
        and 0<block['start_line']<block['end_line'],'Complete single block boundaries/count required')
    motions=parsed.get('motions')
    require(type(motions)is list and motions and type(parsed.get('motion_count'))is int and parsed['motion_count']==len(motions)
        and all(type(x)is dict and type(x.get('block'))is int and x['block']==0 for x in motions),'All observed motions must belong to the sole block')
    require(type(parsed.get('sha256'))is str and re.fullmatch('[0-9a-f]{64}',parsed['sha256'])
        and type(parsed.get('bytes'))is int and 0<parsed['bytes']<=64*1024*1024,'Pinned bounded parser byte identity required')
    for key in ('operation_native_ids_inferred_from_labels','block_order_native_qualified','units_scale_verified','coordinate_frame_verified',
                'physical_poses_verified','tool_reference_verified','full_turn_semantics_qualified','production_qualified'):
        require(parsed.get(key)is False,'Raw parser cannot promote qualification: '+key)
    return dict(scope='CURRENT_PAIR_FIRST_CL_BLOCK_PROOF_V1',one_complete_metric_block=True,native_record_count_matches=True,
        expected_operation_native_id=expected_operation_native_id,expected_record_count=expected_count,
        raw_CL_sha256=parsed['sha256'],raw_CL_bytes=parsed['bytes'],native_id_inferred_from_label=False,
        identity_basis='caller-bound sole generated operation inventory; no native ID encoded in CL label',
        caller_file_and_inventory_binding_required=True,preCL_required=False,protected_contour_has_no_CL_block=True,
        world_geometry_verified=False,physical_toolpath_qualified=False,production_qualified=False)
