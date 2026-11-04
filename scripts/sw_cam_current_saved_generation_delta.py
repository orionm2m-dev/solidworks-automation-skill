"""当前保存 MILL 指定刀路的捕获增量与有界 CL 契约；无原生连接。"""
from copy import deepcopy
from scripts.sw_cam_current_saved_parameter_fields import equal

MAX_OPERATIONS=32
MAX_RECORDS=100000

def require(value,message):
    if not value:raise ValueError(message)


def inventory(state):
    """严格验证完整顺序、已抑制空操作及记录总数；不静默过滤行。"""
    require(type(state) is dict and state.get('capture_complete') is True,'Complete current captured state required')
    rows=state.get('operations');require(type(rows) is list and 1<=len(rows)<=MAX_OPERATIONS,'Bounded complete operation inventory required')
    ids=[];generated=[];suppressed=[];total=0
    for row in rows:
        require(type(row) is dict,'Exact operation row required')
        oid=row.get('native_id');require(type(oid) is int and 0<oid<2**32 and oid not in ids,'Unique strict operation IDs required');ids.append(oid)
        require(type(row.get('suppressed')) is bool and type(row.get('toolpath_generated')) is bool,'Strict suppression/generated flags required')
        counts=row.get('toolpath_record_counts');require(type(counts) is list and len(counts)<=1 and all(type(n) is int and 0<n<=MAX_RECORDS for n in counts),'One positive count per generated operation, or empty required')
        require(row['toolpath_generated'] is bool(counts),'Generated flag/count mismatch')
        if row['suppressed']:
            require(not counts and row['toolpath_generated'] is False,'Suppressed operations must remain ungenerated and empty');suppressed.append(deepcopy(row))
        if counts:generated.append(dict(operation_native_id=oid,toolpath_record_counts=deepcopy(counts)))
        total+=sum(counts)
    require(total<=MAX_RECORDS,'Complete record total exceeds bounded CL capacity; no truncation')
    require(state.get('operation_count')==len(rows) and type(state.get('operation_count')) is int,'Actual operation count differs')
    counts=state.get('operation_counts');require(type(counts) is list and all(type(v) is int and v>=0 for v in counts) and sum(counts)==len(rows),'Setup operation counts differ')
    return dict(rows=rows,ids=ids,generated=generated,suppressed=suppressed,total_record_count=total)


def select(state,selected_ids,*,generated=False):
    """仅允许完整 authority 中的明确 rough 子集；不推断目标 ID 或类型。"""
    info=inventory(state)
    require(type(selected_ids) is list and 1<=len(selected_ids)<=8 and all(type(v) is int and v>0 for v in selected_ids) and len(set(selected_ids))==len(selected_ids),'Bounded explicit unique selected operation IDs required')
    require(set(selected_ids)<=set(info['ids']),'Selected operation is absent from complete authority')
    require(type(state.get('parameter_capture_complete')) is bool and state['parameter_capture_complete'],'Complete own parameter observations required')
    params=state.get('operation_parameters');require(type(params) is list,'Own parameter rows required')
    selected=[]
    for oid in selected_ids:
        row=next(r for r in info['rows'] if r['native_id']==oid)
        matches=[p for p in params if p.get('operation_native_id')==oid]
        require(len(matches)==1 and matches[0].get('read_complete') is True,'Unique complete own parameters required')
        p=matches[0]
        require(type(row.get('mill_operation_type')) is int and row['mill_operation_type']==0 and p.get('operation_type')==0,'Initial selected-generation contract supports observed Rough type0 only')
        require(row['suppressed'] is False and row['toolpath_generated'] is generated,'Exact selected generated/suppressed state required')
        require(row.get('linked_feature_ids')==[p.get('feature_native_id')],'Own feature binding differs')
        require(equal(row.get('assigned_tool'),p.get('tool',{}).get('generic')),'Own tool binding and full parameter tool differ')
        selected.append(deepcopy(row))
    return selected


