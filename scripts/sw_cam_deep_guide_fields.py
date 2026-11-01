"""Read only the learned four deep-guide operation fields in one bounded batch.

The owning writer must supply its verified, durable native-ID mapping and a CAM
document retained from its current full capture. No setter, Save, GTP, bootstrap,
configuration switch or replay is exposed here. Frozen shallow helpers are reused
without modifying their fixed target contracts.
"""
from copy import deepcopy
from time import perf_counter
from scripts import sw_cam_guide_field_read_batch as fast
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_rough_firstcut import require

PROTECTED_IDS = frozenset((195,196,267,247,248,271,143,144,320,322,324,326,328))
PAIRS = ((80,0),(80,1),(81,0),(81,1))
KEYS = ('operation_native_id','feature_native_id','operation_type')


def learned_targets(targets):
    """Strict four-row identity mapping; IDs must come from verified insertions."""
    require(type(targets) is list and len(targets)==4,'Exactly four learned deep targets required')
    triples=[]
    for row in targets:
        require(type(row) is dict and all(type(row.get(k)) is int for k in KEYS),'Strict native integer IDs and operation type required')
        triple=tuple(row[k] for k in KEYS)
        require(0<triple[0]<2**31 and triple[0] not in PROTECTED_IDS,'A new bounded operation ID is required')
        triples.append(triple)
    require(tuple((fid,kind) for _,fid,kind in triples)==PAIRS,'Exact ordered deep80/81 rough/finish pairs required')
    require(len({oid for oid,_,_ in triples})==4,'Four distinct actual operation IDs required')
    return tuple(triples)


def select_fields(target,targets,names=None):
    allowed=learned_targets(targets)
    require(type(target) is dict and all(type(target.get(k)) is int for k in KEYS)
        and tuple(target[k] for k in KEYS) in allowed,'Selected operation is outside the learned deep group')
    specs=fast.config.ROUGH_FIELDS if target['operation_type']==0 else fast.config.FINISH_FIELDS
    keys=[spec[0] for spec in specs]
    if names is None:return specs
    require(type(names) is list and 1<=len(names)<=len(keys)
        and all(type(v) is str and v in keys for v in names) and len(set(names))==len(names),
        'Unique bounded configured field names required')
    return tuple(next(spec for spec in specs if spec[0]==name) for name in names)


def read_field_values(backend,target,*,targets,field_names=None,progress=lambda:None,diagnostic=None):
    """Same-session read-only field observation; never infer IDs or reuse after Save."""
    specs=select_fields(target,targets,field_names)
    doc=backend.doc
    require(doc is not None,'Current full-capture CAM document required')
    wanted=backend.loaded['configuration_tool']
    require(type(wanted.get('native_id')) is int and wanted['native_id']==273
        and type(wanted.get('cut_diameter_native')) in (int,float) and wanted['cut_diameter_native']==2.,
        'Qualified existing D2 tool273 required')
    require(diagnostic is None or (type(diagnostic) is dict and not diagnostic),'Fresh optional diagnostic mapping required')
    result={} if diagnostic is None else diagnostic
    result.update(operation_native_id=target['operation_native_id'],feature_native_id=target['feature_native_id'],
        field_values={},read_complete=False,binding_native_calls=0,binding_checks=0,binding_elapsed_seconds=0.,
        learned_targets=[dict(zip(KEYS,row)) for row in learned_targets(targets)])
    state=dict(member='',returned=False,read_index=0)
    binding=fast.make_configuration_check(backend,doc,result)
    batch=fast.make_batch(backend,doc,progress,state,binding)
    started=perf_counter()
    try:
        with batch:
            result['before'],raw,feature=fast.target_binding(doc,target,batch,wanted)
            owners={}
            for spec in specs:
                key,name,getter,_,mode=spec
                if name not in owners:
                    if name in ('lead_in','lead_out'):
                        if 'ICWFinishMillOp' not in owners:owners['ICWFinishMillOp']=batch.typed(raw,'ICWFinishMillOp')
                        lead=batch.read(owners['ICWFinishMillOp'],'IGetLeadin' if name=='lead_in' else 'IGetLeadout',feature)
                        owners[name]=batch.typed(lead,'ICWLeadInOut')
                    else:owners[name]=batch.typed(raw,name)
                result['field_values'][key]=fast.normalized(batch.read(owners[name],getter,*([feature] if mode=='feature' else [])))
            result['after'],_,_=fast.target_binding(doc,target,batch,wanted)
            require(fast.group.exact(result['before'],result['after']),'Selected target binding changed during field reading')
        batch.require_complete()
        result['read_complete']=True
    finally:
        result['read_batch']=batch.summary()
        result['elapsed_seconds']=perf_counter()-started
    return result


