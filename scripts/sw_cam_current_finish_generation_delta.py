"""One configured Finish generation; raw failed empty368 remains immutable."""
from copy import deepcopy
from scripts import sw_cam_current_finish_configuration_delta as configuration
from scripts import sw_cam_current_saved_generation_delta as legacy
from scripts import sw_cam_current_circular_finish_delta as creation
require=configuration.require;exact=configuration.exact;EXTRA=configuration.EXTRA

def select(state,oid,fid,*,generated=False):
    require(type(oid)is int and type(fid)is int and oid>0 and fid>0,'Strict actual new identities required')
    require(all(state.get(k)is True for k in('capture_complete','extended_capture_complete','parameter_capture_complete')),'Full captured state required')
    rows=state['operations'];require(type(rows)is list and len(rows)==30 and len({r['native_id']for r in rows})==30,'Exact unique30 required')
    baseline=deepcopy(state);baseline['operations']=deepcopy(rows[:-1])
    for key in('document','sketch_state'):require(type(state[key]['needs_save'])is bool,'Strict dirty flag required');baseline[key]['needs_save']=False
    creation.validate_baseline(baseline)
    row=rows[-1];require(row['native_id']==oid and row['linked_feature_ids']==[fid]and type(row['mill_operation_type'])is int and row['mill_operation_type']==1 and row['setup_native_id']==94 and row['suppressed']is False and row['toolpath_generated']is generated,'Exact last configured Finish required')
    require(exact(row['assigned_tool'],state['parameter_batch']['candidate_tool']['generic'])and row['assigned_tool']['native_id']==249,'Unchanged shared249 required')
    counts=row['toolpath_record_counts'];require(type(counts)is list,'Native count array required')
    if generated:require(len(counts)==1 and type(counts[0])is int and 0<counts[0]<=legacy.MAX_RECORDS-83961,'Positive bounded new Finish count required')
    else:require(exact(counts,[]),'Only never-generated empty new Finish may generate')
    obs=state[EXTRA]['operation_observation'];require(obs['operation_native_id']==oid and obs['feature_native_id']==fid and obs['tool_native_id']==249 and obs['defaults']['complete']is True and obs['modes']['capture_complete']is True,'Complete selected observation required')
    return deepcopy(row)

def observed_rows(reference,actual,oid,fid,attempted):
    require(type(attempted)is list and (not attempted or(len(attempted)==1 and type(attempted[0])is int and attempted[0]==oid)),'One explicit durable attempt allowed')
    require(type(reference)is list and len(reference)==30 and type(actual)is list and len(actual)==30 and exact(reference[:-1],actual[:-1]),'Protected29 rows changed')
    expected=deepcopy(reference[-1]);new=actual[-1]
    require(expected['native_id']==oid and expected['linked_feature_ids']==[fid]and expected['toolpath_generated']is False and exact(expected['toolpath_record_counts'],[]),'Configured empty target required')
    if attempted:
        counts=new['toolpath_record_counts'];require(new['toolpath_generated']is True and type(counts)is list and len(counts)==1 and type(counts[0])is int and 0<counts[0]<=legacy.MAX_RECORDS-83961,'Positive bounded new Finish count required')
        expected.update(toolpath_generated=True,toolpath_record_counts=deepcopy(counts))
    require(exact(expected,new),'New Finish binding/tool or unrelated row fields changed');return deepcopy(actual)

def verify_generation(before,after,oid,fid):
    select(before,oid,fid);select(after,oid,fid,generated=True)
    expected=deepcopy(before);expected['operations']=observed_rows(before['operations'],after['operations'],oid,fid,[oid])
    for key in('document','sketch_state'):expected[key]['needs_save']=after[key]['needs_save']
    require(configuration.circular.circular_state_equal(expected,after),'GTP changed protected parameters, tool, geometry, empty368, source or old paths')
    return dict(selected_operation_native_id=oid,selected_record_count=after['operations'][-1]['toolpath_record_counts'][0],protected_operations=29,protected_positive_paths=20,protected_records=83961,raw_empty368_preserved=True,physical_toolpath_qualified=False)

def verify_saved(before,saved,oid,fid,sha):
    select(before,oid,fid,generated=True);select(saved,oid,fid,generated=True)
    require(saved['document']['needs_save']is False and saved['sketch_state']['needs_save']is False and saved['sketch_state']['saved_file_sha256']==sha,'Exact clean saved source required')
    expected=deepcopy(before);expected['document']['needs_save']=False;expected['sketch_state']['needs_save']=False;expected['sketch_state']['saved_file_sha256']=sha
    require(configuration.circular.circular_state_equal(expected,saved),'Save changed protected full state');return dict(saved_state_verified=True,reopen_persistence_verified=False)

def verify_compact(state,compact,planes):
    require(compact.get('scope')=='CIRCULAR_FINISH_COMPACT_PRE_SAVE_V1'and compact.get('full_parameter_capture')is False,'Exact compact observation required')
    for key in('operations','features','feature_setups','operation_counts','selected_operation_setup','operation_setups','operation_setup_count','operation_count','operation_inventory_scope'):require(exact(compact['inventory'][key],state[key]),'Compact inventory changed: '+key)
    require(exact(compact['new_circle'],state[EXTRA])and exact(compact['shared_candidate'],state['parameter_batch']['candidate_tool']),'Selected geometry/parameters or shared tool changed')
    pair=state['selected_pair_observations'];require(exact(compact['selected_targets'],pair['targets'])and exact(compact['retained_draft'],pair['draft']),'Protected pair/draft changed')
    require(exact(compact['plane_observations'],planes),'Plane metadata changed');creation.circle.verify_sw(state,dict(state,sketch_state=compact['sketch_state']))
    return dict(compact_verified=True,full_parameter_capture=False)

def positive_rows(state):return [dict(operation_native_id=r['native_id'],toolpath_record_counts=deepcopy(r['toolpath_record_counts']))for r in state['operations']if r['toolpath_generated']is True]
