"""Pure WIP comparison bridge. No terminal-authority loader or native endpoint.

The caller must separately bind the completed saved producer, current source,
owner, event session, output and one-shot marker. Raw empty rows are preserved.
"""
from copy import deepcopy
from scripts import sw_cam_current_circular_wip_binding as common
from scripts import sw_cam_completed_gtp_wip as core
require=common.require
SCOPE='SAVED_ROUTE_RAW_EMPTY_WIP_COMPARISON_V1'

def inventory(state,declared_empty_ids):
    require(type(declared_empty_ids)is list and all(type(x)is int and x>0 for x in declared_empty_ids)and len(set(declared_empty_ids))==len(declared_empty_ids),'Explicit distinct empty operation IDs required')
    rows=state.get('operations');require(type(rows)is list and 1<=len(rows)<=common.delta.MAX_OPERATIONS,'Bounded complete actual route required')
    ids=[r['native_id']for r in rows];require(all(type(x)is int and 0<x<2**32 for x in ids)and len(set(ids))==len(ids),'Strict unique operation IDs required')
    require(set(declared_empty_ids)<=set(ids),'Declared empty operation absent')
    require(type(state.get('operation_count'))is int and state['operation_count']==len(rows),'Actual operation count differs')
    per_setup=state.get('operation_counts');require(type(per_setup)is list and all(type(n)is int and n>=0 for n in per_setup)and sum(per_setup)==len(rows),'Actual setup counts differ')
    positive=[];empty=[];total=0
    for row in rows:
        counts=row.get('toolpath_record_counts');flag=row.get('toolpath_generated');oid=row['native_id']
        require(type(row.get('suppressed'))is bool,'Strict suppression flag required')
        require(not row['suppressed'] or (flag is False and counts==[]),'Suppressed path is not a machining path')
        require(type(flag)is bool and type(counts)is list and len(counts)<=1,'Strict generated flag and bounded counts required')
        if oid in declared_empty_ids:
            require(flag is False and (counts==[]or(len(counts)==1 and type(counts[0])is int and counts[0]==0)),'Declared empty operation acquired a path')
            empty.append(dict(operation_native_id=oid,toolpath_generated=False,raw_toolpath_record_counts=deepcopy(counts)))
        elif flag:
            require(len(counts)==1 and type(counts[0])is int and 0<counts[0]<=common.delta.MAX_RECORDS,'Positive actual generated record count required')
            total+=counts[0];positive.append(dict(operation_native_id=oid,toolpath_record_counts=deepcopy(counts)))
        else:require(counts==[],'Undeclared zero collection or stale ungenerated path')
    require(total<=common.delta.MAX_RECORDS and positive,'Bounded positive saved paths required')
    return dict(positive_operations=positive,empty_witnesses=empty,total_records=total,operation_count=len(rows))

def comparison_contract(state,*,process_id,source_sha256,declared_empty_ids,positive_operation_rows):
    require(type(process_id)is int and process_id>0,'Exact process identity required');common.strict_sha(source_sha256)
    info=inventory(state,declared_empty_ids)
    require(info['positive_operations']==positive_operation_rows,'Explicit actual positive path mapping differs')
    require(state.get('capture_complete')is True and state.get('extended_capture_complete')is True and state.get('parameter_capture_complete')is True and state.get('parameter_batch',{}).get('read_complete')is True,'Complete saved route observation required')
    require(state['document']['needs_save']is False and state['sketch_state']['needs_save']is False and type(state['sketch_state']['pid'])is int and state['sketch_state']['pid']==process_id and state['sketch_state']['saved_file_sha256']==source_sha256,'Exact clean saved owner/source required')
    out=dict(scope=SCOPE,process_id=process_id,source_sha256=source_sha256,document=deepcopy(state['document']),snapshot=deepcopy(state),declared_empty_ids=deepcopy(declared_empty_ids),inventory=info,authority_revalidated=False)
    out['comparison_sha256']=common.digest(out);return out

def validate_capture(contract,document,snapshot):
    expected=deepcopy(contract);digest=expected.pop('comparison_sha256');require(common.digest(expected)==digest,'Comparison contract drift')
    require(document==contract['document']and snapshot['document']==document and document['needs_save']is False,'Saved document changed')
    fresh=comparison_contract(snapshot,process_id=contract['process_id'],source_sha256=contract['source_sha256'],declared_empty_ids=contract['declared_empty_ids'],positive_operation_rows=contract['inventory']['positive_operations'])
    require(fresh['inventory']==contract['inventory'],'Raw empty collection or positive path mapping changed')
    require(common.authority.circular_state_equal(contract['snapshot'],snapshot),'Protected complete saved state changed')
    return dict(document=deepcopy(document),source_sha256=contract['source_sha256'],snapshot=common.authority.normalized(common.authority.align_circular_mass(contract['snapshot'],snapshot)))

def run_existing_core(contract,report,*,capture_existing,guard_factory,persist,claim,invoke,collect):
    require(report.get('native_call_attempted')is False and type(report.get('native_call_count'))is int and report['native_call_count']==0,'Fresh report; no replay')
    def capture(label):
        document,snapshot,native=capture_existing(label)
        report.setdefault('raw_captures',[]).append(dict(label=label,document=deepcopy(document),snapshot=deepcopy(snapshot)));persist()
        return validate_capture(contract,document,snapshot),native
    core.run_one_wip_export(report,capture=capture,guard_factory=guard_factory,persist=persist,claim=claim,invoke=invoke,collect=collect)
    require([x['label']for x in report['raw_captures']]==['before','after']and report['native_call_count']==1,'Exactly two observations and one export required')
    report.update(comparison_readback_verified=True,raw_empty_rows_preserved=True,cache_freshness_verified=False,material_removal_verified=False,outer_authority_cleanup_still_required=True);persist();return report
