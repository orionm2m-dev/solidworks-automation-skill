"""One saved circle Finish: fixed recipe and comparison-only numeric projection."""
from copy import deepcopy
from scripts import sw_cam_finish_configuration_recipe as fields
from scripts import sw_cam_current_circular_finish_delta as creation
from scripts import sw_cam_partial_mill_pair_projection as numeric
from scripts import sw_cam_current_circular_authority as circular
require=fields.require;exact=fields.exact
SCOPE='CURRENT_ORDINARY_CIRCULAR_FINISH_CONFIGURATION_RECIPE_V1'
EXTRA=creation.EXTRA
NOMINALS={'link_to_tool':False,'spindle':2000.0,'xy_feed':150.0,'leadin_feed':{'value_native':75.0,'is_percent':False,'physical_units_verified':False},'depth_override':True,'machining_depth':7.1,'side_allowance':0.0,'final_side':0.5,'final_depth':0.0,'spring_passes':0,'first_depth':[7.1,False],'max_depth':[7.1,False],'side_step':[0.5,False],'override_previous':True,'previous_allowance':0.5,'gouge_check':True}
NUMERIC=frozenset({'machining_depth','first_depth','max_depth'})

def validate_recipe(recipe,before,oid,fid):
    require(type(recipe)is dict and set(recipe)=={'scope','row','qualification_only','save_after_verified'}and recipe['scope']==SCOPE and recipe['qualification_only']is True and recipe['save_after_verified']is True,'Exact single Finish recipe required')
    row=recipe['row'];require(type(row)is dict and set(row)=={'role','operation_kind','operation_native_id','feature_native_id','expected_tool_native_id','existing_tool_native_id','changes'},'Exact selected row required')
    require(row['role']=='wall'and type(row['operation_kind'])is int and row['operation_kind']==1,'Only wall Finish kind1 required')
    for key in('operation_native_id','feature_native_id','expected_tool_native_id','existing_tool_native_id'):require(type(row[key])is int and row[key]>0,'Strict actual identity required')
    require(row['operation_native_id']==oid and row['feature_native_id']==fid and row['existing_tool_native_id']==249,'Actual new circle/op and existing249 required')
    require(len(before['operations'])==30 and len({x['native_id']for x in before['operations']})==30,'Complete unique saved30 required')
    operation=before['operations'][-1];require(operation['native_id']==oid and operation['linked_feature_ids']==[fid]and operation['mill_operation_type']==1 and type(operation['mill_operation_type'])is int and operation['suppressed']is False and operation['toolpath_generated']is False and exact(operation['toolpath_record_counts'],[]),'Only actual last empty Finish required')
    previous=deepcopy(before);previous['operations']=previous['operations'][:-1];creation.validate_baseline(previous)
    observed=before[EXTRA]['operation_observation'];require(observed['operation_native_id']==oid and observed['feature_native_id']==fid and observed['tool_native_id']==operation['assigned_tool']['native_id']==row['expected_tool_native_id'],'Saved observation/own tool differs')
    require(observed['defaults']['complete']is True and observed['modes']['capture_complete']is True and observed['defaults']['finish']['BottomFinOpt']is False,'Complete wall default required; no BottomFin write')
    nc=observed['modes']['nc'];require(type(nc['GetSpeedFeedMethod'])is int and nc['GetSpeedFeedMethod']==0 and nc['GetIsLockSpindleSpeed']is False and type(nc['GetCNCComp'])is int and nc['GetCNCComp']==0 and type(nc['GetTlpComp'])is int and nc['GetTlpComp']==1,'Supported observed NC mode required')
    require(type(row['changes'])is list and [x.get('field')for x in row['changes']]==list(NOMINALS),'Exact bounded ordered fields required')
    for c in row['changes']:
        require(type(c)is dict and set(c)=={'field','expected','new'},'Exact field delta required');f=fields.FIELDS[c['field']];fields.checked(f,c['expected']);fields.checked(f,c['new'])
        require(exact(fields.value_at(observed,f.path),c['expected'])and exact(c['new'],NOMINALS[c['field']]),'Expected observation or fixed new value differs')
    return deepcopy(recipe)

def expected_target(before,recipe):return fields.expected_observation(before,recipe['row'])