def read_parameter_groups(doc, handles, targets, batch, report, persist, *, learned):
    """Observe a nonempty subset of the four newly learned targets, no mutations."""
    learned_targets(learned)
    require(type(targets) is list and 1<=len(targets)<=4, "A bounded learned-target subset is required")
    require(type(report) is dict and "parameters" not in report, "Fresh parameter report required")
    selected_ids=[]
    for row in targets:
        select_fields(row,learned)
        oid=row["operation_native_id"]
        require(oid in handles and oid not in selected_ids, "Unique retained operation handle required")
        assigned=row.get("assigned_tool")
        require(type(assigned) is dict and type(assigned.get("native_id")) is int
            and 0<assigned["native_id"]<2**31, "Strict actual assigned tool ID required")
        selected_ids.append(oid)
    reader=fast.reader
    pocket,guide,group,fields,protected=reader.pocket,reader.guide,reader.group,reader.fields,reader.protected
    read_generic_tool=reader.read_generic_tool
    read_tool_dimensions=reader.read_tool_dimensions
    machine = batch.typed(batch.read(batch.typed(doc, 'ICWPartDoc'), 'IGetMachine'), 'ICWMachine')
    setups = _items(batch.read(machine, 'IGetEnumOpSetups'), batch.typed, batch.read, 3)
    selected = [s for s in setups if _object_id(doc, s, batch.read) == 93]
    require(len(selected) == 1, 'Exact operation setup93 required')
    setup, tool_cache = selected[0], {}
    for row in targets:
        oid, fid = row['operation_native_id'], row['feature_native_id']
        report['phase'] = 'parameters_' + str(oid)
        out = dict(operation_native_id=oid, feature_native_id=fid, read_complete=False)
        report.setdefault('parameters', []).append(out); persist()
        found = batch.read(doc, 'GetCWObjectFromID', 1, fid)
        require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True,
            'Exact retained guide feature lookup required')
        feature, operation = batch.feature_dispatch(found[0]), handles[oid]
        require(_object_id(doc, feature, batch.read) == fid, 'Resolved guide identity differs')
        out['levels'] = pocket.read_levels(operation, feature, read=batch.read,
            typed=batch.typed, feature_dispatch=batch.feature_dispatch)
        if row['operation_type'] == 0:
            out['rough'] = pocket.rough.read_rough_entry_parameters(operation, feature,
                read=batch.read, typed=batch.typed, diagnostic=out.setdefault('rough_diagnostic', {}))
            out['startpoints'] = guide.start.read_startpoints(operation, feature, read=batch.read,
                typed=batch.typed, metadata=batch.metadata, diagnostic=out.setdefault('startpoint_diagnostic', {}))
        else:
            out['finish'] = pocket.read_finish_parameters(operation, feature, read=batch.read, typed=batch.typed)
            out['finish_fields'] = fields.read_cached_fields(batch, operation, feature,
                out.setdefault('finish_field_diagnostic', {}))
            out['protected_finish'] = protected.read_protected(operation, feature, read=batch.read,
                typed=batch.typed, record=lambda key, value: out.setdefault('protected_raw', {}).update(
                    {key: pocket.rough.bounded_raw_observation(value)}))
            out['leads'] = pocket.leads.read_lead_details(operation, feature, read=batch.read,
                typed=batch.typed, lead_typed=lambda raw: batch.typed(raw, 'ICWLeadInOut'))
        out['nc'] = pocket.read_nc_settings(operation, setup, read=batch.read, typed=batch.typed,
            pointer_read=batch.plane, diagnostic=out.setdefault('nc_diagnostic', {}), persist=persist)
        generic, tool = read_generic_tool(operation, doc, batch.read, batch.typed)
        require(group.exact(generic, row['assigned_tool']), 'Assigned tool changed')
        tid = generic['native_id']; reused = tid in tool_cache
        if not reused: tool_cache[tid] = read_tool_dimensions(tool, generic, batch)
        require(group.exact(tool_cache[tid]['generic'], generic), 'Shared tool identity differs')
        out.update(tool=deepcopy(tool_cache[tid]), tool_dimensions_reused=reused, read_complete=True)
        persist()
    require(len(report['parameters']) == len(targets) and all(r['read_complete'] for r in report['parameters']),
        'Every selected actual parameter group must be complete')
    report['unique_tool_dimension_reads'] = len(tool_cache)