def verify_generation(before,after,selected_ids,completed_ids):
    """只放行已完成显式目标的 generated/count 和严格布尔 dirty；保护其他字段。"""
    select(before,selected_ids)
    info=inventory(after)
    require(type(completed_ids) is list and completed_ids==selected_ids[:len(completed_ids)] and completed_ids,'Completed targets must be a nonempty ordered selected prefix')
    require(type(after.get('document',{}).get('needs_save')) is bool,'Strict observed document dirty flag required')
    expected=deepcopy(before);observed={r['native_id']:r for r in info['rows']};counts={}
    for oid in completed_ids:
        require(oid in observed,'Completed operation disappeared')
        row=observed[oid];require(row['toolpath_generated'] is True and len(row['toolpath_record_counts'])==1,'Positive completed selected records required')
        target=next(r for r in expected['operations'] if r['native_id']==oid)
        target['toolpath_generated']=True;target['toolpath_record_counts']=deepcopy(row['toolpath_record_counts']);counts[str(oid)]=deepcopy(row['toolpath_record_counts'])
    expected['document']['needs_save']=after['document']['needs_save']
    require(equal(expected,after),'GTP changed protected operation, suppression, tool, parameter, feature/setup or source fields')
    select(after,completed_ids,generated=True)
    return dict(selected_generated_counts=counts,old_generated_operations_preserved=inventory(before)['generated'],suppressed_rows_preserved=True,complete_captured_delta_verified=True,physical_toolpath_qualified=False)


def verify_saved(generated,saved):
    """源 SHA 由调用方在严格 Save 返回后转换；这里仅允许完整捕获 dirty 变 False。"""
    inventory(generated);inventory(saved)
    expected=deepcopy(generated);expected['document']['needs_save']=False
    require(equal(expected,saved),'Save changed captured state beyond the clean flag')
    return dict(saved_capture_preserved=True,clean_document=True,reopen_persistence_verified=False)


def cl_rows(authority,current,selected_ids,*,completed_ids=None):
    """在完整 source 行中允许且仅允许已固定的 suppressed/empty 行。"""
    a=inventory(authority);b=inventory(current)
    if completed_ids:verify_generation(authority,current,selected_ids,completed_ids)
    else:require(equal(authority,current),'Pre-GTP CL state differs from completed configuration authority')
    require(equal(a['suppressed'],b['suppressed']),'Pinned suppressed rows changed')
    require(b['generated'],'Machine CL requires at least one generated path')
    return deepcopy(b['generated'])


def compare_cl(before_parsed,after_parsed,before_rows,after_rows,selected_ids):
    """复用现有完整 block signature；不从计数或弧端点推断物理轨迹。"""
    from scripts.sw_cam_chamfer_cl_review import block_signature
    old=[r['operation_native_id'] for r in before_rows];new=[r['operation_native_id'] for r in after_rows]
    require(len(set(old))==len(old) and len(set(new))==len(new),'Unique CL operation context required')
    require(set(new)==set(old)|set(selected_ids) and not set(old)&set(selected_ids),'CL generated inventory differs from explicit selection')
    for parsed,rows in ((before_parsed,before_rows),(after_parsed,after_rows)):
        require(parsed.get('parse_complete') is True and parsed.get('native_count_matches') is True and len(parsed.get('operation_blocks',[]))==len(rows),'Complete native-count-matched CL required')
        require(parsed.get('declared_units')==['MM'],'Explicit unchanged metric CL declaration required')
    old_boxes=[x['raw'] for x in before_parsed['commands'] if x['name']=='BOX']
    new_boxes=[x['raw'] for x in after_parsed['commands'] if x['name']=='BOX']
    require(old_boxes==new_boxes,'CL stock declaration changed')
    signatures=[block_signature(after_parsed,i) for i in range(len(new))];positions=[]
    for i,oid in enumerate(old):
        sig=block_signature(before_parsed,i);matches=[j for j,v in enumerate(signatures) if v==sig]
        require(len(matches)==1,'Protected CL block changed or has ambiguous complete signature')
        positions.append(matches[0])
    require(positions==sorted(positions),'Protected CL block order changed')
    require([new[i] for i in positions]==old,'Protected blocks do not match expected ordered native-count context')
    return dict(protected_complete_streams_verified=True,protected_operation_native_ids=old,protected_block_count=len(old),new_block_count=len(selected_ids),new_block_native_id_mapping_verified=False,world_geometry_verified=False,production_qualified=False)