def project_target(raw,expected,recipe):
    out=deepcopy(raw);evidence=[]
    for change in recipe['row']['changes']:
        key=change['field']
        if key not in NUMERIC:continue
        f=fields.FIELDS[key]
        for path in(f.path,*f.echoes):
            actual=fields.value_at(out,path);want=fields.value_at(expected,path);pair=path==f.path and f.kind=='absolute_pair'
            if pair:
                fields.checked(f,actual);require(type(want)is list and want[1]is False,'Exact absolute depth pair required');a=actual[0];n=want[0]
            else:a=actual;n=want
            require(type(n)is float and n==7.1,'Original nominal7.1 required');numeric.fixed_double(a,n)
            if a.hex()!=n.hex():evidence.append(dict(field=key,path=list(path),raw=a,raw_hex=a.hex(),nominal=n,nominal_hex=n.hex(),manufacturing_tolerance_applied=False))
            fields.put(out,path,[n,False]if pair else n)
    require(exact(out,expected),'Unrequested selected parameter, mode, NC, echo or lead change');return evidence

def expected_state(before,recipe,raw_target):
    out=deepcopy(before);row=recipe['row'];oid=row['operation_native_id'];pb=out['parameter_batch'];candidate=pb['candidate_tool'];cid=candidate['generic']['native_id'];require(cid==row['existing_tool_native_id']==249,'Unchanged shared249 required')
    op=next(x for x in out['operations']if x['native_id']==oid);require(op['assigned_tool']['native_id']==row['expected_tool_native_id'],'Original own tool differs');op['assigned_tool']=deepcopy(candidate['generic'])
    consumers=[x['native_id']for x in out['operations']if x['assigned_tool']['native_id']==cid];require(set(consumers)-set(pb['candidate_consumer_ids'])<={oid},'Only new Finish consumer may grow');pb['candidate_consumer_ids']=consumers
    nc=raw_target['modes']['nc'];pb['candidate_consumers'][str(oid)]=dict(operation_native_id=oid,assigned_tool_native_id=cid,read_complete=True,feeds_compensation={k:deepcopy(nc[k])for k in('GetSpndlSpeed','XYFeed','GetCNCComp','GetTlpComp')},physical_units_qualified=False,cutting_conditions_qualified=False,tool_defaults_read=False,full_parameters_read=False)
    require(set(pb['candidate_consumers'])=={str(x)for x in consumers},'Exact shared consumer map required');out[EXTRA]['operation_observation']=deepcopy(raw_target);return out

def verify_full(before,after,recipe,*,saved_source=None):
    oid=recipe['row']['operation_native_id'];fid=recipe['row']['feature_native_id'];validate_recipe(recipe,before,oid,fid)
    raw=after[EXTRA]['operation_observation'];representations=project_target(raw,expected_target(before[EXTRA]['operation_observation'],recipe),recipe);expected=expected_state(before,recipe,raw);actual=deepcopy(after)
    for state in(expected,actual):
        for key in('document','sketch_state'):require(type(state[key]['needs_save'])is bool,'Strict dirty flag required');state[key]['needs_save']=False
    if saved_source is not None:
        require(after['document']['needs_save']is False and after['sketch_state']['needs_save']is False and after['sketch_state']['saved_file_sha256']==saved_source,'Clean saved source required');expected['sketch_state']['saved_file_sha256']=saved_source
    require(circular.circular_state_equal(expected,actual),'Protected29,20 paths, geometry, tool, old consumers or raw target changed')
    return dict(selected_operation_native_id=oid,protected_operations=29,protected_positive_paths=20,protected_records=83961,native_double_representations=representations,full_saved_state_verified=saved_source is not None,production_qualified=False)

def verify_compact(before,compact,recipe,before_planes):
    require(compact.get('scope')=='CIRCULAR_FINISH_COMPACT_PRE_SAVE_V1'and compact.get('full_parameter_capture')is False,'Actual targeted compact observation required')
    raw=compact['new_circle']['operation_observation'];representations=project_target(raw,expected_target(before[EXTRA]['operation_observation'],recipe),recipe);expected=expected_state(before,recipe,raw)
    for key in('operations','features','feature_setups','operation_counts','selected_operation_setup','operation_setups','operation_setup_count','operation_count','operation_inventory_scope'):require(exact(compact['inventory'][key],expected[key]),'Compact protected inventory changed: '+key)
    require(exact(compact['new_circle'],expected[EXTRA]),'New circle geometry/catalogue or observation changed')
    pair=before['selected_pair_observations'];require(exact(compact['selected_targets'],pair['targets'])and exact(compact['retained_draft'],pair['draft']),'Old selected pair/draft changed')
    require(type(compact['sketch_state'].get('needs_save'))is bool,'Strict compact sketch dirty flag required')
    require(exact(compact['shared_candidate'],before['parameter_batch']['candidate_tool']),'Shared tool profile changed');creation.circle.verify_sw(before,dict(before,sketch_state=compact['sketch_state']))
    require(exact(compact['plane_observations'],before_planes),'Floor/new Finish planes changed');return dict(targeted_presave_verified=True,full_parameter_capture=False,representation_evidence=representations,production_qualified=False)
